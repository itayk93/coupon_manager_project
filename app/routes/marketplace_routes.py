# marketplace_routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from app.models import Coupon, User, Transaction, Notification, CouponRequest, Tag, Company
from app.helpers import send_coupon_purchase_request_email, get_coupon_data
from app.extensions import db
import logging
from datetime import datetime, timezone
import os
from app.helpers import send_email

marketplace_bp = Blueprint('marketplace', __name__)

logger = logging.getLogger(__name__)

@marketplace_bp.route('/marketplace')
@login_required
def marketplace():
    coupons = Coupon.query.filter_by(is_available=True, is_for_sale=True).all()
    coupon_requests = CouponRequest.query.filter_by(fulfilled=False).all()
    requested_coupon_ids = [transaction.coupon_id for transaction in
                            Transaction.query.filter_by(buyer_id=current_user.id).all()]

    companies = Company.query.all()
    # מיפויים לפי מזהה ושם חברה
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}
    company_logo_mapping_by_id = {company.id: company.image_path for company in companies}
    company_name_mapping_by_id = {company.id: company.name for company in companies}

    # ------------------------------------------
    # 1) שאילתות עבור עסקאות ממתינות
    # ------------------------------------------
    pending_as_seller_count = Transaction.query.filter_by(
        seller_id=current_user.id, status='ממתין לאישור המוכר'
    ).count()

    pending_as_buyer_count = Transaction.query.filter_by(
        buyer_id=current_user.id, status='ממתין לאישור המוכר'
    ).count()

    return render_template(
        'marketplace.html',
        coupons=coupons,
        requested_coupon_ids=requested_coupon_ids,
        coupon_requests=coupon_requests,
        company_logo_mapping=company_logo_mapping,
        company_logo_mapping_by_id=company_logo_mapping_by_id,
        company_name_mapping_by_id=company_name_mapping_by_id,

        # מעבירים את המספרים לתבנית
        pending_as_seller_count=pending_as_seller_count,
        pending_as_buyer_count=pending_as_buyer_count
    )

@marketplace_bp.route('/marketplace/coupon/<int:id>')
@login_required
def marketplace_coupon_detail(id):
    coupon = Coupon.query.get_or_404(id)
    if not coupon.is_available or not coupon.is_for_sale:
        flash('קופון זה אינו זמין במרקטפלייס.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    # שליפת פרטי המוכר
    seller = User.query.get(coupon.user_id)

    return render_template('marketplace_coupon_detail.html', coupon=coupon, seller=seller)

@marketplace_bp.route('/request_coupon', methods=['GET', 'POST'])
@login_required
def request_coupon_detail(id):
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

@marketplace_bp.route('/request_to_buy/<int:coupon_id>', methods=['POST'])
@login_required
def request_to_buy(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    if coupon.user_id == current_user.id:
        flash('אינך יכול לקנות את הקופון של עצמך.', 'warning')
        return redirect(url_for('marketplace.marketplace'))

    if not coupon.is_available or not coupon.is_for_sale:
        flash('קופון זה אינו זמין למכירה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    # יצירת טרנזקציה חדשה
    transaction = Transaction(
        coupon_id=coupon.id,
        buyer_id=current_user.id,
        seller_id=coupon.user_id,
        status='ממתין לאישור המוכר'
    )
    db.session.add(transaction)

    # סימון הקופון כלא זמין
    coupon.is_available = False

    # יצירת התראה למוכר
    notification = Notification(
        user_id=coupon.user_id,
        message=f"{current_user.first_name} {current_user.last_name} מבקש לקנות את הקופון שלך.",
        link=url_for('coupons.my_transactions')
    )
    db.session.add(notification)
    db.session.commit()

    # עדכון זמן שליחת הבקשה מהקונה
    transaction.buyer_request_sent_at = datetime.utcnow()
    db.session.commit()

    # שליחת מייל למוכר
    seller = coupon.user
    buyer = current_user
    try:
        send_coupon_purchase_request_email(seller, buyer, coupon)
        flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
    except Exception as e:
        logger.error(f'שגיאה בשליחת מייל למוכר: {e}')
        flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

    return redirect(url_for('coupons.my_transactions'))

@marketplace_bp.route('/buy_coupon', methods=['POST'])
@login_required
def buy_coupon():
    """
    רוטה לטיפול בבקשת קנייה של קופון.
    """
    coupon_id = request.form.get('coupon_id', type=int)
    if not coupon_id:
        flash('קופון לא תקין.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    coupon = Coupon.query.get_or_404(coupon_id)

    # בדיקת אם המשתמש מנסה לקנות את הקופון שלו
    if coupon.user_id == current_user.id:
        flash('אינך יכול לקנות את הקופון שלך.', 'warning')
        return redirect(url_for('marketplace.marketplace'))

    # בדיקת זמינות הקופון למכירה
    if not coupon.is_available or not coupon.is_for_sale:
        flash('קופון זה אינו זמין למכירה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    # יצירת טרנזקציה חדשה
    transaction = Transaction(
        coupon_id=coupon.id,
        buyer_id=current_user.id,
        seller_id=coupon.user_id,
        status='ממתין לאישור המוכר'
    )
    db.session.add(transaction)

    # סימון הקופון כלא זמין
    coupon.is_available = False

    # יצירת התראה למוכר
    notification = Notification(
        user_id=coupon.user_id,
        message=f"{current_user.first_name} {current_user.last_name} מבקש לקנות את הקופון שלך.",
        link=url_for('coupons.my_transactions')
    )
    db.session.add(notification)

    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        logger.error(f"Error creating transaction: {e}")
        flash('אירעה שגיאה בעת יצירת העסקה. נסה שוב מאוחר יותר.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    # שליחת מייל למוכר באמצעות הפונקציה הנפרדת
    seller = coupon.user
    buyer = current_user
    try:
        send_coupon_purchase_request_email(seller, buyer, coupon)
        flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
    except Exception as e:
        logger.error(f'שגיאה בשליחת מייל למוכר: {e}')
        flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

    return redirect(url_for('coupons.my_transactions'))

@marketplace_bp.route('/coupon_request/<int:id>', methods=['GET', 'POST'])
@login_required
def coupon_request_detail_view(id):
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

@marketplace_bp.route('/delete_coupon_request/<int:id>', methods=['POST'])
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

###
# כאן מגיע השינוי המרכזי ב-my_transactions
# נעדכן כך שיציג עסקאות פעילות בנפרד ו"עסקאות שהסתיימו" בנפרד.
###
@marketplace_bp.route('/my_transactions')
@login_required
def my_transactions():
    # עסקאות פעילות
    transactions_as_buyer = Transaction.query.filter(
        Transaction.buyer_id == current_user.id,
        Transaction.status.in_(['ממתין לאישור המוכר', 'ממתין לאישור הקונה'])
    ).all()

    transactions_as_seller = Transaction.query.filter(
        Transaction.seller_id == current_user.id,
        Transaction.status.in_(['ממתין לאישור המוכר', 'ממתין לאישור הקונה'])
    ).all()

    # עסקאות שהסתיימו
    completed_transactions = Transaction.query.filter(
        Transaction.status.in_(['מבוטל', 'הושלם']),
        ((Transaction.buyer_id == current_user.id) | (Transaction.seller_id == current_user.id))
    ).all()

    # מיפוי לוגו
    companies = Company.query.all()
    company_logo_mapping = {c.name.lower(): c.image_path for c in companies}

    return render_template(
        'my_transactions.html',
        transactions_as_buyer=transactions_as_buyer,
        transactions_as_seller=transactions_as_seller,
        completed_transactions=completed_transactions,
        company_logo_mapping=company_logo_mapping
    )

@marketplace_bp.route('/approve_transaction/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def approve_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coupons.my_transactions'))

    # אם המוכר כבר אישר פעם אחת או שהסטטוס אינו "ממתין לאישור המוכר" – חסימה
    if transaction.seller_approved or transaction.status == 'ממתין לאישור הקונה':
        flash('כבר אישרת את העסקה. לא ניתן לאשר שוב.', 'warning')
        return redirect(url_for('coupons.my_transactions'))

    form = ApproveTransactionForm()
    if form.validate_on_submit():
        transaction.seller_phone = form.seller_phone.data
        transaction.seller_approved = True
        transaction.coupon_code_entered = True
        transaction.status = 'ממתין לאישור הקונה'
        db.session.commit()

        # לאחר שהמוכר אישר את העסקה, נשלח מייל לקונה
        seller = transaction.seller
        buyer = transaction.buyer
        coupon = transaction.coupon

        html_content = render_template(
            'emails/seller_approved_transaction.html',
            seller=seller,
            buyer=buyer,
            coupon=coupon
        )

        try:
            send_email(
                sender_email='itayk93@gmail.com',
                sender_name='MaCoupon',
                recipient_email=buyer.email,
                recipient_name=f'{buyer.first_name} {buyer.last_name}',
                subject='המוכר אישר את העסקה',
                html_content=html_content
            )
            flash('אישרת את העסקה והמייל נשלח לקונה בהצלחה.', 'success')
        except Exception as e:
            logger.error(f"Error sending seller approved email: {e}")
            flash('העסקה אושרה, אך לא הצלחנו לשלוח מייל לקונה.', 'warning')

        return redirect(url_for('coupons.my_transactions'))

    return render_template('approve_transaction.html', form=form, transaction=transaction)

@marketplace_bp.route('/decline_transaction/<int:transaction_id>')
@login_required
def decline_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coupons.my_transactions'))

    # החזרת הקופון לזמינות
    coupon = transaction.coupon
    coupon.is_available = True
    db.session.delete(transaction)
    db.session.commit()
    flash('דחית את העסקה.', 'info')
    return redirect(url_for('coupons.my_transactions'))

@marketplace_bp.route('/confirm_transaction/<int:transaction_id>')
@login_required
def confirm_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coupons.my_transactions'))

    transaction.status = 'הושלם'
    # העברת הבעלות על הקופון
    coupon = transaction.coupon
    coupon.user_id = current_user.id
    coupon.is_available = True
    db.session.commit()
    flash('אישרת את העסקה. הקופון הועבר לחשבונך.', 'success')
    return redirect(url_for('coupons.my_transactions'))

@marketplace_bp.route('/cancel_transaction/<int:transaction_id>')
@login_required
def cancel_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coupons.my_transactions'))

    # החזרת הקופון לזמינות
    coupon = transaction.coupon
    coupon.is_available = True
    db.session.delete(transaction)
    db.session.commit()
    flash('ביטלת את העסקה.', 'info')
    return redirect(url_for('coupons.my_transactions'))

def complete_transaction(transaction):
    try:
        coupon = transaction.coupon
        # העברת הבעלות על הקופון לקונה
        coupon.user_id = transaction.buyer_id
        # הקופון כבר לא למכירה
        coupon.is_for_sale = False
        # הקופון כעת זמין שוב לשימוש
        coupon.is_available = True

        # עדכון סטטוס העסקה
        transaction.status = 'הושלם'

        # אפשר להוסיף התראות לשני הצדדים, רישום לוג, וכדומה
        notification_buyer = Notification(
            user_id=transaction.buyer_id,
            message='הקופון הועבר לחשבונך.',
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )
        notification_seller = Notification(
            user_id=transaction.seller_id,
            message='העסקה הושלמה והקופון הועבר לקונה.',
            link=url_for('coupons.my_transactions')
        )

        db.session.add(notification_buyer)
        db.session.add(notification_seller)

        db.session.commit()
        flash('העסקה הושלמה בהצלחה והקופון הועבר לקונה!', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error completing transaction {transaction.id}: {e}")
        flash('אירעה שגיאה בעת השלמת העסקה. נא לנסות שוב.', 'danger')

@marketplace_bp.route('/offer_coupon/<int:request_id>', methods=['GET', 'POST'])
@login_required
def offer_coupon(request_id):
    coupon_request = CouponRequest.query.get_or_404(request_id)
    if coupon_request.user_id == current_user.id:
        flash('אינך יכול למכור לעצמך.', 'warning')
        return redirect(url_for('marketplace.marketplace'))

    # שליפת הקופונים של המוכר המתאימים לבקשה
    seller_coupons = Coupon.query.filter_by(
        user_id=current_user.id,
        company=coupon_request.company,
        is_for_sale=False
    ).all()

    if not seller_coupons:
        flash('אין לך קופונים מתאימים למכירה.', 'warning')
        return redirect(url_for('marketplace.marketplace'))

    if request.method == 'POST':
        coupon_id = request.form.get('coupon_id')
        coupon = Coupon.query.get(coupon_id)
        if coupon is None or coupon.user_id != current_user.id:
            flash('קופון לא תקין.', 'danger')
            return redirect(url_for('marketplace.marketplace'))

        # יצירת עסקה
        transaction = Transaction(
            coupon_id=coupon.id,
            buyer_id=coupon_request.user_id,
            seller_id=current_user.id,
            status='ממתין לאישור הקונה'
        )
        db.session.add(transaction)

        # סימון הקופון כלא זמין
        coupon.is_available = False

        # יצירת התראה לקונה
        notification = Notification(
            user_id=coupon_request.user_id,
            message=f"{current_user.first_name} {current_user.last_name} מציע לך קופון עבור {coupon_request.company}.",
            link=url_for('coupons.my_transactions')
        )
        db.session.add(notification)
        db.session.commit()

        flash('הצעתך נשלחה לקונה.', 'success')
        return redirect(url_for('coupons.my_transactions'))

    return render_template('select_coupon_to_offer.html', coupon_request=coupon_request, seller_coupons=seller_coupons)

@marketplace_bp.route('/seller_cancel_transaction/<int:transaction_id>')
@login_required
def seller_cancel_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לבטל עסקה זו.', 'danger')
        return redirect(url_for('marketplace.my_transactions'))

    seller = transaction.seller
    buyer = transaction.buyer
    coupon = transaction.coupon

    # החזרת הקופון לזמינות (אם צריך)
    coupon.is_available = True

    # שליחת מייל לקונה שהמוכר ביטל
    html_content = render_template(
        'emails/seller_canceled_transaction.html',
        seller=seller,
        buyer=buyer,
        coupon=coupon
    )
    try:
        send_email(
            sender_email='itayk93@gmail.com',
            sender_name='MaCoupon',
            recipient_email=buyer.email,
            recipient_name=f'{buyer.first_name} {buyer.last_name}',
            subject='המוכר ביטל את העסקה',
            html_content=html_content
        )
        flash('ביטלת את העסקה ונשלח מייל לקונה.', 'info')
    except Exception as e:
        logger.error(f"Error sending cancellation email to buyer: {e}")
        flash('ביטלת את העסקה, אך אירעה שגיאה בשליחת המייל.', 'warning')

    # עדכון הסטטוס ל"מבוטל"
    transaction.status = 'מבוטל'
    transaction.updated_at = datetime.utcnow()  # חשוב אם יש לכם עמודת updated_at
    db.session.commit()

    # ! מחזירים ל- marketplace.my_transactions
    return redirect(url_for('marketplace.my_transactions'))
