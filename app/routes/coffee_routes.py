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
    return render_template('coffee/index.html', offers=offers)

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models_coffee import CoffeeOffer
from app.forms import CoffeeOfferForm  # Ensure the form is imported


@coffee_bp.route('/offer', methods=['GET', 'POST'])
@login_required
def create_offer():
    """
    Handles the creation of a coffee discount offer.

    This function allows users (buyers or sellers) to create an offer 
    for purchasing coffee at a discount. The user provides:
      - Discount percentage (e.g., 20% off)
      - Customer group (Connoisseur, Expert, Ambassador)
      - (Optional) Loyalty points offered
      - Offer type: "I am offering a discount" (seller) or "I am looking for a discount" (buyer)
      - (Optional) Description

    The page displays a short explanation:
    "This page allows users with discounts (e.g., Ambassador) to help 
    other users buy coffee at a reduced price. The final price will be 
    agreed upon between the parties, and the software is not responsible 
    for transactions."
    
    Returns:
        - Renders `offer_form.html` for GET requests.
        - Processes form submission and redirects to the index page for POST requests.
    """

    form = CoffeeOfferForm()  # Create an instance of the form

    # If the form is submitted and passes validation
    if form.validate_on_submit():
        # Create a new coffee offer instance using the form data
        new_offer = CoffeeOffer(
            seller_id=current_user.id,  # Store the ID of the logged-in user as the seller
            discount_percent=form.discount_percent.data,  # Discount percentage
            customer_group=form.customer_group.data,  # Selected customer group
            points_offered=form.points_offered.data,  # Optional loyalty points
            is_buy_offer=True if form.offer_type.data == 'buy' else False,  # Determine if the user is buying or selling
            expiration_date=form.expiration_date.data,  # שמירת תוקף ההנחה  
            description=form.description.data,  # Optional description
        )

        db.session.add(new_offer)  # Add the new offer to the database session
        db.session.commit()  # Commit changes to the database

        flash("The discount offer was successfully created!", "success")  # Success message
        return redirect(url_for('coffee.index'))  # Redirect to the coffee index page

    # If it's a GET request, render the offer form
    return render_template('coffee/offer_form.html', form=form)

@coffee_bp.route('/offers')
@login_required
def list_offers():
    """מציג את רשימת כל הצעות הקפה הקיימות."""
    offers = CoffeeOffer.query.order_by(CoffeeOffer.expiration_date.desc()).all()
    return render_template('coffee/offer_list.html', offers=offers)

@coffee_bp.route('/offer/<int:offer_id>')
@login_required
def offer_detail(offer_id):
    """מציג את פרטי הצעת הקפה. אם המשתמש אינו המוכר – יוצג לו כפתור לרכוש."""
    offer = CoffeeOffer.query.get_or_404(offer_id)
    return render_template('coffee/offer_detail.html', offer=offer)

@coffee_bp.route('/buy_offer/<int:offer_id>', methods=['GET', 'POST'])
@login_required
def buy_offer(offer_id):
    """
    עמוד שבו קונה יכול לקבל את ההצעה.
    הקונה מזין:
      - מחיר שסוכם לפני ההנחה
      - מחיר שסוכם אחרי ההנחה
      - (אופציונלי) מספר נקודות מועדון לשימוש
    """
    offer = CoffeeOffer.query.get_or_404(offer_id)
    if offer.seller_id == current_user.id:
        flash("אינך יכול לרכוש את ההצעה שלך.", "danger")
        return redirect(url_for('coffee.offer_detail', offer_id=offer_id))
    if request.method == 'POST':
        try:
            negotiated_price_before = float(request.form.get('negotiated_price_before'))
            negotiated_price_after = float(request.form.get('negotiated_price_after'))
        except (TypeError, ValueError):
            flash("יש להזין מחירים תקינים.", "danger")
            return redirect(url_for('coffee.buy_offer', offer_id=offer_id))
        points_used = request.form.get('points_used')
        try:
            points_used = int(points_used) if points_used else None
        except ValueError:
            flash("יש להזין נקודות כמספר שלם.", "danger")
            return redirect(url_for('coffee.buy_offer', offer_id=offer_id))

        transaction = CoffeeTransaction(
            coffee_offer_id=offer.id,
            buyer_id=current_user.id,
            seller_id=offer.seller_id,
            negotiated_price_before=negotiated_price_before,
            negotiated_price_after=negotiated_price_after,
            points_used=points_used,
            status='pending'
        )
        db.session.add(transaction)
        db.session.commit()
        flash("בקשת רכישה נוצרה בהצלחה. אנא תיאמו עם המוכר את המחיר.", "success")
        return redirect(url_for('coffee.transaction_detail', transaction_id=transaction.id))
    return render_template('coffee/buy_offer.html', offer=offer)

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
