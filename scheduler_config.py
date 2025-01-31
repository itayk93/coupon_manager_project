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

def send_expiration_warnings_work():
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
                sender_email="CouponMasterIL2@gmail.com",
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

def send_expiration_warnings():
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
                sender_email="CouponMasterIL2@gmail.com",
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

def daily_email_flow():
    """
    פונקציה שתשלח את המייל היומי רק אם עוד לא נשלח היום.
    """
    global WAS_SENT_TODAY
    if WAS_SENT_TODAY:
        logging.info("daily_email_flow - Email already sent today. Skipping.")
        return

    from app import create_app  # ✅ מייבא רק בתוך הפונקציה
    app = create_app()
    with app.app_context():
        try:
            from app.scheduler_utils import update_company_counts_and_send_email
            update_company_counts_and_send_email(app)
            WAS_SENT_TODAY = True
            logging.info("daily_email_flow - Email sent successfully, marked WAS_SENT_TODAY = True")
        except Exception as e:
            logging.error(f"Error in daily_email_flow: {e}")


def configure_scheduler():
    """
    מגדיר את עבודות ה-scheduler כך שיוכלו לפעול באפליקציה.
    מונע כפילויות על ידי בדיקה אם ה-scheduler כבר פועל.
    """
    global scheduler

    if not scheduler.running:  # מונע הפעלה כפולה
        logging.info("Starting scheduler and adding jobs...")

        # איפוס הדגל כל חצות
        scheduler.add_job(
            func=reset_was_sent_today,
            trigger=CronTrigger(hour=0, minute=0),
            id='reset_was_sent_today',
            name='Reset the daily email flag at midnight',
            replace_existing=True
        )

        # שליחת התראות על קופונים שפג תוקפם
        scheduler.add_job(
            func=send_expiration_warnings,
            trigger=CronTrigger(hour=8, minute=0),
            id='send_expiration_warnings',
            name='Send expiration warnings daily at 8:00',
            replace_existing=True
        )

        # בדיקת ושליחת המייל היומי כל שעתיים מ-10:00 עד 22:00
        scheduler.add_job(
            func=daily_email_flow,
            trigger=CronTrigger(hour='10,12,14,16,18,20,22', minute=0),
            id='daily_email_flow',
            name='Check if daily email was sent; if not, send. Runs every 2 hours from 10 to 22.',
            replace_existing=True
        )

        scheduler.start()
        logging.info(f"Scheduler started successfully with jobs: {scheduler.get_jobs()}")

    else:
        logging.info("Scheduler is already running, skipping re-initialization.")
