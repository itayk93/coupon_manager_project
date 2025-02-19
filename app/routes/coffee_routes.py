# app/routes/coffee_routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from datetime import datetime
from app.extensions import db
from app.models_coffee import CoffeeOffer, CoffeeTransaction, CoffeeReview

coffee_bp = Blueprint('coffee', __name__, url_prefix='/coffee')

@coffee_bp.route('/')
@login_required
def index():
    """דף הבית של מודול הקפה – מציג את כל ההצעות."""
    offers = CoffeeOffer.query.order_by(CoffeeOffer.expiration_date.desc()).all()
    return render_template('coffee/index.html', offers=offers,now=datetime.utcnow().date())

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models_coffee import CoffeeOffer
from app.forms import CoffeeOfferForm  # Ensure the form is imported

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.forms import CoffeeOfferForm  # Import the form
@coffee_bp.route('/offer', methods=['GET', 'POST'], endpoint='offer_form')
@login_required
def create_offer():
    """
    Handles the creation of a coffee discount offer.

    Users can create an offer as either a seller (offering a discount) or a buyer (requesting a discount).
    The form validates user input and, upon success, saves the offer to the database.

    Returns:
        - Renders `offer_form.html` for GET requests.
        - Processes the form submission and redirects to the index page for POST requests.
    """

    form = CoffeeOfferForm()  # יצירת מופע של הטופס

    if request.method == 'POST':
        # ✅ הדפסת נתוני הטופס לניפוי שגיאות
        print("🔍 Raw form data:", request.form)

        if form.validate_on_submit():
            print("✅ Form validation successful!")

            # ✅ קבלת סוג ההצעה ובדיקת תקינות
            offer_type = form.offer_type.data
            print("📌 Offer Type:", offer_type)

            # ✅ עיבוד ערך `desired_discount`
            desired_discount = request.form.get("desired_discount")
            if offer_type == 'buy' and desired_discount is not None:
                try:
                    desired_discount = float(desired_discount)  # המרת מחרוזת למספר
                except ValueError:
                    desired_discount = None  # במקרה של שגיאה בהמרה

            # ✅ יצירת מופע של CoffeeOffer ושמירה ל-DB
            new_offer = CoffeeOffer(
                user_id=current_user.id,  # שיוך ההצעה למשתמש הנוכחי
                discount_percent=form.discount_percent.data if offer_type == 'sell' else None,
                customer_group=form.customer_group.data if offer_type == 'sell' else None,
                points_offered=form.points_offered.data if offer_type == 'sell' else None,
                desired_discount=desired_discount if offer_type == 'buy' else None,
                buyer_description=form.buyer_description.data if offer_type == 'buy' else None,
                offer_type=offer_type,
                is_buy_offer=(offer_type == 'buy'),
                description=form.description.data,
                expiration_date=form.expiration_date.data,
            )

            # ✅ הדפסת נתוני ההצעה לפני שמירה
            print("📝 Saving to DB:", new_offer.__dict__)

            # ✅ שמירת ההצעה בבסיס הנתונים
            db.session.add(new_offer)
            db.session.commit()

            flash("✅ ההצעה נשמרה בהצלחה!", "success")
            return redirect(url_for('coffee.index'))
        else:
            print("❌ Form validation failed!")
            print("Errors:", form.errors)
            flash("⚠️ לא הצלחנו לשמור את ההצעה. בדוק שהזנת את כל הנתונים הנדרשים.", "danger")

    return render_template('coffee/offer_form.html', form=form)


@coffee_bp.route('/offers', endpoint='list_offers')
@login_required
def list_offers():
    """מציג את רשימת כל הצעות הקפה הקיימות."""
    offers = CoffeeOffer.query.order_by(CoffeeOffer.expiration_date.desc()).all()
    return render_template('coffee/offer_list.html', offers=offers, now=datetime.utcnow().date())

@coffee_bp.route('/offer/<int:offer_id>')
@login_required
def offer_detail(offer_id):
    """מציג את פרטי הצעת הקפה. אם המשתמש אינו המוכר – יוצג לו כפתור לרכוש."""
    offer = CoffeeOffer.query.get_or_404(offer_id)
    return render_template('coffee/offer_detail.html', offer=offer,now=datetime.utcnow().date())

@coffee_bp.route('/transaction/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def transaction_detail(transaction_id):
    """
    מציג את פרטי העסקה.
    במידה והעסקה עדיין לא הושלמה – הקונה יכול לעדכן את המחירים (לפני ואחרי ההנחה) ולסמן את העסקה כ"ושלמה".
    """
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)
    if current_user.id not in [transaction.buyer_id, transaction.seller_id]:
        flash("אין לך הרשאה לעסקה זו.", "danger")
        return redirect(url_for('coffee.index'))
    if request.method == 'POST':
        try:
            negotiated_price_before = float(request.form.get('negotiated_price_before'))
            negotiated_price_after = float(request.form.get('negotiated_price_after'))
        except (TypeError, ValueError):
            flash("יש להזין מחירים תקינים.", "danger")
            return redirect(url_for('coffee.transaction_detail', transaction_id=transaction_id))
        transaction.negotiated_price_before = negotiated_price_before
        transaction.negotiated_price_after = negotiated_price_after
        transaction.status = 'completed'
        db.session.commit()
        flash("העסקה הושלמה.", "success")
        return redirect(url_for('coffee.transaction_detail', transaction_id=transaction_id))
    return render_template('coffee/transaction_detail.html', transaction=transaction)

@coffee_bp.route('/review/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def review_seller(transaction_id):
    """
    מאפשר לקונה להשאיר ביקורת על המוכר לאחר השלמת העסקה.
    """
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)
    if current_user.id != transaction.buyer_id:
        flash("אינך מורשה להשאיר ביקורת על עסקה זו.", "danger")
        return redirect(url_for('coffee.index'))
    # בדיקה אם כבר נכתבה ביקורת עבור עסקה זו
    existing_review = CoffeeReview.query.filter_by(transaction_id=transaction.id, reviewer_id=current_user.id).first()
    if existing_review:
        flash("כבר השארת ביקורת על עסקה זו.", "info")
        return redirect(url_for('coffee.transaction_detail', transaction_id=transaction.id))
    if request.method == 'POST':
        try:
            rating = int(request.form.get('rating'))
        except (TypeError, ValueError):
            flash("יש להזין דירוג תקין (מספר בין 1 ל-5).", "danger")
            return redirect(url_for('coffee.review_seller', transaction_id=transaction.id))
        comment = request.form.get('comment')
        new_review = CoffeeReview(
            transaction_id=transaction.id,
            reviewer_id=current_user.id,
            rating=rating,
            comment=comment
        )
        db.session.add(new_review)
        db.session.commit()
        flash("תודה! הביקורת נשמרה.", "success")
        return redirect(url_for('coffee.transaction_detail', transaction_id=transaction.id))
    return render_template('coffee/review.html', transaction=transaction)

# app/routes/coffee_transactions_routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from datetime import datetime
import traceback
from app.extensions import db
from app.models import Notification, User
from app.models_coffee import CoffeeOffer, CoffeeTransaction
from app.forms import ApproveTransactionForm, SellerAddCouponCodeForm  # יש להגדיר טפסים אלו
from app.helpers import send_email, get_geo_location
import logging


# ----------------------------
# 1. קנייה של הצעת קפה (יצירת עסקה)
# ----------------------------
@coffee_bp.route('/buy_offer', methods=['POST'])
@login_required
def buy_offer():
    """
    הקונה מבקש לרכוש את הצעת הקפה.
    נוודא שההצעה זמינה ושלא מנסים לקנות את ההצעה של עצמם.
    ניצור עסקה (CoffeeTransaction), נסמן את ההצעה כלא זמינה,
    ונשלח התראה ומייל למוכר.
    """
    offer_id = request.form.get('offer_id', type=int)
    if not offer_id:
        flash('הצעה לא תקינה.', 'danger')
        return redirect(url_for('coffee.index'))
    offer = CoffeeOffer.query.get_or_404(offer_id)
    if offer.user_id == current_user.id:
        flash('אינך יכול לרכוש את ההצעה שלך.', 'warning')
        return redirect(url_for('coffee.index'))
    if not offer.is_available or not offer.is_for_sale:
        flash('ההצעה אינה זמינה לרכישה.', 'danger')
        return redirect(url_for('coffee.index'))

    transaction = CoffeeTransaction(
        offer_id=offer.id,
        buyer_id=current_user.id,
        seller_id=offer.user_id,
        status='ממתין לאישור המוכר',
        created_at=datetime.utcnow()
    )
    db.session.add(transaction)
    offer.is_available = False

    # יצירת התראה למוכר
    notification = Notification(
        user_id=offer.user_id,
        message=f"{current_user.first_name} {current_user.last_name} מבקש לרכוש את הצעת הקפה שלך.",
        link=url_for('coffee.my_transactions')
    )
    db.session.add(notification)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating transaction: {e}")
        flash('אירעה שגיאה ביצירת העסקה. נסה שוב מאוחר יותר.', 'danger')
        return redirect(url_for('coffee.index'))

    # שליחת מייל למוכר
    seller = User.query.get(offer.user_id)
    buyer = current_user
    try:
        send_email(
            sender_email='noreply@couponmasteril.com',
            sender_name='מערכת הנחות קפה',
            recipient_email=seller.email,
            recipient_name=f"{seller.first_name} {seller.last_name}",
            subject="בקשת רכישה להצעת קפה",
            html_content=render_template('emails/seller_new_buyer_coffee.html',
                                          seller=seller, buyer=buyer, offer=offer)
        )
        flash('בקשת הרכישה נשלחה והמוכר יקבל מייל.', 'success')
    except Exception as e:
        current_app.logger.error(f"Error sending email to seller: {e}")
        flash('העסקה נוצרה אך לא הצלחנו לשלוח מייל למוכר.', 'warning')
    return redirect(url_for('coffee.my_transactions'))

# ----------------------------
# 2. אישור עסקה – המוכר מאשר את העסקה (עדכון פרטי העסקה)
# ----------------------------
@coffee_bp.route('/approve_transaction/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def approve_transaction(transaction_id):
    """
    עמוד שבו המוכר מאשר עסקה.
    על המוכר להזין, למשל, טלפון לצורך קשר או להשלים פרטים במידת הצורך.
    לאחר העדכון, העיסקה משנה סטטוס ל"ממתין לאישור הקונה".
    """
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coffee.my_transactions'))
    form = ApproveTransactionForm()  # טופס לאישור עסקה – יש להגדיר אותו במודולי הטפסים
    if request.method == "POST":
        if form.validate_on_submit():
            try:
                transaction.seller_phone = form.seller_phone.data
                transaction.seller_approved = True
                transaction.status = 'ממתין לאישור הקונה'
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error approving transaction: {e}")
                flash('אירעה שגיאה בעדכון העסקה.', 'danger')
                return redirect(url_for('coffee.my_transactions'))

            # שליחת מייל לקונה
            seller = current_user
            buyer = User.query.get(transaction.buyer_id)
            offer = transaction.offer
            try:
                send_email(
                    sender_email='noreply@couponmasteril.com',
                    sender_name='מערכת הנחות קפה',
                    recipient_email=buyer.email,
                    recipient_name=f"{buyer.first_name} {buyer.last_name}",
                    subject="המוכר אישר את העסקה",
                    html_content=render_template('emails/seller_approved_transaction_coffee.html',
                                                  seller=seller, buyer=buyer, offer=offer)
                )
            except Exception as e:
                current_app.logger.error(f"Error sending email to buyer: {e}")
                flash('העסקה עודכנה אך לא נשלח מייל לקונה.', 'warning')
            flash('העסקה עודכנה בהצלחה. המייל נשלח לקונה.', 'success')
            return redirect(url_for('coffee.my_transactions'))
        else:
            flash('יש לתקן את השגיאות בטופס.', 'danger')
    return render_template('approve_transaction_coffee.html', form=form, transaction=transaction)

# ----------------------------
# 3. אישור העברה – המוכר מאשר שהכסף התקבל
# ----------------------------
@coffee_bp.route('/seller_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def seller_confirm_transfer(transaction_id):
    """
    עמוד שבו המוכר מאשר שסופקה העברת כספים.
    בעת אישור – מתבצעת העברת בעלות על ההצעה לקונה, העיסקה מסומנת כ"הושלמה" ונשלח מייל.
    """
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coffee.my_transactions'))
    if request.method == 'POST':
        try:
            transaction.seller_confirmed = True
            transaction.seller_confirmed_at = datetime.utcnow()
            transaction.status = 'הושלם'
            offer = transaction.offer
            # העברת בעלות – הקופון עובר לבעלות הקונה
            offer.user_id = transaction.buyer_id
            offer.is_available = True
            db.session.commit()
            flash('העסקה הושלמה. ההצעה הועברה לקונה.', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error in seller confirm transfer: {e}")
            flash('אירעה שגיאה בעת אישור העסקה.', 'danger')
        return redirect(url_for('coffee.my_transactions'))
    return render_template('seller_confirm_transfer_coffee.html', transaction=transaction)

# ----------------------------
# 4. אישור העברה – הקונה מאשר שהעברת הכסף בוצעה
# ----------------------------
@coffee_bp.route('/buyer_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def buyer_confirm_transfer(transaction_id):
    """
    עמוד שבו הקונה מאשר שהעברת הכסף בוצעה.
    עם אישור הקונה, העיסקה מעדכנת את סטטוס 'buyer_confirmed' ונשלח מייל למוכר.
    """
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coffee.my_transactions'))
    if request.method == 'POST':
        try:
            transaction.buyer_confirmed = True
            transaction.buyer_confirmed_at = datetime.utcnow()
            transaction.status = 'buyer_confirmed'
            db.session.commit()
            flash('אישרת את העסקה. המייל נשלח למוכר.', 'success')
            # שליחת מייל למוכר
            seller = User.query.get(transaction.seller_id)
            buyer = current_user
            offer = transaction.offer
            send_email(
                sender_email='noreply@couponmasteril.com',
                sender_name='מערכת הנחות קפה',
                recipient_email=seller.email,
                recipient_name=f"{seller.first_name} {seller.last_name}",
                subject="הקונה אישר את העסקה",
                html_content=render_template('emails/buyer_confirmed_transfer_coffee.html',
                                              seller=seller, buyer=buyer, offer=offer)
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error in buyer confirm transfer: {e}")
            flash('אירעה שגיאה בעת אישור העסקה.', 'danger')
        return redirect(url_for('coffee.my_transactions'))
    return render_template('buyer_confirm_transfer_coffee.html', transaction=transaction)

# ----------------------------
# 5. רכישה ישירה (דרך קישור במייל)
# ----------------------------
@coffee_bp.route('/buy_offer_direct')
@login_required
def buy_offer_direct():
    """
    הקונה לוחץ על קישור במייל כדי לרכוש הצעה.
    נוצרת עסקה, ההצעה מסומנת כלא זמינה, והתראה נשלחת למוכר.
    """
    offer_id = request.args.get('offer_id', type=int)
    if not offer_id:
        flash('לא זוהתה הצעה לרכישה.', 'danger')
        return redirect(url_for('coffee.index'))
    offer = CoffeeOffer.query.get_or_404(offer_id)
    if not offer.is_for_sale or not offer.is_available:
        flash('ההצעה אינה זמינה יותר.', 'danger')
        return redirect(url_for('coffee.index'))
    if offer.user_id == current_user.id:
        flash('לא ניתן לרכוש את ההצעה שלך.', 'danger')
        return redirect(url_for('coffee.index'))
    transaction = CoffeeTransaction(
        offer_id=offer.id,
        buyer_id=current_user.id,
        seller_id=offer.user_id,
        status='ממתין לאישור המוכר',
        created_at=datetime.utcnow()
    )
    db.session.add(transaction)
    offer.is_available = False
    db.session.commit()

    # יצירת התראה למוכר
    notification = Notification(
        user_id=offer.user_id,
        message=f"{current_user.first_name} {current_user.last_name} מעוניין לרכוש את ההצעה שלך.",
        link=url_for('coffee.my_transactions')
    )
    db.session.add(notification)
    db.session.commit()

    # שליחת מייל למוכר
    try:
        seller = User.query.get(offer.user_id)
        send_email(
            sender_email='noreply@couponmasteril.com',
            sender_name='מערכת הנחות קפה',
            recipient_email=seller.email,
            recipient_name=f"{seller.first_name} {seller.last_name}",
            subject="יש לך קונה חדש להצעת קפה",
            html_content=render_template('emails/seller_new_buyer_coffee.html',
                                          seller=seller, buyer=current_user, offer=offer)
        )
    except Exception as e:
        current_app.logger.error(f"Error sending email: {e}")
        flash('העסקה נוצרה אך לא נשלח מייל למוכר.', 'warning')

    flash('בקשת הרכישה נוצרה. המוכר יקבל הודעה במייל.', 'success')
    return redirect(url_for('coffee.my_transactions'))

# ----------------------------
# 6. עמוד העסקאות שלי (למכירה וקניה של הצעות קפה)
# ----------------------------
@coffee_bp.route('/my_transactions')
@login_required
def my_transactions():
    """
    מציג את כל העסקאות הקשורות להצעות הקפה של המשתמש (כמוכר וכקונה).
    """
    transactions = CoffeeTransaction.query.filter(
        (CoffeeTransaction.seller_id == current_user.id) | (CoffeeTransaction.buyer_id == current_user.id)
    ).order_by(CoffeeTransaction.created_at.desc()).all()
    return render_template('my_transactions_coffee.html', transactions=transactions)
