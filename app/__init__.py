# app/__init__.py
import os
from flask import Flask
from dotenv import load_dotenv
from .config import Config
from .extensions import db, login_manager, csrf, migrate

def create_app():
    load_dotenv()
    app = Flask(__name__, static_folder='static', template_folder='templates')

    # טעינת קונפיגורציה
    app.config.from_object(Config)

    # אתחול ההרחבות
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    csrf.init_app(app)

    from .models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # רישום ה-blueprints
    from .routes.auth_routes import auth_bp
    from .routes.profile_routes import profile_bp
    from .routes.coupons_routes import coupons_bp
    from .routes.marketplace_routes import marketplace_bp
    from .routes.transactions_routes import transactions_bp
    from .routes.export_routes import export_bp
    from .routes.uploads_routes import uploads_bp
    from .routes.requests_routes import requests_bp
    from .routes.admin_routes import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(coupons_bp)
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(admin_bp)

    return app
