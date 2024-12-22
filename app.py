import os
import logging
from datetime import datetime, timedelta
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from app.extensions import db, login_manager, csrf
from app.models import User, Tag

# טעינת משתני סביבה
load_dotenv()

app = Flask(__name__)
# הגדרת הרמה של ה-logger של האפליקציה עצמה
app.logger.setLevel(logging.DEBUG)

# הגדרות תצורה
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['WTF_CSRF_ENABLED'] = True
app.config['SECURITY_PASSWORD_SALT'] = os.getenv('SECURITY_PASSWORD_SALT')
ALLOWED_EXTENSIONS = {'xlsx'}

# אתחול הרחבות
db.init_app(app)
migrate = Migrate(app, db)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'  # נניח שה-login route נמצא ב-auth_routes
csrf.init_app(app)

import logging

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ייבוא ה-Blueprints
from app.routes.auth_routes import auth_bp
from app.routes.profile_routes import profile_bp
from app.routes.coupons_routes import coupons_bp
from app.routes.marketplace_routes import marketplace_bp
from app.routes.requests_routes import requests_bp
from app.routes.transactions_routes import transactions_bp
from app.routes.export_routes import export_bp
from app.routes.uploads_routes import uploads_bp
from app.routes.admin_routes import admin_bp

# רישום ה-Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(coupons_bp)
app.register_blueprint(marketplace_bp)
app.register_blueprint(requests_bp)
app.register_blueprint(transactions_bp)
app.register_blueprint(export_bp)
app.register_blueprint(uploads_bp)
app.register_blueprint(admin_bp)

# יצירת תיקיית instance אם לא קיימת
if not os.path.exists('instance'):
    os.makedirs('instance')

with app.app_context():
    db.create_all()
    # תגיות מוגדרות מראש
    predefined_tags = [
        {'name': 'מבצע', 'count': 10},
        {'name': 'הנחה', 'count': 8},
        {'name': 'חדש', 'count': 5},
    ]
    for tag_data in predefined_tags:
        tag = Tag.query.filter_by(name=tag_data['name']).first()
        if not tag:
            tag = Tag(name=tag_data['name'], count=tag_data['count'])
            db.session.add(tag)
            logging.info(f"נוספה תגית חדשה: {tag.name}")
        else:
            if tag.count != tag_data['count']:
                tag.count = tag_data['count']
                logging.info(f"עודכנה ספירת תגית: {tag.name} ל-{tag.count}")
    db.session.commit()

try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    logging.info(f"יצירת תיקיית ההעלאה: {app.config['UPLOAD_FOLDER']}")
except Exception as e:
    logging.error(f"שגיאה ביצירת תיקיית ההעלאה: {e}")

# הגדרת Scheduler
scheduler = BackgroundScheduler()


def send_expiration_warnings():
    """פונקציה לבדיקת קופונים ולשליחת התראות לפני תפוגה."""
    with app.app_context():
        today = datetime.utcnow().date()
        one_month_ahead = today + timedelta(days=30)
        one_week_ahead = today + timedelta(days=7)
        one_day_ahead = today + timedelta(days=1)

        # התראות חודש לפני תפוגה
        coupons_month = Coupon.query.filter(
            Coupon.expiration == one_month_ahead.strftime('%Y-%m-%d'),
            Coupon.reminder_sent_30_days == False  # וידוא שיש את השדה במסד הנתונים
        ).all()

        for coupon in coupons_month:
            user = coupon.user
            if user:
                try:
                    expiration_date = coupon.expiration
                    coupon_detail_link = url_for('coupon_detail', id=coupon.id, _external=True)

                    # יצירת תוכן המייל
                    html_content = render_template(
                        'emails/coupon_expiration_warning.html',
                        user=user,
                        coupon=coupon,
                        expiration_date=expiration_date,
                        coupon_detail_link=coupon_detail_link,
                        days_left=30  # ציון המספר 30 עבור התראה חודש מראש
                    )

                    # שליחת המייל
                    send_email(
                        sender_email=os.getenv('SENDER_EMAIL'),
                        sender_name='MaCoupon',
                        recipient_email=user.email,
                        recipient_name=f'{user.first_name} {user.last_name}',
                        subject='התראה על תפוגת תוקף קופון - חודש אחד נותר',
                        html_content=html_content
                    )

                    # עדכון מצב השליחה
                    coupon.reminder_sent_30_days = True
                    db.session.commit()

                    logger.info(f"Sent 30-day expiration warning for coupon {coupon.code} to {user.email}")
                except Exception as e:
                    logger.error(f"Error sending 30-day expiration warning for coupon {coupon.code}: {e}")
                    db.session.rollback()

        # התראות שבוע לפני תפוגה
        coupons_week = Coupon.query.filter(
            Coupon.expiration == one_week_ahead.strftime('%Y-%m-%d'),
            Coupon.reminder_sent_7_days == False
        ).all()

        for coupon in coupons_week:
            user = coupon.user
            if user:
                try:
                    expiration_date = coupon.expiration
                    coupon_detail_link = url_for('coupon_detail', id=coupon.id, _external=True)

                    # יצירת תוכן המייל
                    html_content = render_template(
                        'emails/coupon_expiration_warning.html',
                        user=user,
                        coupon=coupon,
                        expiration_date=expiration_date,
                        coupon_detail_link=coupon_detail_link,
                        days_left=7  # ציון המספר 7 עבור התראה שבוע מראש
                    )

                    # שליחת המייל
                    send_email(
                        sender_email=os.getenv('SENDER_EMAIL'),
                        sender_name='MaCoupon',
                        recipient_email=user.email,
                        recipient_name=f'{user.first_name} {user.last_name}',
                        subject='התראה על תפוגת תוקף קופון - שבוע אחד נותר',
                        html_content=html_content
                    )

                    # עדכון מצב השליחה
                    coupon.reminder_sent_7_days = True
                    db.session.commit()

                    logger.info(f"Sent 7-day expiration warning for coupon {coupon.code} to {user.email}")
                except Exception as e:
                    logger.error(f"Error sending 7-day expiration warning for coupon {coupon.code}: {e}")
                    db.session.rollback()

        # התראות יום לפני תפוגה
        coupons_day = Coupon.query.filter(
            Coupon.expiration == one_day_ahead.strftime('%Y-%m-%d'),
            Coupon.reminder_sent_1_day == False
        ).all()

        for coupon in coupons_day:
            user = coupon.user
            if user:
                try:
                    expiration_date = coupon.expiration
                    coupon_detail_link = url_for('coupon_detail', id=coupon.id, _external=True)

                    # יצירת תוכן המייל
                    html_content = render_template(
                        'emails/coupon_expiration_warning.html',
                        user=user,
                        coupon=coupon,
                        expiration_date=expiration_date,
                        coupon_detail_link=coupon_detail_link,
                        days_left=1  # ציון המספר 1 עבור התראה יום מראש
                    )

                    # שליחת המייל
                    send_email(
                        sender_email=os.getenv('SENDER_EMAIL'),
                        sender_name='MaCoupon',
                        recipient_email=user.email,
                        recipient_name=f'{user.first_name} {user.last_name}',
                        subject='התראה על תפוגת תוקף קופון - יום אחד נותר',
                        html_content=html_content
                    )

                    # עדכון מצב השליחה
                    coupon.reminder_sent_1_day = True
                    db.session.commit()

                    logger.info(f"Sent 1-day expiration warning for coupon {coupon.code} to {user.email}")
                except Exception as e:
                    logger.error(f"Error sending 1-day expiration warning for coupon {coupon.code}: {e}")
                    db.session.rollback()

def configure_scheduler():
    scheduler.add_job(
        func=send_expiration_warnings,
        trigger="interval", days=1,
        id='send_expiration_warnings',
        name='Send expiration warnings',
        replace_existing=True
    )
    scheduler.start()
    logging.info("Scheduler configured and started.")

if __name__ == '__main__':
    if not app.debug or os.environ.get("FLASK_ENV") == "production":
        configure_scheduler()
        logging.info("Scheduler started in production mode.")

    app.run(debug=True)
