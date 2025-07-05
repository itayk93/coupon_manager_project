# app/__init__.py

import os
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, url_for, request
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from app.routes.coupons_routes import to_israel_time_filter  # Import the function
from scheduler_config import configure_scheduler
from app.helpers import has_feature_access


# Import configurations and "extensions"
from app.config import Config
from app.extensions import db, login_manager, csrf, migrate

# Example models
from app.models import User, Coupon

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

# Import the Scheduler
from scheduler_config import (
    configure_scheduler,
)  # ← Changed import according to file location


def create_app():
    # Load environment variables (for extra safety, can also be in wsgi.py)
    load_dotenv()

    import os

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    app = Flask(__name__, static_folder="static", template_folder="templates")

    app.config["GA_TRACKING_ID"] = os.getenv("GA_TRACKING_ID", "")
    app.config["CLARITY_PROJECT_ID"] = os.getenv("CLARITY_PROJECT_ID", "")

    @app.context_processor
    def inject_tracking_ids():
        return dict(
            ga_tracking_id=app.config["GA_TRACKING_ID"],
            clarity_project_id=app.config["CLARITY_PROJECT_ID"],
        )

    # Load configuration (Config) from config.py
    app.config.from_object(Config)

    # Set log level (debug etc.)
    app.logger.setLevel(logging.DEBUG)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_message = "עליך להתחבר כדי לגשת לעמוד זה"
    login_manager.login_message_category = (
        "warning"  # Can be changed to 'info', 'danger', 'success'
    )
    login_manager.login_view = "auth.login"
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register Israel time filter
    from app.routes.coupons_routes import to_israel_time_filter

    app.add_template_filter(to_israel_time_filter, "to_israel_time")

    # Register Blueprints
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
    from app.routes.admin_routes.admin_newsletter_routes import admin_newsletter_bp
    from app.extensions import google_bp
    from app.routes.telegram_routes import telegram_bp
    from app.routes.statistics_routes import statistics_bp
    from app.routes.sharing_routes import sharing_bp

    # from app.routes.profile_routes import profile_bp

    app.register_blueprint(google_bp, url_prefix="/login")  # ✅ Added Google Login here!
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
    app.register_blueprint(admin_bp, url_prefix="/admin")
    # app.register_blueprint(profile_bp, url_prefix='/')
    app.register_blueprint(admin_dashboard_bp, url_prefix="/admin")
    app.register_blueprint(admin_messages_bp)
    app.register_blueprint(admin_newsletter_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(telegram_bp)
    app.register_blueprint(statistics_bp)
    app.register_blueprint(sharing_bp)

    # If needed - create instance folder
    if not os.path.exists("instance"):
        os.makedirs("instance")

    # Run operations with context
    with app.app_context():
        db.create_all()

        # Create uploads folder
        try:
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            logger.info(f"יצירת תיקיית ההעלאה: {app.config['UPLOAD_FOLDER']}")
        except Exception as e:
            logger.error(f"שגיאה ביצירת תיקיית ההעלאה: {e}")

    # 📌 Call the scheduler **only after the application is loaded**
    from scheduler_config import configure_scheduler

    configure_scheduler()

    @app.context_processor
    def utility_processor():
        def generate_unsubscribe_token(user):
            """יצירת טוקן לביטול הרשמה"""
            return str(abs(hash(f"{user.email}{user.id}")))[:10]

        def generate_preferences_token(user):
            """יצירת טוקן לעדכון העדפות"""
            return str(abs(hash(f"{user.email}{user.id}preferences")))[:10]
            
        return dict(
            has_feature_access=has_feature_access,
            generate_unsubscribe_token=generate_unsubscribe_token,
            generate_preferences_token=generate_preferences_token
        )

    # עקיפת בדיקת CSRF עבור routes של טלגרם רק אם מוגדר
    if not app.config.get('TELEGRAM_CSRF_PROTECTION', False):
        csrf.exempt(telegram_bp)

    return app


def send_expiration_warnings():
    """Sends notifications about coupons that are about to expire, using Flask context."""
    from app import create_app  # Load the application

    app = create_app()

    with app.app_context():
        from app.models import Coupon

        today = datetime.utcnow().date()
        one_month_ahead = today + timedelta(days=30)

        coupons_month = Coupon.query.filter(
            Coupon.expiration == one_month_ahead.strftime("%Y-%m-%d"),
            Coupon.reminder_sent_30_days == False,
        ).all()

        for coupon in coupons_month:
            user = coupon.user
            if user:
                try:
                    expiration_date = coupon.expiration
                    coupon_detail_link = request.host_url.rstrip("/") + url_for(
                        "coupon_detail", id=coupon.id
                    )
                    html_content = render_template(
                        "emails/coupon_expiration_warning.html",
                        user=user,
                        coupon=coupon,
                        expiration_date=expiration_date,
                        coupon_detail_link=coupon_detail_link,
                        days_left=30,
                    )

                    # Send email
                    send_email(
                        sender_email="noreply@couponmasteril.com",
                        sender_name="Coupon Master",
                        recipient_email=user.email,
                        recipient_name=f"{user.first_name} {user.last_name}",
                        subject="התראה על תפוגת קופון - 30 יום נותרו",
                        html_content=html_content,
                    )

                    coupon.reminder_sent_30_days = True
                    db.session.commit()
                    logger.info(
                        f"Sent 30-day expiration warning for coupon {coupon.code} to {user.email}"
                    )

                except Exception as e:
                    logger.error(
                        f"Error sending 30-day expiration warning for coupon {coupon.code}: {e}"
                    )
                    db.session.rollback()
