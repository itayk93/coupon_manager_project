# app/__init__.py

import os
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, url_for
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

# ייבוא הגדרות ו"הרחבות"
from app.config import Config
from app.extensions import db, login_manager, csrf, migrate

# לצורכי שליחה (אם יש לך פונקציה send_email וכו')
# from app.mail import send_email

# מודלים לדוגמה
from app.models import User, Tag, Coupon

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def create_app():
    # טוען משתני סביבה (ליתר בטחון, אפשר גם ב-wsgi.py)
    load_dotenv()

    app = Flask(__name__, static_folder='static', template_folder='templates')

    # טוען קונפיגורציה (Config) מהקובץ config.py
    app.config.from_object(Config)

    # הגדרת רמת הלוגים (debug וכו')
    app.logger.setLevel(logging.DEBUG)

    # אתחול ההרחבות
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # רישום הפילטר
    from app.routes.coupons_routes import to_israel_time_filter
    app.add_template_filter(to_israel_time_filter, 'to_israel_time')

    # רישום Blueprints
    from app.routes.auth_routes import auth_bp
    from app.routes.profile_routes import profile_bp
    from app.routes.coupons_routes import coupons_bp
    from app.routes.marketplace_routes import marketplace_bp
    from app.routes.requests_routes import requests_bp
    from app.routes.transactions_routes import transactions_bp
    from app.routes.export_routes import export_bp
    from app.routes.uploads_routes import uploads_bp
    from app.routes.admin_routes import admin_bp
    from app.routes.admin_routes.admin_tags_routes import admin_tags_bp
    from app.routes.admin_routes.admin_companies_routes import admin_companies_bp
    from app.routes.admin_routes.admin_coupon_tags_routes import admin_coupon_tags_bp
    #from app.routes.profile_routes import profile_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(coupons_bp)
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(admin_tags_bp)
    app.register_blueprint(admin_companies_bp)
    app.register_blueprint(admin_coupon_tags_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    #app.register_blueprint(profile_bp, url_prefix='/')

    # אם צריך - יצירת instance folder
    if not os.path.exists('instance'):
        os.makedirs('instance')

    # הרצת פעולות עם context
    with app.app_context():
        db.create_all()

        # יצירת תגיות דוגמה
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
                logger.info(f"נוספה תגית חדשה: {tag.name}")
            else:
                if tag.count != tag_data['count']:
                    tag.count = tag_data['count']
                    logger.info(f"עודכנה ספירת תגית: {tag.name} ל-{tag.count}")
        db.session.commit()

        # יצירת תיקיית העלאות
        try:
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            logger.info(f"יצירת תיקיית ההעלאה: {app.config['UPLOAD_FOLDER']}")
        except Exception as e:
            logger.error(f"שגיאה ביצירת תיקיית ההעלאה: {e}")

    # מגדיר ומפעיל את ה-Scheduler (למשל לשליחת התראות על תפוגה)
    configure_scheduler(app)

    return app

def send_expiration_warnings(app):
    """פונקציה לדוגמה: שולחת התראות על קופונים שעומדים לפוג."""
    with app.app_context():
        today = datetime.utcnow().date()
        one_month_ahead = today + timedelta(days=30)
        one_week_ahead = today + timedelta(days=7)
        one_day_ahead = today + timedelta(days=1)

        # שליחת התראות 30 יום לפני
        coupons_month = Coupon.query.filter(
            Coupon.expiration == one_month_ahead.strftime('%Y-%m-%d'),
            Coupon.reminder_sent_30_days == False
        ).all()
        for coupon in coupons_month:
            user = coupon.user
            if user:
                try:
                    # בונה תוכן מייל לדוגמה
                    expiration_date = coupon.expiration
                    coupon_detail_link = url_for('coupon_detail', id=coupon.id, _external=True)
                    html_content = render_template(
                        'emails/coupon_expiration_warning.html',
                        user=user,
                        coupon=coupon,
                        expiration_date=expiration_date,
                        coupon_detail_link=coupon_detail_link,
                        days_left=30
                    )
                    # send_email(sender_email=os.getenv('SENDER_EMAIL'), ...)

                    coupon.reminder_sent_30_days = True
                    db.session.commit()
                    logger.info(f"Sent 30-day expiration warning for coupon {coupon.code} to {user.email}")
                except Exception as e:
                    logger.error(f"Error sending 30-day expiration warning: {e}")
                    db.session.rollback()

        # דומה גם ל-7 ימים, 1 יום וכו'...

def configure_scheduler(app):
    """מגדיר את כל עבודות ה-Scheduler."""
    # הוספת Job שחוזר כל יום
    scheduler.add_job(
        func=send_expiration_warnings,
        trigger="interval",
        days=1,
        args=[app],  # מוסר את ה־app לפונקציה
        id='send_expiration_warnings',
        name='Send expiration warnings daily',
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler configured and started.")

