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

ip_address = None

def log_user_activity(ip_address,action, coupon_id=None):
    """
    פונקציה מרכזית לרישום activity log.
    """
    try:
        user_id = current_user.id if current_user.is_authenticated else None
        user_agent = request.headers.get('User-Agent', '')

        # 🔹 בדיקת ההסכמה האחרונה של המשתמש (רק לפי user_id) 🔹
        consent_check_query = """
            SELECT consent_status FROM user_consents 
            WHERE user_id = :user_id 
            ORDER BY timestamp DESC LIMIT 1
        """
        result = db.session.execute(
            text(consent_check_query),
            {"user_id": user_id}
        ).fetchone()
        
        if not result or not result[0]:  # אם אין הסכמה או שהיא false, לא נמשיך לרשום את הפעולה
            return

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

@auth_bp.route('/confirm/<token>')
def confirm_email(token):
    #log_user_activity(ip_address,"confirm_email_attempt")

    try:
        email = confirm_token(token)
    except SignatureExpired:
        flash('קישור האישור פג תוקף.', 'error')
        #log_user_activity(ip_address,"confirm_email_link_expired")
        return redirect(url_for('auth.login'))
    except BadTimeSignature:
        flash('קישור האישור אינו תקין.', 'error')
        #log_user_activity(ip_address,"confirm_email_link_invalid")
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first_or_404()

    if user.is_confirmed:
        flash('החשבון כבר אושר. אנא התחבר.', 'success')
        #log_user_activity(ip_address,"confirm_email_already_confirmed")
    else:
        user.is_confirmed = True
        user.confirmed_on = datetime.now()
        db.session.add(user)
        db.session.commit()
        flash('חשבון האימייל שלך אושר בהצלחה!', 'success')
        #log_user_activity(ip_address,"confirm_email_success")

    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    ip_address = request.remote_addr  # קבלת כתובת ה-IP של המשתמש
    #log_user_activity(ip_address, "login_view")

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if not user:
            flash("משתמש לא קיים.", "danger")
            #log_user_activity(ip_address, "login_nonexistent_user")
            return redirect(url_for('auth.login'))

        # בדיקה אם המשתמש נמחק לוגית
        if user.is_deleted:
            flash("משתמש זה כבר לא קיים במערכת.", "warning")
            #log_user_activity(ip_address, "login_deleted_user_attempt")
            return redirect(url_for('auth.login'))

        # בדיקה האם המשתמש אישר את חשבונו
        if not user.is_confirmed:
            flash('עליך לאשר את חשבונך לפני התחברות.', 'error')
            #log_user_activity(ip_address, "login_unconfirmed_user")
            return redirect(url_for('auth.login'))

        # בדיקה אם הסיסמה תואמת
        if check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            #log_user_activity(ip_address, "login_success")

            # 🔹 שדרוג חשוב: קישור ההסכמה למשתמש לאחר התחברות 🔹
            update_consent_after_login(user.id)

            return redirect(url_for('profile.index'))
        else:
            flash('אימייל או סיסמה שגויים.', 'error')
            #log_user_activity(ip_address, "login_failed_credentials")

    else:
        if request.method == 'POST':
            pass
            #log_user_activity(ip_address, "login_form_validation_failed")

    return render_template('login.html', form=form)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    #log_user_activity(ip_address,"register_view")

    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('אימייל זה כבר רשום במערכת.', 'error')
            #log_user_activity(ip_address,"register_email_already_exists")
            return redirect(url_for('auth.register'))

        # <-- הוספנו gender=form.gender.data -->
        new_user = User(
            email=email,
            password=generate_password_hash(form.password.data),
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            gender=form.gender.data, 
            is_confirmed=False
        )
        try:
            db.session.add(new_user)
            db.session.commit()
            #log_user_activity(ip_address,"register_user_created")
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת יצירת החשבון שלך.', 'error')
            logger.error(f"Error during user creation: {e}")
            #log_user_activity(ip_address,"register_user_creation_failed")
            return redirect(url_for('auth.register'))


        token = generate_confirmation_token(new_user.email)
        confirm_url = url_for('auth.confirm_email', token=token, _external=True)
        html = render_template('emails/account_confirmation.html', user=new_user, confirmation_link=confirm_url)

        sender_email = 'CouponMasterIL2@gmail.com'
        sender_name = 'Coupon Master'
        recipient_email = new_user.email
        recipient_name = new_user.first_name
        subject = 'אישור חשבון ב-Coupon Master'

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
            #log_user_activity(ip_address,"register_confirmation_email_sent")
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            flash('אירעה שגיאה בשליחת המייל. נסה שוב מאוחר יותר.', 'error')
            #log_user_activity(ip_address,"register_confirmation_email_failed")

        return redirect(url_for('auth.login'))
    else:
        if request.method == 'POST':
            #log_user_activity(ip_address,"register_form_validation_failed")
            logger.warning(f"Form errors: {form.errors}")

    return render_template('register.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    #log_user_activity(ip_address,"logout_attempt")

    logout_user()
    flash('התנתקת בהצלחה.', 'info')
    #log_user_activity(ip_address,"logout_success")
    return redirect(url_for('auth.login'))


from flask import request, jsonify, make_response
from datetime import datetime
from sqlalchemy import text

@auth_bp.route('/save_consent', methods=['POST'])
def save_consent():
    try:
        # שליפת כתובת IP
        ip_address = request.remote_addr
        #log_user_activity(ip_address, "save_consent_attempt")

        # קבלת הנתונים מהבקשה
        data = request.json
        consent = data.get('consent')

        if consent is None:
            return jsonify({"error": "Invalid data"}), 400

        # בדיקת משתמש מחובר
        user_id = current_user.id if current_user.is_authenticated else None

        # בדיקה אם יש הסכמה קיימת לפי user_id או כתובת IP
        if user_id:
            existing_consent = UserConsent.query.filter_by(user_id=user_id).first()
        else:
            existing_consent = UserConsent.query.filter_by(ip_address=ip_address).first()

        if existing_consent:
            # עדכון סטטוס ההסכמה והזמן
            existing_consent.consent_status = consent
            existing_consent.timestamp = datetime.utcnow()
            consent_id = existing_consent.consent_id  # שמירה של ה-ID
        else:
            # יצירת רשומת הסכמה חדשה
            new_consent = UserConsent(
                user_id=user_id,
                ip_address=ip_address,
                consent_status=consent,
                timestamp=datetime.utcnow()
            )
            db.session.add(new_consent)
            db.session.commit()  # שמירה לפני שליפה
            consent_id = new_consent.consent_id  # קבלת ה-ID שנשמר

        db.session.commit()
        #log_user_activity(ip_address, "save_consent_success")

        # יצירת תגובה עם עוגיה המכילה את consent_id
        response = make_response(jsonify({"message": "Consent saved successfully", "consent_id": consent_id}))
        response.set_cookie("consent_id", str(consent_id), max_age=365 * 24 * 60 * 60, path="/")

        return response
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

def update_consent_after_login(user_id):
    try:
        consent_id = request.cookies.get("consent_id")
        ip_address = request.remote_addr

        if consent_id:
            # עדכון ה-user_id בטבלת ההסכמות לפי העוגיה
            db.session.execute(
                text("""
                    UPDATE user_consents
                    SET user_id = :user_id
                    WHERE consent_id = :consent_id AND user_id IS NULL
                """),
                {"user_id": user_id, "consent_id": consent_id}
            )
        else:
            # אם אין עוגיה, ננסה לאתר לפי ה-IP האחרון
            db.session.execute(
                text("""
                    UPDATE user_consents
                    SET user_id = :user_id
                    WHERE ip_address = :ip_address AND user_id IS NULL
                """),
                {"user_id": user_id, "ip_address": ip_address}
            )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating consent after login: {e}")

@auth_bp.route('/privacy-policy')
def privacy_policy():
    #log_user_activity(ip_address,"view_privacy_policy")
    return render_template('privacy_policy.html')



@auth_bp.before_app_request
def check_location():
    """
    פונקציה לבדיקה לפני כל בקשה נכנסת.
    """
    from app.helpers import get_geo_location, get_public_ip

    # קבלת כתובת ה-IP
    ip_address = None

    # רישום הפעולה
    ##log_user_activity(ip_address, "page_access")

    # קבלת נתוני המיקום
    geo_data = get_geo_location(ip_address)
    country = geo_data.get("country")

    # אם המיקום אינו ישראל או איטליה, חסום את הגישה
    if country not in [None, "IL", "IT", "US"]:
        #log_user_activity(ip_address,"access_blocked_due_to_location")
        return render_template("access_denied.html", country=country), 403

# app/routes/auth_routes.py

from flask import render_template, request, flash, url_for, redirect
from app.forms import ForgotPasswordForm, ResetPasswordForm
from app.helpers import send_password_reset_email, confirm_token, generate_confirmation_token
from app.models import User
from werkzeug.security import generate_password_hash
from app.helpers import confirm_password_reset_token

@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            # שולח מייל שחזור סיסמה
            send_password_reset_email(user)
            flash('נשלח אליך מייל שחזור סיסמה אם המשתמש קיים במערכת.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash('האימייל שהוזן לא קיים במערכת.', 'error')
    return render_template('forgot_password.html', form=form)

@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = confirm_password_reset_token(token)  # <-- קריאה לפונקציה החדשה
    except SignatureExpired:
        flash('קישור שחזור הסיסמה פג תוקף.', 'error')
        return redirect(url_for('auth.login'))
    except BadTimeSignature:
        flash('קישור שחזור הסיסמה אינו תקין.', 'error')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first_or_404()

    form = ResetPasswordForm()
    if form.validate_on_submit():
        new_password = form.password.data
        user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('הסיסמה אופסה בהצלחה! אנא התחבר עם הסיסמה החדשה.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password_form.html', form=form, token=token)
