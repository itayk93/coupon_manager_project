import os
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Tag
from app.forms import TagManagementForm

admin_tags_bp = Blueprint('admin_tags_bp', __name__)

@admin_tags_bp.route('/admin/manage_tags', methods=['GET', 'POST'])
@login_required
def manage_tags():
    # בדיקה אם המשתמש הוא אדמין
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בעמוד זה.', 'danger')
        return redirect(url_for('index'))  # נניח שיש לך ראוט 'index'

    form = TagManagementForm()
    if form.validate_on_submit():
        # בדיקה אם התגית כבר קיימת
        tag_name = form.name.data.strip()
        existing_tag = Tag.query.filter_by(name=tag_name).first()
        if existing_tag:
            flash('תגית זו כבר קיימת.', 'warning')
            return redirect(url_for('admin_tags_bp.manage_tags'))

        # יצירת תגית חדשה
        new_tag = Tag(name=tag_name)

        db.session.add(new_tag)
        db.session.commit()

        flash('תגית חדשה נוצרה בהצלחה!', 'success')
        return redirect(url_for('admin_tags_bp.manage_tags'))

    # שליפת כל התגיות כדי להציג אותן ברשימה
    tags = Tag.query.order_by(Tag.id.asc()).all()
    return render_template('admin_manage_tags.html', form=form, tags=tags)
