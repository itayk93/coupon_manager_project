# app/routes/auth_routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from itsdangerous import SignatureExpired, BadTimeSignature
from app.extensions import db
from app.models import User, UserConsent
from app.forms import LoginForm, RegisterForm
from app.helpers import generate_confirmation_token, confirm_token, send_email
from app.helpers import send_coupon_purchase_request_email, get_geo_location  # אם צריך
import logging
from flask import Blueprint, render_template, request, current_app, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy.sql import text
from datetime import datetime
from app.extensions import db
from app.helpers import get_geo_location, get_public_ip


auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)
import requests
from datetime import datetime
from flask import request, current_app
from flask_login import current_user

def log_user_activity(action, coupon_id=None):
    """
    פונקציה מרכזית לרישום activity log.
    """
    try:
        ip_address = get_public_ip()
        user_agent = request.headers.get('User-Agent', '')

        geo_data = get_geo_location(ip_address)

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
            "country_code": geo_data.get("countryCode"),
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

@auth_bp.route('/confirm/<token>')
def confirm_email(token):
    log_user_activity("confirm_email_attempt")

    try:
        email = confirm_token(token)
    except SignatureExpired:
        flash('קישור האישור פג תוקף.', 'error')
        log_user_activity("confirm_email_link_expired")
        return redirect(url_for('auth.login'))
    except BadTimeSignature:
        flash('קישור האישור אינו תקין.', 'error')
        log_user_activity("confirm_email_link_invalid")
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first_or_404()

    if user.is_confirmed:
        flash('החשבון כבר אושר. אנא התחבר.', 'success')
        log_user_activity("confirm_email_already_confirmed")
    else:
        user.is_confirmed = True
        user.confirmed_on = datetime.now()
        db.session.add(user)
        db.session.commit()
        flash('חשבון האימייל שלך אושר בהצלחה!', 'success')
        log_user_activity("confirm_email_success")

    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    log_user_activity("login_view")

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password, form.password.data):
            if not user.is_confirmed:
                flash('עליך לאשר את חשבונך לפני התחברות.', 'error')
                log_user_activity("login_unconfirmed_user")
                return redirect(url_for('auth.login'))
            login_user(user, remember=form.remember.data)
            log_user_activity("login_success")
            return redirect(url_for('profile.index'))
        else:
            flash('אימייל או סיסמה שגויים.', 'error')
            log_user_activity("login_failed_credentials")
    else:
        if request.method == 'POST':
            log_user_activity("login_form_validation_failed")

    return render_template('login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    log_user_activity("register_view")

    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('אימייל זה כבר רשום במערכת.', 'error')
            log_user_activity("register_email_already_exists")
            return redirect(url_for('auth.register'))

        new_user = User(
            email=email,
            password=generate_password_hash(form.password.data),
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            is_confirmed=False
        )
        try:
            db.session.add(new_user)
            db.session.commit()
            log_user_activity("register_user_created")
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת יצירת החשבון שלך.', 'error')
            logger.error(f"Error during user creation: {e}")
            log_user_activity("register_user_creation_failed")
            return redirect(url_for('auth.register'))

        token = generate_confirmation_token(new_user.email)
        confirm_url = url_for('auth.confirm_email', token=token, _external=True)
        html = render_template('emails/account_confirmation.html', user=new_user, confirmation_link=confirm_url)

        sender_email = 'itayk93@gmail.com'
        sender_name = 'MaCoupon'
        recipient_email = new_user.email
        recipient_name = new_user.first_name
        subject = 'אישור חשבון ב-MaCoupon'

        try:
            send_email(
                sender_email=sender_email,
                sender_name=sender_name,
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                subject=subject,
                html_content=html
            )
            flash('נשלח אליך מייל לאישור החשבון. אנא בדוק את תיבת הדואר שלך.', 'success')
            log_user_activity("register_confirmation_email_sent")
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            flash('אירעה שגיאה בשליחת המייל. נסה שוב מאוחר יותר.', 'error')
            log_user_activity("register_confirmation_email_failed")

        return redirect(url_for('auth.login'))
    else:
        if request.method == 'POST':
            log_user_activity("register_form_validation_failed")
            logger.warning(f"Form errors: {form.errors}")

    return render_template('register.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    log_user_activity("logout_attempt")

    logout_user()
    flash('התנתקת בהצלחה.', 'info')
    log_user_activity("logout_success")
    return redirect(url_for('auth.login'))


@auth_bp.route('/save_consent', methods=['POST'])
def save_consent():
    log_user_activity("save_consent_attempt")

    # קבלת הנתונים מהבקשה
    data = request.json
    consent = data.get('consent')

    if consent is None:
        return jsonify({"error": "Invalid data"}), 400

    # זיהוי משתמש לפי user_id (אם מחובר) או לפי כתובת IP (אם לא מחובר)
    user_id = current_user.id if current_user.is_authenticated else None
    ip_address = get_public_ip()

    # בדיקה אם כבר קיימת רשומת הסכמה
    if user_id:
        existing_consent = UserConsent.query.filter_by(user_id=user_id).first()
    else:
        existing_consent = UserConsent.query.filter_by(ip_address=ip_address).first()

    if existing_consent:
        # עדכון סטטוס העדפה
        existing_consent.consent_status = consent
        existing_consent.timestamp = datetime.utcnow()
    else:
        # יצירת רשומת הסכמה חדשה
        new_consent = UserConsent(
            user_id=user_id,
            ip_address=ip_address,
            consent_status=consent,
            timestamp=datetime.utcnow()
        )
        db.session.add(new_consent)

    db.session.commit()
    log_user_activity("save_consent_success")
    return jsonify({"message": "Consent saved successfully"}), 200

@auth_bp.route('/privacy-policy')
def privacy_policy():
    log_user_activity("view_privacy_policy")
    return render_template('privacy_policy.html')




def log_user_activity(action, coupon_id=None):
    """
    פונקציה מרכזית לרישום פעילות המשתמש.
    """
    try:
        ip_address = get_public_ip()
        user_agent = request.headers.get('User-Agent', '')

        geo_data = get_geo_location(ip_address)

        activity = {
            "user_id": current_user.id if current_user.is_authenticated else None,
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


@auth_bp.before_app_request
def check_location():
    """
    פונקציה לבדיקה לפני כל בקשה נכנסת.
    """
    # רישום הפעולה
    log_user_activity("page_access")

    # קבלת נתוני המיקום
    from app.helpers import get_geo_location, get_public_ip
    ip_address = get_public_ip()
    print(ip_address)
    geo_data = get_geo_location()
    country = geo_data.get("country")

    # אם המיקום אינו ישראל או איטליה, חסום את הגישה
    if country not in [None, "Israel", "Italy", "United States"]:
        log_user_activity("access_blocked_due_to_location")
        return render_template("access_denied.html", country=country), 403
