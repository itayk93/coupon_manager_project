# app/routes/profile_routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, send_file
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func
import re
import os
import pandas as pd
from io import BytesIO
from datetime import datetime, timezone, timedelta
from werkzeug.utils import secure_filename
import pytz  # ספרייה לניהול אזורי זמן
import random

from app.extensions import db, cache
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
    TelegramUser,
    UserReview,
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


@profile_bp.route("/faq")
def faq():
    """
    דף שאלות נפוצות לניהול קופונים דיגיטליים
    """
    return render_template("faq.html")


@profile_bp.route("/load_more_coupons")
@login_required
def load_more_coupons():
    """
    AJAX endpoint to load more coupons for lazy loading
    """
    try:
        offset = request.args.get('offset', 0, type=int)
        limit = request.args.get('limit', 50, type=int)
        
        # Load all remaining coupons (no limit)
        more_coupons = Coupon.query.filter(
            Coupon.user_id == current_user.id
        ).order_by(Coupon.date_added.desc()).offset(offset).all()
        
        # Convert to JSON format
        coupons_data = []
        for coupon in more_coupons:
            coupons_data.append({
                'id': coupon.id,
                'code': coupon.code,
                'company': coupon.company,
                'value': coupon.value,
                'remaining_value': coupon.value - coupon.used_value,
                'status': coupon.status,
                'is_one_time': coupon.is_one_time,
                'is_for_sale': coupon.is_for_sale,
                'expiration': coupon.expiration.strftime('%Y-%m-%d') if coupon.expiration else None
            })
        
        return jsonify({
            'success': True,
            'coupons': coupons_data,
            'has_more': len(more_coupons) == limit
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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
    # OPTIMIZED: Single query with eager loading instead of 6 separate queries
    # --------------------------------------------------------------------------------

    # Load all user coupons (removed pagination limit)
    all_user_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id
    ).order_by(Coupon.date_added.desc()).all()
    
    has_more_coupons = False
    remaining_count = 0

    # Filter in memory (much faster than separate DB queries)
    all_coupons = [c for c in all_user_coupons 
                   if not c.is_for_sale and c.exclude_saving != True]
    
    coupons_for_sale = [c for c in all_user_coupons if c.is_for_sale]
    
    active_one_time_coupons = [c for c in all_coupons 
                               if c.status == "פעיל" and c.is_one_time]
    
    used_coupons = [c for c in all_coupons 
                    if c.status != "פעיל"]
    
    active_coupons = [c for c in all_coupons 
                      if c.status == "פעיל" and not c.is_one_time]

    # --------------------------------------------------------------------------------
    # 1. Calculate total coupons and savings - INCLUDING BOTH ONE-TIME AND NON-ONE-TIME
    # --------------------------------------------------------------------------------

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
    # 3. OPTIMIZED: Status updates with session-based caching
    # --------------------------------------------------------------------------------
    from app.models import clear_status_update_cache
    from flask import session
    from datetime import date
    
    today = date.today().isoformat()
    cache_key = f'status_updated_{current_user.id}'
    
    # Only update statuses if not done today (using session cache)
    if session.get(cache_key) != today:
        all_to_update = all_coupons + coupons_for_sale
        for coupon in all_to_update:
            update_coupon_status(coupon)
        
        # Mark as updated today in session
        session[cache_key] = today
        
        # Clear cache after processing all coupons
        clear_status_update_cache()
        db.session.commit()
    else:
        # Status already updated today - skip expensive operations
        pass

    # --------------------------------------------------------------------------------
    # 4. Check "Are there coupons expiring in the next 7 days" + show banner once a day
    # --------------------------------------------------------------------------------

    # Check if user dismissed the alert today
    dismissed_today = (
        current_user.dismissed_expiring_alert_at is not None
        and current_user.dismissed_expiring_alert_at == date.today()
    )

    # Find coupons expiring in the next week (using already loaded data)
    one_week_from_now = date.today() + timedelta(days=7)
    today = date.today()
    
    expiring_coupons = []
    for coupon in all_coupons:
        if (coupon.status == "פעיל" and 
            coupon.expiration is not None):
            
            # Handle expiration date format
            exp_date = coupon.expiration
            if isinstance(exp_date, str):
                try:
                    exp_date = datetime.strptime(exp_date, "%Y-%m-%d").date()
                except ValueError:
                    continue  # Skip invalid dates
            elif hasattr(exp_date, 'date'):
                exp_date = exp_date.date()
            
            if today <= exp_date <= one_week_from_now:
                expiring_coupons.append(coupon)

    # Show alert only if there are relevant coupons and user hasn't dismissed the alert today
    show_expiring_alert = len(expiring_coupons) > 0 and not dismissed_today

    # --------------------------------------------------------------------------------
    # 5. Companies mapping - using traditional query (company is a string field, not FK)
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
    # 6. OPTIMIZED: Database aggregation for company statistics instead of Python loops
    # --------------------------------------------------------------------------------
    from sqlalchemy import case
    
    # Single aggregated query for company statistics
    company_stats_query = db.session.query(
        Coupon.company,
        func.count(Coupon.id).label('count'),
        func.sum(Coupon.value).label('total_value'),
        func.sum(Coupon.used_value).label('used_value'),
        func.sum(Coupon.value - Coupon.used_value).label('remaining_value'),
        func.sum(case((Coupon.value > Coupon.cost, Coupon.value - Coupon.cost), else_=0)).label('savings'),
        func.sum(case((Coupon.is_one_time == True, 1), else_=0)).label('one_time_count'),
        func.sum(case((Coupon.is_one_time == False, 1), else_=0)).label('non_one_time_count'),
        func.min(case((Coupon.status == "פעיל", Coupon.expiration), else_=None)).label('earliest_expiration')
    ).filter(
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        Coupon.exclude_saving != True
    ).group_by(Coupon.company).all()
    
    # Convert query results to dictionaries
    companies_stats = {}
    company_earliest_expirations = {}
    company_coupon_types = {}
    
    for stat in company_stats_query:
        company = stat.company
        companies_stats[company] = {
            "total_value": float(stat.total_value or 0),
            "used_value": float(stat.used_value or 0),
            "remaining_value": float(stat.remaining_value or 0),
            "savings": float(stat.savings or 0),
            "count": stat.count,
            "one_time_count": stat.one_time_count,
            "non_one_time_count": stat.non_one_time_count,
        }
        company_coupon_types[company] = {
            "one_time": stat.one_time_count,
            "non_one_time": stat.non_one_time_count
        }
        
        # Track earliest expiration
        if stat.earliest_expiration:
            company_earliest_expirations[company] = stat.earliest_expiration
    
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

    # OPTIMIZED: Simplified monthly timeline processing (avoid PostgreSQL complexity)
    monthly_data = {}
    
    # Use memory processing for monthly data (still much faster than original nested loops)
    for coupon in all_coupons:
        if hasattr(coupon, "date_added") and coupon.date_added:
            month_key = coupon.date_added.strftime("%Y-%m")

            if month_key not in monthly_data:
                monthly_data[month_key] = {
                    "savings": 0,
                    "count": 0,
                    "original_value": 0,
                    "remaining_value": 0,
                    "companies": set(),
                    "one_time_count": 0,
                    "non_one_time_count": 0,
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

    # OPTIMIZED: Use already calculated values instead of loops
    total_coupons_count = len(all_coupons)
    active_coupons_count = len(active_coupons) + len(active_one_time_coupons)
    total_companies_count = len(companies_stats)

    # Calculate average usage percentage using existing totals
    average_usage_percentage = 0
    if total_coupons_value > 0:
        total_used_value = sum(coupon.used_value for coupon in all_coupons)
        average_usage_percentage = (total_used_value / total_coupons_value) * 100

    # Use memory filtering instead of loops for counts
    one_time_count = len(active_one_time_coupons) + len([c for c in used_coupons if c.is_one_time])
    non_one_time_count = total_coupons_count - one_time_count

    # --------------------------------------------------------------------------------
    # 10. OPTIMIZED: Convert data for JSON and template rendering with caching
    # --------------------------------------------------------------------------------
    
    # Cache for parsed dates to avoid repeated parsing
    _date_parse_cache = {}
    
    def parse_date_cached(date_str):
        if date_str not in _date_parse_cache:
            _date_parse_cache[date_str] = datetime.strptime(date_str, "%Y-%m-%d").date()
        return _date_parse_cache[date_str]

    # Convert expiration from String to Date (if it's not None) with caching
    for coupon in expiring_coupons:
        if isinstance(coupon.expiration, str):  # If expiration is a string
            coupon.expiration = parse_date_cached(coupon.expiration)

    # OPTIMIZED: Convert companies data to format for JavaScript with pre-calculated values
    
    # Pre-calculate active coupons per company to avoid repeated loops
    active_coupons_by_company = {}
    for coupon in active_coupons + active_one_time_coupons:
        company = coupon.company
        active_coupons_by_company[company] = active_coupons_by_company.get(company, 0) + 1
    
    sorted_company_data = []
    for company, stats in sorted_companies:
        # Get earliest expiration date for this company
        earliest_expiration = None
        if company in company_earliest_expirations:
            exp_date = company_earliest_expirations[company]
            if exp_date:
                # Handle both string and date objects
                if isinstance(exp_date, str):
                    earliest_expiration = exp_date
                elif hasattr(exp_date, 'strftime'):
                    earliest_expiration = exp_date.strftime("%Y-%m-%d")
                else:
                    earliest_expiration = str(exp_date)

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
                "active_coupons": active_coupons_by_company.get(company, 0),
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
        # Add WhatsApp banner flag
        show_whatsapp_banner=current_user.show_whatsapp_banner,
        # Lazy loading variables
        has_more_coupons=has_more_coupons,
        remaining_count=remaining_count,
        total_user_coupons_count=total_coupons_count,
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
        flash("לא ניתן לדרג את עצמך!", "warning")
        return redirect(url_for("profile.user_profile", user_id=user_id))

    # לוודא שהעסקה קיימת בין המשתמשים (transaction)
    # בדיקה שהמשתמש הנוכחי היה חלק מהעסקה (קונה או מוכר)
    transaction = Transaction.query.filter(
        (Transaction.id == transaction_id) &
        (
            ((Transaction.buyer_id == current_user.id) & (Transaction.seller_id == user_to_rate.id)) |
            ((Transaction.seller_id == current_user.id) & (Transaction.buyer_id == user_to_rate.id))
        )
    ).first()

    if not transaction:
        flash("עסקה לא נמצאה או אין הרשאה.", "error")
        return redirect(url_for("profile.user_profile", user_id=user_id))

    # לוודא שלא קיימת ביקורת על העסקה הזו
    existing_review = UserReview.query.filter_by(
        reviewer_id=current_user.id,
        reviewed_user_id=user_to_rate.id,
        transaction_id=transaction.id,
    ).first()

    if existing_review:
        flash("כבר כתבת ביקורת על עסקה זו.", "warning")
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
        flash("הביקורת שלך נשמרה בהצלחה!", "success")
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
    """מציג את דף הפרופיל של משתמש ספציפי"""
    user = User.query.get_or_404(user_id)
    is_owner = current_user.id == user_id
    is_admin = current_user.is_admin

    # Get user's ratings
    ratings = UserReview.query.filter_by(reviewed_user_id=user_id).all()
    avg_rating = db.session.query(func.avg(UserReview.rating)).filter_by(reviewed_user_id=user_id).scalar()

    # Get Telegram user info if exists
    telegram_user = None
    if is_owner:
        telegram_user = TelegramUser.query.filter_by(user_id=user_id).first()

    form = ProfileForm()
    if form.validate_on_submit():
        # ... existing form handling code ...
        pass

    return render_template(
        'profile/user_profile.html',
        user=user,
        form=form,
        is_owner=is_owner,
        is_admin=is_admin,
        ratings=ratings,
        avg_rating=avg_rating,
        telegram_user=telegram_user
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


@profile_bp.route('/connect_telegram')
@login_required
def connect_telegram():
    """יצירת קוד אימות לחיבור לבוט טלגרם"""
    try:
        # יצירת קוד אימות אקראי
        verification_code = ''.join(random.choices('0123456789', k=6))
        
        # שמירת הקוד במסד הנתונים
        telegram_user = TelegramUser.query.filter_by(user_id=current_user.id).first()
        if not telegram_user:
            telegram_user = TelegramUser(
                user_id=current_user.id,
                verification_token=verification_code,
                verification_expires_at=datetime.utcnow() + timedelta(minutes=10),
                is_verified=False,
                ip_address=request.remote_addr,
                device_info=request.user_agent.string
            )
            db.session.add(telegram_user)
        else:
            telegram_user.verification_token = verification_code
            telegram_user.verification_expires_at = datetime.utcnow() + timedelta(minutes=10)
            telegram_user.is_verified = False
        
        try:
            db.session.commit()
            flash(f'קוד האימות שלך הוא: {verification_code}. שלח אותו לבוט כדי להתחבר.', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Database error in connect_telegram: {str(e)}")
            flash('אירעה שגיאה ביצירת קוד האימות. אנא נסה שוב מאוחר יותר.', 'error')
            return redirect(url_for('profile.user_profile', user_id=current_user.id))
        
        return redirect(url_for('profile.user_profile', user_id=current_user.id))
        
    except Exception as e:
        current_app.logger.error(f"Error in connect_telegram: {str(e)}")
        flash('אירעה שגיאה ביצירת קוד האימות. אנא נסה שוב מאוחר יותר.', 'error')
        return redirect(url_for('profile.user_profile', user_id=current_user.id))


@profile_bp.route("/preferences", methods=["GET", "POST"])
@login_required
def user_preferences():
    """עמוד העדפות משתמש"""
    if request.method == "POST":
        try:
            # עדכון העדפות המשתמש
            current_user.newsletter_subscription = 'newsletter_subscription' in request.form
            current_user.telegram_monthly_summary = 'telegram_monthly_summary' in request.form
            
            db.session.commit()
            flash("ההעדפות שלך נשמרו בהצלחה!", "success")
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating user preferences: {str(e)}")
            flash("אירעה שגיאה בשמירת ההעדפות. אנא נסה שוב.", "error")
        
        return redirect(url_for('profile.user_preferences'))
    
    return render_template("profile/user_preferences.html")


@profile_bp.route("/unsubscribe")
def unsubscribe_newsletter():
    """ביטול הרשמה לניוזלטר"""
    user_id = request.args.get('user_id')
    token = request.args.get('token')
    
    if not user_id or not token:
        flash("קישור לא תקין לביטול הרשמה.", "error")
        return redirect(url_for('auth.login'))
    
    try:
        user = User.query.get(int(user_id))
        if not user:
            flash("משתמש לא נמצא.", "error")
            return redirect(url_for('auth.login'))
        
        # בדיקת תוקף הטוקן
        from app.routes.admin_routes.admin_newsletter_routes import generate_unsubscribe_token
        expected_token = generate_unsubscribe_token(user)
        
        if token != expected_token:
            flash("קישור לא תקין לביטול הרשמה.", "error")
            return redirect(url_for('auth.login'))
        
        # שמירת נתוני הטוקן בסשן ודרישת התחברות
        from flask import session
        session['unsubscribe_user_id'] = user.id
        session['unsubscribe_token'] = token
        
        flash("כדי לבטל הרשמה לניוזלטר, אנא התחבר לחשבון שלך", "info")
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in unsubscribe_newsletter: {str(e)}")
        flash("אירעה שגיאה בביטול ההרשמה. אנא נסה שוב מאוחר יותר.", "error")
    
    return redirect(url_for('auth.login'))


@profile_bp.route("/complete_unsubscribe")
@login_required
def complete_unsubscribe():
    """השלמת ביטול הרשמה לניוזלטר אחרי התחברות"""
    from flask import session
    
    # בדיקה שיש בסשן בקשה לביטול מנוי
    if 'unsubscribe_user_id' not in session or 'unsubscribe_token' not in session:
        flash("לא נמצאה בקשה לביטול הרשמה.", "error")
        return redirect(url_for('profile.user_preferences'))
    
    # בדיקה שהמשתמש המחובר זהה למשתמש שביקש לבטל
    if current_user.id != session['unsubscribe_user_id']:
        flash("לא ניתן לבטל הרשמה עבור משתמש אחר.", "error")
        session.pop('unsubscribe_user_id', None)
        session.pop('unsubscribe_token', None)
        return redirect(url_for('profile.user_preferences'))
    
    # אימות הטוקן שוב
    from app.routes.admin_routes.admin_newsletter_routes import generate_unsubscribe_token
    expected_token = generate_unsubscribe_token(current_user)
    
    if session['unsubscribe_token'] != expected_token:
        flash("טוקן לא תקין לביטול הרשמה.", "error")
        session.pop('unsubscribe_user_id', None)
        session.pop('unsubscribe_token', None)
        return redirect(url_for('profile.user_preferences'))
    
    try:
        # ביטול הרשמה לניוזלטר
        current_user.newsletter_subscription = False
        db.session.commit()
        
        # ניקוי הסשן
        session.pop('unsubscribe_user_id', None)
        session.pop('unsubscribe_token', None)
        
        flash("ההרשמה לניוזלטר בוטלה בהצלחה. אנו מצטערים לראותכם הולכים!", "success")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in complete_unsubscribe: {str(e)}")
        flash("אירעה שגיאה בביטול ההרשמה. אנא נסה שוב מאוחר יותר.", "error")
    
    return redirect(url_for('profile.user_preferences'))


@profile_bp.route("/complete_preferences")
@login_required
def complete_preferences():
    """השלמת עדכון העדפות אחרי התחברות"""
    from flask import session
    
    # בדיקה שיש בסשן בקשה לעדכון העדפות
    if 'preferences_user_id' not in session or 'preferences_token' not in session:
        flash("לא נמצאה בקשה לעדכון העדפות.", "error")
        return redirect(url_for('profile.user_preferences'))
    
    # בדיקה שהמשתמש המחובר זהה למשתמש שביקש לעדכן
    if current_user.id != session['preferences_user_id']:
        flash("לא ניתן לעדכן העדפות עבור משתמש אחר.", "error")
        session.pop('preferences_user_id', None)
        session.pop('preferences_token', None)
        return redirect(url_for('profile.user_preferences'))
    
    # אימות הטוקן שוב
    from app.routes.admin_routes.admin_newsletter_routes import generate_preferences_token
    expected_token = generate_preferences_token(current_user)
    
    if session['preferences_token'] != expected_token:
        flash("טוקן לא תקין לעדכון העדפות.", "error")
        session.pop('preferences_user_id', None)
        session.pop('preferences_token', None)
        return redirect(url_for('profile.user_preferences'))
    
    # ניקוי הסשן
    session.pop('preferences_user_id', None)
    session.pop('preferences_token', None)
    
    flash("כאן תוכלו לעדכן את העדפות הדוא\"ל והטלגרם שלכם", "info")
    return redirect(url_for('profile.user_preferences'))


@profile_bp.route("/preferences_from_email")
def preferences_from_email():
    """עדכון העדפות ממייל - הפניה לעמוד האתר"""
    user_id = request.args.get('user_id')
    token = request.args.get('token')
    
    if not user_id or not token:
        flash("קישור לא תקין לעדכון העדפות.", "error")
        return redirect(url_for('auth.login'))
    
    try:
        user = User.query.get(int(user_id))
        if not user:
            flash("משתמש לא נמצא.", "error")
            return redirect(url_for('auth.login'))
        
        # בדיקת תוקף הטוקן
        from app.routes.admin_routes.admin_newsletter_routes import generate_preferences_token
        expected_token = generate_preferences_token(user)
        
        if token != expected_token:
            flash("קישור לא תקין לעדכון העדפות.", "error")
            return redirect(url_for('auth.login'))
        
        # שמירת נתוני הטוקן בסשן ודרישת התחברות
        from flask import session
        session['preferences_user_id'] = user.id
        session['preferences_token'] = token
        
        flash("כדי לעדכן את העדפות המייל, אנא התחבר לחשבון שלך", "info")
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        current_app.logger.error(f"Error in preferences_from_email: {str(e)}")
        flash("אירעה שגיאה. אנא נסו שוב מאוחר יותר.", "error")
        return redirect(url_for('auth.login'))
