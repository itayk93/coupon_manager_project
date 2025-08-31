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
        
        # הגדרות תזמון חדשות
        schedule_type = request.form.get('schedule_type', 'daily')  # daily, weekly, monthly, specific_dates
        weekly_day = request.form.get('weekly_day', '1')  # יום בשבוע (1=ב׳, 7=א׳)
        monthly_day = request.form.get('monthly_day', '1')  # יום בחודש
        specific_dates = request.form.get('specific_dates', '')  # תאריכים ספציפיים מופרדים בפסיקים
        
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
            
            # שמירת הגדרות תזמון חדשות
            AdminSettings.set_setting('email_schedule_type', schedule_type, 'string', 
                                    'סוג תזמון המייל (daily/weekly/monthly/specific_dates)')
            AdminSettings.set_setting('email_weekly_day', int(weekly_day), 'integer', 
                                    'יום בשבוע לשליחה (1=ב׳, 7=א׳)')
            AdminSettings.set_setting('email_monthly_day', int(monthly_day), 'integer', 
                                    'יום בחודש לשליחה')
            AdminSettings.set_setting('email_specific_dates', specific_dates, 'string', 
                                    'תאריכים ספציפיים מופרדים בפסיקים')
            logging.info("Saved scheduling settings")
            
            AdminSettings.set_setting('email_report_options', report_options, 'json', 
                                    'אפשרויות תוכן הדוח המתקדם')
            logging.info("Saved email_report_options")
            
            # עדכון מיילים מתוכננים קיימים לזמן החדש
            try:
                update_existing_scheduled_emails(int(email_hour), int(email_minute))
                logging.info("Updated existing scheduled emails with new timing")
            except Exception as e:
                logging.error(f"Error updating existing scheduled emails: {e}")
            
            # Scheduler functionality removed - using external cron jobs
            logging.info("Email settings saved (scheduler disabled)")
            
            flash('הגדרות המייל נשמרו בהצלחה! מיילים מתוכננים עודכנו לזמן החדש.', 'success')
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
        'report_options': AdminSettings.get_setting('email_report_options', default_report_options),
        # הגדרות תזמון חדשות
        'schedule_type': AdminSettings.get_setting('email_schedule_type', 'daily'),
        'weekly_day': AdminSettings.get_setting('email_weekly_day', 1),
        'monthly_day': AdminSettings.get_setting('email_monthly_day', 1),
        'specific_dates': AdminSettings.get_setting('email_specific_dates', '')
    }
    
    # בדיקת סטטוס שליחה היום (scheduler disabled)
    email_sent_today = False
    
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
        # יצירת ניוזלטר יומי על בסיס ההגדרות
        success = create_daily_newsletter()
        if success:
            flash('ניוזלטר יומי נוצר והוגדר לשליחה!', 'success')
        else:
            flash('שגיאה ביצירת הניוזלטר היומי', 'danger')
        
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
        # איפוס סטטוס המייל (scheduler disabled - placeholder)
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


def create_daily_newsletter():
    """
    יצירת ניוזלטר יומי על בסיס הגדרות המייל
    """
    try:
        from app.models import Newsletter, AdminSettings, Company
        from datetime import datetime, timezone, timedelta
        from sqlalchemy import text
        
        # קבלת ההגדרות
        schedule_type = AdminSettings.get_setting('email_schedule_type', 'daily')
        send_time_hour = AdminSettings.get_setting('daily_email_hour', 9)
        send_time_minute = AdminSettings.get_setting('daily_email_minute', 0)
        recipient_email = AdminSettings.get_setting('daily_email_recipient', 'itayk93@gmail.com')
        
        # קבלת הגדרות תזמון נוספות
        weekly_day = AdminSettings.get_setting('email_weekly_day', 1)  # יום בשבוע (1=ב׳, 7=א׳)
        monthly_day = AdminSettings.get_setting('email_monthly_day', 1)  # יום בחודש
        specific_dates = AdminSettings.get_setting('email_specific_dates', '')  # תאריכים ספציפיים
        
        # יצירת זמן השליחה - המרה מזמן ישראל לUTC
        import pytz
        israel_tz = pytz.timezone('Asia/Jerusalem')
        utc_tz = pytz.timezone('UTC')
        
        now = datetime.now(timezone.utc)
        
        if schedule_type == 'daily':
            # יצירת תאריך השליחה בזמן ישראל
            israel_now = now.astimezone(israel_tz)
            israel_scheduled = israel_now.replace(hour=send_time_hour, minute=send_time_minute, second=0, microsecond=0)
            
            # אם הזמן כבר עבר היום בישראל, הגדר למחר
            if israel_scheduled <= israel_now:
                israel_scheduled += timedelta(days=1)
            
            # המרה חזרה ל-UTC
            scheduled_time = israel_scheduled.astimezone(utc_tz).replace(tzinfo=timezone.utc)
            
        elif schedule_type == 'weekly':
            # תזמון שבועי - שליחה ביום מסוים בשבוע
            israel_now = now.astimezone(israel_tz)
            
            # חישוב היום הנוכחי בשבוע (0=א׳, 1=ב׳, ..., 6=ש׳)
            current_weekday = israel_now.weekday()
            target_weekday = (weekly_day - 1) % 7  # המרה מ-1-7 ל-0-6
            
            # חישוב כמה ימים צריך להוסיף כדי להגיע ליום המטרה
            days_to_add = (target_weekday - current_weekday) % 7
            if days_to_add == 0 and israel_now.hour >= send_time_hour and israel_now.minute >= send_time_minute:
                # אם היום הוא היום המטרה והזמן כבר עבר, נקבע לשבוע הבא
                days_to_add = 7
            
            # יצירת התאריך המתוזמן
            israel_scheduled = israel_now.replace(hour=send_time_hour, minute=send_time_minute, second=0, microsecond=0) + timedelta(days=days_to_add)
            
            # המרה חזרה ל-UTC
            scheduled_time = israel_scheduled.astimezone(utc_tz).replace(tzinfo=timezone.utc)
            
        elif schedule_type == 'monthly':
            # תזמון חודשי - שליחה ביום מסוים בחודש
            israel_now = now.astimezone(israel_tz)
            
            # יצירת התאריך המתוזמן לחודש הבא
            if israel_now.day >= monthly_day and (israel_now.hour > send_time_hour or (israel_now.hour == send_time_hour and israel_now.minute >= send_time_minute)):
                # אם היום כבר עבר או הזמן עבר, נקבע לחודש הבא
                if israel_now.month == 12:
                    next_month = israel_now.replace(year=israel_now.year + 1, month=1, day=monthly_day)
                else:
                    next_month = israel_now.replace(month=israel_now.month + 1, day=monthly_day)
                israel_scheduled = next_month.replace(hour=send_time_hour, minute=send_time_minute, second=0, microsecond=0)
            else:
                # נקבע לחודש הנוכחי
                israel_scheduled = israel_now.replace(day=monthly_day, hour=send_time_hour, minute=send_time_minute, second=0, microsecond=0)
            
            # המרה חזרה ל-UTC
            scheduled_time = israel_scheduled.astimezone(utc_tz).replace(tzinfo=timezone.utc)
            
        elif schedule_type == 'specific_dates':
            # תזמון לתאריכים ספציפיים
            if specific_dates:
                # פיצול התאריכים המופרדים בפסיקים
                date_list = [d.strip() for d in specific_dates.split(',') if d.strip()]
                if date_list:
                    # נקבע לתאריך הראשון שעדיין לא עבר
                    for date_str in date_list:
                        try:
                            # ניסיון לפרסר את התאריך בפורמטים שונים
                            for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
                                try:
                                    parsed_date = datetime.strptime(date_str, fmt)
                                    # הוספת השעה והדקה
                                    scheduled_date = parsed_date.replace(hour=send_time_hour, minute=send_time_minute, second=0, microsecond=0)
                                    
                                    # המרה לזמן ישראל
                                    israel_scheduled = israel_tz.localize(scheduled_date)
                                    
                                    # בדיקה אם התאריך עדיין לא עבר
                                    if israel_scheduled > israel_now:
                                        scheduled_time = israel_scheduled.astimezone(utc_tz).replace(tzinfo=timezone.utc)
                                        break
                                except ValueError:
                                    continue
                            else:
                                continue
                            break
                        except:
                            continue
                    else:
                        # אם כל התאריכים עברו, נקבע לתאריך הבא
                        scheduled_time = now + timedelta(days=1)
                        scheduled_time = scheduled_time.replace(hour=send_time_hour, minute=send_time_minute, second=0, microsecond=0)
                else:
                    # אם אין תאריכים, נקבע לשעה הבאה
                    scheduled_time = now + timedelta(hours=1)
                    scheduled_time = scheduled_time.replace(minute=send_time_minute, second=0, microsecond=0)
            else:
                # אם אין תאריכים, נקבע לשעה הבאה
                scheduled_time = now + timedelta(hours=1)
                scheduled_time = scheduled_time.replace(minute=send_time_minute, second=0, microsecond=0)
        else:
            # ברירת מחדל - לשעה הבאה
            scheduled_time = now + timedelta(hours=1)
            scheduled_time = scheduled_time.replace(minute=send_time_minute, second=0, microsecond=0)

        # עדכון ספירת הקופונים לחברות
        update_query = text(
            """
            UPDATE companies c
            SET company_count = COALESCE(subquery.company_count, 0)
            FROM (
                SELECT c.id, COUNT(cp.company) AS company_count
                FROM companies c
                LEFT JOIN coupon cp ON c.name = cp.company
                GROUP BY c.id
            ) AS subquery
            WHERE c.id = subquery.id;
            """
        )
        db.session.execute(update_query)
        db.session.commit()
        
        # קבלת נתוני החברות המעודכנים
        companies = Company.query.order_by(Company.company_count.desc()).all()
        
        # קביעת כותרת ותיאור בהתאם לסוג התזמון
        if schedule_type == 'daily':
            report_title = "דוח יומי - סטטיסטיקות קופונים"
            report_description = "דוח אוטומטי יומי עם נתוני החברות והקופונים העדכניים"
            title_suffix = "יומי"
        elif schedule_type == 'weekly':
            report_title = "דוח שבועי - סטטיסטיקות קופונים"
            report_description = "דוח אוטומטי שבועי עם נתוני החברות והקופונים העדכניים"
            title_suffix = "שבועי"
        elif schedule_type == 'monthly':
            report_title = "דוח חודשי - סטטיסטיקות קופונים"
            report_description = "דוח אוטומטי חודשי עם נתוני החברות והקופונים העדכניים"
            title_suffix = "חודשי"
        elif schedule_type == 'specific_dates':
            report_title = "דוח מיוחד - סטטיסטיקות קופונים"
            report_description = "דוח אוטומטי לתאריכים מיוחדים עם נתוני החברות והקופונים העדכניים"
            title_suffix = "מיוחד"
        else:
            report_title = "דוח - סטטיסטיקות קופונים"
            report_description = "דוח אוטומטי עם נתוני החברות והקופונים העדכניים"
            title_suffix = ""
        
        # יצירת תוכן הניוזלטר
        html_content = f"""
        <div style="direction: rtl; font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #2c3e50; text-align: center; border-bottom: 2px solid #3498db; padding-bottom: 10px;">
                {report_title}
            </h2>
            <p style="text-align: center; color: #7f8c8d; margin-bottom: 30px;">
                נתונים מעודכנים נכון לתאריך: {now.strftime("%d/%m/%Y %H:%M")}
            </p>
            
            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h3 style="color: #2c3e50; margin-top: 0;">סיכום כללי:</h3>
                <p><strong>סך הכל חברות:</strong> {str(len(companies))}</p>
                <p><strong>סך הכל קופונים:</strong> {str(sum(c.company_count for c in companies))}</p>
            </div>
            
            <h3 style="color: #2c3e50;">פירוט לפי חברות:</h3>
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                <thead>
                    <tr style="background-color: #3498db; color: white;">
                        <th style="padding: 12px; text-align: right; border: 1px solid #ddd;">שם החברה</th>
                        <th style="padding: 12px; text-align: center; border: 1px solid #ddd;">מספר קופונים</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for i, company in enumerate(companies):
            row_color = "#f2f2f2" if i % 2 == 0 else "white"
            html_content += f"""
                    <tr style="background-color: {row_color};">
                        <td style="padding: 10px; text-align: right; border: 1px solid #ddd;">{company.name}</td>
                        <td style="padding: 10px; text-align: center; border: 1px solid #ddd; font-weight: bold; color: #2c3e50;">{company.company_count}</td>
                    </tr>
            """
        
        html_content += """
                </tbody>
            </table>
            
            <div style="margin-top: 30px; padding: 15px; background-color: #e8f5e8; border-radius: 5px; text-align: center;">
                <p style="margin: 0; color: #27ae60; font-size: 14px;">
                    <strong>דוח זה נוצר אוטומטית ע"י מערכת ניהול הקופונים</strong>
                </p>
            </div>
        </div>
        """
        
        # יצירת הניוזלטר במסד הנתונים
        newsletter = Newsletter(
            title=f"דוח {title_suffix} - {now.strftime('%d/%m/%Y')}",
            newsletter_type='custom',
            custom_html=html_content,
            main_title=report_title,
            content=report_description,
            is_published=True,
            scheduled_send_time=scheduled_time,
            created_by=1,  # Admin user ID
            is_sent=False
        )
        
        db.session.add(newsletter)
        db.session.commit()
        
        logging.info(f"Daily newsletter created successfully with ID {newsletter.id}, scheduled for {scheduled_time}")
        return True
        
    except Exception as e:
        logging.error(f"Error creating daily newsletter: {e}")
        db.session.rollback()
        return False


def update_existing_scheduled_emails(new_hour, new_minute):
    """
    עדכון מיילים מתוכננים קיימים לזמן חדש
    """
    try:
        import pytz
        from datetime import datetime, timezone
        from app.models import Newsletter
        
        israel_tz = pytz.timezone('Asia/Jerusalem')
        utc_tz = pytz.timezone('UTC')
        
        # מציאת כל המיילים המתוכננים שטרם נשלחו
        future_emails = Newsletter.query.filter(
            Newsletter.is_sent == False,
            Newsletter.title.like('דוח%'),
            Newsletter.scheduled_send_time.isnot(None),
            Newsletter.scheduled_send_time > datetime.now(timezone.utc)
        ).all()
        
        logging.info(f"Found {len(future_emails)} scheduled emails to update")
        
        for newsletter in future_emails:
            old_time = newsletter.scheduled_send_time
            old_israel = old_time.astimezone(israel_tz)
            
            # יצירת זמן חדש - אותו תאריך, זמן חדש
            new_israel = old_israel.replace(
                hour=new_hour,
                minute=new_minute,
                second=0,
                microsecond=0
            )
            
            # המרה ל-UTC
            new_utc = new_israel.astimezone(utc_tz).replace(tzinfo=timezone.utc)
            
            newsletter.scheduled_send_time = new_utc
            logging.info(f"Updated newsletter {newsletter.id} from {old_israel.strftime('%H:%M')} to {new_israel.strftime('%H:%M')} Israel time")
        
        db.session.commit()
        logging.info(f"Successfully updated {len(future_emails)} scheduled emails")
        return True
        
    except Exception as e:
        logging.error(f"Error updating scheduled emails: {e}")
        db.session.rollback()
        return False