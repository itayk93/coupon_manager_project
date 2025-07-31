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
        logging.info("POST request received for email settings")
        logging.info(f"Form data keys: {list(request.form.keys())}")
        
        # קבלת הגדרות מהטופס
        daily_email_enabled = request.form.get('daily_email_enabled') == 'on'
        email_hour = request.form.get('email_hour', '9')
        email_minute = request.form.get('email_minute', '0')
        recipient_email = request.form.get('recipient_email', 'itayk93@gmail.com')
        
        logging.info(f"Basic settings - enabled: {daily_email_enabled}, hour: {email_hour}, minute: {email_minute}")
        
        # קבלת כל אפשרויות הדוח המתקדם
        report_options = {
            # גרפים ויזואליזציות
            'chart_coupons_by_company': request.form.get('chart_coupons_by_company') == 'on',
            'chart_value_pie': request.form.get('chart_value_pie') == 'on',
            'chart_weekly_trend': request.form.get('chart_weekly_trend') == 'on',
            'chart_price_histogram': request.form.get('chart_price_histogram') == 'on',
            
            # מטריקות מתקדמות
            'metrics_roi': request.form.get('metrics_roi') == 'on',
            'metrics_recent_activity': request.form.get('metrics_recent_activity') == 'on',
            'metrics_expiring': request.form.get('metrics_expiring') == 'on',
            'metrics_top_companies': request.form.get('metrics_top_companies') == 'on',
            
            # תובנות חכמות
            'insights_top3': request.form.get('insights_top3') == 'on',
            'insights_weekly_comparison': request.form.get('insights_weekly_comparison') == 'on',
            'insights_expiring_alerts': request.form.get('insights_expiring_alerts') == 'on',
            
            # אנליטיקה עסקית
            'analytics_conversion_rate': request.form.get('analytics_conversion_rate') == 'on',
            'analytics_time_to_sell': request.form.get('analytics_time_to_sell') == 'on',
            'analytics_profitable_companies': request.form.get('analytics_profitable_companies') == 'on',
            
            # פילוח מתקדם
            'segmentation_categories': request.form.get('segmentation_categories') == 'on',
            'segmentation_price_ranges': request.form.get('segmentation_price_ranges') == 'on',
            'comparisons_monthly': request.form.get('comparisons_monthly') == 'on',
        }
        
        logging.info(f"Report options collected: {report_options}")
        enabled_features = [k for k, v in report_options.items() if v]
        logging.info(f"Enabled features: {enabled_features}")
        
        try:
            # שמירת ההגדרות
            logging.info("Starting to save settings...")
            AdminSettings.set_setting('daily_email_enabled', daily_email_enabled, 'boolean', 
                                    'האם לשלוח מייל יומי עם נתוני קופונים')
            logging.info("Saved daily_email_enabled")
            
            AdminSettings.set_setting('daily_email_hour', int(email_hour), 'integer', 
                                    'שעה לשליחת המייל היומי (0-23)')
            logging.info("Saved daily_email_hour")
            
            AdminSettings.set_setting('daily_email_minute', int(email_minute), 'integer', 
                                    'דקה לשליחת המייל היומי (0-59)')
            logging.info("Saved daily_email_minute")
            
            AdminSettings.set_setting('daily_email_recipient', recipient_email, 'string', 
                                    'כתובת מייל למקבל המייל היומי')
            logging.info("Saved daily_email_recipient")
            
            AdminSettings.set_setting('email_report_options', report_options, 'json', 
                                    'אפשרויות תוכן הדוח המתקדם')
            logging.info("Saved email_report_options")
            
            # עדכון הscheduler עם ההגדרות החדשות
            from scheduler_config import update_scheduler_time
            update_scheduler_time(int(email_hour), int(email_minute))
            logging.info("Updated scheduler time")
            
            flash('הגדרות המייל נשמרו בהצלחה! הזמן עודכן בscheduler.', 'success')
            logging.info("Settings saved successfully!")
            
        except Exception as e:
            flash(f'שגיאה בשמירת ההגדרות: {str(e)}', 'danger')
            logging.error(f"Error saving email settings: {e}", exc_info=True)
    
    # טעינת הגדרות נוכחות
    # ברירות מחדל לאפשרויות הדוח
    default_report_options = {
        'chart_coupons_by_company': True,
        'chart_value_pie': True,
        'chart_weekly_trend': True,
        'chart_price_histogram': False,
        'metrics_roi': True,
        'metrics_recent_activity': True,
        'metrics_expiring': True,
        'metrics_top_companies': True,
        'insights_top3': True,
        'insights_weekly_comparison': True,
        'insights_expiring_alerts': True,
        'analytics_conversion_rate': False,
        'analytics_time_to_sell': False,
        'analytics_profitable_companies': False,
        'segmentation_categories': False,
        'segmentation_price_ranges': False,
        'comparisons_monthly': False,
    }
    
    current_settings = {
        'daily_email_enabled': AdminSettings.get_setting('daily_email_enabled', True),
        'email_hour': AdminSettings.get_setting('daily_email_hour', 9),  # Changed default to 9 AM Israel time
        'email_minute': AdminSettings.get_setting('daily_email_minute', 0),
        'recipient_email': AdminSettings.get_setting('daily_email_recipient', 'itayk93@gmail.com'),
        'report_options': AdminSettings.get_setting('email_report_options', default_report_options)
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
    
    return redirect(url_for('admin_bp.admin_email_bp.email_settings'))

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
    
    return redirect(url_for('admin_bp.admin_email_bp.email_settings'))


@admin_email_bp.route('/view-full-report', methods=['GET'])
def view_full_report():
    """
    צפייה בדוח המלא כ-HTML מעוצב
    """
    try:
        from app import create_app
        from app.analytics.email_analytics import generate_full_email_content
        
        app = create_app()
        html_content = generate_full_email_content(app)
        
        return html_content
        
    except Exception as e:
        logging.error(f"Error generating full report: {e}")
        return f"<h1 style='direction: rtl; text-align: right; font-family: Arial;'>שגיאה בטעינת הדוח: {str(e)}</h1>"


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
    
    return redirect(url_for('admin_bp.admin_email_bp.email_settings'))