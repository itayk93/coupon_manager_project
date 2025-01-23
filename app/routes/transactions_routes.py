from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
import logging
import re
import traceback
from app.models import Coupon, User, Transaction, Notification, CouponRequest, CouponUsage, Tag, Company, db
from app.forms import DeleteCouponRequestForm, ApproveTransactionForm, ConfirmDeleteForm, UpdateCouponUsageForm
from app.helpers import send_coupon_purchase_request_email, send_email, get_coupon_data, update_coupon_status, complete_transaction, get_geo_location
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from app.models import Transaction, db
from app.forms import ApproveTransactionForm
from app.helpers import send_email
import traceback

transactions_bp = Blueprint('transactions', __name__)
logger = logging.getLogger(__name__)
from app.helpers import get_geo_location, get_public_ip

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
    מציג את כל העסקאות של המשתמש הנוכחי, מחולקות ל:
    - עסקאות פעילות (מוכר/קונה) שהסטטוס שלהן לא 'הושלם' ולא 'מבוטל'
    - עסקאות שהסתיימו (הושלמו או בוטלו)
    """

    # עסקאות פעילות של המשתמש כמוכר
    active_seller_transactions = Transaction.query.filter(
        Transaction.seller_id == current_user.id,
        ~Transaction.status.in_(["הושלם", "מבוטל"])
    ).all()

    # עסקאות פעילות של המשתמש כקונה
    active_buyer_transactions = Transaction.query.filter(
        Transaction.buyer_id == current_user.id,
        ~Transaction.status.in_(["הושלם", "מבוטל"])
    ).all()

    # עסקאות שהסתיימו (הושלמו או בוטלו) של המשתמש (כמוכר או כקונה)
    completed_transactions = Transaction.query.filter(
        (Transaction.seller_id == current_user.id) | (Transaction.buyer_id == current_user.id),
        Transaction.status.in_(["הושלם", "מבוטל"])
    ).all()

    # שליפת כל החברות לצורך לוגו
    companies = Company.query.all()
    company_logo_mapping = {c.name.lower(): c.image_path for c in companies}

    # שליפת בקשות למשתמש הנוכחי כמבקש
    coupon_requests = CouponRequest.query.filter_by(user_id=current_user.id).all()

    # שליפת קופונים של המשתמש הנוכחי
    user_coupons = Coupon.query.filter_by(user_id=current_user.id).all()

    # יצירת מיפוי עבור שם חברה לנתיב לוגו (באותיות קטנות)
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}

    return render_template(
        'my_transactions.html',
        transactions_as_seller=active_seller_transactions,
        transactions_as_buyer=active_buyer_transactions,
        completed_transactions=completed_transactions,
        coupon_requests=coupon_requests,
        user_coupons=user_coupons,
        company_logo_mapping=company_logo_mapping
    )


@transactions_bp.route('/buy_coupon', methods=['POST'])
@login_required
def buy_coupon():
    """
    רוטה לטיפול בבקשת קנייה של קופון.
    """
    coupon_id = request.form.get('coupon_id', type=int)
    if not coupon_id:
        flash('קופון לא תקין.', 'danger')
        return redirect(url_for('marketplace'))

    coupon = Coupon.query.get_or_404(coupon_id)

    # בדיקת אם המשתמש מנסה לקנות את הקופון שלו
    if coupon.user_id == current_user.id:
        flash('אינך יכול לקנות את הקופון שלך.', 'warning')
        return redirect(url_for('marketplace'))

    # בדיקת זמינות הקופון למכירה
    if not coupon.is_available or not coupon.is_for_sale:
        flash('קופון זה אינו זמין למכירה.', 'danger')
        return redirect(url_for('marketplace'))

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
        link=url_for('transactions.my_transactions')
    )
    db.session.add(notification)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating transaction: {e}")
        flash('אירעה שגיאה בעת יצירת העסקה. נסה שוב מאוחר יותר.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    # שליחת מייל למוכר באמצעות הפונקציה הנפרדת
    seller = coupon.user
    buyer = current_user
    try:
        send_coupon_purchase_request_email(seller, buyer, coupon)
        flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
    except Exception as e:
        logging.error(f'שגיאה בשליחת מייל למוכר: {e}')
        flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

    return redirect(url_for('transactions.my_transactions'))


@transactions_bp.route('/approve_transaction/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def approve_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    form = ApproveTransactionForm()
    current_app.logger.debug(f"Request method: {request.method}")
    current_app.logger.debug(f"Form data: {form.data}")
    current_app.logger.debug(f"Form errors: {form.errors}")
    if form.validate_on_submit():
        current_app.logger.debug("Form validated successfully")
        try:
            # עדכון פרטי המוכר והסטטוס
            try:
                transaction.seller_phone = form.seller_phone.data
                transaction.seller_approved = True
                transaction.status = 'ממתין לאישור הקונה'  # שינוי סטטוס

                db.session.commit()

                # לוג לבדיקה לאחר commit
                updated_transaction = Transaction.query.get(transaction_id)
                current_app.logger.debug(f"Updated transaction {transaction_id} status: {updated_transaction.status}")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating transaction {transaction_id}: {e}")

            # לוג לעדכון מוצלח
            current_app.logger.info(f"Transaction {transaction_id} updated to 'ממתין לאישור הקונה'")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating transaction {transaction_id}: {e}")
            flash('אירעה שגיאה בעדכון העסקה.', 'danger')
            return redirect(url_for('transactions.my_transactions'))

        # שליחת מייל לקונה
        seller = transaction.seller
        buyer = transaction.buyer
        coupon = transaction.coupon

        html_content = render_template('emails/seller_approved_transaction.html',
                                       seller=seller, buyer=buyer, coupon=coupon)

        try:
            send_email(
                sender_email='CouponMasterIL2@gmail.com',
                sender_name='Coupon Master',
                recipient_email=buyer.email,
                recipient_name=f'{buyer.first_name} {buyer.last_name}',
                subject='המוכר אישר את העסקה',
                html_content=html_content
            )
            flash('אישרת את העסקה והמייל נשלח לקונה בהצלחה.', 'success')
        except Exception as e:
            current_app.logger.error(f"Error sending email for transaction {transaction_id}: {e}")
            flash('העסקה אושרה, אך לא הצלחנו לשלוח מייל לקונה.', 'warning')

        return redirect(url_for('transactions.my_transactions'))
    else:
        current_app.logger.debug("Form validation failed")

    return render_template('approve_transaction.html', form=form, transaction=transaction)


@transactions_bp.route('/decline_transaction/<int:transaction_id>')
@login_required
def decline_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    # החזרת הקופון לזמינות
    coupon = transaction.coupon
    coupon.is_available = True
    db.session.delete(transaction)
    db.session.commit()
    flash('דחית את העסקה.', 'info')
    return redirect(url_for('transactions.my_transactions'))

@transactions_bp.route('/confirm_transaction/<int:transaction_id>')
@login_required
def confirm_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    transaction.status = 'הושלם'
    # העברת הבעלות על הקופון
    coupon = transaction.coupon
    coupon.user_id = current_user.id
    coupon.is_available = True
    db.session.commit()
    flash('אישרת את העסקה. הקופון הועבר לחשבונך.', 'success')
    return redirect(url_for('transactions_.my_transactions'))


@transactions_bp.route('/cancel_transaction/<int:transaction_id>')
@login_required
def cancel_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    # החזרת הקופון לזמינות
    coupon = transaction.coupon
    coupon.is_available = True
    db.session.delete(transaction)
    db.session.commit()
    flash('ביטלת את העסקה.', 'info')
    return redirect(url_for('transactions.my_transactions'))







@transactions_bp.route('/mark_coupon_as_fully_used/<int:id>', methods=['POST'])
@login_required
def mark_coupon_as_fully_used(id):
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
        flash('אין יתרה לניצול בקופון, הוא כבר נוצל במלואו.', 'info')
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
    coupon = Coupon.query.get_or_404(id)
    log_user_activity("update_coupon_view", coupon.id)

    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לעדכן קופון זה.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

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

                data_directory = "automatic_coupon_update/input_html"
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
    transaction = Transaction.query.get_or_404(transaction_id)
    log_user_activity("complete_transaction_route_attempt", transaction.coupon_id)

    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    complete_transaction(transaction)
    flash('העסקה סומנה כהושלמה (באופן ידני).', 'info')
    return redirect(url_for('transactions.my_transactions'))


@transactions_bp.route('/seller_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def seller_confirm_transfer(transaction_id):
    """
    המוכר מאשר סופית שהכסף התקבל.
    פעולה זו תסיים את העסקה, תעביר את הקופון לקונה ותסמן את הטרנזקציה כהושלמה.
    כמו כן, נשלח מייל למוכר עצמו כדי להודיע שהעסקה הסתיימה.
    """
    transaction = Transaction.query.get_or_404(transaction_id)
    log_user_activity("seller_confirm_transfer_view", transaction.coupon_id)

    # וידוא שהמשתמש הנוכחי הוא אכן המוכר
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    if request.method == 'POST':
        # המוכר אישר שהכסף התקבל
        transaction.seller_confirmed = True
        transaction.seller_confirmed_at = datetime.utcnow()

        # סימון העסקה כ"הושלמה"
        transaction.status = 'הושלם'

        # העברת בעלות על הקופון לקונה
        coupon = transaction.coupon
        buyer = transaction.buyer
        seller = transaction.seller

        coupon.user_id = buyer.id
        coupon.is_for_sale = False  # "רגיל"
        coupon.is_available = True  # הקופון פעיל בשימוש הקונה

        try:
            db.session.commit()
            flash('העסקה הושלמה. הקופון הועבר לבעלות הקונה.', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error completing transaction {transaction_id}: {e}")
            flash('אירעה שגיאה בעת סימון העסקה כהושלמה.', 'danger')
            return redirect(url_for('transactions.my_transactions'))

        # 1. שליחת מייל לקונה (אופציונלי, אם קיים כבר)
        if buyer and buyer.email:
            html_content_buyer = render_template(
                'emails/seller_confirmed_transfer.html',  # תבנית שכבר יש לך
                seller=seller,
                buyer=buyer,
                coupon=coupon
            )
            try:
                send_email(
                    sender_email='CouponMasterIL2@gmail.com',
                    sender_name='Coupon Master',
                    recipient_email=buyer.email,
                    recipient_name=f'{buyer.first_name} {buyer.last_name}',
                    subject='המוכר אישר את קבלת התשלום והעסקה הושלמה',
                    html_content=html_content_buyer
                )
            except Exception as e:
                current_app.logger.error(f"Error sending seller_confirmed_transfer email to buyer: {e}")
                flash('העסקה הושלמה אך לא הצלחנו לשלוח מייל לקונה.', 'warning')

        # 2. שליחת מייל למוכר עצמו – "העסקה הסתיימה"
        if seller and seller.email:
            html_content_seller = render_template(
                'emails/transaction_completed_seller.html',  # תבנית חדשה (ראה למטה)
                seller=seller,
                buyer=buyer,
                coupon=coupon
            )
            try:
                send_email(
                    sender_email='CouponMasterIL2@gmail.com',
                    sender_name='Coupon Master',
                    recipient_email=seller.email,
                    recipient_name=f'{seller.first_name} {seller.last_name}',
                    subject='העסקה הסתיימה בהצלחה',
                    html_content=html_content_seller
                )
            except Exception as e:
                current_app.logger.error(f"Error sending transaction_completed_seller email: {e}")
                flash('העסקה הושלמה אך לא הצלחנו לשלוח מייל למוכר.', 'warning')

        return redirect(url_for('transactions.my_transactions'))

    # בקשת GET (או שגיאה) => הצגת הטופס
    return render_template('seller_confirm_transfer.html', transaction=transaction)


@transactions_bp.route('/buyer_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def buyer_confirm_transfer(transaction_id):
    """
    הקונה מאשר את העברת הכסף למוכר.
    לאחר האישור:
    - מעדכנים את השדה buyer_confirmed ל-True ואת buyer_confirmed_at עם התאריך הנוכחי.
    - הסטטוס נשמר כערך קצר יותר במקום הטקסט המלא (למשל 'buyer_confirmed') כדי למנוע חריגת אורך בעמודה status.
    - נשלח מייל למוכר.
    - חוזרים ל-my_transactions בסיום.
    """
    log_user_activity("buyer_confirm_transfer_view", transaction_id)
    current_app.logger.debug(f"Starting buyer_confirm_transfer with transaction_id: {transaction_id}")

    try:
        transaction = Transaction.query.get_or_404(transaction_id)
        current_app.logger.debug(f"Fetched transaction: {transaction}")

        # בדיקה שהמשתמש הנוכחי הוא אכן הקונה
        if transaction.buyer_id != current_user.id:
            current_app.logger.warning("User attempted to confirm transfer for a transaction they do not own.")
            flash('אין לך הרשאה לפעולה זו.', 'danger')
            return redirect(url_for('transactions.my_transactions'))

        # אם הבקשה היא POST, מבצעים את האישור
        if request.method == 'POST':
            try:
                # סימון שהקונה אישר
                transaction.buyer_confirmed = True
                transaction.buyer_confirmed_at = datetime.utcnow()

                # שמירת סטטוס קצר כדי לא לחרוג מהמגבלה של ה-DB
                transaction.status = "buyer_confirmed"
                # אפשר כמובן לבחור מילה אחרת, למשל: "buyer_confirmed_waiting_seller"
                # העיקר שהיא תהיה קצרה מספיק עבור העמודה בעייתית.

                db.session.commit()  # ניסיון לשמור את השינויים במסד הנתונים

                flash('אישרת שההעברה הכספית בוצעה.', 'success')
                current_app.logger.info("Buyer confirmed transfer successfully.")

                # שליחת מייל למוכר
                seller = transaction.seller
                buyer = transaction.buyer
                coupon = transaction.coupon
                current_app.logger.debug(f"Seller: {seller}, Buyer: {buyer}, Coupon: {coupon}")

                if seller and seller.email:
                    try:
                        html_content = render_template(
                            'emails/buyer_confirmed_transfer.html',
                            seller=seller, buyer=buyer, coupon=coupon
                        )
                        send_email(
                            sender_email='CouponMasterIL2@gmail.com',
                            sender_name='Coupon Master',
                            recipient_email=seller.email,
                            recipient_name=f'{seller.first_name} {seller.last_name}',
                            subject='הקונה אישר שההעברה הכספית בוצעה',
                            html_content=html_content
                        )
                        current_app.logger.debug("Sent buyer_confirmed_transfer email successfully.")
                    except Exception as e:
                        current_app.logger.error(f"Error sending buyer_confirmed_transfer email to seller: {e}")
                        flash('האישור נקלט אך המייל למוכר לא נשלח.', 'warning')

                # בסיום, חזרה לרשימת העסקאות
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

    # אם זו בקשת GET או שהייתה שגיאה, מציגים את התבנית buyer_confirm_transfer.html
    current_app.logger.debug("Rendering buyer_confirm_transfer template.")
    return render_template('buyer_confirm_transfer.html', transaction=transaction)

@transactions_bp.route('/buy_coupon_direct')
@login_required
def buy_coupon_direct():
    """
    הקונה לוחץ על "לרכישה" במייל שקיבל.
    נוצרת Transaction, נשלחת למוכר התראה ומייל.
    כמו כן, אם יש בקשת קופון שהביאה להצעה הזאת - נסמן אותה כ-fulfilled.
    """
    log_user_activity("buy_coupon_direct_attempt")

    coupon_id = request.args.get('coupon_id', type=int)
    if not coupon_id:
        flash('לא זוהה קופון לרכישה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    coupon = Coupon.query.get_or_404(coupon_id)
    if not coupon.is_for_sale or not coupon.is_available:
        flash('קופון זה אינו זמין יותר למכירה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    if coupon.user_id == current_user.id:
        flash('לא ניתן לקנות קופון של עצמך.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    new_transaction = Transaction(
        coupon_id=coupon.id,
        buyer_id=current_user.id,
        seller_id=coupon.user_id,
        status='ממתין לאישור המוכר',
    )
    db.session.add(new_transaction)

    coupon.is_available = False
    db.session.commit()

    # כעת צריך למצוא אם קיימת בקשת קופון רלוונטית => נסמן fulfilled
    # נניח הגענו מהצעה שקישרה בין coupon_request.id->coupon.
    # בפועל אין ID ישיר, אבל אפשר לזהות לפי user_id + company (או לשמור reference).
    # להלן דוגמה:
    coupon_request = CouponRequest.query.filter_by(
        user_id=current_user.id,
        company=coupon.company,
        fulfilled=False
    ).first()
    if coupon_request:
        coupon_request.fulfilled = True
        db.session.commit()

    # שליחת נוטיפיקציה למוכר
    seller_notification = Notification(
        user_id=coupon.user_id,
        message=f"{current_user.first_name} {current_user.last_name} מעוניין לרכוש את הקופון שלך.",
        link=url_for('transactions.my_transactions')
    )
    db.session.add(seller_notification)
    db.session.commit()

    # שליחת מייל למוכר
    try:
        seller = User.query.get(coupon.user_id)
        buyer = current_user
        subject = "יש לך קונה חדש!"
        html_content = render_template(
            'emails/seller_new_buyer.html',
            seller=seller,
            buyer=buyer,
            coupon=coupon,
            transaction=new_transaction
        )

        send_email(
            sender_email='CouponMasterIL2@gmail.com',
            sender_name='Coupon Master',
            recipient_email=seller.email,
            recipient_name=f"{seller.first_name} {seller.last_name}",
            subject=subject,
            html_content=html_content
        )
        current_app.logger.info(f"[DEBUG] email sent to seller {seller.email} about new buyer")
    except Exception as e:
        current_app.logger.error(f"[ERROR] sending email to seller: {e}")
        flash('נוצרה העסקה, אך לא הצלחנו לשלוח מייל למוכר.', 'warning')

    flash('נוצרה בקשת רכישה. על המוכר לאשר זאת.', 'success')
    return redirect(url_for('transactions.my_transactions'))
