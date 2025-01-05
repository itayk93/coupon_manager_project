# marketplace_routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from app.models import Coupon, User, Transaction, Notification, CouponRequest, Tag, Company
from app.helpers import send_coupon_purchase_request_email, get_coupon_data, get_geo_location
from app.extensions import db
import logging
from datetime import datetime, timezone
import os
from app.helpers import send_email
from sqlalchemy.sql import text

marketplace_bp = Blueprint('marketplace', __name__)

logger = logging.getLogger(__name__)

from app.helpers import get_geo_location, get_public_ip

def log_user_activity(action, coupon_id=None):
    """
    רישום פעולות משתמש.
    """
    try:
        # קבלת נתוני IP וגיאוגרפיה
        ip_address = get_public_ip() or '0.0.0.0'
        geo_data = get_geo_location(ip_address)
        user_agent = request.headers.get('User-Agent', '')

        # בניית נתוני הפעולה
        activity = {
            "user_id": current_user.id if current_user.is_authenticated else None,
            "coupon_id": coupon_id,
            "timestamp": datetime.utcnow(),
            "action": action,
            "device": user_agent[:50] if user_agent else None,
            "browser": user_agent.split(' ')[0][:50] if user_agent else None,
            "ip_address": ip_address[:45] if ip_address else None,
            "city": geo_data.get("city"),
            "region": geo_data.get("region"),
            "country": geo_data.get("country"),
            "isp": geo_data.get("isp"),
            "lat": geo_data.get("lat"),
            "lon": geo_data.get("lon"),
            "timezone": geo_data.get("timezone"),
        }

        # כתיבה למסד הנתונים
        db.session.execute(
            text("""
                INSERT INTO user_activities (user_id, coupon_id, timestamp, action, device, browser, ip_address, city, region, country, isp, lat, lon, timezone)
                VALUES (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :city, :region, :country, :isp, :lat, :lon, :timezone)
            """),
            activity
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging activity: {e}")


@marketplace_bp.route('/marketplace')
@login_required
def marketplace():
    log_user_activity("marketplace_view", None)

    coupons = Coupon.query.filter_by(is_available=True, is_for_sale=True).all()
    coupon_requests = CouponRequest.query.filter_by(fulfilled=False).all()
    requested_coupon_ids = [
        transaction.coupon_id for transaction in
        Transaction.query.filter_by(buyer_id=current_user.id).all()
    ]

    companies = Company.query.all()
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}
    company_logo_mapping_by_id = {company.id: company.image_path for company in companies}
    company_name_mapping_by_id = {company.id: company.name for company in companies}

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
        pending_as_seller_count=pending_as_seller_count,
        pending_as_buyer_count=pending_as_buyer_count
    )


@marketplace_bp.route('/marketplace/coupon/<int:id>')
@login_required
def marketplace_coupon_detail(id):
    log_user_activity("marketplace_coupon_detail_view", coupon_id=id)

    coupon = Coupon.query.get_or_404(id)
    if not coupon.is_available or not coupon.is_for_sale:
        flash('קופון זה אינו זמין במרקטפלייס.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    seller = User.query.get(coupon.user_id)
    return render_template('marketplace_coupon_detail.html', coupon=coupon, seller=seller)


@marketplace_bp.route('/request_coupon/<int:id>', methods=['GET', 'POST'])
@login_required
def request_coupon_detail(id):
    log_user_activity("request_coupon_detail_view", None)

    coupon_request = CouponRequest.query.get_or_404(id)
    if coupon_request.fulfilled:
        flash('בקשת הקופון כבר טופלה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    delete_form = DeleteCouponRequestForm()
    if delete_form.validate_on_submit():
        db.session.delete(coupon_request)
        db.session.commit()
        flash('הבקשה נמחקה בהצלחה.', 'success')
        return redirect(url_for('marketplace.marketplace'))

    requester = User.query.get(coupon_request.user_id)
    company = Company.query.get(coupon_request.company)
    if not company:
        flash('החברה לא נמצאה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    company_logo_mapping = {company.name.lower(): company.image_path for company in Company.query.all()}
    return render_template(
        'coupon_request_detail.html',
        coupon_request=coupon_request,
        requester=requester,
        company=company,
        company_logo_mapping=company_logo_mapping,
        delete_form=delete_form
    )


@marketplace_bp.route('/request_to_buy/<int:coupon_id>', methods=['POST'])
@login_required
def request_to_buy(coupon_id):
    log_user_activity("request_to_buy_attempt", coupon_id=coupon_id)

    coupon = Coupon.query.get_or_404(coupon_id)
    if coupon.user_id == current_user.id:
        flash('אינך יכול לקנות את הקופון של עצמך.', 'warning')
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
        link=url_for('marketplace.my_transactions')
    )
    db.session.add(notification)
    db.session.commit()

    transaction.buyer_request_sent_at = datetime.utcnow()
    db.session.commit()

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
    log_user_activity("buy_coupon_attempt", None)

    coupon_id = request.form.get('coupon_id', type=int)
    if not coupon_id:
        flash('קופון לא תקין.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

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
    log_user_activity("coupon_request_detail_view", None)

    coupon_request = CouponRequest.query.get_or_404(id)
    if coupon_request.fulfilled:
        flash('בקשת הקופון כבר טופלה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    delete_form = DeleteCouponRequestForm()
    if delete_form.validate_on_submit():
        db.session.delete(coupon_request)
        db.session.commit()
        flash('הבקשה נמחקה בהצלחה.', 'success')
        return redirect(url_for('marketplace.marketplace'))

    requester = User.query.get(coupon_request.user_id)
    company = Company.query.get(coupon_request.company)
    if not company:
        flash('החברה לא נמצאה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    company_logo_mapping = {company.name.lower(): company.image_path for company in Company.query.all()}
    return render_template(
        'coupon_request_detail.html',
        coupon_request=coupon_request,
        requester=requester,
        company=company,
        company_logo_mapping=company_logo_mapping,
        delete_form=delete_form
    )


@marketplace_bp.route('/delete_coupon_request/<int:id>', methods=['POST'])
@login_required
def delete_coupon_request(id):
    log_user_activity("delete_coupon_request_attempt", None)

    coupon_request = CouponRequest.query.get_or_404(id)
    if coupon_request.user_id != current_user.id:
        flash('אין לך הרשאה למחוק בקשה זו.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    try:
        db.session.delete(coupon_request)
        db.session.commit()

        try:
            log_user_activity("delete_coupon_request_success", None)
        except Exception as e:
            current_app.logger.error(f"Error logging success activity [delete_coupon_request_success]: {e}")

        flash('בקשת הקופון נמחקה בהצלחה.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting coupon request {id}: {e}")
        flash('אירעה שגיאה בעת מחיקת הבקשה.', 'danger')

    return redirect(url_for('marketplace.marketplace'))


@marketplace_bp.route('/my_transactions')
@login_required
def my_transactions():
    log_user_activity("my_transactions_view", None)

    transactions_as_buyer = Transaction.query.filter(
        Transaction.buyer_id == current_user.id,
        Transaction.status.in_(['ממתין לאישור המוכר', 'ממתין לאישור הקונה'])
    ).all()

    transactions_as_seller = Transaction.query.filter(
        Transaction.seller_id == current_user.id,
        Transaction.status.in_(['ממתין לאישור המוכר', 'ממתין לאישור הקונה'])
    ).all()

    completed_transactions = Transaction.query.filter(
        Transaction.status.in_(['מבוטל', 'הושלם']),
        ((Transaction.buyer_id == current_user.id) | (Transaction.seller_id == current_user.id))
    ).all()

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
    log_user_activity("approve_transaction_view", transaction_id)

    # שליפת העסקה מהדאטהבייס
    transaction = Transaction.query.get_or_404(transaction_id)

    # בדיקת הרשאות (שהמשתמש הוא המוכר בעסקה)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coupons.my_transactions'))

    # בדיקה אם העסקה כבר אושרה בעבר
    if transaction.seller_approved or transaction.status == 'ממתין לאישור הקונה':
        flash('כבר אישרת את העסקה. לא ניתן לאשר שוב.', 'warning')
        return redirect(url_for('coupons.my_transactions'))

    # יצירת אובייקט טופס
    form = ApproveTransactionForm()

    # ווידוא שהבקשה היא POST והטופס תקין
    if request.method == 'POST' and form.validate_on_submit():
        try:
            # עדכון פרטי העסקה
            transaction.seller_phone = form.seller_phone.data
            transaction.seller_approved = True
            transaction.coupon_code_entered = True
            transaction.status = 'ממתין לאישור הקונה'

            # שמירת השינויים בדאטהבייס
            db.session.commit()

            # הוספת הודעת הצלחה ללוגים ולמשתמש
            print("Transaction updated successfully!")
            flash('אישרת את העסקה בהצלחה!', 'success')

            # שליחת מייל לקונה
            seller = transaction.seller
            buyer = transaction.buyer
            coupon = transaction.coupon

            html_content = render_template(
                'emails/seller_approved_transaction.html',
                seller=seller,
                buyer=buyer,
                coupon=coupon
            )
            send_email(
                sender_email='itayk93@gmail.com',
                sender_name='MaCoupon',
                recipient_email=buyer.email,
                recipient_name=f'{buyer.first_name} {buyer.last_name}',
                subject='המוכר אישר את העסקה',
                html_content=html_content
            )

            # הפניה לעמוד העסקאות
            return redirect(url_for('coupons.my_transactions'))

        except Exception as e:
            # טיפול בשגיאה ועדכון הדאטהבייס
            db.session.rollback()
            print(f"Error committing transaction: {e}")
            flash('שגיאה בעת אישור העסקה. נסה שוב מאוחר יותר.', 'danger')

    # אם זה GET בלבד, הצגת העמוד עם הטופס
    return render_template('approve_transaction.html', form=form, transaction=transaction)


@marketplace_bp.route('/decline_transaction/<int:transaction_id>')
@login_required
def decline_transaction(transaction_id):
    log_user_activity("decline_transaction", None)

    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coupons.my_transactions'))

    coupon = transaction.coupon
    coupon.is_available = True
    db.session.delete(transaction)
    db.session.commit()
    flash('דחית את העסקה.', 'info')
    return redirect(url_for('coupons.my_transactions'))


@marketplace_bp.route('/confirm_transaction/<int:transaction_id>')
@login_required
def confirm_transaction(transaction_id):
    log_user_activity("confirm_transaction", None)

    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coupons.my_transactions'))

    transaction.status = 'הושלם'
    coupon = transaction.coupon
    coupon.user_id = current_user.id
    coupon.is_available = True
    db.session.commit()
    flash('אישרת את העסקה. הקופון הועבר לחשבונך.', 'success')

    # כעת נפנה אותו למסך הביקורת על המוכר
    seller_id = transaction.seller_id
    return redirect(url_for('marketplace.review_seller', seller_id=seller_id, transaction_id=transaction.id))


@marketplace_bp.route('/cancel_transaction/<int:transaction_id>')
@login_required
def cancel_transaction(transaction_id):
    log_user_activity("cancel_transaction", None)

    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coupons.my_transactions'))

    coupon = transaction.coupon
    coupon.is_available = True
    db.session.delete(transaction)
    db.session.commit()
    flash('ביטלת את העסקה.', 'info')
    return redirect(url_for('coupons.my_transactions'))


def complete_transaction(transaction):
    """
    פונקציה פנימית להשלמת עסקה. במידת הצורך ניתן לקרוא לה במקום אחר בקוד.
    כאן גם ניתן לשלב לוג, בדומה לשאר הפעולות.
    """
    try:
        # Log the completion attempt
        log_user_activity("complete_transaction", coupon_id=transaction.coupon_id)
    except Exception as e:
        current_app.logger.error(f"Error logging activity [complete_transaction]: {e}")

    try:
        coupon = transaction.coupon
        coupon.user_id = transaction.buyer_id
        coupon.is_for_sale = False
        coupon.is_available = True
        transaction.status = 'הושלם'

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
    log_user_activity("offer_coupon_view", None)

    coupon_request = CouponRequest.query.get_or_404(request_id)
    if coupon_request.user_id == current_user.id:
        flash('אינך יכול למכור לעצמך.', 'warning')
        return redirect(url_for('marketplace.marketplace'))

    seller_coupons = Coupon.query.filter_by(
        user_id=current_user.id,
        company=coupon_request.company,
        is_for_sale=False
    ).all()

    if not seller_coupons:
        flash('אין לך קופונים מתאימים למכירה.', 'warning')
        return redirect(url_for('marketplace.marketplace'))

    if request.method == 'POST':
        selected_coupon_id = request.form.get('coupon_id')
        coupon = Coupon.query.get(selected_coupon_id)
        if coupon is None or coupon.user_id != current_user.id:
            flash('קופון לא תקין.', 'danger')
            return redirect(url_for('marketplace.marketplace'))

        transaction = Transaction(
            coupon_id=coupon.id,
            buyer_id=coupon_request.user_id,
            seller_id=current_user.id,
            status='ממתין לאישור הקונה'
        )
        db.session.add(transaction)

        coupon.is_available = False

        notification = Notification(
            user_id=coupon_request.user_id,
            message=f"{current_user.first_name} {current_user.last_name} מציע לך קופון עבור {coupon_request.company}.",
            link=url_for('coupons.my_transactions')
        )
        db.session.add(notification)
        db.session.commit()

        try:
            log_user_activity("offer_coupon_submit", coupon_id=coupon.id)
        except Exception as e:
            current_app.logger.error(f"Error logging activity [offer_coupon_submit]: {e}")

        flash('הצעתך נשלחה לקונה.', 'success')
        return redirect(url_for('coupons.my_transactions'))

    return render_template('select_coupon_to_offer.html', coupon_request=coupon_request, seller_coupons=seller_coupons)


@marketplace_bp.route('/seller_cancel_transaction/<int:transaction_id>')
@login_required
def seller_cancel_transaction(transaction_id):
    log_user_activity("seller_cancel_transaction_attempt", transaction_id)

    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לבטל עסקה זו.', 'danger')
        return redirect(url_for('marketplace.my_transactions'))

    seller = transaction.seller
    buyer = transaction.buyer
    coupon = transaction.coupon

    coupon.is_available = True

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

    transaction.status = 'מבוטל'
    transaction.updated_at = datetime.utcnow()
    db.session.commit()

    try:
        log_user_activity("seller_cancel_transaction_success", transaction_id)
    except Exception as e:
        current_app.logger.error(f"Error logging activity [seller_cancel_transaction_success]: {e}")

    return redirect(url_for('marketplace.my_transactions'))


@marketplace_bp.route('/review_seller/<int:seller_id>', methods=['GET', 'POST'])
@login_required
def review_seller(seller_id):
    """
    הקונה משאיר ביקורת למוכר.
    נבדוק שמדובר בקונה שאכן סיים עסקה עם המוכר הזה.
    """
    transaction_id = request.args.get('transaction_id', type=int)

    # בדיקה אם אכן קיימת עסקה הושלמה בין current_user (הקונה) למוכר (seller_id)
    transaction = Transaction.query.filter_by(
        id=transaction_id,
        buyer_id=current_user.id,
        seller_id=seller_id,
        status='הושלם'
    ).first()

    if not transaction:
        flash('לא נמצאה עסקה תקינה להוספת ביקורת.', 'danger')
        return redirect(url_for('marketplace.my_transactions'))

    if request.method == 'GET':
        # בדיקה אם כבר השארת ביקורת על העסקה הזו (אופציונלי).
        existing_review = UserReview.query.filter_by(
            reviewer_id=current_user.id,
            reviewed_user_id=seller_id
        ).first()
        if existing_review:
            flash('כבר השארת ביקורת על משתמש זה.', 'info')
            return redirect(url_for('marketplace.my_transactions'))

        return render_template('review_seller.html', seller_id=seller_id)

    if request.method == 'POST':
        # מקבלים את הערך מהסליידר (1-5) ואת התגובה
        rating_str = request.form.get('rating')
        comment = request.form.get('comment', '')

        # ולידציה בסיסית
        try:
            rating = int(rating_str)
        except:
            flash('עליך לבחור דירוג תקין בין 1 ל-5.', 'danger')
            return redirect(request.url)

        if rating < 1 or rating > 5:
            flash('הדירוג חייב להיות בין 1 ל-5.', 'danger')
            return redirect(request.url)

        # שמירת הביקורת
        user_review = UserReview(
            reviewer_id=current_user.id,
            reviewed_user_id=seller_id,
            rating=rating,
            comment=comment
        )
        db.session.add(user_review)
        db.session.commit()

        flash('הביקורת נשמרה בהצלחה!', 'success')
        return redirect(url_for('profile.profile_view', user_id=seller_id))

@marketplace_bp.route('/buyer_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def buyer_confirm_transfer(transaction_id):
    """
    הקונה מאשר שההעברה הכספית בוצעה.
    """
    log_user_activity("buyer_confirm_transfer_view", transaction_id)

    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('marketplace.my_transactions'))

    # אם הגיעו בטופס POST (כלומר לחצו על "אשר שההעברה הכספית בוצעה")
    if request.method == 'POST':
        # נסמן בדאטה־בייס שהקונה אישר
        transaction.buyer_confirmed = True
        transaction.buyer_confirmed_at = datetime.utcnow()
        db.session.commit()

        flash('אישרת שההעברה הכספית בוצעה.', 'success')

        # שליחת מייל למוכר (בדומה לבקוד הישן שלך)
        seller = transaction.seller
        buyer = transaction.buyer
        coupon = transaction.coupon
        if seller and seller.email:
            try:
                html_content = render_template(
                    'emails/buyer_confirmed_transfer.html',
                    seller=seller, buyer=buyer, coupon=coupon
                )
                send_email(
                    sender_email='itayk93@gmail.com',
                    sender_name='MaCoupon',
                    recipient_email=seller.email,
                    recipient_name=f'{seller.first_name} {seller.last_name}',
                    subject='הקונה אישר שההעברה הכספית בוצעה',
                    html_content=html_content
                )
            except Exception as e:
                current_app.logger.error(f"Error sending buyer_confirmed_transfer email to seller: {e}")
                flash('האישור נקלט אך המייל למוכר לא נשלח.', 'warning')

        # בדיקה אם גם המוכר אישר (seller_approved), ואם הקוד הוזן (coupon_code_entered)
        if transaction.seller_approved and transaction.buyer_confirmed and transaction.coupon_code_entered:
            # במקרה ששלושת התנאים התקיימו, קוראים לפונקציה שמסיימת את העסקה
            complete_transaction(transaction)

        return redirect(url_for('marketplace.my_transactions'))

    # אם זה GET בלבד, אפשר סתם להחזיר דף המאשר שזו פעולת הקונה.
    return render_template('buyer_confirm_transfer.html', transaction=transaction)
