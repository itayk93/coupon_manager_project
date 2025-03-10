# app/routes/coffee_routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from datetime import datetime
from app.extensions import db
from app.models_coffee import CoffeeOffer, CoffeeTransaction, CoffeeReview
import traceback
from app.forms import ConfirmTransferForm

coffee_bp = Blueprint('coffee', __name__, url_prefix='/coffee')

@coffee_bp.route('/')
@login_required
def index():
    """דף הבית של מודול הקפה – מציג את כל ההצעות."""
    offers = CoffeeOffer.query.order_by(CoffeeOffer.expiration_date.desc()).all()
    return render_template('coffee/index.html', offers=offers, now=datetime.utcnow().date())

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models_coffee import CoffeeOffer
from app.forms import CoffeeOfferForm,ConfirmTransferForm  # Ensure the form is imported

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
            discount_percent = form.discount_percent.data
            if discount_percent is None:
                discount_percent = 0  # מונע שגיאות של NULL במסד הנתונים
            if offer_type == 'sell':
                if discount_percent is None or discount_percent == '':
                    discount_percent = 0  # ברירת מחדל למוכר אם לא הוזן כלום
            elif offer_type == 'buy':
                discount_percent = None  # הצעות קנייה לא צריכות ערך הנחה

            # עדכון הנתונים לאובייקט ההצעה
            new_offer = CoffeeOffer(
                user_id=current_user.id,
                customer_group=form.customer_group.data if offer_type == 'sell' else None,
                points_offered=form.points_offered.data if offer_type == 'sell' else None,
                desired_discount=desired_discount if offer_type == 'buy' else None,
                buyer_description=form.buyer_description.data if offer_type == 'buy' else None,
                offer_type=offer_type,
                is_buy_offer=(offer_type == 'buy'),
                discount_percent=discount_percent,  # עדכון נכון של ההנחה
                description=form.description.data,
                expiration_date=form.expiration_date.data,
            )

            print(f"📌 discount_percent לפני שמירה: {discount_percent}")

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
    from app.forms import DeleteOfferForm
    form = DeleteOfferForm()
    return render_template('coffee/offer_detail.html', offer=offer, now=datetime.utcnow().date(), form=form)

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

from app.models import UserReview
from app.forms import ReviewSellerForm
@coffee_bp.route('/review/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def review_seller(transaction_id):
    """
    מאפשר לקונה להשאיר ביקורת על המוכר, נשמר בטבלת user_reviews בעמודה coffee_transaction.
    """
    # שליפת העסקה מטבלת transactions (או coffee_transaction)
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)

    # וידוא שהמשתמש הנוכחי הוא הקונה בעסקה
    if current_user.id != transaction.buyer_id:
        flash("אינך מורשה להשאיר ביקורת על עסקה זו.", "danger")
        return redirect(url_for('coffee.index'))

    # בדיקה אם כבר קיימת ביקורת
    existing_review = UserReview.query.filter_by(
        reviewer_id=current_user.id,
        reviewed_user_id=transaction.seller_id,
        coffee_transaction=transaction.id
    ).first()
    if existing_review:
        flash("כבר השארת ביקורת על עסקה זו.", "info")
        return redirect(url_for('coffee.my_transactions'))

    # טופס ביקורת
    form = ReviewSellerForm()
    if form.validate_on_submit():
        try:
            new_review = UserReview(
                reviewer_id=current_user.id,
                reviewed_user_id=transaction.seller_id,
                coffee_transaction=transaction.id,  # ← שדה חדש במקום transaction_id
                rating=form.rating.data,
                comment=form.comment.data
            )
            db.session.add(new_review)
            db.session.commit()
            flash("תודה! הביקורת נשמרה.", "success")
            return redirect(url_for('coffee.my_transactions'))

        except Exception as e:
            db.session.rollback()
            flash("אירעה שגיאה בעת שמירת הביקורת.", "danger")
            return redirect(url_for('coffee.my_transactions'))
    else:
        if request.method == 'POST':
            print("Form errors:", form.errors)
            flash("יש לתקן את השגיאות בטופס.", "danger")

    return render_template('coffee/review.html', form=form, transaction=transaction)

@coffee_bp.route('/offer/edit/<int:offer_id>', methods=['GET', 'POST'], endpoint='edit_offer')
@login_required
def edit_offer(offer_id):
    """מאפשר למוכר לערוך את הצעת הקפה שלו."""
    offer = CoffeeOffer.query.get_or_404(offer_id)
    if offer.user_id != current_user.id:
        flash("אין לך הרשאה לערוך הצעה זו.", "danger")
        return redirect(url_for('coffee.index'))
    
    form = CoffeeOfferForm(obj=offer)
    
    if form.validate_on_submit():
        form.populate_obj(offer)
        db.session.commit()
        flash("ההצעה עודכנה בהצלחה!", "success")
        return redirect(url_for('coffee.offer_detail', offer_id=offer.id))

    return render_template('coffee/edit_offer.html', form=form, offer=offer)


from flask_wtf import FlaskForm
from wtforms import HiddenField
from app.helpers import send_email
from app.models import User
from app.forms import CancelTransactionForm


@coffee_bp.route('/cancel_transaction/<int:transaction_id>', methods=['POST'])
@login_required
def cancel_transaction(transaction_id):
    """
    מאפשר לבטל עסקה במצב שממתין (לא הושלמה)
    ומחזיר את מצב ההצעה למה שהיה לפני תחילת העסקה.
    שולח מייל לצד השני (המוכר/הקונה) שהעסקה בוטלה.
    """
    form = CancelTransactionForm()
    # validate_on_submit יבצע אימות CSRF
    if not form.validate_on_submit():
        flash("בקשת הביטול נכשלה עקב שגיאת אבטחה. נסה שוב.", "danger")
        return redirect(url_for('coffee.my_transactions'))

    transaction = CoffeeTransaction.query.get_or_404(transaction_id)
    
    # בדיקה שהמשתמש הוא הקונה או המוכר
    if current_user.id not in [transaction.buyer_id, transaction.seller_id]:
        flash("אין לך הרשאה לבטל עסקה זו.", "danger")
        return redirect(url_for('coffee.my_transactions'))
    
    # אם העסקה כבר הושלמה, לא ניתן לבטל אותה
    if transaction.status in ['completed', 'buyer_confirmed']:
        flash("לא ניתן לבטל עסקה שהושלמה.", "danger")
        return redirect(url_for('coffee.my_transactions'))
    
    try:
        # החזרת ההצעה למצב זמין
        transaction.offer.is_available = True
        
        # שמירת נתונים כדי שנוכל להשתמש בהם אחר כך
        seller_user = User.query.get(transaction.seller_id)
        buyer_user  = User.query.get(transaction.buyer_id)

        # מחיקת העסקה
        db.session.delete(transaction)
        db.session.commit()

        flash("העסקה בוטלה והמצב הוחזר למצב המקורי.", "success")

        # ---------------------
        # שליחת מייל לצד השני
        # ---------------------
        # נקבע האם הנוכחי הוא המוכר
        is_seller = (current_user.id == seller_user.id)

        # המשתמש הנגדי (צד שני בעסקה)
        if is_seller:
            other_user = buyer_user
        else:
            other_user = seller_user

        # נניח שנגדיר "coupon" = dict עם company = תיאור ההצעה
        coupon = {
            'company': transaction.offer.description if transaction.offer.description else "קופון"
        }

        # שליחת מייל עם התבנית
        send_email(
            sender_email='noreply@couponmasteril.com',
            sender_name='מערכת הנחות קפה',
            recipient_email=other_user.email,
            recipient_name=f"{other_user.first_name} {other_user.last_name}",
            subject="העסקה בוטלה",
            html_content=render_template(
                'emails/coffee/seller_canceled_transaction.html',
                seller=seller_user,
                buyer=buyer_user,
                coupon=coupon,
                is_seller=is_seller  # מאפשר בתוך התבנית לדעת מי ביטל
            )
        )
    except Exception as e:
        db.session.rollback()
        flash("אירעה שגיאה בעת ביטול העסקה או שליחת המייל.", "danger")

    return redirect(url_for('coffee.my_transactions'))

@coffee_bp.route('/offer/delete/<int:offer_id>', methods=['POST'], endpoint='delete_offer')
@login_required
def delete_offer(offer_id):
    """
    מאפשר למשתמש למחוק את ההצעה שיצר.
    אם המשתמש אינו הבעלים של ההצעה, לא תתבצע המחיקה.
    """
    offer = CoffeeOffer.query.get_or_404(offer_id)
    if offer.user_id != current_user.id:
        flash("אין לך הרשאה למחוק הצעה זו.", "danger")
        return redirect(url_for('coffee.index'))
    try:
        db.session.delete(offer)
        db.session.commit()
        flash("ההצעה נמחקה בהצלחה.", "success")
    except Exception as e:
        db.session.rollback()
        flash("אירעה שגיאה בעת מחיקת ההצעה.", "danger")
    return redirect(url_for('coffee.index'))

@coffee_bp.route('/offer/confirm_delete/<int:offer_id>', methods=['GET', 'POST'], endpoint='confirm_delete_offer')
@login_required
def confirm_delete_offer(offer_id):
    """
    מציג דף אישור למחיקת הצעת קפה.
    אם המשתמש מאשר (POST), ההצעה נמחקת.
    """
    offer = CoffeeOffer.query.get_or_404(offer_id)
    if offer.user_id != current_user.id:
        flash("אין לך הרשאה למחוק הצעה זו.", "danger")
        return redirect(url_for('coffee.index'))

    from app.forms import DeleteOfferForm
    form = DeleteOfferForm()
    if form.validate_on_submit():
        try:
            db.session.delete(offer)
            db.session.commit()
            flash("ההצעה נמחקה בהצלחה.", "success")
        except Exception as e:
            db.session.rollback()
            flash("אירעה שגיאה בעת מחיקת ההצעה.", "danger")
        return redirect(url_for('coffee.index'))

    # GET request – הצגת טופס אישור מחיקה
    return render_template('coffee/confirm_delete_offer.html', offer=offer, form=form)

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

    print("✅ [buy_offer] הפונקציה הופעלה!")

    # 🛠️ בדיקת נתוני הבקשה שהתקבלו
    print(f"📌 [buy_offer] נתוני הבקשה שהתקבלו: {request.form}")

    offer_id = request.form.get('offer_id', type=int)
    if not offer_id:
        flash('⚠️ הצעה לא תקינה.', 'danger')
        print("❌ [buy_offer] שגיאה: offer_id לא התקבל כראוי")
        return redirect(url_for('coffee.index'))

    # 🔍 שליפת ההצעה מה-DB
    offer = CoffeeOffer.query.get(offer_id)
    if not offer:
        flash('⚠️ ההצעה אינה קיימת.', 'danger')
        print(f"❌ [buy_offer] שגיאה: לא נמצאה הצעה עם ID {offer_id}")
        return redirect(url_for('coffee.index'))
    
    print(f"✅ [buy_offer] נמצאה הצעה: ID {offer.id}, is_available={offer.is_available}, is_for_sale={offer.is_for_sale}, user_id={offer.user_id}")

    # ❌ בדיקה אם המשתמש מנסה לקנות את ההצעה של עצמו
    if offer.user_id == current_user.id:
        flash('⚠️ אינך יכול לרכוש את ההצעה שלך.', 'warning')
        print(f"🚨 [buy_offer] שגיאה: המשתמש {current_user.id} מנסה לרכוש את ההצעה של עצמו {offer.id}")
        return redirect(url_for('coffee.index'))

    # ❌ בדיקה אם ההצעה לא זמינה לרכישה
    if not offer.is_available or not offer.is_for_sale:
        flash('⚠️ ההצעה אינה זמינה לרכישה.', 'danger')
        print(f"🚨 [buy_offer] שגיאה: ההצעה אינה זמינה - is_available={offer.is_available}, is_for_sale={offer.is_for_sale}")
        return redirect(url_for('coffee.index'))

    # 🔎 בדיקה אם יש כבר עסקה פתוחה להצעה זו
    existing_transaction = CoffeeTransaction.query.filter_by(offer_id=offer.id, status="ממתין לאישור המוכר").first()
    if existing_transaction:
        flash('⚠️ הצעה זו כבר נמצאת בתהליך רכישה.', 'danger')
        print(f"🚨 [buy_offer] שגיאה: קיימת כבר עסקה פתוחה להצעה {offer.id}, Transaction ID: {existing_transaction.id}")
        return redirect(url_for('coffee.index'))

    # ✅ יצירת מופע של עסקה חדשה
    transaction = CoffeeTransaction(
        offer_id=offer.id,
        buyer_id=current_user.id,
        seller_id=offer.user_id,
        status='ממתין לאישור המוכר',
        created_at=datetime.utcnow()
    )

    print(f"📝 [buy_offer] לפני שמירה: {transaction.__dict__}")

    # ✅ שמירת העסקה במסד הנתונים
    db.session.add(transaction)
    
    # ❗ סימון ההצעה כלא זמינה
    offer.is_available = False
    print(f"📝 [buy_offer] סימון ההצעה {offer.id} כלא זמינה (is_available=False)")

    # ✅ יצירת התראה למוכר
    notification = Notification(
        user_id=offer.user_id,
        message=f"{current_user.first_name} {current_user.last_name} מבקש לרכוש את הצעת הקפה שלך.",
        link=url_for('coffee.my_transactions')
    )
    db.session.add(notification)

    # 🔄 ניסיון לשמור את השינויים בבסיס הנתונים
    try:
        db.session.commit()
        print(f"✅ [buy_offer] העסקה נוצרה בהצלחה! Transaction ID: {transaction.id}")

        # 🔎 בדיקה אם העסקה נשמרה באמת
        test_transaction = CoffeeTransaction.query.filter_by(id=transaction.id).first()
        if test_transaction:
            print(f"✅ [buy_offer] העסקה קיימת ב-DB עם ID {test_transaction.id}")
        else:
            print(f"❌ [buy_offer] WARNING: העסקה לא קיימת ב-DB אחרי commit!")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"❌ [buy_offer] Error creating transaction: {e}")
        import traceback
        print(f"❌ [buy_offer] שגיאה בעת שמירת העסקה:\n{traceback.format_exc()}")
        flash('⚠️ אירעה שגיאה ביצירת העסקה. נסה שוב מאוחר יותר.', 'danger')
        return redirect(url_for('coffee.index'))

    # ✅ שליחת מייל למוכר
    seller = User.query.get(offer.user_id)
    buyer = current_user
    try:
        send_email(
            sender_email='noreply@couponmasteril.com',
            sender_name='מערכת הנחות קפה',
            recipient_email=seller.email,
            recipient_name=f"{seller.first_name} {seller.last_name}",
            subject="בקשת רכישה להצעת קפה",
            html_content=render_template('emails/coffee/seller_new_buyer_coffee.html',
                                          seller=seller, buyer=buyer, offer=offer)
        )
        flash('✅ בקשת הרכישה נשלחה והמוכר יקבל מייל.', 'success')
        print(f"📧 [buy_offer] מייל נשלח למוכר {seller.email}")
    except Exception as e:
        current_app.logger.error(f"❌ [buy_offer] Error sending email to seller: {e}")
        print(f"❌ [buy_offer] שגיאה בשליחת מייל למוכר: {e}")
        flash('⚠️ העסקה נוצרה אך לא הצלחנו לשלוח מייל למוכר.', 'warning')

    return redirect(url_for('coffee.my_transactions'))

# ----------------------------
# 2. אישור עסקה – המוכר מאשר את העסקה (עדכון פרטי העסקה)
# ----------------------------
from app.forms import ApproveCoffeeTransactionForm  # עדכון ייבוא לטופס החדש

@coffee_bp.route('/approve_transaction/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def approve_transaction(transaction_id):
    """
    עמוד שבו המוכר מאשר עסקה ומזין את מספר הטלפון לשליחה לקונה.
    אם כבר קיים מספר טלפון בהצעה, המשתמש לא יכול לעדכן אותו מחדש.
    לאחר העדכון, העסקה משנה סטטוס ל"ממתין לאישור הקונה" ונשלח מייל לקונה.
    """
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)
    offer = transaction.offer  # שולפים את ההצעה המקושרת

    # בודקים שהמוכר הוא המשתמש הנוכחי
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coffee.my_transactions'))

    # אם כבר הוגדר טלפון בהצעה, אי אפשר להזין שוב
    if offer.seller_phone:
        flash(f"נתת כבר את הטלפון שלך: {offer.seller_phone}", "info")
        return redirect(url_for('coffee.my_transactions'))

    form = ApproveCoffeeTransactionForm()
    if request.method == "POST" and form.validate_on_submit():
        try:
            # כאן מעדכנים את עמודת seller_phone בהצעה
            offer.seller_phone = form.seller_phone.data
            transaction.seller_approved = True
            transaction.status = 'ממתין לאישור הקונה'
            db.session.commit()

            flash("העסקה עודכנה בהצלחה. מספר הטלפון נשלח לקונה.", "success")

            # שליחת מייל לקונה
            seller = current_user
            buyer = User.query.get(transaction.buyer_id)
            send_email(
                sender_email='noreply@couponmasteril.com',
                sender_name='מערכת הנחות קפה',
                recipient_email=buyer.email,
                recipient_name=f"{buyer.first_name} {buyer.last_name}",
                subject="המוכר אישר את העסקה ושלח את מספר הטלפון שלו",
                html_content=render_template(
                    'emails/coffee/seller_approved_transaction_coffee.html',
                    seller=seller,
                    buyer=buyer,
                    offer=offer
                )
            )

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error approving transaction: {e}")
            flash('אירעה שגיאה בעדכון העסקה.', 'danger')

        return redirect(url_for('coffee.my_transactions'))

    else:
        if request.method == "POST":
            # הדפסת שגיאות הטופס
            print("Form errors:", form.errors)
            flash('יש לתקן את השגיאות בטופס.', 'danger')

    return render_template('coffee/approve_transaction_coffee.html',
                           form=form, transaction=transaction)

# ----------------------------
# 3. אישור העברה – המוכר מאשר שהכסף התקבל
# ----------------------------
@coffee_bp.route('/seller_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def seller_confirm_transfer(transaction_id):
    """
    עמוד שבו המוכר מאשר שסופקה העברת כספים.
    בעת אישור – מתבצעת העברת בעלות על ההצעה לקונה, העסקה מסומנת כ"הושלמה" ונשלח מייל.
    """
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coffee.my_transactions'))

    form = ConfirmTransferForm()  # ✅ יצירת מופע של הטופס

    if form.validate_on_submit():  # ✅ בדיקת הטופס במקום request.method == 'POST'
        try:
            transaction.seller_confirmed = True
            transaction.seller_confirmed_at = datetime.utcnow()
            transaction.status = 'הושלם'
            offer = transaction.offer

            # ✅ העברת בעלות – הקופון עובר לקונה
            offer.user_id = transaction.buyer_id
            offer.is_available = True

            db.session.commit()
            flash('העסקה הושלמה. ההצעה הועברה לקונה.', 'success')

            # ✅ שליחת מייל למוכר
            seller = current_user
            buyer = User.query.get(transaction.buyer_id)
            send_email(
                sender_email='noreply@couponmasteril.com',
                sender_name='מערכת הנחות קפה',
                recipient_email=buyer.email,
                recipient_name=f"{buyer.first_name} {buyer.last_name}",
                subject="המוכר אישר את העסקה",
                html_content=render_template('coffee/seller_confirm_transfer_coffee.html',
                                              seller=seller, buyer=buyer, offer=offer, form=form)
            )

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"❌ שגיאה בעת אישור העסקה: {e}")
            print(traceback.print_exc())
            flash('אירעה שגיאה בעת אישור העסקה.', 'danger')

        return redirect(url_for('coffee.my_transactions'))

    return render_template('coffee/seller_confirm_transfer_coffee.html', transaction=transaction, form=form)

# ----------------------------
# 4. אישור העברה – הקונה מאשר שהעברת הכסף בוצעה
# ----------------------------
@coffee_bp.route('/buyer_confirm_transfer/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def buyer_confirm_transfer(transaction_id):
    """
    עמוד שבו הקונה מאשר שהעברת הכסף בוצעה.
    עם אישור הקונה, העסקה מתעדכנת ונשלח מייל למוכר.
    """
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)

    # בדיקה שהמשתמש הנוכחי הוא הקונה
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('coffee.my_transactions'))

    form = ConfirmTransferForm()  # יצירת מופע של הטופס

    if form.validate_on_submit():
        try:
            # עדכון הסטטוס של העסקה
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
                html_content=render_template('emails/coffee/buyer_confirmed_transfer_coffee.html',
                                              seller=seller, buyer=buyer, offer=offer)
            )

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"❌ שגיאה בעת אישור העסקה: {e}")
            flash('אירעה שגיאה בעת אישור העסקה.', 'danger')

        return redirect(url_for('coffee.my_transactions'))

    return render_template('coffee/buyer_confirm_transfer_coffee.html', transaction=transaction, form=form)

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
            html_content=render_template('emails/coffee/seller_new_buyer_coffee.html',
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
        (CoffeeTransaction.seller_id == current_user.id) |
        (CoffeeTransaction.buyer_id == current_user.id)
    ).order_by(CoffeeTransaction.created_at.desc()).all()

    form = CancelTransactionForm()

    # ייבוא טבלת הביקורות
    from app.models import UserReview

    # בדיקה עבור כל עסקה אם כבר קיימת ביקורת
    for tx in transactions:
        tx.has_review = False
        # אם המשתמש הנוכחי הוא הקונה, נחפש ביקורת מתאימה
        if tx.buyer_id == current_user.id:
            existing_review = UserReview.query.filter_by(
                reviewer_id=current_user.id,
                reviewed_user_id=tx.seller_id,
                coffee_transaction=tx.id
            ).first()
            if existing_review:
                tx.has_review = True

    return render_template('coffee/my_transactions_coffee.html',
                           transactions=transactions,
                           form=form)

# ----------------------------
# 7. סיום העסקה
# ----------------------------
@coffee_bp.route('/finalize_transaction/<int:transaction_id>', methods=['POST'], endpoint='finalize_transaction')
@login_required
def finalize_transaction(transaction_id):
    """
    Allows the seller to finalize the transaction once the buyer has confirmed.
    On success, the transaction status is set to 'completed' (or 'הושלם'), 
    an email is sent to the buyer using the provided email template, and no action buttons
    will be displayed in the transactions view.
    """
    transaction = CoffeeTransaction.query.get_or_404(transaction_id)
    
    # Only the seller can finalize the transaction.
    if current_user.id != transaction.seller_id:
        flash("אין לך הרשאה לסיים את העסקה.", "danger")
        return redirect(url_for('coffee.my_transactions'))
    
    # Ensure that the buyer has confirmed the transfer.
    if not transaction.buyer_confirmed:
        flash("הקונה עדיין לא אישר את העסקה.", "warning")
        return redirect(url_for('coffee.my_transactions'))
    
    try:
        # Finalize the transaction
        transaction.status = 'completed'  # or 'הושלם'
        transaction.seller_confirmed = True
        transaction.seller_confirmed_at = datetime.utcnow()
        db.session.commit()
        flash("העסקה הושלמה בהצלחה.", "success")
        
        # Send an email to the buyer to notify that the seller has finalized the transaction.
        seller = current_user
        buyer = User.query.get(transaction.buyer_id)
        send_email(
            sender_email='noreply@couponmasteril.com',
            sender_name='מערכת הנחות קפה',
            recipient_email=buyer.email,
            recipient_name=f"{buyer.first_name} {buyer.last_name}",
            subject="המוכר אישר את העסקה",
            html_content=render_template(
                'emails/coffee/seller_approved_transaction_coffee.html',
                seller=seller,
                buyer=buyer,
                offer=transaction.offer
            )
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error finalizing transaction: {e}")
        flash("אירעה שגיאה בעת סיום העסקה.", "danger")
    
    return redirect(url_for('coffee.my_transactions'))


# 8. Delete Review (for the buyer)
@coffee_bp.route('/review/delete/<int:transaction_id>', methods=['POST'])
@login_required
def delete_review(transaction_id):
    """
    Allows the buyer to delete their review for the given coffee transaction.
    The review is identified by the current user (reviewer) and the coffee_transaction field.
    """
    review = UserReview.query.filter_by(
        reviewer_id=current_user.id,
        coffee_transaction=transaction_id
    ).first()
    if not review:
        flash("ביקורת לא נמצאה לעסקה זו.", "warning")
        return redirect(url_for('coffee.my_transactions'))
    try:
        db.session.delete(review)
        db.session.commit()
        flash("הביקורת נמחקה בהצלחה.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting review: {e}")
        flash("אירעה שגיאה בעת מחיקת הביקורת.", "danger")
    return redirect(url_for('coffee.my_transactions'))

# 9. Edit Review (for the buyer)
@coffee_bp.route('/review/edit/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def edit_review(transaction_id):
    """
    Allows the buyer to edit their review for the given coffee transaction.
    The review is identified by the current user and the coffee_transaction field.
    """
    review = UserReview.query.filter_by(
        reviewer_id=current_user.id,
        coffee_transaction=transaction_id
    ).first()
    if not review:
        flash("ביקורת לא נמצאה לעסקה זו.", "warning")
        return redirect(url_for('coffee.my_transactions'))
    
    form = ReviewSellerForm(obj=review)
    if form.validate_on_submit():
        try:
            review.rating = form.rating.data
            review.comment = form.comment.data
            db.session.commit()
            flash("הביקורת עודכנה בהצלחה.", "success")
            return redirect(url_for('coffee.my_transactions'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating review: {e}")
            flash("אירעה שגיאה בעת עדכון הביקורת.", "danger")
            return redirect(url_for('coffee.my_transactions'))
    else:
        if request.method == "POST":
            print("Form errors:", form.errors)
            flash("יש לתקן את השגיאות בטופס.", "danger")
    return render_template('coffee/edit_review.html', form=form, transaction_id=transaction_id)
