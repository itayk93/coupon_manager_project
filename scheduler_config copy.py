import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask
from app.extensions import db
from app.models import Coupon
from app.helpers import send_email  # ודא שהפונקציה send_email מוגדרת

# משתנה גלובלי לסימון אם כבר שלחנו את המייל היומי
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

from datetime import datetime, date, timedelta

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
        expiration_date = datetime.strptime(coupon['expiration'], "%Y-%m-%d").date()
        if expiration_date == today:
            categorized["today_coupons"].append(coupon)
        elif expiration_date == tomorrow:
            categorized["tomorrow_coupons"].append(coupon)
        else:
            categorized["future_coupons"].append(coupon)

    return categorized

from flask import render_template
from sqlalchemy.sql import text
from datetime import date, timedelta, datetime

def send_expiration_warnings_old_old():
    from app import create_app
    app = create_app()
    with app.app_context():
        # שאילתה שמביאה את הנתונים, כולל חישוב יתרה (remaining_value)
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
                -- מחושב דינמית אם יש טבלאות usage ו-transaction:
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
              AND TO_DATE(c.expiration, 'YYYY-MM-DD') 
                  BETWEEN CURRENT_DATE AND (CURRENT_DATE + INTERVAL '30 days')
              AND c.reminder_sent_30_days = FALSE
              AND c.status = 'פעיל'
              AND c.is_for_sale = FALSE;
        """)

        coupons = db.session.execute(query).fetchall()
        users = {}

        for coupon in coupons:
            user_id = coupon.user_id

            # חישוב "תוקף עד"
            expiration_date = datetime.strptime(coupon.expiration, "%Y-%m-%d").date()
            days_left = (expiration_date - date.today()).days
            expiration_formatted = expiration_date.strftime('%d/%m/%Y')

            # מכניסים את הקופון לרשימת הקופונים של המשתמש
            # בלי שום פענוח על code
            users.setdefault(user_id, {
                'email': coupon.email,
                'first_name': coupon.first_name,
                'coupons': []
            })
            users[user_id]['coupons'].append({
                'coupon_id': coupon.coupon_id,
                'company': coupon.company,
                'code': coupon.code,  # פה זה הקוד "כמו שהוא" מה-DB
                'remaining_value': coupon.remaining_value,
                'expiration': coupon.expiration,
                'expiration_formatted': expiration_formatted,
                'days_left': days_left,
                'coupon_detail_link': f"https://yourwebsite.com/coupon_detail/{coupon.coupon_id}"
            })

        # שליחת מייל אחד לכל משתמש
        for user in users.values():
            email_content = render_template(
                "emails/coupon_expiration_warning.html",  # התבנית שלך
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

            # עדכון DB כדי שלא נשלח שוב למחרת
            update_query = text("""
                UPDATE coupon
                SET reminder_sent_30_days = TRUE
                WHERE id = ANY(:coupon_ids)
            """)
            db.session.execute(update_query, {
                "coupon_ids": [c['coupon_id'] for c in user['coupons']]
            })
            db.session.commit()

from flask import render_template
from sqlalchemy.sql import text
from datetime import date, timedelta, datetime
from app.helpers import decrypt_coupon_code  # ייבוא הפונקציה לפענוח

def send_expiration_warnings_old():
    from app import create_app
    app = create_app()
    with app.app_context():
        # שאילתה שמביאה את הנתונים, כולל חישוב יתרה (remaining_value)
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
                -- מחושב דינמית אם יש טבלאות usage ו-transaction:
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
              AND TO_DATE(c.expiration, 'YYYY-MM-DD') 
                  BETWEEN CURRENT_DATE AND (CURRENT_DATE + INTERVAL '30 days')
              AND c.reminder_sent_30_days = FALSE
              AND c.status = 'פעיל'
              AND c.is_for_sale = FALSE;
        """)

        coupons = db.session.execute(query).fetchall()
        users = {}

        for coupon in coupons:
            user_id = coupon.user_id

            # פענוח קוד הקופון
            decrypted_code = decrypt_coupon_code(coupon.code)

            # חישוב "תוקף עד"
            expiration_date = datetime.strptime(coupon.expiration, "%Y-%m-%d").date()
            days_left = (expiration_date - date.today()).days
            expiration_formatted = expiration_date.strftime('%d/%m/%Y')

            # מכניסים את הקופון לרשימת הקופונים של המשתמש עם הקוד המפוענח
            users.setdefault(user_id, {
                'email': coupon.email,
                'first_name': coupon.first_name,
                'coupons': []
            })
            users[user_id]['coupons'].append({
                'coupon_id': coupon.coupon_id,
                'company': coupon.company,
                'code': decrypted_code if decrypted_code else "שגיאה בפענוח",  # אם יש שגיאה, לא שולחים את הקוד המצונזר
                'remaining_value': coupon.remaining_value,
                'expiration': coupon.expiration,
                'expiration_formatted': expiration_formatted,
                'days_left': days_left,
                'coupon_detail_link': f"https://yourwebsite.com/coupon_detail/{coupon.coupon_id}"
            })

        # שליחת מייל אחד לכל משתמש
        for user in users.values():
            email_content = render_template(
                "emails/coupon_expiration_warning.html",  # התבנית שלך
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

            # עדכון DB כדי שלא נשלח שוב למחרת
            update_query = text("""
                UPDATE coupon
                SET reminder_sent_30_days = TRUE
                WHERE id = ANY(:coupon_ids)
            """)
            db.session.execute(update_query, {
                "coupon_ids": [c['coupon_id'] for c in user['coupons']]
            })
            db.session.commit()


from flask import render_template
from sqlalchemy.sql import text
from datetime import date, datetime, timedelta
from app.helpers import send_email


def send_expiration_warnings():
    """
    שליחת התראות למשתמשים על קופונים שעומדים לפוג לפי נקודות זמן שונות (30 יום, 7 ימים, יום לפני, וביום עצמו).
    """

    from app import create_app
    from sqlalchemy.sql import text
    from app.extensions import db
    from flask import render_template
    from app.helpers import send_email

    app = create_app()

    with app.app_context():
        # שליפת כל הקופונים שצריכים תזכורת היום
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
            expiration_date = datetime.strptime(coupon.expiration, "%Y-%m-%d").date()
            days_left = (expiration_date - date.today()).days
            expiration_formatted = expiration_date.strftime('%d/%m/%Y')

            users.setdefault(user_id, {
                'email': coupon.email,
                'first_name': coupon.first_name,
                'coupons': []
            })
            users[user_id]['coupons'].append({
                'coupon_id': coupon.coupon_id,
                'company': coupon.company,
                'code': coupon.code,
                'remaining_value': coupon.remaining_value,
                'expiration': coupon.expiration,
                'expiration_formatted': expiration_formatted,
                'days_left': days_left,
                'coupon_detail_link': f"https://yourwebsite.com/coupon_detail/{coupon.coupon_id}"
            })

        # שליחת מיילים למשתמשים
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

            from sqlalchemy.dialects.postgresql import ARRAY

            # סימון שהמייל נשלח
            update_query = text("""
                UPDATE coupon
                SET 
                    reminder_sent_30_days = CASE 
                        WHEN TO_DATE(expiration, 'YYYY-MM-DD') = CURRENT_DATE + INTERVAL '30 days' 
                        THEN TRUE ELSE reminder_sent_30_days 
                    END,
                    reminder_sent_7_days = CASE 
                        WHEN TO_DATE(expiration, 'YYYY-MM-DD') = CURRENT_DATE + INTERVAL '7 days' 
                        THEN TRUE ELSE reminder_sent_7_days 
                    END,
                    reminder_sent_1_day = CASE 
                        WHEN TO_DATE(expiration, 'YYYY-MM-DD') = CURRENT_DATE + INTERVAL '1 days' 
                        THEN TRUE ELSE reminder_sent_1_day 
                    END,
                    reminder_sent_today = CASE 
                        WHEN TO_DATE(expiration, 'YYYY-MM-DD') = CURRENT_DATE 
                        THEN TRUE ELSE reminder_sent_today 
                    END
                WHERE id = ANY(:coupon_ids);
            """)

            # ודא ש-coupon_ids מועבר כטופל

            coupon_ids = [c[0] for c in coupons]  # הקופון ID הוא האיבר הראשון בטאפל
            db.session.execute(update_query, {"coupon_ids": coupon_ids})
            db.session.commit()

import logging
from scheduler_utils import load_status, save_status

def daily_email_flow():
    """
    פונקציה ששולחת את המייל היומי רק אם הוא עדיין לא נשלח היום.
    """
    # יבוא מקומי של create_app כדי למנוע מעגל תלות
    from app import create_app
    from scheduler_utils import update_company_counts_and_send_email
    from app.extensions import db
    # כאן אנו בודקים את הסטטוס דרך הטבלה (ללא המשתנה הגלובלי WAS_SENT_TODAY)
    from scheduler_utils import load_status, save_status
    if load_status():
        logging.info("daily_email_flow - Email already sent today. Skipping.")
        return
    app = create_app()
    with app.app_context():
        try:
            update_company_counts_and_send_email(app)
            save_status(True)
            logging.info("daily_email_flow - Email sent successfully, status saved in DB.")
        except Exception as e:
            logging.error(f"daily_email_flow - Error: {e}")

def reset_dismissed_alerts():
    """
    איפוס ההתראות הדחויות לכל המשתמשים פעם ביום.
    """
    try:
        db.session.execute("UPDATE users SET dismissed_expiring_alert_at = NULL")
        db.session.commit()
        logging.info("reset_dismissed_alerts - All dismissed alerts reset successfully.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"reset_dismissed_alerts - Error: {e}")

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
            name='Reset daily status at midnight',
            replace_existing=True
        )

        # --- תהליך B: שליחת התראות על קופונים שפג תוקפם (expiration warnings) ---
        scheduler.add_job(
            func=send_expiration_warnings,
            trigger=CronTrigger(hour=8, minute=0),
            id='expiration_warnings',
            name='Send expiration warnings at 8:00',
            replace_existing=True
        )

        # --- תהליך C: שליחת המייל היומי (daily email) ---
        scheduler.add_job(
            func=daily_email_flow,
            trigger=CronTrigger(hour=8, minute=0),
            id='daily_email',
            name='Send daily email at 8:00',
            replace_existing=True
        )

        # --- תהליך D: איפוס התראות דחויות (dismissed alerts reset) ---
        scheduler.add_job(
            func=reset_dismissed_alerts,
            trigger=CronTrigger(hour=0, minute=0),
            id='dismissed_reset',
            name='Reset dismissed alerts at midnight',
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
            if now.hour >= 8 and not load_process_status('expiration'):
                logging.info("Process 'expiration' not executed today and time is after 8:00. Executing expiration warnings now...")
                send_expiration_warnings()
                save_process_status('expiration', True)
            else:
                logging.info("Process 'expiration' already executed today or time is before 8:00.")

            # תהליך C: שליחת המייל היומי (daily email)
            if now.hour >= 8 and not load_process_status('daily_email'):
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
