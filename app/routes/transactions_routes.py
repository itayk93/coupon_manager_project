# transactions_routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from app.models import Coupon, User, Transaction, Notification, CouponRequest, CouponUsage, Tag, Company
from app.forms import DeleteCouponRequestForm, ApproveTransactionForm, ConfirmDeleteForm, UpdateCouponUsageForm
from app.helpers import send_coupon_purchase_request_email, send_email, get_coupon_data
from app.extensions import db
import logging
from datetime import datetime, timezone
import re

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Transaction
from app.helpers import send_email, complete_transaction
from datetime import datetime

transactions_bp = Blueprint('transactions', __name__)

logger = logging.getLogger(__name__)


@transactions_bp.route('/my_transactions')
@login_required
def my_transactions():
    transactions_as_buyer = Transaction.query.filter_by(buyer_id=current_user.id).all()
    transactions_as_seller = Transaction.query.filter_by(seller_id=current_user.id).all()

    # שליפת כל החברות
    companies = Company.query.all()
    # יצירת מיפוי שם חברה -> נתיב תמונה (באות קטנות)
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}

    return render_template(
        'my_transactions.html',
        transactions_as_buyer=transactions_as_buyer,
        transactions_as_seller=transactions_as_seller,
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
        return redirect(url_for('transactions.marketplace'))

    coupon = Coupon.query.get_or_404(coupon_id)

    # בדיקת אם המשתמש מנסה לקנות את הקופון שלו
    if coupon.user_id == current_user.id:
        flash('אינך יכול לקנות את הקופון שלך.', 'warning')
        return redirect(url_for('transactions.marketplace'))

    # בדיקת זמינות הקופון למכירה
    if not coupon.is_available or not coupon.is_for_sale:
        flash('קופון זה אינו זמין למכירה.', 'danger')
        return redirect(url_for('transactions.marketplace'))

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
        logger.error(f"Error creating transaction: {e}")
        flash('אירעה שגיאה בעת יצירת העסקה. נסה שוב מאוחר יותר.', 'danger')
        return redirect(url_for('transactions.marketplace'))

    # שליחת מייל למוכר באמצעות הפונקציה הנפרדת
    seller = coupon.user
    buyer = current_user
    try:
        send_coupon_purchase_request_email(seller, buyer, coupon)
        flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
    except Exception as e:
        logger.error(f'שגיאה בשליחת מייל למוכר: {e}')
        flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

    return redirect(url_for('transactions.my_transactions'))

@transactions_bp.route('/request_to_buy/<int:coupon_id>', methods=['POST'])
@login_required
def request_to_buy(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    if coupon.user_id == current_user.id:
        flash('אינך יכול לקנות את הקופון של עצמך.', 'warning')
        return redirect(url_for('transactions.marketplace'))

    if not coupon.is_available or not coupon.is_for_sale:
        flash('קופון זה אינו זמין למכירה.', 'danger')
        return redirect(url_for('transactions.marketplace'))

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

    return redirect(url_for('transactions.my_transactions'))

@transactions_bp.route('/approve_transaction/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def approve_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    form = ApproveTransactionForm()
    if form.validate_on_submit():
        transaction.seller_phone = form.seller_phone.data
        transaction.seller_approved = True
        transaction.coupon_code_entered = True
        db.session.commit()

        # לאחר שהמוכר אישר את העסקה, נשלח מייל לקונה
        seller = transaction.seller
        buyer = transaction.buyer
        coupon = transaction.coupon

        html_content = render_template('emails/seller_approved_transaction.html',
                                       seller=seller, buyer=buyer, coupon=coupon)

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

        return redirect(url_for('transactions.my_transactions'))

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
    return redirect(url_for('transactions.my_transactions'))

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

@transactions_bp.route('/update_coupon_transactions', methods=['POST'])
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
            return redirect(url_for('transactions.coupon_detail', id=coupon.id))
        else:
            flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
            return redirect(url_for('transactions.show_coupons'))

    # קבלת הנתונים מהטופס
    coupon_id = request.form.get('coupon_id')
    coupon_code = request.form.get('coupon_code')
    print(f"coupon_id: {coupon_id}, coupon_code: {coupon_code}")

    coupon = None
    if coupon_id:
        coupon = Coupon.query.get(coupon_id)
    elif coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()

    if not coupon:
        flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
        return redirect(url_for('transactions.show_coupons'))

    # קבלת הנתונים ועדכון העסקאות
    df = get_coupon_data(coupon.code)
    if df is not None:
        # מחיקת עסקאות קודמות שהגיעו מ-Multipass בלבד
        Transaction.query.filter_by(coupon_id=coupon.id, source='Multipass').delete()

        # הוספת עסקאות חדשות
        for index, row in df.iterrows():
            transaction = Transaction(
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

    return redirect(url_for('transactions.coupon_detail', id=coupon.id))

@transactions_bp.route('/mark_coupon_as_fully_used/<int:id>', methods=['POST'])
@login_required
def mark_coupon_as_fully_used(id):
    coupon = Coupon.query.get_or_404(id)

    # בדיקת הרשאה
    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('transactions.show_coupons'))

    # בדיקה אם הקופון כבר נוצל או לא פעיל
    if coupon.status != 'פעיל':
        flash('הקופון כבר נוצל או לא פעיל.', 'warning')
        return redirect(url_for('transactions.coupon_detail', id=id))

    # בדיקה אם הקופון הוא לא חד-פעמי (כי לחד-פעמי כבר יש רוטה אחרת)
    if coupon.is_one_time:
        flash('קופון זה הוא חד-פעמי. אנא השתמש בכפתור המתאים לו.', 'warning')
        return redirect(url_for('transactions.coupon_detail', id=id))

    # מחשבים כמה עוד נותר להשתמש
    remaining_amount = coupon.value - coupon.used_value
    if remaining_amount <= 0:
        flash('אין ערך נותר בקופון, הוא כבר נוצל במלואו.', 'info')
        return redirect(url_for('transactions.coupon_detail', id=id))

    # ביצוע העדכון
    try:
        # עדכון הערך הנוצל
        coupon.used_value = coupon.value
        update_coupon_status(coupon)  # יעדכן את הסטטוס ל"נוצל"

        # יצירת רשומת שימוש
        usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=remaining_amount,
            timestamp=datetime.now(timezone.utc),
            action='נוצל',
            details='הקופון סומן כנוצל לגמרי על ידי המשתמש.'
        )
        db.session.add(usage)

        # יצירת התראה למשתמש
        notification = Notification(
            user_id=coupon.user_id,
            message=f"הקופון {coupon.code} נוצל במלואו.",
            link=url_for('transactions.coupon_detail', id=coupon.id)
        )
        db.session.add(notification)

        db.session.commit()
        flash('הקופון סומן כנוצל לגמרי בהצלחה.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking coupon as fully used: {e}")
        flash('אירעה שגיאה בעת סימון הקופון כנוצל.', 'danger')

    return redirect(url_for('transactions.coupon_detail', id=id))

@transactions_bp.route('/update_coupon/<int:id>', methods=['GET', 'POST'])
@login_required
def update_coupon(id):
    coupon = Coupon.query.get_or_404(id)

    # בדיקת הרשאות
    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לעדכן קופון זה.', 'danger')
        return redirect(url_for('transactions.show_coupons'))

    # בדיקת אם הקופון הוא חד-פעמי
    if coupon.is_one_time:
        coupon.status = "נוצל"
        try:
            db.session.commit()
            flash('סטטוס הקופון עודכן בהצלחה ל"נוצל".', 'success')
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
            # עדכון כמות השימוש
            coupon.used_value += new_used_amount
            update_coupon_status(coupon)

            # יצירת רשומת שימוש חדשה
            usage = CouponUsage(
                coupon_id=coupon.id,
                used_amount=new_used_amount,
                timestamp=datetime.now(timezone.utc),
                action='שימוש',
                details=f'השתמשת ב-{new_used_amount} ש"ח מהקופון.'
            )
            db.session.add(usage)

            # יצירת התראה למשתמש
            notification = Notification(
                user_id=coupon.user_id,
                message=f"השתמשת ב-{new_used_amount} ש״ח בקופון {coupon.code}.",
                link=url_for('transactions.coupon_detail', id=coupon.id)
            )
            db.session.add(notification)

            db.session.commit()
            flash('כמות השימוש עודכנה בהצלחה.', 'success')
            return redirect(url_for('transactions.coupon_detail', id=id))
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת עדכון כמות השימוש.', 'danger')
            logger.error(f"Error updating coupon usage: {e}")

    return render_template('update_coupon_usage.html', form=form, coupon=coupon)

@transactions_bp.route('/update_all_coupons')
@login_required
def update_all_coupons():
    # קבלת כל הקופונים הפעילים של המשתמש הנוכחי שאינם נוצלו עד הסוף
    active_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.status == 'פעיל'
    ).order_by(Coupon.date_added.desc()).all()

    if not active_coupons:
        flash('אין קופונים פעילים לעדכן.', 'info')
        return redirect(url_for('transactions.show_coupons'))

    updated_coupons = []
    failed_coupons = []

    for coupon in active_coupons:
        # בדיקת פורמט הקוד
        pattern = r'^(\d+)-(\d{4})$'
        match = re.match(pattern, coupon.code)
        if match:
            coupon_number_input = match.group(1)
            # קריאת הפונקציה לקבלת הנתונים
            df = get_coupon_data(coupon_number_input)
            if df is not None and 'שימוש' in df.columns:
                # עדכון השדה used_value עם סך 'שימוש'
                total_used = df['שימוש'].sum()
                if isinstance(total_used, (pd.Series, pd.DataFrame)):
                    # אם total_used הוא Series, קבל את הערך הבודד
                    total_used = total_used.iloc[0] if not total_used.empty else 0.0
                else:
                    total_used = float(total_used) if not pd.isna(total_used) else 0.0

                # עדכון הערך החדש
                coupon.used_value = total_used
                update_coupon_status(coupon)

                db.session.commit()

                # שמירת ה-DataFrame כקובץ xlsx
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

    # הצגת הודעות למשתמש
    if updated_coupons:
        flash('הקופונים הבאים עודכנו בהצלחה: ' + ', '.join(updated_coupons), 'success')
    if failed_coupons:
        flash('הקופונים הבאים לא עודכנו: ' + ', '.join(failed_coupons), 'danger')

    return redirect(url_for('transactions.show_coupons'))

@transactions_bp.route('/complete_transaction/<int:transaction_id>')
@login_required
def complete_transaction_route(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))
    complete_transaction(transaction)
    return redirect(url_for('transactions.my_transactions'))

@transactions_bp.route('/seller_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def seller_confirm_transfer(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    if request.method == 'POST':
        transaction.seller_confirmed = True
        transaction.seller_confirmed_at = datetime.utcnow()
        db.session.commit()
        flash('אישרת שההעברה הכספית בוצעה.', 'success')

        seller = transaction.seller
        buyer = transaction.buyer
        coupon = transaction.coupon
        if buyer and buyer.email:
            html_content = render_template('emails/seller_confirmed_transfer.html',
                                           seller=seller, buyer=buyer, coupon=coupon)
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
                print(f"Error sending seller_confirmed_transfer email: {e}")
                flash('האישור נקלט אך המייל לא נשלח.', 'warning')

        if transaction.seller_confirmed and transaction.buyer_confirmed and transaction.coupon_code_entered:
            complete_transaction(transaction)

        return redirect(url_for('transactions.my_transactions'))

    return render_template('seller_confirm_transfer.html', transaction=transaction)


@transactions_bp.route('/buyer_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def buyer_confirm_transfer(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    if request.method == 'POST':
        transaction.buyer_confirmed = True
        transaction.buyer_confirmed_at = datetime.utcnow()
        db.session.commit()
        flash('אישרת שההעברה הכספית בוצעה.', 'success')

        seller = transaction.seller
        buyer = transaction.buyer
        coupon = transaction.coupon
        if seller and seller.email:
            html_content = render_template('emails/buyer_confirmed_transfer.html',
                                           seller=seller, buyer=buyer, coupon=coupon)
            try:
                send_email(
                    sender_email='itayk93@gmail.com',
                    sender_name='MaCoupon',
                    recipient_email=seller.email,
                    recipient_name=f'{seller.first_name} {seller.last_name}',
                    subject='הקונה אישר שההעברה הכספית בוצעה',
                    html_content=html_content
                )
            except Exception as e:
                print(f"Error sending buyer_confirmed_transfer email: {e}")
                flash('האישור נקלט אך המייל לא נשלח.', 'warning')

        if transaction.seller_confirmed and transaction.buyer_confirmed and transaction.coupon_code_entered:
            complete_transaction(transaction)

        return redirect(url_for('transactions.my_transactions'))

    return render_template('buyer_confirm_transfer.html', transaction=transaction)
