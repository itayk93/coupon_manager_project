# app/routes/auth_routes.py

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
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from urllib.parse import urlparse
from datetime import datetime
from itsdangerous import SignatureExpired, BadTimeSignature
from app.extensions import db
from app.models import User, UserConsent, AdminSettings
from app.forms import LoginForm, RegisterForm
from app.helpers import generate_confirmation_token, confirm_token, send_email
from app.helpers import send_coupon_purchase_request_email, get_geo_location  # אם צריך
import logging
from flask import (
    Blueprint,
    render_template,
    request,
    current_app,
    redirect,
    url_for,
    flash,
)
from flask_login import current_user
from sqlalchemy.sql import text
from datetime import datetime
from app.extensions import db
from app.helpers import get_geo_location, get_public_ip

from app.activity_logging import log_activity
from app.registration_guard import (
    check_registration_rate_limits,
    get_client_ip,
    is_honeypot_triggered,
    is_public_registration_enabled,
    is_register_submission_too_fast,
    is_registration_payload_suspicious,
    mark_register_form_rendered,
)


auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)
import requests
from datetime import datetime
from flask import request, current_app
from flask_login import current_user

from flask_dance.contrib.google import google
from flask import session
from app.extensions import google_bp
from app.extensions import cache

_cache_backend_warning_logged = False


def _warn_cache_backend_unavailable(operation, exc):
    global _cache_backend_warning_logged
    if not _cache_backend_warning_logged:
        current_app.logger.warning(
            "Cache backend unavailable during %s; login rate limiting falls back to no-op: %s",
            operation,
            exc,
        )
        _cache_backend_warning_logged = True


def _cache_get_safe(key):
    try:
        return cache.get(key)
    except Exception as exc:
        _warn_cache_backend_unavailable(f"cache.get({key})", exc)
        return None


def _cache_set_safe(key, value, timeout=None):
    try:
        cache.set(key, value, timeout=timeout)
    except Exception as exc:
        _warn_cache_backend_unavailable(f"cache.set({key})", exc)


def _cache_delete_safe(key):
    try:
        cache.delete(key)
    except Exception as exc:
        _warn_cache_backend_unavailable(f"cache.delete({key})", exc)


def _send_confirmation_email(user):
    """Send the account confirmation email for a user."""
    token = generate_confirmation_token(user.email)
    confirm_url = request.host_url.rstrip("/") + url_for(
        "auth.confirm_email", token=token
    )
    html = render_template(
        "emails/account_confirmation.html",
        user=user,
        confirmation_link=confirm_url,
    )

    send_email(
        sender_email="noreply@couponmasteril.com",
        sender_name="Coupon Master",
        recipient_email=user.email,
        recipient_name=user.first_name,
        subject="אישור חשבון ב-Coupon Master",
        html_content=html,
    )


@auth_bp.route("/login/google")
def login_google():
    flash("התחברות באמצעות Google כרגע בטיפול. אפשר להתחבר עם אימייל וסיסמה.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register/google")
def register_google():
    flash("הרשמה באמצעות Google כרגע בטיפול. אפשר להירשם עם אימייל וסיסמה.", "info")
    return redirect(url_for("auth.register"))  # ניתן להוסיף לוגיקה לרישום נפרד אם צריך


@auth_bp.route("/login/google/authorized")  # שונה מ-callback ל-authorized
def google_callback():    
    if not google.authorized:
        print("Google not authorized")
        flash("ההתחברות נכשלה!", "danger")
        return redirect(url_for("auth.login"))

    print("Getting user info from Google...")
    try:
        # קבלת נתוני המשתמש מגוגל
        resp = google.get("/oauth2/v1/userinfo")
        print(f"Response status: {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"Error response: {resp.text}")
            flash("נכשל בשליפת הנתונים מגוגל.", "danger")
            return redirect(url_for("auth.login"))

        user_info = resp.json()
        print(f"User info: {user_info}")
        
        google_id = user_info.get("id")
        email = user_info.get("email")
        first_name = user_info.get("given_name", "")
        last_name = user_info.get("family_name", "")


        # חיפוש המשתמש לפי אימייל
        user = User.query.filter_by(email=email).first()
        print(f"Existing user found: {user is not None}")

        if not user:
            # יצירת משתמש חדש
            default_whatsapp_banner = AdminSettings.get_setting("default_whatsapp_banner_for_new_users", True)
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                google_id=google_id,
                is_confirmed=True,
                show_whatsapp_banner=default_whatsapp_banner,
            )
            db.session.add(user)
            db.session.commit()
        else:
            # אם המשתמש קיים ואין לו Google ID, נוסיף אותו
            if not user.google_id:
                user.google_id = google_id
                db.session.commit()

        # התחברות למערכת
        login_user(user)
        log_activity(action="login_success", user_id=user.id)
        flash(f"ברוך הבא, {user.first_name}!", "success")
        
        # 🔹 בדיקה אם יש בקשות עומדות לביטול הרשמה או עדכון העדפות בסשן 🔹
        if 'unsubscribe_user_id' in session and 'unsubscribe_token' in session:
            if user.id == session['unsubscribe_user_id']:
                return redirect(url_for("profile.complete_unsubscribe"))
            else:
                # אם המשתמש שהתחבר שונה מהמשתמש שביקש לבטל הרשמה
                session.pop('unsubscribe_user_id', None)
                session.pop('unsubscribe_token', None)
                flash("לא ניתן לבטל הרשמה עבור משתמש אחר.", "error")
        
        if 'preferences_user_id' in session and 'preferences_token' in session:
            if user.id == session['preferences_user_id']:
                return redirect(url_for("profile.complete_preferences"))
            else:
                # אם המשתמש שהתחבר שונה מהמשתמש שביקש לעדכן העדפות
                session.pop('preferences_user_id', None)
                session.pop('preferences_token', None)
                flash("לא ניתן לעדכן העדפות עבור משתמש אחר.", "error")
        
        return redirect(url_for("profile.index"))
        
    except Exception as e:
        print(f"Error in Google callback: {e}")
        current_app.logger.error(f"Google OAuth error: {e}")
        flash("שגיאה בהתחברות עם Google. נסה שוב.", "danger")
        return redirect(url_for("auth.login"))

ip_address = None


def log_user_activity(ip_address, action, coupon_id=None):
    """
    פונקציה מרכזית לרישום activity log.
    """
    try:
        user_id = current_user.id if current_user.is_authenticated else None
        user_agent = request.headers.get("User-Agent", "")

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


@auth_bp.route("/confirm/<token>")
def confirm_email(token):
    # log_user_activity(ip_address,"confirm_email_attempt")

    try:
        email = confirm_token(token)
    except SignatureExpired:
        flash("קישור האישור פג תוקף.", "error")
        # log_user_activity(ip_address,"confirm_email_link_expired")
        return redirect(url_for("auth.login"))
    except BadTimeSignature:
        flash("קישור האישור אינו תקין.", "error")
        # log_user_activity(ip_address,"confirm_email_link_invalid")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(email=email).first_or_404()

    if user.is_confirmed:
        flash("החשבון כבר אושר. אנא התחבר.", "success")
        # log_user_activity(ip_address,"confirm_email_already_confirmed")
    else:
        user.is_confirmed = True
        user.confirmed_on = datetime.now()
        db.session.add(user)
        db.session.commit()
        flash("חשבון האימייל שלך אושר בהצלחה!", "success")
        # log_user_activity(ip_address,"confirm_email_success")

    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    ip_address = request.remote_addr  # קבלת כתובת ה-IP של המשתמש
    # log_user_activity(ip_address, "login_view")
    current_app.logger.info("Login route entered from ip=%s", ip_address)
    next_url = request.args.get("next", "").strip()
    if request.method == "POST":
        next_url = (request.form.get("next") or next_url).strip()

    def _is_safe_next(target):
        if not target:
            return False
        parsed = urlparse(target)
        if parsed.scheme or parsed.netloc:
            return False
        if not target.startswith("/"):
            return False
        if target.startswith("//"):
            return False
        return True

    def _login_attempt_keys(email_value):
        safe_email = (email_value or "").strip().lower() or "unknown"
        safe_ip = (ip_address or "unknown").replace(":", "_")
        return (
            f"login_attempts:ip:{safe_ip}",
            f"login_attempts:email:{safe_email}",
            f"login_lock:ip:{safe_ip}",
            f"login_lock:email:{safe_email}",
        )

    def _apply_login_attempt(email_value):
        attempts_ip_key, attempts_email_key, lock_ip_key, lock_email_key = _login_attempt_keys(
            email_value
        )
        max_attempts = max(1, int(current_app.config.get("LOGIN_MAX_ATTEMPTS", 6)))
        window_seconds = max(60, int(current_app.config.get("LOGIN_WINDOW_SECONDS", 600)))
        lock_seconds = max(60, int(current_app.config.get("LOGIN_LOCK_SECONDS", 900)))

        ip_attempts = int(_cache_get_safe(attempts_ip_key) or 0) + 1
        email_attempts = int(_cache_get_safe(attempts_email_key) or 0) + 1
        _cache_set_safe(attempts_ip_key, ip_attempts, timeout=window_seconds)
        _cache_set_safe(attempts_email_key, email_attempts, timeout=window_seconds)

        if ip_attempts >= max_attempts:
            _cache_set_safe(lock_ip_key, "1", timeout=lock_seconds)
        if email_attempts >= max_attempts:
            _cache_set_safe(lock_email_key, "1", timeout=lock_seconds)

    def _is_login_locked(email_value):
        _, _, lock_ip_key, lock_email_key = _login_attempt_keys(email_value)
        return bool(_cache_get_safe(lock_ip_key) or _cache_get_safe(lock_email_key))

    def _clear_login_attempts(email_value):
        attempts_ip_key, attempts_email_key, lock_ip_key, lock_email_key = _login_attempt_keys(
            email_value
        )
        for key in (attempts_ip_key, attempts_email_key, lock_ip_key, lock_email_key):
            _cache_delete_safe(key)

    form = LoginForm()
    try:
        if form.validate_on_submit():
            email = form.email.data.strip().lower()

            if _is_login_locked(email):
                flash("יותר מדי ניסיונות התחברות. נסה שוב מאוחר יותר.", "error")
                return redirect(url_for("auth.login"))

            user = User.query.filter_by(email=email).first()

            if not user:
                flash("משתמש לא קיים.", "danger")
                _apply_login_attempt(email)
                # log_user_activity(ip_address, "login_nonexistent_user")
                return redirect(url_for("auth.login"))

            # בדיקה אם המשתמש נמחק לוגית
            if user.is_deleted:
                flash("משתמש זה כבר לא קיים במערכת.", "warning")
                # log_user_activity(ip_address, "login_deleted_user_attempt")
                return redirect(url_for("auth.login"))

            # בדיקה האם המשתמש אישר את חשבונו
            if not user.is_confirmed:
                flash("עליך לאשר את חשבונך לפני התחברות.", "error")
                # log_user_activity(ip_address, "login_unconfirmed_user")
                return redirect(url_for("auth.login"))

            # בדיקה אם הסיסמה תואמת
            if not user.password:
                flash("לחשבון הזה אין סיסמה מקומית. נסה להתחבר עם Google.", "error")
                return redirect(url_for("auth.login"))

            try:
                password_matches = check_password_hash(user.password, form.password.data)
            except Exception as exc:
                current_app.logger.error(
                    "Password verification failed for user_id=%s email=%s: %s",
                    user.id,
                    email,
                    exc,
                )
                flash("אירעה שגיאה בבדיקת הסיסמה. נסה שוב.", "danger")
                return redirect(url_for("auth.login"))

            if password_matches:
                _clear_login_attempts(email)
                login_user(user, remember=form.remember.data)
                log_activity(action="login_success", user_id=user.id)
                # log_user_activity(ip_address, "login_success")

                # 🔹 שדרוג חשוב: קישור ההסכמה למשתמש לאחר התחברות 🔹
                update_consent_after_login(user.id)

                # 🔹 בדיקה אם יש בקשות עומדות לביטול הרשמה או עדכון העדפות בסשן 🔹
                if 'unsubscribe_user_id' in session and 'unsubscribe_token' in session:
                    if user.id == session['unsubscribe_user_id']:
                        return redirect(url_for("profile.complete_unsubscribe"))
                    else:
                        # אם המשתמש שהתחבר שונה מהמשתמש שביקש לבטל הרשמה
                        session.pop('unsubscribe_user_id', None)
                        session.pop('unsubscribe_token', None)
                        flash("לא ניתן לבטל הרשמה עבור משתמש אחר.", "error")
                
                if 'preferences_user_id' in session and 'preferences_token' in session:
                    if user.id == session['preferences_user_id']:
                        return redirect(url_for("profile.complete_preferences"))
                    else:
                        # אם המשתמש שהתחבר שונה מהמשתמש שביקש לעדכן העדפות
                        session.pop('preferences_user_id', None)
                        session.pop('preferences_token', None)
                        flash("לא ניתן לעדכן העדפות עבור משתמש אחר.", "error")

                if _is_safe_next(next_url):
                    return redirect(next_url)
                return redirect(url_for("profile.index"))
            else:
                flash("אימייל או סיסמה שגויים.", "error")
                _apply_login_attempt(email)
                # log_user_activity(ip_address, "login_failed_credentials")

        else:
            if request.method == "POST":
                pass
                # log_user_activity(ip_address, "login_form_validation_failed")
    except Exception as exc:
        current_app.logger.error(
            "Unexpected error in login route (ip=%s): %s",
            ip_address,
            exc,
            exc_info=True,
        )
        flash("אירעה שגיאה בהתחברות. נסה שוב מאוחר יותר.", "danger")
        return redirect(url_for("auth.login"))

    return render_template("login.html", form=form, next=next_url if _is_safe_next(next_url) else "")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    # log_user_activity(ip_address,"register_view")

    form = RegisterForm()
    ip_address = get_client_ip()

    if not is_public_registration_enabled():
        if request.method == "POST":
            logger.warning(
                "Blocked registration: public registration disabled. ip=%s",
                ip_address,
            )
        flash("ההרשמה מושבתת זמנית. נסה שוב מאוחר יותר.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":

        if is_honeypot_triggered(form.website.data):
            logger.warning(
                "Blocked registration by honeypot. ip=%s email=%s",
                ip_address,
                (form.email.data or "").strip().lower(),
            )
            flash("לא ניתן להשלים הרשמה כרגע.", "error")
            return redirect(url_for("auth.register"))

        rate_limited, rate_limit_message = check_registration_rate_limits(
            ip_address=ip_address,
            email=form.email.data,
        )
        if rate_limited:
            logger.warning(
                "Blocked registration by rate limit. ip=%s email=%s",
                ip_address,
                (form.email.data or "").strip().lower(),
            )
            flash(rate_limit_message, "error")
            return redirect(url_for("auth.register"))

        if is_register_submission_too_fast():
            logger.warning(
                "Blocked registration: form submitted too fast. ip=%s email=%s",
                ip_address,
                (form.email.data or "").strip().lower(),
            )
            flash("זוהתה הרשמה אוטומטית. אנא נסה שוב בעוד כמה שניות.", "error")
            return redirect(url_for("auth.register"))

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        first_name = form.first_name.data.strip()
        last_name = form.last_name.data.strip()

        suspicious_payload, suspicious_reason = is_registration_payload_suspicious(
            first_name=first_name,
            last_name=last_name,
            email=email,
        )
        if suspicious_payload:
            logger.warning(
                "Blocked suspicious registration payload. ip=%s email=%s reason=%s",
                ip_address,
                email,
                suspicious_reason,
            )
            flash("לא ניתן להשלים הרשמה כרגע. בדוק את הפרטים ונסה שוב.", "error")
            return redirect(url_for("auth.register"))

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            if existing_user.is_confirmed:
                flash("אימייל זה כבר רשום ומאושר במערכת. אפשר להתחבר.", "error")
            else:
                try:
                    _send_confirmation_email(existing_user)
                    flash(
                        "החשבון כבר קיים אבל עדיין לא אושר. שלחנו שוב מייל אישור.",
                        "info",
                    )
                except Exception as e:
                    logger.error(
                        "Error resending confirmation email for existing user %s: %s",
                        email,
                        e,
                    )
                    flash(
                        "החשבון כבר קיים אבל עדיין לא אושר. לא הצלחנו לשלוח מייל אישור מחדש.",
                        "error",
                    )
            # log_user_activity(ip_address,"register_email_already_exists")
            return redirect(url_for("auth.register"))

        # <-- הוספנו gender=form.gender.data -->
        default_whatsapp_banner = AdminSettings.get_setting("default_whatsapp_banner_for_new_users", True)
        new_user = User(
            email=email,
            password=generate_password_hash(form.password.data),
            first_name=first_name,
            last_name=last_name,
            gender=form.gender.data,
            is_confirmed=False,
            show_whatsapp_banner=default_whatsapp_banner,
        )
        try:
            db.session.add(new_user)
            db.session.commit()
            log_activity(action="register_success", user_id=new_user.id)
            # log_user_activity(ip_address,"register_user_created")
        except Exception as e:
            db.session.rollback()
            flash("אירעה שגיאה בעת יצירת החשבון שלך.", "error")
            logger.error(f"Error during user creation: {e}")
            # log_user_activity(ip_address,"register_user_creation_failed")
            return redirect(url_for("auth.register"))

        try:
            _send_confirmation_email(new_user)
            flash(
                "נשלח אליך מייל לאישור החשבון. אנא בדוק את תיבת הדואר שלך.", "success"
            )
            # log_user_activity(ip_address,"register_confirmation_email_sent")
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            flash("אירעה שגיאה בשליחת המייל. נסה שוב מאוחר יותר.", "error")
            # log_user_activity(ip_address,"register_confirmation_email_failed")

        return redirect(url_for("auth.login"))
    else:
        if request.method == "POST":
            # log_user_activity(ip_address,"register_form_validation_failed")
            logger.warning(f"Form errors: {form.errors}")

    mark_register_form_rendered()
    return render_template("register.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    # log_user_activity(ip_address,"logout_attempt")

    logout_user()
    flash("התנתקת בהצלחה.", "info")
    # log_user_activity(ip_address,"logout_success")
    return redirect(url_for("auth.login"))


from flask import request, jsonify, make_response
from datetime import datetime
from sqlalchemy import text


@auth_bp.route("/save_consent", methods=["POST"])
def save_consent():
    try:
        # שליפת כתובת IP
        ip_address = request.remote_addr
        # log_user_activity(ip_address, "save_consent_attempt")

        # קבלת הנתונים מהבקשה
        data = request.json
        consent = data.get("consent")

        if consent is None:
            return jsonify({"error": "Invalid data"}), 400

        # בדיקת משתמש מחובר
        user_id = current_user.id if current_user.is_authenticated else None

        # בדיקה אם יש הסכמה קיימת לפי user_id או כתובת IP
        if user_id:
            existing_consent = UserConsent.query.filter_by(user_id=user_id).first()
        else:
            existing_consent = UserConsent.query.filter_by(
                ip_address=ip_address
            ).first()

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
                timestamp=datetime.utcnow(),
            )
            db.session.add(new_consent)
            db.session.commit()  # שמירה לפני שליפה
            consent_id = new_consent.consent_id  # קבלת ה-ID שנשמר

        db.session.commit()
        # log_user_activity(ip_address, "save_consent_success")

        # יצירת תגובה עם עוגיה המכילה את consent_id
        response = make_response(
            jsonify({"message": "Consent saved successfully", "consent_id": consent_id})
        )
        response.set_cookie(
            "consent_id",
            str(consent_id),
            max_age=365 * 24 * 60 * 60,
            path="/",
            secure=current_app.config.get("SESSION_COOKIE_SECURE", True),
            httponly=True,
            samesite=current_app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
        )

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
                text(
                    """
                    UPDATE user_consents
                    SET user_id = :user_id
                    WHERE consent_id = :consent_id AND user_id IS NULL
                """
                ),
                {"user_id": user_id, "consent_id": consent_id},
            )
        else:
            # אם אין עוגיה, ננסה לאתר לפי ה-IP האחרון
            db.session.execute(
                text(
                    """
                    UPDATE user_consents
                    SET user_id = :user_id
                    WHERE ip_address = :ip_address AND user_id IS NULL
                """
                ),
                {"user_id": user_id, "ip_address": ip_address},
            )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating consent after login: {e}")


@auth_bp.route("/privacy-policy")
def privacy_policy():
    # log_user_activity(ip_address,"view_privacy_policy")
    return render_template("privacy_policy.html")


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
        # log_user_activity(ip_address,"access_blocked_due_to_location")
        return render_template("access_denied.html", country=country), 403


# app/routes/auth_routes.py

from flask import render_template, request, flash, url_for, redirect
from app.forms import ForgotPasswordForm, ResetPasswordForm
from app.helpers import (
    send_password_reset_email,
    confirm_token,
    generate_confirmation_token,
)
from app.models import User
from werkzeug.security import generate_password_hash
from app.helpers import confirm_password_reset_token


@auth_bp.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            # שולח מייל שחזור סיסמה
            send_password_reset_email(user)
            flash("נשלח אליך מייל שחזור סיסמה אם המשתמש קיים במערכת.", "success")
            return redirect(url_for("auth.login"))
        else:
            flash("האימייל שהוזן לא קיים במערכת.", "error")
    return render_template("forgot_password.html", form=form)


@auth_bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = confirm_password_reset_token(token)  # <-- קריאה לפונקציה החדשה
    except SignatureExpired:
        flash("קישור שחזור הסיסמה פג תוקף.", "error")
        return redirect(url_for("auth.login"))
    except BadTimeSignature:
        flash("קישור שחזור הסיסמה אינו תקין.", "error")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(email=email).first_or_404()

    form = ResetPasswordForm()
    if form.validate_on_submit():
        new_password = form.password.data
        user.password = generate_password_hash(new_password)
        db.session.commit()
        flash("הסיסמה אופסה בהצלחה! אנא התחבר עם הסיסמה החדשה.", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password_form.html", form=form, token=token)
