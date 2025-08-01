import os
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Company, AdminSettings
from app.forms import CompanyManagementForm, DeleteCompanyForm
from app.utils.logo_fetcher import fetch_company_logo_auto_approve

admin_companies_bp = Blueprint(
    "admin_companies_bp", __name__, url_prefix="/admin/companies"
)


@admin_companies_bp.route("/", methods=["GET", "POST"])
@login_required
def manage_companies():
    if not current_user.is_admin:
        flash("אין לך הרשאה לצפות בעמוד זה.", "danger")
        return redirect(url_for("index"))

    form = CompanyManagementForm()
    delete_form = DeleteCompanyForm()

    if form.validate_on_submit() and "submit" in request.form:
        company_name = form.name.data.strip()
        existing_company = Company.query.filter_by(name=company_name).first()
        if existing_company:
            flash("חברה זו כבר קיימת.", "warning")
            return redirect(url_for("admin_companies_bp.manage_companies"))

        # יצירת חברה חדשה
        new_company = Company(name=company_name)
        db.session.add(new_company)
        db.session.commit()
        
        # ניסיון לחיפוש לוגו אוטומטי
        try:
            logo_success = fetch_company_logo_auto_approve(company_name, new_company.id)
            if logo_success:
                flash(f"חברה חדשה נוספה בהצלחה עם לוגו: {company_name}!", "success")
            else:
                flash(f"חברה חדשה נוספה: {company_name} (לא נמצא לוגו - נקבע לוגו ברירת מחדל)", "warning")
        except Exception as e:
            # במקרה של שגיאה, נוודא שהחברה עדיין נוצרה עם לוגו ברירת מחדל
            new_company.image_path = "images/default_logo.png"
            db.session.commit()
            flash(f"חברה חדשה נוספה: {company_name} (שגיאה בחיפוש לוגו - נקבע לוגו ברירת מחדל)", "warning")
            
        return redirect(url_for("admin_companies_bp.manage_companies"))

    companies = Company.query.order_by(Company.id.asc()).all()
    return render_template(
        "admin/admin_manage_companies.html",
        form=form,
        companies=companies,
        delete_form=delete_form,
    )


@admin_companies_bp.route("/admin/delete_company/<int:company_id>", methods=["POST"])
@login_required
def delete_company(company_id):
    if not current_user.is_admin:
        flash("אין לך הרשאה לביצוע פעולה זו.", "danger")
        return redirect(url_for("index"))

    try:
        # שליפת החברה ומחיקתה
        company = Company.query.get_or_404(company_id)
        db.session.delete(company)
        db.session.commit()
        flash(f'חברה "{company.name}" נמחקה בהצלחה.', "success")
    except Exception as e:
        db.session.rollback()
        print(f"Error while deleting company: {e}")
        flash("שגיאה במחיקת החברה.", "danger")

    return redirect(url_for("admin_companies_bp.manage_companies"))


@admin_companies_bp.route("/settings", methods=["GET", "POST"])
@login_required
def company_settings():
    """Manage company-related settings"""
    if not current_user.is_admin:
        flash("אין לך הרשאה לצפות בעמוד זה.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        # Update auto logo fetch setting
        auto_fetch_enabled = request.form.get("auto_fetch_logos") == "on"
        AdminSettings.set_setting(
            "auto_fetch_company_logos", 
            auto_fetch_enabled, 
            setting_type="boolean",
            description="Enable automatic logo fetching when creating new companies"
        )
        db.session.commit()
        
        status = "הופעל" if auto_fetch_enabled else "בוטל"
        flash(f"חיפוש לוגואים אוטומטי {status} בהצלחה!", "success")
        return redirect(url_for("admin_companies_bp.company_settings"))

    # Get current setting
    auto_fetch_enabled = AdminSettings.get_setting("auto_fetch_company_logos", default=True)
    
    return render_template(
        "admin/company_settings.html",
        auto_fetch_enabled=auto_fetch_enabled
    )


@admin_companies_bp.route("/fetch_missing_logos", methods=["POST"])
@login_required  
def fetch_missing_logos():
    """Fetch logos for companies that don't have them"""
    if not current_user.is_admin:
        flash("אין לך הרשאה לביצוע פעולה זו.", "danger")
        return redirect(url_for("index"))

    try:
        # Find companies without logos or with default logo
        companies_without_logos = Company.query.filter(
            (Company.image_path == None) | 
            (Company.image_path == "") |
            (Company.image_path == "default_logo.png") |
            (Company.image_path == "images/default_logo.png")
        ).all()
        
        success_count = 0
        total_count = len(companies_without_logos)
        
        for company in companies_without_logos:
            try:
                if fetch_company_logo_auto_approve(company.name, company.id):
                    success_count += 1
            except Exception as e:
                print(f"Failed to fetch logo for {company.name}: {e}")
                continue
        
        if success_count > 0:
            flash(f"נמצאו לוגואים עבור {success_count} מתוך {total_count} חברות!", "success")
        else:
            flash(f"לא נמצאו לוגואים חדשים עבור {total_count} חברות שנבדקו.", "info")
            
    except Exception as e:
        flash(f"שגיאה בחיפוש לוגואים: {str(e)}", "danger")
    
    return redirect(url_for("admin_companies_bp.manage_companies"))
