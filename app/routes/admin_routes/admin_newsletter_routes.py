# admin_newsletter_routes.py
from flask import Blueprint, redirect, url_for, flash, request, render_template, current_app, jsonify
from flask_login import login_required, current_user
from app.models import Newsletter, NewsletterSending, User
from app.extensions import db
from app.helpers import send_html_email, get_current_month_year_hebrew
import os
from functools import wraps
import logging
from datetime import datetime


def generate_unsubscribe_token(user):
    """יצירת טוקן לביטול הרשמה"""
    return str(abs(hash(f"{user.email}{user.id}")))[:10]

def generate_preferences_token(user):
    """יצירת טוקן לעדכון העדפות"""
    return str(abs(hash(f"{user.email}{user.id}preferences")))[:10]

def generate_unsubscribe_link(user):
    """יצירת קישור ביטול הרשמה עבור משתמש"""
    token = generate_unsubscribe_token(user)
    return f"https://couponmasteril.com{url_for('profile.unsubscribe_newsletter', user_id=user.id, token=token)}"

logger = logging.getLogger(__name__)

admin_newsletter_bp = Blueprint("admin_newsletter_bp", __name__)

# Admin-only decorator
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash("אין לך הרשאה לגשת לעמוד זה.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function

# עמוד ניהול ניוזלטרים
@admin_newsletter_bp.route("/manage", methods=["GET"])
@admin_required
def manage_newsletters():
    """עמוד ניהול ניוזלטרים"""
    newsletters = Newsletter.query.order_by(Newsletter.created_at.desc()).all()
    return render_template("admin/admin_manage_newsletters.html", newsletters=newsletters)

# יצירת ניוזלטר חדש
@admin_newsletter_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create_newsletter():
    """יצירת ניוזלטר חדש"""
    if request.method == "POST":
        title = request.form.get("title")
        newsletter_type = request.form.get("newsletter_type", "structured")
        content = request.form.get("content")
        main_title = request.form.get("main_title")
        additional_title = request.form.get("additional_title")
        telegram_bot_section = request.form.get("telegram_bot_section")
        website_features_section = request.form.get("website_features_section")
        highlight_text = request.form.get("highlight_text")
        custom_html = request.form.get("custom_html")
        show_telegram_button = request.form.get("show_telegram_button") == "on"
        
        if not title:
            flash("יש למלא כותרת לניוזלטר.", "danger")
            return render_template("admin/admin_create_newsletter.html")
        
        if newsletter_type == "structured" and not content:
            flash("יש למלא תוכן עיקרי בניוזלטר מובנה.", "danger")
            return render_template("admin/admin_create_newsletter.html")
        
        if newsletter_type == "custom" and not custom_html:
            flash("יש למלא קוד HTML בניוזלטר מותאם אישית.", "danger")
            return render_template("admin/admin_create_newsletter.html")
        
        # טיפול בתמונה
        image_path = None
        if 'newsletter_image' in request.files:
            file = request.files['newsletter_image']
            if file and file.filename != '':
                # בדיקת סוג הקובץ
                if not file.content_type.startswith('image/'):
                    flash("יש לבחור קובץ תמונה בלבד.", "danger")
                    return render_template("admin/admin_create_newsletter.html")
                
                # יצירת תיקיה לתמונות ניוזלטר אם לא קיימת
                upload_folder = os.path.join(current_app.root_path, 'static', 'newsletter_images')
                os.makedirs(upload_folder, exist_ok=True)
                
                # יצירת שם קובץ ייחודי
                import uuid
                file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
                filename = f"newsletter_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{file_extension}"
                
                # שמירת הקובץ
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                
                image_path = f'newsletter_images/{filename}'
        
        newsletter = Newsletter(
            title=title,
            newsletter_type=newsletter_type,
            content=content if newsletter_type == "structured" else None,
            main_title=main_title if newsletter_type == "structured" else None,
            additional_title=additional_title if newsletter_type == "structured" else None,
            telegram_bot_section=telegram_bot_section if newsletter_type == "structured" else None,
            website_features_section=website_features_section if newsletter_type == "structured" else None,
            highlight_text=highlight_text if newsletter_type == "structured" else None,
            custom_html=custom_html if newsletter_type == "custom" else None,
            image_path=image_path,
            show_telegram_button=show_telegram_button if newsletter_type == "structured" else False,
            created_by=current_user.id
        )
        
        db.session.add(newsletter)
        db.session.commit()
        
        flash(f"ניוזלטר '{title}' נוצר בהצלחה!", "success")
        return redirect(url_for("admin_newsletter_bp.manage_newsletters"))
    
    return render_template("admin/admin_create_newsletter.html")

# עריכת ניוזלטר
@admin_newsletter_bp.route("/edit/<int:newsletter_id>", methods=["GET", "POST"])
@admin_required
def edit_newsletter(newsletter_id):
    """עריכת ניוזלטר קיים"""
    newsletter = Newsletter.query.get_or_404(newsletter_id)
    
    if request.method == "POST":
        newsletter.title = request.form.get("title")
        
        if newsletter.newsletter_type == "structured":
            newsletter.content = request.form.get("content")
            newsletter.telegram_bot_section = request.form.get("telegram_bot_section")
            newsletter.website_features_section = request.form.get("website_features_section")
            newsletter.main_title = request.form.get("main_title")
            newsletter.additional_title = request.form.get("additional_title")
            newsletter.highlight_text = request.form.get("highlight_text")
            newsletter.show_telegram_button = request.form.get("show_telegram_button") == "on"
            
            if not newsletter.title or not newsletter.content:
                flash("יש למלא לפחות כותרת ותוכן עיקרי.", "danger")
                return render_template("admin/admin_edit_newsletter.html", newsletter=newsletter)
        else:
            newsletter.custom_html = request.form.get("custom_html")
            
            if not newsletter.title or not newsletter.custom_html:
                flash("יש למלא לפחות כותרת וקוד HTML.", "danger")
                return render_template("admin/admin_edit_newsletter.html", newsletter=newsletter)
        
        # טיפול בתמונה חדשה
        if 'newsletter_image' in request.files:
            file = request.files['newsletter_image']
            if file and file.filename != '':
                # בדיקת סוג הקובץ
                if not file.content_type.startswith('image/'):
                    flash("יש לבחור קובץ תמונה בלבד.", "danger")
                    return render_template("admin/admin_edit_newsletter.html", newsletter=newsletter)
                
                # מחיקת התמונה הקודמת אם קיימת
                if newsletter.image_path:
                    try:
                        old_image_path = os.path.join(current_app.root_path, 'static', newsletter.image_path)
                        if os.path.exists(old_image_path):
                            os.remove(old_image_path)
                    except Exception as e:
                        current_app.logger.warning(f"Could not delete old image: {e}")
                
                # יצירת תיקיה לתמונות ניוזלטר אם לא קיימת
                upload_folder = os.path.join(current_app.root_path, 'static', 'newsletter_images')
                os.makedirs(upload_folder, exist_ok=True)
                
                # יצירת שם קובץ ייחודי
                import uuid
                file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
                filename = f"newsletter_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{file_extension}"
                
                # שמירת הקובץ
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                
                newsletter.image_path = f'newsletter_images/{filename}'
        
        db.session.commit()
        flash(f"ניוזלטר '{newsletter.title}' עודכן בהצלחה!", "success")
        return redirect(url_for("admin_newsletter_bp.manage_newsletters"))
    
    return render_template("admin/admin_edit_newsletter.html", newsletter=newsletter)

# תצוגה מקדימה של ניוזלטר
@admin_newsletter_bp.route("/preview/<int:newsletter_id>")
@admin_required
def preview_newsletter(newsletter_id):
    """תצוגה מקדימה של ניוזלטר"""
    newsletter = Newsletter.query.get_or_404(newsletter_id)
    
    if newsletter.newsletter_type == "custom":
        # עבור HTML מותאם אישית - החזרת ה-HTML ישירות עם משתנים לדוגמה
        html_content = newsletter.custom_html
        
        # הוספת תמונה וחלק ביטול המנוי לתצוגה המקדימה
        from datetime import datetime
        current_year = datetime.now().year
        
        # תמונה אם קיימת
        image_section = ""
        if newsletter.image_path:
            image_url = f"{url_for('static', filename=newsletter.image_path, _external=True)}"
            image_section = f'''
            <br>
            <!-- Newsletter Image -->
            <div style="text-align: center; margin: 20px 0;">
                <img src="{image_url}" alt="תמונת הניוזלטר" style="max-width: 100%; max-height: 300px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.1);">
            </div>
            '''
        
        unsubscribe_section = f'''
            {image_section}
            <br>
            <!-- Footer -->
            <div style="max-width: 500px; margin: 20px auto; background-color: #34495e; color: #bdc3c7; text-align: center; padding: 18px 25px; border-radius: 10px; font-family: Arial, sans-serif;">
                <p style="margin: 0 0 12px 0; font-size: 14px;"><strong>Coupon Master</strong></p>
                <div style="font-size: 12px; color: #95a5a6; margin: 12px 0;">
                    <p style="margin: 0 0 10px 0;">שלום דוגמה, קיבלת את המייל הזה כי אתה רשום לניוזלטר שלנו.</p>
                    <p style="margin: 0;">
                        <a href="#" style="color: #95a5a6; text-decoration: underline;">ביטול מנוי</a>
                        | 
                        <a href="#" style="color: #95a5a6; text-decoration: underline;">עדכון העדפות</a>
                    </p>
                </div>
                <p style="margin: 12px 0 0 0; font-size: 11px;">© {current_year} Coupon Master. כל הזכויות שמורות.</p>
            </div>
        '''
        
        # בדיקה אם יש כבר </body> או </html> ואם כן, להוסיף לפני זה
        if '</body>' in html_content:
            html_content = html_content.replace('</body>', unsubscribe_section + '</body>')
        elif '</html>' in html_content:
            html_content = html_content.replace('</html>', unsubscribe_section + '</html>')
        else:
            html_content += unsubscribe_section
        
        html_content = html_content.replace("{{ user.first_name }}", "דוגמה")
        html_content = html_content.replace("{{ user.last_name }}", "משתמש")
        html_content = html_content.replace("{{ user.email }}", "example@email.com")
        html_content = html_content.replace("{{ unsubscribe_link }}", "#")
        
        # החלפת URL התמונה אם קיימת
        if newsletter.image_path:
            image_url = f"{url_for('static', filename=newsletter.image_path, _external=True)}"
            logger.info(f"Preview: Replacing newsletter_image_url with: {image_url}")
            html_content = html_content.replace("{{ newsletter_image_url }}", image_url)
        else:
            logger.info("Preview: No image path found, removing newsletter_image_url placeholder")
            html_content = html_content.replace("{{ newsletter_image_url }}", "")
            
        return html_content
    else:
        # עבור ניוזלטר מובנה - יצירת HTML בעזרת החלפת מחרוזות
        from types import SimpleNamespace
        dummy_user = SimpleNamespace(first_name="דוגמה", last_name="משתמש", email="example@email.com", id=1)
        
        def dummy_generate_unsubscribe_token(user):
            return "dummy_token"
        
        def dummy_generate_preferences_token(user):
            return "dummy_token"
        
        # קרא את הטמפלט כקובץ טקסט
        import os
        template_path = os.path.join(current_app.root_path, 'templates', 'emails', 'newsletter_template.html')
        
        with open(template_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # החלפת משתנים בסיסיים
        hebrew_month_year = get_current_month_year_hebrew()
        html_content = html_content.replace("{{ newsletter.title }}", newsletter.title)
        html_content = html_content.replace("{{ hebrew_month_year }}", hebrew_month_year)
        html_content = html_content.replace("{{ newsletter.created_at.strftime('%B %Y') }}", "דצמבר 2024")
        html_content = html_content.replace("{{ user.first_name }}", "דוגמה")
        
        # טיפול בתוכן
        if newsletter.content:
            content_html = newsletter.content.replace('\n', '<br>')
            html_content = html_content.replace("{{ newsletter.content|replace('\\n', '<br>')|safe }}", content_html)
        
        # טיפול בסקציות נוספות
        if newsletter.telegram_bot_section:
            html_content = html_content.replace("{{ newsletter.telegram_bot_section|safe }}", newsletter.telegram_bot_section)
        
        if newsletter.website_features_section:
            html_content = html_content.replace("{{ newsletter.website_features_section|safe }}", newsletter.website_features_section)
        
        # טיפול בכפתור הטלגרם
        if newsletter.show_telegram_button:
            html_content = html_content.replace("{% if newsletter.show_telegram_button %}", "")
            html_content = html_content.replace("{% endif %}", "")
        else:
            # הסרת קטע הכפתור אם לא רוצים להציג אותו
            import re
            html_content = re.sub(r'\{\% if newsletter\.show_telegram_button \%\}.*?\{\% endif \%\}', '', html_content, flags=re.DOTALL)
        
        # החלפת הקישורים לקישורי דמה
        html_content = html_content.replace(
            "{% if unsubscribe_link and unsubscribe_link != '#' %}",
            "<!-- Preview mode - using dummy links -->"
        )
        html_content = html_content.replace("{% else %}", "")
        html_content = html_content.replace("{% endif %}", "")
        
        # טיפול בתמונת הניוזלטר
        if newsletter.image_path:
            html_content = html_content.replace("{{ newsletter.image_path }}", newsletter.image_path)
        
        # הסרת קוד Jinja2 שנותר
        import re
        html_content = re.sub(r'\{\{[^}]*url_for[^}]*\}\}', '#', html_content)
        html_content = re.sub(r'\{\%[^%]*\%\}', '', html_content)
        html_content = re.sub(r'\{\{[^}]*\}\}', '', html_content)
        
        return html_content

# עמוד בחירת משתמשים לשליחה
@admin_newsletter_bp.route("/send/<int:newsletter_id>", methods=["GET", "POST"])
@admin_required
def send_newsletter(newsletter_id):
    """עמוד בחירת משתמשים ושליחת ניוזלטר"""
    newsletter = Newsletter.query.get_or_404(newsletter_id)
    
    if request.method == "POST":
        selected_users = request.form.getlist("selected_users")
        send_all = request.form.get("send_all") == "on"
        
        if send_all:
            # שליחה לכל המשתמשים שמעוניינים בניוזלטר
            users = User.query.filter_by(is_deleted=False, is_confirmed=True, newsletter_subscription=True).all()
        elif selected_users:
            # שליחה למשתמשים נבחרים שמעוניינים בניוזלטר
            users = User.query.filter(
                User.id.in_(selected_users), 
                User.is_deleted==False, 
                User.is_confirmed==True, 
                User.newsletter_subscription==True
            ).all()
        else:
            flash("יש לבחור לפחות משתמש אחד או לסמן 'שליחה לכולם'.", "warning")
            users = User.query.filter_by(is_deleted=False, is_confirmed=True, newsletter_subscription=True).all()
            return render_template("admin/admin_send_newsletter.html", newsletter=newsletter, users=users)
        
        # ביצוע השליחה
        success_count = 0
        error_count = 0
        
        for user in users:
            
            try:
                # יצירת קישור ביטול הרשמה
                unsubscribe_link = generate_unsubscribe_link(user)
                
                # יצירת תוכן המייל בהתאם לסוג הניוזלטר
                if newsletter.newsletter_type == "custom":
                    # שימוש ב-HTML מותאם אישית
                    html_content = newsletter.custom_html
                    
                    # יצירת קישור ביטול המנוי ועדכון העדפות
                    unsubscribe_token = generate_unsubscribe_token(user)
                    preferences_token = generate_preferences_token(user)
                    unsubscribe_full_link = f"https://couponmasteril.com{url_for('profile.unsubscribe_newsletter', user_id=user.id, token=unsubscribe_token)}"
                    preferences_full_link = f"https://couponmasteril.com{url_for('profile.preferences_from_email', user_id=user.id, token=preferences_token)}"
                    
                    # הוספת תמונה וחלק ביטול המנוי לסוף ה-HTML אם הוא לא קיים
                    from datetime import datetime
                    current_year = datetime.now().year
                    
                    # תמונה אם קיימת
                    image_section = ""
                    if newsletter.image_path:
                        image_url = f"https://couponmasteril.com/static/{newsletter.image_path}"
                        image_section = f'''
                        <br>
                        <!-- Newsletter Image -->
                        <div style="text-align: center; margin: 20px 0;">
                            <img src="{image_url}" alt="תמונת הניוזלטר" style="max-width: 100%; max-height: 300px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.1);">
                        </div>
                        '''
                    
                    unsubscribe_section = f'''
                        {image_section}
                        <br>
                        <!-- Footer -->
                        <div style="max-width: 500px; margin: 20px auto; background-color: #34495e; color: #bdc3c7; text-align: center; padding: 18px 25px; border-radius: 10px; font-family: Arial, sans-serif;">
                            <p style="margin: 0 0 12px 0; font-size: 14px;"><strong>Coupon Master</strong></p>
                            <div style="font-size: 12px; color: #95a5a6; margin: 12px 0;">
                                <p style="margin: 0 0 10px 0;">שלום {user.first_name}, קיבלת את המייל הזה כי אתה רשום לניוזלטר שלנו.</p>
                                <p style="margin: 0;">
                                    <a href="{unsubscribe_full_link}" style="color: #95a5a6; text-decoration: underline;">ביטול מנוי</a>
                                    | 
                                    <a href="{preferences_full_link}" style="color: #95a5a6; text-decoration: underline;">עדכון העדפות</a>
                                </p>
                            </div>
                            <p style="margin: 12px 0 0 0; font-size: 11px;">© {current_year} Coupon Master. כל הזכויות שמורות.</p>
                        </div>
                    '''
                    
                    # בדיקה אם יש כבר </body> או </html> ואם כן, להוסיף לפני זה
                    if '</body>' in html_content:
                        html_content = html_content.replace('</body>', unsubscribe_section + '</body>')
                    elif '</html>' in html_content:
                        html_content = html_content.replace('</html>', unsubscribe_section + '</html>')
                    else:
                        html_content += unsubscribe_section
                    
                    # החלפת משתנים בסיסיים
                    html_content = html_content.replace("{{ user.first_name }}", user.first_name)
                    html_content = html_content.replace("{{ user.last_name }}", user.last_name)
                    html_content = html_content.replace("{{ user.email }}", user.email)
                    html_content = html_content.replace("{{ unsubscribe_link }}", unsubscribe_link)
                    
                    # החלפת URL התמונה אם קיימת
                    if newsletter.image_path:
                        image_url = f"https://couponmasteril.com/static/{newsletter.image_path}"
                        logger.info(f"Replacing newsletter_image_url with: {image_url}")
                        html_content = html_content.replace("{{ newsletter_image_url }}", image_url)
                    else:
                        logger.info("No image path found, removing newsletter_image_url placeholder")
                        html_content = html_content.replace("{{ newsletter_image_url }}", "")
                else:
                    # שימוש בתבנית המובנית
                    hebrew_month_year = get_current_month_year_hebrew()
                    html_content = render_template("emails/newsletter_template.html", 
                                                 newsletter=newsletter, 
                                                 user=user,
                                                 unsubscribe_link=unsubscribe_link,
                                                 generate_unsubscribe_token=generate_unsubscribe_token,
                                                 generate_preferences_token=generate_preferences_token,
                                                 hebrew_month_year=hebrew_month_year)
                
                send_html_email(
                    api_key=os.getenv("BREVO_API_KEY"),
                    sender_email=os.getenv("SENDER_EMAIL", "noreply@couponmaster.co.il"),
                    sender_name="Coupon Master",
                    recipient_email=user.email,
                    recipient_name=f"{user.first_name} {user.last_name}",
                    subject=newsletter.title,
                    html_content=html_content,
                    add_timestamp=False
                )
                
                # רישום השליחה בבסיס הנתונים
                existing_sending = NewsletterSending.query.filter_by(
                    newsletter_id=newsletter.id,
                    user_id=user.id
                ).first()
                
                if existing_sending:
                    existing_sending.delivery_status = "sent"
                    existing_sending.sent_at = datetime.utcnow()
                    existing_sending.error_message = None
                else:
                    sending = NewsletterSending(
                        newsletter_id=newsletter.id,
                        user_id=user.id,
                        delivery_status="sent"
                    )
                    db.session.add(sending)
                success_count += 1
                
            except Exception as e:
                logger.error(f"Failed to send newsletter to {user.email}: {e}")
                # רישום שליחה כושלת
                existing_sending = NewsletterSending.query.filter_by(
                    newsletter_id=newsletter.id,
                    user_id=user.id
                ).first()
                
                if existing_sending:
                    existing_sending.delivery_status = "failed"
                    existing_sending.sent_at = datetime.utcnow()
                    existing_sending.error_message = str(e)
                else:
                    sending = NewsletterSending(
                        newsletter_id=newsletter.id,
                        user_id=user.id,
                        delivery_status="failed",
                        error_message=str(e)
                    )
                    db.session.add(sending)
                error_count += 1
        
        # עדכון מספר השליחות בניוזלטר
        newsletter.sent_count = success_count
        newsletter.is_published = True
        db.session.commit()
        
        if error_count > 0:
            flash(f"הניוזלטר נשלח ל-{success_count} משתמשים, {error_count} שליחות נכשלו.", "warning")
        else:
            flash(f"הניוזלטר נשלח בהצלחה ל-{success_count} משתמשים!", "success")
        
        return redirect(url_for("admin_newsletter_bp.manage_newsletters"))
    
    # GET - הצגת עמוד בחירת המשתמשים שמעוניינים בניוזלטר
    users = User.query.filter_by(is_deleted=False, is_confirmed=True, newsletter_subscription=True).all()
    return render_template("admin/admin_send_newsletter.html", newsletter=newsletter, users=users)

# מחיקת ניוזלטר
@admin_newsletter_bp.route("/delete/<int:newsletter_id>", methods=["POST"])
@admin_required
def delete_newsletter(newsletter_id):
    """מחיקת ניוזלטר"""
    newsletter = Newsletter.query.get_or_404(newsletter_id)
    title = newsletter.title
    
    db.session.delete(newsletter)
    db.session.commit()
    
    flash(f"ניוזלטר '{title}' נמחק בהצלחה.", "success")
    return redirect(url_for("admin_newsletter_bp.manage_newsletters"))

# API לקבלת רשימת משתמשים
@admin_newsletter_bp.route("/api/users")
@admin_required
def get_users_api():
    """API לקבלת רשימת משתמשים עם פרטים בסיסיים שמעוניינים בניוזלטר"""
    users = User.query.filter_by(is_deleted=False, is_confirmed=True, newsletter_subscription=True).all()
    users_data = []
    
    for user in users:
        users_data.append({
            'id': user.id,
            'name': f"{user.first_name} {user.last_name}",
            'email': user.email,
            'created_at': user.created_at.strftime('%d/%m/%Y') if user.created_at else 'לא ידוע'
        })
    
    return jsonify(users_data)