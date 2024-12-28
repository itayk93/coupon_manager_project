# /Users/itaykarkason/Desktop/coupon_manager_project/app/routes/__init__.py

from .marketplace_routes import marketplace_bp
from .requests_routes import requests_bp
from .transactions_routes import transactions_bp
from .uploads_routes import uploads_bp
from .admin_routes import admin_bp
from .export_routes import export_bp
from .usage_data_routes import usage_data_bp
from app.routes.admin_routes.admin_tags_routes import admin_tags_bp
from app.routes.admin_routes.admin_companies_routes import admin_companies_bp
from app.routes.admin_routes.admin_coupon_tags_routes import admin_coupon_tags_bp

def init_app(app):
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(coupons_bp)
    app.register_blueprint(usage_data_bp)
    app.register_blueprint(admin_tags_bp)
    app.register_blueprint(admin_companies_bp)
    app.register_blueprint(admin_coupon_tags_bp)
