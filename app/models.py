# app/models.py

import os
from datetime import datetime, timezone
from dotenv import load_dotenv

from flask import url_for
from flask_login import UserMixin
from sqlalchemy.types import TypeDecorator, String
from sqlalchemy.sql import func
from cryptography.fernet import Fernet

from app.extensions import db  # נניח שיש לך את האובייקט db כאן
from sqlalchemy import Column, Integer, String  # הוסף את הייבוא החסר

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
            # הצפנה רק אם הערך אינו נראה כבר מוצפן
            if not value.startswith("gAAAAA"):
                value = value.encode()
                encrypted_value = cipher_suite.encrypt(value)
                return encrypted_value.decode()
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                # פענוח רק אם הערך נראה מוצפן
                if value.startswith("gAAAAA"):
                    value = value.encode()
                    decrypted_value = cipher_suite.decrypt(value)
                    return decrypted_value.decode()
            except Exception as e:
                print(f"Error decrypting value: {value} - {e}")
        return value

# Association table for Coupon and Tag (many-to-many)
coupon_tags = db.Table(
    'coupon_tags',
    db.metadata,  # Ensure you're using Flask-SQLAlchemy's metadata
    db.Column('coupon_id', db.Integer, db.ForeignKey('coupon.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete='CASCADE'), primary_key=True),
    extend_existing=True  # Allows redefining the table if it already exists
)


class User(UserMixin, db.Model):
    """
    טבלת המשתמשים.
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    google_id = db.Column(db.String(50), unique=True, nullable=True)  # ✅ זה השדה החדש
    password = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(150), nullable=False)
    last_name = db.Column(db.String(150), nullable=False)
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    dismissed_message_id = db.Column(db.Integer, nullable=True)
    # עמודה תאריך יצירת המשתמש
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    # שדה תיאור פרופיל (טקסט משתמש כותב על עצמו)
    profile_description = db.Column(db.Text, nullable=True)

    # נתיב לתמונת פרופיל
    profile_image = db.Column(db.String(255), nullable=True)

    is_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    slots = db.Column(db.Integer, default=0, nullable=False)
    slots_automatic_coupons = db.Column(db.Integer, default=50, nullable=False)

    # 🆕 שדה חדש: מתי המשתמש דחה את התראה על קופונים שפג תוקפם
    dismissed_expiring_alert_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    notifications = db.relationship('Notification', back_populates='user', lazy=True)
    coupons = db.relationship('Coupon', back_populates='user', lazy=True)
    coupon_requests = db.relationship('CouponRequest', back_populates='user', lazy=True)
    transactions_sold = db.relationship(
        'Transaction',
        foreign_keys='Transaction.seller_id',
        back_populates='seller',
        lazy=True
    )
    transactions_bought = db.relationship(
        'Transaction',
        foreign_keys='Transaction.buyer_id',
        back_populates='buyer',
        lazy=True
    )

    # New: יחס לטבלת דירוגים (עבור משתמש זה כ"מקבל" הדירוג)
    received_ratings = db.relationship('UserRating', foreign_keys='UserRating.rated_user_id', back_populates='rated_user', lazy=True)

    # פונקציה לחישוב כמה קופונים המשתמש מכר
    @property
    def coupons_sold_count(self):
        # למשל, נניח ב-Transaction הססטוס הסופי הוא 'הושלם' / 'אושר' / 'נסגר'
        # אפשר לבדוק transaction.status == 'הושלם'
        from app.models import Transaction
        sold_transactions = Transaction.query.filter_by(seller_id=self.id, status='הושלמה').all()
        return len(sold_transactions)

    @property
    def days_since_register(self):
        """
        מחזיר כמה ימים עברו מאז שהמשתמש נוצר.
        """
        if not self.created_at:
            return 0
        now_naive = datetime.now().replace(tzinfo=None)
        created_at_naive = self.created_at.replace(tzinfo=None) if self.created_at.tzinfo else self.created_at
        delta = now_naive - created_at_naive
        return delta.days

    def __repr__(self):
        return f"<User {self.id} {self.email}>"

    # New Relationships for Usage Data
    consents = db.relationship("UserConsent", back_populates="user", lazy=True)
    activities = db.relationship("UserActivity", back_populates="user", lazy=True)
    opt_out = db.relationship("OptOut", back_populates="user", uselist=False)


class Tag(db.Model):
    """
    טבלת תגיות (לסיווג קופונים, למשל).
    """
    __tablename__ = 'tag'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    count = db.Column(db.Integer, default=0)

    coupons = db.relationship('Coupon', secondary=coupon_tags, back_populates='tags')


class Coupon(db.Model):
    """
    טבלת קופונים.
    """
    __tablename__ = 'coupon'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(EncryptedString(255), nullable=False, unique=True)
    description = db.Column(EncryptedString, nullable=True)
    value = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    company = db.Column(db.String(100), nullable=False)
    expiration = db.Column(db.Date, nullable=True)  # תאריך תוקף
    source = db.Column(db.String(255), nullable=True)  # שדה חדש עבור מקור הקופון
    buyme_coupon_url = db.Column(EncryptedString(255), nullable=True)     # >>> NEW FIELD: BuyMe Coupon URL <<<
    date_added = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    used_value = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='פעיל')
    is_available = db.Column(db.Boolean, default=True)
    is_for_sale = db.Column(db.Boolean, default=False)
    is_one_time = db.Column(db.Boolean, default=False)
    purpose = db.Column(db.String(255), nullable=True)
    exclude_saving = db.Column(db.Boolean, default=False, nullable=False)  # מציין אם להחריג מהחישוב
    auto_download_details = db.Column(db.Text, nullable=True)  # ניתן לשנות את סוג הנתונים בהתאם

    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', back_populates='coupons')

    tags = db.relationship('Tag', secondary=coupon_tags, back_populates='coupons')
    usages = db.relationship('CouponUsage', backref='coupon', lazy=True, cascade='all, delete-orphan')

    # Relevant for specific coupons
    cvv = db.Column(EncryptedString(4), nullable=True)       # אורך מקסימלי 4 (3 או 4 ספרות)
    card_exp = db.Column(EncryptedString(5), nullable=True)  # אורך מקסימלי 5 (פורמט "MM/YY")

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

    @property
    def remaining_value(self):
        return max(self.value - self.used_value, 0)

    @property
    def original_value(self):
        """
        מחזיר את הערך המקורי של הקופון.
        זהה ל-value בשלב זה, אך יכול להשתנות בעתיד אם תרצה.
        """
        return self.value

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


class CouponUsage(db.Model):
    """
    טבלת רישום פעולות שימוש (חלקיות או מלאות) בקופון.
    """
    __tablename__ = 'coupon_usage'
    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=False)
    used_amount = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    action = db.Column(db.String(50), nullable=True)     # לדוגמה: "redeem", "partial_use"
    details = db.Column(db.String(255), nullable=True)


class Notification(db.Model):
    """
    טבלת התראות (Notifications).
    """
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


class Transaction(db.Model):
    """
    טבלת טרנזקציות (קניה/מכירה של קופון בין משתמשים).
    """
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id', ondelete='CASCADE'), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='ממתין לאישור המוכר')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    source = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    buyer_phone = db.Column(db.String(20), nullable=True)
    seller_phone = db.Column(db.String(20), nullable=True)
    seller_confirmed = db.Column(db.Boolean, default=False)
    seller_approved = db.Column(db.Boolean, default=False)
    buyer_confirmed = db.Column(db.Boolean, default=False)
    coupon_code_entered = db.Column(db.Boolean, default=False)
    action = db.Column(db.String(50), nullable=True)
    details = db.Column(db.String(255), nullable=True)
    transaction_date = db.Column(db.DateTime(timezone=True), nullable=True)

    # הוספת העמודות החדשות
    buyer_request_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    seller_email_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    buyer_email_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    buyer_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    seller_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(db.DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    coupon = db.relationship(
        'Coupon',
        backref=db.backref('transactions', cascade='all, delete-orphan', passive_deletes=True),
        lazy=True
    )
    seller = db.relationship('User', foreign_keys=[seller_id], back_populates='transactions_sold', lazy=True)
    buyer = db.relationship('User', foreign_keys=[buyer_id], back_populates='transactions_bought', lazy=True)

""""""""""
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

    # עמודות תיעוד נוספות
    buyer_request_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    seller_email_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    buyer_email_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    buyer_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    seller_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    coupon = db.relationship(
        'Coupon',
        backref=db.backref('transactions', cascade='all, delete-orphan', passive_deletes=True),
        lazy=True
    )
    seller = db.relationship('User', foreign_keys=[seller_id], back_populates='transactions_sold', lazy=True)
    buyer = db.relationship('User', foreign_keys=[buyer_id], back_populates='transactions_bought', lazy=True)
"""""""""
class CouponRequest(db.Model):
    """
    טבלת בקשות לקופונים (משתמשים מבקשים קופון מסוים).
    """
    __tablename__ = 'coupon_requests'
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(100), nullable=False)
    other_company = db.Column(db.String(100), nullable=True)  # שדה חדש
    code = db.Column(db.String(255), nullable=True)           # אפשר ערך NULL
    value = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=True)          # שדה הסבר
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date_requested = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    fulfilled = db.Column(db.Boolean, default=False)

    user = db.relationship('User', back_populates='coupon_requests')


class Company(db.Model):
    """
    טבלת חברות (כדי לשמור תמונות לוגו, למשל).
    """
    __tablename__ = 'companies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    image_path = db.Column(db.String(200), nullable=False)
    company_count = db.Column(db.Integer, default=0)  # וודא שזה קיים!

    def __repr__(self):
        return f"<Company {self.name}>"


def update_coupon_status(coupon):
    """
    פונקציה שתעודכן (כנראה) בכל שלב של שינוי קופון.
    """
    try:
        current_date = datetime.now(timezone.utc).date()
        status = 'פעיל'

        if coupon.expiration:
            expiration_date = coupon.expiration
            if current_date > expiration_date:
                status = 'פג תוקף'
                # Create notification for expired coupon
                """""""""
                notification = Notification(
                    user_id=coupon.user_id,
                    message=f"הקופון {coupon.code} פג תוקף.",
                    link=url_for('coupon_detail', id=coupon.id)
                )
                db.session.add(notification)
                """""""""

        if coupon.used_value >= coupon.value:
            status = 'נוצל'
            """""""""
            # Create notification for fully used coupon
            notification = Notification(
                user_id=coupon.user_id,
                message=f"הקופון {coupon.code} נוצל במלואו.",
                link=url_for('coupon_detail', id=coupon.id)
            )
            db.session.add(notification)
            """""""""

        if coupon.status != status:
            coupon.status = status

    except Exception as e:
        print(f"Error in update_coupon_status: {e}")


class CouponTransaction(db.Model):
    """
    טבלת "טרנזקציות" (או לוג) של שימוש רב-פעמי בקופון.
    """
    __tablename__ = 'coupon_transaction'

    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=False)
    transaction_date = db.Column(db.DateTime, nullable=True)
    location = db.Column(db.String(255), nullable=True)
    recharge_amount = db.Column(db.Float, nullable=True)
    usage_amount = db.Column(db.Float, nullable=True)
    reference_number = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(50), nullable=False, default='User')

    coupon = db.relationship('Coupon', back_populates='multipass_transactions')


class GptUsage(db.Model):
    """
    טבלת רישום שימוש ב-GPT ע"י המשתמש.
    """
    __tablename__ = 'gpt_usage'

    gpt_usage_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # שדה 'id' בקוליזיה עם self.id => שים לב אם הכוונה ל-GPT API ID
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


class UserConsent(db.Model):
    """
    טבלת הסכמה לאיסוף מידע (Consent).
    """
    __tablename__ = "user_consents"

    consent_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # הפך ללא חובה
    ip_address = db.Column(db.String(45), nullable=True) 
    consent_status = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    version = db.Column(db.String(50), default="1.0")

    user = db.relationship("User", back_populates="consents")


class UserActivity(db.Model):
    """
    טבלת פעילות משתמשים (Events, Trackers וכו').
    """
    __tablename__ = "user_activities"

    activity_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False)  # כגון: "view_coupon", "redeem_coupon"
    coupon_id = db.Column(db.Integer, nullable=True)    # מזהה קופון
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=True)
    device = db.Column(db.String(50), nullable=True)    # "Desktop", "Mobile"
    browser = db.Column(db.String(50), nullable=True)
    geo_location = db.Column(db.String(100), nullable=True)
    duration = db.Column(db.Integer, nullable=True)     # משך הפעולה בשניות, אם רלוונטי
    extra_metadata = db.Column(db.Text, nullable=True)  # JSON או טקסט נוסף

    user = db.relationship("User", back_populates="activities")


class OptOut(db.Model):
    """
    טבלת Opt-Out: משתמשים שביקשו להפסיק איסוף מידע.
    """
    __tablename__ = "opt_outs"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    opted_out = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="opt_out")


# app/models.py (המשך)

class UserRating(db.Model):
    """
    טבלת דירוג והערות על משתמשים:
    - כל רשומה מציינת ש- rating_user_id (מי מדרג) נתן דירוג ל- rated_user_id (מי שקיבל).
    - rating_value: מספר (1-5 למשל).
    - rating_comment: הערה חופשית.
    - created_at: תאריך כתיבת הדירוג/ההערה.
    - מגבלה: כל משתמש יכול לדרג משתמש אחר רק פעם אחת => נטפל בזה בלוגיקה של ה-Route.
    """
    __tablename__ = 'user_ratings'

    id = db.Column(db.Integer, primary_key=True)
    rated_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating_value = db.Column(db.Integer, nullable=False)
    rating_comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    # יחסים
    rated_user = db.relationship('User', foreign_keys=[rated_user_id], back_populates='received_ratings')
    # אם תרצה לקבל גם את מי שנתן את הדירוג (User), אפשר להוסיף יחסים נוספים:
    rating_user = db.relationship('User', foreign_keys=[rating_user_id], lazy=True)

    def __repr__(self):
        return f"<UserRating from {self.rating_user_id} to {self.rated_user_id} = {self.rating_value}>"

# app/models.py

from app.extensions import db
from datetime import datetime

class UserReview(db.Model):
    __tablename__ = 'user_reviews'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # מי שנתן את הביקורת
    reviewed_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # המשתמש שמקבל את הביקורת
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)  # עמודה חדשה
    coffee_transaction = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    rating = db.Column(db.Integer, nullable=True)  # דירוג 1-5
    comment = db.Column(db.Text, nullable=True)    # הערה טקסטואלית
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('reviewer_id', 'reviewed_user_id', 'transaction_id', name='user_reviews_unique_review'),
    )

    # קשרים אופציונליים
    reviewer = db.relationship("User", foreign_keys=[reviewer_id], backref="reviews_given")
    reviewed_user = db.relationship("User", foreign_keys=[reviewed_user_id], backref="reviews_received")

class AdminMessage(db.Model):
    __tablename__ = 'admin_messages'

    id = db.Column(db.Integer, primary_key=True)
    message_text = db.Column(db.Text, nullable=False)
    link_url = db.Column(db.String(255), nullable=True)   # קישור אופציונלי
    link_text = db.Column(db.String(255), nullable=True)  # טקסט הכפתור
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FeatureAccess(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    feature_name = db.Column(db.String(255), nullable=False)
    access_mode = db.Column(db.String(50), default=None)
