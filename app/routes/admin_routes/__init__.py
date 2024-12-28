from flask import Blueprint
from flask_login import login_required, current_user
from .admin_tags_routes import admin_tags_bp
from .admin_companies_routes import admin_companies_bp
from .admin_coupon_tags_routes import admin_coupon_tags_bp

admin_bp = Blueprint('admin_routes', __name__)

# רישום כל ה-blueprints בתוך admin_bp
admin_bp.register_blueprint(admin_tags_bp, url_prefix='/tags')
admin_bp.register_blueprint(admin_companies_bp, url_prefix='/companies')
admin_bp.register_blueprint(admin_coupon_tags_bp, url_prefix='/coupon-tags')
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

# יצירת ה-Blueprint
admin_bp = Blueprint('admin_bp', __name__, url_prefix='/admin')

@admin_bp.route('/dashboard', methods=['GET'])
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בעמוד זה.', 'danger')
        return redirect(url_for('index'))

    return render_template('admin/admin_dashboard.html')
