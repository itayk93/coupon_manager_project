# requests_routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from app.models import CouponRequest, User, Company, db
from app.forms import DeleteCouponRequestForm
import logging

requests_bp = Blueprint('requests', __name__)

logger = logging.getLogger(__name__)

@requests_bp.route('/coupon_request/<int:id>', methods=['GET', 'POST'])
@login_required
def coupon_request_detail(id):
    coupon_request = CouponRequest.query.get_or_404(id)

    # אם הבקשה כבר טופלה, חזרה לשוק הקופונים
    if coupon_request.fulfilled:
        flash('בקשת הקופון כבר טופלה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    # יצירת טופס מחיקה
    delete_form = DeleteCouponRequestForm()

    # אם הטופס הוגש
    if delete_form.validate_on_submit():
        # מחיקת הבקשה
        db.session.delete(coupon_request)
        db.session.commit()
        flash('הבקשה נמחקה בהצלחה.', 'success')
        return redirect(url_for('marketplace.marketplace'))  # חזרה לשוק הקופונים

    # שליפת פרטי המבקש
    requester = User.query.get(coupon_request.user_id)

    # שליפת החברה לפי ה-ID מהבקשה
    company = Company.query.get(coupon_request.company)

    # אם החברה לא נמצאה
    if not company:
        flash('החברה לא נמצאה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    # יצירת מילון של מיפוי לוגו של החברה
    company_logo_mapping = {company.name.lower(): company.image_path for company in Company.query.all()}

    return render_template(
        'coupon_request_detail.html',
        coupon_request=coupon_request,
        requester=requester,
        company=company,  # העברת אובייקט החברה
        company_logo_mapping=company_logo_mapping,
        delete_form=delete_form  # שליחה של הטופס לתבנית
    )

@requests_bp.route('/delete_coupon_request/<int:id>', methods=['POST'])
@login_required
def delete_coupon_request(id):
    coupon_request = CouponRequest.query.get_or_404(id)

    # בדיקת הרשאה: המשתמש יכול למחוק רק בקשות שהוא יצר
    if coupon_request.user_id != current_user.id:
        flash('אין לך הרשאה למחוק בקשה זו.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    try:
        db.session.delete(coupon_request)
        db.session.commit()
        flash('בקשת הקופון נמחקה בהצלחה.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting coupon request {id}: {e}")
        flash('אירעה שגיאה בעת מחיקת הבקשה.', 'danger')

    return redirect(url_for('marketplace.marketplace'))


@requests_bp.route('/request_coupon', methods=['GET', 'POST'])
@login_required
def request_coupon():
    if request.method == 'POST':
        coupon_id = request.form.get('coupon_id', type=int)
        coupon = Coupon.query.get_or_404(coupon_id)

        if coupon.user_id == current_user.id:
            flash('אינך יכול לקנות את הקופון שלך.', 'warning')
            return redirect(url_for('marketplace.marketplace'))

        if not coupon.is_available or not coupon.is_for_sale:
            flash('קופון זה אינו זמין למכירה.', 'danger')
            return redirect(url_for('marketplace.marketplace'))

        transaction = Transaction(
            coupon_id=coupon.id,
            buyer_id=current_user.id,
            seller_id=coupon.user_id,
            status='ממתין לאישור המוכר'
        )
        db.session.add(transaction)
        coupon.is_available = False

        notification = Notification(
            user_id=coupon.user_id,
            message=f"{current_user.first_name} {current_user.last_name} מבקש לקנות את הקופון שלך.",
            link=url_for('transactions.my_transactions')
        )
        db.session.add(notification)
        db.session.commit()

        seller = coupon.user
        buyer = current_user
        try:
            send_coupon_purchase_request_email(seller, buyer, coupon)
            flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
        except Exception as e:
            requests_bp.logger.error(f'שגיאה בשליחת מייל למוכר: {e}')
            flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

        return redirect(url_for('transactions.my_transactions'))

    return render_template('request_coupon.html')

@requests_bp.route('/buy_slots', methods=['GET', 'POST'])
@login_required
def buy_slots():
    form = BuySlotsForm()
    if form.validate_on_submit():
        try:
            slot_amount = int(form.slot_amount.data)
            if slot_amount not in [10, 20, 50]:
                flash('כמות סלוטים לא תקפה.', 'danger')
                return redirect(url_for('buy_slots'))

            # עדכון מספר ה-slots של המשתמש הנוכחי
            current_user.slots += slot_amount
            db.session.commit()
            flash(f'רכשת {slot_amount} סלוטים בהצלחה!', 'success')
            return redirect(url_for('buy_slots'))
        except ValueError:
            flash('כמות סלוטים לא תקפה.', 'danger')
            return redirect(url_for('buy_slots'))
    return render_template('buy_slots.html', slots=current_user.slots, form=form)
