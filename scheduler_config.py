# scheduler_config.py

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
from flask import current_app
from app import create_app
from extantions import  db
from models import Coupon
from send_mail import send_email
import logging

# יצירת מופע של ה-scheduler
scheduler = BackgroundScheduler()

load_dotenv()
SENDER_NAME=MaCoupon

def send_expiration_warnings():
    """פונקציה לבדיקת קופונים ולשליחת התראות לפני תפוגה."""
    app = create_app()  # שימוש ב-create_app כדי להבטיח context גם במצב מתוזמן
    with app.app_context():
        today = datetime.utcnow().date()
        one_month_ahead = today + timedelta(days=30)
        one_week_ahead = today + timedelta(days=7)
        one_day_ahead = today + timedelta(days=1)

        # בדיקה לשליחה חודש מראש
        coupons_month = Coupon.query.filter(
            Coupon.expiration == one_month_ahead.strftime('%Y-%m-%d'),
            Coupon.reminder_sent_30_days == False
        ).all()

        for coupon in coupons_month:
            user = coupon.user
            if user:
                try:
                    expiration_date = coupon.expiration
                    coupon_detail_link = url_for('coupon_detail', id=coupon.id, _external=True)
                    html_content = render_template(
                        'emails/coupon_expiration_warning.html',
                        user=user,
                        coupon=coupon,
                        expiration_date=expiration_date,
                        coupon_detail_link=coupon_detail_link,
                        days_left=30
                    )
                    send_email(
                        sender_email=os.getenv('SENDER_EMAIL'),
                        sender_name=SENDER_NAME,
                        recipient_email=user.email,
                        recipient_name=f'{user.first_name} {user.last_name}',
                        subject='התראה על תפוגת תוקף קופון - חודש אחד נותר',
                        html_content=html_content
                    )
                    coupon.reminder_sent_30_days = True
                    db.session.commit()

                except Exception as e:
                    logging.error(f"Error sending 30-day expiration warning for coupon {coupon.code}: {e}")
                    db.session.rollback()

        # בדיקות דומות לשליחה שבוע ויום מראש
        # ...

def configure_scheduler():
    """הגדרת משימות ה-scheduler כך שיוכלו לפעול באפליקציה."""
    scheduler.add_job(
        func=send_expiration_warnings,
        trigger=CronTrigger(hour=0, minute=0),
        id='send_expiration_warnings',
        name='Send expiration warnings one month, one week, and one day before expiration',
        replace_existing=True
    )
    scheduler.start()
    logging.info("Scheduler configured and started.")
