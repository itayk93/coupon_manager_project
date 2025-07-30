from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import AdminSettings
import logging
from datetime import datetime

admin_email_bp = Blueprint('admin_email_bp', __name__)

def admin_required(f):
    """Decorator to require admin privileges"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('אין לך הרשאה לצפות בעמוד זה.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@admin_email_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def email_settings():
    """
    עמוד הגדרות המייל היומי
    """
    if request.method == 'POST':
        # קבלת הגדרות מהטופס
        daily_email_enabled = request.form.get('daily_email_enabled') == 'on'
        email_hour = request.form.get('email_hour', '6')
        email_minute = request.form.get('email_minute', '0')
        recipient_email = request.form.get('recipient_email', 'itayk93@gmail.com')
        
        try:
            # שמירת ההגדרות
            AdminSettings.set_setting('daily_email_enabled', daily_email_enabled, 'boolean', 
                                    'האם לשלוח מייל יומי עם נתוני קופונים')
            AdminSettings.set_setting('daily_email_hour', int(email_hour), 'integer', 
                                    'שעה לשליחת המייל היומי (0-23)')
            AdminSettings.set_setting('daily_email_minute', int(email_minute), 'integer', 
                                    'דקה לשליחת המייל היומי (0-59)')
            AdminSettings.set_setting('daily_email_recipient', recipient_email, 'string', 
                                    'כתובת מייל למקבל המייל היומי')
            
            flash('הגדרות המייל נשמרו בהצלחה!', 'success')
            
        except Exception as e:
            flash(f'שגיאה בשמירת ההגדרות: {str(e)}', 'danger')
            logging.error(f"Error saving email settings: {e}")
    
    # טעינת הגדרות נוכחות
    current_settings = {
        'daily_email_enabled': AdminSettings.get_setting('daily_email_enabled', True),
        'email_hour': AdminSettings.get_setting('daily_email_hour', 6),
        'email_minute': AdminSettings.get_setting('daily_email_minute', 0),
        'recipient_email': AdminSettings.get_setting('daily_email_recipient', 'itayk93@gmail.com')
    }
    
    # בדיקת סטטוס שליחה היום
    from scheduler_utils import load_process_status  # Local import
    email_sent_today = load_process_status('daily_email')
    
    return render_template('admin/email_settings.html', 
                         settings=current_settings, 
                         email_sent_today=email_sent_today)

@admin_email_bp.route('/send-now', methods=['POST'])
@login_required
@admin_required
def send_email_now():
    """
    שליחת מייל מיידית (ללא תלות בזמן הזמנה)
    """
    try:
        from app import create_app  # Local import to avoid circular dependency
        from scheduler_utils import update_company_counts_and_send_email, save_process_status  # Local import
        app = create_app()
        with app.app_context():
            # שליחת המייל
            update_company_counts_and_send_email(app)
            # עדכון סטטוס שנשלח
            save_process_status('daily_email', True)
            
        flash('המייל נשלח בהצלחה!', 'success')
        
    except Exception as e:
        flash(f'שגיאה בשליחת המייל: {str(e)}', 'danger')
        logging.error(f"Error sending email manually: {e}")
    
    return redirect(url_for('admin_email_bp.email_settings'))

@admin_email_bp.route('/reset-status', methods=['POST'])
@login_required
@admin_required
def reset_email_status():
    """
    איפוס סטטוס שליחת המייל (מאפשר שליחה מחדש)
    """
    try:
        from scheduler_utils import save_process_status  # Local import
        save_process_status('daily_email', False)
        flash('סטטוס המייל אופס בהצלחה. המייל יכול להישלח שוב.', 'success')
        
    except Exception as e:
        flash(f'שגיאה באיפוס הסטטוס: {str(e)}', 'danger')
        logging.error(f"Error resetting email status: {e}")
    
    return redirect(url_for('admin_email_bp.email_settings'))

@admin_email_bp.route('/test-email', methods=['POST'])
@login_required
@admin_required
def test_email():
    """
    שליחת מייל בדיקה
    """
    try:
        from app.helpers import send_email
        
        test_recipient = request.form.get('test_email', current_user.email)
        
        # יצירת תוכן בדיקה
        html_content = """
        <html>
            <head><meta charset="utf-8"></head>
            <body style="direction: rtl; font-family: Arial, sans-serif;">
                <h2>מייל בדיקה מאתר הקופונים</h2>
                <p>זהו מייל בדיקה מהמערכת.</p>
                <p>אם קיבלת מייל זה, המערכת פועלת כראוי.</p>
                <p>נשלח בתאריך: {}</p>
            </body>
        </html>
        """.format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        send_email(
            sender_email="noreply@couponmasteril.com",
            sender_name="Coupon Master",
            recipient_email=test_recipient,
            recipient_name="Test",
            subject="מייל בדיקה מאתר הקופונים",
            html_content=html_content
        )
        
        flash(f'מייל בדיקה נשלח בהצלחה לכתובת: {test_recipient}', 'success')
        
    except Exception as e:
        flash(f'שגיאה בשליחת מייל הבדיקה: {str(e)}', 'danger')
        logging.error(f"Error sending test email: {e}")
    
    return redirect(url_for('admin_email_bp.email_settings'))