# app/routes/admin_tags_routes.py

import os
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Tag
from app.forms import TagManagementForm, DeleteTagForm
import logging

admin_tags_bp = Blueprint('admin_tags_bp', __name__, url_prefix='/admin/tags')

# הגדרת לוגר
logger = logging.getLogger(__name__)

@admin_tags_bp.route('/', methods=['GET', 'POST'])
@login_required
def manage_tags():
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בעמוד זה.', 'danger')
        return redirect(url_for('index'))

    form = TagManagementForm()
    delete_form = DeleteTagForm()

    if form.validate_on_submit() and 'submit' in request.form:
        tag_name = form.name.data.strip()
        existing_tag = Tag.query.filter_by(name=tag_name).first()
        if existing_tag:
            flash('תגית זו כבר קיימת.', 'warning')
            return redirect(url_for('admin_tags_bp.manage_tags'))

        # יצירת תגית חדשה עם ספירה התחלתית של 1
        new_tag = Tag(name=tag_name, count=1)
        db.session.add(new_tag)
        db.session.commit()
        flash('תגית חדשה נוצרה בהצלחה!', 'success')
        return redirect(url_for('admin_tags_bp.manage_tags'))

    tags = Tag.query.order_by(Tag.id.asc()).all()
    return render_template('admin/admin_manage_tags.html', form=form, tags=tags, delete_form=delete_form)


@admin_tags_bp.route('/admin/delete_tag/<int:tag_id>', methods=['POST'])
@login_required
def delete_tag(tag_id):
    if not current_user.is_admin:
        flash('אין לך הרשאה לביצוע פעולה זו.', 'danger')
        return redirect(url_for('index'))

    try:
        # שליפת התגית ומחיקתה
        tag = Tag.query.get_or_404(tag_id)
        db.session.delete(tag)
        db.session.commit()
        flash(f'תגית "{tag.name}" נמחקה בהצלחה.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Error while deleting tag: {e}")
        flash('שגיאה במחיקת התגית.', 'danger')

    return redirect(url_for('admin_tags_bp.manage_tags'))
