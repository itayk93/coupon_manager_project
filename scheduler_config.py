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
from datetime import date, datetime, timedelta
from app.helpers import send_email


def send_expiration_warnings():
    """
    שליחת התראות למשתמשים על קופונים שעומדים לפוג לפי נקודות זמן שונות (30 יום, 7 ימים, יום לפני, וביום עצמו).
    """

    from app import create_app
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
                sender_email="CouponMasterIL2@gmail.com",
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
from app.scheduler_utils import load_status, save_status

def daily_email_flow():
    """
    פונקציה שתשלח את המייל היומי רק אם עוד לא נשלח היום.
    """
    if load_status():  # ✅ במקום WAS_SENT_TODAY
        logging.info("daily_email_flow - Email already sent today. Skipping.")
        return

    from app import create_app  # ✅ מייבא רק בתוך הפונקציה
    app = create_app()
    with app.app_context():
        try:
            from app.scheduler_utils import update_company_counts_and_send_email
            update_company_counts_and_send_email(app)
            save_status(True)  # ✅ מעדכן את מסד הנתונים שהמייל נשלח
            logging.info("daily_email_flow - Email sent successfully, status saved in DB.")
        except Exception as e:
            logging.error(f"❌ Error in daily_email_flow: {e}")

import logging
import datetime
from apscheduler.triggers.cron import CronTrigger
from scheduler_utils import load_status, save_status  # ✅ מייבאים את הפונקציות מה- utils

def configure_scheduler():
    """
    מגדיר את עבודות ה-scheduler כך שיוכלו לפעול באפליקציה,
    תוך בדיקה האם יש להריץ את daily_email_flow מיד אם השעה כבר אחרי 8
    והמייל היומי עדיין לא נשלח.
    """
    global scheduler

    if not scheduler.running:  # מונע הפעלה כפולה
        logging.info("Starting scheduler and adding jobs...")

        # איפוס הדגל כל חצות (עדכון במסד הנתונים)
        scheduler.add_job(
            func=lambda: save_status(False),
            trigger=CronTrigger(hour=0, minute=0),
            id='reset_was_sent_today',
            name='Reset the daily email flag at midnight',
            replace_existing=True
        )

        # שליחת התראות על קופונים שפג תוקפם (30, 7, 1 ימים לפני וביום התפוגה)
        scheduler.add_job(send_expiration_warnings, trigger=CronTrigger(hour=8, minute=0), id='exp_30_days')
        scheduler.add_job(send_expiration_warnings, trigger=CronTrigger(hour=8, minute=0), id='exp_7_days')
        scheduler.add_job(send_expiration_warnings, trigger=CronTrigger(hour=8, minute=0), id='exp_1_day')
        scheduler.add_job(send_expiration_warnings, trigger=CronTrigger(hour=8, minute=0), id='exp_today')

        # בדיקת ושליחת המייל היומי כל שעתיים מ-10:00 עד 22:00
        scheduler.add_job(
            func=daily_email_flow,
            trigger=CronTrigger(hour='10,12,14,16,18,20,22', minute=0),
            id='daily_email_flow',
            name='Check if daily email was sent; if not, send. Runs every 2 hours from 10 to 22.',
            replace_existing=True
        )

        # איפוס ההתראות הדחויות בחצות
        scheduler.add_job(
            func=reset_dismissed_alerts,
            trigger=CronTrigger(hour=0, minute=0),
            id='reset_dismissed_alerts',
            name='Reset dismissed expiring alerts daily at midnight',
            replace_existing=True
        )

        scheduler.start()
        logging.info(f"Scheduler started successfully with jobs: {scheduler.get_jobs()}")

        # בדיקה: אם השעה היא אחרי 8 והמייל היומי עדיין לא נשלח, להפעיל את daily_email_flow מיד.
        now = datetime.datetime.now()
        status = load_status()  # קבלת הסטטוס ממסד הנתונים

        logging.info(f"🛠️  [DEBUG] Time now: {now.hour}:{now.minute} - Email sent status: {status}")

        # בדיקה אם השעה היא בדיוק 8:00 והמייל עדיין לא נשלח
        if now.hour == 8 and now.minute == 0 and not status:
            logging.info("🚀 השעה בדיוק 8:00 והמייל לא נשלח עדיין - מפעיל עכשיו את daily_email_flow!")
            daily_email_flow()
            save_status(True)  # מעדכן שהמייל נשלח
        else:
            logging.info("✅ המייל כבר נשלח היום או שהשעה לא בדיוק 8:00.")

from app.extensions import db
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

def reset_dismissed_alerts():
    """
    איפוס העמודה dismissed_expiring_alert_at לכל המשתמשים פעם ביום.
    כך שההתראה תופיע שוב למחרת אם יש קופונים שפג תוקפם.
    """
    try:
        db.session.execute("UPDATE users SET dismissed_expiring_alert_at = NULL")
        db.session.commit()
        logging.info("reset_dismissed_alerts - All dismissed_expiring_alert_at fields reset to NULL.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"reset_dismissed_alerts - Error resetting dismissed alerts: {e}")

