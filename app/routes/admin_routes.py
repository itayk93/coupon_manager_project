# admin_routes.py
from flask import Blueprint, redirect, url_for, flash, request, render_template
from flask_login import login_required, current_user
from app.models import (
    Tag, Coupon, CouponTransaction, FeatureAccess, User
)
from app.extensions import db
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField, HiddenField
from wtforms.validators import DataRequired
from app.helpers import get_coupon_data, send_password_reset_email
import logging

logger = logging.getLogger(__name__)

# ===============================
# Blueprint לניהול תגיות (admin_tags_bp)
# ===============================
admin_tags_bp = Blueprint('admin_tags_bp', __name__, url_prefix='/admin/tags')

# --- טפסים לניהול תגיות ---
class EditTagForm(FlaskForm):
    name = StringField('שם חדש לתגית', validators=[DataRequired()])
    submit = SubmitField('עדכן')

class TransferCouponsForm(FlaskForm):
    source_tag_id = HiddenField('מזהה תגית מקור')
    target_tag_id = SelectField('העבר קופונים לתגית', coerce=int)
    submit = SubmitField('העבר קופונים')

# רוט לעדכון שם תגית
@admin_tags_bp.route('/edit_tag/<int:tag_id>', methods=['GET', 'POST'])
@login_required
def edit_tag(tag_id):
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('auth.login'))
    
    tag = Tag.query.get_or_404(tag_id)
    form = EditTagForm(obj=tag)
    
    if form.validate_on_submit():
        old_name = tag.name
        tag.name = form.name.data
        db.session.commit()
        flash(f'שם התגית עודכן בהצלחה מ-"{old_name}" ל-"{tag.name}".', 'success')
        return redirect(url_for('admin_tags_bp.manage_tags'))
    
    return render_template('edit_tag.html', form=form, tag=tag)

# רוט להעברת קופונים מתגית אחת לאחרת
@admin_tags_bp.route('/transfer_coupons/<int:source_tag_id>', methods=['GET', 'POST'])
@login_required
def transfer_coupons(source_tag_id):
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('auth.login'))
    
    source_tag = Tag.query.get_or_404(source_tag_id)
    
    # רשימת תגיות נוספות (לא כולל תגית המקור)
    other_tags = [(tag.id, tag.name) for tag in Tag.query.filter(Tag.id != source_tag_id).all()]
    if not other_tags:
        flash('אין תגיות אחרות להעברה אליהן.', 'warning')
        return redirect(url_for('admin_tags_bp.manage_tags'))
    
    form = TransferCouponsForm()
    form.target_tag_id.choices = other_tags
    form.source_tag_id.data = source_tag_id
    
    if form.validate_on_submit():
        target_tag = Tag.query.get(form.target_tag_id.data)
        
        # שליפת כל הקופונים מהתגית המקורית
        coupons = Coupon.query.filter_by(tag_id=source_tag_id).all()
        count = len(coupons)
        
        # העברת הקופונים לתגית היעד
        for coupon in coupons:
            coupon.tag_id = target_tag.id
        
        # עדכון ספירת הקופונים בכל תגית
        source_tag.count -= count
        target_tag.count += count
        
        db.session.commit()
        flash(f'{count} קופונים הועברו בהצלחה מהתגית "{source_tag.name}" לתגית "{target_tag.name}".', 'success')
        return redirect(url_for('admin_tags_bp.manage_tags'))
    
    return render_template('transfer_coupons.html', form=form, source_tag=source_tag)

# admin_tags_routes.py

from flask import Blueprint, redirect, url_for, flash, request, render_template
from flask_login import login_required, current_user
from app.models import Tag, Coupon
from app.extensions import db
from app.forms import TagManagementForm, DeleteTagForm, EditTagForm, TransferCouponsForm

admin_tags_bp = Blueprint('admin_tags_bp', __name__, url_prefix='/admin/tags')

# רוט לניהול תגיות
@admin_tags_bp.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_tags():
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בדף זה.', 'danger')
        return redirect(url_for('auth.login'))

    # טופס הוספת תגית חדשה
    form = TagManagementForm()

    # טופס למחיקת תגית
    delete_form = DeleteTagForm()

    # טופס לעריכת שם תגית
    edit_form = EditTagForm()

    # טופס להעברת קופונים
    transfer_form = TransferCouponsForm()

    # טיפול בשליחת טופס הוספת תגית
    if form.validate_on_submit():
        new_tag = Tag(name=form.name.data)
        db.session.add(new_tag)
        db.session.commit()
        flash(f'התגית "{new_tag.name}" נוצרה בהצלחה.', 'success')
        return redirect(url_for('admin_tags_bp.manage_tags'))

    # שליפת כל התגיות
    tags = Tag.query.all()

    # עדכון רשימת התגיות בטופס העברת הקופונים
    if tags:
        transfer_form.target_tag_id.choices = [(tag.id, tag.name) for tag in tags]

    return render_template(
        'admin/admin_manage_tags.html',
        form=form,             # טופס להוספת תגית
        edit_form=edit_form,   # טופס לעריכת תגית
        transfer_form=transfer_form,  # טופס להעברת קופונים
        delete_form=delete_form,   # טופס למחיקת תגית
        tags=tags              # רשימת כל התגיות
    )

# ===============================
# Blueprint לניהול מערכת (admin_bp)
# ===============================
admin_bp = Blueprint('admin', __name__)

# עדכון עסקאות קופונים
@admin_bp.route('/update_coupon_transactions', methods=['POST'])
@login_required
def update_coupon_transactions():
    # בדיקת הרשאות – רק אדמין מורשה
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        coupon_id = request.form.get('coupon_id')
        coupon_code = request.form.get('coupon_code')

        coupon = None
        if coupon_id:
            coupon = Coupon.query.get(coupon_id)
        elif coupon_code:
            coupon = Coupon.query.filter_by(code=coupon_code).first()

        if coupon:
            return redirect(url_for('coupon_detail', id=coupon.id))
        else:
            flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
            return redirect(url_for('show_coupons'))

    # קבלת נתוני הקופון מהטופס
    coupon_id = request.form.get('coupon_id')
    coupon_code = request.form.get('coupon_code')
    logger.info(f"coupon_id: {coupon_id}, coupon_code: {coupon_code}")

    coupon = None
    if coupon_id:
        coupon = Coupon.query.get(coupon_id)
    elif coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()

    if not coupon:
        flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
        return redirect(url_for('show_coupons'))

    # שליפת נתונים ועדכון עסקאות
    df = get_coupon_data(coupon.code)
    if df is not None:
        # מחיקת עסקאות קודמות ממקור Multipass
        CouponTransaction.query.filter_by(coupon_id=coupon.id, source='Multipass').delete()

        for index, row in df.iterrows():
            transaction = CouponTransaction(
                coupon_id=coupon.id,
                transaction_date=row['transaction_date'],
                location=row['location'],
                recharge_amount=row['recharge_amount'] or 0,
                usage_amount=row['usage_amount'] or 0,
                reference_number=row.get('reference_number', ''),
                source='Multipass'
            )
            db.session.add(transaction)

        # עדכון השדה used_value של הקופון
        total_used = df['usage_amount'].sum()
        coupon.used_value = total_used

        db.session.commit()
        flash(f'הנתונים עבור הקופון {coupon.code} עודכנו בהצלחה.', 'success')
    else:
        flash(f'אירעה שגיאה בעת עדכון הנתונים עבור הקופון {coupon.code}.', 'danger')

    return redirect(url_for('coupon_detail', id=coupon.id))

# ניהול משתמשים
@admin_bp.route('/manage_users', methods=['GET'])
@login_required
def manage_users():
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בדף זה.', 'danger')
        return redirect(url_for('auth.login'))

    users = User.query.all()
    return render_template('admin_manage_users.html', users=users)

# איפוס סיסמת משתמש
@admin_bp.route('/reset_user_password', methods=['POST'])
@login_required
def reset_user_password():
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('auth.login'))

    user_id = request.form.get('user_id')
    user = User.query.get(user_id)
    if not user:
        flash('משתמש לא נמצא.', 'error')
        return redirect(url_for('admin.manage_users'))

    send_password_reset_email(user)
    flash(f'נשלח מייל שחזור סיסמה ל-{user.email} בהצלחה!', 'success')
    return redirect(url_for('admin.manage_users'))

# ניהול טבלת feature_access – הוספה וצפייה
@admin_bp.route('/feature_access', methods=['GET', 'POST'])
@login_required
def manage_feature_access():
    if not current_user.is_admin:
        flash('אין לך הרשאה לגשת לעמוד זה.', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        feature_name = request.form.get('feature_name')
        access_mode = request.form.get('access_mode')

        new_feature = FeatureAccess(
            feature_name=feature_name,
            access_mode=access_mode
        )
        db.session.add(new_feature)
        db.session.commit()

        flash('הפיצ’ר נוסף בהצלחה!', 'success')
        return redirect(url_for('admin.manage_feature_access'))

    features = FeatureAccess.query.all()
    return render_template('manage_features.html', features=features)
