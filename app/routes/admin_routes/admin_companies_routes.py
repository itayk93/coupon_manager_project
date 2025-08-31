import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Company, AdminSettings
from app.forms import CompanyManagementForm, DeleteCompanyForm
from app.utils.logo_fetcher import fetch_company_logo_auto_approve, fetch_company_logo
from app.utils.logo_fetcher import LogoFetcher

logger = logging.getLogger(__name__)

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


@admin_companies_bp.route("/find_logo/<int:company_id>", methods=["GET"])
@login_required
def find_logo_for_approval(company_id):
    """Find logo for a specific company and show approval screen"""
    if not current_user.is_admin:
        flash("אין לך הרשאה לביצוע פעולה זו.", "danger")
        return redirect(url_for("index"))

    company = Company.query.get_or_404(company_id)
    
    try:
        # Fetch logo info (without saving to database yet)
        logo_info = fetch_company_logo(company.name, company.id)
        
        if logo_info and logo_info.get('success'):
            # Store logo info in session for approval
            from flask import session
            session[f'pending_logo_{company_id}'] = logo_info
            
            return render_template(
                "admin/logo_approval.html",
                company=company,
                logo_info=logo_info
            )
        else:
            flash(f"לא נמצא לוגו עבור החברה '{company.name}'", "warning")
            return redirect(url_for("admin_companies_bp.manage_companies"))
            
    except Exception as e:
        flash(f"שגיאה בחיפוש לוגו: {str(e)}", "danger")
        return redirect(url_for("admin_companies_bp.manage_companies"))


@admin_companies_bp.route("/approve_logo/<int:company_id>", methods=["POST"])
@login_required
def approve_logo(company_id):
    """Approve and save the found logo"""
    if not current_user.is_admin:
        flash("אין לך הרשאה לביצוע פעולה זו.", "danger")
        return redirect(url_for("index"))

    from flask import session
    logo_info = session.get(f'pending_logo_{company_id}')
    
    if not logo_info:
        flash("לא נמצא לוגו ממתין לאישור", "warning")
        return redirect(url_for("admin_companies_bp.manage_companies"))

    try:
        # Approve and save the logo
        fetcher = LogoFetcher()
        success = fetcher.approve_and_save_logo(logo_info)
        
        if success:
            flash(f"הלוגו עבור '{logo_info['company_name']}' אושר ונשמר בהצלחה!", "success")
            # Clean up session
            session.pop(f'pending_logo_{company_id}', None)
        else:
            flash("שגיאה בשמירת הלוגו", "danger")
            
    except Exception as e:
        flash(f"שגיאה באישור הלוגו: {str(e)}", "danger")
    
    return redirect(url_for("admin_companies_bp.manage_companies"))


@admin_companies_bp.route("/reject_logo/<int:company_id>", methods=["POST"])
@login_required
def reject_logo(company_id):
    """Reject the found logo and set default"""
    if not current_user.is_admin:
        flash("אין לך הרשאה לביצוע פעולה זו.", "danger")
        return redirect(url_for("index"))

    from flask import session
    logo_info = session.get(f'pending_logo_{company_id}')
    
    if not logo_info:
        flash("לא נמצא לוגו ממתין לאישור", "warning")
        return redirect(url_for("admin_companies_bp.manage_companies"))

    try:
        # Set default logo
        fetcher = LogoFetcher()
        fetcher.update_company_logo_path(company_id, "images/default_logo.png")
        
        # Remove the downloaded logo file
        import os
        logo_file_path = os.path.join(fetcher.static_images_path, logo_info['logo_path'].replace('images/', ''))
        if os.path.exists(logo_file_path):
            os.remove(logo_file_path)
        
        flash(f"הלוגו עבור '{logo_info['company_name']}' נדחה ונקבע לוגו ברירת מחדל", "info")
        
        # Clean up session
        session.pop(f'pending_logo_{company_id}', None)
        
    except Exception as e:
        flash(f"שגיאה בדחיית הלוגו: {str(e)}", "danger")
    
    return redirect(url_for("admin_companies_bp.manage_companies"))


@admin_companies_bp.route("/upload_logo/<int:company_id>", methods=["POST"])
@login_required
def upload_logo(company_id):
    """Handle manual logo upload for a company"""
    if not current_user.is_admin:
        flash("אין לך הרשאה לביצוע פעולה זו.", "danger")
        return redirect(url_for("index"))

    company = Company.query.get_or_404(company_id)
    
    # Check if file was uploaded
    if 'logo_file' not in request.files:
        flash("לא נבחר קובץ להעלאה", "danger")
        return redirect(url_for("admin_companies_bp.manage_companies"))
    
    file = request.files['logo_file']
    
    # Check if file is empty
    if file.filename == '':
        flash("לא נבחר קובץ להעלאה", "danger")
        return redirect(url_for("admin_companies_bp.manage_companies"))
    
    try:
        # Import image processing utilities
        from app.utils.logo_fetcher import LogoFetcher
        from PIL import Image
        from werkzeug.utils import secure_filename
        import os
        
        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'webp'}
        if not ('.' in file.filename and 
                file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
            flash("סוג קובץ לא נתמך. אנא העלה PNG, JPG, JPEG או WebP", "danger")
            return redirect(url_for("admin_companies_bp.manage_companies"))
        
        # Read file content
        file_content = file.read()
        
        # Validate file size (5MB)
        if len(file_content) > 5 * 1024 * 1024:
            flash("גודל הקובץ חייב להיות פחות מ-5MB", "danger")
            return redirect(url_for("admin_companies_bp.manage_companies"))
        
        # Process and save the image
        try:
            fetcher = LogoFetcher()
        except Exception as e:
            logger.error(f"Failed to initialize LogoFetcher: {e}")
            flash(f"שגיאה בהכנת תיקיית התמונות: {str(e)}", "danger")
            return redirect(url_for("admin_companies_bp.manage_companies"))
        
        # Create a unique filename
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        safe_name = "".join(c for c in company.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_name = safe_name.replace(' ', '_').lower()[:50]
        filename = f"{safe_name}_{company_id}_manual.{file_extension}"
        
        # Process the image (resize to 128x128, convert to PNG)
        from io import BytesIO
        image = Image.open(BytesIO(file_content))
        
        # Convert to RGB if necessary (for PNG with transparency)
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Resize image
        image = image.resize((128, 128), Image.Resampling.LANCZOS)
        
        # Save image
        file_path = os.path.join(fetcher.static_images_path, filename)
        try:
            image.save(file_path, 'PNG', optimize=True)
            logger.info(f"Logo file saved successfully: {file_path}")
            
            # Verify file was actually created
            if not os.path.exists(file_path):
                raise Exception(f"File was not created: {file_path}")
                
        except Exception as e:
            logger.error(f"Failed to save image file: {e}")
            flash(f"שגיאה בשמירת קובץ התמונה: {str(e)}", "danger")
            return redirect(url_for("admin_companies_bp.manage_companies"))
        
        # Update database
        relative_path = f"images/{filename}"
        success = fetcher.update_company_logo_path(company_id, relative_path)
        
        if success:
            flash(f"לוגו עבור '{company.name}' הועלה ונשמר בהצלחה!", "success")
        else:
            flash("שגיאה בשמירת הלוגו למסד הנתונים", "danger")
            # Clean up file if database update failed
            if os.path.exists(file_path):
                os.remove(file_path)
                
    except Exception as e:
        flash(f"שגיאה בעיבוד הקובץ: {str(e)}", "danger")
    
    return redirect(url_for("admin_companies_bp.manage_companies"))
