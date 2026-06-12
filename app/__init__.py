# app/__init__.py

import os
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, url_for, request, Response
from dotenv import load_dotenv

# Import configurations and "extensions"
from app.config import Config
from app.extensions import db, login_manager, csrf, migrate, cache

# Example models
from app.models import User, Coupon

# NOTE: route modules (coupons_routes, helpers) are intentionally imported
# inside create_app() — importing them at module level creates circular-import
# fragility because they import from this package in turn.

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app():
    # Load environment variables (for extra safety, can also be in wsgi.py)
    load_dotenv()

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

    # Never allow insecure OAuth transport in production unless explicitly enabled.
    if app.config.get("ALLOW_INSECURE_OAUTH_TRANSPORT"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    # Set log level (debug etc.)
    app.logger.setLevel(logging.DEBUG)

    # Initialize extensions
    db.init_app(app)
    
    # Force SQLAlchemy to configure models immediately to avoid race conditions/deadlocks in Gunicorn
    try:
        from sqlalchemy.orm import configure_mappers
        configure_mappers()
    except Exception as e:
        app.logger.error(f"Error configuring mappers: {e}")

    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_message = "עליך להתחבר כדי לגשת לעמוד זה"
    login_manager.login_message_category = (
        "warning"  # Can be changed to 'info', 'danger', 'success'
    )
    login_manager.login_view = "auth.login"
    csrf.init_app(app)
    cache.init_app(app)

    # Safety net: a request that died mid-transaction must not leave the
    # session in a failed state for the next request on the same worker
    # (PendingRollbackError).
    @app.teardown_request
    def rollback_failed_session(exc):
        if exc is not None:
            try:
                db.session.rollback()
            except Exception:
                logger.exception("Rollback after failed request raised")

    # Configure browser cache headers and baseline security headers
    @app.after_request
    def add_cache_and_security_headers(response):
        # Cache static files for 1 year
        if request.endpoint == 'static':
            response.cache_control.max_age = 31536000  # 1 year
            response.cache_control.public = True
        # Cache API responses for 5 minutes
        elif request.path.startswith('/api/'):
            response.cache_control.max_age = 300  # 5 minutes

        if app.config.get("ENABLE_SECURITY_HEADERS", True):
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault(
                "Permissions-Policy",
                "geolocation=(), microphone=(), camera=(), payment=()",
            )
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "img-src 'self' data: https:; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
                "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
                "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com https://www.clarity.ms https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
                "connect-src 'self' https://www.google-analytics.com https://www.clarity.ms; "
                "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'",
            )
            if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    "max-age=31536000; includeSubDomains; preload",
                )
        return response

    @app.route("/robots.txt")
    def robots_txt():
        return app.send_static_file("robots.txt")

    @app.route("/sitemap.xml")
    def sitemap_xml():
        pages = [
            url_for("auth.login", _external=True),
            url_for("auth.register", _external=True),
            url_for("auth.forgot_password", _external=True),
            url_for("auth.privacy_policy", _external=True),
            url_for("profile.faq", _external=True),
        ]
        xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
        for page in pages:
            xml.append(f"<url><loc>{page}</loc></url>")
        xml.append("</urlset>")
        return Response("\n".join(xml), mimetype="application/xml")

    @app.route("/privacy-policy")
    def privacy_policy_root():
        return render_template("privacy_policy.html")

    @app.route("/favicon.ico")
    def favicon_ico():
        return app.send_static_file("icons/favicon-32x32.png")

    @app.route("/apple-touch-icon.png")
    def apple_touch_icon():
        return app.send_static_file("icons/apple-touch-icon.png")

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
    from app.routes.admin_routes.admin_scheduler_routes import admin_scheduler_bp
    from app.extensions import google_bp
    from app.routes.telegram_routes import telegram_bp
    from app.routes.statistics_routes import statistics_bp
    from app.routes.sharing_routes import sharing_bp
    from app.routes.cron_routes import cron_bp
    from app.routes.api_routes import api_bp

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
    app.register_blueprint(admin_scheduler_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(telegram_bp)
    app.register_blueprint(statistics_bp)
    app.register_blueprint(sharing_bp)
    app.register_blueprint(cron_bp)
    app.register_blueprint(api_bp)

    # If needed - create instance folder
    if not os.path.exists("instance"):
        os.makedirs("instance")

    # Run operations with context
    with app.app_context():
        # Schema is managed by Flask-Migrate (flask db upgrade) in production.
        # create_all() is kept only for local SQLite development and tests,
        # where there is no migration step; running it against Postgres would
        # bypass migrations and cause schema drift.
        if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
            db.create_all()

        # Create uploads folder
        try:
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            logger.info(f"יצירת תיקיית ההעלאה: {app.config['UPLOAD_FOLDER']}")
        except Exception as e:
            logger.error(f"שגיאה ביצירת תיקיית ההעלאה: {e}")

    # Scheduler functionality removed - now using external cron jobs

    @app.context_processor
    def utility_processor():
        from app.helpers import has_feature_access
        from app.utils.tokens import (
            generate_unsubscribe_token,
            generate_preferences_token,
        )

        return dict(
            has_feature_access=has_feature_access,
            generate_unsubscribe_token=generate_unsubscribe_token,
            generate_preferences_token=generate_preferences_token
        )

    # Register template helpers for caching
    from app.template_helpers import register_template_helpers
    register_template_helpers(app)

    # Cron endpoints are machine-to-machine and must not require CSRF tokens.
    # (They are protected via API tokens / secrets instead.)
    # A failure here must abort startup: silently keeping CSRF on these
    # endpoints would break the external cron jobs without any visible error.
    from app.routes.coupons_routes import api_update_multipass
    csrf.exempt(api_update_multipass)

    from app.routes.admin_routes.admin_scheduled_emails_routes import (
        cron_send_pending_emails,
        cron_send_expiration_reminders,
    )
    csrf.exempt(cron_send_pending_emails)
    csrf.exempt(cron_send_expiration_reminders)

    # עקיפת בדיקת CSRF עבור routes של טלגרם רק אם מוגדר
    if not app.config.get('TELEGRAM_CSRF_PROTECTION', False):
        csrf.exempt(telegram_bp)

    # הפעלת מערכת התזמון (opt-in בלבד; ברירת המחדל היא cron חיצוני).
    # נעילה בין-תהליכית מבטיחה שרק worker אחד של gunicorn מריץ את ה-scheduler,
    # אחרת כל משימה הייתה רצה פעם אחת לכל worker (מיילים כפולים וכו').
    if app.config.get("ENABLE_SCHEDULER", False) and not app.config.get("TESTING"):
        try:
            from app.utils.process_lock import acquire_singleton_lock

            if acquire_singleton_lock("task_scheduler"):
                from app.scheduler import TaskScheduler
                scheduler = TaskScheduler(app)
                scheduler.start()
                app.logger.info("✅ Task scheduler started successfully")
            else:
                app.logger.info("Task scheduler already running in another worker")
        except Exception as e:
            app.logger.error(f"❌ Failed to start task scheduler: {e}")

    return app
