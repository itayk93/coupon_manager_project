# app/models_coffee.py
from datetime import datetime
from app.extensions import db
from datetime import datetime, timezone

class CoffeeReview(db.Model):
    __tablename__ = 'coffee_reviews'
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('coffee_transaction.id', ondelete='CASCADE'), nullable=False, unique=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaction = db.relationship('CoffeeTransaction', backref='review')
    reviewer = db.relationship('User', backref='coffee_reviews')


# ----------------------------
# מודלים עבור הצעות קפה ותהליכי עסקה
# ----------------------------

class CoffeeOffer(db.Model):
    """טבלת הצעות קפה."""
    __tablename__ = 'coffee_offer'
    id = db.Column(db.Integer, primary_key=True)
    discount_percent = db.Column(db.Float, nullable=True, default=0)
    customer_group = db.Column(db.String(50), nullable=False)
    points_offered = db.Column(db.Integer, nullable=True)
    offer_type = db.Column(db.String(10), nullable=False, default='sell')
    expiration_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=True)
    date_created = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    is_available = db.Column(db.Boolean, default=True)
    is_for_sale = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', backref='coffee_offers', lazy=True)
    is_buy_offer = db.Column(db.Boolean, default=False)
    desired_discount = db.Column(db.Float, nullable=True)
    buyer_description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<CoffeeOffer {self.id} {self.discount_percent}% for {self.customer_group}>"

class CoffeeTransaction(db.Model):
    """טבלת טרנזקציות עבור הצעות קפה."""
    __tablename__ = 'coffee_transaction'
    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(db.Integer, db.ForeignKey('coffee_offer.id'), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='ממתין לאישור המוכר')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    seller_confirmed = db.Column(db.Boolean, default=False)
    buyer_confirmed = db.Column(db.Boolean, default=False)
    seller_phone = db.Column(db.String(20), nullable=True)
    buyer_phone = db.Column(db.String(20), nullable=True)
    seller_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    buyer_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    offer = db.relationship('CoffeeOffer', backref=db.backref('transactions', cascade='all, delete-orphan'), lazy=True)
    seller = db.relationship('User', foreign_keys=[seller_id], backref='coffee_transactions_sold', lazy=True)
    buyer = db.relationship('User', foreign_keys=[buyer_id], backref='coffee_transactions_bought', lazy=True)

    def __repr__(self):
        return f"<CoffeeTransaction {self.id} status: {self.status}>"
