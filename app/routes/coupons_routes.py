# app/routes/coupons_routes.py
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    current_app,
    send_file,
)
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text
import os
import pandas as pd
import traceback
import re
from io import BytesIO
from datetime import datetime, timezone
import pytz
import logging
from fuzzywuzzy import fuzz
import numpy as np
from app.extensions import db
from app.models import (
    Coupon,
    Company,
    Tag,
    CouponUsage,
    Transaction,
    Notification,
    CouponRequest,
    GptUsage,
    CouponTransaction,
    coupon_tags,
    UserTourProgress,
)
from app.forms import (
    ProfileForm,
    SellCouponForm,
    UploadCouponsForm,
    AddCouponsBulkForm,
    CouponForm,
    DeleteCouponsForm,
    ConfirmDeleteForm,
    MarkCouponAsUsedForm,
    EditCouponForm,
    ApproveTransactionForm,
    SMSInputForm,
    UpdateCouponUsageForm,
    DeleteCouponForm,
    UploadImageForm,
    DeleteCouponRequestForm,
    RateUserForm,
)
from app.helpers import (
    update_coupon_status,
    get_coupon_data,
    process_coupons_excel,
    extract_coupon_detail_sms,
    extract_coupon_detail_image_proccess,
    send_email,
    get_most_common_tag_for_company,
    get_geo_location,
    get_public_ip,
    update_coupon_usage,
)
from flask import session

logger = logging.getLogger(__name__)

coupons_bp = Blueprint("coupons", __name__)


def to_israel_time_filter(dt):
    """Converts UTC datetime to Israel time and formats as string."""
    if not dt:
        return ""
    israel = pytz.timezone("Asia/Jerusalem")
    return dt.replace(tzinfo=pytz.utc).astimezone(israel).strftime("%d/%m/%Y %H:%M:%S")


def add_coupon_transaction(coupon):
    """
    When creating a new coupon, we add a coupon_transaction record.
    To prevent two different records from being created during editing,
    it is recommended to always keep the same reference_number value here (e.g., 'Initial').
    """
    new_transaction = CouponTransaction(
        coupon_id=coupon.id,
        transaction_date=datetime.utcnow(),
        recharge_amount=coupon.value,
        usage_amount=0,
        location="הוזן באופן ידני",
        reference_number="Initial",
        source="User",
    )
    db.session.add(new_transaction)
    db.session.commit()


from sqlalchemy import text


def log_user_activity(action, coupon_id=None):
    try:
        # ip_address = request.remote_addr  # קבלת כתובת ה-IP האמיתית
        ip_address = None

        user_id = current_user.id if current_user.is_authenticated else None

        # 🔹 בדיקת ההסכמה האחרונה של המשתמש (רק לפי user_id) 🔹
        consent_check_query = """
            SELECT consent_status FROM user_consents 
            WHERE user_id = :user_id 
            ORDER BY timestamp DESC LIMIT 1
        """
        result = db.session.execute(
            text(consent_check_query), {"user_id": user_id}
        ).fetchone()

        if (
            not result or not result[0]
        ):  # אם אין הסכמה או שהיא false, לא נמשיך לרשום את הפעולה
            return

        # שליפת נתוני מיקום (אם רלוונטי)
        geo_data = get_geo_location(ip_address)

        activity = {
            "user_id": user_id,
            "coupon_id": coupon_id,
            "timestamp": datetime.utcnow(),
            "action": action,
            "device": request.headers.get("User-Agent", "")[:50],
            "browser": request.headers.get("User-Agent", "").split(" ")[0][:50]
            if request.headers.get("User-Agent", "")
            else None,
            "ip_address": ip_address[:45] if ip_address else None,
            "city": geo_data.get("city"),
            "region": geo_data.get("region"),
            "country": geo_data.get("country"),
        }

        db.session.execute(
            text(
                """
                INSERT INTO user_activities
                (user_id, coupon_id, timestamp, action, device, browser, ip_address, city, region, country)
                VALUES
                (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :city, :region, :country)
            """
            ),
            activity,
        )
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging activity [{action}]: {e}")


@coupons_bp.route("/sell_coupon", methods=["GET", "POST"])
@login_required
def sell_coupon():
    """
    Endpoint for selling a coupon. Allows entering coupon details,
    automatically calculates the discount percentage,
    and adds a tag automatically based on the company name (if found).
    There is no manual option for selecting a tag.
    """
    # -- activity log snippet --
    # log_user_activity("sell_coupon_view", None)

    form = SellCouponForm()

    # Fetch only companies (no need to fetch tags for manual selection)
    companies = Company.query.order_by(Company.name).all()

    # Prepare a list of options for company selection
    company_choices = [("", "בחר חברה")]
    company_choices += [(str(company.id), company.name) for company in companies]
    company_choices.append(("other", "אחר"))
    form.company_select.choices = company_choices

    if form.validate_on_submit():
        # Collect data from the form
        expiration = form.expiration.data
        purpose = (
            form.purpose.data.strip()
            if form.is_one_time.data and form.purpose.data
            else None
        )

        # Convert input from the form
        try:
            face_value = float(form.cost.data)  # כמה הקופון שווה בפועל
        except:
            face_value = 0.0

        try:
            asked_price = float(form.value.data)  # כמה המשתמש רוצה לקבל
        except:
            asked_price = 0.0

        # Calculate discount percentage
        if face_value > 0:
            discount_percentage = ((face_value - asked_price) / face_value) * 100
        else:
            discount_percentage = 0.0

        # Handle company selection
        selected_company_id = form.company_select.data
        if selected_company_id == "":
            flash("יש לבחור חברה.", "danger")
            return redirect(url_for("coupons.sell_coupon"))

        elif selected_company_id == "other":
            company_name = form.other_company.data.strip()
            if not company_name:
                flash("יש להזין שם חברה חדשה.", "danger")
                return redirect(url_for("coupons.sell_coupon"))

            existing_company = Company.query.filter_by(name=company_name).first()
            if existing_company:
                company = existing_company
            else:
                company = Company(name=company_name)
                db.session.add(company)
                try:
                    db.session.commit()
                    flash(f'החברה "{company_name}" נוספה בהצלחה.', "success")
                except IntegrityError:
                    db.session.rollback()
                    flash("שגיאה בעת הוספת החברה. ייתכן שהחברה כבר קיימת.", "danger")
                    return redirect(url_for("coupons.sell_coupon"))
        else:
            company = Company.query.get(int(selected_company_id))
            if not company:
                flash("החברה שנבחרה אינה תקפה.", "danger")
                return redirect(url_for("coupons.sell_coupon"))

        # Create a coupon object (without discount_percentage, as it doesn't exist in the model columns)
        new_coupon = Coupon(
            code=form.code.data.strip(),
            value=face_value,  # face value
            cost=asked_price,  # user's asking price
            company=company.name,
            description=form.description.data.strip() if form.description.data else "",
            expiration=expiration,
            user_id=current_user.id,
            is_available=True,
            is_for_sale=True,
            is_one_time=form.is_one_time.data,
            purpose=purpose,
        )

        # ------------------------------------------------------------
        # Automatic tag identification based on company name
        # ------------------------------------------------------------
        chosen_company_name = company.name
        current_app.logger.info(
            f"[DEBUG] sell_coupon => chosen_company = '{chosen_company_name}'"
        )

        # Retrieve the most common tag for the chosen company
        found_tag = get_most_common_tag_for_company(
            chosen_company_name
        )  # וודא שהפונקציה מחזירה ערך
        if found_tag:
            # current_app.logger.info(f"[DEBUG] sell_coupon => auto found_tag = '{found_tag.name}'")
            pass
        else:
            # current_app.logger.info("[DEBUG] sell_coupon => auto found_tag = 'None'")
            pass

        # If a matching tag is found, add it to the coupon
        if found_tag:
            new_coupon.tags.append(found_tag)

        # שמירה ב־DB
        db.session.add(new_coupon)
        try:
            db.session.commit()
            add_coupon_transaction(new_coupon)  # ✅ הוספת רשומה לטבלת CouponTransaction

            try:
                new_activity = {
                    "user_id": current_user.id,
                    "coupon_id": new_coupon.id,
                    "timestamp": datetime.utcnow(),
                    "action": "sell_coupon_created",
                    "device": request.headers.get("User-Agent", "")[:50],
                    "browser": request.headers.get("User-Agent", "").split(" ")[0][:50]
                    if request.headers.get("User-Agent", "")
                    else None,
                    "ip_address": ip_address[:45] if ip_address else None,
                    "geo_location": get_geo_location(ip_address)[:100],
                }
                db.session.execute(
                    text(
                        """
                        INSERT INTO user_activities
                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                        VALUES
                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                    """
                    ),
                    new_activity,
                )
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Error logging activity [sell_coupon_created]: {e}"
                )

            flash("קופון למכירה נוסף בהצלחה!", "success")
            return redirect(url_for("coupons.show_coupons"))

        except IntegrityError:
            db.session.rollback()
            flash("קוד הקופון כבר קיים. אנא בחר קוד אחר.", "danger")
        except Exception as e:
            db.session.rollback()
            flash("אירעה שגיאה בעת הוספת הקופון. אנא נסה שוב מאוחר יותר.", "danger")
            current_app.logger.error(f"Error adding coupon: {e}")

    else:
        # If we reached here with a POST request and there are errors, log them
        if request.method == "POST":
            for field, errors in form.errors.items():
                for error in errors:
                    current_app.logger.error(f"Error in {field}: {error}")
            flash("יש לתקן את השגיאות בטופס.", "danger")

    return render_template("sell_coupon.html", form=form, companies=companies)


@coupons_bp.route("/coupons")
@login_required
def show_coupons():
    # log_user_activity("show_coupons", None)

    coupons = (
        Coupon.query.options(joinedload(Coupon.tags))
        .filter_by(user_id=current_user.id, is_for_sale=False)
        .all()
    )
    for coupon in coupons:
        update_coupon_status(coupon)
    db.session.commit()

    companies = Company.query.order_by(Company.name).all()
    company_logo_mapping = {c.name.lower(): c.image_path for c in companies}
    for company_name in company_logo_mapping:
        if not company_logo_mapping[company_name]:
            company_logo_mapping[company_name] = "images/default.png"

    active_coupons = [
        coupon
        for coupon in coupons
        if coupon.status == "פעיל" and not coupon.is_one_time
    ]
    active_one_time_coupons = [
        coupon for coupon in coupons if coupon.status == "פעיל" and coupon.is_one_time
    ]

    latest_usage_subquery = (
        db.session.query(
            CouponUsage.coupon_id, func.max(CouponUsage.timestamp).label("latest_usage")
        )
        .group_by(CouponUsage.coupon_id)
        .subquery()
    )

    inactive_coupons_query = (
        db.session.query(Coupon, latest_usage_subquery.c.latest_usage)
        .outerjoin(
            latest_usage_subquery, Coupon.id == latest_usage_subquery.c.coupon_id
        )
        .options(joinedload(Coupon.tags))
        .filter(
            Coupon.user_id == current_user.id,
            Coupon.status != "פעיל",
            Coupon.is_for_sale == False,
        )
        .order_by(
            latest_usage_subquery.c.latest_usage.desc().nullslast(),
            Coupon.company.asc(),
        )
    )

    inactive_coupons_with_usage = inactive_coupons_query.all()

    coupons_for_sale = (
        Coupon.query.filter_by(user_id=current_user.id, is_for_sale=True)
        .order_by(Coupon.date_added.desc())
        .all()
    )

    return render_template(
        "coupons.html",
        active_coupons=active_coupons,
        active_one_time_coupons=active_one_time_coupons,
        inactive_coupons_with_usage=inactive_coupons_with_usage,
        coupons_for_sale=coupons_for_sale,
        company_logo_mapping=company_logo_mapping,
    )


# ────────────────────────────────────────────────────────────────────────────────
# coupons_routes.py   – fixed get_tag_coupon_stats (works on PostgreSQL)
# ────────────────────────────────────────────────────────────────────────────────
from sqlalchemy import func, Numeric  # ← keep near other SQLAlchemy imports

# …


@coupons_bp.route("/tag_coupon_stats")
@login_required
def get_tag_coupon_stats():
    """
    Returns (as JSON) up‑to‑15 tags that belong to the current user, sorted by
    average saving percentage (highest→lowest).  Each row contains:

        • tag_id
        • tag_name
        • total_coupons          – how many of the user's coupons carry this tag
        • total_savings (₪)      – Σ(value‑cost) over those coupons
        • avg_savings_percentage – mean( (value‑cost)/value * 100 )  rounded to 2dp
    """
    try:
        # ── 1. build the % expression once, keeps the query readable ───────────
        percent_expr = (
            (Coupon.value - Coupon.cost)
            / func.nullif(Coupon.value, 0)
            * 100  # prevent divide‑by‑0
        )

        # ── 2. construct the ORM query – no raw SQL, portable across DBs ──────
        avg_savings_percentage = func.coalesce(
            func.round(
                func.avg(percent_expr.cast(Numeric)),  # cast → NUMERIC so round() works
                2,
            ),
            0,
        ).label("avg_savings_percentage")

        qry = (
            db.session.query(
                Tag.id.label("tag_id"),
                Tag.name.label("tag_name"),
                func.count(Coupon.id.distinct()).label("total_coupons"),
                func.coalesce(func.sum(Coupon.value - Coupon.cost), 0).label(
                    "total_savings"
                ),
                avg_savings_percentage,
            )
            .join(coupon_tags, Tag.id == coupon_tags.c.tag_id)
            .join(Coupon, Coupon.id == coupon_tags.c.coupon_id)
            .filter(Coupon.user_id == current_user.id)  # scope = this user
            .group_by(Tag.id, Tag.name)
            .having(
                func.count(Coupon.id.distinct()) >= 3
            )  # only tags with at least 3 coupons
            .order_by(avg_savings_percentage.desc())  # sort by % saving
            .limit(15)
        )

        # ── 3. materialise & jsonify ──────────────────────────────────────────
        tag_stats = [
            {
                "tag_id": row.tag_id,
                "tag_name": row.tag_name,
                "total_coupons": int(row.total_coupons),
                "total_savings": float(row.total_savings),
                "avg_savings_percentage": float(row.avg_savings_percentage),
            }
            for row in qry.all()
        ]
        return jsonify(tag_stats)

    except Exception:
        # logs full stack‑trace; response remains generic
        current_app.logger.exception("get_tag_coupon_stats failed")
        return jsonify({"error": "internal server error"}), 500


@coupons_bp.route("/upload_coupons", methods=["GET", "POST"])
@login_required
def upload_coupons():
    """
    Excel file upload screen and bulk addition of coupons for the current user.
    """
    # -- activity log snippet --
    # log_user_activity("upload_coupons_view", None)

    form = UploadCouponsForm()
    if form.validate_on_submit():
        file = form.file.data
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        try:
            # Now we receive 3 values: list of errors, list of warnings, and list of new coupons.
            (
                invalid_coupons,
                missing_optional_fields_messages,
                new_coupons,
            ) = process_coupons_excel(file_path, current_user)

            # Display warnings about missing optional fields
            for msg in missing_optional_fields_messages:
                flash(msg, "warning")

            if invalid_coupons:
                # מציג לכל משתמש הודעת שגיאה עם כל הקופונים הפגומים
                flash(
                    "הקופונים הבאים לא היו תקינים ולא נוספו:<br>"
                    + "<br>".join(invalid_coupons),
                    "danger",
                )
            else:
                # For each new coupon successfully added, create a coupon_transaction record
                for c in new_coupons:
                    add_coupon_transaction(c)

                flash("כל הקופונים נוספו בהצלחה!", "success")

        except Exception as e:
            flash("אירעה שגיאה בעת עיבוד הקובץ.", "danger")
            traceback.print_exc()

        try:
            new_activity = {
                "user_id": current_user.id,
                "coupon_id": None,
                "timestamp": datetime.utcnow(),
                "action": "upload_coupons_submit",
                "device": request.headers.get("User-Agent", "")[:50],
                "browser": request.headers.get("User-Agent", "").split(" ")[0][:50]
                if request.headers.get("User-Agent", "")
                else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": get_geo_location(ip_address)[:100],
            }
            db.session.execute(
                text(
                    """
                    INSERT INTO user_activities
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                    VALUES
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                """
                ),
                new_activity,
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error logging activity [upload_coupons_submit]: {e}"
            )

        return redirect(url_for("coupons.show_coupons"))

    return render_template("upload_coupons.html", form=form)


@coupons_bp.route("/load_coupon_modals")
@login_required
def load_coupon_modals():
    """
    Route to dynamically load the coupon modals HTML content.
    This keeps the modal code separate from the main index page.
    """
    return render_template("index_modals/coupon_modals.html")


@coupons_bp.route("/load_quick_add_coupon_modal")
@login_required
def load_quick_add_coupon_modal():
    companies = Company.query.order_by(Company.name).all()
    # Get the base URL for static files - need to pass it to construct full image paths
    static_url = url_for("static", filename="")
    return render_template(
        "index_modals/quick_add_coupon_modal.html",
        companies=companies,
        static_url=static_url,
    )


@coupons_bp.route("/load_usage_report_modal")
@login_required
def load_usage_report_modal():
    """טוען את מודל הדיווח על שימוש בקופונים"""
    usage_form = UsageExplanationForm()

    # בדוק אם יש בקשה מפורשת להציג את מסך האישור
    show_review = request.args.get("show_review", "false").lower() == "true"

    # רק אם מבקשים במפורש לראות את מסך האישור ויש נתונים בסשן
    parsed_usages = session.get("parsed_usages", [])
    review_mode = show_review and len(parsed_usages) > 0

    if review_mode:
        # דומה ללוגיקה מ-review_usage_findings
        all_user_coupons = [cpn for cpn in current_user.coupons if cpn.status == "פעיל"]
        for row in parsed_usages:
            row_company = row.get("company", "").lower()
            matched_coupons = []
            for cpn in all_user_coupons:
                similarity = fuzz.ratio(row_company, cpn.company.lower())
                remaining_balance = cpn.value - cpn.used_value
                if similarity >= 95:
                    matched_coupons.append(
                        {
                            "id": cpn.id,
                            "company": cpn.company,
                            "code": cpn.code,
                            "remaining_balance": remaining_balance,
                        }
                    )
            if matched_coupons:
                row["matched_coupons"] = matched_coupons
            else:
                row["matched_coupons"] = [
                    {
                        "id": cpn.id,
                        "company": cpn.company,
                        "code": cpn.code,
                        "remaining_balance": cpn.value - cpn.used_value,
                    }
                    for cpn in all_user_coupons
                ]

        return render_template(
            "index_modals/usage_report_modal.html",
            usage_form=usage_form,
            review_mode=review_mode,
            usage_list=parsed_usages,
        )

    # אחרת, תמיד מציג את מסך ההזנה
    return render_template(
        "index_modals/usage_report_modal.html", usage_form=usage_form, review_mode=False
    )


DEBUG_PRINT = False  # הגדר True כדי להדפיס הודעות debug, False כדי לכבות


@coupons_bp.route("/add_coupons_bulk", methods=["GET", "POST"])
@login_required
def add_coupons_bulk():
    """
    Form that allows the user to manually add multiple coupons (without uploading a file),
    and then create a temporary Excel file – which is then passed to process_coupons_excel for processing.
    """
    # הגדרת הכתובת IP והפעילות
    ip_address = None or "127.0.0.1"

    form = AddCouponsBulkForm()
    companies = Company.query.order_by(Company.name).all()
    tags = Tag.query.all()

    # ✅ SET COMPANY CHOICES FIRST – BEFORE VALIDATION!
    company_choices = [(str(company.id), company.name) for company in companies]
    company_choices.append(("other", "אחר"))
    for coupon_entry in form.coupons.entries:
        coupon_form = coupon_entry.form
        coupon_form.company_id.choices = company_choices
        if DEBUG_PRINT:
            print(f"Available company choices for a coupon: {company_choices}")

    if form.validate_on_submit():
        if DEBUG_PRINT:
            print("טופס add_coupons_bulk אומת בהצלחה")
        try:
            new_coupons_data = []
            for idx, coupon_entry in enumerate(form.coupons.entries):
                coupon_form = coupon_entry.form

                # === 1. עיבוד שם החברה (company_id / other_company) ===
                if DEBUG_PRINT:
                    print(f"Processing company for coupon #{idx + 1}")
                if coupon_form.company_id.data == "other":
                    company_name = (coupon_form.other_company.data or "").strip()
                    if not company_name:
                        flash(f"שם החברה חסר בקופון #{idx + 1}.", "danger")
                        continue
                else:
                    try:
                        company_id = int(coupon_form.company_id.data)
                        company = Company.query.get(company_id)
                        if company:
                            company_name = company.name
                        else:
                            flash(
                                f"חברה ID={company_id} לא נמצאה בקופון #{idx + 1}.",
                                "danger",
                            )
                            continue
                    except ValueError:
                        flash(f"ID החברה אינו תקין בקופון #{idx + 1}.", "danger")
                        continue

                if DEBUG_PRINT:
                    print(f"Company Name for coupon #{idx + 1}: {company_name}")

                # === 2. עיבוד ערכים בסיסיים: code, value, cost, expiration, וכו' ===
                code = coupon_form.code.data.strip()
                if DEBUG_PRINT:
                    print(f"Coupon code for coupon #{idx + 1}: {code}")
                try:
                    value = (
                        float(coupon_form.value.data) if coupon_form.value.data else 0.0
                    )
                    cost = (
                        float(coupon_form.cost.data) if coupon_form.cost.data else 0.0
                    )
                except ValueError:
                    flash(f"ערך או עלות לא תקינים בקופון #{idx+1}.", "danger")
                    continue

                expiration_str = ""
                if coupon_form.expiration.data:
                    expiration_date = coupon_form.expiration.data
                    expiration_str = expiration_date.strftime("%Y-%m-%d")
                if DEBUG_PRINT:
                    print(f"Expiration for coupon #{idx + 1}: {expiration_str}")

                is_one_time = coupon_form.is_one_time.data
                purpose = (
                    (coupon_form.purpose.data or "").strip() if is_one_time else ""
                )
                if DEBUG_PRINT:
                    print(f"One-time flag for coupon #{idx + 1}: {is_one_time}")
                    print(f"Purpose for coupon #{idx + 1}: {purpose}")

                # === 3. איתור תגית אוטומטית (כמו ב-add_coupon) ===
                found_tag = get_most_common_tag_for_company(company_name)
                if DEBUG_PRINT:
                    print(
                        f"Found tag for company {company_name}: {found_tag.name if found_tag else 'None'}"
                    )

                # === 4. הוספת CVV ותוקף כרטיס ===
                cvv = coupon_form.cvv.data.strip() if coupon_form.cvv.data else ""
                card_exp = (
                    coupon_form.card_exp.data.strip()
                    if coupon_form.card_exp.data
                    else ""
                )
                if DEBUG_PRINT:
                    print(f"CVV for coupon #{idx + 1}: {cvv}")
                    print(f"Card Expiration for coupon #{idx + 1}: {card_exp}")

                # === 5. עיבוד שדה "מאיפה קיבלת את הקופון" ===
                source = (coupon_form.source.data or "").strip()
                if DEBUG_PRINT:
                    print(f"Source for coupon #{idx + 1}: {source}")

                # === 6. עיבוד שדה "כתובת URL של הקופון ל-BuyMe" ===
                buyme_coupon_url = (
                    (coupon_form.buyme_coupon_url.data or "").strip()
                    if coupon_form.company_id.data == "54"
                    else None
                )
                if DEBUG_PRINT:
                    print(f"BuyMe URL for coupon #{idx + 1}: {buyme_coupon_url}")

                # === 7. בניית "שורת דאטה" שתלך אחר כך ל-process_coupons_excel ===
                coupon_data = {
                    "קוד קופון": code,
                    "ערך מקורי": value,
                    "עלות": cost,
                    "חברה": company_name,
                    "תיאור": "",  # ניתן להוסיף תמיכה בשדה description אם נדרש
                    "תאריך תפוגה": expiration_str,
                    "קוד לשימוש חד פעמי": is_one_time,
                    "מטרת הקופון": purpose,
                    "תגיות": found_tag.name if found_tag else "",
                    "CVV": cvv,
                    "תוקף כרטיס": card_exp,
                    "מאיפה קיבלת את הקופון": source,
                    "כתובת URL של הקופון ל-BuyMe": buyme_coupon_url,
                }
                if DEBUG_PRINT:
                    print(f"Coupon data for coupon #{idx + 1}: {coupon_data}")
                new_coupons_data.append(coupon_data)

            if new_coupons_data:
                # יצירת DataFrame וייצוא לאקסל
                df_new_coupons = pd.DataFrame(new_coupons_data)
                export_folder = "exports"
                os.makedirs(export_folder, exist_ok=True)
                export_filename = f"new_coupons_{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                export_path = os.path.join(export_folder, export_filename)
                df_new_coupons.to_excel(export_path, index=False)
                if DEBUG_PRINT:
                    print(f"Exported new coupons to {export_path}")
                    print("Exported DataFrame head:")
                    print(df_new_coupons.head())

                (
                    invalid_coupons,
                    missing_optional_fields_messages,
                    newly_created_coupons,
                ) = process_coupons_excel(export_path, current_user)

                for msg in missing_optional_fields_messages:
                    flash(msg, "warning")
                if invalid_coupons:
                    flash(
                        "הקופונים הבאים לא היו תקינים ולא נוספו:<br>"
                        + "<br>".join(invalid_coupons),
                        "danger",
                    )
                else:
                    if newly_created_coupons:
                        flash("כל הקופונים נוספו בהצלחה!", "success")
            else:
                flash("לא נוספו קופונים חדשים.", "info")
                return redirect(url_for("coupons.show_coupons"))

        except Exception as e:
            print(f"Error during bulk coupon processing: {e}")
            traceback.print_exc()
            flash("אירעה שגיאה בעת עיבוד הקופונים. אנא נסה שוב.", "danger")

        # הוספת לוג פעילות
        try:
            geo_data_str = str(get_geo_location(ip_address))
            geo_data_str = geo_data_str[:100] if geo_data_str else None

            new_activity = {
                "user_id": current_user.id,
                "coupon_id": None,
                "timestamp": datetime.utcnow(),
                "action": "add_coupons_bulk_submit",
                "device": request.headers.get("User-Agent", "")[:50],
                "browser": request.headers.get("User-Agent", "").split(" ")[0][:50]
                if request.headers.get("User-Agent", "")
                else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": geo_data_str,
            }
            db.session.execute(
                text(
                    """
                    INSERT INTO user_activities
                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                    VALUES
                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                """
                ),
                new_activity,
            )
            db.session.commit()
            if DEBUG_PRINT:
                print("Activity logged successfully.")
        except Exception as e:
            db.session.rollback()
            print(f"Error logging activity [add_coupons_bulk_submit]: {e}")

        return redirect(url_for("coupons.show_coupons"))

    else:
        if form.is_submitted():
            print("Form submitted but failed validation.")
            print(form.errors)
            for idx, entry in enumerate(form.coupons.entries):
                print(
                    f"Coupon #{idx + 1} — Code: {entry.form.code.data}, Company: {entry.form.company_id.data}, Value: {entry.form.value.data}"
                )

    return render_template(
        "add_coupons.html", form=form, companies=companies, tags=tags
    )


from flask import request, jsonify, abort
from flask_login import current_user, login_required
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
import time
import re
import pandas as pd
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from app.models import Company  # Adjust the import according to your project structure


@coupons_bp.route("/submit_buyme_coupon_urls", methods=["POST"])
@login_required
def submit_buyme_coupon_urls():
    if not current_user.is_admin:
        return jsonify({"message": "Unauthorized"}), 403

    data = request.get_json(silent=True)
    if not data or "urls" not in data:
        return jsonify({"message": "No URLs provided."}), 400

    urls = data["urls"]
    if not isinstance(urls, list) or not urls:
        return jsonify({"message": "Invalid URL list."}), 400

    coupons = []
    driver = None

    try:
        # Setup WebDriver
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        for url in urls:
            try:
                driver.get(url)
                time.sleep(6)  # Consider replacing with WebDriverWait

                page_source = driver.page_source

                # Extract coupon code
                coupon_match = re.search(r"קוד שובר:\s*([\d\s\-]+)", page_source)
                coupon_code = coupon_match.group(1).strip() if coupon_match else ""

                # Extract expiration date
                validity_match = re.search(r"בתוקף עד\s*([\d\.]+)", page_source)
                validity = validity_match.group(1).strip() if validity_match else ""
                if validity:
                    try:
                        validity_date = pd.to_datetime(validity, format="%d.%m.%Y")
                        validity_formatted = validity_date.strftime("%Y-%m-%d")
                    except Exception as e:
                        print(f"[⚠] Error parsing date: {validity} ({e})")
                        validity_formatted = validity
                else:
                    validity_formatted = ""

                # Extract coupon value
                value_match = re.search(
                    r'voucher-card__content__amount">₪<span>(\d+)</span>', page_source
                )
                coupon_value = value_match.group(1).strip() if value_match else ""

                # Build coupon dictionary
                coupons.append(
                    {
                        "url": url,
                        "coupon_code": coupon_code,
                        "validity": validity_formatted,
                        "value": coupon_value,
                        "cost": "0",
                        # Add discount_percentage with default value
                        "discount_percentage": "0",
                    }
                )

            except Exception as e:
                print(f"[❌] Error loading URL {url}: {e}")
                coupons.append(
                    {
                        "url": url,
                        "coupon_code": "",
                        "validity": "",
                        "value": "",
                        "cost": "0",
                        "discount_percentage": "0",
                        "error": str(e),
                    }
                )

    finally:
        if driver:
            driver.quit()

    form = AddCouponsBulkForm()

    print("[ℹ] Extracted Coupons:")
    for coupon in coupons:
        print(coupon)

    # Get BuyMe company ID
    buyme_company = Company.query.filter_by(name="BuyMe").first()
    buyme_company_id = str(buyme_company.id) if buyme_company else None

    # Clear existing form entries
    form.coupons.entries = []

    # Add coupons to the form with ALL required fields
    for coupon in coupons:
        # Calculate discount percentage if not available but we have value and cost
        if (
            not coupon.get("discount_percentage")
            and coupon.get("value")
            and coupon.get("cost")
        ):
            try:
                value = float(coupon["value"])
                cost = float(coupon["cost"])
                if value > 0:  # Avoid division by zero
                    discount_percentage = ((value - cost) / value) * 100
                    coupon["discount_percentage"] = str(round(discount_percentage, 2))
                else:
                    coupon["discount_percentage"] = "0"
            except (ValueError, TypeError):
                coupon["discount_percentage"] = "0"

        # Make sure code is not empty (critical field)
        if not coupon["coupon_code"]:
            print(
                f"[⚠] Warning: Empty coupon code for URL {coupon['url']}. Setting placeholder."
            )
            coupon["coupon_code"] = "BUYME-" + coupon["url"].split("/")[-1][:8]

        # Make sure we have numeric values for value and cost
        try:
            float(coupon["value"])
        except (ValueError, TypeError):
            coupon["value"] = "0"

        try:
            float(coupon["cost"])
        except (ValueError, TypeError):
            coupon["cost"] = "0"

        # Append entry with all necessary fields to satisfy validation
        form.coupons.append_entry(
            {
                "code": coupon["coupon_code"],
                "expiration": coupon["validity"],
                "buyme_coupon_url": coupon["url"],
                "company_id": buyme_company_id,  # Make sure this is set for all coupons
                "value": coupon["value"],
                "cost": coupon["cost"],
                "discount_percentage": coupon["discount_percentage"],
                # Add other fields that might be required by your form validation
                "is_one_time": False,
                "purpose": "",
                "source": "",
            }
        )

    # Add debug information
    for idx, entry in enumerate(form.coupons.entries):
        print(f"Coupon #{idx + 1} form data:")
        for field_name, field in entry.form._fields.items():
            print(f"  {field_name}: {field.data}")

    companies = Company.query.all()  # Fetch all companies
    tags = Tag.query.all()  # Add tags if your form needs them

    # Add debugging for what we're returning to the template
    print(f"Returning form with {len(form.coupons.entries)} coupon entries")

    return render_template(
        "add_coupons.html", form=form, coupons=coupons, companies=companies, tags=tags
    )


def get_most_common_tag_for_company(company_name):
    results = (
        db.session.query(Tag, func.count(Tag.id).label("tag_count"))
        .join(coupon_tags, Tag.id == coupon_tags.c.tag_id)
        .join(Coupon, Coupon.id == coupon_tags.c.coupon_id)
        .filter(func.lower(Coupon.company) == func.lower(company_name))
        .group_by(Tag.id)
        .order_by(func.count(Tag.id).desc(), Tag.id.asc())
        .all()
    )
    if results:
        # current_app.logger.info(f"[DEBUG] get_most_common_tag_for_company({company_name}) => {results}")
        return results[0][0]
    else:
        return None


@coupons_bp.route("/add_coupon_old", methods=["GET", "POST"])
@login_required
def add_coupon_old():
    # -- activity log snippet --
    # log_user_activity("add_coupon_view", None)

    try:
        manual = request.args.get("manual", "false").lower() == "true"
        sms_form = SMSInputForm()
        coupon_form = CouponForm()
        show_coupon_form = manual

        companies = Company.query.order_by(Company.name).all()
        tags = Tag.query.all()

        companies_list = [c.name for c in companies]

        coupon_form.company_id.choices = (
            [("", "בחר")]
            + [(str(company.id), company.name) for company in companies]
            + [("other", "אחר")]
        )
        coupon_form.tag_id.choices = (
            [("", "בחר")]
            + [(str(tag.id), tag.name) for tag in tags]
            + [("other", "אחר")]
        )

        if sms_form.validate_on_submit() and "sms_text" in request.form:
            sms_text = sms_form.sms_text.data
            extracted_data_df, pricing_df = extract_coupon_detail_sms(
                sms_text, companies_list
            )
            if not pricing_df.empty:
                pricing_row = pricing_df.iloc[0]
                new_usage = GptUsage(
                    user_id=current_user.id,
                    created=datetime.strptime(
                        pricing_row["created"], "%Y-%m-%d %H:%M:%S"
                    ),
                    id=pricing_row["id"],
                    object=pricing_row["object"],
                    model=pricing_row["model"],
                    prompt_tokens=int(pricing_row["prompt_tokens"]),
                    completion_tokens=int(pricing_row["completion_tokens"]),
                    total_tokens=int(pricing_row["total_tokens"]),
                    cost_usd=float(pricing_row["cost_usd"]),
                    cost_ils=float(pricing_row["cost_ils"]),
                    exchange_rate=float(pricing_row["exchange_rate"]),
                    # prompt_text=str(pricing_row['prompt_text']),
                    # response_text=str(pricing_row['response_text']),
                    prompt_text=np.nan,
                    response_text=np.nan,
                )
                db.session.add(new_usage)
                db.session.commit()

            if not extracted_data_df.empty:
                extracted_data = extracted_data_df.iloc[0].to_dict()
                company_name = extracted_data.get("חברה", "").strip()
                best_match_ratio = 0
                best_company = None
                for comp in companies:
                    ratio = fuzz.token_set_ratio(company_name, comp.name)
                    if ratio > best_match_ratio:
                        best_match_ratio = ratio
                        best_company = comp

                if best_company and best_match_ratio >= 90:
                    coupon_form.company_id.data = str(best_company.id)
                    coupon_form.other_company.data = ""
                    chosen_company_name = best_company.name
                else:
                    coupon_form.company_id.data = "other"
                    coupon_form.other_company.data = company_name
                    chosen_company_name = company_name

                coupon_form.code.data = extracted_data.get("קוד קופון")
                coupon_form.cost.data = extracted_data.get("עלות", 0) or 0
                try:
                    if extracted_data.get("תאריך תפוגה"):
                        coupon_form.expiration.data = datetime.strptime(
                            extracted_data["תאריך תפוגה"], "%Y-%m-%d"
                        ).date()
                except Exception as e:
                    current_app.logger.error(f"[ERROR] parsing expiration date: {e}")

                coupon_form.is_one_time.data = bool(
                    extracted_data.get("קוד לשימוש חד פעמי")
                )
                coupon_form.purpose.data = extracted_data.get("מטרת הקופון", "")
                coupon_form.description.data = extracted_data.get("תיאור", "")
                coupon_form.value.data = extracted_data.get("ערך מקורי", 0) or 0
                coupon_form.discount_percentage.data = 0

                if current_user.slots_automatic_coupons > 0:
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                else:
                    flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                    return redirect(url_for("coupons.add_coupon"))

                # current_app.logger.info(f"[DEBUG] Sending to get_most_common_tag_for_company => '{chosen_company_name}'")
                found_tag = get_most_common_tag_for_company(chosen_company_name)
                current_app.logger.info(
                    f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'"
                )
                if found_tag:
                    tag_id = found_tag.id
                    tag_name = found_tag.name
                    # current_app.logger.info(
                    # f"[DEBUG] Received tag => '{tag_name}' (ID: {tag_id}) for company '{chosen_company_name}'")
                else:
                    current_app.logger.info(
                        f"[DEBUG] No tag found for company '{chosen_company_name}'"
                    )

                if found_tag:
                    coupon_form.tag_id.data = str(found_tag.id)
                    coupon_form.other_tag.data = ""

                # -- activity log add_coupon_via_sms --
                # log_user_activity("add_coupon_via_sms", None)

                show_coupon_form = True
            else:
                flash("לא נמצאו נתונים בהודעת ה-SMS.", "danger")

            return render_template(
                "add_coupon.html",
                coupon_form=coupon_form,
                sms_form=sms_form,
                show_coupon_form=show_coupon_form,
                companies=companies,
                tags=tags,
            )

        if request.method == "POST":
            if "upload_image" in request.form and coupon_form.upload_image.data:
                image_file = coupon_form.coupon_image.data
                if image_file and image_file.filename != "":
                    try:
                        flash("מתחיל בעיבוד התמונה...", "info")
                        upload_folder = current_app.config.get(
                            "UPLOAD_FOLDER", "uploads"
                        )
                        if not os.path.exists(upload_folder):
                            os.makedirs(upload_folder)
                            flash(f"התקייה {upload_folder} נוצרה.", "info")

                        image_path = os.path.join(upload_folder, image_file.filename)
                        image_file.save(image_path)
                        flash(f"התמונה נשמרה ב-{image_path}.", "success")

                        if not companies_list:
                            flash(
                                "רשימת החברות ריקה. ודא שישנן חברות במערכת.", "warning"
                            )
                            return render_template(
                                "add_coupon.html",
                                coupon_form=coupon_form,
                                sms_form=sms_form,
                                show_coupon_form=show_coupon_form,
                                companies=companies,
                                tags=tags,
                            )

                        coupon_df, pricing_df = extract_coupon_detail_image_proccess(
                            client_id=os.getenv("IMGUR_CLIENT_ID"),
                            image_path=image_path,
                            companies_list=companies_list,
                        )
                        flash(
                            "הפונקציה extract_coupon_detail_image_proccess הסתיימה.",
                            "info",
                        )

                        if not coupon_df.empty:
                            flash("הופקו פרטי הקופון בהצלחה.", "success")

                            extracted_company = coupon_df.loc[0, "חברה"]
                            best_match_ratio = 0
                            best_company = None
                            for comp in companies:
                                ratio = fuzz.token_set_ratio(
                                    extracted_company, comp.name
                                )
                                if ratio > best_match_ratio:
                                    best_match_ratio = ratio
                                    best_company = comp

                            if best_company and best_match_ratio >= 90:
                                coupon_form.company_id.data = str(best_company.id)
                                coupon_form.other_company.data = ""
                                chosen_company_name = best_company.name
                            else:
                                coupon_form.company_id.data = "other"
                                coupon_form.other_company.data = extracted_company
                                chosen_company_name = extracted_company

                            coupon_form.code.data = coupon_df.loc[0, "קוד קופון"]
                            coupon_form.cost.data = (
                                coupon_df.loc[0, "עלות"]
                                if pd.notnull(coupon_df.loc[0, "עלות"])
                                else 0
                            )
                            coupon_form.value.data = (
                                coupon_df.loc[0, "ערך מקורי"]
                                if pd.notnull(coupon_df.loc[0, "ערך מקורי"])
                                else 0
                            )
                            coupon_form.discount_percentage.data = (
                                coupon_df.loc[0, "אחוז הנחה"]
                                if pd.notnull(coupon_df.loc[0, "אחוז הנחה"])
                                else 0
                            )
                            try:
                                expiration_val = coupon_df.loc[0, "תאריך תפוגה"]
                                if pd.notnull(expiration_val):
                                    coupon_form.expiration.data = pd.to_datetime(
                                        expiration_val
                                    ).date()
                            except Exception as e:
                                current_app.logger.error(
                                    f"[ERROR] parsing expiration date from image: {e}"
                                )

                            coupon_form.description.data = (
                                coupon_df.loc[0, "תיאור"]
                                if pd.notnull(coupon_df.loc[0, "תיאור"])
                                else ""
                            )
                            coupon_form.is_one_time.data = False
                            coupon_form.purpose.data = ""

                            if current_user.slots_automatic_coupons > 0:
                                current_user.slots_automatic_coupons -= 1
                                db.session.commit()
                            else:
                                flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                                return redirect(url_for("coupons.add_coupon"))

                            # current_app.logger.info(f"[DEBUG] Sending to get_most_common_tag_for_company => '{chosen_company_name}'")
                            found_tag = get_most_common_tag_for_company(
                                chosen_company_name
                            )
                            current_app.logger.info(
                                f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'"
                            )
                            if found_tag:
                                tag_id = found_tag.id
                                tag_name = found_tag.name
                                # current_app.logger.info(
                                # f"[DEBUG] Received tag => '{tag_name}' (ID: {tag_id}) for company '{chosen_company_name}'")
                            else:
                                current_app.logger.info(
                                    f"[DEBUG] No tag found for company '{chosen_company_name}'"
                                )

                            if found_tag:
                                coupon_form.tag_id.data = str(found_tag.id)
                                coupon_form.other_tag.data = ""

                            # -- activity log snippet --
                            try:
                                new_activity = {
                                    "user_id": current_user.id,
                                    "coupon_id": None,
                                    "timestamp": datetime.utcnow(),
                                    "action": "add_coupon_via_image_upload",
                                    "device": request.headers.get("User-Agent", "")[
                                        :50
                                    ],
                                    "browser": request.headers.get(
                                        "User-Agent", ""
                                    ).split(" ")[0][:50]
                                    if request.headers.get("User-Agent", "")
                                    else None,
                                    "ip_address": ip_address[:45]
                                    if ip_address
                                    else None,
                                    "geo_location": get_geo_location(ip_address)[:100],
                                }
                                db.session.execute(
                                    text(
                                        """
                                        INSERT INTO user_activities
                                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                                        VALUES
                                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                                    """
                                    ),
                                    new_activity,
                                )
                                db.session.commit()
                            except Exception as e:
                                db.session.rollback()
                                current_app.logger.error(
                                    f"Error logging activity [add_coupon_via_image_upload]: {e}"
                                )
                            # -- end snippet --

                            show_coupon_form = True
                            flash(
                                "הטופס מולא בהצלחה. אנא בדוק וערוך אם נדרש.", "success"
                            )
                        else:
                            flash("לא ניתן היה לחלץ פרטי קופון מהתמונה.", "danger")
                    except Exception as e:
                        current_app.logger.error(f"[ERROR] processing image: {e}")
                        traceback.print_exc()
                        flash(
                            "אירעה שגיאה בעת עיבוד התמונה. אנא נסה שוב מאוחר יותר.",
                            "danger",
                        )
                else:
                    flash("חובה להעלות תמונה.", "danger")

                return render_template(
                    "add_coupon.html",
                    coupon_form=coupon_form,
                    sms_form=sms_form,
                    show_coupon_form=show_coupon_form,
                    companies=companies,
                    tags=tags,
                )

            elif "submit_coupon" in request.form and coupon_form.submit_coupon.data:
                # current_app.logger.info("[DEBUG] Manual flow - user pressed submit_coupon")
                if coupon_form.validate_on_submit():
                    code = coupon_form.code.data.strip()
                    try:
                        value = (
                            float(coupon_form.value.data)
                            if coupon_form.value.data
                            else 0
                        )
                    except Exception as e:
                        current_app.logger.error(
                            f"[ERROR] converting value to float: {e}"
                        )
                        value = 0
                    try:
                        cost = (
                            float(coupon_form.cost.data) if coupon_form.cost.data else 0
                        )
                    except Exception as e:
                        current_app.logger.error(
                            f"[ERROR] converting cost to float: {e}"
                        )
                        cost = 0

                    description = (coupon_form.description.data or "").strip()
                    expiration = coupon_form.expiration.data or None
                    is_one_time = coupon_form.is_one_time.data
                    purpose = (
                        coupon_form.purpose.data.strip() if is_one_time else ""
                    ) or None
                    source = coupon_form.source.data.strip()  # הוספתי את שדה המקור

                    selected_company_id = coupon_form.company_id.data
                    other_company_name = (coupon_form.other_company.data or "").strip()

                    if selected_company_id == "other":
                        if not other_company_name:
                            flash("יש להזין שם חברה חדשה.", "danger")
                            return redirect(
                                url_for("coupons.add_coupon", manual="true")
                            )
                        existing_company = Company.query.filter_by(
                            name=other_company_name
                        ).first()
                        if existing_company:
                            company = existing_company
                        else:
                            company = Company(
                                name=other_company_name, image_path="default_logo.png"
                            )
                            db.session.add(company)
                            db.session.flush()
                    else:
                        try:
                            selected_company_id = int(selected_company_id)
                            company = Company.query.get(selected_company_id)
                            if not company:
                                flash("חברה נבחרה אינה תקפה.", "danger")
                                return redirect(
                                    url_for("coupons.add_coupon", manual="true")
                                )
                        except (ValueError, TypeError):
                            flash("חברה נבחרה אינה תקפה.", "danger")
                            return redirect(
                                url_for("coupons.add_coupon", manual="true")
                            )

                    if current_user.slots_automatic_coupons <= 0:
                        flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                        return redirect(url_for("coupons.add_coupon", manual="true"))

                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()

                    new_coupon = Coupon(
                        code=code,
                        value=value,
                        cost=cost,
                        company=company.name,
                        description=description,
                        expiration=expiration,
                        user_id=current_user.id,
                        is_one_time=is_one_time,
                        purpose=purpose,
                        source=source,  # שדה המקור
                    )

                    # Assign the BuyMe Coupon URL from the form (it will be encrypted upon saving)
                    new_coupon.buyme_coupon_url = (
                        coupon_form.buyme_coupon_url.data.strip()
                        if coupon_form.buyme_coupon_url.data
                        else None
                    )

                    chosen_company_name = company.name
                    # current_app.logger.info(f"[DEBUG] Manual flow => chosen_company_name = '{chosen_company_name}'")
                    found_tag = get_most_common_tag_for_company(chosen_company_name)
                    # current_app.logger.info(f"[DEBUG] Manual flow => auto found_tag = '{found_tag}'")

                    if found_tag:
                        new_coupon.tags.append(found_tag)

                    db.session.add(new_coupon)

                    try:
                        db.session.commit()
                        # Add a row to coupon_transaction
                        add_coupon_transaction(new_coupon)

                        # -- activity log snippet --
                        try:
                            new_activity = {
                                "user_id": current_user.id,
                                "coupon_id": new_coupon.id,
                                "timestamp": datetime.utcnow(),
                                "action": "add_coupon_manual_submit",
                                "device": request.headers.get("User-Agent", "")[:50],
                                "browser": request.headers.get("User-Agent", "").split(
                                    " "
                                )[0][:50]
                                if request.headers.get("User-Agent", "")
                                else None,
                                "ip_address": ip_address[:45] if ip_address else None,
                                "geo_location": get_geo_location(ip_address)[:100],
                            }
                            db.session.execute(
                                text(
                                    """
                                    INSERT INTO user_activities
                                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                                    VALUES
                                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                                """
                                ),
                                new_activity,
                            )
                            db.session.commit()
                        except Exception as e:
                            db.session.rollback()
                            current_app.logger.error(
                                f"Error logging activity [add_coupon_manual_submit]: {e}"
                            )

                        flash("קופון נוסף בהצלחה!", "success")
                        return redirect(url_for("coupons.show_coupons"))
                    except IntegrityError as e:
                        db.session.rollback()
                        current_app.logger.error(
                            f"[ERROR] IntegrityError adding coupon: {e}"
                        )
                        flash("קוד קופון זה כבר קיים. אנא בחר קוד אחר.", "danger")
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.error(f"[ERROR] Error adding coupon: {e}")
                        flash("אירעה שגיאה בעת הוספת הקופון. נסה שוב.", "danger")
                else:
                    flash("הטופס אינו תקין. אנא בדוק את הנתונים שהזנת.", "danger")

        return render_template(
            "add_coupon.html",
            coupon_form=coupon_form,
            sms_form=sms_form,
            show_coupon_form=show_coupon_form,
            companies=companies,
            tags=tags,
        )
    except Exception as e:
        current_app.logger.error(f"[ERROR] Unhandled exception in add_coupon: {e}")
        traceback.print_exc()
        flash("אירעה שגיאה בלתי צפויה. אנא נסה שוב מאוחר יותר.", "danger")
        return redirect(url_for("coupons.add_coupon"))


@coupons_bp.route("/add_coupon_old_12042025", methods=["GET", "POST"])
@login_required
def add_coupon_old_12042025():
    # Log activity snippet (commented out)
    # log_user_activity("add_coupon_view", None)
    try:
        manual = request.args.get("manual", "false").lower() == "true"
        sms_form = SMSInputForm()
        coupon_form = CouponForm()
        show_coupon_form = manual

        companies = Company.query.order_by(Company.name).all()
        tags = Tag.query.all()

        companies_list = [c.name for c in companies]

        coupon_form.company_id.choices = (
            [("", "בחר")]
            + [(str(company.id), company.name) for company in companies]
            + [("other", "אחר")]
        )
        coupon_form.tag_id.choices = (
            [("", "בחר")]
            + [(str(tag.id), tag.name) for tag in tags]
            + [("other", "אחר")]
        )

        # Process SMS submission
        if sms_form.validate_on_submit() and "sms_text" in request.form:
            sms_text = sms_form.sms_text.data
            extracted_data_df, pricing_df = extract_coupon_detail_sms(
                sms_text, companies_list
            )
            if not pricing_df.empty:
                pricing_row = pricing_df.iloc[0]
                new_usage = GptUsage(
                    user_id=current_user.id,
                    created=datetime.strptime(
                        pricing_row["created"], "%Y-%m-%d %H:%M:%S"
                    ),
                    id=pricing_row["id"],
                    object=pricing_row["object"],
                    model=pricing_row["model"],
                    prompt_tokens=int(pricing_row["prompt_tokens"]),
                    completion_tokens=int(pricing_row["completion_tokens"]),
                    total_tokens=int(pricing_row["total_tokens"]),
                    cost_usd=float(pricing_row["cost_usd"]),
                    cost_ils=float(pricing_row["cost_ils"]),
                    exchange_rate=float(pricing_row["exchange_rate"]),
                    prompt_text=np.nan,
                    response_text=np.nan,
                )
                db.session.add(new_usage)
                db.session.commit()

            if not extracted_data_df.empty:
                extracted_data = extracted_data_df.iloc[0].to_dict()
                company_name = extracted_data.get("חברה", "").strip()
                best_match_ratio = 0
                best_company = None
                for comp in companies:
                    ratio = fuzz.token_set_ratio(company_name, comp.name)
                    if ratio > best_match_ratio:
                        best_match_ratio = ratio
                        best_company = comp

                if best_company and best_match_ratio >= 90:
                    coupon_form.company_id.data = str(best_company.id)
                    coupon_form.other_company.data = ""
                    chosen_company_name = best_company.name
                else:
                    coupon_form.company_id.data = "other"
                    coupon_form.other_company.data = company_name
                    chosen_company_name = company_name

                coupon_form.code.data = extracted_data.get("קוד קופון")
                coupon_form.cost.data = extracted_data.get("עלות", 0) or 0
                try:
                    if extracted_data.get("תאריך תפוגה"):
                        coupon_form.expiration.data = datetime.strptime(
                            extracted_data["תאריך תפוגה"], "%Y-%m-%d"
                        ).date()
                except Exception as e:
                    current_app.logger.error(f"[ERROR] parsing expiration date: {e}")

                coupon_form.is_one_time.data = bool(
                    extracted_data.get("קוד לשימוש חד פעמי")
                )
                coupon_form.purpose.data = extracted_data.get("מטרת הקופון", "")
                coupon_form.description.data = extracted_data.get("תיאור", "")
                coupon_form.value.data = extracted_data.get("ערך מקורי", 0) or 0
                coupon_form.discount_percentage.data = 0

                if current_user.slots_automatic_coupons > 0:
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                else:
                    flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                    return redirect(url_for("coupons.add_coupon"))

                found_tag = get_most_common_tag_for_company(chosen_company_name)
                current_app.logger.info(
                    f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'"
                )
                if found_tag:
                    coupon_form.tag_id.data = str(found_tag.id)
                    coupon_form.other_tag.data = ""

                show_coupon_form = True
            else:
                flash("לא נמצאו נתונים בהודעת ה-SMS.", "danger")

            return render_template(
                "add_coupon.html",
                coupon_form=coupon_form,
                sms_form=sms_form,
                show_coupon_form=show_coupon_form,
                companies=companies,
                tags=tags,
            )

        # Process POST request (image upload or manual coupon submission)
        if request.method == "POST":
            if "upload_image" in request.form and coupon_form.upload_image.data:
                image_file = coupon_form.coupon_image.data
                if image_file and image_file.filename != "":
                    try:
                        flash("Starting image processing...", "info")
                        upload_folder = current_app.config.get(
                            "UPLOAD_FOLDER", "uploads"
                        )
                        if not os.path.exists(upload_folder):
                            os.makedirs(upload_folder)
                            flash(f"Folder {upload_folder} created.", "info")

                        image_path = os.path.join(upload_folder, image_file.filename)
                        image_file.save(image_path)
                        flash(f"Image saved to {image_path}.", "success")

                        if not companies_list:
                            flash(
                                "Company list is empty. Ensure companies exist in the system.",
                                "warning",
                            )
                            return render_template(
                                "add_coupon.html",
                                coupon_form=coupon_form,
                                sms_form=sms_form,
                                show_coupon_form=show_coupon_form,
                                companies=companies,
                                tags=tags,
                            )

                        coupon_df, pricing_df = extract_coupon_detail_image_proccess(
                            client_id=os.getenv("IMGUR_CLIENT_ID"),
                            image_path=image_path,
                            companies_list=companies_list,
                        )
                        flash("extract_coupon_detail_image_proccess completed.", "info")

                        if not coupon_df.empty:
                            flash("Coupon details extracted successfully.", "success")

                            extracted_company = coupon_df.loc[0, "חברה"]
                            best_match_ratio = 0
                            best_company = None
                            for comp in companies:
                                ratio = fuzz.token_set_ratio(
                                    extracted_company, comp.name
                                )
                                if ratio > best_match_ratio:
                                    best_match_ratio = ratio
                                    best_company = comp

                            if best_company and best_match_ratio >= 90:
                                coupon_form.company_id.data = str(best_company.id)
                                coupon_form.other_company.data = ""
                                chosen_company_name = best_company.name
                            else:
                                coupon_form.company_id.data = "other"
                                coupon_form.other_company.data = extracted_company
                                chosen_company_name = extracted_company

                            coupon_form.code.data = coupon_df.loc[0, "קוד קופון"]
                            coupon_form.cost.data = (
                                coupon_df.loc[0, "עלות"]
                                if pd.notnull(coupon_df.loc[0, "עלות"])
                                else 0
                            )
                            coupon_form.value.data = (
                                coupon_df.loc[0, "ערך מקורי"]
                                if pd.notnull(coupon_df.loc[0, "ערך מקורי"])
                                else 0
                            )
                            coupon_form.discount_percentage.data = (
                                coupon_df.loc[0, "אחוז הנחה"]
                                if pd.notnull(coupon_df.loc[0, "אחוז הנחה"])
                                else 0
                            )
                            try:
                                expiration_val = coupon_df.loc[0, "תאריך תפוגה"]
                                if pd.notnull(expiration_val):
                                    coupon_form.expiration.data = pd.to_datetime(
                                        expiration_val
                                    ).date()
                            except Exception as e:
                                current_app.logger.error(
                                    f"[ERROR] parsing expiration date from image: {e}"
                                )

                            coupon_form.description.data = (
                                coupon_df.loc[0, "תיאור"]
                                if pd.notnull(coupon_df.loc[0, "תיאור"])
                                else ""
                            )
                            coupon_form.is_one_time.data = False
                            coupon_form.purpose.data = ""

                            if current_user.slots_automatic_coupons > 0:
                                current_user.slots_automatic_coupons -= 1
                                db.session.commit()
                            else:
                                flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                                return redirect(url_for("coupons.add_coupon"))

                            found_tag = get_most_common_tag_for_company(
                                chosen_company_name
                            )
                            current_app.logger.info(
                                f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'"
                            )
                            if found_tag:
                                coupon_form.tag_id.data = str(found_tag.id)
                                coupon_form.other_tag.data = ""

                            try:
                                new_activity = {
                                    "user_id": current_user.id,
                                    "coupon_id": None,
                                    "timestamp": datetime.utcnow(),
                                    "action": "add_coupon_via_image_upload",
                                    "device": request.headers.get("User-Agent", "")[
                                        :50
                                    ],
                                    "browser": request.headers.get(
                                        "User-Agent", ""
                                    ).split(" ")[0][:50]
                                    if request.headers.get("User-Agent", "")
                                    else None,
                                    "ip_address": ip_address[:45]
                                    if ip_address
                                    else None,
                                    "geo_location": get_geo_location(ip_address)[:100],
                                }
                                db.session.execute(
                                    text(
                                        """
                                        INSERT INTO user_activities
                                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                                        VALUES
                                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                                    """
                                    ),
                                    new_activity,
                                )
                                db.session.commit()
                            except Exception as e:
                                db.session.rollback()
                                current_app.logger.error(
                                    f"Error logging activity [add_coupon_via_image_upload]: {e}"
                                )

                            show_coupon_form = True
                            flash(
                                "Form populated successfully. Please check and edit if necessary.",
                                "success",
                            )
                        else:
                            flash(
                                "Could not extract coupon details from image.", "danger"
                            )
                    except Exception as e:
                        current_app.logger.error(f"[ERROR] processing image: {e}")
                        traceback.print_exc()
                        flash(
                            "An error occurred while processing the image. Please try again later.",
                            "danger",
                        )
                else:
                    flash("Image is required.", "danger")
                return render_template(
                    "add_coupon.html",
                    coupon_form=coupon_form,
                    sms_form=sms_form,
                    show_coupon_form=show_coupon_form,
                    companies=companies,
                    tags=tags,
                )
            elif "submit_coupon" in request.form and coupon_form.submit_coupon.data:
                # Manual flow - user pressed submit_coupon
                if coupon_form.validate_on_submit():
                    code = coupon_form.code.data.strip()
                    try:
                        value = (
                            float(coupon_form.value.data)
                            if coupon_form.value.data
                            else 0
                        )
                    except Exception as e:
                        current_app.logger.error(
                            f"[ERROR] converting value to float: {e}"
                        )
                        value = 0
                    try:
                        cost = (
                            float(coupon_form.cost.data) if coupon_form.cost.data else 0
                        )
                    except Exception as e:
                        current_app.logger.error(
                            f"[ERROR] converting cost to float: {e}"
                        )
                        cost = 0
                    description = (coupon_form.description.data or "").strip()
                    expiration = coupon_form.expiration.data or None
                    is_one_time = coupon_form.is_one_time.data
                    purpose = (
                        coupon_form.purpose.data.strip() if is_one_time else ""
                    ) or None
                    source = coupon_form.source.data.strip()  # Source field
                    selected_company_id = coupon_form.company_id.data
                    other_company_name = (coupon_form.other_company.data or "").strip()
                    if selected_company_id == "other":
                        if not other_company_name:
                            flash("יש להזין שם חברה חדשה.", "danger")
                            return redirect(
                                url_for("coupons.add_coupon", manual="true")
                            )
                        existing_company = Company.query.filter_by(
                            name=other_company_name
                        ).first()
                        if existing_company:
                            company = existing_company
                        else:
                            company = Company(
                                name=other_company_name, image_path="default_logo.png"
                            )
                            db.session.add(company)
                            db.session.flush()
                    else:
                        try:
                            selected_company_id = int(selected_company_id)
                            company = Company.query.get(selected_company_id)
                            if not company:
                                flash("חברה נבחרה אינה תקפה.", "danger")
                                return redirect(
                                    url_for("coupons.add_coupon", manual="true")
                                )
                        except (ValueError, TypeError):
                            flash("חברה נבחרה אינה תקפה.", "danger")
                            return redirect(
                                url_for("coupons.add_coupon", manual="true")
                            )
                    if current_user.slots_automatic_coupons <= 0:
                        flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                        return redirect(url_for("coupons.add_coupon", manual="true"))
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                    new_coupon = Coupon(
                        code=code,
                        value=value,
                        cost=cost,
                        company=company.name,
                        description=description,
                        expiration=expiration,
                        user_id=current_user.id,
                        is_one_time=is_one_time,
                        purpose=purpose,
                        source=source,  # Source field
                    )
                    new_coupon.buyme_coupon_url = (
                        coupon_form.buyme_coupon_url.data.strip()
                        if coupon_form.buyme_coupon_url.data
                        else None
                    )
                    chosen_company_name = company.name
                    found_tag = get_most_common_tag_for_company(chosen_company_name)
                    if found_tag:
                        new_coupon.tags.append(found_tag)
                    db.session.add(new_coupon)
                    try:
                        db.session.commit()
                        add_coupon_transaction(new_coupon)
                        # Activity log snippet
                        try:
                            new_activity = {
                                "user_id": current_user.id,
                                "coupon_id": new_coupon.id,
                                "timestamp": datetime.utcnow(),
                                "action": "add_coupon_manual_submit",
                                "device": request.headers.get("User-Agent", "")[:50],
                                "browser": request.headers.get("User-Agent", "").split(
                                    " "
                                )[0][:50]
                                if request.headers.get("User-Agent", "")
                                else None,
                                "ip_address": ip_address[:45] if ip_address else None,
                                "geo_location": get_geo_location(ip_address)[:100],
                            }
                            db.session.execute(
                                text(
                                    """
                                    INSERT INTO user_activities
                                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                                    VALUES
                                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                                """
                                ),
                                new_activity,
                            )
                            db.session.commit()
                        except Exception as e:
                            db.session.rollback()
                            current_app.logger.error(
                                f"Error logging activity [add_coupon_manual_submit]: {e}"
                            )
                        # If request is made via AJAX, return JSON response without full page reload
                        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                            return jsonify(success=True, message="קופון נוסף בהצלחה!")
                        else:
                            flash("קופון נוסף בהצלחה!", "success")
                            return redirect(url_for("coupons.show_coupons"))
                    except IntegrityError as e:
                        db.session.rollback()
                        current_app.logger.error(
                            f"[ERROR] IntegrityError adding coupon: {e}"
                        )
                        flash("קוד קופון זה כבר קיים. אנא בחר קוד אחר.", "danger")
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.error(f"[ERROR] Error adding coupon: {e}")
                        flash("אירעה שגיאה בעת הוספת הקופון. נסה שוב.", "danger")
                else:
                    flash("הטופס אינו תקין. אנא בדוק את הנתונים שהזנת.", "danger")

        return render_template(
            "add_coupon.html",
            coupon_form=coupon_form,
            sms_form=sms_form,
            show_coupon_form=show_coupon_form,
            companies=companies,
            tags=tags,
        )
    except Exception as e:
        current_app.logger.error(f"[ERROR] Unhandled exception in add_coupon: {e}")
        traceback.print_exc()
        flash("אירעה שגיאה בלתי צפויה. אנא נסה שוב מאוחר יותר.", "danger")
        return redirect(url_for("coupons.add_coupon"))


@coupons_bp.route("/add_coupon_with_image.html", methods=["GET", "POST"])
@login_required
def add_coupon_with_image_html():
    # log_user_activity("add_coupon_with_image_html_view", None)

    form = CouponForm()
    if request.method == "POST":
        # Step A: If an image was uploaded
        image_file = request.files.get("coupon_image")
        if image_file and image_file.filename != "":
            upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            image_path = os.path.join(upload_folder, image_file.filename)
            image_file.save(image_path)

            try:
                coupon_df, pricing_df = extract_coupon_detail_image_proccess(
                    client_id=os.getenv("IMGUR_CLIENT_ID"),
                    image_path=image_path,
                    companies_list=[company.name for company in Company.query.all()],
                )
            except Exception as e:
                current_app.logger.error(f"Error extracting coupon from image: {e}")
                flash(f"אירעה שגיאה בעת עיבוד התמונה: {e}", "danger")
                return render_template("add_coupon_with_image.html", form=form)

            if not coupon_df.empty:
                # Fill in the fields based on what was returned from image processing
                form.company_id.data = coupon_df.loc[0, "חברה"]
                form.code.data = coupon_df.loc[0, "קוד קופון"]
                form.cost.data = coupon_df.loc[0, "עלות"]
                form.value.data = coupon_df.loc[0, "ערך מקורי"]
                form.discount_percentage.data = coupon_df.loc[0, "אחוז הנחה"]

                try:
                    form.expiration.data = pd.to_datetime(
                        coupon_df.loc[0, "תאריך תפוגה"]
                    ).date()
                except:
                    form.expiration.data = None

                form.description.data = coupon_df.loc[0, "תיאור"]
                flash("הטופס מולא בהצלחה. אנא בדוק וערוך אם נדרש.", "success")
            else:
                flash("לא ניתן היה לחלץ פרטי קופון מהתמונה.", "danger")

        # Step B: If the user submitted the final form (e.g., a button called 'submit_coupon') => save the coupon
        elif "submit_coupon" in request.form and form.validate_on_submit():
            # Steps to create the coupon exactly like in `add_coupon_with_image`,
            # including finding the company, saving to the database, and then adding the tag (get_most_common_tag_for_company).
            selected_company_id = form.company_id.data
            other_company_name = (form.other_company.data or "").strip()

            if selected_company_id == "other":
                # Handle 'other' company
                if not other_company_name:
                    flash("יש להזין שם חברה חדשה.", "danger")
                    return redirect(url_for("coupons.add_coupon_with_image_html"))
                existing_company = Company.query.filter_by(
                    name=other_company_name
                ).first()
                if existing_company:
                    company = existing_company
                else:
                    company = Company(
                        name=other_company_name, image_path="default_logo.png"
                    )
                    db.session.add(company)
                    db.session.flush()
            else:
                try:
                    selected_company_id = int(selected_company_id)
                    company = Company.query.get(selected_company_id)
                    if not company:
                        flash("חברה נבחרה אינה תקפה.", "danger")
                        return redirect(url_for("coupons.add_coupon_with_image_html"))
                except (ValueError, TypeError):
                    flash("חברה נבחרה אינה תקפה.", "danger")
                    return redirect(url_for("coupons.add_coupon_with_image_html"))

            code = form.code.data.strip()
            try:
                value = float(form.value.data) if form.value.data else 0
            except ValueError:
                flash("ערך הקופון חייב להיות מספר.", "danger")
                return render_template("add_coupon_with_image.html", form=form)

            try:
                cost = float(form.cost.data) if form.cost.data else 0
            except ValueError:
                flash("מחיר הקופון חייב להיות מספר.", "danger")
                return render_template("add_coupon_with_image.html", form=form)

            description = form.description.data.strip() if form.description.data else ""
            expiration = form.expiration.data or None
            is_one_time = form.is_one_time.data
            purpose = (
                form.purpose.data.strip() if is_one_time and form.purpose.data else None
            )

            # Check for unique code
            if Coupon.query.filter_by(code=code).first():
                flash("קוד קופון זה כבר קיים. אנא בחר קוד אחר.", "danger")
                return redirect(url_for("coupons.add_coupon_with_image_html"))

            # Expiration date check
            current_date = datetime.utcnow().date()
            if expiration and expiration < current_date:
                flash("תאריך התפוגה של הקופון כבר עבר. אנא בחר תאריך תקין.", "danger")
                return render_template("add_coupon_with_image.html", form=form)

            new_coupon = Coupon(
                code=code,
                value=value,
                cost=cost,
                company=company.name,
                description=description,
                expiration=expiration,
                user_id=current_user.id,
                is_one_time=is_one_time,
                purpose=purpose,
                used_value=0.0,
                status="פעיל",
            )

            # Step of adding the most common tag (like in the manual flow)
            chosen_company_name = company.name
            found_tag = get_most_common_tag_for_company(chosen_company_name)
            if found_tag:
                new_coupon.tags.append(found_tag)

            db.session.add(new_coupon)
            try:
                db.session.commit()
                add_coupon_transaction(
                    new_coupon
                )  # ואז ליצור את רשומת ה-CouponTransaction
                """""" """
                notification = Notification(
                    user_id=current_user.id,
                    message=f"הקופון {new_coupon.code} נוסף בהצלחה.",
                    link=url_for('coupons.coupon_detail', id=new_coupon.id)
                )
                db.session.add(notification)
                """ """"""
                db.session.commit()

                flash("קופון נוסף בהצלחה!", "success")
                return redirect(url_for("coupons.show_coupons"))
            except IntegrityError:
                db.session.rollback()
                flash("קוד קופון זה כבר קיים. אנא בחר קוד אחר.", "danger")
            except Exception as e:
                db.session.rollback()
                flash("אירעה שגיאה בעת הוספת הקופון. נסה שוב.", "danger")
                current_app.logger.error(f"Error adding coupon: {e}")

    return render_template("add_coupon_with_image.html", form=form)


# Debug control - set this to True to enable debug prints, False to disable
DEBUG_ENABLED = False


def debug_print(message, level="INFO"):
    """Print debug messages if debugging is enabled
    
    Args:
        message: The message to print
        level: Debug level (INFO, WARNING, ERROR)
    """
    if DEBUG_ENABLED:
        print(f"[DEBUG-{level}] {message}")


@coupons_bp.route("/add_coupon", methods=["GET", "POST"])
@login_required
def add_coupon():
    debug_print("Entering add_coupon route")

    # Log activity snippet (commented out)
    # log_user_activity("add_coupon_view", None)
    try:
        debug_print("Checking if request is AJAX")
        # Check for AJAX requests first - this is important for SMS detection
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            debug_print("Processing AJAX request")
            # Check if this is an SMS detection request
            if request.form.get("submit_sms") == "true":
                debug_print("Processing SMS detection request")
                # Get the SMS text from the form
                sms_text = request.form.get("sms_text", "")
                debug_print(
                    f"SMS text received: {sms_text[:50]}..."
                    if len(sms_text) > 50
                    else f"SMS text received: {sms_text}"
                )

                if not sms_text:
                    debug_print("No SMS text provided", "WARNING")
                    return jsonify(success=False, message="לא הוזן טקסט SMS")

                # Get companies list for matching
                debug_print("Fetching companies for matching")
                companies = Company.query.order_by(Company.name).all()
                companies_list = [c.name for c in companies]
                debug_print(f"Found {len(companies_list)} companies")

                # Extract coupon details from SMS text
                debug_print("Extracting coupon details from SMS")
                extracted_data_df, pricing_df = extract_coupon_detail_sms(
                    sms_text, companies_list
                )
                debug_print(
                    f"Extraction complete. Data found: {not extracted_data_df.empty}"
                )

                # Log GPT usage if available
                if not pricing_df.empty:
                    debug_print("Logging GPT usage")
                    pricing_row = pricing_df.iloc[0]
                    new_usage = GptUsage(
                        user_id=current_user.id,
                        created=datetime.strptime(
                            pricing_row["created"], "%Y-%m-%d %H:%M:%S"
                        ),
                        id=pricing_row["id"],
                        object=pricing_row["object"],
                        model=pricing_row["model"],
                        prompt_tokens=int(pricing_row["prompt_tokens"]),
                        completion_tokens=int(pricing_row["completion_tokens"]),
                        total_tokens=int(pricing_row["total_tokens"]),
                        cost_usd=float(pricing_row["cost_usd"]),
                        cost_ils=float(pricing_row["cost_ils"]),
                        exchange_rate=float(pricing_row["exchange_rate"]),
                        prompt_text=np.nan,
                        response_text=np.nan,
                    )
                    db.session.add(new_usage)
                    db.session.commit()
                    debug_print("GPT usage logged successfully")

                # Return extracted data if available
                if not extracted_data_df.empty:
                    debug_print("Processing extracted data")
                    extracted_data = extracted_data_df.iloc[0].to_dict()

                    # Convert data types for JSON serialization
                    debug_print("Converting data types for JSON serialization")
                    for key, value in extracted_data.items():
                        if pd.isna(value):
                            extracted_data[key] = None
                        elif isinstance(value, np.int64):
                            extracted_data[key] = int(value)
                        elif isinstance(value, np.float64):
                            extracted_data[key] = float(value)

                    debug_print("Returning extracted data via JSON")
                    return jsonify(
                        success=True, message="הקופון זוהה בהצלחה!", data=extracted_data
                    )
                else:
                    debug_print("No data extracted from SMS", "WARNING")
                    return jsonify(
                        success=False, message="לא ניתן לזהות נתונים בטקסט שהוזן"
                    )

            # Regular AJAX coupon submission
            elif request.form.get("submit_coupon") == "true":
                debug_print("Processing AJAX coupon submission")

                # Validate form data similar to manual submission
                code = request.form.get("code", "").strip()
                value = float(request.form.get("value", 0))
                cost = float(request.form.get("cost", 0))
                description = (request.form.get("description", "") or "").strip()
                expiration = request.form.get("expiration")
                is_one_time = request.form.get("is_one_time") == "true"
                purpose = (
                    request.form.get("purpose", "").strip() if is_one_time else ""
                ) or None
                source = (request.form.get("source", "") or "").strip()
                selected_company_id = request.form.get("company_id")
                other_company_name = (
                    request.form.get("other_company", "") or ""
                ).strip()

                debug_print(
                    f"AJAX Coupon details: code={code}, value={value}, cost={cost}"
                )

                try:
                    # Check slots availability
                    if current_user.slots_automatic_coupons <= 0:
                        debug_print("No slots available", "WARNING")
                        return jsonify(
                            success=False, message="אין לך מספיק סלוטים להוספת קופונים."
                        )

                    # Handle company selection similar to manual submission
                    if selected_company_id == "other":
                        if not other_company_name:
                            debug_print("No company name provided", "WARNING")
                            return jsonify(
                                success=False, message="יש להזין שם חברה חדשה."
                            )

                        existing_company = Company.query.filter_by(
                            name=other_company_name
                        ).first()
                        if existing_company:
                            company = existing_company
                        else:
                            company = Company(
                                name=other_company_name, image_path="default_logo.png"
                            )
                            db.session.add(company)
                            db.session.flush()
                    else:
                        try:
                            selected_company_id = int(selected_company_id)
                            company = Company.query.get(selected_company_id)
                            if not company:
                                debug_print(
                                    f"Company with ID {selected_company_id} not found",
                                    "ERROR",
                                )
                                return jsonify(
                                    success=False, message="חברה נבחרה אינה תקפה."
                                )
                        except (ValueError, TypeError):
                            debug_print(
                                f"Invalid company ID: {selected_company_id}", "ERROR"
                            )
                            return jsonify(
                                success=False, message="חברה נבחרה אינה תקפה."
                            )

                    # Decrease slots
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                    debug_print(
                        f"Slot used. Remaining slots: {current_user.slots_automatic_coupons}"
                    )

                    # Create coupon
                    new_coupon = Coupon(
                        code=code,
                        value=value,
                        cost=cost,
                        company=company.name,
                        description=description,
                        expiration=datetime.strptime(expiration, "%Y-%m-%d").date()
                        if expiration
                        else None,
                        user_id=current_user.id,
                        is_one_time=is_one_time,
                        purpose=purpose,
                        source=source,
                    )

                    # Optional: Add tag
                    chosen_company_name = company.name
                    found_tag = get_most_common_tag_for_company(chosen_company_name)
                    if found_tag:
                        new_coupon.tags.append(found_tag)

                    db.session.add(new_coupon)
                    db.session.commit()

                    debug_print(f"Coupon added successfully. ID: {new_coupon.id}")
                    return jsonify(success=True, message="קופון נוסף בהצלחה!")

                except Exception as e:
                    db.session.rollback()
                    debug_print(f"Error adding AJAX coupon: {e}", "ERROR")
                    return jsonify(
                        success=False, message=f"שגיאה בהוספת קופון: {str(e)}"
                    )

        # Non-AJAX request handling - the original function logic follows:
        debug_print("Processing non-AJAX request")
        manual = request.args.get("manual", "false").lower() == "true"
        debug_print(f"Manual mode: {manual}")
        sms_form = SMSInputForm()
        coupon_form = CouponForm()
        show_coupon_form = manual
        debug_print(f"Initial show_coupon_form: {show_coupon_form}")

        debug_print("Fetching companies and tags")
        companies = Company.query.order_by(Company.name).all()
        tags = Tag.query.all()
        debug_print(f"Found {len(companies)} companies and {len(tags)} tags")

        companies_list = [c.name for c in companies]

        debug_print("Populating form choices")
        coupon_form.company_id.choices = (
            [("", "בחר")]
            + [(str(company.id), company.name) for company in companies]
            + [("other", "אחר")]
        )
        coupon_form.tag_id.choices = (
            [("", "בחר")]
            + [(str(tag.id), tag.name) for tag in tags]
            + [("other", "אחר")]
        )

        # Process SMS submission
        if sms_form.validate_on_submit() and "sms_text" in request.form:
            debug_print("Processing SMS form submission")
            sms_text = sms_form.sms_text.data
            debug_print(
                f"SMS text: {sms_text[:50]}..."
                if len(sms_text) > 50
                else f"SMS text: {sms_text}"
            )
            extracted_data_df, pricing_df = extract_coupon_detail_sms(
                sms_text, companies_list
            )
            debug_print(
                f"Extraction complete. Data found: {not extracted_data_df.empty}"
            )

            if not pricing_df.empty:
                debug_print("Logging GPT usage")
                pricing_row = pricing_df.iloc[0]
                new_usage = GptUsage(
                    user_id=current_user.id,
                    created=datetime.strptime(
                        pricing_row["created"], "%Y-%m-%d %H:%M:%S"
                    ),
                    id=pricing_row["id"],
                    object=pricing_row["object"],
                    model=pricing_row["model"],
                    prompt_tokens=int(pricing_row["prompt_tokens"]),
                    completion_tokens=int(pricing_row["completion_tokens"]),
                    total_tokens=int(pricing_row["total_tokens"]),
                    cost_usd=float(pricing_row["cost_usd"]),
                    cost_ils=float(pricing_row["cost_ils"]),
                    exchange_rate=float(pricing_row["exchange_rate"]),
                    prompt_text=np.nan,
                    response_text=np.nan,
                )
                db.session.add(new_usage)
                db.session.commit()
                debug_print("GPT usage logged successfully")

            if not extracted_data_df.empty:
                debug_print("Processing extracted data")
                extracted_data = extracted_data_df.iloc[0].to_dict()
                company_name = extracted_data.get("חברה", "").strip()
                debug_print(f"Extracted company name: {company_name}")

                debug_print("Finding best company match")
                best_match_ratio = 0
                best_company = None
                for comp in companies:
                    ratio = fuzz.token_set_ratio(company_name, comp.name)
                    if ratio > best_match_ratio:
                        best_match_ratio = ratio
                        best_company = comp
                debug_print(
                    f"Best match: {best_company.name if best_company else 'None'} with ratio {best_match_ratio}"
                )

                if best_company and best_match_ratio >= 90:
                    debug_print(f"Using existing company: {best_company.name}")
                    coupon_form.company_id.data = str(best_company.id)
                    coupon_form.other_company.data = ""
                    chosen_company_name = best_company.name
                else:
                    debug_print(f"Using new company name: {company_name}")
                    coupon_form.company_id.data = "other"
                    coupon_form.other_company.data = company_name
                    chosen_company_name = company_name

                debug_print("Populating coupon form with extracted data")
                coupon_form.code.data = extracted_data.get("קוד קופון")
                coupon_form.cost.data = extracted_data.get("עלות", 0) or 0
                try:
                    if extracted_data.get("תאריך תפוגה"):
                        debug_print(
                            f"Parsing expiration date: {extracted_data['תאריך תפוגה']}"
                        )
                        coupon_form.expiration.data = datetime.strptime(
                            extracted_data["תאריך תפוגה"], "%Y-%m-%d"
                        ).date()
                except Exception as e:
                    debug_print(f"Error parsing expiration date: {e}", "ERROR")
                    current_app.logger.error(f"[ERROR] parsing expiration date: {e}")

                coupon_form.is_one_time.data = bool(
                    extracted_data.get("קוד לשימוש חד פעמי")
                )
                coupon_form.purpose.data = extracted_data.get("מטרת הקופון", "")
                coupon_form.description.data = extracted_data.get("תיאור", "")
                coupon_form.value.data = extracted_data.get("ערך מקורי", 0) or 0
                coupon_form.discount_percentage.data = 0

                debug_print(
                    f"Checking slot availability. Current slots: {current_user.slots_automatic_coupons}"
                )
                if current_user.slots_automatic_coupons > 0:
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                    debug_print(
                        f"Slot used. Remaining slots: {current_user.slots_automatic_coupons}"
                    )
                else:
                    debug_print("No slots available", "WARNING")
                    flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                    return redirect(url_for("coupons.add_coupon"))

                debug_print(f"Finding tag for company: {chosen_company_name}")
                found_tag = get_most_common_tag_for_company(chosen_company_name)
                current_app.logger.info(
                    f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'"
                )
                if found_tag:
                    debug_print(f"Tag found: {found_tag.name}")
                    coupon_form.tag_id.data = str(found_tag.id)
                    coupon_form.other_tag.data = ""

                show_coupon_form = True
                debug_print("Form populated successfully, showing coupon form")
            else:
                debug_print("No data found in SMS", "WARNING")
                flash("לא נמצאו נתונים בהודעת ה-SMS.", "danger")

            debug_print("Rendering template with SMS data")
            return render_template(
                "add_coupon.html",
                coupon_form=coupon_form,
                sms_form=sms_form,
                show_coupon_form=show_coupon_form,
                companies=companies,
                tags=tags,
            )

        # Process POST request (image upload or manual coupon submission)
        if request.method == "POST":
            debug_print("Processing POST request")
            if "upload_image" in request.form and coupon_form.upload_image.data:
                debug_print("Processing image upload")
                image_file = coupon_form.coupon_image.data
                if image_file and image_file.filename != "":
                    debug_print(f"Image file: {image_file.filename}")
                    try:
                        flash("Starting image processing...", "info")
                        upload_folder = current_app.config.get(
                            "UPLOAD_FOLDER", "uploads"
                        )
                        debug_print(f"Upload folder: {upload_folder}")
                        if not os.path.exists(upload_folder):
                            os.makedirs(upload_folder)
                            debug_print(f"Created folder: {upload_folder}")
                            flash(f"Folder {upload_folder} created.", "info")

                        image_path = os.path.join(upload_folder, image_file.filename)
                        image_file.save(image_path)
                        debug_print(f"Image saved to: {image_path}")
                        flash(f"Image saved to {image_path}.", "success")

                        if not companies_list:
                            debug_print("Company list is empty", "WARNING")
                            flash(
                                "Company list is empty. Ensure companies exist in the system.",
                                "warning",
                            )
                            return render_template(
                                "add_coupon.html",
                                coupon_form=coupon_form,
                                sms_form=sms_form,
                                show_coupon_form=show_coupon_form,
                                companies=companies,
                                tags=tags,
                            )

                        debug_print("Extracting coupon details from image")
                        coupon_df, pricing_df = extract_coupon_detail_image_proccess(
                            client_id=os.getenv("IMGUR_CLIENT_ID"),
                            image_path=image_path,
                            companies_list=companies_list,
                        )
                        debug_print("Image processing completed")
                        flash("extract_coupon_detail_image_proccess completed.", "info")

                        if not coupon_df.empty:
                            debug_print("Coupon details extracted successfully")
                            flash("Coupon details extracted successfully.", "success")

                            extracted_company = coupon_df.loc[0, "חברה"]
                            debug_print(f"Extracted company: {extracted_company}")
                            best_match_ratio = 0
                            best_company = None
                            for comp in companies:
                                ratio = fuzz.token_set_ratio(
                                    extracted_company, comp.name
                                )
                                if ratio > best_match_ratio:
                                    best_match_ratio = ratio
                                    best_company = comp
                            debug_print(
                                f"Best match: {best_company.name if best_company else 'None'} with ratio {best_match_ratio}"
                            )

                            if best_company and best_match_ratio >= 90:
                                debug_print(
                                    f"Using existing company: {best_company.name}"
                                )
                                coupon_form.company_id.data = str(best_company.id)
                                coupon_form.other_company.data = ""
                                chosen_company_name = best_company.name
                            else:
                                debug_print(
                                    f"Using new company name: {extracted_company}"
                                )
                                coupon_form.company_id.data = "other"
                                coupon_form.other_company.data = extracted_company
                                chosen_company_name = extracted_company

                            debug_print("Populating coupon form with extracted data")
                            coupon_form.code.data = coupon_df.loc[0, "קוד קופון"]
                            coupon_form.cost.data = (
                                coupon_df.loc[0, "עלות"]
                                if pd.notnull(coupon_df.loc[0, "עלות"])
                                else 0
                            )
                            coupon_form.value.data = (
                                coupon_df.loc[0, "ערך מקורי"]
                                if pd.notnull(coupon_df.loc[0, "ערך מקורי"])
                                else 0
                            )
                            coupon_form.discount_percentage.data = (
                                coupon_df.loc[0, "אחוז הנחה"]
                                if pd.notnull(coupon_df.loc[0, "אחוז הנחה"])
                                else 0
                            )
                            try:
                                expiration_val = coupon_df.loc[0, "תאריך תפוגה"]
                                if pd.notnull(expiration_val):
                                    debug_print(
                                        f"Parsing expiration date: {expiration_val}"
                                    )
                                    coupon_form.expiration.data = pd.to_datetime(
                                        expiration_val
                                    ).date()
                            except Exception as e:
                                debug_print(
                                    f"Error parsing expiration date: {e}", "ERROR"
                                )
                                current_app.logger.error(
                                    f"[ERROR] parsing expiration date from image: {e}"
                                )

                            coupon_form.description.data = (
                                coupon_df.loc[0, "תיאור"]
                                if pd.notnull(coupon_df.loc[0, "תיאור"])
                                else ""
                            )
                            coupon_form.is_one_time.data = False
                            coupon_form.purpose.data = ""

                            debug_print(
                                f"Checking slot availability. Current slots: {current_user.slots_automatic_coupons}"
                            )
                            if current_user.slots_automatic_coupons > 0:
                                current_user.slots_automatic_coupons -= 1
                                db.session.commit()
                                debug_print(
                                    f"Slot used. Remaining slots: {current_user.slots_automatic_coupons}"
                                )
                            else:
                                debug_print("No slots available", "WARNING")
                                flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                                return redirect(url_for("coupons.add_coupon"))

                            debug_print(
                                f"Finding tag for company: {chosen_company_name}"
                            )
                            found_tag = get_most_common_tag_for_company(
                                chosen_company_name
                            )
                            current_app.logger.info(
                                f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'"
                            )
                            if found_tag:
                                debug_print(f"Tag found: {found_tag.name}")
                                coupon_form.tag_id.data = str(found_tag.id)
                                coupon_form.other_tag.data = ""

                            try:
                                debug_print("Logging user activity")
                                new_activity = {
                                    "user_id": current_user.id,
                                    "coupon_id": None,
                                    "timestamp": datetime.utcnow(),
                                    "action": "add_coupon_via_image_upload",
                                    "device": request.headers.get("User-Agent", "")[
                                        :50
                                    ],
                                    "browser": request.headers.get(
                                        "User-Agent", ""
                                    ).split(" ")[0][:50]
                                    if request.headers.get("User-Agent", "")
                                    else None,
                                    "ip_address": ip_address[:45]
                                    if ip_address
                                    else None,
                                    "geo_location": get_geo_location(ip_address)[:100],
                                }
                                db.session.execute(
                                    text(
                                        """
                                        INSERT INTO user_activities
                                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                                        VALUES
                                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                                    """
                                    ),
                                    new_activity,
                                )
                                db.session.commit()
                                debug_print("Activity logged successfully")
                            except Exception as e:
                                debug_print(f"Error logging activity: {e}", "ERROR")
                                db.session.rollback()
                                current_app.logger.error(
                                    f"Error logging activity [add_coupon_via_image_upload]: {e}"
                                )

                            show_coupon_form = True
                            debug_print(
                                "Form populated successfully, showing coupon form"
                            )
                            flash(
                                "Form populated successfully. Please check and edit if necessary.",
                                "success",
                            )
                        else:
                            debug_print("No coupon details found in image", "WARNING")
                            flash(
                                "Could not extract coupon details from image.", "danger"
                            )
                    except Exception as e:
                        debug_print(f"Error processing image: {e}", "ERROR")
                        current_app.logger.error(f"[ERROR] processing image: {e}")
                        traceback.print_exc()
                        flash(
                            "An error occurred while processing the image. Please try again later.",
                            "danger",
                        )
                else:
                    debug_print("No image provided", "WARNING")
                    flash("Image is required.", "danger")
                debug_print("Rendering template after image processing")
                return render_template(
                    "add_coupon.html",
                    coupon_form=coupon_form,
                    sms_form=sms_form,
                    show_coupon_form=show_coupon_form,
                    companies=companies,
                    tags=tags,
                )
            elif "submit_coupon" in request.form and coupon_form.submit_coupon.data:
                debug_print("Processing manual coupon submission")
                # Manual flow - user pressed submit_coupon
                if coupon_form.validate_on_submit():
                    debug_print("Form validation successful")
                    code = coupon_form.code.data.strip()
                    debug_print(f"Coupon code: {code}")
                    try:
                        value = (
                            float(coupon_form.value.data)
                            if coupon_form.value.data
                            else 0
                        )
                        debug_print(f"Coupon value: {value}")
                    except Exception as e:
                        debug_print(f"Error converting value to float: {e}", "ERROR")
                        current_app.logger.error(
                            f"[ERROR] converting value to float: {e}"
                        )
                        value = 0
                    try:
                        cost = (
                            float(coupon_form.cost.data) if coupon_form.cost.data else 0
                        )
                        debug_print(f"Coupon cost: {cost}")
                    except Exception as e:
                        debug_print(f"Error converting cost to float: {e}", "ERROR")
                        current_app.logger.error(
                            f"[ERROR] converting cost to float: {e}"
                        )
                        cost = 0
                    description = (coupon_form.description.data or "").strip()
                    expiration = coupon_form.expiration.data or None
                    debug_print(f"Expiration date: {expiration}")
                    is_one_time = coupon_form.is_one_time.data
                    debug_print(f"One-time use: {is_one_time}")
                    purpose = (
                        coupon_form.purpose.data.strip() if is_one_time else ""
                    ) or None
                    source = coupon_form.source.data.strip()  # Source field
                    debug_print(f"Source: {source}")
                    selected_company_id = coupon_form.company_id.data
                    debug_print(f"Selected company ID: {selected_company_id}")
                    other_company_name = (coupon_form.other_company.data or "").strip()

                    if selected_company_id == "other":
                        debug_print("Processing 'other' company selection")
                        if not other_company_name:
                            debug_print("No company name provided", "WARNING")
                            flash("יש להזין שם חברה חדשה.", "danger")
                            return redirect(
                                url_for("coupons.add_coupon", manual="true")
                            )
                        debug_print(
                            f"Checking if company '{other_company_name}' already exists"
                        )
                        existing_company = Company.query.filter_by(
                            name=other_company_name
                        ).first()
                        if existing_company:
                            debug_print(
                                f"Company already exists: {existing_company.name}"
                            )
                            company = existing_company
                        else:
                            debug_print(f"Creating new company: {other_company_name}")
                            company = Company(
                                name=other_company_name, image_path="default_logo.png"
                            )
                            db.session.add(company)
                            db.session.flush()
                            debug_print(f"New company created with ID: {company.id}")
                    else:
                        debug_print(
                            f"Using existing company with ID: {selected_company_id}"
                        )
                        try:
                            selected_company_id = int(selected_company_id)
                            company = Company.query.get(selected_company_id)
                            if not company:
                                debug_print(
                                    f"Company with ID {selected_company_id} not found",
                                    "ERROR",
                                )
                                flash("חברה נבחרה אינה תקפה.", "danger")
                                return redirect(
                                    url_for("coupons.add_coupon", manual="true")
                                )
                            debug_print(f"Company found: {company.name}")
                        except (ValueError, TypeError):
                            debug_print(
                                f"Invalid company ID: {selected_company_id}", "ERROR"
                            )
                            flash("חברה נבחרה אינה תקפה.", "danger")
                            return redirect(
                                url_for("coupons.add_coupon", manual="true")
                            )

                    debug_print(
                        f"Checking slot availability. Current slots: {current_user.slots_automatic_coupons}"
                    )
                    if current_user.slots_automatic_coupons <= 0:
                        debug_print("No slots available", "WARNING")
                        flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                        return redirect(url_for("coupons.add_coupon", manual="true"))

                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                    debug_print(
                        f"Slot used. Remaining slots: {current_user.slots_automatic_coupons}"
                    )

                    debug_print("Creating new coupon object")
                    new_coupon = Coupon(
                        code=code,
                        value=value,
                        cost=cost,
                        company=company.name,
                        description=description,
                        expiration=expiration,
                        user_id=current_user.id,
                        is_one_time=is_one_time,
                        purpose=purpose,
                        source=source,  # Source field
                    )
                    new_coupon.buyme_coupon_url = (
                        coupon_form.buyme_coupon_url.data.strip()
                        if coupon_form.buyme_coupon_url.data
                        else None
                    )
                    debug_print(f"BuyMe URL: {new_coupon.buyme_coupon_url}")

                    chosen_company_name = company.name
                    debug_print(f"Finding tag for company: {chosen_company_name}")
                    found_tag = get_most_common_tag_for_company(chosen_company_name)
                    if found_tag:
                        debug_print(f"Tag found: {found_tag.name}")
                        new_coupon.tags.append(found_tag)

                    db.session.add(new_coupon)
                    debug_print("Attempting to save coupon to database")
                    try:
                        db.session.commit()
                        debug_print(f"Coupon saved with ID: {new_coupon.id}")
                        add_coupon_transaction(new_coupon)
                        debug_print("Coupon transaction recorded")

                        # Activity log snippet
                        try:
                            debug_print("Logging user activity")
                            new_activity = {
                                "user_id": current_user.id,
                                "coupon_id": new_coupon.id,
                                "timestamp": datetime.utcnow(),
                                "action": "add_coupon_manual_submit",
                                "device": request.headers.get("User-Agent", "")[:50],
                                "browser": request.headers.get("User-Agent", "").split(
                                    " "
                                )[0][:50]
                                if request.headers.get("User-Agent", "")
                                else None,
                                "ip_address": ip_address[:45] if ip_address else None,
                                "geo_location": get_geo_location(ip_address)[:100],
                            }
                            db.session.execute(
                                text(
                                    """
                                    INSERT INTO user_activities
                                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                                    VALUES
                                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                                """
                                ),
                                new_activity,
                            )
                            db.session.commit()
                            debug_print("Activity logged successfully")
                        except Exception as e:
                            debug_print(f"Error logging activity: {e}", "ERROR")
                            db.session.rollback()
                            current_app.logger.error(
                                f"Error logging activity [add_coupon_manual_submit]: {e}"
                            )

                        # If request is made via AJAX, return JSON response without full page reload
                        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                            debug_print("Returning AJAX success response")
                            return jsonify(success=True, message="קופון נוסף בהצלחה!")
                        else:
                            debug_print("Redirecting to coupons list")
                            flash("קופון נוסף בהצלחה!", "success")
                            return redirect(url_for("coupons.show_coupons"))
                    except IntegrityError as e:
                        debug_print(f"IntegrityError: {e}", "ERROR")
                        db.session.rollback()
                        current_app.logger.error(
                            f"[ERROR] IntegrityError adding coupon: {e}"
                        )
                        flash("קוד קופון זה כבר קיים. אנא בחר קוד אחר.", "danger")
                    except Exception as e:
                        debug_print(f"Error adding coupon: {e}", "ERROR")
                        db.session.rollback()
                        current_app.logger.error(f"[ERROR] Error adding coupon: {e}")
                        flash("אירעה שגיאה בעת הוספת הקופון. נסה שוב.", "danger")
                else:
                    debug_print("Form validation failed", "WARNING")
                    flash("הטופס אינו תקין. אנא בדוק את הנתונים שהזנת.", "danger")

        debug_print("Rendering add_coupon template")
        return render_template(
            "add_coupon.html",
            coupon_form=coupon_form,
            sms_form=sms_form,
            show_coupon_form=show_coupon_form,
            companies=companies,
            tags=tags,
        )
    except Exception as e:
        debug_print(f"Unhandled exception: {e}", "ERROR")
        current_app.logger.error(f"[ERROR] Unhandled exception in add_coupon: {e}")
        traceback.print_exc()
        flash("אירעה שגיאה בלתי צפויה. אנא נסה שוב מאוחר יותר.", "danger")
        return redirect(url_for("coupons.add_coupon"))


@coupons_bp.route("/add_coupon_with_image", methods=["GET", "POST"])
@login_required
def add_coupon_with_image():
    # log_user_activity("add_coupon_with_image_view", None)

    upload_image_form = UploadImageForm()
    coupon_form = CouponForm()
    show_coupon_form = False

    # Fetch the list of companies from the database
    companies = Company.query.order_by(Company.name).all()

    # Set the choices for the company_id field only (without tags)
    coupon_form.company_id.choices = (
        [("", "בחר")]
        + [(str(company.id), company.name) for company in companies]
        + [("other", "אחר")]
    )

    # If an image was uploaded using the upload image form
    if (
        upload_image_form.validate_on_submit()
        and upload_image_form.submit_upload_image.data
    ):
        image_file = upload_image_form.coupon_image.data
        if image_file:
            filename = secure_filename(image_file.filename)
            upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            image_path = os.path.join(upload_folder, filename)
            image_file.save(image_path)

            try:
                coupon_df, pricing_df = extract_coupon_detail_image_proccess(
                    client_id=os.getenv("IMGUR_CLIENT_ID"),
                    image_path=image_path,
                    companies_list=[company.name for company in companies],
                )
            except Exception as e:
                current_app.logger.error(f"Error extracting coupon from image: {e}")
                flash(f"אירעה שגיאה בעת עיבוד התמונה: {e}", "danger")
                return render_template(
                    "add_coupon_with_image.html",
                    coupon_form=coupon_form,
                    upload_image_form=upload_image_form,
                    show_coupon_form=show_coupon_form,
                )

            if not coupon_df.empty:
                coupon_data = coupon_df.iloc[0].to_dict()
                company_name = coupon_data.get("חברה", "").strip()
                # Find the best matching company (Fuzzy Matching)
                best_match_ratio = 0
                best_company = None
                for comp in companies:
                    ratio = fuzz.token_set_ratio(company_name, comp.name)
                    if ratio > best_match_ratio:
                        best_match_ratio = ratio
                        best_company = comp

                # If a good enough match is found for the company
                if best_company and best_match_ratio >= 90:
                    coupon_form.company_id.data = str(best_company.id)
                    coupon_form.other_company.data = ""
                else:
                    # אחרת נרשום אותה כ"אחר" ונמלא את שדה חברה חדשה
                    coupon_form.company_id.data = "other"
                    coupon_form.other_company.data = company_name

                # מילוי יתר השדות
                try:
                    coupon_form.cost.data = float(coupon_data.get("עלות", 0))
                except ValueError:
                    coupon_form.cost.data = 0.0
                    flash("מחיר הקופון לא היה ניתן להמרה למספר, הוגדר כ-0.", "warning")

                try:
                    coupon_form.value.data = float(coupon_data.get("ערך מקורי", 0))
                except ValueError:
                    coupon_form.value.data = 0.0
                    flash("ערך הקופון לא היה ניתן להמרה למספר, הוגדר כ-0.", "warning")

                if "אחוז הנחה" in coupon_df.columns:
                    try:
                        coupon_form.discount_percentage.data = float(
                            coupon_data.get("אחוז הנחה", 0)
                        )
                    except ValueError:
                        coupon_form.discount_percentage.data = 0.0
                        flash(
                            "אחוז הנחה לא היה ניתן להמרה למספר, הוגדר כ-0.", "warning"
                        )
                else:
                    coupon_form.discount_percentage.data = 0

                expiration_str = coupon_data.get("תאריך תפוגה")
                if expiration_str:
                    try:
                        coupon_form.expiration.data = datetime.strptime(
                            expiration_str, "%Y-%m-%d"
                        ).date()
                    except ValueError:
                        try:
                            coupon_form.expiration.data = datetime.strptime(
                                expiration_str, "%d/%m/%Y"
                            ).date()
                        except ValueError:
                            coupon_form.expiration.data = None
                            flash("תאריך התפוגה לא בפורמט תקין.", "warning")
                else:
                    coupon_form.expiration.data = None

                coupon_form.code.data = coupon_data.get("קוד קופון")
                coupon_form.description.data = coupon_data.get("תיאור", "")
                coupon_form.is_one_time.data = bool(
                    coupon_data.get("קוד לשימוש חד פעמי")
                )
                coupon_form.purpose.data = (
                    coupon_data.get("מטרת הקופון", "")
                    if coupon_form.is_one_time.data
                    else ""
                )

                # הפחתת סלוטים (לדוגמה, אם במערכת יש הגבלה על מספר הקופונים האוטומטיים)
                if current_user.slots_automatic_coupons > 0:
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                else:
                    flash("אין לך מספיק סלוטים להוספת קופונים.", "danger")
                    return redirect(url_for("coupons.add_coupon_with_image"))

                show_coupon_form = True
                flash("הטופס מולא בהצלחה. אנא בדוק וערוך אם נדרש.", "success")
            else:
                error_reason = "לא נמצאו נתונים בתמונה."
                if not pricing_df.empty and "error_message" in pricing_df.columns:
                    error_reason = pricing_df.iloc[0]["error_message"]
                flash(f"לא ניתן היה לחלץ פרטי קופון מהתמונה: {error_reason}", "danger")

    # אם שלחו את הטופס הסופי להוספת הקופון
    elif coupon_form.validate_on_submit() and coupon_form.submit_coupon.data:
        selected_company_id = coupon_form.company_id.data
        other_company_name = (
            coupon_form.other_company.data.strip()
            if coupon_form.other_company.data
            else ""
        )

        # טיפול בחברה (יצירה או שליפה)
        if selected_company_id == "other":
            if not other_company_name:
                flash("יש להזין שם חברה חדשה.", "danger")
                return redirect(url_for("coupons.add_coupon_with_image"))
            existing_company = Company.query.filter_by(name=other_company_name).first()
            if existing_company:
                company = existing_company
            else:
                company = Company(
                    name=other_company_name, image_path="default_logo.png"
                )
                db.session.add(company)
                db.session.flush()
        else:
            try:
                selected_company_id = int(selected_company_id)
                company = Company.query.get(selected_company_id)
                if not company:
                    flash("חברה נבחרה אינה תקפה.", "danger")
                    return redirect(url_for("coupons.add_coupon_with_image"))
            except (ValueError, TypeError):
                flash("חברה נבחרה אינה תקפה.", "danger")
                return redirect(url_for("coupons.add_coupon_with_image"))

        code = coupon_form.code.data.strip()
        try:
            value = float(coupon_form.value.data)
        except ValueError:
            flash("ערך הקופון חייב להיות מספר.", "danger")
            show_coupon_form = True
            return render_template(
                "add_coupon_with_image.html",
                coupon_form=coupon_form,
                upload_image_form=upload_image_form,
                show_coupon_form=show_coupon_form,
                form=coupon_form,
            )

        try:
            cost = float(coupon_form.cost.data)
        except ValueError:
            flash("מחיר הקופון חייב להיות מספר.", "danger")
            show_coupon_form = True
            return render_template(
                "add_coupon_with_image.html",
                coupon_form=coupon_form,
                upload_image_form=upload_image_form,
                show_coupon_form=show_coupon_form,
                form=coupon_form,
            )

        description = (
            coupon_form.description.data.strip() if coupon_form.description.data else ""
        )
        expiration = coupon_form.expiration.data or None
        is_one_time = coupon_form.is_one_time.data
        purpose = (
            coupon_form.purpose.data.strip()
            if is_one_time and coupon_form.purpose.data
            else None
        )

        # בדיקה שהקוד לא קיים כבר
        if Coupon.query.filter_by(code=code).first():
            flash("קוד קופון זה כבר קיים. אנא בחר קוד אחר.", "danger")
            return redirect(url_for("coupons.add_coupon_with_image"))

        # בדיקת תאריך תפוגה
        current_date = datetime.utcnow().date()
        if expiration and expiration < current_date:
            flash("תאריך התפוגה של הקופון כבר עבר. אנא בחר תאריך תקין.", "danger")
            show_coupon_form = True
            return render_template(
                "add_coupon_with_image.html",
                coupon_form=coupon_form,
                upload_image_form=upload_image_form,
                show_coupon_form=show_coupon_form,
                form=coupon_form,
            )

        new_coupon = Coupon(
            code=code,
            value=value,
            cost=cost,
            company=company.name,
            description=description,
            expiration=expiration,
            user_id=current_user.id,
            is_one_time=is_one_time,
            purpose=purpose,
            used_value=0.0,
            status="פעיל",
        )

        # *** כאן מוסיפים את התגית הנפוצה (כמו ב-manual flow) ***
        chosen_company_name = company.name
        found_tag = get_most_common_tag_for_company(chosen_company_name)
        if found_tag:
            new_coupon.tags.append(found_tag)

        db.session.add(new_coupon)
        try:
            db.session.commit()
            """""" """
            notification = Notification(
                user_id=current_user.id,
                message=f"הקופון {new_coupon.code} נוסף בהצלחה.",
                link=url_for('coupons.coupon_detail', id=new_coupon.id)
            )
            db.session.add(notification)
            """ """"""
            db.session.commit()

            flash("קופון נוסף בהצלחה!", "success")
            return redirect(url_for("coupons.show_coupons"))
        except IntegrityError:
            db.session.rollback()
            flash("קוד קופון זה כבר קיים. אנא בחר קוד אחר.", "danger")
        except Exception as e:
            db.session.rollback()
            flash("אירעה שגיאה בעת הוספת הקופון. נסה שוב.", "danger")
            current_app.logger.error(f"Error adding coupon: {e}")

        show_coupon_form = True

    return render_template(
        "add_coupon_with_image.html",
        coupon_form=coupon_form,
        upload_image_form=upload_image_form,
        show_coupon_form=show_coupon_form,
        form=upload_image_form if not show_coupon_form else coupon_form,
    )


@coupons_bp.route("/add_coupon_manual", methods=["GET", "POST"])
@login_required
def add_coupon_manual():
    # -- activity log snippet --
    # log_user_activity("add_coupon_manual_view", None)

    coupon_form = CouponForm()
    if coupon_form.validate_on_submit():
        pass
    return render_template(
        "add_coupon.html", coupon_form=coupon_form, show_coupon_form=True
    )


def convert_date_format(date_input):
    if isinstance(date_input, str):
        try:
            return datetime.strptime(date_input, "%d/%m/%Y").date()
        except ValueError:
            return None
    elif isinstance(date_input, datetime):
        return date_input.date()
    elif isinstance(date_input, datetime.date):
        return date_input
    else:
        return None


@coupons_bp.route("/edit_coupon/<int:id>", methods=["GET", "POST"])
@login_required
def edit_coupon(id):
    coupon = Coupon.query.get_or_404(id)

    # -- activity log snippet --
    # log_user_activity("edit_coupon_view", coupon.id)

    if coupon.user_id != current_user.id:
        flash("אינך מורשה לערוך קופון זה.", "danger")
        return redirect(url_for("coupons.show_coupons"))

    form = EditCouponForm(obj=coupon)

    companies = Company.query.order_by(Company.name).all()
    company_choices = [("", "בחר חברה")]
    company_choices += [(str(c.id), c.name) for c in companies]
    company_choices.append(("other", "אחר"))
    form.company_id.choices = company_choices

    if form.validate_on_submit():
        try:
            old_value = coupon.value
            if form.company_id.data == "other":
                # אם המשתמש בחר "אחר"
                new_company_name = form.other_company.data.strip()
                if not new_company_name:
                    flash("יש להזין שם חברה חדשה.", "danger")
                    return redirect(url_for("coupons.edit_coupon", id=coupon.id))
                # בדיקה אם כבר קיימת החברה הזאת
                existing_company = Company.query.filter_by(
                    name=new_company_name
                ).first()
                if existing_company:
                    coupon.company = existing_company.name
                else:
                    # אם לא קיימת, יוצרים רשומה חדשה:
                    new_company = Company(
                        name=new_company_name, image_path="default_logo.png"
                    )
                    db.session.add(new_company)
                    db.session.commit()
                    coupon.company = new_company.name
            else:
                # אם המשתמש בחר חברה קיימת
                selected_company_id = int(form.company_id.data)
                chosen_company = Company.query.get(selected_company_id)
                if chosen_company:
                    coupon.company = chosen_company.name
                else:
                    flash("החברה שנבחרה אינה תקפה.", "danger")
                    return redirect(url_for("coupons.edit_coupon", id=coupon.id))

            coupon.code = form.code.data.strip()
            coupon.value = float(form.value.data)
            coupon.cost = float(form.cost.data)
            coupon.cvv = form.cvv.data
            coupon.card_exp = form.card_exp.data
            coupon.description = form.description.data or ""
            coupon.is_one_time = form.is_one_time.data
            coupon.purpose = (
                form.purpose.data.strip() if form.is_one_time.data else None
            )
            coupon.expiration = form.expiration.data if form.expiration.data else None
            coupon.cvv = form.cvv.data.strip() if form.cvv.data else None
            coupon.card_exp = form.card_exp.data.strip() if form.card_exp.data else None

            if form.tags.data:
                if isinstance(form.tags.data, str) and form.tags.data:
                    tag_names = [
                        tag.strip() for tag in form.tags.data.split(",") if tag.strip()
                    ]
                elif isinstance(form.tags.data, list):
                    tag_names = [
                        tag.strip()
                        for tag in form.tags.data
                        if isinstance(tag, str) and tag.strip()
                    ]
                else:
                    tag_names = []
                coupon.tags.clear()
                for name in tag_names:
                    tag = Tag.query.filter_by(name=name).first()
                    if not tag:
                        tag = Tag(name=name, count=1)
                        db.session.add(tag)
                    else:
                        tag.count += 1
                    coupon.tags.append(tag)
            else:
                coupon.tags.clear()

            db.session.commit()

            if coupon.value != old_value:
                initial_transaction = CouponTransaction.query.filter(
                    CouponTransaction.coupon_id == coupon.id,
                    CouponTransaction.source == "User",
                    CouponTransaction.reference_number.in_(["Initial", "ManualEntry"]),
                ).first()
                if initial_transaction:
                    initial_transaction.recharge_amount = coupon.value
                else:
                    initial_transaction = CouponTransaction(
                        coupon_id=coupon.id,
                        transaction_date=datetime.utcnow(),
                        location="הטענה ראשונית",
                        recharge_amount=coupon.value,
                        usage_amount=0.0,
                        reference_number="Initial",
                        source="User",
                    )
                    db.session.add(initial_transaction)
                db.session.commit()

            try:
                new_activity = {
                    "user_id": current_user.id,
                    "coupon_id": coupon.id,
                    "timestamp": datetime.utcnow(),
                    "action": "edit_coupon_submit",
                    "device": request.headers.get("User-Agent", "")[:50],
                    "browser": request.headers.get("User-Agent", "").split(" ")[0][:50]
                    if request.headers.get("User-Agent", "")
                    else None,
                    "ip_address": ip_address[:45] if ip_address else None,
                    "geo_location": get_geo_location(ip_address)[:100],
                }
                db.session.execute(
                    text(
                        """
                        INSERT INTO user_activities
                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                        VALUES
                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                    """
                    ),
                    new_activity,
                )
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Error logging activity [edit_coupon_submit]: {e}"
                )

            flash("הקופון עודכן בהצלחה.", "success")
            return redirect(url_for("coupons.coupon_detail", id=coupon.id))

        except IntegrityError:
            db.session.rollback()
            flash("קוד קופון זה כבר קיים. אנא בחר קוד אחר.", "danger")
        except Exception as e:
            db.session.rollback()
            flash("אירעה שגיאה בעת עדכון הקופון. נסה שוב.", "danger")
            current_app.logger.error(f"Error updating coupon: {e}")

    elif request.method == "GET":
        # מוצא את החברה לפי השם
        existing_company = Company.query.filter_by(name=coupon.company).first()
        if existing_company:
            # אם החברה נמצאה – מציב את ה־ID שלה
            form.company_id.data = str(existing_company.id)
            form.other_company.data = ""
        else:
            # אם לא, סביר שזו "חברה אחרת" שלא קיימת ב־DB
            form.company_id.data = "other"
            form.other_company.data = coupon.company

        if coupon.expiration:
            if isinstance(coupon.expiration, str):
                try:
                    coupon.expiration = datetime.strptime(
                        coupon.expiration, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    try:
                        coupon.expiration = datetime.strptime(
                            coupon.expiration, "%d/%m/%Y"
                        ).date()
                    except ValueError:
                        coupon.expiration = None
        form.expiration.data = coupon.expiration
        form.tags.data = ", ".join([tag.name for tag in coupon.tags])

    existing_tags = ", ".join([tag.name for tag in coupon.tags])
    top_tags = Tag.query.order_by(Tag.count.desc()).limit(3).all()
    top_tags = [tag.name for tag in top_tags]

    return render_template(
        "edit_coupon.html",
        form=form,
        coupon=coupon,
        existing_tags=existing_tags,
        top_tags=top_tags,
    )


@coupons_bp.route("/delete_coupons", methods=["GET", "POST"])
@login_required
def select_coupons_to_delete():
    # -- activity log snippet --
    # log_user_activity("select_coupons_to_delete_view", None)

    form = DeleteCouponsForm()
    coupons = (
        Coupon.query.filter_by(user_id=current_user.id)
        .order_by(Coupon.date_added.desc())
        .all()
    )
    form.coupon_ids.choices = [
        (coupon.id, f"{coupon.company} - {coupon.code}") for coupon in coupons
    ]

    if form.validate_on_submit():
        selected_ids = form.coupon_ids.data
        if selected_ids:
            Coupon.query.filter(Coupon.id.in_(selected_ids)).delete(
                synchronize_session=False
            )
            db.session.commit()

            try:
                new_activity = {
                    "user_id": current_user.id,
                    "coupon_id": None,
                    "timestamp": datetime.utcnow(),
                    "action": f"deleted_coupons_{selected_ids}",
                    "device": request.headers.get("User-Agent", "")[:50],
                    "browser": request.headers.get("User-Agent", "").split(" ")[0][:50]
                    if request.headers.get("User-Agent", "")
                    else None,
                    "ip_address": ip_address[:45] if ip_address else None,
                    "geo_location": get_geo_location(ip_address)[:100],
                }
                db.session.execute(
                    text(
                        """
                        INSERT INTO user_activities
                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                        VALUES
                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                    """
                    ),
                    new_activity,
                )
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Error logging activity [deleted_coupons]: {e}"
                )

            flash("הקופונים נמחקו בהצלחה.", "success")
        else:
            flash("לא נבחרו קופונים למחיקה.", "warning")
        return redirect(url_for("coupons.show_coupons"))

    return render_template("delete_coupons.html", form=form, coupons=coupons)


def get_companies():
    response = supabase.table("companies").select("*").execute()
    if response.status_code == 200:
        return response.data
    else:
        print("Error fetching companies:", response.error_message)
        return []


# ---------- Route ----------
@coupons_bp.route("/coupon_detail/<int:id>")
@login_required
def coupon_detail(id):
    """
    Display full details for a specific coupon.

    Only the user who owns the coupon can view this page.
    Any other user receives a 404 response *without* revealing
    whether the coupon exists.
    """

    # ------------------------------------------------------------------
    # 1) Fetch the coupon **only** if the current user is the owner.
    #    first_or_404() automatically returns a 404 error if no record
    #    matches (either coupon does not exist OR belongs to someone else).
    # ------------------------------------------------------------------
    coupon = Coupon.query.filter_by(id=id, user_id=current_user.id).first_or_404()

    # At this point we know the viewer is the owner.
    is_owner = True

    # ------------------------------------------------------------------
    # 2) Initialize WTForms instances used in the template.
    # ------------------------------------------------------------------
    mark_form = MarkCouponAsUsedForm()
    delete_form = DeleteCouponForm()
    update_form = UpdateCouponUsageForm()

    # A flag that controls whether the "Multipass" button is shown.
    show_multipass_button = coupon.auto_download_details is not None

    # Get tour progress and determine if tour should be shown
    tour_progress = UserTourProgress.query.filter_by(user_id=current_user.id).first()
    should_show_tour = tour_progress is None or tour_progress.coupon_detail_timestamp is None
    coupon_detail_timestamp = tour_progress.coupon_detail_timestamp if tour_progress else None

    # ------------------------------------------------------------------
    # 3) Consolidate usage / transaction rows *exactly like before*.
    #    (Your original SQL kept; modified only for readability.)
    # ------------------------------------------------------------------
    sql = text(
        """
        WITH CouponFilter AS (
            SELECT DISTINCT coupon_id
            FROM coupon_transaction
            WHERE source = 'Multipass'
        ),
        CombinedData AS (
            SELECT
                'coupon_usage' AS source_table,
                id,
                coupon_id,
                -used_amount AS transaction_amount,
                timestamp,
                action,
                details,
                NULL  AS location,
                0     AS recharge_amount,
                NULL  AS reference_number,
                NULL  AS source
            FROM coupon_usage
            WHERE details NOT LIKE '%Multipass%'

            UNION ALL

            SELECT
                'coupon_transaction' AS source_table,
                id,
                coupon_id,
                -usage_amount + recharge_amount AS transaction_amount,
                transaction_date AS timestamp,
                source AS action,
                CASE WHEN location IS NOT NULL AND location <> ''
                     THEN location ELSE NULL END AS details,
                location,
                recharge_amount,
                reference_number,
                source
            FROM coupon_transaction
        ),
        SummedData AS (
            SELECT
                source_table, id, coupon_id, timestamp,
                transaction_amount, details, action
            FROM CombinedData
            WHERE coupon_id = :coupon_id
              AND (
                  coupon_id NOT IN (SELECT coupon_id FROM CouponFilter)
                  OR (source_table = 'coupon_transaction' AND action = 'Multipass')
              )

            UNION ALL

            SELECT
                'sum_row'        AS source_table,
                NULL             AS id,
                coupon_id,
                NULL             AS timestamp,
                SUM(transaction_amount) AS transaction_amount,
                'יתרה בקופון'   AS details,
                NULL             AS action
            FROM CombinedData
            WHERE coupon_id = :coupon_id
              AND (
                  coupon_id NOT IN (SELECT coupon_id FROM CouponFilter)
                  OR (source_table = 'coupon_transaction' AND action = 'Multipass')
              )
            GROUP BY coupon_id
        )
        SELECT source_table, id, coupon_id, timestamp,
               transaction_amount, details, action
        FROM   SummedData
        ORDER  BY CASE WHEN timestamp IS NULL THEN 1 ELSE 0 END,
                 timestamp ASC;
    """
    )

    result = db.session.execute(sql, {"coupon_id": coupon.id})
    consolidated_rows = result.fetchall()

    # ------------------------------------------------------------------
    # 4) Extra calculations for display (discount, logo, etc.).
    # ------------------------------------------------------------------
    discount_percentage = None
    if coupon.is_for_sale and coupon.value > 0:
        discount_percentage = round(
            ((coupon.value - coupon.cost) / coupon.value) * 100, 2
        )

    companies = Company.query.order_by(Company.name).all()
    company_logo_mapping = {c.name.lower(): c.image_path for c in companies}
    company_logo = company_logo_mapping.get(
        coupon.company.lower(), "images/default_logo.png"
    )

    # ------------------------------------------------------------------
    # 5) Render the template with all the gathered context.
    # ------------------------------------------------------------------
    return render_template(
        "coupon_detail.html",
        coupon=coupon,
        is_owner=is_owner,  # always True here
        mark_form=mark_form,
        delete_form=delete_form,
        update_form=update_form,
        consolidated_rows=consolidated_rows,
        discount_percentage=discount_percentage,
        company_logo=company_logo,
        cvv=coupon.cvv,
        card_exp=coupon.card_exp,
        show_multipass_button=show_multipass_button,
        should_show_tour=should_show_tour,
        coupon_detail_timestamp=coupon_detail_timestamp
    )


@coupons_bp.route("/delete_coupon/<int:id>", methods=["POST"])
@login_required
def delete_coupon(id):
    # -- activity log snippet --
    # log_user_activity("delete_coupon_attempt", id)

    form = DeleteCouponForm()
    if form.validate_on_submit():
        coupon = Coupon.query.get_or_404(id)
        if coupon.user_id != current_user.id:
            flash("אינך מורשה למחוק קופון זה.", "danger")
            return redirect(url_for("coupons.show_coupons"))

        transactions = Transaction.query.filter_by(coupon_id=coupon.id).all()
        if transactions:
            return redirect(url_for("coupons.confirm_delete_coupon", id=id))
        else:
            for tag in coupon.tags:
                tag.count -= 1
                if tag.count < 0:
                    tag.count = 0

            data_directory = "automatic_coupon_update/input_html"
            xlsx_filename = f"coupon_{coupon.code}_{coupon.id}.xlsx"
            xlsx_path = os.path.join(data_directory, xlsx_filename)
            if os.path.exists(xlsx_path):
                os.remove(xlsx_path)

            db.session.delete(coupon)
            try:
                db.session.commit()

                try:
                    success_activity = {
                        "user_id": current_user.id,
                        "coupon_id": id,
                        "timestamp": datetime.utcnow(),
                        "action": "delete_coupon_success",
                        "device": request.headers.get("User-Agent", "")[:50],
                        "browser": request.headers.get("User-Agent", "").split(" ")[0][
                            :50
                        ]
                        if request.headers.get("User-Agent", "")
                        else None,
                        "ip_address": ip_address[:45] if ip_address else None,
                        "geo_location": get_geo_location(ip_address)[:100],
                    }
                    db.session.execute(
                        text(
                            """
                            INSERT INTO user_activities 
                                (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                            VALUES 
                                (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                        """
                        ),
                        success_activity,
                    )
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(
                        f"Error logging activity [delete_coupon_success]: {e}"
                    )

                flash(f'קופון "{coupon.code}" נמחק בהצלחה!', "success")
                return redirect(url_for("coupons.show_coupons"))
            except:
                db.session.rollback()
                flash("שגיאה בעת מחיקת הקופון.", "danger")
                return redirect(url_for("coupons.show_coupons"))
    else:
        flash("שגיאה במחיקת הקופון. נסה שוב.", "danger")
        return redirect(url_for("coupons.show_coupons"))


@coupons_bp.route("/confirm_delete_coupon/<int:id>", methods=["GET", "POST"])
@login_required
def confirm_delete_coupon(id):
    coupon = Coupon.query.get_or_404(id)

    # -- activity log snippet --
    # log_user_activity("confirm_delete_coupon_view", coupon.id)

    if coupon.user_id != current_user.id:
        flash("אינך מורשה למחוק קופון זה.", "danger")
        return redirect(url_for("coupons.show_coupons"))

    form = ConfirmDeleteForm()
    if form.validate_on_submit():
        if form.submit.data:
            try:
                transactions = Transaction.query.filter_by().all()
                for transaction in transactions:
                    db.session.delete(transaction)

                for tag in coupon.tags:
                    tag.count -= 1
                    if tag.count < 0:
                        tag.count = 0

                data_directory = "automatic_coupon_update/input_html"
                xlsx_filename = f"coupon_{coupon.code}_{coupon.id}.xlsx"
                xlsx_path = os.path.join(data_directory, xlsx_filename)
                if os.path.exists(xlsx_path):
                    os.remove(xlsx_path)

                db.session.delete(coupon)
                db.session.commit()
                flash(f'קופון "{coupon.code}" נמחק בהצלחה!', "success")
                return redirect(url_for("coupons.show_coupons"))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error deleting coupon {coupon.id}: {e}")
                flash("אירעה שגיאה במחיקת הקופון. נסה שוב.", "danger")
        elif form.cancel.data:
            flash("המחיקה בוטלה.", "info")
            return redirect(url_for("coupons.coupon_detail", id=id))

    return render_template("confirm_delete.html", coupon=coupon, form=form)


@coupons_bp.route("/edit_usage/<int:usage_id>", methods=["GET", "POST"])
@login_required
def edit_usage(usage_id):
    usage = CouponUsage.query.get_or_404(usage_id)
    coupon = Coupon.query.get_or_404(usage.coupon_id)

    # -- activity log snippet --
    # log_user_activity("edit_usage_view", coupon_id)

    if coupon.user_id != current_user.id:
        flash("אינך מורשה לערוך שימוש זה.", "danger")
        return redirect(url_for("coupons.show_coupons"))

    if request.method == "POST":
        new_used_amount = float(request.form["used_amount"])
        if new_used_amount <= 0:
            flash("כמות השימוש חייבת להיות חיובית.", "danger")
            return redirect(url_for("coupons.edit_usage", usage_id=usage_id))

        coupon.used_value -= usage.used_amount
        if (coupon.used_value + new_used_amount) > coupon.value:
            flash("הכמות שהשתמשת בה גדולה מערך הקופון הנותר.", "danger")
            coupon.used_value += usage.used_amount
            return redirect(url_for("coupons.edit_usage", usage_id=usage_id))

        usage.used_amount = new_used_amount
        coupon.used_value += new_used_amount
        update_coupon_status(coupon)

        db.session.commit()

        # -- activity log snippet --
        try:
            new_activity = {
                "user_id": current_user.id,
                "coupon_id": coupon.id,
                "timestamp": datetime.utcnow(),
                "action": "edit_usage_success",
                "device": request.headers.get("User-Agent", "")[:50],
                "browser": request.headers.get("User-Agent", "").split(" ")[0][:50]
                if request.headers.get("User-Agent", "")
                else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": get_geo_location(ip_address)[:100],
            }
            db.session.execute(
                text(
                    """
                    INSERT INTO user_activities 
                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                    VALUES 
                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                """
                ),
                new_activity,
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error logging activity [edit_usage_success]: {e}"
            )

        flash("רשומת השימוש עודכנה בהצלחה!", "success")
        return redirect(url_for("coupons.coupon_detail", id=coupon.id))

    return render_template("edit_usage.html", usage=usage, coupon=coupon)


@coupons_bp.route("/update_all_coupons/process", methods=["GET", "POST"])
@login_required
def update_all_coupons_route():
    # -- activity log snippet --
    # log_user_activity("update_all_coupons_process", None)

    updated, failed = update_all_active_coupons()
    if updated:
        flash(f"הקופונים הבאים עודכנו: {', '.join(updated)}", "success")
    if failed:
        flash(f"הקופונים הבאים נכשלו: {', '.join(failed)}", "danger")
    return redirect(url_for("coupons.show_coupons"))


@coupons_bp.route("/get_tags")
@login_required
def get_tags():
    # -- activity log snippet --
    # log_user_activity("get_tags", None)

    tags = [tag.name for tag in Tag.query.all()]
    return jsonify(tags)


@coupons_bp.route("/usage_order")
@login_required
def usage_order():
    # -- activity log snippet --
    # log_user_activity("usage_order_view", None)

    valid_coupons = (
        Coupon.query.filter(Coupon.status == "פעיל", Coupon.user_id == current_user.id)
        .order_by((Coupon.used_value / Coupon.value).desc())
        .all()
    )

    expired_coupons = (
        Coupon.query.filter(
            Coupon.status == "פג תוקף", Coupon.user_id == current_user.id
        )
        .order_by((Coupon.used_value / Coupon.value).desc())
        .all()
    )

    return render_template(
        "usage_order.html", valid_coupons=valid_coupons, expired_coupons=expired_coupons
    )


@coupons_bp.route("/export_excel")
@login_required
def export_excel():
    # -- activity log snippet --
    # log_user_activity("export_excel", None)

    coupons = Coupon.query.filter_by(user_id=current_user.id).all()
    data = []
    for coupon in coupons:
        data.append(
            {
                "קוד קופון": coupon.code,
                "חברה": coupon.company,
                "ערך מקורי": coupon.value,
                "עלות": coupon.cost,
                "ערך שהשתמשת בו": coupon.used_value,
                "ערך נותר": coupon.remaining_value,
                "סטטוס": coupon.status,
                "תאריך תפוגה": coupon.expiration or "",
                "תאריך הוספה": coupon.date_added.strftime("%Y-%m-%d %H:%M"),
                "תיאור": coupon.description or "",
                "CVV": coupon.cvv if coupon.cvv else "",
                "תוקף כרטיס": coupon.card_exp if coupon.card_exp else "",
            }
        )

    df = pd.DataFrame(data)
    output = BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="קופונים")

    output.seek(0)
    return send_file(
        output,
        download_name="coupons.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@coupons_bp.route("/export_pdf")
@login_required
def export_pdf():
    # -- activity log snippet --
    # log_user_activity("export_pdf", None)

    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont("DejaVuSans", "DejaVuSans.ttf"))

    coupons = Coupon.query.filter_by(user_id=current_user.id).all()
    output = BytesIO()
    p = canvas.Canvas(output, pagesize=letter)
    p.setFont("DejaVuSans", 12)

    y = 750
    for coupon in coupons:
        text = f"קוד קופון: {coupon.code}, חברה: {coupon.company}, יתרה לניצול: {coupon.remaining_value} ₪"
        p.drawRightString(550, y, text)
        y -= 20
        if y < 50:
            p.showPage()
            p.setFont("DejaVuSans", 12)
            y = 750

    p.save()
    output.seek(0)
    return send_file(
        output,
        download_name="coupons.pdf",
        as_attachment=True,
        mimetype="application/pdf",
    )


@coupons_bp.route("/delete_coupon_request/<int:id>", methods=["POST"])
@login_required
def delete_coupon_request(id):
    coupon_request = CouponRequest.query.get_or_404(id)

    # -- activity log snippet --
    # log_user_activity("delete_coupon_request_attempt", None)

    if coupon_request.user_id != current_user.id:
        flash("אין לך הרשאה למחוק בקשה זו.", "danger")
        return redirect(url_for("coupons.marketplace"))

    try:
        db.session.delete(coupon_request)
        db.session.commit()

        # לוג הצלחת המחיקה
        try:
            new_activity = {
                "user_id": current_user.id,
                "coupon_id": None,
                "timestamp": datetime.utcnow(),
                "action": "delete_coupon_request_success",
                "device": request.headers.get("User-Agent", "")[:50],
                "browser": request.headers.get("User-Agent", "").split(" ")[0][:50]
                if request.headers.get("User-Agent", "")
                else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": get_geo_location(ip_address)[:100],
            }
            db.session.execute(
                text(
                    """
                    INSERT INTO user_activities
                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                    VALUES
                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                """
                ),
                new_activity,
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error logging activity [delete_coupon_request_success]: {e}"
            )

        flash("בקשת הקופון נמחקה בהצלחה.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting coupon request {id}: {e}")
        flash("אירעה שגיאה בעת מחיקת הבקשה.", "danger")

    return redirect(url_for("transactions.my_transactions"))


def complete_transaction(transaction):
    # -- activity log snippet --
    try:
        user_agent = request.headers.get("User-Agent", "") if request else ""
        geo_location = get_geo_location(ip_address) if request else "N/A"
        activity = {
            "user_id": transaction.seller_id,
            "coupon_id": transaction.coupon_id,
            "timestamp": datetime.utcnow(),
            "action": "complete_transaction",
            "device": user_agent[:50] if user_agent else None,
            "browser": user_agent.split(" ")[0][:50] if user_agent else None,
            "ip_address": ip_address[:45]
            if ip_address
            else None
            if ip_address != "N/A"
            else "N/A",
            "geo_location": geo_location[:100] if geo_location != "N/A" else "N/A",
        }
        db.session.execute(
            text(
                """
                INSERT INTO user_activities 
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                VALUES 
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
            """
            ),
            activity,
        )
        db.session.commit()
    except:
        db.session.rollback()
    # -- end snippet --

    try:
        coupon = transaction.coupon
        coupon.user_id = transaction.buyer_id
        coupon.is_for_sale = False
        coupon.is_available = True
        transaction.status = "הושלם"

        notification_buyer = Notification(
            user_id=transaction.buyer_id,
            message="הקופון הועבר לחשבונך.",
            link=url_for("coupons.coupon_detail", id=coupon.id),
        )
        notification_seller = Notification(
            user_id=transaction.seller_id,
            message="העסקה הושלמה והקופון הועבר לקונה.",
            link=url_for("transactions.my_transactions"),
        )

        db.session.add(notification_buyer)
        db.session.add(notification_seller)
        db.session.commit()
        flash("העסקה הושלמה בהצלחה והקופון הועבר לקונה!", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error completing transaction {transaction.id}: {e}")
        flash("אירעה שגיאה בעת השלמת העסקה. נא לנסות שוב.", "danger")


@coupons_bp.route("/send_coupon_expiration_warning/<int:coupon_id>")
def send_coupon_expiration_warning(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)

    # -- activity log snippet --
    # log_user_activity("send_coupon_expiration_warning", coupon.id)

    user = coupon.user
    expiration_date = coupon.expiration
    coupon_detail_link = request.host_url.rstrip("/") + url_for(
        "coupons.coupon_detail", id=coupon.id
    )

    html_content = render_template(
        "emails/coupon_expiration_warning.html",
        user=user,
        coupon=coupon,
        expiration_date=expiration_date,
        coupon_detail_link=coupon_detail_link,
    )

    send_email(
        sender_email="noreply@couponmasteril.com",
        sender_name="Coupon Master",
        recipient_email=user.email,
        recipient_name=f"{user.first_name} {user.last_name}",
        subject="התראה על תפוגת תוקף קופון",
        html_content=html_content,
    )

    flash("אימייל התראה על תפוגת תוקף קופון נשלח.", "success")
    return redirect(url_for("coupons.show_coupons"))


@coupons_bp.route("/mark_coupon_as_used/<int:id>", methods=["POST"])
@login_required
def mark_coupon_as_used(id):
    coupon = Coupon.query.get_or_404(id)

    # -- activity log snippet --
    # log_user_activity("mark_coupon_as_used", coupon.id)

    if coupon.user_id != current_user.id:
        flash("אין לך הרשאה לבצע פעולה זו.", "danger")
        return redirect(url_for("coupons.show_coupons"))

    try:
        # במקום לבדוק is_one_time, נאפשר לכל קופון לסמן כ"נוצל לגמרי".
        coupon.used_value = coupon.value
        update_coupon_status(coupon)

        # יוצרים רשומה בהיסטוריית השימוש (CouponUsage)
        usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=coupon.value,  # סימון כנוצל לגמרי
            timestamp=datetime.now(timezone.utc),
            action="נוצל לגמרי",
            details='סומן על ידי המשתמש כ"נוצל לגמרי".',
        )
        db.session.add(usage)

        # שולחים נוטיפיקציה
        """""" """
        notification = Notification(
            user_id=coupon.user_id,
            message=f"הקופון {coupon.code} סומן כנוצל לגמרי.",
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )
        db.session.add(notification)
        """ """"""

        db.session.commit()

        flash('הקופון סומן בהצלחה כ"נוצל לגמרי".', "success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking coupon as fully used: {e}")
        flash("אירעה שגיאה בעת סימון הקופון כנוצל לגמרי.", "danger")

    return redirect(url_for("coupons.coupon_detail", id=id))


@coupons_bp.route(
    "/update_coupon_usage_from_multipass/<int:id>", methods=["GET", "POST"]
)
@login_required
def update_coupon_usage_from_multipass(id):
    """
    מושך נתונים מ־Multipass עבור קופון קיים ומעדכן ב־DB,
    רק אם המשתמש בעל ההרשאה (לצורך הדוגמה: רק אימייל ספציפי).
    """
    # קודם נשלוף את הקופון:
    coupon = Coupon.query.get_or_404(id)
    # כעת יש לנו coupon.id, אפשר ללוגג
    # log_user_activity("update_coupon_usage_from_multipass", coupon.id)

    if coupon.is_one_time:
        flash("קופון חד-פעמי – אין צורך בעדכון שימוש מ-Multipass.", "warning")
        return redirect(url_for("coupons.coupon_detail", id=id))

    # מעבירים את אובייקט הקופון, ולא רק את code
    df = get_coupon_data(coupon)
    if df is None:
        flash("לא ניתן לעדכן את השימוש מ-Multipass.", "danger")
        return redirect(url_for("coupons.coupon_detail", id=id))

    try:
        # לפי הסכמה החדשה, "usage_amount" בעמודה
        total_usage = df["usage_amount"].sum()
        coupon.used_value = float(total_usage)
        update_coupon_status(coupon)

        usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=total_usage,
            timestamp=datetime.now(timezone.utc),
            action="עדכון מ-Multipass",
            details="שימוש מעודכן מ-Multipass.",
        )
        db.session.add(usage)
        """""" """
        notification = Notification(
            user_id=coupon.user_id,
            message=f"השימוש בקופון {coupon.code} עודכן מ-Multipass.",
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )
        db.session.add(notification)
        """ """"""
        db.session.commit()

        flash("השימוש עודכן בהצלחה מ-Multipass.", "success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating coupon usage from Multipass: {e}")
        flash("אירעה שגיאה בעת עדכון השימוש.", "danger")

    return redirect(url_for("coupons.coupon_detail", id=id))


@coupons_bp.route("/update_coupon_usage/<int:id>", methods=["GET", "POST"])
@login_required
def update_coupon_usage_route(id):
    coupon = Coupon.query.get_or_404(id)

    # שליפת רשימת החברות ובניית מיפוי לוגו
    companies = Company.query.order_by(Company.name).all()
    company_logo_mapping = {c.name.lower(): c.image_path for c in companies}
    for company_name in company_logo_mapping:
        if not company_logo_mapping[company_name]:
            company_logo_mapping[company_name] = "images/default.png"

    is_owner = current_user.id == coupon.user_id

    # אם הקופון לא שלך, חסימה
    if not is_owner:
        flash("אין לך הרשאה לבצע פעולה זו.", "danger")
        return redirect(url_for("coupons.show_coupons"))

    # אם הקופון חד-פעמי, פשוט מסמנים כנוצל
    if coupon.is_one_time:
        coupon.status = "נוצל"
        try:
            db.session.commit()
            flash('סטטוס הקופון עודכן בהצלחה ל"נוצל".', "success")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating one-time coupon status: {e}")
            flash("אירעה שגיאה בעת עדכון סטטוס הקופון.", "danger")
        return redirect(url_for("coupons.coupon_detail", id=id))

    form = UpdateCouponUsageForm()
    mark_fully_used_form = MarkCouponAsUsedForm()

    if form.validate_on_submit():
        new_used_amount = form.used_amount.data
        if new_used_amount < 0:
            flash("כמות השימוש חייבת להיות חיובית.", "danger")
            return redirect(url_for("coupons.update_coupon_usage_route", id=id))

        if (coupon.used_value + new_used_amount) > coupon.value:
            flash("הכמות שהשתמשת בה גדולה מערך הקופון הנותר.", "danger")
            return redirect(url_for("coupons.update_coupon_usage_route", id=id))

        try:
            update_coupon_usage(coupon, new_used_amount, details="שימוש ידני")
            flash("כמות השימוש עודכנה בהצלחה.", "success")
            return redirect(url_for("coupons.coupon_detail", id=coupon.id))
        except Exception as e:
            flash("אירעה שגיאה בעת עדכון כמות השימוש.", "danger")
            current_app.logger.error(f"Error updating coupon usage: {e}")

    return render_template(
        "update_coupon_usage.html",
        coupon=coupon,
        is_owner=is_owner,
        form=form,
        mark_fully_used_form=mark_fully_used_form,
        company_logo_mapping=company_logo_mapping,
    )


@coupons_bp.route("/update_all_active_coupons", methods=["POST"])
@login_required
def update_all_active_coupons():
    """
    עדכון מרוכז של כל הקופונים הפעילים שאינם חד-פעמיים, רק אם המשתמש הנוכחי הוא admin.
    מושך נתונים מ־Multipass עבור כל קופון בנפרד.
    """
    if not current_user.is_admin:
        flash("אין לך הרשאה לבצע פעולה זו.", "danger")
        return redirect(url_for("profile.index"))

    active_coupons = Coupon.query.filter(
        Coupon.status == "פעיל",
        Coupon.is_one_time == False,
        Coupon.auto_download_details.isnot(
            None
        ),  # רק קופונים שיש להם auto_download_details
    ).all()

    updated_coupons = []
    failed_coupons = []

    for cpn in active_coupons:
        try:
            df = get_coupon_data(cpn)  # מעבירים קופון שלם
            if df is not None:
                total_usage = float(df["usage_amount"].sum())
                cpn.used_value = total_usage
                update_coupon_status(cpn)

                usage = CouponUsage(
                    coupon_id=cpn.id,
                    used_amount=total_usage,
                    timestamp=datetime.now(timezone.utc),
                    action="עדכון מרוכז",
                    details="עדכון מתוך Multipass",
                )
                db.session.add(usage)

                """""" """
                notification = Notification(
                    user_id=cpn.user_id,
                    message=f"השימוש בקופון {cpn.code} עודכן מ-Multipass.",
                    link=url_for('coupons.coupon_detail', id=cpn.id)
                )
                db.session.add(notification)
                """ """"""

                updated_coupons.append(cpn.code)
            else:
                failed_coupons.append(cpn.code)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating coupon {cpn.code}: {e}")
            failed_coupons.append(cpn.code)

    db.session.commit()

    if updated_coupons:
        flash(f'הקופונים הבאים עודכנו בהצלחה: {", ".join(updated_coupons)}', "success")
    if failed_coupons:
        flash(f'הקופונים הבאים לא עודכנו: {", ".join(failed_coupons)}', "danger")

    return redirect(url_for("profile.index"))


@coupons_bp.route("/update_coupon_transactions", methods=["POST"])
@login_required
def update_coupon_transactions():
    """
    פעולה ידנית לאדמין: עדכון נתוני שימוש/הטענות של קופון מסויים
    לפי מזהה קופון או code שמגיע ב-POST.
    """
    # log_user_activity("update_coupon_transactions_attempt")

    if not current_user.is_admin:
        flash("אין לך הרשאה לבצע פעולה זו.", "danger")
        coupon_id = request.form.get("coupon_id")
        coupon_code = request.form.get("coupon_code")

        # לא מאתרים? מפנים חזרה
        coupon = None
        if coupon_id:
            coupon = Coupon.query.get(coupon_id)
        elif coupon_code:
            coupon = Coupon.query.filter_by(code=coupon_code).first()

        if coupon:
            return redirect(url_for("transactions.coupon_detail", id=coupon.id))
        else:
            flash("לא ניתן לעדכן נתונים ללא מזהה קופון תקין.", "danger")
            return redirect(url_for("transactions.my_transactions"))

    # אם אנחנו כן אדמין, מנסים לאתר את הקופון
    coupon_id = request.form.get("coupon_id")
    coupon_code = request.form.get("coupon_code")
    coupon = None

    if coupon_id:
        coupon = Coupon.query.get(coupon_id)
    elif coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()

    if not coupon:
        flash("לא ניתן לעדכן נתונים ללא מזהה קופון תקין.", "danger")
        return redirect(url_for("coupons.coupon_detail"))

    try:
        df = get_coupon_data(coupon)  # מעבירים את האובייקט
        if df is not None:
            total_usage = float(df["usage_amount"].sum())
            coupon.used_value = total_usage
            update_coupon_status(coupon)

            usage = CouponUsage(
                coupon_id=coupon.id,
                used_amount=total_usage,
                timestamp=datetime.now(timezone.utc),
                action="עדכון מרוכז",
                details="עדכון מתוך Multipass",
            )
            db.session.add(usage)

            """""" """
            notification = Notification(
                user_id=coupon.user_id,
                message=f"השימוש בקופון {coupon.code} עודכן מ-Multipass.",
                link=url_for('coupons.coupon_detail', id=coupon.id)
            )
            db.session.add(notification)
            """ """"""
            flash(f"הקופון עודכן בהצלחה: {coupon.code}", "success")
        else:
            current_app.logger.error(
                f"Error updating coupon {coupon.code} (no DataFrame returned)."
            )
            db.session.rollback()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating coupon {coupon.code}: {e}")

    db.session.commit()
    return redirect(url_for("coupons.coupon_detail", id=coupon.id))


####################################################################################################
# טיפול בטקסט לקופון שמשתמש מזין במסך הראשי ועובר דרך gpt
####################################################################################################
from app.forms import UsageExplanationForm
from app.helpers import parse_user_usage_text


@coupons_bp.route("/parse_usage_text", methods=["POST"])
@login_required
def parse_usage_text():
    # שלב 1: בדיקת טופס
    form = UsageExplanationForm()
    if form.validate_on_submit():
        usage_text = form.usage_explanation.data.strip()
        if not usage_text:
            # בבקשת AJAX החזר שגיאה
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "message": "לא הוזן טקסט."}), 400
            # אחרת הצג הודעה ונתב בחזרה לדף הראשי
            flash("לא הוזן טקסט.", "danger")
            return redirect(url_for("profile.index"))

        # שלב 2: קריאה ל-GPT
        try:
            usage_df, gpt_usage_df = parse_user_usage_text(usage_text, current_user)

            # נשמור את שורת ה-GPT בטבלת GptUsage אם יש
            if not gpt_usage_df.empty:
                from app.models import GptUsage

                row = gpt_usage_df.iloc[0]
                new_gpt = GptUsage(
                    user_id=current_user.id,
                    created=datetime.strptime(row["created"], "%Y-%m-%d %H:%M:%S"),
                    id=row["id"],
                    object=row["object"],
                    model=row["model"],
                    prompt_tokens=int(row["prompt_tokens"]),
                    completion_tokens=int(row["completion_tokens"]),
                    total_tokens=int(row["total_tokens"]),
                    cost_usd=float(row["cost_usd"]),
                    cost_ils=float(row["cost_ils"]),
                    exchange_rate=float(row["exchange_rate"]),
                    prompt_text=np.nan,
                    response_text=np.nan,
                )
                db.session.add(new_gpt)
                db.session.commit()

            if usage_df.empty:
                # לא נמצאו שימושים
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": "לא זוהו שימושים בקופונים מהטקסט שהוזן.",
                            }
                        ),
                        404,
                    )
                flash("לא זוהו שימושים בקופונים מהטקסט שהוזן.", "danger")
                return redirect(url_for("profile.index"))

            # בודקים אם יש למשתמש סלוטים פנויים לשימוש ב־GPT
            if current_user.slots_automatic_coupons <= 0:
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": "אין לך מספיק סלוטים למילוי אוטומטי.",
                            }
                        ),
                        403,
                    )
                flash("אין לך מספיק סלוטים למילוי אוטומטי.", "danger")
                return redirect(url_for("profile.index"))

            # מנכים סלוט אחד
            current_user.slots_automatic_coupons -= 1
            db.session.commit()

            # שלב 3: שמירת usage_df ב-Session
            session["parsed_usages"] = usage_df.to_dict(orient="records")

            # בבקשת AJAX - החזר הוראה לטעון את המודל במצב סקירה
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                # שינוי כאן: במקום show_review, אנחנו נותנים כתובת URL למודל
                return jsonify(
                    {
                        "success": True,
                        "message": "הטקסט נותח בהצלחה",
                        "reload_modal": True,
                        "modal_url": url_for(
                            "coupons.load_review_modal"
                        ),  # חדש: כתובת URL למודל הסקירה
                    }
                )

            # ניתוב למסך הסקירה (עובד בבקשה רגילה - שלא AJAX)
            return redirect(url_for("coupons.review_usage_findings"))

        except Exception as e:
            current_app.logger.error(f"Error in parse_usage_text: {e}")
            traceback.print_exc()
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "אירעה שגיאה בעת ניתוח הטקסט עם GPT.",
                        }
                    ),
                    500,
                )
            flash("אירעה שגיאה בעת ניתוח הטקסט עם GPT.", "danger")
            return redirect(url_for("profile.index"))
    else:
        # הטופס לא עבר אימות
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return (
                jsonify({"success": False, "message": "יש למלא את הטופס כראוי."}),
                400,
            )
        flash("יש למלא את הטופס כראוי.", "danger")
        return redirect(url_for("profile.index"))


@coupons_bp.route("/load_review_modal")
@login_required
def load_review_modal():
    """מחזיר את תוכן המודל לסקירת השימושים המזוהים"""
    # מקבל נתונים מהסשן
    usage_list = session.get("parsed_usages", [])

    if not usage_list:
        return jsonify({"success": False, "message": "לא נמצאו נתוני שימוש"})

    # שולפים את כל הקופונים הפעילים של המשתמש
    all_user_coupons = [cpn for cpn in current_user.coupons if cpn.status == "פעיל"]

    if not all_user_coupons:
        return jsonify(
            {"success": False, "message": "אין לך קופונים פעילים שניתן להשתמש בהם"}
        )

    # מחפשים קופונים מתאימים לפי דמיון לכל שימוש שזוהה
    for row in usage_list:
        row_company = row.get("company", "").lower()
        matched_coupons = []

        for cpn in all_user_coupons:
            # משתמשים בכמה אלגוריתמים לזיהוי דמיון טקסט
            ratio = fuzz.ratio(row_company, cpn.company.lower())
            partial_ratio = fuzz.partial_ratio(row_company, cpn.company.lower())
            token_sort_ratio = fuzz.token_sort_ratio(row_company, cpn.company.lower())

            # לוקחים את הציון הגבוה ביותר מכל האלגוריתמים
            similarity = max(ratio, partial_ratio, token_sort_ratio)
            remaining_balance = cpn.value - cpn.used_value

            print(
                f"Similarity between '{row_company}' and '{cpn.company.lower()}': {similarity}"
            )

            if similarity >= 60:  # רף מופחת לקבלת יותר התאמות
                matched_coupons.append(
                    {
                        "id": cpn.id,
                        "company": cpn.company,
                        "code": cpn.code,
                        "remaining_balance": remaining_balance,
                    }
                )

        # אם אין התאמות טובות, נחזיר את כל הקופונים הפעילים
        if not matched_coupons:
            print(
                f"No good matches found for '{row_company}', including all active coupons"
            )
            matched_coupons = [
                {
                    "id": cpn.id,
                    "company": cpn.company,
                    "code": cpn.code,
                    "remaining_balance": cpn.value - cpn.used_value,
                }
                for cpn in all_user_coupons
            ]

        row["matched_coupons"] = matched_coupons

    # מחזירים את תוכן המודל בלבד (לא עמוד שלם)
    form = UsageExplanationForm()
    return render_template(
        "review_usage_modal.html",
        usage_list=usage_list,
        current_user=current_user,
        form=form,
    )


@coupons_bp.route("/process_review_form", methods=["POST"])
@login_required
def process_review_form():
    """מעבד את הטופס שנשלח ממסך הסקירה"""
    # בדיקה האם הבקשה היא AJAX
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # שליפת נתונים מהסשן
    parsed_usages = session.get("parsed_usages", [])
    if not parsed_usages:
        if is_ajax:
            return jsonify({"success": False, "message": "לא נמצאו נתוני שימוש"})
        flash("לא נמצאו נתוני שימוש", "warning")
        return redirect(url_for("profile.index"))

    # מעבד את הנתונים שנשלחו מהטופס
    confirmed_usages = []

    # עיבוד כל שורה בטופס
    for i in range(len(parsed_usages)):
        # בדיקה האם השורה סומנה
        checkbox_name = f"row-{i}-checked"
        if checkbox_name not in request.form:
            continue

        # קבלת ערכים
        coupon_id_str = request.form.get(f"row-{i}-company", "")
        amount_str = request.form.get(f"row-{i}-amount", "0")

        # המרת הסכום למספר
        try:
            used_amount = float(amount_str)
        except (ValueError, TypeError):
            if is_ajax:
                return jsonify(
                    {"success": False, "message": f"סכום לא תקין בשורה {i+1}"}
                )
            flash(f"סכום לא תקין בשורה {i+1}", "warning")
            continue

        # בדיקות תקינות
        if not coupon_id_str or coupon_id_str == "other":
            if is_ajax:
                return jsonify(
                    {"success": False, "message": f"לא נבחר קופון בשורה {i+1}"}
                )
            flash(f"לא נבחר קופון בשורה {i+1}", "warning")
            continue

        if used_amount <= 0:
            if is_ajax:
                return jsonify(
                    {
                        "success": False,
                        "message": f"הסכום חייב להיות גדול מאפס בשורה {i+1}",
                    }
                )
            flash(f"הסכום חייב להיות גדול מאפס בשורה {i+1}", "warning")
            continue

        # הוספת השימוש לרשימת השימושים המאושרים
        additional_info = ""
        if i < len(parsed_usages):
            additional_info = parsed_usages[i].get("additional_info", "")

        confirmed_usages.append(
            {
                "company_final": coupon_id_str,
                "used_amount": used_amount,
                "additional_info": additional_info,
            }
        )

    # בדיקה האם יש שימושים מאושרים
    if not confirmed_usages:
        if is_ajax:
            return jsonify({"success": False, "message": "לא נבחרו שימושים לעדכון"})
        flash("לא נבחרו שימושים לעדכון", "warning")
        return redirect(url_for("profile.index"))

    # עדכון הקופונים
    from app.models import Coupon, CouponUsage

    errors = []
    successes = []

    for row in confirmed_usages:
        coupon_id_str = row.get("company_final", "")
        used_amount = float(row.get("used_amount", 0.0))

        # המרת ה-ID לint
        try:
            coupon_id = int(coupon_id_str)
        except ValueError:
            error_msg = f"מזהה קופון לא תקין: {coupon_id_str}"
            errors.append(error_msg)
            continue

        # איתור הקופון
        coupon = Coupon.query.get(coupon_id)
        if not coupon:
            error_msg = f"קופון לא נמצא: {coupon_id_str}"
            errors.append(error_msg)
            continue

        if coupon.user_id != current_user.id:
            error_msg = f"הקופון {coupon.code} אינו שייך למשתמש הנוכחי"
            errors.append(error_msg)
            continue

        # בדיקת יתרה בקופון
        remaining = coupon.value - coupon.used_value
        if used_amount > remaining:
            error_msg = f'ניסית להשתמש ב-{used_amount} ש"ח בקופון {coupon.code}, אך נותרו רק {remaining} ש"ח'
            errors.append(error_msg)
            continue

        # עדכון השימוש
        coupon.used_value += used_amount

        # יצירת רשומת שימוש חדשה
        new_usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=used_amount,
            timestamp=datetime.now(timezone.utc),
            action="שימוש ידני",
            details=row.get("additional_info", "שימוש שהוזן דרך מודל GPT"),
        )
        db.session.add(new_usage)

        # עדכון סטטוס הקופון
        update_coupon_status(coupon)

        # הוספה להודעות הצלחה
        successes.append(f"עודכן שימוש של {used_amount} ₪ בקופון {coupon.code}")

    # שמירת השינויים במסד הנתונים
    try:
        db.session.commit()

        # ניקוי הסשן
        session.pop("parsed_usages", None)

        # החזרת תשובה עבור AJAX
        if is_ajax:
            success_message = "השימושים עודכנו בהצלחה"
            if errors:
                success_message += ", אך חלק מהשימושים לא עודכנו"

            return jsonify(
                {
                    "success": True,
                    "message": success_message,
                    "errors": errors,
                    "successes": successes,
                }
            )

        # הצגת הודעות הצלחה/שגיאה
        if errors:
            error_msg = "חלק מהשימושים לא עודכנו:\n" + "\n".join(errors)
            flash(error_msg, "warning")

        if successes:
            success_msg = "הקופונים הבאים עודכנו בהצלחה:\n" + "\n".join(successes)
            flash(success_msg, "success")

        return redirect(url_for("profile.index"))

    except Exception as e:
        # שגיאה בעת השמירה
        db.session.rollback()
        error_msg = f"שגיאה בעת עדכון השימושים: {str(e)}"

        if is_ajax:
            return jsonify({"success": False, "message": error_msg})

        flash(error_msg, "danger")
        return redirect(url_for("profile.index"))


from thefuzz import fuzz

from app.forms import UsageExplanationForm

# app/routes/coupons_routes.py

# app/routes/coupons_routes.py


@coupons_bp.route("/review_usage", methods=["GET", "POST"])
@login_required
def review_usage_findings():
    """
    מציג את מסך סקירת השימושים שזוהו (עמוד נפרד, לא מודל).
    בעדיפות להשתמש במודל באמצעות load_review_modal, אבל שומרים פונקציה זו כגיבוי.
    """
    # עבור בקשות GET - מציג את מסך הסקירה
    if request.method == "GET":
        # מקבל נתונים מהסשן
        usage_list = session.get("parsed_usages", [])

        if not usage_list:
            flash("לא נמצאו נתוני שימוש. הזן טקסט תחילה.", "danger")
            return redirect(url_for("profile.index"))

        # שולפים את כל הקופונים הפעילים של המשתמש
        all_user_coupons = [cpn for cpn in current_user.coupons if cpn.status == "פעיל"]

        # מחפשים קופונים מתאימים לפי דמיון
        for row in usage_list:
            row_company = row.get("company", "").lower()
            matched_coupons = []

            for cpn in all_user_coupons:
                # אלגוריתמי התאמה
                ratio = fuzz.ratio(row_company, cpn.company.lower())
                partial_ratio = fuzz.partial_ratio(row_company, cpn.company.lower())
                token_sort_ratio = fuzz.token_sort_ratio(
                    row_company, cpn.company.lower()
                )

                # לוקחים את הציון הגבוה ביותר מכל האלגוריתמים
                similarity = max(ratio, partial_ratio, token_sort_ratio)
                remaining_balance = cpn.value - cpn.used_value

                if similarity >= 60:  # סף נמוך יותר להתאמות
                    matched_coupons.append(
                        {
                            "id": cpn.id,
                            "company": cpn.company,
                            "code": cpn.code,
                            "remaining_balance": remaining_balance,
                        }
                    )

            # אם אין התאמות טובות, נכלול את כל הקופונים הפעילים
            if not matched_coupons:
                matched_coupons = [
                    {
                        "id": cpn.id,
                        "company": cpn.company,
                        "code": cpn.code,
                        "remaining_balance": cpn.value - cpn.used_value,
                    }
                    for cpn in all_user_coupons
                ]

            row["matched_coupons"] = matched_coupons

        # מציג את תבנית הסקירה (עמוד מלא)
        form = UsageExplanationForm()
        return render_template(
            "review_usage.html",
            usage_list=usage_list,
            current_user=current_user,
            form=form,
        )

    # עבור בקשות POST - מעבד את הטופס (פתרון פשוט: העברה ל-process_review_form)
    elif request.method == "POST":
        return process_review_form()


@coupons_bp.route("/clear_usage_session", methods=["POST"])
@login_required
def clear_usage_session():
    """מנקה את נתוני השימוש מהסשן וחוזר למצב הזנה"""
    session.pop("parsed_usages", None)
    session.pop("confirmed_usages", None)
    return jsonify({"success": True})


@coupons_bp.route("/get_active_coupons")
@login_required
def get_active_coupons():
    """מחזיר את כל הקופונים הפעילים של המשתמש הנוכחי"""
    active_coupons = [
        {
            "id": cpn.id,
            "company": cpn.company,
            "code": cpn.code,
            "remaining_balance": float(cpn.value - cpn.used_value),
        }
        for cpn in current_user.coupons
        if cpn.status == "פעיל"
    ]
    return jsonify({"success": True, "coupons": active_coupons})


@coupons_bp.route("/confirm_usage_update", methods=["GET", "POST"])
@login_required
def confirm_usage_update():
    debug_session("CONFIRM START")

    # Get confirmed usages from session
    confirmed_usages = session.get("confirmed_usages", [])
    print(f"[CONFIRM] Found {len(confirmed_usages)} confirmed usages")

    if not confirmed_usages:
        flash("אין שימושים לאישור.", "warning")
        return redirect(url_for("profile.index"))

    errors = []
    successes = []

    from app.models import Coupon, CouponUsage

    # Process each confirmed usage
    for idx, row in enumerate(confirmed_usages):
        print(f"[CONFIRM] Processing usage {idx}: {row}")

        coupon_id_str = row.get("company_final", "")

        try:
            used_amount = float(row.get("used_amount", 0.0))
        except (ValueError, TypeError):
            print(f"[CONFIRM] Invalid amount: {row.get('used_amount')}")
            used_amount = 0.0

        # Skip invalid entries
        if not coupon_id_str or coupon_id_str in ("", "other") or used_amount <= 0:
            msg = "שימוש לא תקין: חסר ID קופון או סכום."
            print(f"[CONFIRM] {msg}")
            errors.append(msg)
            continue

        # Try to convert coupon ID to int
        try:
            coupon_id = int(coupon_id_str)
            print(f"[CONFIRM] Looking up coupon ID: {coupon_id}")
        except ValueError:
            msg = f"ID הקופון אינו תקין: {coupon_id_str}"
            print(f"[CONFIRM] {msg}")
            errors.append(msg)
            continue

        # Find the coupon
        coupon = Coupon.query.get(coupon_id)
        if not coupon:
            msg = f"לא נמצא קופון עם מזהה {coupon_id_str}."
            print(f"[CONFIRM] {msg}")
            errors.append(msg)
            continue

        if coupon.user_id != current_user.id:
            msg = f"הקופון {coupon_id_str} אינו שייך למשתמש הנוכחי."
            print(f"[CONFIRM] {msg}")
            errors.append(msg)
            continue

        # Check remaining balance
        remaining = coupon.value - coupon.used_value
        print(f"[CONFIRM] Coupon {coupon.code} remaining balance: {remaining}")

        if used_amount > remaining:
            msg = f'ניסית להשתמש ב-{used_amount} ש"ח, אבל בקופון {coupon.code} נותר רק {remaining}.'
            print(f"[CONFIRM] {msg}")
            errors.append(msg)
            continue

        # Update coupon usage
        print(
            f"[CONFIRM] Updating coupon {coupon.code}: adding {used_amount} to used_value"
        )
        coupon.used_value += used_amount
        new_usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=used_amount,
            timestamp=datetime.now(),
            action="שימוש ממסך סיכום GPT",
            details=row.get("additional_info", "שימוש שהוזן ידנית"),
        )
        db.session.add(new_usage)

        # Update coupon status
        update_coupon_status(coupon)

        successes.append(f"עודכן שימוש של {used_amount} ₪ בקופון {coupon.code}.")

    # Try to commit changes
    try:
        print(
            f"[CONFIRM] Committing changes: {len(successes)} successes, {len(errors)} errors"
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        error_msg = f"Error in confirm_usage_update: {str(e)}"
        print(f"[CONFIRM] {error_msg}")
        current_app.logger.error(error_msg)
        flash("שגיאה בעת שמירת הנתונים.", "danger")
        return redirect(url_for("profile.index"))

    # Show success/error messages
    if errors:
        error_msg = "חלק מהשימושים לא עודכנו:\n" + "\n".join(errors)
        print(f"[CONFIRM] Errors: {error_msg}")
        flash(error_msg, "warning")

    if successes:
        success_msg = "הקופונים הבאים עודכנו בהצלחה:\n" + "\n".join(successes)
        print(f"[CONFIRM] Successes: {success_msg}")
        flash(success_msg, "success")

    # Clear session data
    print("[CONFIRM] Clearing session data")
    session.pop("parsed_usages", None)
    session.pop("confirmed_usages", None)

    debug_session("CONFIRM END")

    return redirect(url_for("profile.index"))


def debug_session(label):
    """Debug helper to print session data"""
    parsed = session.get("parsed_usages", [])
    confirmed = session.get("confirmed_usages", [])
    print(f"[DEBUG {label}] parsed_usages: {parsed}")
    print(f"[DEBUG {label}] confirmed_usages: {confirmed}")


@coupons_bp.route(
    "/delete_transaction_record/<string:source_table>/<int:record_id>", methods=["POST"]
)
@login_required
def delete_transaction_record(source_table, record_id):
    user_id = current_user.id

    if source_table == "coupon_usage":
        usage = CouponUsage.query.get_or_404(record_id)
        coupon = usage.coupon
        if coupon.user_id != user_id:
            flash("אין לך הרשאה למחוק שימוש זה.", "danger")
            return redirect(url_for("coupons.coupon_detail", id=coupon.id))

        coupon.used_value -= usage.used_amount
        if coupon.used_value < 0:
            coupon.used_value = 0

        db.session.delete(usage)
        update_coupon_status(coupon)

    elif source_table == "coupon_transaction":
        transaction = CouponTransaction.query.get_or_404(record_id)
        coupon = Coupon.query.get(transaction.coupon_id)
        if not coupon or coupon.user_id != user_id:
            flash("אין לך הרשאה למחוק טעינה זו.", "danger")
            return redirect(
                url_for("coupons.coupon_detail", id=coupon.id if coupon else None)
            )

        # --- \u274C מניעת מחיקת הרשומה הראשונית ---
        if transaction.reference_number in ["ManualEntry", "Initial"]:
            flash("לא ניתן למחוק את הטעינה הראשונית של הקופון.", "danger")
            return redirect(url_for("coupons.coupon_detail", id=coupon.id))

        # אחרת, זו טעינה/שימוש רגילה – אפשר להמשיך בלוגיקה הרגילה:
        if transaction.recharge_amount > 0:
            new_value = coupon.value - transaction.recharge_amount
            if new_value < coupon.used_value:
                flash("לא ניתן למחוק טעינה שכבר נוצלה בחלקה.", "danger")
                return redirect(url_for("coupons.coupon_detail", id=coupon.id))
            coupon.value = new_value

        if transaction.usage_amount > 0:
            coupon.used_value -= transaction.usage_amount
            if coupon.used_value < 0:
                coupon.used_value = 0

        db.session.delete(transaction)
        update_coupon_status(coupon)

    else:
        flash("טבלה לא מוכרת, לא ניתן למחוק.", "danger")
        return redirect(url_for("coupons.show_coupons"))

    try:
        db.session.commit()
        flash("הרשומה נמחקה בהצלחה.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting transaction record: {e}")
        flash("שגיאה בעת מחיקת הרשומה.", "danger")

    return redirect(url_for("coupons.coupon_detail", id=coupon.id))


@coupons_bp.route("/update_coupon_detail_timestamp", methods=["POST"])
@login_required
def update_coupon_detail_timestamp():
    try:
        # Get the user's tour progress record
        tour_progress = UserTourProgress.query.filter_by(user_id=current_user.id).first()
        
        if tour_progress:
            # Update the timestamp
            tour_progress.coupon_detail_timestamp = datetime.utcnow()
            db.session.commit()
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Tour progress record not found'}), 404
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@coupons_bp.route("/update_tour_progress", methods=["POST"])
@login_required
def update_tour_progress():
    try:
        # Get the user's tour progress record
        tour_progress = UserTourProgress.query.filter_by(user_id=current_user.id).first()
        if not tour_progress:
            tour_progress = UserTourProgress(user_id=current_user.id)
            db.session.add(tour_progress)
        
        # Set the timestamp based on tour type
        tour_type = request.form.get('tour_type', 'add_coupon')
        if tour_type == 'add_coupon':
            tour_progress.add_coupon_timestamp = datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        elif tour_type == 'coupon_detail':
            tour_progress.coupon_detail_timestamp = datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        print(f"Error updating tour progress: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
