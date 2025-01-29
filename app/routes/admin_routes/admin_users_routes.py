# app/routes/admin_routes/admin_users_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User
from app.helpers import send_password_reset_email  # שימוש בפונקציה קיימת לשליחת מייל שחזור

admin_users_bp = Blueprint('admin_users_bp', __name__, url_prefix='/users')

@admin_users_bp.route('/', methods=['GET'])
@login_required
def manage_users():
    """
    עמוד המציג את כל המשתמשים. רק למשתמשים אדמינים.
    """
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בעמוד זה.', 'danger')
        return redirect(url_for('index'))

    users = User.query.order_by(User.id.asc()).all()
    return render_template('admin/admin_manage_users.html', users=users)


@admin_users_bp.route('/reset_password', methods=['POST'])
@login_required
def reset_user_password():
    """
    שליחת מייל שחזור סיסמה למשתמש.
    """
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('index'))

    user_id = request.form.get('user_id')
    user = User.query.get(user_id)
    if not user:
        flash('המשתמש לא נמצא.', 'danger')
        return redirect(url_for('admin_users_bp.manage_users'))

    # שימוש בפונקציה קיימת לשליחת מייל שחזור סיסמה
    send_password_reset_email(user)

    flash(f'נשלח מייל שחזור סיסמה לכתובת {user.email}.', 'success')
    return redirect(url_for('admin_users_bp.manage_users'))
