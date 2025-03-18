# admin_routes.py

from flask import Blueprint, redirect, url_for, flash, request, render_template
from flask_login import login_required, current_user
from app.models import Coupon, CouponTransaction, FeatureAccess, User
from app.helpers import get_coupon_data, has_feature_access, send_password_reset_email
from app.extensions import db
import logging

admin_bp = Blueprint('admin', __name__)
logger = logging.getLogger(__name__)

# -------------------
# Routes
# -------------------

@admin_bp.route('/update_coupon_transactions', methods=['POST'])
@login_required
def update_coupon_transactions():
    # בדיקת הרשאות
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

    # קבלת הנתונים מהטופס
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

    # קבלת הנתונים ועדכון העסקאות
    df = get_coupon_data(coupon.code)
    if df is not None:
        # מחיקת עסקאות קודמות שהגיעו מ-Multipass בלבד
        CouponTransaction.query.filter_by(coupon_id=coupon.id, source='Multipass').delete()

        # הוספת עסקאות חדשות
        for index, row in df.iterrows():
            transaction = CouponTransaction(
                coupon_id=coupon.id,
                transaction_date=row['transaction_date'],
                location=row['location'],
                recharge_amount=row['recharge_amount'] or 0,
                usage_amount=row['usage_amount'] or 0,
                reference_number=row.get('reference_number', ''),
                source='Multipass'  # ציון שהעסקה הגיעה מ-Multipass
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

@admin_bp.route('/manage_users', methods=['GET'])
@login_required
def manage_users():
    # וידוא שהמשתמש הוא אדמין
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בדף זה.', 'danger')
        return redirect(url_for('auth.login'))

    users = User.query.all()
    return render_template('admin_manage_users.html', users=users)

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

    # שליחת מייל שחזור סיסמה
    send_password_reset_email(user)
    flash(f'נשלח מייל שחזור סיסמה ל-{user.email} בהצלחה!', 'success')
    return redirect(url_for('admin.manage_users'))

# ---------------------------------------------------
# רוט חדש: ניהול טבלת feature_access
# ---------------------------------------------------
@admin_bp.route('/feature_access', methods=['GET', 'POST'])
@login_required
def manage_feature_access():
    """מסך לניהול רשומות בטבלת feature_access (לדוגמה: הוספה/צפייה)."""
    # בדיקת הרשאות אפליקטיבית: רק אדמין יכול לגשת
    if not current_user.is_admin:
        flash('אין לך הרשאה לגשת לעמוד זה.', 'danger')
        return redirect(url_for('auth.login'))  # או הפניה לאן שרוצים

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
        # מפנה חזרה לרוט לצפייה בכל הרשומות
        return redirect(url_for('admin.manage_feature_access'))

    # בשיטת GET – שולפים את כל הרשומות מהטבלה
    features = FeatureAccess.query.all()
    return render_template('manage_features.html', features=features)
