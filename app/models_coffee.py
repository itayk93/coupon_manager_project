# app/models_coffee.py
from datetime import datetime
from app.extensions import db

class CoffeeOffer(db.Model):
    __tablename__ = 'coffee_offers'
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    discount_percent = db.Column(db.Float, nullable=False)
    customer_group = db.Column(db.String(50), nullable=False)  # "Connoisseur", "Expert", "Ambassador"
    points_offered = db.Column(db.Integer, nullable=True)       # מספר נקודות במועדון (אופציונלי)
    is_buy_offer = db.Column(db.Boolean, default=False)           # אם True – זוהי בקשת קנייה (ולא הצעת מכירה)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    seller = db.relationship('User', backref='coffee_offers')

class CoffeeTransaction(db.Model):
    __tablename__ = 'coffee_transactions'
    id = db.Column(db.Integer, primary_key=True)
    coffee_offer_id = db.Column(db.Integer, db.ForeignKey('coffee_offers.id', ondelete='CASCADE'), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    seller_id = db.Column(db.Integer, nullable=False)  # מועתק מהצעת הקפה (לנוחות)
    negotiated_price_before = db.Column(db.Float, nullable=True)  # המחיר שהוסכם לפני ההנחה
    negotiated_price_after = db.Column(db.Float, nullable=True)   # המחיר אחרי ההנחה
    points_used = db.Column(db.Integer, nullable=True)            # מספר נקודות לשימוש (אם צוין)
    status = db.Column(db.String(50), default='pending')            # לדוגמה: pending, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    coffee_offer = db.relationship('CoffeeOffer', backref='transactions')
    buyer = db.relationship('User', foreign_keys=[buyer_id])

class CoffeeReview(db.Model):
    __tablename__ = 'coffee_reviews'
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('coffee_transactions.id', ondelete='CASCADE'), nullable=False, unique=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaction = db.relationship('CoffeeTransaction', backref='review')
    reviewer = db.relationship('User', backref='coffee_reviews')
