# app/routes/profile_routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func
import re
import os
import pandas as pd
from io import BytesIO
from datetime import datetime, timezone
from werkzeug.utils import secure_filename
import pytz  # ספרייה לניהול אזורי זמן

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
    ChangePasswordForm,
)
from app.helpers import update_coupon_status, get_coupon_data, process_coupons_excel
from app.helpers import send_coupon_purchase_request_email, send_password_change_email
from sqlalchemy.exc import IntegrityError
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Notification, User
from datetime import datetime
from app.forms import BuySlotsForm
from flask_wtf.csrf import validate_csrf, ValidationError
import logging
from flask import redirect, render_template, url_for, flash
from flask_login import login_required, current_user
from app.models import User, UserReview
from app.forms import RateUserForm
from app import db

logger = logging.getLogger(__name__)

profile_bp = Blueprint("profile", __name__)
from sqlalchemy.sql import text
from flask import request, current_app
from flask_login import current_user
from app.helpers import get_geo_location, get_public_ip

ip_address = None
from app.models import AdminMessage


def log_user_activity(ip_address, action, coupon_id=None):
    """
    פונקציה מרכזית לרישום activity log.
    """
    try:
        user_agent = request.headers.get("User-Agent", "")

        geo_data = get_geo_location(ip_address)

        # ודא ש-geo_data מחזירה ערכים נכונים
        # print(f"Geo Data: {geo_data}")

        activity = {
            "user_id": current_user.id
            if current_user and current_user.is_authenticated
            else None,
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
            "country_code": geo_data.get("country_code"),
            "zip": geo_data.get("zip"),
            "lat": geo_data.get("lat"),
            "lon": geo_data.get("lon"),
            "timezone": geo_data.get("timezone"),
            "org": geo_data.get("org"),
            "as_info": geo_data.get("as"),
        }

        db.session.execute(
            text(
                """
                INSERT INTO user_activities
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address, city, region, country, isp, 
                     country_code, zip, lat, lon, timezone, org, as_info)
                VALUES
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :city, :region, :country, :isp, 
                     :country_code, :zip, :lat, :lon, :timezone, :org, :as_info)
            """
            ),
            activity,
        )
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging activity [{action}]: {e}")


@profile_bp.route("/")
def home():
    if current_user.is_authenticated:
        # רישום הפעולה
        # log_user_activity(ip_address, "authorized_index_access")
        return redirect(url_for("profile.index"))
    else:
        # log_user_activity(ip_address, "unauthorized_redirect_to_login")
        return redirect(url_for("auth.login"))


def get_greeting():
    israel_tz = pytz.timezone("Asia/Jerusalem")
    current_hour = datetime.now(israel_tz).hour

    if current_hour < 12:
        return "בוקר טוב"
    elif current_hour < 18:
        return "צהריים טובים"
    else:
        return "ערב טוב"


# app/routes/profile_routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from datetime import date, timedelta, datetime
import pytz
import logging

from app.extensions import db
from app.models import Coupon, Company
from app.forms import ProfileForm
from app.helpers import update_coupon_status, get_greeting
from app.forms import ProfileForm, UsageExplanationForm


# ייתכן שיש לך פונקציה לקבל IP, אשתמש כאן ב-REMOTE_ADDR
def get_ip_address():
    return request.remote_addr or "0.0.0.0"


@profile_bp.route("/index", methods=["GET", "POST"])
@login_required
def index():
    from sqlalchemy import cast, Date, func
    import json

    """
    Profile/Home page that displays:
    - Greeting (based on time of day)
    - Profile editing options (ProfileForm)
    - Coupon amount calculations (remaining, savings...)
    - Display coupons in different categories
    - Show banner for "coupons expiring in 7 days" - once per day, if there are any.
    """
    ip_address = get_ip_address()
    # log_user_activity(ip_address, "index")

    # Profile edit form
    profile_form = ProfileForm()

    # First form: usage
    usage_form = UsageExplanationForm()

    # Second form: sms => to create a new coupon via SMS parse
    sms_form = SMSInputForm()

    # Check profile form submission
    if profile_form.validate_on_submit() and "age" in request.form:
        current_user.age = profile_form.age.data
        current_user.gender = profile_form.gender.data
        db.session.commit()
        flash("פרטי הפרופיל עודכנו בהצלחה.", "success")
        return redirect(url_for("profile.index"))

    if request.method == "GET":
        # Fill profile form
        profile_form.first_name.data = current_user.first_name
        profile_form.last_name.data = current_user.last_name
        profile_form.age.data = current_user.age
        profile_form.gender.data = current_user.gender

    greeting = (
        get_greeting()
    )  # For example: based on time, returns "Good morning" / "Good evening", etc.

    # --------------------------------------------------------------------------------
    # 1. Calculate total coupons and savings - INCLUDING BOTH ONE-TIME AND NON-ONE-TIME
    # --------------------------------------------------------------------------------

    # Get all coupons (including one-time) but excluding those for sale
    all_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        Coupon.exclude_saving != True,
    ).all()

    # Calculate total remaining value, savings, and total value
    total_remaining = sum(coupon.value - coupon.used_value for coupon in all_coupons)
    total_savings = sum(
        (coupon.value - coupon.cost)
        for coupon in all_coupons
        if coupon.value > coupon.cost
    )
    total_coupons_value = sum(coupon.value for coupon in all_coupons)
    percentage_savings = (
        (total_savings / total_coupons_value) * 100 if total_coupons_value > 0 else 0
    )

    # --------------------------------------------------------------------------------
    # 2. Fetch and divide into categories (active, active_one_time, used, for_sale)
    # --------------------------------------------------------------------------------

    # Active one-time coupons
    active_one_time_coupons = Coupon.query.filter(
        Coupon.status == "פעיל",
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        Coupon.is_one_time == True,
    ).all()

    # Used coupons (not active)
    used_coupons = Coupon.query.filter(
        Coupon.status != "פעיל",
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
    ).all()

    # Coupons for sale
    coupons_for_sale = Coupon.query.filter(
        Coupon.user_id == current_user.id, Coupon.is_for_sale == True
    ).all()

    # Active coupons (non-one-time)
    active_coupons = (
        Coupon.query.filter(
            Coupon.user_id == current_user.id,
            Coupon.status == "פעיל",
            Coupon.is_for_sale == False,
            ~Coupon.is_one_time,
        )
        .order_by(Coupon.date_added.desc())
        .all()
    )

    # --------------------------------------------------------------------------------
    # 3. Update status (for all categories) and then commit
    # --------------------------------------------------------------------------------
    all_to_update = all_coupons + coupons_for_sale
    for coupon in all_to_update:
        update_coupon_status(coupon)
    db.session.commit()

    # --------------------------------------------------------------------------------
    # 4. Check "Are there coupons expiring in the next 7 days" + show banner once a day
    # --------------------------------------------------------------------------------

    # Check if user dismissed the alert today
    dismissed_today = (
        current_user.dismissed_expiring_alert_at is not None
        and current_user.dismissed_expiring_alert_at == date.today()
    )

    # Find coupons expiring in the next week
    one_week_from_now = date.today() + timedelta(days=7)
    expiring_coupons = (
        Coupon.query.filter(
            Coupon.user_id == current_user.id,
            Coupon.status == "פעיל",
            Coupon.is_for_sale == False,
            Coupon.expiration.isnot(None),
        )
        .filter(
            cast(Coupon.expiration, Date) >= date.today(),
            cast(Coupon.expiration, Date) <= one_week_from_now,
        )
        .all()
    )

    # Show alert only if there are relevant coupons and user hasn't dismissed the alert today
    show_expiring_alert = len(expiring_coupons) > 0 and not dismissed_today

    # --------------------------------------------------------------------------------
    # 5. Fetch all companies (for logo map, if relevant)
    # --------------------------------------------------------------------------------
    companies = Company.query.all()
    company_logo_mapping = {
        company.name.lower(): company.image_path for company in companies
    }

    # Add check and set default logo if missing
    for company_name in company_logo_mapping:
        if not company_logo_mapping[company_name]:  # If path is missing or None
            company_logo_mapping[company_name] = "images/default.png"

    # --------------------------------------------------------------------------------
    # 6. Accurate statistics by company for the charts
    # --------------------------------------------------------------------------------
    # Organize data by company
    companies_stats = {}

    # Create dictionary to track earliest expiration date per company
    company_earliest_expirations = {}

    # Track coupon types per company
    company_coupon_types = {}

    for coupon in all_coupons:
        company = coupon.company
        if company not in companies_stats:
            companies_stats[company] = {
                "total_value": 0,
                "used_value": 0,
                "remaining_value": 0,
                "savings": 0,
                "count": 0,
                "one_time_count": 0,
                "non_one_time_count": 0,
            }
            company_coupon_types[company] = {"one_time": 0, "non_one_time": 0}

        companies_stats[company]["total_value"] += coupon.value
        companies_stats[company]["used_value"] += coupon.used_value
        companies_stats[company]["remaining_value"] += coupon.value - coupon.used_value
        companies_stats[company]["savings"] += max(0, coupon.value - coupon.cost)
        companies_stats[company]["count"] += 1

        # Track coupon type counts
        if coupon.is_one_time:
            companies_stats[company]["one_time_count"] += 1
            company_coupon_types[company]["one_time"] += 1
        else:
            companies_stats[company]["non_one_time_count"] += 1
            company_coupon_types[company]["non_one_time"] += 1

        # Track earliest expiration date for each company
        if coupon.expiration and coupon.status == "פעיל":
            # Convert string to date if needed
            exp_date = coupon.expiration
            if isinstance(exp_date, str):
                exp_date = datetime.strptime(exp_date, "%Y-%m-%d").date()

            # Update the earliest date for this company
            if (
                company not in company_earliest_expirations
                or exp_date < company_earliest_expirations[company]
            ):
                company_earliest_expirations[company] = exp_date

    # Sort companies by savings amount
    sorted_companies = sorted(
        companies_stats.items(), key=lambda x: x[1]["savings"], reverse=True
    )

    # --------------------------------------------------------------------------------
    # 7. Prepare timeline data (monthly savings data)
    # --------------------------------------------------------------------------------

    # Month names in Hebrew
    month_names = {
        "01": "ינואר",
        "02": "פברואר",
        "03": "מרץ",
        "04": "אפריל",
        "05": "מאי",
        "06": "יוני",
        "07": "יולי",
        "08": "אוגוסט",
        "09": "ספטמבר",
        "10": "אוקטובר",
        "11": "נובמבר",
        "12": "דצמבר",
    }

    # Group coupons by month added
    monthly_data = {}

    for coupon in all_coupons:
        # Use date_added as the reference month
        if hasattr(coupon, "date_added") and coupon.date_added:
            month_key = coupon.date_added.strftime("%Y-%m")

            if month_key not in monthly_data:
                monthly_data[month_key] = {
                    "savings": 0,  # Value - cost (the actual savings)
                    "count": 0,
                    "original_value": 0,  # Total face value
                    "remaining_value": 0,  # Remaining value
                    "companies": set(),  # Set of companies for this month
                    "one_time_count": 0,  # Count of one-time coupons
                    "non_one_time_count": 0,  # Count of non-one-time coupons
                }

            # Add coupon data to the month
            monthly_data[month_key]["savings"] += max(0, coupon.value - coupon.cost)
            monthly_data[month_key]["count"] += 1
            monthly_data[month_key]["original_value"] += coupon.value
            monthly_data[month_key]["remaining_value"] += (
                coupon.value - coupon.used_value
            )
            monthly_data[month_key]["companies"].add(coupon.company)

            # Track coupon type
            if coupon.is_one_time:
                monthly_data[month_key]["one_time_count"] += 1
            else:
                monthly_data[month_key]["non_one_time_count"] += 1

    # Convert to sorted list for timeline charts
    timeline_data_formatted = []

    for month_year, data in sorted(monthly_data.items()):
        year, month = month_year.split("-")
        month_name = month_names.get(month, month)

        # Calculate average discount percentage
        discount_percentage = 0
        if data["original_value"] > 0:
            discount_percentage = (data["savings"] / data["original_value"]) * 100

        # Convert company set to list
        companies_list = list(data["companies"])

        # Create data entry
        timeline_data_formatted.append(
            {
                "month": f"{month_name} {year}",
                "value": data["savings"],  # Using savings as the value
                "original_value": data["original_value"],
                "remaining_value": data["remaining_value"],
                "coupons_count": data["count"],
                "one_time_count": data["one_time_count"],
                "non_one_time_count": data["non_one_time_count"],
                "discount_percentage": discount_percentage,
                "companies": companies_list,
            }
        )

    # --------------------------------------------------------------------------------
    # 8. Prepare cumulative savings data
    # --------------------------------------------------------------------------------

    # This should be based on actual savings (value - cost), not just usage
    cumulative_savings = []
    running_total = 0

    for entry in timeline_data_formatted:
        monthly_savings = entry["value"]  # This is already the savings amount
        running_total += monthly_savings

        cumulative_savings.append(
            {
                "month": entry["month"],
                "value": monthly_savings,
                "cumulative": running_total,
            }
        )

    # --------------------------------------------------------------------------------
    # 9. Calculate additional metrics for general statistics
    # --------------------------------------------------------------------------------

    # Basic counts
    total_coupons_count = len(all_coupons)
    active_coupons_count = len(active_coupons) + len(active_one_time_coupons)
    total_companies_count = len(companies_stats)

    # Calculate average usage percentage
    average_usage_percentage = 0
    if total_coupons_value > 0:
        total_used_value = sum(coupon.used_value for coupon in all_coupons)
        average_usage_percentage = (total_used_value / total_coupons_value) * 100

    # Count one-time vs non-one-time coupons
    one_time_count = sum(1 for coupon in all_coupons if coupon.is_one_time)
    non_one_time_count = total_coupons_count - one_time_count

    # --------------------------------------------------------------------------------
    # 10. Convert data for JSON and template rendering
    # --------------------------------------------------------------------------------

    # Convert expiration from String to Date (if it's not None)
    for coupon in expiring_coupons:
        if isinstance(coupon.expiration, str):  # If expiration is a string
            coupon.expiration = datetime.strptime(coupon.expiration, "%Y-%m-%d").date()

    # Convert companies data to format for JavaScript
    sorted_company_data = []
    for company, stats in sorted_companies:
        # Get earliest expiration date for this company
        earliest_expiration = None
        if company in company_earliest_expirations:
            earliest_expiration = company_earliest_expirations[company].strftime(
                "%Y-%m-%d"
            )

        # Create company data entry
        sorted_company_data.append(
            {
                "company": company,
                "savings": stats["savings"],
                "used_value": stats["used_value"],
                "total_value": stats["total_value"],
                "remaining_value": stats["remaining_value"],
                "coupons_count": stats["count"],
                "one_time_count": stats["one_time_count"],
                "non_one_time_count": stats["non_one_time_count"],
                "active_coupons": sum(
                    1 for coupon in active_coupons if coupon.company == company
                )
                + sum(
                    1 for coupon in active_one_time_coupons if coupon.company == company
                ),
                "usage_percentage": (stats["used_value"] / stats["total_value"] * 100)
                if stats["total_value"] > 0
                else 0,
                "earliest_expiration": earliest_expiration,  # Add earliest expiration date
            }
        )

    # --------------------------------------------------------------------------------
    # 11. Admin message handling
    # --------------------------------------------------------------------------------
    # Get the latest message
    latest_message = AdminMessage.query.order_by(AdminMessage.id.desc()).first()
    show_admin_message = False

    if latest_message:
        if (current_user.dismissed_message_id is None) or (
            current_user.dismissed_message_id < latest_message.id
        ):
            show_admin_message = True

    # --------------------------------------------------------------------------------
    # 12. Check if we need to show the review modal
    # --------------------------------------------------------------------------------
    # Check the request parameter to determine if we should show the usage review modal
    # This is used when redirected from review_usage_findings function
    show_review_modal = request.args.get("show_review_modal", "0") == "1"

    # --------------------------------------------------------------------------------
    # 13. Check tour progress
    # --------------------------------------------------------------------------------
    tour_progress = UserTourProgress.query.filter_by(user_id=current_user.id).first()
    if not tour_progress:
        tour_progress = UserTourProgress(user_id=current_user.id)
        db.session.add(tour_progress)
        db.session.commit()

    # Check if we need to show the tour
    show_tour = tour_progress.index_timestamp is None

    # --------------------------------------------------------------------------------
    # 14. Handle tour completion
    # --------------------------------------------------------------------------------
    if request.method == "POST" and request.form.get("action") == "complete_tour":
        try:
            # Update tour progress
            tour_progress = UserTourProgress.query.filter_by(user_id=current_user.id).first()
            if not tour_progress:
                tour_progress = UserTourProgress(user_id=current_user.id)
                db.session.add(tour_progress)
            
            # Set the timestamp based on tour type
            tour_type = request.form.get('tour_type', 'index')
            if tour_type == 'index':
                tour_progress.index_timestamp = datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
            elif tour_type == 'coupon_detail':
                tour_progress.coupon_detail_timestamp = datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
            
            db.session.commit()
            
            return jsonify({"success": True})
        except Exception as e:
            db.session.rollback()
            print(f"Error updating tour progress: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # --------------------------------------------------------------------------------
    # 15. Return the completed template with all data
    # --------------------------------------------------------------------------------
    return render_template(
        "index.html",
        profile_form=profile_form,
        usage_form=usage_form,
        sms_form=sms_form,
        greeting=greeting,
        total_value=total_remaining,
        total_savings=total_savings,
        total_coupons_value=total_coupons_value,
        percentage_savings=percentage_savings,
        active_coupons=active_coupons,
        active_one_time_coupons=active_one_time_coupons,
        used_coupons=used_coupons,
        coupons_for_sale=coupons_for_sale,
        company_logo_mapping=company_logo_mapping,
        # Variables relevant for alerts
        show_expiring_alert=show_expiring_alert,
        expiring_coupons=expiring_coupons,
        # Add current_date and timedelta to template
        current_date=date.today(),
        timedelta=timedelta,
        # Statistics data
        companies_stats=json.dumps(sorted_company_data),
        timeline_data=json.dumps(timeline_data_formatted),
        total_coupons_count=total_coupons_count,
        total_companies_count=total_companies_count,
        average_usage_percentage=average_usage_percentage,
        active_coupons_count=active_coupons_count,
        one_time_count=one_time_count,
        non_one_time_count=non_one_time_count,
        # Cumulative savings data
        cumulative_savings=json.dumps(cumulative_savings),
        # Admin messages
        show_admin_message=show_admin_message,
        admin_message=latest_message if show_admin_message else None,
        # Flag to show review modal
        show_review_modal=show_review_modal,
        # Add tour progress flag
        show_tour=show_tour,
    )


@profile_bp.route("/load_stats_modal")
@login_required
def load_stats_modal():
    return render_template("index_modals/stats_modal.html")


@profile_bp.route("/dismiss_expiring_alert", methods=["GET"])
@login_required
def dismiss_expiring_alert():
    """
    המשתמש לחץ על X בסרגל ההתראות => עדכון התאריך האחרון שבו דחה את ההתראה בדאטהבייס.
    """
    current_user.dismissed_expiring_alert_at = date.today()
    db.session.commit()

    return redirect(url_for("profile.index"))


@profile_bp.route("/notifications")
@login_required
def notifications():
    notifications_list = (
        Notification.query.filter_by(user_id=current_user.id, hide_from_view=False)
        .order_by(Notification.timestamp.desc())
        .all()
    )
    return render_template("notifications.html", notifications=notifications_list)


@profile_bp.route("/delete_notification/<int:notification_id>", methods=["POST"])
@login_required
def delete_notification(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id, user_id=current_user.id, hide_from_view=False
    ).first()
    if notification:
        notification.hide_from_view = True  # סימון כהוסתר
        db.session.commit()
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": "התראה לא נמצאה"}), 404


@profile_bp.route("/delete_all_notifications", methods=["POST"])
@login_required
def delete_all_notifications():
    try:
        logger.info(f"User {current_user.id} is attempting to hide all notifications.")
        notifications = Notification.query.filter_by(
            user_id=current_user.id, hide_from_view=False
        ).all()
        for notification in notifications:
            notification.hide_from_view = True
        db.session.commit()
        logger.info(f"User {current_user.id} hid {len(notifications)} notifications.")
        return jsonify({"status": "success", "deleted": len(notifications)})
    except Exception as e:
        logger.error(f"Error hiding all notifications: {e}")
        return jsonify({"status": "error", "message": "שגיאה במחיקת ההתראות"}), 500


@profile_bp.route("/update_profile_field", methods=["POST"])
@login_required
def update_profile_field():
    try:
        data = request.get_json()
        field = data.get("field")
        value = data.get("value")

        logger.info(f"Received update for field: {field} with value: {value}")

        csrf_token = request.headers.get("X-CSRFToken")
        # print(f"Received CSRF Token: {csrf_token}")
        if not csrf_token:
            logger.warning("Missing CSRF token in request.")
            return jsonify({"status": "error", "message": "Missing CSRF token."}), 400

        try:
            validate_csrf(csrf_token)
        except ValidationError:
            logger.warning("Invalid CSRF token.")
            return jsonify({"status": "error", "message": "Invalid CSRF token."}), 400

        allowed_fields = ["first_name", "last_name", "age", "gender"]
        if field not in allowed_fields:
            logger.warning(f"Attempt to update unauthorized field: {field}")
            return jsonify({"status": "error", "message": "Unauthorized field."}), 400

        user = User.query.get(current_user.id)
        setattr(user, field, value)
        db.session.commit()

        logger.info(f"Successfully updated field: {field} for user: {current_user.id}")
        return jsonify({"status": "success"}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(
            f"Error updating field: {field} for user: {current_user.id}. Error: {str(e)}"
        )
        return (
            jsonify(
                {"status": "error", "message": "Server error. Please try again later."}
            ),
            500,
        )


@profile_bp.route("/about")
def about():
    return render_template("about.html")


@profile_bp.route("/buy_slots", methods=["GET", "POST"])
@login_required
def buy_slots():
    form = BuySlotsForm()
    if form.validate_on_submit():
        try:
            slot_amount = int(form.slot_amount.data)
            if slot_amount not in [10, 20, 50]:
                flash("כמות סלוטים לא תקפה.", "danger")
                return redirect(url_for("profile.buy_slots"))

            current_user.slots += slot_amount
            db.session.commit()
            flash(f"רכשת {slot_amount} סלוטים בהצלחה!", "success")
            return redirect(url_for("profile.buy_slots"))
        except ValueError:
            flash("כמות סלוטים לא תקפה.", "danger")
            return redirect(url_for("profile.buy_slots"))
    return render_template("buy_slots.html", slots=current_user.slots, form=form)


@profile_bp.route("/edit_profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    """
    עריכת פרופיל המשתמש המחובר: תיאור קצר + תמונת פרופיל.
    """
    form = UserProfileForm()

    if request.method == "POST":
        if form.validate_on_submit():
            # עדכון התיאור
            current_user.profile_description = form.profile_description.data

            # העלאת תמונה (אם הועלתה)
            if form.profile_image.data:
                file = form.profile_image.data
                if allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # שמירה בנתיב קבוע בתוך static/uploads, למשל
                    upload_path = os.path.join("app", "static", "uploads", "profiles")
                    os.makedirs(upload_path, exist_ok=True)
                    save_path = os.path.join(upload_path, filename)
                    file.save(save_path)

                    # שמירת הנתיב בבסיס הנתונים
                    current_user.profile_image = f"static/uploads/profiles/{filename}"
                else:
                    flash(
                        "סוג קובץ לא תקין. יש להעלות תמונה בפורמט jpg/png/gif", "danger"
                    )
                    return redirect(url_for("profile.edit_profile"))

            db.session.commit()
            flash("פרופיל עודכן בהצלחה!", "success")
            return redirect(url_for("profile.profile_view", user_id=current_user.id))
        else:
            flash("נא לתקן את השגיאות בטופס.", "danger")

    # מילוי ערכים קיימים
    if request.method == "GET":
        form.profile_description.data = current_user.profile_description

    return render_template("profile/edit_profile.html", form=form)


@profile_bp.route(
    "/rate_user/<int:user_id>/<int:transaction_id>", methods=["GET", "POST"]
)
@login_required
def rate_user(user_id, transaction_id):
    form = RateUserForm()
    user_to_rate = User.query.get_or_404(user_id)

    # לוודא שמשתמש לא יכול לדרג את עצמו
    if user_id == current_user.id:
        flash("You cannot rate yourself!", "warning")
        return redirect(url_for("profile.user_profile", user_id=user_id))

    # לוודא שהעסקה קיימת בין המשתמשים (transaction)
    transaction = Transaction.query.filter_by(
        id=transaction_id, buyer_id=current_user.id, seller_id=user_to_rate.id
    ).first()

    if not transaction:
        flash("Transaction not found or unauthorized.", "error")
        return redirect(url_for("profile.user_profile", user_id=user_id))

    # לוודא שלא קיימת ביקורת על העסקה הזו
    existing_review = UserReview.query.filter_by(
        reviewer_id=current_user.id,
        reviewed_user_id=user_to_rate.id,
        transaction_id=transaction.id,
    ).first()

    if existing_review:
        flash("You have already written a review for this transaction.", "warning")
        return redirect(url_for("profile.user_profile", user_id=user_id))

    if form.validate_on_submit():
        new_review = UserReview(
            reviewer_id=current_user.id,
            reviewed_user_id=user_to_rate.id,
            transaction_id=transaction.id,  # קישור הביקורת לעסקה
            rating=form.rating.data,
            comment=form.comment.data,
        )
        db.session.add(new_review)
        db.session.commit()
        flash("Your review has been saved successfully!", "success")
        return redirect(url_for("profile.user_profile", user_id=current_user.id))

    return render_template(
        "profile/rate_user.html",
        form=form,
        user_to_rate=user_to_rate,
        transaction=transaction,
    )


@profile_bp.route("/user_profile/<int:user_id>", methods=["GET", "POST"])
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    form = ProfileForm()

    # הגדרת האם המשתמש הנוכחי הוא הבעלים של הפרופיל
    is_owner = current_user.id == user.id
    is_admin = current_user.is_admin if hasattr(current_user, "is_admin") else False

    # 1) מחשבים דירוג ממוצע של המשתמש (אם יש ביקורות)
    avg_rating = (
        db.session.query(func.avg(UserReview.rating))
        .filter(UserReview.reviewed_user_id == user.id)
        .scalar()
    )
    if avg_rating is not None:
        avg_rating = round(avg_rating, 1)  # עיגול לעשרון אחד
    else:
        avg_rating = None  # אם אין ביקורות בכלל

    # 3) שליפת כל הביקורות שהמשתמש (user) קיבל, כדי להציגן בתבנית
    ratings = (
        UserReview.query.filter_by(reviewed_user_id=user.id)
        .order_by(UserReview.created_at.desc())
        .all()
    )

    # פונקציית עזר לבדיקת האם המשתמש הנוכחי כתב כבר ביקורת על עסקה ספציפית
    def review_already_exists(transaction_id):
        existing = UserReview.query.filter_by(
            reviewer_id=current_user.id,
            reviewed_user_id=user.id,
            transaction_id=transaction_id,
        ).first()
        return existing is not None

    # 4) אתחול הטופס עם ערכי המשתמש (GET)
    if request.method == "GET":
        form.first_name.data = user.first_name
        form.last_name.data = user.last_name
        form.age.data = user.age
        form.gender.data = user.gender

    # 5) טיפול ב-POST: שמירת ערכי הטופס
    if form.validate_on_submit():
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.age = form.age.data
        user.gender = form.gender.data

        db.session.commit()
        flash("פרופיל עודכן בהצלחה!", "success")
        return redirect(url_for("profile.user_profile", user_id=user.id))

    # מילוי טופס הפרופיל רק לבעל הפרופיל
    if is_owner:
        form.first_name.data = user.first_name
        form.last_name.data = user.last_name
        form.age.data = user.age
        form.gender.data = user.gender

    # 6) העברת כל הנתונים לתבנית
    return render_template(
        "profile/user_profile.html",
        form=form,
        user=user,
        avg_rating=avg_rating,  # נוספו
        is_owner=is_owner,  # נוספו
        ratings=ratings,  # נוספו
        review_already_exists=review_already_exists,  # נוספו
    )


@profile_bp.route("/user_profile")
@login_required
def user_profile_default():
    return redirect(url_for("profile.user_profile", user_id=current_user.id))


@profile_bp.route("/landing_page")
def landing_page():
    # שליפת סכום (value - cost) מכל הקופונים
    total_savings = (
        db.session.query(db.func.sum(Coupon.value - Coupon.cost))
        .filter(Coupon.is_for_sale == False)
        .scalar()
    )
    if not total_savings:
        total_savings = 0  # אם לא הוחזר ערך (None), נאפס ל-0

    # העברת המשתנה total_savings לטמפלט
    return render_template("landing_page.html", total_savings=total_savings)


@profile_bp.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("סיסמא נוכחית שגויה", "danger")
            return render_template("profile/change_password.html", form=form)

        if form.current_password.data == form.new_password.data:
            flash("הסיסמא החדשה חייבת להיות שונה מהסיסמא הנוכחית", "danger")
            return render_template("profile/change_password.html", form=form)

        # Store the new password in session for confirmation
        session["new_password"] = form.new_password.data

        # Generate token for confirmation
        token = current_user.generate_password_change_token()

        # Send confirmation email
        if send_password_change_email(current_user, token):
            flash("נשלח מייל אישור לשינוי הסיסמא. אנא בדוק את תיבת הדואר שלך.", "info")
        else:
            flash("אירעה שגיאה בשליחת מייל האישור. אנא נסה שוב מאוחר יותר.", "danger")
            return render_template("profile/change_password.html", form=form)

        return redirect(url_for("profile.user_profile", user_id=current_user.id))

    return render_template("profile/change_password.html", form=form)


@profile_bp.route("/confirm_password_change/<token>")
@login_required
def confirm_password_change(token):
    try:
        if current_user.verify_password_change_token(token):
            # Get the new password from the session
            new_password = session.get("new_password")
            if not new_password:
                flash("לא נמצאה סיסמא חדשה לאישור. אנא נסה שוב.", "danger")
                return redirect(url_for("profile.change_password"))

            # Update password
            current_user.set_password(new_password)
            db.session.commit()

            # Clear the session
            session.pop("new_password", None)

            flash("הסיסמא עודכנה בהצלחה!", "success")
        else:
            flash("הקישור לאישור שינוי הסיסמא אינו תקין או פג תוקף.", "danger")
    except Exception as e:
        flash("אירעה שגיאה בעת אישור שינוי הסיסמא. אנא נסה שוב.", "danger")
        current_app.logger.error(f"Error confirming password change: {str(e)}")

    return redirect(url_for("profile.user_profile", user_id=current_user.id))
