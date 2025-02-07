# app/routes/admin_routes/admin_messages_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import AdminMessage, User
from app.extensions import db
from app.forms import AdminMessageForm

admin_messages_bp = Blueprint('admin_messages_bp', __name__, url_prefix='/admin/messages')

@admin_messages_bp.route('/', methods=['GET', 'POST'])
@login_required
def manage_admin_messages():
    """
    עמוד שמאפשר למנהל:
    1) להוסיף הודעה חדשה (עם קישור אופציונלי).
    2) לצפות בכל ההודעות.
    3) לסמן הודעות למחיקה מרובה או למחוק הודעה בודדת.
    """
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בעמוד זה.', 'danger')
        return redirect(url_for('profile.index'))

    form = AdminMessageForm()

    if request.method == 'POST' and form.validate_on_submit():
        message_text = form.message_text.data
        link_url = form.link_url.data or None
        link_text = form.link_text.data or None

        # יצירת רשומה חדשה
        new_message = AdminMessage(
            message_text=message_text,
            link_url=link_url,
            link_text=link_text
        )
        db.session.add(new_message)
        db.session.commit()
        flash('הודעת המנהל נוספה בהצלחה.', 'success')

        # מאתחל את ה-dismissed_message_id של כל המשתמשים (שיראו את ההודעה החדשה)
        User.query.update({User.dismissed_message_id: None})
        db.session.commit()

        return redirect(url_for('admin_messages_bp.manage_admin_messages'))

    # שליפת כל ההודעות
    messages = AdminMessage.query.order_by(AdminMessage.created_at.desc()).all()
    return render_template('admin/admin_manage_messages.html', form=form, messages=messages)

@admin_messages_bp.route('/delete/<int:message_id>', methods=['POST'])
@login_required
def delete_admin_message(message_id):
    """
    מחיקת הודעה בודדת.
    """
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('admin_messages_bp.manage_admin_messages'))

    message = AdminMessage.query.get_or_404(message_id)
    db.session.delete(message)
    db.session.commit()

    flash('הודעת המנהל נמחקה בהצלחה.', 'success')
    return redirect(url_for('admin_messages_bp.manage_admin_messages'))

@admin_messages_bp.route('/delete_multiple', methods=['POST'])
@login_required
def delete_multiple_admin_messages():
    """
    מחיקת מספר הודעות בבת אחת (Bulk).
    """
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('admin_messages_bp.manage_admin_messages'))

    message_ids = request.form.getlist('message_ids')
    if not message_ids:
        flash('לא נבחרו הודעות למחיקה.', 'warning')
        return redirect(url_for('admin_messages_bp.manage_admin_messages'))

    AdminMessage.query.filter(AdminMessage.id.in_(message_ids)).delete(synchronize_session=False)
    db.session.commit()

    flash(f'נמחקו {len(message_ids)} הודעות מנהל בהצלחה.', 'success')
    return redirect(url_for('admin_messages_bp.manage_admin_messages'))

@admin_messages_bp.route('/dismiss_admin_message', methods=['POST'])
@login_required
def dismiss_admin_message():
    """
    משתמש מסמן שהודעת המנהל האחרונה נראתה => עדכון dismissed_message_id בבסיס הנתונים.
    """
    csrf_token = request.form.get("csrf_token")
    if not csrf_token:
        flash("שגיאת אבטחה: CSRF Token חסר!", "danger")
        return redirect(url_for("index"))

    latest_message = AdminMessage.query.order_by(AdminMessage.id.desc()).first()
    if latest_message:
        current_user.dismissed_message_id = latest_message.id
        db.session.commit()
        flash("ההודעה סומנה כנראתה.", "success")

    return redirect(request.referrer or url_for('index'))
