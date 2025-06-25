# admin_newsletter_routes.py
from flask import Blueprint, redirect, url_for, flash, request, render_template, current_app, jsonify
from flask_login import login_required, current_user
from app.models import Newsletter, NewsletterSending, User
from app.extensions import db
from app.helpers import send_html_email
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

admin_newsletter_bp = Blueprint("admin_newsletter_bp", __name__, url_prefix="/admin/newsletter")

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
        telegram_bot_section = request.form.get("telegram_bot_section")
        website_features_section = request.form.get("website_features_section")
        custom_html = request.form.get("custom_html")
        
        if not title:
            flash("יש למלא כותרת לניוזלטר.", "danger")
            return render_template("admin/admin_create_newsletter.html")
        
        if newsletter_type == "structured" and not content:
            flash("יש למלא תוכן עיקרי בניוזלטר מובנה.", "danger")
            return render_template("admin/admin_create_newsletter.html")
        
        if newsletter_type == "custom" and not custom_html:
            flash("יש למלא קוד HTML בניוזלטר מותאם אישית.", "danger")
            return render_template("admin/admin_create_newsletter.html")
        
        newsletter = Newsletter(
            title=title,
            newsletter_type=newsletter_type,
            content=content if newsletter_type == "structured" else None,
            telegram_bot_section=telegram_bot_section if newsletter_type == "structured" else None,
            website_features_section=website_features_section if newsletter_type == "structured" else None,
            custom_html=custom_html if newsletter_type == "custom" else None,
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
            
            if not newsletter.title or not newsletter.content:
                flash("יש למלא לפחות כותרת ותוכן עיקרי.", "danger")
                return render_template("admin/admin_edit_newsletter.html", newsletter=newsletter)
        else:
            newsletter.custom_html = request.form.get("custom_html")
            
            if not newsletter.title or not newsletter.custom_html:
                flash("יש למלא לפחות כותרת וקוד HTML.", "danger")
                return render_template("admin/admin_edit_newsletter.html", newsletter=newsletter)
        
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
        html_content = html_content.replace("{{ user.first_name }}", "דוגמה")
        html_content = html_content.replace("{{ user.last_name }}", "משתמש")
        html_content = html_content.replace("{{ user.email }}", "example@email.com")
        html_content = html_content.replace("{{ unsubscribe_link }}", "#")
        return html_content
    else:
        # עבור ניוזלטר מובנה - שימוש בתבנית
        from types import SimpleNamespace
        dummy_user = SimpleNamespace(first_name="דוגמה", last_name="משתמש", email="example@email.com")
        dummy_unsubscribe_link = "#"
        return render_template("emails/newsletter_template.html", 
                             newsletter=newsletter, 
                             user=dummy_user,
                             unsubscribe_link=dummy_unsubscribe_link,
                             generate_unsubscribe_token=generate_unsubscribe_token,
                             generate_preferences_token=generate_preferences_token)

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
            # בדיקה שהמשתמש עדיין לא קיבל את הניוזלטר הזה
            existing_sending = NewsletterSending.query.filter_by(
                newsletter_id=newsletter.id,
                user_id=user.id
            ).first()
            
            if existing_sending:
                continue
            
            try:
                # יצירת קישור ביטול הרשמה
                unsubscribe_link = generate_unsubscribe_link(user)
                
                # יצירת תוכן המייל בהתאם לסוג הניוזלטר
                if newsletter.newsletter_type == "custom":
                    # שימוש ב-HTML מותאם אישית
                    html_content = newsletter.custom_html
                    # החלפת משתנים בסיסיים
                    html_content = html_content.replace("{{ user.first_name }}", user.first_name)
                    html_content = html_content.replace("{{ user.last_name }}", user.last_name)
                    html_content = html_content.replace("{{ user.email }}", user.email)
                    html_content = html_content.replace("{{ unsubscribe_link }}", unsubscribe_link)
                else:
                    # שימוש בתבנית המובנית
                    html_content = render_template("emails/newsletter_template.html", 
                                                 newsletter=newsletter, 
                                                 user=user,
                                                 unsubscribe_link=unsubscribe_link,
                                                 generate_unsubscribe_token=generate_unsubscribe_token,
                                                 generate_preferences_token=generate_preferences_token)
                
                send_html_email(
                    api_key=os.getenv("BREVO_API_KEY"),
                    sender_email=os.getenv("SENDER_EMAIL", "noreply@couponmaster.co.il"),
                    sender_name="Coupon Master",
                    recipient_email=user.email,
                    recipient_name=f"{user.first_name} {user.last_name}",
                    subject=newsletter.title,
                    html_content=html_content
                )
                
                # רישום השליחה בבסיס הנתונים
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