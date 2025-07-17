from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import AdminSettings, User, db

admin_whatsapp_banner_bp = Blueprint("admin_whatsapp_banner_bp", __name__)


@admin_whatsapp_banner_bp.route("/whatsapp-banner", methods=["GET", "POST"])
@login_required
def admin_whatsapp_banner():
    """
    עמוד אדמין לניהול הגדרות WhatsApp banner
    """
    if not current_user.is_admin:
        flash("אין לך הרשאה לצפות בעמוד זה.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        # עדכון הגדרת ברירת המחדל למשתמשים חדשים
        default_value = request.form.get("default_whatsapp_banner", "false") == "true"
        
        AdminSettings.set_setting(
            key="default_whatsapp_banner_for_new_users",
            value=default_value,
            setting_type="boolean",
            description="ברירת המחדל להצגת בנר WhatsApp למשתמשים חדשים"
        )
        
        flash("הגדרות WhatsApp banner עודכנו בהצלחה!", "success")
        return redirect(url_for("admin_bp.admin_whatsapp_banner_bp.admin_whatsapp_banner"))

    # קבלת הגדרה נוכחית
    default_banner = AdminSettings.get_setting("default_whatsapp_banner_for_new_users", True)
    
    return render_template(
        "admin/admin_whatsapp_banner.html",
        default_banner=default_banner
    )


@admin_whatsapp_banner_bp.route("/whatsapp-banner/users", methods=["GET", "POST"])
@login_required
def admin_whatsapp_banner_users():
    """
    עמוד אדמין לניהול הגדרות WhatsApp banner עבור משתמשים קיימים
    """
    if not current_user.is_admin:
        flash("אין לך הרשאה לצפות בעמוד זה.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        # עדכון הגדרות עבור משתמשים ספציפיים
        for user_id in request.form.getlist("user_ids"):
            show_banner = f"user_{user_id}_banner" in request.form
            user = User.query.get(int(user_id))
            if user:
                user.show_whatsapp_banner = show_banner
        
        db.session.commit()
        flash("הגדרות WhatsApp banner עבור המשתמשים עודכנו בהצלחה!", "success")
        return redirect(url_for("admin_bp.admin_whatsapp_banner_bp.admin_whatsapp_banner_users"))

    # קבלת כל המשתמשים
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "", type=str)
    
    users_query = User.query.filter(User.is_deleted == False)
    
    if search:
        users_query = users_query.filter(
            db.or_(
                User.first_name.contains(search),
                User.last_name.contains(search),
                User.email.contains(search)
            )
        )
    
    users = users_query.paginate(
        page=page,
        per_page=20,
        error_out=False
    )
    
    return render_template(
        "admin/admin_whatsapp_banner_users.html",
        users=users,
        search=search
    )


@admin_whatsapp_banner_bp.route("/whatsapp-banner/bulk-update", methods=["POST"])
@login_required
def bulk_update_whatsapp_banner():
    """
    עדכון מסיבי של הגדרות WhatsApp banner
    """
    if not current_user.is_admin:
        flash("אין לך הרשאה לבצע פעולה זו.", "danger")
        return redirect(url_for("index"))

    action = request.form.get("action")
    
    if action == "enable_all":
        User.query.filter(User.is_deleted == False).update({"show_whatsapp_banner": True})
        flash("בנר WhatsApp הופעל עבור כל המשתמשים!", "success")
    elif action == "disable_all":
        User.query.filter(User.is_deleted == False).update({"show_whatsapp_banner": False})
        flash("בנר WhatsApp בוטל עבור כל המשתמשים!", "success")
    
    db.session.commit()
    return redirect(url_for("admin_bp.admin_whatsapp_banner_bp.admin_whatsapp_banner_users"))