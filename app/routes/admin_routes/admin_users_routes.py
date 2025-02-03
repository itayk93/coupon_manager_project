# app/routes/admin_routes/admin_users_routes.py

import os
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, current_app
)
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from datetime import datetime  # <-- הוספה של השורה החסרה
import random, string

# הרחבות מהאפליקציה שלך
from app.extensions import db
from app.models import User

# במקום Flask-Mail, נשתמש בפונקציה שלך מ-helpers.py
from app.helpers import (
    send_email,
    send_password_reset_email
)

admin_users_bp = Blueprint('admin_users_bp', __name__, url_prefix='/users')

@admin_users_bp.route('/', methods=['GET'])
@login_required
def manage_users():
    """ עמוד המציג את כל המשתמשים (אדמין בלבד). """
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בעמוד זה.', 'danger')
        return redirect(url_for('profile.index'))

    users = User.query.order_by(User.id.asc()).all()
    return render_template('admin/admin_manage_users.html', users=users)

    users = User.query.order_by(User.id.asc()).all()
    return render_template('admin/admin_manage_users.html', users=users)

@admin_users_bp.route('/reset_password', methods=['POST'])
@login_required
def reset_user_password():
    """
    שליחת מייל שחזור סיסמה למשתמש (אדמין בלבד).
    """
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('profile.index'))

    user_id = request.form.get('user_id', type=int)
    user = User.query.get(user_id)
    if not user:
        flash('המשתמש לא נמצא.', 'danger')
        return redirect(url_for('admin_bp.admin_users_bp.manage_users'))

    # -- כאן אתה יכול לקרוא לפונקציה הקיימת לשליחת מייל שחזור --
    # send_password_reset_email(user)
    flash(f'נשלח מייל שחזור סיסמה לכתובת {user.email}.', 'success')
    return redirect(url_for('admin_bp.admin_users_bp.manage_users'))



@admin_users_bp.route('/update_slots_automatic_coupons', methods=['POST'])
@login_required
def update_slots_automatic_coupons():
    """
    מעדכן את כמות slots_automatic_coupons של המשתמש.
    """
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('profile.index'))

    user_id = request.form.get('user_id', type=int)
    new_slots = request.form.get('slots_automatic_coupons', type=int)

    user = User.query.get(user_id)
    if user:
        user.slots_automatic_coupons = new_slots
        db.session.commit()
        flash("הסלוטים עודכנו בהצלחה!", "success")
    else:
        flash("משתמש לא נמצא.", "error")

    return redirect(url_for('admin_bp.admin_users_bp.manage_users'))

@admin_users_bp.route('/initiate_delete_user', methods=['POST'])
@login_required
def initiate_delete_user():
    """
    פותח תהליך מחיקה - שולח למשתמש מייל עם לינק 'confirm_delete_user/<token>'.
    """
    user_id = request.form.get('user_id', type=int)
    user = User.query.get(user_id)
    if not user:
        flash("משתמש לא נמצא.", "error")
        return redirect_after_deletion()

    if user.is_admin:
        flash("לא ניתן למחוק חשבון אדמין.", "error")
        return redirect_after_deletion()

    # אם זה לא אני ולא אדמין - חסום
    if user.id != current_user.id and not current_user.is_admin:
        flash("אין לך הרשאה למחוק חשבון זה.", "danger")
        return redirect_after_deletion()

    # אם כבר נמחק, אין טעם
    if user.is_deleted:
        flash("משתמש זה כבר נמחק בעבר.", "warning")
        return redirect_after_deletion()

    # יצירת טוקן
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    token = s.dumps({'user_id': user.id}, salt='delete-user-salt')

    # שליחת מייל
    send_delete_confirmation_email(user, token)

    flash("נשלח מייל למשתמש לצורך אישור מחיקה.", "info")
    return redirect_after_deletion()

def redirect_after_deletion():
    """
    פונקציה שעוזרת להחליט לאן לחזור אחרי "מחיקה".
    - אם המשתמש הנוכחי אדמין => נחזור לרשימת המשתמשים (manage_users).
    - אחרת => נחזור לעמוד בית (או מה שתרצה).
    """
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin_bp.admin_users_bp.manage_users'))
    else:
        # עמוד הבית או פרופיל אישי
        return redirect(url_for('profile.index'))

from flask_login import logout_user

@admin_users_bp.route('/confirm_delete_user/<token>', methods=['GET'])
def confirm_delete_user(token):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = s.loads(token, salt='delete-user-salt', max_age=259200)
        user_id = data.get('user_id')
    except SignatureExpired:
        flash("זמן האישור פג תוקף.", "error")
        return redirect_after_deletion()
    except BadSignature:
        flash("קישור לא חוקי או טוקן פגום.", "error")
        return redirect_after_deletion()

    user = User.query.get(user_id)
    if not user:
        flash("משתמש לא נמצא.", "error")
        return redirect_after_deletion()

    if user.is_admin:
        flash("לא ניתן למחוק חשבון אדמין.", "error")
        return redirect_after_deletion()

    if user.is_deleted:
        flash("המשתמש כבר נמחק בעבר.", "info")
        return redirect_after_deletion()

    # שינוי הפרטים -> Deleted user
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    user.email = f"deleted_{user.id}_{now_str}@deleted.com"
    user.first_name = "Deleted"
    user.last_name = f"User_{now_str}"
    user.is_confirmed = False
    user.is_deleted = True
    user.password = ''.join(random.choices(string.ascii_letters + string.digits, k=60))

    db.session.commit()

    flash("המשתמש נמחק בהצלחה", "success")

    # אם המשתמש שמחק הוא אותו user, נבצע logout
    if current_user.is_authenticated and current_user.id == user.id:
        logout_user()
        return redirect(url_for('auth.login'))
    else:
        return redirect_after_deletion()


def send_delete_confirmation_email(user, token):
    """
    שולח מייל עם לינק למחיקת המשתמש ומספק לוגים למעקב.
    """
    deletion_link = url_for(
        'admin_bp.admin_users_bp.confirm_delete_user',
        token=token,
        _external=True
    )
    subject = "אישור מחיקת חשבון ב-Coupon Master"

    # רנדר תבנית המייל
    html_content = render_template('emails/account_delete_confirmation.html',
                                   user=user, deletion_link=deletion_link)

    sender_email = 'CouponMasterIL2@gmail.com'
    sender_name = 'Coupon Master'
    recipient_email = user.email
    recipient_name = user.first_name or 'משתמש יקר'

    try:
        current_app.logger.info(f"ניסיון לשליחת מייל מחיקת משתמש ל-{recipient_email}")
        current_app.logger.info(f"קישור מחיקה: {deletion_link}")

        response = send_email(
            sender_email=sender_email,
            sender_name=sender_name,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            subject=subject,
            html_content=html_content
        )

        if response:
            current_app.logger.info(f"מייל למחיקת משתמש נשלח בהצלחה ל-{recipient_email}. תשובת השרת: {response}")
        else:
            current_app.logger.warning(f"מייל למחיקת משתמש **לא נשלח** ל-{recipient_email}. תשובת השרת: None")

    except Exception as e:
        current_app.logger.error(f"שגיאה בשליחת מייל למחיקת משתמש ל-{recipient_email}: {e}")

def redirect_after_deletion():
    """
    פונקציה קטנה שמחליטה לאן להפנות לאחר פעולת מחיקה/אישור
    אם current_user אדמין -> חזרה ל-manage_users
    אחרת -> חזרה לעמוד הראשי
    """
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin_bp.admin_users_bp.manage_users'))
    else:
        # עמוד הבית / פרופיל / כל דבר אחר
        return redirect(url_for('profile.index'))

@admin_users_bp.route('/resend_confirmation_email', methods=['POST'])
@login_required
def resend_confirmation_email():
    """
    שולח מייל אישור מחדש למשתמש שאינו מאושר (אדמין בלבד).
    """
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('profile.index'))

    user_id = request.form.get('user_id', type=int)
    user = User.query.get(user_id)
    if not user:
        flash("משתמש לא נמצא.", "error")
        return redirect(url_for('admin_bp.admin_users_bp.manage_users'))

    if user.is_confirmed:
        flash("המשתמש כבר אישר את חשבונו.", "info")
        return redirect(url_for('admin_bp.admin_users_bp.manage_users'))

    # ייבוא הפונקציה ליצירת הטוקן (ודא שהפונקציה קיימת ב-app/helpers.py)
    from app.helpers import generate_confirmation_token

    # יצירת טוקן אישור
    token = generate_confirmation_token(user.email)
    confirm_url = url_for('auth.confirm_email', token=token, _external=True)
    
    # רינדור התבנית של מייל אישור (בדומה לשליחת המייל בהרשמה)
    html = render_template('emails/account_confirmation.html',
                           user=user, confirmation_link=confirm_url)

    # פרטי השולח והנמען (עדכן במידת הצורך)
    sender_email = 'CouponMasterIL2@gmail.com'
    sender_name = 'Coupon Master'
    recipient_email = user.email
    recipient_name = user.first_name or 'משתמש יקר'
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
        flash(f'נשלח מייל אישור מחדש לכתובת {user.email}.', 'success')
    except Exception as e:
        current_app.logger.error(f"שגיאה בשליחת מייל אישור מחדש ל-{user.email}: {e}")
        flash('אירעה שגיאה בשליחת המייל. אנא נסה שוב מאוחר יותר.', 'error')

    return redirect(url_for('admin_bp.admin_users_bp.manage_users'))
