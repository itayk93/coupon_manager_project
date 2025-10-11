from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db, csrf
from app.models import Newsletter, NewsletterSending, User
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps

admin_scheduled_emails_bp = Blueprint('admin_scheduled_emails_bp', __name__)

def admin_required(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('אין לך הרשאה לצפות בעמוד זה.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def api_token_required(f):
    """Decorator to require API token for cron jobs"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'error': 'Missing or invalid authorization header',
                'message': 'Authorization header with Bearer token is required'
            }), 401
        
        token = auth_header.split(' ')[1]
        expected_token = current_app.config.get('CRON_API_TOKEN')
        
        if not expected_token or token != expected_token:
            return jsonify({
                'success': False,
                'error': 'Invalid API token',
                'message': 'The provided API token is invalid'
            }), 401
        
        return f(*args, **kwargs)
    return decorated_function

@admin_scheduled_emails_bp.route('/scheduled-emails', methods=['GET'])
@login_required
@admin_required
def scheduled_emails():
    """
    עמוד ניהול מיילים מתוכננים
    מציג את כל המיילים שמתוכננים להישלח היום
    """
    try:
        import pytz
        israel_tz = pytz.timezone('Asia/Jerusalem')
        
        # קבלת התאריך הנוכחי
        now_utc = datetime.now(timezone.utc)
        now_israel = now_utc.astimezone(israel_tz)
        today_israel = now_israel.date()
        tomorrow_israel = today_israel + timedelta(days=1)
        
        # חיפוש כל הניוזלטרים המתוכננים להישלח היום ומחר (בזמן ישראל)
        scheduled_emails = Newsletter.query.filter(
            Newsletter.is_published == True,
            Newsletter.scheduled_send_time.isnot(None),
            Newsletter.scheduled_send_time > now_utc  # רק מיילים עתידיים
        ).order_by(Newsletter.scheduled_send_time.asc()).all()
        
        # הוספת מידע נוסף לכל מייל
        email_data = []
        for email in scheduled_emails:
            # המרת זמן לזמן ישראל
            scheduled_israel = email.scheduled_send_time.astimezone(israel_tz)
            
            # חישוב זמן שנותר
            time_diff = email.scheduled_send_time - now_utc
            hours_remaining = time_diff.total_seconds() / 3600 if time_diff.total_seconds() > 0 else 0
            
            email_info = {
                'newsletter': email,
                'scheduled_time': scheduled_israel,  # זמן ישראל במקום UTC
                'scheduled_time_utc': email.scheduled_send_time,  # UTC לחישובים
                'is_past_due': email.scheduled_send_time <= now_utc,
                'should_be_sent': email.scheduled_send_time <= now_utc and not email.is_sent,
                'hours_remaining': round(hours_remaining, 1)
            }
            email_data.append(email_info)
        
        return render_template('admin/admin_scheduled_emails.html', 
                             email_data=email_data,
                             current_time=now_israel)  # זמן ישראל לטמפלט
        
    except Exception as e:
        logging.error(f"Error loading scheduled emails: {e}")
        flash(f'שגיאה בטעינת המיילים המתוכננים: {str(e)}', 'danger')
        return redirect(url_for('admin_bp.admin_dashboard'))

@admin_scheduled_emails_bp.route('/send-pending-emails', methods=['POST'])
@login_required
@admin_required
def send_pending_emails():
    """
    API endpoint לשליחת מיילים שאמורים להישלח
    שולח רק מיילים שהזמן שלהם עבר ועדיין לא נשלחו
    """
    try:
        current_time = datetime.now(timezone.utc)
        
        # חיפוש מיילים שאמורים להישלח (זמן שעבר, עדיין לא נשלחו)
        pending_emails = Newsletter.query.filter(
            Newsletter.scheduled_send_time <= current_time,
            Newsletter.is_sent == False,
            Newsletter.is_published == True,
            Newsletter.scheduled_send_time.isnot(None)
        ).all()
        
        sent_count = 0
        failed_count = 0
        sent_emails = []
        failed_emails = []
        
        for newsletter in pending_emails:
            try:
                # שליחת הניוזלטר לכל המשתמשים המנויים
                success = send_newsletter_to_subscribers(newsletter)
                
                if success:
                    # עדכון שהניוזלטר נשלח
                    newsletter.is_sent = True
                    db.session.commit()
                    sent_count += 1
                    sent_emails.append({
                        'title': newsletter.title,
                        'scheduled_time': newsletter.scheduled_send_time.strftime('%H:%M')
                    })
                else:
                    failed_count += 1
                    failed_emails.append({
                        'title': newsletter.title,
                        'scheduled_time': newsletter.scheduled_send_time.strftime('%H:%M'),
                        'error': 'שגיאה בשליחה'
                    })
                    
            except Exception as e:
                logging.error(f"Error sending newsletter {newsletter.id}: {e}")
                failed_count += 1
                failed_emails.append({
                    'title': newsletter.title,
                    'scheduled_time': newsletter.scheduled_send_time.strftime('%H:%M'),
                    'error': str(e)
                })
        
        # הכנת תגובה
        response_data = {
            'success': True,
            'sent_count': sent_count,
            'failed_count': failed_count,
            'sent_emails': sent_emails,
            'failed_emails': failed_emails,
            'message': f'נשלחו {sent_count} מיילים בהצלחה'
        }
        
        if failed_count > 0:
            response_data['message'] += f', {failed_count} מיילים נכשלו'
        
        return jsonify(response_data)
        
    except Exception as e:
        logging.error(f"Error in send_pending_emails: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'message': f'שגיאה בשליחת המיילים: {str(e)}'
        }), 500

@admin_scheduled_emails_bp.route('/api/cron/send-pending-emails', methods=['POST'])
@api_token_required
def cron_send_pending_emails():
    """
    API endpoint לשליחת מיילים שאמורים להישלח - מיועד לCron Jobs
    דורש API token authentication במקום login session
    """
    try:
        current_time = datetime.now(timezone.utc)
        
        # חיפוש מיילים שאמורים להישלח (זמן שעבר, עדיין לא נשלחו)
        pending_emails = Newsletter.query.filter(
            Newsletter.scheduled_send_time <= current_time,
            Newsletter.is_sent == False,
            Newsletter.is_published == True,
            Newsletter.scheduled_send_time.isnot(None)
        ).all()
        
        sent_count = 0
        failed_count = 0
        sent_emails = []
        failed_emails = []
        
        # לוג תחילת תהליך
        logging.info(f"Cron job started: Found {len(pending_emails)} pending emails to send")
        
        for newsletter in pending_emails:
            try:
                # שליחת הניוזלטר לכל המשתמשים המנויים
                success = send_newsletter_to_subscribers(newsletter)
                
                if success:
                    # עדכון שהניוזלטר נשלח
                    newsletter.is_sent = True
                    newsletter.sent_at = current_time
                    db.session.commit()
                    sent_count += 1
                    sent_emails.append({
                        'id': newsletter.id,
                        'title': newsletter.title,
                        'scheduled_time': newsletter.scheduled_send_time.strftime('%d/%m/%Y %H:%M'),
                        'sent_count': newsletter.sent_count
                    })
                    logging.info(f"Newsletter {newsletter.id} ({newsletter.title}) sent successfully to {newsletter.sent_count} users")
                else:
                    failed_count += 1
                    failed_emails.append({
                        'id': newsletter.id,
                        'title': newsletter.title,
                        'scheduled_time': newsletter.scheduled_send_time.strftime('%d/%m/%Y %H:%M'),
                        'error': 'שגיאה בשליחה'
                    })
                    logging.error(f"Failed to send newsletter {newsletter.id} ({newsletter.title})")
                    
            except Exception as e:
                logging.error(f"Error sending newsletter {newsletter.id}: {e}")
                failed_count += 1
                failed_emails.append({
                    'id': newsletter.id,
                    'title': newsletter.title,
                    'scheduled_time': newsletter.scheduled_send_time.strftime('%d/%m/%Y %H:%M'),
                    'error': str(e)
                })
        
        # הכנת תגובה מפורטת
        response_data = {
            'success': True,
            'timestamp': current_time.isoformat(),
            'summary': {
                'total_processed': len(pending_emails),
                'sent_count': sent_count,
                'failed_count': failed_count
            },
            'sent_emails': sent_emails,
            'failed_emails': failed_emails,
            'message': f'Cron job completed: {sent_count} emails sent successfully'
        }
        
        if failed_count > 0:
            response_data['message'] += f', {failed_count} emails failed'
        
        if sent_count == 0 and failed_count == 0:
            response_data['message'] = 'No pending emails found to send'
        
        logging.info(f"Cron job completed: {sent_count} sent, {failed_count} failed")
        return jsonify(response_data)
        
    except Exception as e:
        logging.error(f"Critical error in cron_send_pending_emails: {e}")
        return jsonify({
            'success': False,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'error': str(e),
            'message': f'Critical error in cron job: {str(e)}'
        }), 500

@admin_scheduled_emails_bp.route('/api/cron/send-expiration-reminders', methods=['POST'])
@csrf.exempt
@api_token_required
def cron_send_expiration_reminders():
    """
    API endpoint לשליחת תזכורות תפוגת קופונים - מיועד לCron Jobs
    שולח תזכורות ל-30, 7 ו-1 ימים לפני תפוגה
    """
    try:
        from datetime import date, timedelta
        from app.models import Coupon, User, Company
        from app.helpers import send_email
        import base64
        import os
        
        current_time = datetime.now(timezone.utc)
        today = current_time.date()
        
        # חיפוש קופונים שצריכים תזכורות
        # 30 ימים לפני תפוגה
        date_30_days = today + timedelta(days=30)
        # 7 ימים לפני תפוגה  
        date_7_days = today + timedelta(days=7)
        # יום אחד לפני תפוגה
        date_1_day = today + timedelta(days=1)
        
        sent_count = 0
        failed_count = 0
        sent_reminders = []
        failed_reminders = []
        
        # פונקציה לשליחת תזכורת
        def send_reminder(coupon, user, days_left, reminder_type):
            try:
                # הכנת תוכן המייל
                company_obj = Company.query.filter_by(name=coupon.company).first()
                logo_filename = (
                    company_obj.image_path
                    if company_obj and company_obj.image_path
                    else "default_logo.png"
                )
                
                # קריאת לוגו החברה
                logo_filepath = os.path.join(
                    current_app.root_path, "static", logo_filename
                )
                
                try:
                    with open(logo_filepath, "rb") as image_file:
                        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
                except Exception as e:
                    logging.warning(f"Could not read logo file {logo_filepath}: {e}")
                    encoded_string = ""
                
                # הכנת נתוני הקופון למייל
                coupon_data = {
                    "company": coupon.company,
                    "company_logo_base64": encoded_string,
                    "code": coupon.code,
                    "remaining_value": coupon.remaining_value,
                    "expiration": coupon.expiration,
                    "expiration_formatted": datetime.strptime(coupon.expiration, "%Y-%m-%d").strftime("%d/%m/%Y"),
                    "days_left": days_left,
                    "coupon_detail_link": f"https://www.couponmasteril.com/coupon_detail/{coupon.id}",
                }
                
                # קביעת כותרת המייל לפי מספר הימים
                if days_left == 30:
                    subject = "תזכורת: קופון פג תוקף בעוד 30 יום"
                elif days_left == 7:
                    subject = "תזכורת: קופון פג תוקף בעוד שבוע"
                elif days_left == 1:
                    subject = "תזכורת דחופה: קופון פג תוקף מחר!"
                else:
                    subject = f"תזכורת: קופון פג תוקף בעוד {days_left} ימים"
                
                # רינדור תבנית המייל
                from flask import render_template
                html_content = render_template(
                    "emails/coupon_expiration_warning.html",
                    user={"first_name": user.first_name, "email": user.email},
                    coupons=[coupon_data],
                    current_year=today.year,
                )
                
                # שליחת המייל
                success = send_email(
                    sender_email="noreply@couponmasteril.com",
                    sender_name="Coupon Master",
                    recipient_email=user.email,
                    recipient_name=f"{user.first_name} {user.last_name}",
                    subject=subject,
                    html_content=html_content,
                )
                
                if success:
                    # עדכון הדגל שהתזכורת נשלחה
                    if reminder_type == 30:
                        coupon.reminder_sent_30_days = True
                    elif reminder_type == 7:
                        coupon.reminder_sent_7_days = True
                    elif reminder_type == 1:
                        coupon.reminder_sent_1_day = True
                    
                    db.session.commit()
                    
                    return True, None
                else:
                    return False, "Email sending failed"
                    
            except Exception as e:
                return False, str(e)
        
        # לוג תחילת תהליך
        logging.info(f"Expiration reminders cron job started")
        
        # תזכורות 30 ימים
        coupons_30_days = Coupon.query.join(User).filter(
            Coupon.expiration == date_30_days.strftime("%Y-%m-%d"),
            Coupon.reminder_sent_30_days == False,
            Coupon.status == 'פעיל',
            Coupon.is_for_sale == False
        ).all()
        
        for coupon in coupons_30_days:
            success, error = send_reminder(coupon, coupon.user, 30, 30)
            if success:
                sent_count += 1
                sent_reminders.append({
                    'type': '30_days',
                    'coupon_id': coupon.id,
                    'user_email': coupon.user.email,
                    'company': coupon.company,
                    'code': coupon.code
                })
            else:
                failed_count += 1
                failed_reminders.append({
                    'type': '30_days',
                    'coupon_id': coupon.id,
                    'user_email': coupon.user.email,
                    'error': error
                })
        
        # תזכורות 7 ימים
        coupons_7_days = Coupon.query.join(User).filter(
            Coupon.expiration == date_7_days.strftime("%Y-%m-%d"),
            Coupon.reminder_sent_7_days == False,
            Coupon.status == 'פעיל',
            Coupon.is_for_sale == False
        ).all()
        
        for coupon in coupons_7_days:
            success, error = send_reminder(coupon, coupon.user, 7, 7)
            if success:
                sent_count += 1
                sent_reminders.append({
                    'type': '7_days',
                    'coupon_id': coupon.id,
                    'user_email': coupon.user.email,
                    'company': coupon.company,
                    'code': coupon.code
                })
            else:
                failed_count += 1
                failed_reminders.append({
                    'type': '7_days',
                    'coupon_id': coupon.id,
                    'user_email': coupon.user.email,
                    'error': error
                })
        
        # תזכורות יום אחד
        coupons_1_day = Coupon.query.join(User).filter(
            Coupon.expiration == date_1_day.strftime("%Y-%m-%d"),
            Coupon.reminder_sent_1_day == False,
            Coupon.status == 'פעיל',
            Coupon.is_for_sale == False
        ).all()
        
        for coupon in coupons_1_day:
            success, error = send_reminder(coupon, coupon.user, 1, 1)
            if success:
                sent_count += 1
                sent_reminders.append({
                    'type': '1_day',
                    'coupon_id': coupon.id,
                    'user_email': coupon.user.email,
                    'company': coupon.company,
                    'code': coupon.code
                })
            else:
                failed_count += 1
                failed_reminders.append({
                    'type': '1_day',
                    'coupon_id': coupon.id,
                    'user_email': coupon.user.email,
                    'error': error
                })
        
        # תזכורות לקופונים שעומדים לפוג בעוד 2-6 ימים (שעדיין לא קיבלו תזכורת)
        date_2_to_6_days_start = date.today() + timedelta(days=2)
        date_2_to_6_days_end = date.today() + timedelta(days=6)
        
        from sqlalchemy import and_
        
        coupons_2_to_6_days = Coupon.query.join(User).filter(
            and_(
                Coupon.expiration >= date_2_to_6_days_start.strftime("%Y-%m-%d"),
                Coupon.expiration <= date_2_to_6_days_end.strftime("%Y-%m-%d")
            ),
            Coupon.reminder_sent_7_days == False,
            Coupon.reminder_sent_1_day == False,
            Coupon.status == 'פעיל',
            Coupon.is_for_sale == False
        ).all()
        
        for coupon in coupons_2_to_6_days:
            # חישוב כמה ימים נשארו
            exp_date = datetime.strptime(coupon.expiration, '%Y-%m-%d').date()
            days_left = (exp_date - today).days
            
            success, error = send_reminder(coupon, coupon.user, days_left, days_left)
            if success:
                sent_count += 1
                sent_reminders.append({
                    'type': f'{days_left}_days',
                    'coupon_id': coupon.id,
                    'user_email': coupon.user.email,
                    'company': coupon.company,
                    'code': coupon.code
                })
                # סמן שהתזכורת נשלחה (נשתמש בשדה reminder_sent_7_days)
                coupon.reminder_sent_7_days = True
                db.session.commit()
            else:
                failed_count += 1
                failed_reminders.append({
                    'type': f'{days_left}_days',
                    'coupon_id': coupon.id,
                    'user_email': coupon.user.email,
                    'error': error
                })
        
        # הכנת תגובה מפורטת
        response_data = {
            'success': True,
            'timestamp': current_time.isoformat(),
            'summary': {
                'total_sent': sent_count,
                'total_failed': failed_count,
                'reminders_30_days': len([r for r in sent_reminders if r['type'] == '30_days']),
                'reminders_7_days': len([r for r in sent_reminders if r['type'] == '7_days']),
                'reminders_1_day': len([r for r in sent_reminders if r['type'] == '1_day'])
            },
            'sent_reminders': sent_reminders,
            'failed_reminders': failed_reminders,
            'message': f'Expiration reminders completed: {sent_count} sent successfully'
        }
        
        if failed_count > 0:
            response_data['message'] += f', {failed_count} failed'
        
        if sent_count == 0 and failed_count == 0:
            response_data['message'] = 'No expiration reminders needed today'
        
        logging.info(f"Expiration reminders completed: {sent_count} sent, {failed_count} failed")
        return jsonify(response_data)
        
    except Exception as e:
        logging.error(f"Critical error in cron_send_expiration_reminders: {e}")
        return jsonify({
            'success': False,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'error': str(e),
            'message': f'Critical error in expiration reminders cron job: {str(e)}'
        }), 500

def send_newsletter_to_subscribers(newsletter):
    """
    שליחת ניוזלטר לכל המשתמשים המנויים
    מחזירה True אם הצליח, False אם נכשל
    """
    try:
        # קבלת כל המשתמשים שמנויים לניוזלטר
        subscribed_users = User.query.filter(
            User.newsletter_subscription == True
        ).all()
        
        if not subscribed_users:
            logging.warning(f"No subscribed users found for newsletter {newsletter.id}")
            return True
        
        # שליחה לכל משתמש
        total_sent = 0
        for user in subscribed_users:
            try:
                # בדיקה אם כבר נשלח למשתמש זה
                existing_sending = NewsletterSending.query.filter_by(
                    newsletter_id=newsletter.id,
                    user_id=user.id
                ).first()
                
                if existing_sending:
                    continue  # כבר נשלח למשתמש זה
                
                # שליחת המייל
                success = send_newsletter_email(newsletter, user)
                
                if success:
                    # תיעוד השליחה
                    sending = NewsletterSending(
                        newsletter_id=newsletter.id,
                        user_id=user.id,
                        delivery_status='sent'
                    )
                    db.session.add(sending)
                    total_sent += 1
                else:
                    # תיעוד שגיאה
                    sending = NewsletterSending(
                        newsletter_id=newsletter.id,
                        user_id=user.id,
                        delivery_status='failed',
                        error_message='שגיאה בשליחת המייל'
                    )
                    db.session.add(sending)
                    
            except Exception as e:
                logging.error(f"Error sending newsletter to user {user.id}: {e}")
                # תיעוד שגיאה
                sending = NewsletterSending(
                    newsletter_id=newsletter.id,
                    user_id=user.id,
                    delivery_status='failed',
                    error_message=str(e)
                )
                db.session.add(sending)
        
        # עדכון מספר השליחות בניוזלטר
        newsletter.sent_count = total_sent
        db.session.commit()
        
        logging.info(f"Newsletter {newsletter.id} sent to {total_sent} users")
        return True
        
    except Exception as e:
        logging.error(f"Error sending newsletter {newsletter.id}: {e}")
        db.session.rollback()
        return False

def send_newsletter_email(newsletter, user):
    """
    שליחת מייל ניוזלטר למשתמש ספציפי
    מחזירה True אם הצליח, False אם נכשל
    """
    try:
        from app.helpers import send_html_email
        from app.routes.admin_routes.admin_newsletter_routes import generate_unsubscribe_link
        
        # הכנת תוכן המייל
        if newsletter.newsletter_type == 'custom' and newsletter.custom_html:
            # ניוזלטר מותאם אישית
            email_content = newsletter.custom_html
        else:
            # ניוזלטר מובנה - צריך לרנדר את התבנית
            email_content = render_newsletter_template(newsletter, user)
        
        # הוספת קישור ביטול הרשמה
        unsubscribe_link = generate_unsubscribe_link(user)
        if unsubscribe_link not in email_content:
            email_content += f'<br><br><a href="{unsubscribe_link}">לביטול הרשמה לחץ כאן</a>'
        
        # שליחת המייל
        success = send_html_email(
            recipient_email=user.email,
            recipient_name=f"{user.first_name} {user.last_name}",
            subject=newsletter.title,
            html_content=email_content,
            sender_email="noreply@couponmasteril.com",
            sender_name="Coupon Master"
        )
        
        return success
        
    except Exception as e:
        logging.error(f"Error sending email to user {user.email}: {e}")
        return False

def render_newsletter_template(newsletter, user):
    """
    רינדור תבנית הניוזלטר עבור משתמש ספציפי
    """
    try:
        from flask import render_template_string
        
        # תבנית בסיסית לניוזלטר
        template = """
        <html>
        <head>
            <meta charset="utf-8">
            <title>{{ newsletter.title }}</title>
        </head>
        <body style="direction: rtl; font-family: Arial, sans-serif; margin: 20px;">
            {% if newsletter.main_title %}
            <h1>{{ newsletter.main_title }}</h1>
            {% endif %}
            
            {% if newsletter.additional_title %}
            <h2>{{ newsletter.additional_title }}</h2>
            {% endif %}
            
            {% if newsletter.content %}
            <div>{{ newsletter.content|safe }}</div>
            {% endif %}
            
            {% if newsletter.highlight_text %}
            <div style="background-color: #f0f8ff; padding: 10px; margin: 10px 0; border-right: 4px solid #007bff;">
                {{ newsletter.highlight_text|safe }}
            </div>
            {% endif %}
            
            {% if newsletter.telegram_bot_section %}
            <div style="margin: 20px 0;">
                <h3>בוט הטלגרם שלנו</h3>
                {{ newsletter.telegram_bot_section|safe }}
                {% if newsletter.show_telegram_button %}
                <br><a href="https://t.me/your_bot" style="background-color: #0088cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">הצטרף לבוט</a>
                {% endif %}
            </div>
            {% endif %}
            
            {% if newsletter.website_features_section %}
            <div style="margin: 20px 0;">
                <h3>תכונות האתר</h3>
                {{ newsletter.website_features_section|safe }}
            </div>
            {% endif %}
        </body>
        </html>
        """
        
        return render_template_string(template, newsletter=newsletter, user=user)
        
    except Exception as e:
        logging.error(f"Error rendering newsletter template: {e}")
        return f"<html><body><h1>{newsletter.title}</h1><p>{newsletter.content or 'תוכן לא זמין'}</p></body></html>"