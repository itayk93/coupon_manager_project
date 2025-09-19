# marketplace_routes.py
from app.forms import OfferCouponForm
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    current_app,
)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from app.cache_helpers import cached_user_data, cache_for_minutes
from app.models import (
    Coupon,
    User,
    Transaction,
    Notification,
    CouponRequest,
    Tag,
    Company,
)
from app.helpers import (
    send_coupon_purchase_request_email,
    get_coupon_data,
    get_geo_location,
    get_public_ip,
)
from app.extensions import db
import logging
from datetime import datetime, timezone
import os
from app.helpers import send_email
from sqlalchemy.sql import text
import traceback

marketplace_bp = Blueprint("marketplace", __name__)

logger = logging.getLogger(__name__)

from app.helpers import get_geo_location, get_public_ip


def log_user_activity(action, coupon_id=None):
    try:
        ip_address = None or "0.0.0.0"
        geo_data = get_geo_location(ip_address)
        user_agent = request.headers.get("User-Agent", "")

        current_app.logger.info(
            f"[LOG] Action='{action}', coupon_id={coupon_id}, user_id={current_user.id if current_user else None}"
        )
        current_app.logger.info(
            f"[LOG] IP={ip_address}, GEO={geo_data}, UA={user_agent[:50]}"
        )

        activity = {
            "user_id": current_user.id if current_user.is_authenticated else None,
            "coupon_id": coupon_id,
            "timestamp": datetime.utcnow(),
            "action": action,
            "device": user_agent[:50] if user_agent else None,
            "browser": user_agent.split(" ")[0][:50] if user_agent else None,
            "ip_address": ip_address[:45] if ip_address else None,
            "city": geo_data.get("city"),
            "region": geo_data.get("region"),
            "country": geo_data.get("country"),
            "isp": geo_data.get("isp"),
            "lat": geo_data.get("lat"),
            "lon": geo_data.get("lon"),
            "timezone": geo_data.get("timezone"),
        }

        db.session.execute(
            text(
                """
                INSERT INTO user_activities
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address,
                     city, region, country, isp, lat, lon, timezone)
                VALUES
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address,
                     :city, :region, :country, :isp, :lat, :lon, :timezone)
            """
            ),
            activity,
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[ERROR] #log_user_activity failed: {e}")


@marketplace_bp.route("/marketplace")
@login_required
@cached_user_data(timeout=300, key_prefix="marketplace")
def marketplace():
    """
    מציג את שוק הקופונים עם הקופונים הזמינים והבקשות לקנייה.
    בקשות שכבר סופקו/fulfilled לא יופיעו.
    """
    # log_user_activity("marketplace_view")

    try:
        # ספירת עסקאות ממתינות כמוכר
        pending_as_seller_count = Transaction.query.filter_by(
            seller_id=current_user.id, status="ממתין לאישור המוכר"
        ).count()

        # ספירת עסקאות ממתינות כקונה
        pending_as_buyer_count = Transaction.query.filter_by(
            buyer_id=current_user.id, status="ממתין לאישור המוכר"
        ).count()

        # קופונים זמינים למכירה
        coupons = Coupon.query.filter_by(is_for_sale=True, is_available=True).all()

        # בקשות לקופונים (לא fulfilled)
        coupon_requests = CouponRequest.query.filter_by(fulfilled=False).all()

        # קבלת מזהי קופונים שכבר ביקש המשתמש לקנות
        requested_coupon_ids = [
            t.coupon_id
            for t in Transaction.query.filter_by(buyer_id=current_user.id).all()
        ]

        # שליפת לוגואים ושמות חברות לפי מזהה
        companies = Company.query.all()
        company_logo_mapping_by_id = {c.id: c.image_path for c in companies}
        company_name_mapping_by_id = {c.id: c.name for c in companies}

        # שליפת לוגואים של חברות לפי שם
        company_logo_mapping = {c.name.lower(): c.image_path for c in companies}

        return render_template(
            "marketplace.html",
            pending_as_seller_count=pending_as_seller_count,
            pending_as_buyer_count=pending_as_buyer_count,
            coupons=coupons,
            requested_coupon_ids=requested_coupon_ids,
            coupon_requests=coupon_requests,
            company_logo_mapping_by_id=company_logo_mapping_by_id,
            company_name_mapping_by_id=company_name_mapping_by_id,
            company_logo_mapping=company_logo_mapping,
        )

    except Exception as e:
        logger.error(f"Error fetching marketplace data: {e}")
        traceback.print_exc()
        flash("אירעה שגיאה בעת טעינת שוק הקופונים. אנא נסה שוב מאוחר יותר.", "danger")
        return redirect(url_for("marketplace.marketplace"))


@marketplace_bp.route("/marketplace/coupon/<int:id>")
@login_required
def marketplace_coupon_detail(id):
    # log_user_activity("marketplace_coupon_detail_view", coupon_id=id)

    coupon = Coupon.query.get_or_404(id)
    if not coupon.is_available or not coupon.is_for_sale:
        flash("קופון זה אינו זמין במרקטפלייס.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    seller = User.query.get(coupon.user_id)
    return render_template("coupon_detail.html", coupon=coupon, seller=seller)


@marketplace_bp.route("/request_coupon/<int:id>", methods=["GET", "POST"])
@login_required
def request_coupon_detail(id):
    # log_user_activity("request_coupon_detail_view", None)

    coupon_request = CouponRequest.query.get_or_404(id)
    if coupon_request.fulfilled:
        flash("בקשת הקופון כבר טופלה.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    delete_form = DeleteCouponRequestForm()
    if delete_form.validate_on_submit():
        db.session.delete(coupon_request)
        db.session.commit()
        flash("הבקשה נמחקה בהצלחה.", "success")
        return redirect(url_for("marketplace.marketplace"))

    requester = User.query.get(coupon_request.user_id)
    company = Company.query.get(coupon_request.company)
    if not company:
        flash("החברה לא נמצאה.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    company_logo_mapping = {
        company.name.lower(): company.image_path for company in Company.query.all()
    }
    return render_template(
        "coupon_request_detail.html",
        coupon_request=coupon_request,
        requester=requester,
        company=company,
        company_logo_mapping=company_logo_mapping,
        delete_form=delete_form,
    )


@marketplace_bp.route("/coupon_request/<int:id>", methods=["GET", "POST"])
@login_required
def coupon_request_detail_view(id):
    """
    מסך פירוט בקשת קופון, מאפשר מחיקה.
    אם הבקשה סופקה - לא נציג פה.
    """
    # log_user_activity("coupon_request_detail_view")
    coupon_request = CouponRequest.query.get_or_404(id)
    if coupon_request.fulfilled:
        flash("בקשת הקופון כבר טופלה.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    from app.forms import DeleteCouponRequestForm

    delete_form = DeleteCouponRequestForm()
    if delete_form.validate_on_submit():
        db.session.delete(coupon_request)
        db.session.commit()
        flash("הבקשה נמחקה בהצלחה.", "success")
        return redirect(url_for("marketplace.marketplace"))

    requester = User.query.get(coupon_request.user_id)
    company = Company.query.filter_by(name=coupon_request.company).first()
    if not company:
        flash("החברה לא נמצאה.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    company_logo_mapping = {c.name.lower(): c.image_path for c in Company.query.all()}
    return render_template(
        "coupon_request_detail.html",
        coupon_request=coupon_request,
        requester=requester,
        company=company,
        company_logo_mapping=company_logo_mapping,
        delete_form=delete_form,
    )


@marketplace_bp.route("/delete_coupon_request/<int:id>", methods=["POST"])
@login_required
def delete_coupon_request(id):
    # log_user_activity("delete_coupon_request_attempt", None)

    coupon_request = CouponRequest.query.get_or_404(id)
    if coupon_request.user_id != current_user.id:
        flash("אין לך הרשאה למחוק בקשה זו.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    try:
        db.session.delete(coupon_request)
        db.session.commit()

        try:
            pass
            # log_user_activity("delete_coupon_request_success", None)
        except Exception as e:
            current_app.logger.error(
                f"Error logging success activity [delete_coupon_request_success]: {e}"
            )

        flash("בקשת הקופון נמחקה בהצלחה.", "success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting coupon request {id}: {e}")
        flash("אירעה שגיאה בעת מחיקת הבקשה.", "danger")

    return redirect(url_for("marketplace.marketplace"))


@marketplace_bp.route("/seller_cancel_transaction/<int:transaction_id>")
@login_required
def seller_cancel_transaction(transaction_id):
    """
    המוכר מבטל עסקה - הקופון חוזר להיות זמין.
    """
    # log_user_activity("seller_cancel_transaction_attempt", transaction_id)

    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash("אין לך הרשאה לבטל עסקה זו.", "danger")
        return redirect(url_for("transactions.my_transactions"))

    seller = transaction.seller
    buyer = transaction.buyer
    coupon = transaction.coupon

    coupon.is_available = True

    html_content = render_template(
        "emails/seller_canceled_transaction.html",
        seller=seller,
        buyer=buyer,
        coupon=coupon,
    )
    try:
        send_email(
            sender_email="noreply@couponmasteril.com",
            sender_name="Coupon Master",
            recipient_email=buyer.email,
            recipient_name=f"{buyer.first_name} {buyer.last_name}",
            subject="המוכר ביטל את העסקה",
            html_content=html_content,
        )
        flash("ביטלת את העסקה ונשלח מייל לקונה.", "info")
    except Exception as e:
        logger.error(f"Error sending cancellation email to buyer: {e}")
        flash("ביטלת את העסקה, אך אירעה שגיאה בשליחת המייל.", "warning")

    transaction.status = "מבוטל"
    transaction.updated_at = datetime.utcnow()
    db.session.commit()

    try:
        pass
        # log_user_activity("seller_cancel_transaction_success", transaction_id)
    except Exception as e:
        current_app.logger.error(
            f"Error logging activity [seller_cancel_transaction_success]: {e}"
        )

    return redirect(url_for("transactions.my_transactions"))


@marketplace_bp.route("/review_seller/<int:seller_id>", methods=["GET", "POST"])
@login_required
def review_seller(seller_id):
    """
    הקונה משאיר ביקורת למוכר.
    נבדוק שמדובר בקונה שאכן סיים עסקה עם המוכר הזה.
    """
    transaction_id = request.args.get("transaction_id", type=int)

    # בדיקה אם אכן קיימת עסקה הושלמה בין current_user (הקונה) למוכר (seller_id)
    transaction = Transaction.query.filter_by(
        id=transaction_id, buyer_id=current_user.id, seller_id=seller_id, status="הושלם"
    ).first()

    if not transaction:
        flash("לא נמצאה עסקה תקינה להוספת ביקורת.", "danger")
        return redirect(url_for("transactions.my_transactions"))

    if request.method == "GET":
        # בדיקה אם כבר השארת ביקורת על העסקה הזו (אופציונלי).
        existing_review = UserReview.query.filter_by(
            reviewer_id=current_user.id, reviewed_user_id=seller_id
        ).first()
        if existing_review:
            flash("כבר השארת ביקורת על משתמש זה.", "info")
            return redirect(url_for("transactions.my_transactions"))

        return render_template("review_seller.html", seller_id=seller_id)

    if request.method == "POST":
        # מקבלים את הערך מהסליידר (1-5) ואת התגובה
        rating_str = request.form.get("rating")
        comment = request.form.get("comment", "")

        # ולידציה בסיסית
        try:
            rating = int(rating_str)
        except:
            flash("עליך לבחור דירוג תקין בין 1 ל-5.", "danger")
            return redirect(request.url)

        if rating < 1 or rating > 5:
            flash("הדירוג חייב להיות בין 1 ל-5.", "danger")
            return redirect(request.url)

        # שמירת הביקורת
        user_review = UserReview(
            reviewer_id=current_user.id,
            reviewed_user_id=seller_id,
            rating=rating,
            comment=comment,
        )
        db.session.add(user_review)
        db.session.commit()

        flash("הביקורת נשמרה בהצלחה!", "success")
        return redirect(url_for("profile.profile_view", user_id=seller_id))


# marketplace_routes.py


@marketplace_bp.route("/offer_coupon/<int:request_id>", methods=["GET", "POST"])
@login_required
def offer_coupon_selection(request_id):
    """
    מסך ראשון לבחירת איך להציע קופון (קיים/חדש) + הודעה (אופציונלית) למבקש.
    """
    # log_user_activity("offer_coupon_selection_view")

    coupon_request = CouponRequest.query.get_or_404(request_id)
    if coupon_request.user_id == current_user.id:
        flash("אינך יכול למכור לעצמך.", "warning")
        return redirect(url_for("marketplace.marketplace"))

    # אם הבקשה כבר מולאה (fulfilled), אין טעם
    if coupon_request.fulfilled:
        flash("בקשה זו כבר טופלה.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    current_app.logger.info(
        f"[DEBUG] Entering offer_coupon_selection => request_id={request_id}"
    )

    seller_coupons = Coupon.query.filter_by(
        user_id=current_user.id, is_for_sale=True, is_available=True, status="פעיל"
    ).all()
    current_app.logger.info(
        f"[DEBUG] Found {len(seller_coupons)} existing coupons for user {current_user.id}"
    )

    from app.forms import OfferCouponForm

    form = OfferCouponForm()

    # הגדירו choices לחברות
    companies = Company.query.all()
    company_choices = [("", "בחר חברה")]
    for c in companies:
        company_choices.append((str(c.id), c.name))
    company_choices.append(("other", "אחר"))
    form.company_select.choices = company_choices

    if request.method == "GET":
        current_app.logger.info("[DEBUG] GET => rendering template")
        return render_template(
            "select_coupon_offer_options.html",
            form=form,
            coupon_request=coupon_request,
            seller_coupons=seller_coupons,
        )

    # POST
    current_app.logger.info(f"[DEBUG] POST form data => {request.form}")
    if form.validate_on_submit():
        current_app.logger.info("[DEBUG] Form validated => go to offer_coupon_process")
        return redirect(
            url_for("marketplace.offer_coupon_process", request_id=request_id)
        )
    else:
        current_app.logger.warning(f"[WARNING] Form not valid => errors: {form.errors}")
        for field, errs in form.errors.items():
            for e in errs:
                flash(f"שגיאה בשדה '{field}': {e}", "danger")

        return redirect(
            url_for("marketplace.offer_coupon_selection", request_id=request_id)
        )


@marketplace_bp.route("/offer_coupon_process/<int:request_id>", methods=["POST"])
@login_required
def offer_coupon_process(request_id):
    """
    אחרי שבחרו קופון (קיים/חדש), נוצר/נבחר ה-coupon, ונשלח מייל למבקש עם לינק לרכישה.
    """
    # log_user_activity("offer_coupon_process")

    coupon_request = CouponRequest.query.get_or_404(request_id)
    if coupon_request.user_id == current_user.id:
        flash("אינך יכול למכור לעצמך.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    if coupon_request.fulfilled:
        flash("הבקשה כבר טופלה.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    from app.forms import OfferCouponForm

    form = OfferCouponForm()
    current_app.logger.info(
        f"[DEBUG] offer_coupon_process => POST data = {request.form}"
    )

    # שוב נטען את ה-choices
    companies = Company.query.all()
    company_choices = [("", "בחר חברה")]
    for c in companies:
        company_choices.append((str(c.id), c.name))
    company_choices.append(("other", "אחר"))
    form.company_select.choices = company_choices

    if not form.validate_on_submit():
        current_app.logger.warning(f"[WARNING] form not valid => {form.errors}")
        for f, e in form.errors.items():
            for ee in e:
                flash(f"שגיאה בשדה '{f}': {ee}", "danger")
        return redirect(
            url_for("marketplace.offer_coupon_selection", request_id=request_id)
        )

    offer_choice = form.offer_choice.data
    seller_message = form.seller_message.data or ""
    current_app.logger.info(
        f"[DEBUG] offer_choice={offer_choice}, seller_message={seller_message}"
    )

    chosen_coupon = None

    # אם בחר "קופון קיים"
    if offer_choice == "existing":
        existing_coupon_id = request.form.get("existing_coupon_id")
        if not existing_coupon_id:
            flash("לא נבחר קופון קיים.", "danger")
            return redirect(
                url_for("marketplace.offer_coupon_selection", request_id=request_id)
            )

        chosen_coupon = Coupon.query.filter_by(
            id=existing_coupon_id, user_id=current_user.id
        ).first()

        if not chosen_coupon:
            flash("לא נמצא קופון קיים או אינו שלך.", "danger")
            return redirect(
                url_for("marketplace.offer_coupon_selection", request_id=request_id)
            )

        chosen_coupon.is_for_sale = True
        chosen_coupon.is_available = True
        db.session.commit()

    # אם בחר "קופון חדש"
    elif offer_choice == "new":
        selected_company_id = form.company_select.data
        other_company_name = (form.other_company.data or "").strip()

        if selected_company_id == "other":
            # המשתמש הזין חברה חדשה
            if not other_company_name:
                flash("עליך למלא שם חברה חדשה.", "danger")
                return redirect(
                    url_for("marketplace.offer_coupon_selection", request_id=request_id)
                )

            company_obj = Company.query.filter_by(name=other_company_name).first()
            if not company_obj:
                company_obj = Company(name=other_company_name, image_path="default.png")
                db.session.add(company_obj)
                db.session.flush()
        else:
            # חברה קיימת
            try:
                cid_int = int(selected_company_id)
                company_obj = Company.query.get(cid_int)
                if not company_obj:
                    flash("חברה שנבחרה לא חוקית.", "danger")
                    return redirect(
                        url_for(
                            "marketplace.offer_coupon_selection", request_id=request_id
                        )
                    )
            except ValueError:
                flash("חברה נבחרה אינה תקפה.", "danger")
                return redirect(
                    url_for("marketplace.offer_coupon_selection", request_id=request_id)
                )

        val = form.value.data or 0.0
        cst = form.cost.data or 0.0

        chosen_coupon = Coupon(
            user_id=current_user.id,
            company=company_obj.name,
            code="",  # לא דורשים code
            value=val,
            cost=cst,
            status="פעיל",
            is_for_sale=True,
            is_available=True,
        )
        db.session.add(chosen_coupon)
        db.session.commit()

    else:
        flash("בחירה לא תקפה.", "danger")
        return redirect(
            url_for("marketplace.offer_coupon_selection", request_id=request_id)
        )

    # נשלח מייל למבקש
    buyer = User.query.get(coupon_request.user_id)
    buy_link = request.host_url.rstrip("/") + url_for(
        "transactions.buy_coupon_direct", coupon_id=chosen_coupon.id
    )

    # בונים HTML
    html_content = render_template(
        "emails/offer_coupon_email.html",
        buyer=buyer,
        seller=current_user,
        coupon=chosen_coupon,
        seller_message=seller_message,
        buy_link=buy_link,
    )

    try:
        send_email(
            sender_email="noreply@couponmasteril.com",
            sender_name="Coupon Master",
            recipient_email=buyer.email,
            recipient_name=f"{buyer.first_name} {buyer.last_name}",
            subject="המוכר מציע לך קופון!",
            html_content=html_content,
        )
        flash("ההצעה נשלחה בהצלחה למבקש הקופון!", "success")
        current_app.logger.info(f"[DEBUG] email sent to {buyer.email}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[ERROR] sending offer email: {e}")
        flash("נוצר הקופון אך לא הצלחנו לשלוח מייל למבקש.", "warning")

    return redirect(url_for("marketplace.marketplace"))


@marketplace_bp.route("/transaction_about")
def transaction_about():
    return render_template("transaction_about.html")
