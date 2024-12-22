# admin_routes.py

from flask import Blueprint, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import Coupon, CouponTransaction
from app.helpers import get_coupon_data
from app.extensions import db
import logging

admin_bp = Blueprint('admin', __name__)

logger = logging.getLogger(__name__)

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
                card_number=row['card_number'],
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
