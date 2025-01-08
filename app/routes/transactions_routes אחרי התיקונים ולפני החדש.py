from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from datetime import datetime, timezone
import logging
import traceback
import re

from app.models import (
    Coupon, User, Transaction, Notification,
    CouponRequest, CouponUsage, Tag, Company, db
)
from app.forms import (
    DeleteCouponRequestForm, ApproveTransactionForm,
    ConfirmDeleteForm, UpdateCouponUsageForm
)
from app.helpers import (
    send_coupon_purchase_request_email, send_email,
    get_coupon_data, update_coupon_status, complete_transaction,
    get_geo_location, get_public_ip
)

from sqlalchemy.sql import text

transactions_bp = Blueprint('transactions', __name__)
logger = logging.getLogger(__name__)

def log_user_activity(action, coupon_id=None):
    """
    רישום פעולות משתמש.
    """
    try:
        ip_address = get_public_ip() or '0.0.0.0'
        geo_data = get_geo_location(ip_address)
        user_agent = request.headers.get('User-Agent', '')

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

        db.session.execute(
            text("""
                INSERT INTO user_activities 
                (user_id, coupon_id, timestamp, action, device, browser, ip_address, city, region, country, isp, lat, lon, timezone)
                VALUES 
                (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :city, :region, :country, :isp, :lat, :lon, :timezone)
            """),
            activity
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging activity: {e}")

@transactions_bp.route('/my_transactions')
@login_required
def my_transactions():
    """
    מציג את כל העסקאות של המשתמש הנוכחי (גם כקונה וגם כמוכר),
    ומציג גם טבלת עסקאות שהסתיימו/בוטלו (completed_transactions).
    """
    log_user_activity("my_transactions_view")

    # עסקאות כקונה
    transactions_as_buyer = Transaction.query.filter_by(buyer_id=current_user.id).all()
    # עסקאות כמוכר
    transactions_as_seller = Transaction.query.filter_by(seller_id=current_user.id).all()

    # עסקאות שהסתיימו (או בוטלו)
    completed_transactions = Transaction.query.filter(
        Transaction.status.in_(['מבוטל', 'הושלם']),
        ((Transaction.buyer_id == current_user.id) | (Transaction.seller_id == current_user.id))
    ).all()

    # שליפת לוגואים של חברות
    companies = Company.query.all()
    company_logo_mapping = {c.name.lower(): c.image_path for c in companies}

    return render_template(
        'my_transactions.html',
        transactions_as_buyer=transactions_as_buyer,
        transactions_as_seller=transactions_as_seller,
        completed_transactions=completed_transactions,
        company_logo_mapping=company_logo_mapping
    )


@transactions_bp.route('/request_to_buy/<int:coupon_id>', methods=['POST'])
@login_required
def request_to_buy(coupon_id):
    """
    שלב 1: בקשה לקנייה (Request to Buy)
    הקונה שולח בקשה למוכר לרכוש את הקופון.
    - כאן בחרנו לא לסמן את הקופון כלא זמין (coupon.is_available = False)
      כדי לאפשר למשתמשים אחרים לשלוח גם הם בקשות קנייה.
    """
    log_user_activity("request_to_buy_attempt", coupon_id)
    current_app.logger.debug(f"Starting request_to_buy with coupon_id: {coupon_id}")

    try:
        coupon = Coupon.query.get_or_404(coupon_id)
        current_app.logger.debug(f"Fetched coupon: {coupon}")

        if coupon.user_id == current_user.id:
            current_app.logger.warning("User attempted to buy their own coupon.")
            flash('אינך יכול לקנות את הקופון שלך.', 'warning')
            return redirect(url_for('transactions.my_transactions'))

        if not coupon.is_for_sale:
            current_app.logger.warning("Coupon is not for sale.")
            flash('קופון זה אינו זמין למכירה.', 'danger')
            return redirect(url_for('transactions.my_transactions'))

        # יצירת טרנזקציה חדשה בסטטוס 'ממתין לאישור המוכר'
        transaction = Transaction(
            coupon_id=coupon.id,
            buyer_id=current_user.id,
            seller_id=coupon.user_id,
            status='ממתין לאישור המוכר'
        )
        db.session.add(transaction)
        current_app.logger.debug(f"Added transaction: {transaction}")

        # ** לא מסמנים כאן את הקופון כלא זמין, כדי לאפשר בקשות נוספות **

        # יצירת התראה למוכר
        notification = Notification(
            user_id=coupon.user_id,
            message=f"{current_user.first_name} {current_user.last_name} מבקש לקנות את הקופון שלך.",
            link=url_for('transactions.my_transactions')
        )
        db.session.add(notification)
        current_app.logger.debug(f"Added notification: {notification}")

        db.session.commit()
        current_app.logger.debug("Committed transaction and notification to the database.")

        # עדכון זמן שליחת הבקשה מהקונה
        transaction.buyer_request_sent_at = datetime.utcnow()
        db.session.commit()
        current_app.logger.debug("Updated transaction.buyer_request_sent_at.")

        # שליחת מייל למוכר
        seller = coupon.user
        buyer = current_user
        try:
            send_coupon_purchase_request_email(seller, buyer, coupon)
            current_app.logger.debug("Sent coupon purchase request email successfully.")
            flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
        except Exception as e:
            current_app.logger.error(f'שגיאה בשליחת מייל למוכר: {e}')
            traceback.print_exc()
            flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

    except Exception as e:
        current_app.logger.error(f"Unhandled exception in request_to_buy: {e}")
        traceback.print_exc()
        flash('אירעה שגיאה בלתי צפויה. נא לנסות שוב.', 'danger')

    return redirect(url_for('transactions.my_transactions'))


@transactions_bp.route('/buy_coupon', methods=['POST'])
@login_required
def buy_coupon():
    """
    שלב 1 (מסלול חלופי): בקשה לקנייה (Request to Buy)
    המשתמש יכול לשלוח בקשה דרך טופס נוסף.
    - גם כאן לא מסמנים את הקופון כלא זמין כדי לאפשר בקשות מקבילות.
    """
    log_user_activity("buy_coupon_attempt", None)
    current_app.logger.debug("Starting buy_coupon process.")

    coupon_id = request.form.get('coupon_id', type=int)
    current_app.logger.debug(f"Received coupon_id from form: {coupon_id}")

    if not coupon_id:
        current_app.logger.warning("No coupon_id provided in form.")
        flash('קופון לא תקין.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    try:
        coupon = Coupon.query.get_or_404(coupon_id)
        current_app.logger.debug(f"Fetched coupon: {coupon}")

        if coupon.user_id == current_user.id:
            current_app.logger.warning("User attempted to buy their own coupon.")
            flash('אינך יכול לקנות את הקופון שלך.', 'warning')
            return redirect(url_for('transactions.my_transactions'))

        if not coupon.is_for_sale:
            current_app.logger.warning("Coupon is not for sale.")
            flash('קופון זה אינו זמין למכירה.', 'danger')
            return redirect(url_for('transactions.my_transactions'))

        # יצירת טרנזקציה חדשה
        transaction = Transaction(
            coupon_id=coupon.id,
            buyer_id=current_user.id,
            seller_id=coupon.user_id,
            status='ממתין לאישור המוכר',
            timestamp=datetime.utcnow()
        )
        db.session.add(transaction)
        current_app.logger.debug(f"Added transaction: {transaction}")

        # ** לא מסמנים coupon.is_available = False **

        # יצירת התראה למוכר
        notification = Notification(
            user_id=coupon.user_id,
            message=f"{current_user.first_name} {current_user.last_name} מבקש לקנות את הקופון שלך.",
            link=url_for('transactions.my_transactions')
        )
        db.session.add(notification)
        current_app.logger.debug(f"Added notification: {notification}")

        try:
            db.session.commit()
            current_app.logger.debug("Committed transaction and notification to the database.")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating transaction: {e}")
            traceback.print_exc()
            flash('אירעה שגיאה בעת יצירת העסקה. נסה שוב מאוחר יותר.', 'danger')
            return redirect(url_for('transactions.my_transactions'))

        # שליחת מייל למוכר
        seller = coupon.user
        buyer = current_user
        current_app.logger.debug(f"Seller: {seller}, Buyer: {buyer}")

        try:
            send_coupon_purchase_request_email(seller, buyer, coupon)
            current_app.logger.debug("Sent coupon purchase request email successfully.")
            flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
        except Exception as e:
            current_app.logger.error(f'שגיאה בשליחת מייל למוכר: {e}')
            traceback.print_exc()
            flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

    except Exception as e:
        current_app.logger.error(f"Unhandled exception in buy_coupon: {e}")
        traceback.print_exc()
        flash('אירעה שגיאה בלתי צפויה. נא לנסות שוב.', 'danger')

    return redirect(url_for('transactions.my_transactions'))


@transactions_bp.route('/approve_transaction/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def approve_transaction(transaction_id):
    """
    שלב 2: אישור המוכר (Seller Approval)
    לאחר שהמוכר מאשר, נשנה את הסטטוס => "ממתין לאישור הקונה שהעסקה בוצעה"
    (ולא 'ממתין לאישור הקונה').
    """
    log_user_activity("approve_transaction_view", transaction_id)
    current_app.logger.debug(f"Starting approve_transaction with transaction_id: {transaction_id}")

    transaction = Transaction.query.get_or_404(transaction_id)
    current_app.logger.debug(f"Fetched transaction: {transaction}")

    if transaction.seller_id != current_user.id:
        current_app.logger.warning("User attempted to approve a transaction they do not own.")
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    form = ApproveTransactionForm()
    if form.validate_on_submit():
        try:
            transaction.seller_phone = form.seller_phone.data
            transaction.seller_approved = True
            transaction.coupon_code_entered = True
            # שינוי סטטוס לשם ברור: "ממתין לאישור הקונה שהעסקה בוצעה"
            transaction.status = 'ממתין לאישור הקונה שהעסקה בוצעה'
            transaction.updated_at = datetime.utcnow()

            db.session.commit()
            current_app.logger.debug("Committed seller approval to the database.")

            flash('אישרת את העסקה בהצלחה! מחכים לאישור הקונה שההעברה בוצעה.', 'success')

            # שליחת מייל לקונה להודיע שהמוכר אישר
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
                current_app.logger.debug("Sent seller approved transaction email successfully.")
            except Exception as e:
                current_app.logger.error(f"Error sending seller_approved_transaction email: {e}")
                flash('האישור נקלט אך לא הצלחנו לשלוח הודעה במייל לקונה.', 'warning')

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error during transaction approval: {e}")
            flash('אירעה שגיאה בעת שמירת השינויים במסד הנתונים.', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error during transaction approval: {e}")
            flash('שגיאה בלתי צפויה התרחשה.', 'danger')

        return redirect(url_for('transactions.my_transactions'))

    return render_template('approve_transaction.html', form=form, transaction=transaction)


@transactions_bp.route('/decline_transaction/<int:transaction_id>')
@login_required
def decline_transaction(transaction_id):
    """
    במקרה שהמוכר מחליט לדחות את העסקה במקום לאשר אותה.
    """
    log_user_activity("decline_transaction_attempt", transaction_id)
    current_app.logger.debug(f"Starting decline_transaction with transaction_id: {transaction_id}")

    transaction = Transaction.query.get_or_404(transaction_id)
    current_app.logger.debug(f"Fetched transaction: {transaction}")

    if transaction.seller_id != current_user.id:
        current_app.logger.warning("User attempted to decline a transaction they do not own.")
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    try:
        coupon = transaction.coupon
        # כאן אפשר להשאיר את הקופון זמין (אם רוצים)
        coupon.is_available = True
        current_app.logger.debug(f"Set coupon.is_available to True for coupon_id: {coupon.id}")

        db.session.delete(transaction)
        current_app.logger.debug(f"Deleted transaction: {transaction}")

        db.session.commit()
        current_app.logger.debug("Committed transaction deletion to the database.")

        flash('דחית את העסקה.', 'info')
        log_user_activity("decline_transaction_success", coupon.id)
        current_app.logger.info("Transaction declined successfully.")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error declining transaction: {e}")
        traceback.print_exc()
        flash('אירעה שגיאה בעת ביטול העסקה.', 'danger')

    return redirect(url_for('transactions.my_transactions'))


@transactions_bp.route('/confirm_transaction/<int:transaction_id>')
@login_required
def confirm_transaction(transaction_id):
    """
    מסלול ישן/לא בשימוש כעת (אם לא דורשים אישור העברה כספית).
    משאירים למקרה שצריך "Confirm" מהקונה ללא שלבי ההעברה.
    """
    log_user_activity("confirm_transaction_attempt", transaction_id)
    current_app.logger.debug(f"Starting confirm_transaction with transaction_id: {transaction_id}")

    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        current_app.logger.warning("User attempted to confirm a transaction they do not own.")
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    try:
        transaction.status = 'הושלם'
        coupon = transaction.coupon
        coupon.user_id = current_user.id
        coupon.is_available = True
        db.session.commit()

        flash('אישרת את העסקה. הקופון הועבר לחשבונך.', 'success')
        log_user_activity("confirm_transaction_success", coupon.id)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error confirming transaction {transaction_id}: {e}")
        traceback.print_exc()
        flash('אירעה שגיאה בעת אישור העסקה.', 'danger')

    return redirect(url_for('transactions.my_transactions'))


@transactions_bp.route('/cancel_transaction/<int:transaction_id>')
@login_required
def cancel_transaction(transaction_id):
    """
    ביטול העסקה ע"י הקונה (אם עדיין בסטטוס המתנה וכדומה).
    """
    log_user_activity("cancel_transaction_attempt", transaction_id)
    current_app.logger.debug(f"Starting cancel_transaction with transaction_id: {transaction_id}")

    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        current_app.logger.warning("User attempted to cancel a transaction they do not own.")
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    try:
        coupon = transaction.coupon
        coupon.is_available = True  # נחזיר את הקופון לזמינות
        current_app.logger.debug(f"Set coupon.is_available to True for coupon_id: {coupon.id}")

        db.session.delete(transaction)
        current_app.logger.debug(f"Deleted transaction: {transaction}")

        db.session.commit()
        current_app.logger.debug("Committed cancellation to the database.")

        flash('ביטלת את העסקה.', 'info')
        log_user_activity("cancel_transaction_success", coupon.id)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error cancelling transaction {transaction_id}: {e}")
        traceback.print_exc()
        flash('אירעה שגיאה בעת ביטול העסקה.', 'danger')

    return redirect(url_for('transactions.my_transactions'))


@transactions_bp.route('/seller_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def seller_confirm_transfer(transaction_id):
    """
    שלב 3 (צד המוכר) לאשר שההעברה התקבלה.
    - לאחר שהמוכר אישר, נסמן seller_confirmed = True.
    - נבדוק אם גם הקונה אישר buyer_confirmed והאם coupon_code_entered == True => נסיים את העסקה.
    """
    transaction = Transaction.query.get_or_404(transaction_id)
    log_user_activity("seller_confirm_transfer_view", transaction.coupon_id)
    current_app.logger.debug(f"Starting seller_confirm_transfer with transaction_id: {transaction_id}")

    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    if request.method == 'POST':
        try:
            transaction.seller_confirmed = True
            transaction.seller_confirmed_at = datetime.utcnow()
            db.session.commit()
            flash('אישרת שההעברה הכספית בוצעה.', 'success')

            seller = transaction.seller
            buyer = transaction.buyer
            coupon = transaction.coupon

            # שליחת מייל לקונה שמודיע שהמוכר אישר את ההעברה
            if buyer and buyer.email:
                html_content = render_template(
                    'emails/seller_confirmed_transfer.html',
                    seller=seller, buyer=buyer, coupon=coupon
                )
                try:
                    send_email(
                        sender_email='itayk93@gmail.com',
                        sender_name='MaCoupon',
                        recipient_email=buyer.email,
                        recipient_name=f'{buyer.first_name} {buyer.last_name}',
                        subject='המוכר אישר שההעברה הכספית בוצעה',
                        html_content=html_content
                    )
                except Exception as e:
                    current_app.logger.error(f"Error sending seller_confirmed_transfer email to buyer: {e}")
                    flash('האישור נקלט אך המייל לא נשלח.', 'warning')

            # בדיקה האם כל התנאים להשלמה:
            # (seller_confirmed + buyer_confirmed + coupon_code_entered)
            if transaction.seller_confirmed and transaction.buyer_confirmed and transaction.coupon_code_entered:
                current_app.logger.debug("All conditions met for completing the transaction.")
                complete_transaction(transaction)
                log_user_activity("seller_confirm_transfer_complete_transaction", transaction.coupon_id)

            return redirect(url_for('transactions.my_transactions'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error during POST in seller_confirm_transfer: {e}")
            traceback.print_exc()
            flash('אירעה שגיאה בעת אישור העסקה. נסה שוב מאוחר יותר.', 'danger')

    return render_template('seller_confirm_transfer.html', transaction=transaction)


@transactions_bp.route('/buyer_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def buyer_confirm_transfer(transaction_id):
    """
    שלב 3 (צד הקונה) לאשר שההעברה הכספית בוצעה.
    - לאחר שהקונה אישר, נסמן buyer_confirmed = True.
    - נבדוק אם גם המוכר אישר seller_confirmed והאם coupon_code_entered == True => נסיים את העסקה.
    """
    log_user_activity("buyer_confirm_transfer_view", transaction_id)
    current_app.logger.debug(f"Starting buyer_confirm_transfer with transaction_id: {transaction_id}")

    try:
        transaction = Transaction.query.get_or_404(transaction_id)
        current_app.logger.debug(f"Fetched transaction: {transaction}")

        if transaction.buyer_id != current_user.id:
            current_app.logger.warning("User attempted to confirm transfer for a transaction they do not own.")
            flash('אין לך הרשאה לפעולה זו.', 'danger')
            return redirect(url_for('transactions.my_transactions'))

        if request.method == 'POST':
            try:
                transaction.buyer_confirmed = True
                transaction.buyer_confirmed_at = datetime.utcnow()
                current_app.logger.debug("Set buyer_confirmed to True and updated timestamp.")
                db.session.commit()
                current_app.logger.debug("Committed buyer confirmation to the database.")

                flash('אישרת שההעברה הכספית בוצעה.', 'success')
                current_app.logger.info("Buyer confirmed transfer successfully.")

                seller = transaction.seller
                buyer = transaction.buyer
                coupon = transaction.coupon
                current_app.logger.debug(f"Seller: {seller}, Buyer: {buyer}, Coupon: {coupon}")

                # שליחת מייל למוכר
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
                        current_app.logger.debug("Sent buyer_confirmed_transfer email successfully.")
                    except Exception as e:
                        current_app.logger.error(f"Error sending buyer_confirmed_transfer email to seller: {e}")
                        flash('האישור נקלט אך המייל למוכר לא נשלח.', 'warning')

                # אם שני הצדדים אישרו + הוזן קוד הקופון (coupon_code_entered ע"י המוכר)
                if transaction.seller_confirmed and transaction.buyer_confirmed and transaction.coupon_code_entered:
                    current_app.logger.debug("All conditions met for completing the transaction.")
                    complete_transaction(transaction)
                    log_user_activity("buyer_confirm_transfer_complete_transaction", transaction.coupon_id)

                return redirect(url_for('transactions.my_transactions'))

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error during POST processing in buyer_confirm_transfer: {e}")
                traceback.print_exc()
                flash('אירעה שגיאה בעת אישור העסקה. נסה שוב מאוחר יותר.', 'danger')

    except Exception as e:
        current_app.logger.error(f"Unhandled exception in buyer_confirm_transfer: {e}")
        traceback.print_exc()
        flash('אירעה שגיאה בלתי צפויה. נא לנסות שוב.', 'danger')

    current_app.logger.debug("Rendering buyer_confirm_transfer template.")
    return render_template('buyer_confirm_transfer.html', transaction=transaction)


@transactions_bp.route('/update_coupon_transactions', methods=['POST'])
@login_required
def update_coupon_transactions():
    """
    דוגמה לקוד שמעדכן טרנזקציות קופון ממקור Multipass (ייתכן שלא בשימוש כרגע).
    """
    log_user_activity("update_coupon_transactions_attempt")

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
            return redirect(url_for('transactions.coupon_detail', id=coupon.id))
        else:
            flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
            return redirect(url_for('transactions.my_transactions'))

    coupon_id = request.form.get('coupon_id')
    coupon_code = request.form.get('coupon_code')
    coupon = None
    if coupon_id:
        coupon = Coupon.query.get(coupon_id)
    elif coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()

    if not coupon:
        flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    df = get_coupon_data(coupon.code)
    if df is not None:
        Transaction.query.filter_by(coupon_id=coupon.id, source='Multipass').delete()
        for index, row in df.iterrows():
            t = Transaction(
                coupon_id=coupon.id,
                card_number=row['card_number'],
                transaction_date=row['transaction_date'],
                location=row['location'],
                recharge_amount=row['recharge_amount'] or 0,
                usage_amount=row['usage_amount'] or 0,
                reference_number=row.get('reference_number', ''),
                source='Multipass'
            )
            db.session.add(t)

        total_used = df['usage_amount'].sum()
        coupon.used_value = total_used
        db.session.commit()

        flash(f'הנתונים עבור הקופון {coupon.code} עודכנו בהצלחה.', 'success')
        log_user_activity("update_coupon_transactions_success", coupon.id)
    else:
        flash(f'אירעה שגיאה בעת עדכון הנתונים עבור הקופון {coupon.code}.', 'danger')

    return redirect(url_for('transactions.coupon_detail', id=coupon.id))


@transactions_bp.route('/mark_coupon_as_fully_used/<int:id>', methods=['POST'])
@login_required
def mark_coupon_as_fully_used(id):
    """
    מסמן קופון כריק לחלוטין (אם אינו חד-פעמי).
    """
    coupon = Coupon.query.get_or_404(id)
    log_user_activity("mark_coupon_as_fully_used_attempt", coupon.id)

    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    if coupon.status != 'פעיל':
        flash('הקופון כבר נוצל או לא פעיל.', 'warning')
        return redirect(url_for('transactions.coupon_detail', id=id))

    if coupon.is_one_time:
        flash('קופון זה הוא חד-פעמי. אנא השתמש בכפתור המתאים לו.', 'warning')
        return redirect(url_for('transactions.coupon_detail', id=id))

    remaining_amount = coupon.value - coupon.used_value
    if remaining_amount <= 0:
        flash('אין ערך נותר בקופון, הוא כבר נוצל במלואו.', 'info')
        return redirect(url_for('transactions.coupon_detail', id=id))

    try:
        coupon.used_value = coupon.value
        update_coupon_status(coupon)

        usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=remaining_amount,
            timestamp=datetime.now(timezone.utc),
            action='נוצל',
            details='הקופון סומן כנוצל לגמרי על ידי המשתמש.'
        )
        db.session.add(usage)

        notification = Notification(
            user_id=coupon.user_id,
            message=f"הקופון {coupon.code} נוצל במלואו.",
            link=url_for('transactions.coupon_detail', id=coupon.id)
        )
        db.session.add(notification)
        db.session.commit()

        flash('הקופון סומן כנוצל לגמרי בהצלחה.', 'success')
        log_user_activity("mark_coupon_as_fully_used_success", coupon.id)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking coupon as fully used: {e}")
        flash('אירעה שגיאה בעת סימון הקופון כנוצל.', 'danger')

    return redirect(url_for('transactions.coupon_detail', id=id))


@transactions_bp.route('/update_coupon/<int:id>', methods=['GET', 'POST'])
@login_required
def update_coupon(id):
    """
    מסך לעדכון כמות השימוש בקופון (אם אינו חד-פעמי).
    """
    coupon = Coupon.query.get_or_404(id)
    log_user_activity("update_coupon_view", coupon.id)

    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לעדכן קופון זה.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    # אם זה קופון חד-פעמי, נסמן אותו כנוצל מיידית
    if coupon.is_one_time:
        coupon.status = "נוצל"
        try:
            db.session.commit()
            flash('סטטוס הקופון עודכן בהצלחה ל"נוצל".', 'success')
            log_user_activity("update_coupon_one_time_marked_used", coupon.id)
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת עדכון סטטוס הקופון.', 'danger')
            logger.error(f"Error updating one-time coupon status: {e}")
        return redirect(url_for('transactions.coupon_detail', id=id))

    form = UpdateCouponUsageForm()
    if form.validate_on_submit():
        new_used_amount = form.used_amount.data
        if new_used_amount < 0:
            flash('כמות השימוש חייבת להיות חיובית.', 'danger')
            return redirect(url_for('transactions.update_coupon_usage', id=id))

        if (coupon.used_value + new_used_amount) > coupon.value:
            flash('הכמות שהשתמשת בה גדולה מערך הקופון הנותר.', 'danger')
            return redirect(url_for('transactions.update_coupon_usage', id=id))

        try:
            coupon.used_value += new_used_amount
            update_coupon_status(coupon)

            usage = CouponUsage(
                coupon_id=coupon.id,
                used_amount=new_used_amount,
                timestamp=datetime.now(timezone.utc),
                action='שימוש',
                details=f'השתמשת ב-{new_used_amount} ש"ח מהקופון.'
            )
            db.session.add(usage)

            notification = Notification(
                user_id=coupon.user_id,
                message=f"השתמשת ב-{new_used_amount} ש״ח בקופון {coupon.code}.",
                link=url_for('transactions.coupon_detail', id=coupon.id)
            )
            db.session.add(notification)

            db.session.commit()

            flash('כמות השימוש עודכנה בהצלחה.', 'success')
            log_user_activity("update_coupon_usage_success", coupon.id)
            return redirect(url_for('transactions.coupon_detail', id=id))
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת עדכון כמות השימוש.', 'danger')
            logger.error(f"Error updating coupon usage: {e}")

    return render_template('update_coupon_usage.html', form=form, coupon=coupon)


@transactions_bp.route('/update_all_coupons')
@login_required
def update_all_coupons():
    """
    דוגמה לפונקציה שמעדכנת בבת-אחת את כל הקופונים הפעילים של המשתמש.
    """
    log_user_activity("update_all_coupons_view")

    active_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.status == 'פעיל'
    ).order_by(Coupon.date_added.desc()).all()

    if not active_coupons:
        flash('אין קופונים פעילים לעדכן.', 'info')
        return redirect(url_for('transactions.my_transactions'))

    updated_coupons = []
    failed_coupons = []

    for coupon in active_coupons:
        pattern = r'^(\d+)-(\d{4})$'
        match = re.match(pattern, coupon.code)
        if match:
            coupon_number_input = match.group(1)
            df = get_coupon_data(coupon_number_input)
            if df is not None and 'שימוש' in df.columns:
                total_used = df['שימוש'].sum()
                if isinstance(total_used, (pd.Series, pd.DataFrame)):
                    total_used = total_used.iloc[0] if not total_used.empty else 0.0
                else:
                    total_used = float(total_used) if not pd.isna(total_used) else 0.0

                coupon.used_value = total_used
                update_coupon_status(coupon)
                db.session.commit()

                data_directory = "multipass/input_html"
                os.makedirs(data_directory, exist_ok=True)
                xlsx_filename = f"coupon_{coupon.code}_{coupon.id}.xlsx"
                xlsx_path = os.path.join(data_directory, xlsx_filename)
                df.to_excel(xlsx_path, index=False)

                updated_coupons.append(coupon.code)
            else:
                failed_coupons.append(coupon.code)
        else:
            failed_coupons.append(coupon.code)

    if updated_coupons:
        flash('הקופונים הבאים עודכנו בהצלחה: ' + ', '.join(updated_coupons), 'success')
        log_user_activity("update_all_coupons_success")
    if failed_coupons:
        flash('הקופונים הבאים לא עודכנו: ' + ', '.join(failed_coupons), 'danger')

    return redirect(url_for('transactions.my_transactions'))


@transactions_bp.route('/complete_transaction/<int:transaction_id>')
@login_required
def complete_transaction_route(transaction_id):
    """
    סימון העסקה כהושלמה ידנית (למנהל או מצב debug).
    """
    transaction = Transaction.query.get_or_404(transaction_id)
    log_user_activity("complete_transaction_route_attempt", transaction.coupon_id)

    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    complete_transaction(transaction)
    flash('העסקה סומנה כהושלמה (באופן ידני).', 'info')
    return redirect(url_for('transactions.my_transactions'))
