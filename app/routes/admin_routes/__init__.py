from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

# ייבוא ה-Blueprints הקיימים
from .admin_tags_routes import admin_tags_bp
from .admin_companies_routes import admin_companies_bp
from .admin_coupon_tags_routes import admin_coupon_tags_bp
from .admin_users_routes import admin_users_bp
from .admin_coupons import admin_coupons_bp
from .admin_messages_routes import admin_messages_bp
from .admin_whatsapp_banner_routes import admin_whatsapp_banner_bp
from .admin_email_routes import admin_email_bp
from .admin_scheduled_emails_routes import admin_scheduled_emails_bp

# יצירת ה-Blueprint הראשי עבור /admin
admin_bp = Blueprint("admin_bp", __name__, url_prefix="/admin")

# רישום כל ה-blueprints תחת admin_bp
admin_bp.register_blueprint(admin_tags_bp, url_prefix="/tags")
admin_bp.register_blueprint(admin_companies_bp, url_prefix="/companies")
admin_bp.register_blueprint(admin_coupon_tags_bp, url_prefix="/coupon-tags")
admin_bp.register_blueprint(admin_users_bp, url_prefix="/users")
admin_bp.register_blueprint(
    admin_coupons_bp, url_prefix="/coupons"
)  # ← רישום ניהול קופונים אוטומטיים
admin_bp.register_blueprint(admin_messages_bp)
admin_bp.register_blueprint(admin_whatsapp_banner_bp)
admin_bp.register_blueprint(admin_email_bp, url_prefix="/email")
admin_bp.register_blueprint(admin_scheduled_emails_bp, url_prefix="/scheduled-emails")


@admin_bp.route("/dashboard", methods=["GET"])
@login_required
def admin_dashboard():
    """
    עמוד הדשבורד הראשי לאדמין.
    """
    if not current_user.is_admin:
        flash("אין לך הרשאה לצפות בעמוד זה.", "danger")
        return redirect(url_for("index"))

    return render_template("admin/admin_dashboard.html")
