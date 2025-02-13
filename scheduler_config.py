import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.extensions import db
from app.models import Coupon, Company   # <-- הוספנו את Company
from app.helpers import send_email
from flask import current_app

# משתנה גלובלי לסימון אם כבר שלחנו את המייל היומי (לצורך פונקציות ישנות – לא בשימוש כשמשתמשים בטבלת הסטטוס)
WAS_SENT_TODAY = False

# יצירת מופע של ה-Scheduler
scheduler = BackgroundScheduler()

def reset_was_sent_today():
    """
    איפוס יומי של הדגל שמסמן אם כבר שלחנו את המייל.
    רץ כל חצות (00:00).
    """
    global WAS_SENT_TODAY
    WAS_SENT_TODAY = False
    logging.info("reset_was_sent_today - Resetting WAS_SENT_TODAY to False")

from datetime import date, timedelta

def categorize_coupons(coupons):
    """
    מחלק את הקופונים לשלוש קטגוריות: היום, מחר, והמשך החודש.
    """
    today = date.today()
    tomorrow = today + timedelta(days=1)
    categorized = {
        "today_coupons": [],
        "tomorrow_coupons": [],
        "future_coupons": []
    }
    for coupon in coupons:
        expiration_date = datetime.datetime.strptime(coupon['expiration'], "%Y-%m-%d").date()
        if expiration_date == today:
            categorized["today_coupons"].append(coupon)
        elif expiration_date == tomorrow:
            categorized["tomorrow_coupons"].append(coupon)
        else:
            categorized["future_coupons"].append(coupon)
    return categorized

# --- פונקציות לשליחת התראות ועדכון נתונים (קוד כפי שהצגת, ללא שינוי עיקרי) ---

from flask import render_template
from sqlalchemy.sql import text

def send_expiration_warnings():
    """
    שליחת התראות למשתמשים על קופונים שעומדים לפוג לפי נקודות זמן שונות.
    """
    # יבוא מקומי של create_app כדי למנוע מעגל תלות
    from app import create_app
    from app.extensions import db
    from app.helpers import send_email
    app = create_app()
    with app.app_context():
        query = text("""
            SELECT 
                c.id AS coupon_id,
                c.code, 
                c.value,
                c.expiration, 
                c.company, 
                c.user_id, 
                u.email, 
                u.first_name,
                COALESCE(
                    (SELECT SUM(transaction_amount) FROM (
                        SELECT -used_amount AS transaction_amount
                        FROM coupon_usage WHERE coupon_id = c.id
                        UNION ALL
                        SELECT -usage_amount + recharge_amount
                        FROM coupon_transaction WHERE coupon_id = c.id
                    ) AS subquery),
                    c.value
                ) AS remaining_value
            FROM coupon c
            JOIN users u ON c.user_id = u.id
            WHERE c.expiration IS NOT NULL
              AND c.status = 'פעיל'
              AND c.is_for_sale = FALSE
              AND (
                (TO_DATE(c.expiration, 'YYYY-MM-DD') = CURRENT_DATE + INTERVAL '30 days' AND c.reminder_sent_30_days = FALSE)
                OR (TO_DATE(c.expiration, 'YYYY-MM-DD') = CURRENT_DATE + INTERVAL '7 days' AND c.reminder_sent_7_days = FALSE)
                OR (TO_DATE(c.expiration, 'YYYY-MM-DD') = CURRENT_DATE + INTERVAL '1 days' AND c.reminder_sent_1_day = FALSE)
                OR (TO_DATE(c.expiration, 'YYYY-MM-DD') = CURRENT_DATE AND c.reminder_sent_today = FALSE)
              );
        """)
        coupons = db.session.execute(query).fetchall()
        users = {}
        for coupon in coupons:
            user_id = coupon.user_id
            expiration_date = datetime.datetime.strptime(coupon.expiration, "%Y-%m-%d").date()
            days_left = (expiration_date - date.today()).days
            expiration_formatted = expiration_date.strftime('%d/%m/%Y')
            users.setdefault(user_id, {
                'email': coupon.email,
                'first_name': coupon.first_name,
                'coupons': []
            })
            import os
            import base64

            # נניח שיש לנו את המודל Company עם image_path
            company_obj = Company.query.filter_by(name=coupon.company).first()
            logo_filename = company_obj.image_path if company_obj and company_obj.image_path else "default_logo.png"
            # נניח שהתמונות נמצאות בתיקייה static/logos
            logo_filepath = os.path.join(current_app.root_path, "static", "logos", "images", logo_filename)

            # נסה לקרוא את הקובץ ולהמיר ל-Base64
            try:
                with open(logo_filepath, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            except Exception as e:
                # במקרה של שגיאה, נשתמש במחרוזת ריקה או בלוגו ברירת מחדל כלשהו
                logging.error(f"Error reading logo file {logo_filepath}: {e}")
                encoded_string = ""

            users[user_id]['coupons'].append({
                'coupon_id': coupon.coupon_id,
                'company': coupon.company,
                # נעביר את מחרוזת ה-Base64
                'company_logo_base64': encoded_string,
                'code': coupon.code,
                'remaining_value': coupon.remaining_value,
                'expiration': coupon.expiration,
                'expiration_formatted': expiration_formatted,
                'days_left': days_left,
                'coupon_detail_link': f"https://coupon-manager-project.onrender.com/coupon_detail/{coupon.coupon_id}"
            })

        for user in users.values():
            email_content = render_template(
                "emails/coupon_expiration_warning.html",
                user=user,
                coupons=user['coupons'],
                current_year=date.today().year
            )
            send_email(
                sender_email="noreply@couponmasteril.com",
                sender_name="Coupon Master",
                recipient_email=user['email'],
                recipient_name=user['first_name'],
                subject="התראה על תפוגת קופונים",
                html_content=email_content
            )
            update_query = text("""
                UPDATE coupon
                SET reminder_sent_30_days = TRUE
                WHERE id = ANY(:coupon_ids)
            """)
            db.session.execute(update_query, {
                "coupon_ids": [c['coupon_id'] for c in user['coupons']]
            })
            db.session.commit()


def daily_email_flow():
    """
    פונקציה ששולחת את המייל היומי רק אם הוא עדיין לא נשלח היום.
    """
    from app import create_app
    from scheduler_utils import update_company_counts_and_send_email
    from app.extensions import db
    from scheduler_utils import load_status, save_status  # לוודא שהייבוא תקין

    app = create_app()
    with app.app_context():  # נעטוף את כל הקריאות ב-context של Flask
        if load_status():
            logging.info("daily_email_flow - Email already sent today. Skipping.")
            return

        try:
            update_company_counts_and_send_email(app)
            save_status(True)
            logging.info("daily_email_flow - Email sent successfully, status saved in DB.")
        except Exception as e:
            logging.error(f"daily_email_flow - Error: {e}")

from sqlalchemy import text

def reset_dismissed_alerts():
    """
    איפוס ההתראות הדחויות לכל המשתמשים פעם ביום.
    """
    try:
        db.session.execute(text("UPDATE users SET dismissed_expiring_alert_at = NULL"))
        db.session.commit()
        logging.info("reset_dismissed_alerts - All dismissed alerts reset successfully.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"reset_dismissed_alerts - Error resetting dismissed alerts: {e}")

# --- פונקציות לעבודה עם טבלת הסטטוס (Supabase) ---
# נניח שהפונקציות load_process_status ו-save_process_status הוגדרו בקובץ scheduler_utils.py, כפי שהודגם בהודעה קודמת.
# אם אינך מייבא אותן כבר, יש לוודא שהן קיימות בקובץ זה.

from sqlalchemy.sql import text


def load_process_status(process):
    """
    טוען את הסטטוס של תהליך מסוים (למשל, 'reset', 'expiration', 'daily_email', 'dismissed_reset')
    עבור התאריך הנוכחי.
    """
    today = datetime.date.today()
    query = text("SELECT was_sent FROM daily_email_status WHERE date = :today AND process = :process")
    result = db.session.execute(query, {"today": today, "process": process}).fetchone()
    return result[0] if result else False

def save_process_status(process, was_sent):
    """
    שומר את הסטטוס של תהליך מסוים עבור התאריך הנוכחי.
    משתמש ב-UPsert.
    """
    today = datetime.date.today()
    query = text("""
        INSERT INTO daily_email_status (date, process, was_sent)
        VALUES (:today, :process, :was_sent)
        ON CONFLICT (date, process) DO UPDATE SET was_sent = EXCLUDED.was_sent;
    """)
    try:
        db.session.execute(query, {"today": today, "process": process, "was_sent": was_sent})
        db.session.commit()
        logging.info("Updated status for process '%s' for date %s: %s", process, today, was_sent)
    except Exception as e:
        db.session.rollback()
        logging.error("Error updating status for process '%s': %s", process, e)

# --- פונקציית הקונפיגורציה של ה-Scheduler ---
def configure_scheduler():
    """
    מגדיר את עבודות ה-Scheduler כך שכל תהליך (איפוס, התראות, מייל יומי, איפוס התראות דחויות)
    יתוזמן להתבצע בזמנים קבועים (00:00 או 8:00), ואם המערכת הייתה סגורה והפעולה לא בוצעה,
    היא תתבצע בפעם הראשונה שהמערכת עולה באותו יום.
    """
    # יבוא create_app רק בתוך הפונקציה כדי לשבור את המעגל
    from app import create_app

    global scheduler
    if not scheduler.running:
        logging.info("Starting scheduler and adding jobs...")

        # --- תהליך A: איפוס סטטוס (reset) ---
        scheduler.add_job(
            func=lambda: save_process_status('reset', False),
            trigger=CronTrigger(hour=0, minute=0),
            id='reset_status',
            name='Reset daily status at 2:00',
            replace_existing=True
        )

        # --- תהליך B: שליחת התראות על קופונים שפג תוקפם (expiration warnings) ---
        scheduler.add_job(
            func=send_expiration_warnings,
            trigger=CronTrigger(hour=6, minute=0),
            id='expiration_warnings',
            name='Send expiration warnings at 8:00',
            replace_existing=True
        )

        # --- תהליך C: שליחת המייל היומי (daily email) ---
        scheduler.add_job(
            func=daily_email_flow,
            trigger=CronTrigger(hour=6, minute=0),
            id='daily_email',
            name='Send daily email at 8:00',
            replace_existing=True
        )

        # --- תהליך D: איפוס התראות דחויות (dismissed alerts reset) ---
        scheduler.add_job(
            func=reset_dismissed_alerts,
            trigger=CronTrigger(hour=0, minute=0),
            id='dismissed_reset',
            name='Reset dismissed alerts at 2:00',
            replace_existing=True
        )

        scheduler.start()
        logging.info("Scheduler started successfully with jobs: %s", scheduler.get_jobs())

        # כעת נבדוק עבור כל תהליך – אם לא בוצע היום, נבצע אותו מיד בהפעלה הראשונה של המערכת ביום
        app = create_app()
        with app.app_context():
            now = datetime.datetime.now()
            logging.info("Current time: %s:%s", now.hour, now.minute)

            # תהליך A: איפוס סטטוס (reset)
            if not load_process_status('reset'):
                logging.info("Process 'reset' not executed today. Executing reset process now...")
                save_process_status('reset', False)
            else:
                logging.info("Process 'reset' already executed today.")

            # תהליך B: שליחת התראות (expiration warnings)
            if now.hour >= 6 and not load_process_status('expiration'):
                logging.info("Process 'expiration' not executed today and time is after 8:00. Executing expiration warnings now...")
                send_expiration_warnings()
                save_process_status('expiration', True)
            else:
                logging.info("Process 'expiration' already executed today or time is before 8:00.")

            # תהליך C: שליחת המייל היומי (daily email)
            if now.hour >= 6 and not load_process_status('daily_email'):
                logging.info("Process 'daily_email' not executed today and time is after 8:00. Executing daily email now...")
                daily_email_flow()
                save_process_status('daily_email', True)
            else:
                logging.info("Process 'daily_email' already executed today or time is before 8:00.")

            # תהליך D: איפוס התראות דחויות (dismissed alerts reset)
            if not load_process_status('dismissed_reset'):
                logging.info("Process 'dismissed_reset' not executed today. Executing dismissed alerts reset now...")
                reset_dismissed_alerts()
                save_process_status('dismissed_reset', True)
            else:
                logging.info("Process 'dismissed_reset' already executed today.")
    else:
        logging.info("Scheduler is already running, skipping re-initialization.")
