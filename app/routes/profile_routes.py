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
from app.models import Coupon, Company, Tag, CouponUsage, Transaction, Notification, CouponRequest, GptUsage, CouponTransaction
from app.forms import ProfileForm, SellCouponForm, UploadCouponsForm, AddCouponsBulkForm, CouponForm, DeleteCouponsForm, ConfirmDeleteForm, MarkCouponAsUsedForm, EditCouponForm, ApproveTransactionForm,SMSInputForm
from app.helpers import update_coupon_status, get_coupon_data, process_coupons_excel
from app.helpers import send_coupon_purchase_request_email
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

profile_bp = Blueprint('profile', __name__)
from sqlalchemy.sql import text
from flask import request, current_app
from flask_login import current_user
from app.helpers import get_geo_location, get_public_ip
ip_address = None
from app.models import AdminMessage

def log_user_activity(ip_address,action, coupon_id=None):
    """
    פונקציה מרכזית לרישום activity log.
    """
    try:
        user_agent = request.headers.get('User-Agent', '')

        geo_data = get_geo_location(ip_address)

        # ודא ש-geo_data מחזירה ערכים נכונים
        #print(f"Geo Data: {geo_data}")

        activity = {
            "user_id": current_user.id if current_user and current_user.is_authenticated else None,
            "coupon_id": coupon_id,
            "timestamp": datetime.utcnow(),
            "action": action,
            "device": user_agent[:50] if user_agent else None,
            "browser": user_agent.split(' ')[0][:50] if user_agent else None,
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
            text("""
                INSERT INTO user_activities
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address, city, region, country, isp, 
                     country_code, zip, lat, lon, timezone, org, as_info)
                VALUES
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :city, :region, :country, :isp, 
                     :country_code, :zip, :lat, :lon, :timezone, :org, :as_info)
            """),
            activity
        )
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging activity [{action}]: {e}")

@profile_bp.route('/')
def home():
    if current_user.is_authenticated:
        # רישום הפעולה
        log_user_activity(ip_address, "authorized_index_access")
        return redirect(url_for('profile.index'))
    else:
        log_user_activity(ip_address, "unauthorized_redirect_to_login")
        return redirect(url_for('auth.login'))

def get_greeting():
    israel_tz = pytz.timezone('Asia/Jerusalem')
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
    return request.remote_addr or '0.0.0.0'


@profile_bp.route('/index', methods=['GET', 'POST'])
@login_required
def index():
    from sqlalchemy import cast, Date
    """
    עמוד הפרופיל / הבית שמציג:
    - ברכה (greeting)
    - אפשרות עריכת פרופיל (ProfileForm)
    - חישוב סכומי קופונים (remaining, savings...)
    - הצגת קופונים בקטגוריות שונות
    - הצגת באנר "קופונים שעומדים לפוג תוך 7 ימים" – רק פעם ביום, אם יש כאלה.
    """
    ip_address = get_ip_address()
    log_user_activity(ip_address, "index")

    # טופס עריכת פרופיל
    profile_form = ProfileForm()

    # טופס ראשון: usage
    usage_form = UsageExplanationForm()

    # טופס שני: sms => ליצירת קופון חדש דרך parse SMS
    sms_form = SMSInputForm()

    # בדיקת טופס עריכת פרופיל
    if profile_form.validate_on_submit() and 'age' in request.form:
        current_user.age = profile_form.age.data
        current_user.gender = profile_form.gender.data
        db.session.commit()
        flash('פרטי הפרופיל עודכנו בהצלחה.', 'success')
        return redirect(url_for('profile.index'))

    if request.method == 'GET':
        # מילוי טופס הפרופיל
        profile_form.first_name.data = current_user.first_name
        profile_form.last_name.data = current_user.last_name
        profile_form.age.data = current_user.age
        profile_form.gender.data = current_user.gender

    greeting = get_greeting()  # לדוגמה: בהתאם לשעה, מחזיר "בוקר טוב" / "ערב טוב" וכד'.

    # --------------------------------------------------------------------------------
    # 1. חישוב סך הקופונים והחיסכון (החלק המקורי שלך)
    # --------------------------------------------------------------------------------

    # 1. חישוב סך הקופונים והחיסכון (ללא מסנן סטטוס)
    all_non_one_time_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        ~Coupon.is_one_time,
        Coupon.exclude_saving != True
    ).all()

    total_remaining = sum(coupon.value - coupon.used_value for coupon in all_non_one_time_coupons)
    total_savings = sum(
        (coupon.value - coupon.cost) for coupon in all_non_one_time_coupons if coupon.value > coupon.cost
    )
    total_coupons_value = sum(coupon.value for coupon in all_non_one_time_coupons)
    percentage_savings = (total_savings / total_coupons_value) * 100 if total_coupons_value > 0 else 0

    # 2. חלוקת קופונים לקטגוריות (הקטגוריות נשארות כפי שהן)
    active_one_time_coupons = Coupon.query.filter(
        Coupon.status == 'פעיל',
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        Coupon.is_one_time == True
    ).all()

    used_coupons = Coupon.query.filter(
        Coupon.status != 'פעיל',
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        ~Coupon.is_one_time
    ).all()

    coupons_for_sale = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == True,
        ~Coupon.is_one_time
    ).all()

    active_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.status == 'פעיל',
        Coupon.is_for_sale == False,
        ~Coupon.is_one_time
    ).order_by(Coupon.date_added.desc()).all()

    # 3. עדכון סטטוס – שימוש במשתנה שהגדרנו למעלה
    all_to_update = all_non_one_time_coupons + active_one_time_coupons + used_coupons + coupons_for_sale
    for coupon in all_to_update:
        update_coupon_status(coupon)
    db.session.commit()

    # --------------------------------------------------------------------------------
    # 2. שליפה וחלוקה לקטגוריות (active, active_one_time, used, for_sale)
    # --------------------------------------------------------------------------------

    # קופונים חד-פעמיים פעילים
    active_one_time_coupons = Coupon.query.filter(
        Coupon.status == 'פעיל',
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        Coupon.is_one_time == True
    ).all()

    # קופונים מנוצלים (שאינם פעילים)
    used_coupons = Coupon.query.filter(
        Coupon.status != 'פעיל',
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        ~Coupon.is_one_time
    ).all()

    # קופונים למכירה
    coupons_for_sale = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == True,
        ~Coupon.is_one_time
    ).all()

    # קופונים פעילים (לא-חד-פעמיים)
    active_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.status == 'פעיל',
        Coupon.is_for_sale == False,
        ~Coupon.is_one_time
    ).order_by(Coupon.date_added.desc()).all()

    # --------------------------------------------------------------------------------
    # 3. עדכון סטטוס (לכל הקטגוריות) ואז commit
    # --------------------------------------------------------------------------------
    all_to_update = all_non_one_time_coupons + active_one_time_coupons + used_coupons + coupons_for_sale
    for coupon in all_to_update:
        update_coupon_status(coupon)
    db.session.commit()

    # --------------------------------------------------------------------------------
    # 4. בדיקת "האם יש קופונים שפג תוקפם ב-7 הימים הקרובים" + הצגת באנר פעם ביום
    # --------------------------------------------------------------------------------

    # בדיקה אם המשתמש דחה (dismiss) את ההתרעה היום
    dismissed_today = (session.get('dismissed_expiring_alert_date') == str(date.today()))

    # מציאת קופונים שפג תוקפם בשבוע הקרוב
    one_week_from_now = date.today() + timedelta(days=7)
    expiring_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.status == 'פעיל',
        Coupon.is_for_sale == False,
        Coupon.expiration.isnot(None)  # לוודא שהשדה אינו NULL
    ).filter(
        cast(Coupon.expiration, Date) >= date.today(),
        cast(Coupon.expiration, Date) <= date.today() + timedelta(days=7)
    ).all()

    # בדיקה האם המשתמש דחה (dismiss) את ההתרעה היום
    dismissed_today = (
        current_user.dismissed_expiring_alert_at is not None
        and current_user.dismissed_expiring_alert_at == date.today()
    )

    # מציאת קופונים שפג תוקפם בשבוע הקרוב
    one_week_from_now = date.today() + timedelta(days=7)
    expiring_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.status == 'פעיל',
        Coupon.is_for_sale == False,
        Coupon.expiration.isnot(None)
    ).filter(
        cast(Coupon.expiration, Date) >= date.today(),
        cast(Coupon.expiration, Date) <= one_week_from_now
    ).all()

    # מציגים התראה רק אם יש קופונים רלוונטיים והמשתמש לא דחה את ההתראה היום
    show_expiring_alert = len(expiring_coupons) > 0 and not dismissed_today


    # --------------------------------------------------------------------------------
    # 5. שליפת כל החברות (למפת לוגו, אם רלוונטי)
    # --------------------------------------------------------------------------------
    companies = Company.query.all()
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}

    # --------------------------------------------------------------------------------
    # 6. החזרת ה-Template 'index.html'
    # --------------------------------------------------------------------------------
    # המרה של expiration מ-String ל-Date (אם הוא לא None)
    for coupon in expiring_coupons:
        if isinstance(coupon.expiration, str):  # אם expiration הוא מחרוזת
            coupon.expiration = datetime.strptime(coupon.expiration, "%Y-%m-%d").date()

    # --------------------------------------------------------------------------------
    # הודעת אדמין
    # --------------------------------------------------------------------------------
    # קבלת ההודעה האחרונה
    latest_message = AdminMessage.query.order_by(AdminMessage.id.desc()).first()
    show_admin_message = False

    if latest_message:
        if (current_user.dismissed_message_id is None) or (current_user.dismissed_message_id < latest_message.id):
            show_admin_message = True
    return render_template(
        'index.html',
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

        # משתנים רלוונטיים להתראות
        show_expiring_alert=show_expiring_alert,
        expiring_coupons=expiring_coupons,

        # ✅ הוספת current_date ו-timedelta לתבנית
        current_date=date.today(),
        timedelta=timedelta,

        show_admin_message=show_admin_message,
        admin_message=latest_message if show_admin_message else None)



@profile_bp.route('/dismiss_expiring_alert', methods=['GET'])
@login_required
def dismiss_expiring_alert():
    """
    המשתמש לחץ על X בסרגל ההתראות => עדכון התאריך האחרון שבו דחה את ההתראה בדאטהבייס.
    """
    current_user.dismissed_expiring_alert_at = date.today()
    db.session.commit()
    
    return redirect(url_for('profile.index'))

@profile_bp.route('/notifications')
@login_required
def notifications():
    notifications_list = Notification.query.filter_by(
        user_id=current_user.id,
        hide_from_view=False
    ).order_by(Notification.timestamp.desc()).all()
    return render_template('notifications.html', notifications=notifications_list)

@profile_bp.route('/delete_notification/<int:notification_id>', methods=['POST'])
@login_required
def delete_notification(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=current_user.id,
        hide_from_view=False
    ).first()
    if notification:
        notification.hide_from_view = True  # סימון כהוסתר
        db.session.commit()
        return jsonify({'status': 'success'})
    else:
        return jsonify({'status': 'error', 'message': 'התראה לא נמצאה'}), 404

@profile_bp.route('/delete_all_notifications', methods=['POST'])
@login_required
def delete_all_notifications():
    try:
        logger.info(f"User {current_user.id} is attempting to hide all notifications.")
        notifications = Notification.query.filter_by(
            user_id=current_user.id,
            hide_from_view=False
        ).all()
        for notification in notifications:
            notification.hide_from_view = True
        db.session.commit()
        logger.info(f"User {current_user.id} hid {len(notifications)} notifications.")
        return jsonify({'status': 'success', 'deleted': len(notifications)})
    except Exception as e:
        logger.error(f"Error hiding all notifications: {e}")
        return jsonify({'status': 'error', 'message': 'שגיאה במחיקת ההתראות'}), 500

@profile_bp.route('/update_profile_field', methods=['POST'])
@login_required
def update_profile_field():
    try:
        data = request.get_json()
        field = data.get('field')
        value = data.get('value')

        logger.info(f"Received update for field: {field} with value: {value}")

        csrf_token = request.headers.get('X-CSRFToken')
        #print(f"Received CSRF Token: {csrf_token}")
        if not csrf_token:
            logger.warning("Missing CSRF token in request.")
            return jsonify({'status': 'error', 'message': 'Missing CSRF token.'}), 400

        try:
            validate_csrf(csrf_token)
        except ValidationError:
            logger.warning("Invalid CSRF token.")
            return jsonify({'status': 'error', 'message': 'Invalid CSRF token.'}), 400

        allowed_fields = ['first_name', 'last_name', 'age', 'gender']
        if field not in allowed_fields:
            logger.warning(f"Attempt to update unauthorized field: {field}")
            return jsonify({'status': 'error', 'message': 'Unauthorized field.'}), 400

        user = User.query.get(current_user.id)
        setattr(user, field, value)
        db.session.commit()

        logger.info(f"Successfully updated field: {field} for user: {current_user.id}")
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating field: {field} for user: {current_user.id}. Error: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Server error. Please try again later.'}), 500

@profile_bp.route('/about')
def about():
    return render_template('about.html')

@profile_bp.route('/buy_slots', methods=['GET', 'POST'])
@login_required
def buy_slots():
    form = BuySlotsForm()
    if form.validate_on_submit():
        try:
            slot_amount = int(form.slot_amount.data)
            if slot_amount not in [10, 20, 50]:
                flash('כמות סלוטים לא תקפה.', 'danger')
                return redirect(url_for('profile.buy_slots'))

            current_user.slots += slot_amount
            db.session.commit()
            flash(f'רכשת {slot_amount} סלוטים בהצלחה!', 'success')
            return redirect(url_for('profile.buy_slots'))
        except ValueError:
            flash('כמות סלוטים לא תקפה.', 'danger')
            return redirect(url_for('profile.buy_slots'))
    return render_template('buy_slots.html', slots=current_user.slots, form=form)

@profile_bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """
    עריכת פרופיל המשתמש המחובר: תיאור קצר + תמונת פרופיל.
    """
    form = UserProfileForm()

    if request.method == 'POST':
        if form.validate_on_submit():
            # עדכון התיאור
            current_user.profile_description = form.profile_description.data

            # העלאת תמונה (אם הועלתה)
            if form.profile_image.data:
                file = form.profile_image.data
                if allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # שמירה בנתיב קבוע בתוך static/uploads, למשל
                    upload_path = os.path.join('app', 'static', 'uploads', 'profiles')
                    os.makedirs(upload_path, exist_ok=True)
                    save_path = os.path.join(upload_path, filename)
                    file.save(save_path)

                    # שמירת הנתיב בבסיס הנתונים
                    current_user.profile_image = f'static/uploads/profiles/{filename}'
                else:
                    flash('סוג קובץ לא תקין. יש להעלות תמונה בפורמט jpg/png/gif', 'danger')
                    return redirect(url_for('profile.edit_profile'))

            db.session.commit()
            flash('פרופיל עודכן בהצלחה!', 'success')
            return redirect(url_for('profile.profile_view', user_id=current_user.id))
        else:
            flash('נא לתקן את השגיאות בטופס.', 'danger')

    # מילוי ערכים קיימים
    if request.method == 'GET':
        form.profile_description.data = current_user.profile_description

    return render_template('profile/edit_profile.html', form=form)


@profile_bp.route('/rate_user/<int:user_id>/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def rate_user(user_id, transaction_id):
    form = RateUserForm()
    user_to_rate = User.query.get_or_404(user_id)

    # לוודא שמשתמש לא יכול לדרג את עצמו
    if user_id == current_user.id:
        flash('You cannot rate yourself!', 'warning')
        return redirect(url_for('profile.user_profile', user_id=user_id))

    # לוודא שהעסקה קיימת בין המשתמשים (transaction)
    transaction = Transaction.query.filter_by(
        id=transaction_id,
        buyer_id=current_user.id,
        seller_id=user_to_rate.id
    ).first()

    if not transaction:
        flash('Transaction not found or unauthorized.', 'error')
        return redirect(url_for('profile.user_profile', user_id=user_id))

    # לוודא שלא קיימת ביקורת על העסקה הזו
    existing_review = UserReview.query.filter_by(
        reviewer_id=current_user.id,
        reviewed_user_id=user_to_rate.id,
        transaction_id=transaction.id
    ).first()

    if existing_review:
        flash('You have already written a review for this transaction.', 'warning')
        return redirect(url_for('profile.user_profile', user_id=user_id))

    if form.validate_on_submit():
        new_review = UserReview(
            reviewer_id=current_user.id,
            reviewed_user_id=user_to_rate.id,
            transaction_id=transaction.id,  # קישור הביקורת לעסקה
            rating=form.rating.data,
            comment=form.comment.data
        )
        db.session.add(new_review)
        db.session.commit()
        flash('Your review has been saved successfully!', 'success')
        return redirect(url_for('profile.user_profile', user_id=current_user.id))

    return render_template('profile/rate_user.html', form=form, user_to_rate=user_to_rate, transaction=transaction)

@profile_bp.route('/user_profile/<int:user_id>', methods=['GET', 'POST'])
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    form = ProfileForm()

    # הגדרת האם המשתמש הנוכחי הוא הבעלים של הפרופיל
    is_owner = (current_user.id == user.id)
    is_admin = current_user.is_admin if hasattr(current_user, 'is_admin') else False

    # 1) מחשבים דירוג ממוצע של המשתמש (אם יש ביקורות)
    avg_rating = db.session.query(func.avg(UserReview.rating)).filter(
        UserReview.reviewed_user_id == user.id
    ).scalar()
    if avg_rating is not None:
        avg_rating = round(avg_rating, 1)  # עיגול לעשרון אחד
    else:
        avg_rating = None  # אם אין ביקורות בכלל

    # 3) שליפת כל הביקורות שהמשתמש (user) קיבל, כדי להציגן בתבנית
    ratings = UserReview.query.filter_by(reviewed_user_id=user.id)\
                              .order_by(UserReview.created_at.desc())\
                              .all()

    # פונקציית עזר לבדיקת האם המשתמש הנוכחי כתב כבר ביקורת על עסקה ספציפית
    def review_already_exists(transaction_id):
        existing = UserReview.query.filter_by(
            reviewer_id=current_user.id,
            reviewed_user_id=user.id,
            transaction_id=transaction_id
        ).first()
        return existing is not None

    # 4) אתחול הטופס עם ערכי המשתמש (GET)
    if request.method == 'GET':
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
        flash('פרופיל עודכן בהצלחה!', 'success')
        return redirect(url_for('profile.user_profile', user_id=user.id))

    # מילוי טופס הפרופיל רק לבעל הפרופיל
    if is_owner:
        form.first_name.data = user.first_name
        form.last_name.data = user.last_name
        form.age.data = user.age
        form.gender.data = user.gender

    # 6) העברת כל הנתונים לתבנית
    return render_template(
        'profile/user_profile.html',
        form=form,
        user=user,
        avg_rating=avg_rating,      # נוספו
        is_owner=is_owner,          # נוספו
        ratings=ratings,            # נוספו
        review_already_exists=review_already_exists  # נוספו
    )

@profile_bp.route('/user_profile')
@login_required
def user_profile_default():
    return redirect(url_for('profile.user_profile', user_id=current_user.id))
