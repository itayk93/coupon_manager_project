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

from app.extensions import db
from app.models import Coupon, Company, Tag, CouponUsage, Transaction, Notification, CouponRequest, GptUsage, CouponTransaction
from app.forms import ProfileForm, SellCouponForm, UploadCouponsForm, AddCouponsBulkForm, CouponForm, DeleteCouponsForm, ConfirmDeleteForm, MarkCouponAsUsedForm, EditCouponForm, ApproveTransactionForm
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

logger = logging.getLogger(__name__)

profile_bp = Blueprint('profile', __name__)


@profile_bp.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('profile.index'))
    return render_template('index.html')  # מסך ראשי למשתמשים לא מחוברים


@profile_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm()
    if form.validate_on_submit():
        # Update user's profile details
        current_user.first_name = form.first_name.data
        current_user.last_name = form.last_name.data
        current_user.age = form.age.data
        current_user.gender = form.gender.data
        db.session.commit()
        flash('פרטי הפרופיל עודכנו בהצלחה.', 'success')
        return redirect(url_for('profile.profile'))

    if request.method == 'GET':
        # Pre-fill the form with existing user data
        form.first_name.data = current_user.first_name
        form.last_name.data = current_user.last_name
        form.age.data = current_user.age
        form.gender.data = current_user.gender

    return render_template('profile/profile.html', form=form)

@profile_bp.route('/index', methods=['GET', 'POST'])
@login_required
def index():
    form = ProfileForm()
    if form.validate_on_submit():
        # עדכון פרטי המשתמש
        current_user.age = form.age.data
        current_user.gender = form.gender.data
        db.session.commit()
        flash('פרטי הפרופיל עודכנו בהצלחה.', 'success')
        return redirect(url_for('profile.index'))

    if request.method == 'GET':
        # מילוי הטופס עם נתוני המשתמש הקיימים
        form.first_name.data = current_user.first_name
        form.last_name.data = current_user.last_name
        form.age.data = current_user.age
        form.gender.data = current_user.gender

    # חישוב סך הקופונים והחיסכון לאחר עדכון הסטטוס
    all_non_one_time_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.status == 'פעיל',  # רק קופונים פעילים
        Coupon.is_for_sale == False,
        ~Coupon.is_one_time,  # לא חד פעמיים
        Coupon.exclude_saving != True  # סינון קופונים מסומנים כ-excluded
    ).all()

    print("קופונים פעילים שנכנסו לחישוב:")
    for coupon in all_non_one_time_coupons:
        print(
            f"קוד: {coupon.code}, ערך: {coupon.value}, שימוש עד כה: {coupon.used_value}, נשאר להוציא: {coupon.remaining_value}")

    # חישוב סך הקופונים
    total_remaining = sum(coupon.value - coupon.used_value for coupon in all_non_one_time_coupons)
    print(f"סה\"כ נשאר: {total_remaining:.2f} ש\"ח")

    # חישוב סך החיסכון
    total_savings = sum(
        coupon.used_value * (coupon.value - coupon.cost) / coupon.value
        for coupon in all_non_one_time_coupons if coupon.cost > 0
    )
    print(f"סה\"כ חיסכון: {total_savings:.2f} ש\"ח")

    # חישוב סך ערך הקופונים
    total_coupons_value = sum(coupon.value for coupon in all_non_one_time_coupons)
    print(f"סך ערך הקופונים: {total_coupons_value:.2f} ש\"ח")

    # חישוב אחוז החיסכון
    if total_coupons_value > 0:
        percentage_savings = (total_savings / total_coupons_value) * 100
    else:
        percentage_savings = 0
    print(f"אחוז החיסכון: {percentage_savings:.2f}%")

    # סינון קופונים חד פעמיים פעילים
    active_one_time_coupons = Coupon.query.filter(
        Coupon.status == 'פעיל',
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        Coupon.is_one_time  # קופונים חד פעמיים
    ).all()

    # סינון קופונים משומשים (שאינם פעילים)
    used_coupons = Coupon.query.filter(
        Coupon.status != 'פעיל',
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        ~Coupon.is_one_time  # קופונים שאינם חד פעמיים
    ).all()

    # סינון קופונים למכירה
    coupons_for_sale = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == True,
        ~Coupon.is_one_time  # קופונים שאינם חד פעמיים
    ).all()

    # עדכון סטטוס הקופונים
    for coupon in all_non_one_time_coupons + active_one_time_coupons + used_coupons + coupons_for_sale:
        update_coupon_status(coupon)
    db.session.commit()

    # חישוב סך הקופונים והחיסכון לאחר עדכון הסטטוס
    all_non_one_time_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.status == 'פעיל',
        Coupon.is_for_sale == False,
        ~Coupon.is_one_time,
        Coupon.value > Coupon.used_value,  # להחריג קופונים שנוצלו במלואם
        Coupon.exclude_saving != True  # סינון קופונים מסומנים כ-excluded
    ).all()

    # חישוב סך הקופונים
    total_remaining = sum(coupon.value - coupon.used_value for coupon in all_non_one_time_coupons)

    # חישוב סך החיסכון באופן יחסי לשימוש בפועל
    total_savings = sum(
        coupon.used_value * (coupon.value - coupon.cost) / coupon.value
        for coupon in all_non_one_time_coupons if coupon.cost > 0
    )

    # חישוב סך ערך הקופונים
    total_coupons_value = sum(coupon.value for coupon in all_non_one_time_coupons)

    # חישוב אחוז החיסכון
    if total_coupons_value > 0:
        percentage_savings = (total_savings / total_coupons_value) * 100
    else:
        percentage_savings = 0

    print(f"סה\"כ חיסכון: {total_savings:.2f} ש\"ח")
    print(f"סך ערך הקופונים: {total_coupons_value:.2f} ש\"ח")
    print(f"אחוז החיסכון: {percentage_savings:.2f}%")

    # שליפת הקופונים לפי קטגוריות
    active_coupons = Coupon.query.filter(
        Coupon.status == 'פעיל',
        Coupon.user_id == current_user.id,
        Coupon.is_for_sale == False,
        ~Coupon.is_one_time  # קופונים שאינם חד פעמיים
    ).order_by(Coupon.date_added.desc()).all()

    # שליפת כל החברות ויצירת מילון מיפוי
    companies = Company.query.all()
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}

    # שליפת כל הקופונים שאינם חד-פעמיים (כל הסטטוסים)
    all_non_one_time_coupons_all_status = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.exclude_saving != True  # סינון קופונים מסומנים כ-excluded
    ).all()

    # חישוב סך ההפרשים בין value ל-cost רק אם value גדול מ-cost (חיסכון חיובי)
    total_savings_all = sum(
        (coupon.value - coupon.cost) for coupon in all_non_one_time_coupons_all_status if coupon.value > coupon.cost
    )

    # סך כל הערך של הקופונים הלא חד-פעמיים
    total_coupons_value_all = sum(coupon.value for coupon in all_non_one_time_coupons_all_status)

    # חישוב אחוז החיסכון
    if total_coupons_value_all > 0:
        percentage_savings_all = (total_savings_all / total_coupons_value_all) * 100
    else:
        percentage_savings_all = 0

    return render_template(
        'index.html',
        total_value=total_remaining,
        total_savings=total_savings_all,
        total_coupons_value=total_coupons_value_all,
        percentage_savings=percentage_savings_all,
        active_coupons=active_coupons,
        active_one_time_coupons=active_one_time_coupons,
        used_coupons=used_coupons,
        coupons_for_sale=coupons_for_sale,
        form=form,
        company_logo_mapping=company_logo_mapping
    )

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

@profile_bp.route('/edit_profile')
@login_required
def edit_profile():
    return render_template('profile/edit_profile.html', form=form)

@profile_bp.route('/rate_user')
@login_required
def rate_user():
    return render_template('profile/rate_user.html', form=form)

@profile_bp.route('/user_profile/<int:user_id>', methods=['GET'])
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('profile/user_profile.html', user=user)


@profile_bp.route('/user_profile')
@login_required
def user_profile_default():
    return redirect(url_for('profile.user_profile', user_id=current_user.id))
