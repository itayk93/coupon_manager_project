from datetime import datetime, timezone
from flask import url_for
from app.extensions import db  # Import db from extensions.py
from app.extensions import db
from flask_login import UserMixin
from datetime import datetime, timezone
from flask import url_for
from app.extensions import db  # Import db from extensions.py
from flask_login import UserMixin
from datetime import datetime, timezone
from flask import url_for
from .extensions import db
from flask_login import UserMixin
from datetime import datetime

# Additional imports for encryption
from sqlalchemy.types import TypeDecorator, String
from cryptography.fernet import Fernet
import os

from dotenv import load_dotenv
import os

# טוען את קובץ ה-.env
load_dotenv()

# Load the encryption key from environment variables
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise ValueError("No ENCRYPTION_KEY set for encryption")

cipher_suite = Fernet(ENCRYPTION_KEY.encode())


class EncryptedString(TypeDecorator):
    """Encrypted String Type for SQLAlchemy."""
    impl = String

    def process_bind_param(self, value, dialect):
        if value is not None:
            if not value.startswith("gAAAAA"):  # הצפנה רק אם הערך אינו מוצפן
                value = value.encode()
                encrypted_value = cipher_suite.encrypt(value)
                return encrypted_value.decode()
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                if value.startswith("gAAAAA"):  # פענוח רק אם הערך נראה מוצפן
                    value = value.encode()
                    decrypted_value = cipher_suite.decrypt(value)
                    return decrypted_value.decode()
            except Exception as e:
                # טיפול בשגיאות ערכים לא חוקיים
                print(f"Error decrypting value: {value} - {e}")
        return value


# Association table for Coupon and Tag
coupon_tags = db.Table('coupon_tags',
                       db.Column('coupon_id', db.Integer, db.ForeignKey('coupon.id'), primary_key=True),
                       db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
                       )


# User model
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(150), nullable=False)
    last_name = db.Column(db.String(150), nullable=False)
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    region = db.Column(db.String(50), nullable=True)
    religiosity = db.Column(db.String(50), nullable=True)
    income_level = db.Column(db.String(50), nullable=True)
    is_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)  # שדה האדמין
    slots = db.Column(db.Integer, default=0, nullable=False)
    # בתוך מחלקת User (לא כל הקוד, רק השורה הרלוונטית)
    slots_automatic_coupons = db.Column(db.Integer, default=50, nullable=False)

    # Relationships
    notifications = db.relationship('Notification', back_populates='user', lazy=True)
    coupons = db.relationship('Coupon', back_populates='user', lazy=True)
    coupon_requests = db.relationship('CouponRequest', back_populates='user', lazy=True)
    transactions_sold = db.relationship('Transaction', foreign_keys='Transaction.seller_id', back_populates='seller',
                                        lazy=True)
    transactions_bought = db.relationship('Transaction', foreign_keys='Transaction.buyer_id', back_populates='buyer',
                                          lazy=True)


# Tag model
class Tag(db.Model):
    __tablename__ = 'tag'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    count = db.Column(db.Integer, default=0, nullable=False)


# Coupon Usage model
class CouponUsage(db.Model):
    __tablename__ = 'coupon_usage'
    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=False)
    used_amount = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    action = db.Column(db.String(50), nullable=True)  # Added action field
    details = db.Column(db.String(255), nullable=True)  # Additional details field if needed


# models.py

class Coupon(db.Model):
    __tablename__ = 'coupon'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(EncryptedString(255), nullable=False, unique=True)
    description = db.Column(EncryptedString, nullable=True)
    value = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    company = db.Column(db.String(100), nullable=False)
    expiration = db.Column(db.Date, nullable=True)  # db.Date לשמירת תאריך בלבד
    date_added = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    used_value = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='פעיל')
    is_available = db.Column(db.Boolean, default=True)
    is_for_sale = db.Column(db.Boolean, default=False)
    is_one_time = db.Column(db.Boolean, default=False)
    purpose = db.Column(db.String(255), nullable=True)
    exclude_saving = db.Column(db.Boolean, default=False, nullable=False)  # מציין אם להחריג מהחישוב

    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', back_populates='coupons')

    tags = db.relationship('Tag', secondary=coupon_tags, backref=db.backref('coupons', lazy='dynamic'))
    usages = db.relationship('CouponUsage', backref='coupon', lazy=True, cascade='all, delete-orphan')

    # העמודה החדשה
    discount_percentage = db.Column(db.Float, nullable=True)

    # **הוספת היחס multipass_transactions**
    multipass_transactions = db.relationship(
        'CouponTransaction',
        back_populates='coupon',
        cascade='all, delete-orphan'
    )

    # Fields for tracking reminders
    reminder_sent_30_days = db.Column(db.Boolean, default=False, nullable=False)
    reminder_sent_7_days = db.Column(db.Boolean, default=False, nullable=False)
    reminder_sent_1_day = db.Column(db.Boolean, default=False, nullable=False)

    # Fields for tracking notifications
    notification_sent_pagh_tokev = db.Column(db.Boolean, default=False, nullable=False)
    notification_sent_nutzel = db.Column(db.Boolean, default=False, nullable=False)

    # Fields for tracking reminders
    reminder_sent_30_days = db.Column(db.Boolean, default=False, nullable=False)
    reminder_sent_7_days = db.Column(db.Boolean, default=False, nullable=False)
    reminder_sent_1_day = db.Column(db.Boolean, default=False, nullable=False)

    # Fields for tracking notifications
    notification_sent_pagh_tokev = db.Column(db.Boolean, default=False, nullable=False)
    notification_sent_nutzel = db.Column(db.Boolean, default=False, nullable=False)

    @property
    def remaining_value(self):
        return max(self.value - self.used_value, 0)

    @property
    def computed_discount_percentage(self):
        """
        פרופרטי מחושב לאחוז ההנחה על הקופון.
        """
        if self.value == 0:
            return 0
        return ((self.value - self.cost) / self.value) * 100

    @property
    def usage_percentage(self):
        if self.value > 0:
            return round((self.used_value / self.value) * 100, 2)
        return 0.0

    @property
    def savings_percentage(self):
        if self.value > 0:
            return round(((self.value - self.cost) / self.value) * 100, 2)
        return 0.0

    @property
    def amount_paid_so_far(self):
        if self.value > 0:
            return round((self.used_value / self.value) * self.cost, 2)
        return 0.0


# Notification model
class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    viewed = db.Column(db.Boolean, default=False)
    hide_from_view = db.Column(db.Boolean, default=False, nullable=False)
    shown = db.Column(db.Boolean, default=False, nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', back_populates='notifications', lazy=True)


# Transaction model
class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id', ondelete='CASCADE'), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='ממתין לאישור המוכר')
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    buyer_phone = db.Column(db.String(20), nullable=True)
    seller_phone = db.Column(db.String(20), nullable=True)
    seller_confirmed = db.Column(db.Boolean, default=False)
    seller_approved = db.Column(db.Boolean, default=False)
    buyer_confirmed = db.Column(db.Boolean, default=False)
    coupon_code_entered = db.Column(db.Boolean, default=False)
    action = db.Column(db.String(50), nullable=True)
    details = db.Column(db.String(255), nullable=True)

    # הוספת העמודות החדשות
    buyer_request_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    seller_email_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    buyer_email_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    buyer_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    seller_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    coupon = db.relationship('Coupon',
                             backref=db.backref('transactions', cascade='all, delete-orphan', passive_deletes=True),
                             lazy=True)
    seller = db.relationship('User', foreign_keys=[seller_id], back_populates='transactions_sold', lazy=True)
    buyer = db.relationship('User', foreign_keys=[buyer_id], back_populates='transactions_bought', lazy=True)


class CouponRequest(db.Model):
    __tablename__ = 'coupon_requests'
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(100), nullable=False)
    other_company = db.Column(db.String(100), nullable=True)  # שדה חדש
    code = db.Column(db.String(255), nullable=True)  # אפשר ערך NULL
    value = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date_requested = db.Column(db.DateTime, nullable=False)
    fulfilled = db.Column(db.Boolean, default=False)

    user = db.relationship('User', back_populates='coupon_requests')


# Company model
class Company(db.Model):
    __tablename__ = 'companies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    image_path = db.Column(db.String(200), nullable=False)  # נתיב לתמונת הלוגו

    def __repr__(self):
        return f"<Company {self.name}>"


# Helper function to update coupon status
def update_coupon_status(coupon):
    try:
        current_date = datetime.now(timezone.utc).date()
        status = 'פעיל'

        if coupon.expiration:
            try:
                expiration_date = coupon.expiration
                if current_date > expiration_date:
                    status = 'פג תוקף'
                    # Create notification for expired coupon
                    notification = Notification(
                        user_id=coupon.user_id,
                        message=f"הקופון {coupon.code} פג תוקף.",
                        link=url_for('coupon_detail', id=coupon.id)
                    )
                    db.session.add(notification)
            except ValueError:
                pass

        if coupon.used_value >= coupon.value:
            status = 'נוצל'
            # Create notification for fully used coupon
            notification = Notification(
                user_id=coupon.user_id,
                message=f"הקופון {coupon.code} נוצל במלואו.",
                link=url_for('coupon_detail', id=coupon.id)
            )
            db.session.add(notification)

        if coupon.status != status:
            coupon.status = status
    except Exception as e:
        print(f"Error in update_coupon_status: {e}")


class CouponTransaction(db.Model):
    __tablename__ = 'coupon_transaction'  # ודא ששמו נכון
    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=False)
    card_number = db.Column(db.String(50), nullable=False)
    transaction_date = db.Column(db.DateTime, nullable=True)  # מאפשר NULL
    location = db.Column(db.String(255), nullable=True)
    recharge_amount = db.Column(db.Float, nullable=True)
    usage_amount = db.Column(db.Float, nullable=True)
    reference_number = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(50), nullable=False, default='User')  # שדה חדש

    # קשר לקופון
    coupon = db.relationship('Coupon', back_populates='multipass_transactions')

class GptUsage(db.Model):
    __tablename__ = 'gpt_usage'

    gpt_usage_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    id = db.Column(db.String(255))
    object = db.Column(db.String(255))
    model = db.Column(db.String(255))
    prompt_tokens = db.Column(db.Integer)
    completion_tokens = db.Column(db.Integer)
    total_tokens = db.Column(db.Integer)
    cost_usd = db.Column(db.Float)
    cost_ils = db.Column(db.Float)
    exchange_rate = db.Column(db.Float)
    prompt_text = db.Column(db.Text, nullable=True)
    response_text = db.Column(db.Text, nullable=True)

    user = db.relationship('User', backref='gpt_usage_records')
