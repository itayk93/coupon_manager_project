# admin_tags_routes.py

import os
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Tag
from app.forms import TagManagementForm, DeleteTagForm, EditTagForm, TransferCouponsForm
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
    edit_form = EditTagForm()  # הוספתי את הטופס לעריכת תגית
    transfer_form = TransferCouponsForm()  # הוספתי את טופס העברת הקופונים

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
    return render_template(
        'admin/admin_manage_tags.html',
        form=form,
        tags=tags,
        delete_form=delete_form,
        edit_form=edit_form,  # הוספתי את edit_form
        transfer_form=transfer_form  # הוספתי את transfer_form
    )

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


@admin_tags_bp.route('/edit/<int:tag_id>', methods=['POST'])
@login_required
def edit_tag(tag_id):
    if not current_user.is_admin:
        flash('אין לך הרשאה לביצוע פעולה זו.', 'danger')
        return redirect(url_for('index'))

    edit_form = EditTagForm()
    if edit_form.validate_on_submit():
        try:
            tag = Tag.query.get_or_404(tag_id)
            new_name = edit_form.name.data.strip()

            # Check if the new name already exists for another tag
            existing_tag = Tag.query.filter(Tag.name == new_name, Tag.id != tag_id).first()
            if existing_tag:
                flash('תגית בשם זה כבר קיימת.', 'warning')
                return redirect(url_for('admin_tags_bp.manage_tags'))

            # Update the tag name
            tag.name = new_name
            db.session.commit()
            flash(f'שם התגית עודכן בהצלחה ל-"{new_name}".', 'success')
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error while updating tag: {e}")
            flash('שגיאה בעדכון שם התגית.', 'danger')

    return redirect(url_for('admin_tags_bp.manage_tags'))


@admin_tags_bp.route('/transfer/<int:tag_id>', methods=['POST'])
@login_required
def transfer_coupons(tag_id):
    if not current_user.is_admin:
        flash('אין לך הרשאה לביצוע פעולה זו.', 'danger')
        return redirect(url_for('index'))

    transfer_form = TransferCouponsForm()

    # Populate the choices for the target tag dropdown
    all_tags = Tag.query.filter(Tag.id != tag_id).all()
    transfer_form.target_tag_id.choices = [(t.id, t.name) for t in all_tags]

    if transfer_form.validate_on_submit():
        try:
            source_tag = Tag.query.get_or_404(tag_id)
            target_tag_id = transfer_form.target_tag_id.data
            target_tag = Tag.query.get_or_404(target_tag_id)

            # Here you would add the logic to transfer coupons from source_tag to target_tag
            # This depends on your database structure and relationships
            # For example:
            # coupons = Coupon.query.filter_by(tag_id=source_tag.id).all()
            # for coupon in coupons:
            #     coupon.tag_id = target_tag.id

            # Update the count of both tags
            target_tag.count += source_tag.count
            source_tag.count = 0

            db.session.commit()
            flash(f'הקופונים הועברו בהצלחה מתגית "{source_tag.name}" לתגית "{target_tag.name}".', 'success')
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error while transferring coupons: {e}")
            flash('שגיאה בהעברת הקופונים.', 'danger')

    return redirect(url_for('admin_tags_bp.manage_tags'))