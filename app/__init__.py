# app/__init__.py

import os
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, url_for
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from app.routes.coupons_routes import to_israel_time_filter  # Import the function
from scheduler_config import configure_scheduler

# ייבוא הגדרות ו"הרחבות"
from app.config import Config
from app.extensions import db, login_manager, csrf, migrate

# מודלים לדוגמה
from app.models import User, Coupon

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

# ייבוא ה-Scheduler
from scheduler_config import configure_scheduler  # ← שינוי הייבוא בהתאם למיקום הקובץ

def create_app():
    # טוען משתני סביבה (ליתר ביטחון, אפשר גם ב-wsgi.py)
    load_dotenv()

    import os
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    app = Flask(__name__, static_folder='static', template_folder='templates')

    app.config['GA_TRACKING_ID'] = os.getenv("GA_TRACKING_ID", "")
    app.config['CLARITY_PROJECT_ID'] = os.getenv("CLARITY_PROJECT_ID", "")  # ✅ תיקון כאן!

    @app.context_processor
    def inject_tracking_ids():
        return dict(
            ga_tracking_id=app.config['GA_TRACKING_ID'],
            clarity_project_id=app.config['CLARITY_PROJECT_ID']  # ✅ עכשיו זה נטען נכון
        )


    # טוען קונפיגורציה (Config) מהקובץ config.py
    app.config.from_object(Config)

    # הגדרת רמת הלוגים (debug וכו')
    app.logger.setLevel(logging.DEBUG)


    # אתחול ההרחבות
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_message = "עליך להתחבר כדי לגשת לעמוד זה"
    login_manager.login_message_category = "warning"  # אפשר לשנות ל-'info', 'danger', 'success'
    login_manager.login_view = 'auth.login'
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # רישום פילטר לזמן ישראל
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
    from app.routes.admin_routes.admin_dashboard_routes import admin_dashboard_bp
    from app.routes.admin_routes.admin_messages_routes import admin_messages_bp
    from app.extensions import google_bp
    # from app.routes.profile_routes import profile_bp

    app.register_blueprint(google_bp, url_prefix="/login")  # ✅ הוספנו את Google Login כאן!
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
    # app.register_blueprint(profile_bp, url_prefix='/')
    app.register_blueprint(admin_dashboard_bp, url_prefix="/admin")
    app.register_blueprint(admin_messages_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")


    # אם צריך - יצירת תיקיית instance
    if not os.path.exists('instance'):
        os.makedirs('instance')

    # הרצת פעולות עם context
    with app.app_context():
        db.create_all()

        # יצירת תיקיית העלאות
        try:
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            logger.info(f"יצירת תיקיית ההעלאה: {app.config['UPLOAD_FOLDER']}")
        except Exception as e:
            logger.error(f"שגיאה ביצירת תיקיית ההעלאה: {e}")

    # 📌 קרא למתזמן **רק אחרי שהאפליקציה נטענה**
    from scheduler_config import configure_scheduler
    configure_scheduler()

    return app


def send_expiration_warnings():
    """שולחת התראות על קופונים שעומדים לפוג, תוך שימוש בקונטקסט של Flask."""
    from app import create_app  # טעינת האפליקציה
    app = create_app()

    with app.app_context():
        from app.models import Coupon
        today = datetime.utcnow().date()
        one_month_ahead = today + timedelta(days=30)

        coupons_month = Coupon.query.filter(
            Coupon.expiration == one_month_ahead.strftime('%Y-%m-%d'),
            Coupon.reminder_sent_30_days == False
        ).all()
        
        for coupon in coupons_month:
            user = coupon.user
            if user:
                try:
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

                    # שליחת המייל
                    send_email(
                        sender_email="CouponMasterIL2@gmail.com",
                        sender_name="Coupon Master",
                        recipient_email=user.email,
                        recipient_name=f"{user.first_name} {user.last_name}",
                        subject="התראה על תפוגת קופון - 30 יום נותרו",
                        html_content=html_content
                    )

                    coupon.reminder_sent_30_days = True
                    db.session.commit()
                    logger.info(f"Sent 30-day expiration warning for coupon {coupon.code} to {user.email}")

                except Exception as e:
                    logger.error(f"Error sending 30-day expiration warning for coupon {coupon.code}: {e}")
                    db.session.rollback()
