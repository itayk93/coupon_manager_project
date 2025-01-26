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


def send_expiration_warnings():
    from app import create_app  # ✅ מייבא רק בתוך הפונקציה
    """
    פונקציה ששולחת התראות על קופונים שעתידים לפוג.
    """
    app = create_app()
    with app.app_context():
        try:
            today = db.func.current_date()
            one_month_ahead = today + db.text("INTERVAL '30 days'")

            coupons_to_warn = Coupon.query.filter(
                Coupon.expiration == one_month_ahead,
                Coupon.reminder_sent_30_days == False
            ).all()

            for coupon in coupons_to_warn:
                user = coupon.user
                if user:
                    try:
                        html_content = f"""
                        <html>
                        <body>
                            <p>שלום {user.first_name},</p>
                            <p>תוקף הקופון שלך <strong>{coupon.code}</strong> עומד לפוג בעוד 30 יום.</p>
                        </body>
                        </html>
                        """
                        send_email(
                            sender_email="CouponMasterIL2@gmail.com",
                            sender_name="Coupon Master",
                            recipient_email=user.email,
                            recipient_name=f"{user.first_name} {user.last_name}",
                            subject="התראה על תפוגת קופון - 30 יום נותרו",
                            html_content=html_content
                        )
                        coupon.reminder_sent_30_days = True
                        db.session.commit()
                        logging.info(f"Sent expiration warning to {user.email} for coupon {coupon.code}")
                    except Exception as e:
                        logging.error(f"Failed to send expiration warning for coupon {coupon.code}: {e}")
                        db.session.rollback()

        except Exception as e:
            logging.error(f"Error in send_expiration_warnings: {e}")


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
