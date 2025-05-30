# app/models.py

import os
from datetime import datetime, timezone
from dotenv import load_dotenv

from flask import url_for
from flask_login import UserMixin
from sqlalchemy.types import TypeDecorator, String
from sqlalchemy.sql import func
from cryptography.fernet import Fernet
from itsdangerous import Serializer, URLSafeTimedSerializer
from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db  # Assuming you have the db object here
from sqlalchemy import Column, Integer, String  # Add the missing import

# Load the .env file
load_dotenv()

# Load the encryption key from environment variables
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise ValueError("No ENCRYPTION_KEY set for encryption")

cipher_suite = Fernet(ENCRYPTION_KEY.encode())


class EncryptedString(TypeDecorator):
    """Encrypted String Type for SQLAlchemy."""

    impl = String

    def process_bind_param(self, value, dialect):
        if value is not None:
            # Encrypt only if the value doesn't appear to be already encrypted
            if not value.startswith("gAAAAA"):
                value = value.encode()
                encrypted_value = cipher_suite.encrypt(value)
                return encrypted_value.decode()
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                # Decrypt only if the value appears to be encrypted
                if value.startswith("gAAAAA"):
                    value = value.encode()
                    decrypted_value = cipher_suite.decrypt(value)
                    return decrypted_value.decode()
            except Exception as e:
                print(f"Error decrypting value: {value} - {e}")
        return value


# Association table for Coupon and Tag (many-to-many)
coupon_tags = db.Table(
    "coupon_tags",
    db.metadata,  # Ensure you're using Flask-SQLAlchemy's metadata
    db.Column(
        "coupon_id",
        db.Integer,
        db.ForeignKey("coupon.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "tag_id",
        db.Integer,
        db.ForeignKey("tag.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    extend_existing=True,  # Allows redefining the table if it already exists
)


class User(UserMixin, db.Model):
    """
    Users table.
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    google_id = db.Column(
        db.String(50), unique=True, nullable=True
    )  # ✅ This is the new field
    password = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(150), nullable=False)
    last_name = db.Column(db.String(150), nullable=False)
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    dismissed_message_id = db.Column(db.Integer, nullable=True)
    # User creation date column
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    # Profile description field (text written by the user about themselves)
    profile_description = db.Column(db.Text, nullable=True)

    # Path to profile image
    profile_image = db.Column(db.String(255), nullable=True)

    is_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    slots = db.Column(db.Integer, default=0, nullable=False)
    slots_automatic_coupons = db.Column(db.Integer, default=50, nullable=False)

    # 🆕 New field: When the user dismissed the alert about expiring coupons
    dismissed_expiring_alert_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    notifications = db.relationship("Notification", back_populates="user", lazy=True)
    coupons = db.relationship("Coupon", back_populates="user", lazy=True)
    coupon_requests = db.relationship("CouponRequest", back_populates="user", lazy=True)
    transactions_sold = db.relationship(
        "Transaction",
        foreign_keys="Transaction.seller_id",
        back_populates="seller",
        lazy=True,
    )
    transactions_bought = db.relationship(
        "Transaction",
        foreign_keys="Transaction.buyer_id",
        back_populates="buyer",
        lazy=True,
    )

    # New: Relationship to ratings table (for this user as the "receiver" of the rating)
    received_ratings = db.relationship(
        "UserRating",
        foreign_keys="UserRating.rated_user_id",
        back_populates="rated_user",
        lazy=True,
    )

    # Function to calculate how many coupons the user has sold
    @property
    def coupons_sold_count(self):
        # For example, in Transaction the final status is 'Completed' / 'Approved' / 'Closed'
        # We can check transaction.status == 'Completed'
        from app.models import Transaction

        sold_transactions = Transaction.query.filter_by(
            seller_id=self.id, status="הושלמה"
        ).all()
        return len(sold_transactions)

    @property
    def days_since_register(self):
        """
        Returns how many days have passed since the user was created.
        """
        if not self.created_at:
            return 0
        now_naive = datetime.now().replace(tzinfo=None)
        created_at_naive = (
            self.created_at.replace(tzinfo=None)
            if self.created_at.tzinfo
            else self.created_at
        )
        delta = now_naive - created_at_naive
        return delta.days

    def __repr__(self):
        return f"<User {self.id} {self.email}>"

    # New Relationships for Usage Data
    consents = db.relationship("UserConsent", back_populates="user", lazy=True)
    activities = db.relationship("UserActivity", back_populates="user", lazy=True)
    opt_out = db.relationship("OptOut", back_populates="user", uselist=False)

    def set_password(self, password):
        """Hash and set the user's password."""
        self.password = generate_password_hash(password)

    def check_password(self, password):
        """Check if the provided password matches the stored hash."""
        return check_password_hash(self.password, password)

    def generate_password_change_token(self, expiration=3600):
        """Generate a token for password change confirmation."""
        from itsdangerous import URLSafeTimedSerializer
        from flask import current_app

        s = URLSafeTimedSerializer(
            current_app.config["SECRET_KEY"],
            salt="password-change",  # Using a constant string for salt
        )
        return s.dumps(
            {"user_id": self.id}
        )  # Removed .decode('utf-8') as it's already a string

    def verify_password_change_token(self, token, expiration=3600):
        """Verify the password change token."""
        from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
        from flask import current_app

        s = URLSafeTimedSerializer(
            current_app.config["SECRET_KEY"],
            salt="password-change",  # Same salt as in generate_password_change_token
        )
        try:
            data = s.loads(token, max_age=expiration)
            if data.get("user_id") != self.id:
                return False
            return True
        except (SignatureExpired, BadSignature):
            return False


class Tag(db.Model):
    """
    Tags table (for classifying coupons, for example).
    """

    __tablename__ = "tag"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    count = db.Column(db.Integer, default=0)

    coupons = db.relationship("Coupon", secondary=coupon_tags, back_populates="tags")


class Coupon(db.Model):
    """
    Coupons table.
    """

    __tablename__ = "coupon"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(EncryptedString(255), nullable=False, unique=True)
    description = db.Column(EncryptedString, nullable=True)
    value = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    company = db.Column(db.String(100), nullable=False)
    expiration = db.Column(db.Date, nullable=True)  # Expiration date
    source = db.Column(db.String(255), nullable=True)  # New field for coupon source
    buyme_coupon_url = db.Column(
        EncryptedString(255), nullable=True
    )  # >>> NEW FIELD: BuyMe Coupon URL <<<
    date_added = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    used_value = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="פעיל")
    is_available = db.Column(db.Boolean, default=True)
    is_for_sale = db.Column(db.Boolean, default=False)
    is_one_time = db.Column(db.Boolean, default=False)
    purpose = db.Column(db.String(255), nullable=True)
    exclude_saving = db.Column(
        db.Boolean, default=False, nullable=False
    )  # Indicates whether to exclude from calculation
    auto_download_details = db.Column(
        db.Text, nullable=True
    )  # Can change data type as needed

    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user = db.relationship("User", back_populates="coupons")

    tags = db.relationship("Tag", secondary=coupon_tags, back_populates="coupons")
    usages = db.relationship(
        "CouponUsage", backref="coupon", lazy=True, cascade="all, delete-orphan"
    )

    # Relevant for specific coupons
    cvv = db.Column(
        EncryptedString(4), nullable=True
    )  # Maximum length 4 (3 or 4 digits)
    card_exp = db.Column(
        EncryptedString(5), nullable=True
    )  # Maximum length 5 (format "MM/YY")

    # **Adding the multipass_transactions relationship**
    multipass_transactions = db.relationship(
        "CouponTransaction", back_populates="coupon", cascade="all, delete-orphan"
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
        """Get the original value of the coupon."""
        return self.value

    @property
    def computed_discount_percentage(self):
        """Calculate the discount percentage based on cost and value."""
        if self.value == 0:
            return 0
        return ((self.value - self.cost) / self.value) * 100

    @property
    def usage_percentage(self):
        """Calculate the usage percentage of the coupon."""
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
    Table for recording coupon usage actions (partial or full).
    """

    __tablename__ = "coupon_usage"
    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey("coupon.id"), nullable=False)
    used_amount = db.Column(db.Float, nullable=False)
    timestamp = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    action = db.Column(
        db.String(50), nullable=True
    )  # For example: "redeem", "partial_use"
    details = db.Column(db.String(255), nullable=True)


class Notification(db.Model):
    """
    Notifications table.
    """

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    viewed = db.Column(db.Boolean, default=False)
    hide_from_view = db.Column(db.Boolean, default=False, nullable=False)
    shown = db.Column(db.Boolean, default=False, nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user = db.relationship("User", back_populates="notifications", lazy=True)


class Transaction(db.Model):
    """
    Transactions table (buying/selling coupons between users).
    """

    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(
        db.Integer, db.ForeignKey("coupon.id", ondelete="CASCADE"), nullable=False
    )
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="ממתין לאישור המוכר")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    source = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    buyer_phone = db.Column(db.String(20), nullable=True)
    seller_phone = db.Column(db.String(20), nullable=True)
    seller_confirmed = db.Column(db.Boolean, default=False)
    seller_approved = db.Column(db.Boolean, default=False)
    buyer_confirmed = db.Column(db.Boolean, default=False)
    coupon_code_entered = db.Column(db.Boolean, default=False)
    action = db.Column(db.String(50), nullable=True)
    details = db.Column(db.String(255), nullable=True)
    transaction_date = db.Column(db.DateTime(timezone=True), nullable=True)

    # Adding new columns
    buyer_request_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    seller_email_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    buyer_email_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    buyer_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    seller_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(db.DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    coupon = db.relationship(
        "Coupon",
        backref=db.backref(
            "transactions", cascade="all, delete-orphan", passive_deletes=True
        ),
        lazy=True,
    )
    seller = db.relationship(
        "User", foreign_keys=[seller_id], back_populates="transactions_sold", lazy=True
    )
    buyer = db.relationship(
        "User", foreign_keys=[buyer_id], back_populates="transactions_bought", lazy=True
    )


class CouponRequest(db.Model):
    """
    Coupon requests table (users requesting specific coupons).
    """

    __tablename__ = "coupon_requests"
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(100), nullable=False)
    other_company = db.Column(db.String(100), nullable=True)  # New field
    code = db.Column(db.String(255), nullable=True)  # Can be NULL
    value = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=True)  # Description field
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date_requested = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    fulfilled = db.Column(db.Boolean, default=False)

    user = db.relationship("User", back_populates="coupon_requests")


class Company(db.Model):
    """
    Companies table (to store logo images, for example).
    """

    __tablename__ = "companies"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    image_path = db.Column(db.String(200), nullable=False)
    company_count = db.Column(db.Integer, default=0)  # Make sure this exists!

    def __repr__(self):
        return f"<Company {self.name}>"


def update_coupon_status(coupon):
    try:
        current_date = datetime.now(timezone.utc).date()
        status = "פעיל"

        if coupon.expiration:
            expiration_date = coupon.expiration
            if current_date > expiration_date:
                status = "פג תוקף"
                # Create notification for expired coupon
                """""" """
                notification = Notification(
                    user_id=coupon.user_id,
                    message=f"הקופון {coupon.code} פג תוקף.",
                    link=url_for('coupon_detail', id=coupon.id)
                )
                db.session.add(notification)
                """ """"""

        if coupon.used_value >= coupon.value:
            status = "נוצל"
            """""" """
            # Create notification for fully used coupon
            notification = Notification(
                user_id=coupon.user_id,
                message=f"הקופון {coupon.code} נוצל במלואו.",
                link=url_for('coupon_detail', id=coupon.id)
            )
            db.session.add(notification)
            """ """"""

        if coupon.status != status:
            coupon.status = status

    except Exception as e:
        print(f"Error in update_coupon_status: {e}")


class CouponTransaction(db.Model):
    """
    "Transactions" table (or log) for multi-use coupon usage.
    """

    __tablename__ = "coupon_transaction"

    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey("coupon.id"), nullable=False)
    transaction_date = db.Column(db.DateTime, nullable=True)
    location = db.Column(db.String(255), nullable=True)
    recharge_amount = db.Column(db.Float, nullable=True)
    usage_amount = db.Column(db.Float, nullable=True)
    reference_number = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(50), nullable=False, default="User")

    coupon = db.relationship("Coupon", back_populates="multipass_transactions")


class GptUsage(db.Model):
    """
    Table for recording GPT usage by users.
    """

    __tablename__ = "gpt_usage"

    gpt_usage_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
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

    user = db.relationship("User", backref="gpt_usage_records")


class UserConsent(db.Model):
    """
    Consent table for data collection.
    """

    __tablename__ = "user_consents"

    consent_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True
    )  # Made optional
    ip_address = db.Column(db.String(45), nullable=True)
    consent_status = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    version = db.Column(db.String(50), default="1.0")

    user = db.relationship("User", back_populates="consents")


class UserActivity(db.Model):
    """
    User activity table (Events, Trackers, etc.).
    """

    __tablename__ = "user_activities"

    activity_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(
        db.String(100), nullable=False
    )  # Such as: "view_coupon", "redeem_coupon"
    coupon_id = db.Column(db.Integer, nullable=True)  # Coupon identifier
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=True)
    device = db.Column(db.String(50), nullable=True)  # "Desktop", "Mobile"
    browser = db.Column(db.String(50), nullable=True)
    geo_location = db.Column(db.String(100), nullable=True)
    duration = db.Column(
        db.Integer, nullable=True
    )  # Duration of action in seconds, if relevant
    extra_metadata = db.Column(db.Text, nullable=True)  # JSON or additional text

    user = db.relationship("User", back_populates="activities")


class OptOut(db.Model):
    """
    Opt-Out table: Users who requested to stop data collection.
    """

    __tablename__ = "opt_outs"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    opted_out = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="opt_out")


class UserRating(db.Model):
    """
    User ratings and comments table:
    - Each record indicates that rating_user_id (who rates) gave a rating to rated_user_id (who received).
    - rating_value: number (1-5 for example).
    - rating_comment: free text comment.
    - created_at: date of rating/comment.
    - Limitation: Each user can rate another user only once => We'll handle this in the Route logic.
    """

    __tablename__ = "user_ratings"

    id = db.Column(db.Integer, primary_key=True)
    rated_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating_value = db.Column(db.Integer, nullable=False)
    rating_comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    # Relationships
    rated_user = db.relationship(
        "User", foreign_keys=[rated_user_id], back_populates="received_ratings"
    )
    rating_user = db.relationship("User", foreign_keys=[rating_user_id], lazy=True)

    def __repr__(self):
        return f"<UserRating from {self.rating_user_id} to {self.rated_user_id} = {self.rating_value}>"


class UserReview(db.Model):
    __tablename__ = "user_reviews"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    reviewer_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )  # Who gave the review
    reviewed_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )  # User receiving the review
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("transactions.id"), nullable=True
    )  # New column
    coffee_transaction = db.Column(
        db.Integer, db.ForeignKey("transactions.id"), nullable=True
    )
    rating = db.Column(db.Integer, nullable=True)  # Rating 1-5
    comment = db.Column(db.Text, nullable=True)  # Text comment
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "reviewer_id",
            "reviewed_user_id",
            "transaction_id",
            name="user_reviews_unique_review",
        ),
    )

    reviewer = db.relationship(
        "User", foreign_keys=[reviewer_id], backref="reviews_given"
    )
    reviewed_user = db.relationship(
        "User", foreign_keys=[reviewed_user_id], backref="reviews_received"
    )


class AdminMessage(db.Model):
    __tablename__ = "admin_messages"

    id = db.Column(db.Integer, primary_key=True)
    message_text = db.Column(db.Text, nullable=False)
    link_url = db.Column(db.String(255), nullable=True)  # Optional link
    link_text = db.Column(db.String(255), nullable=True)  # Button text
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FeatureAccess(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    feature_name = db.Column(db.String(255), nullable=False)
    access_mode = db.Column(db.String(50), default=None)


class UserTourProgress(db.Model):
    """
    Table for tracking user tour progress across different pages.
    """
    __tablename__ = "user_tour_progress"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    index_timestamp = db.Column(db.DateTime(timezone=True), nullable=True)
    coupon_detail_timestamp = db.Column(db.DateTime(timezone=True), nullable=True)
    add_coupon_timestamp = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", backref=db.backref("tour_progress", uselist=False))
