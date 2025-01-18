# scheduler_config.py

import os
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import url_for, render_template
from dotenv import load_dotenv

from extantions import db
from models import Coupon
from send_mail import send_email

# טוען משתני סביבה (אם צריך)
load_dotenv()
SENDER_NAME = "Coupon Master"

scheduler = BackgroundScheduler()

# --- משתנה גלובלי לסימון אם כבר שלחנו את המייל היומי ---
WAS_SENT_TODAY = False

def reset_was_sent_today():
    """
    איפוס יומי של הדגל שסימן שכבר שלחנו את המייל.
    רץ כל חצות (00:00).
    """
    global WAS_SENT_TODAY
    WAS_SENT_TODAY = False
    logging.info("reset_was_sent_today - set WAS_SENT_TODAY = False")

def send_expiration_warnings():
    """פונקציה לדוגמה לבדיקת קופונים ולשליחת התראות לפני תפוגה (לא חובה)."""
    app = create_app()  # בהתאם למבנה שלך
    with app.app_context():
        today = datetime.utcnow().date()
        one_month_ahead = today + timedelta(days=30)
        # דוגמה קצרה לחודש מראש; אפשר להרחיב גם לשבוע/יום

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

def daily_email_flow():
    """
    פונקציה שתבדוק אם כבר שלחנו היום את המייל.
    אם לא - נשלח את המייל ונגדיר שנשלח.
    """
    global WAS_SENT_TODAY
    if WAS_SENT_TODAY:
        logging.info("daily_email_flow - email already sent today, skipping.")
        return

    # כי אנחנו צריכים app.context
    from app import create_app
    from app.scheduler_utils import update_company_counts_and_send_email

    app = create_app()
    # שליחת המייל בפועל
    update_company_counts_and_send_email(app)

    # סימון שנשלח המייל להיום
    WAS_SENT_TODAY = True
    logging.info("daily_email_flow - sent email and set WAS_SENT_TODAY = True")

def configure_scheduler():
    """מגדיר את עבודות ה-scheduler כך שיוכלו לפעול באפליקציה."""
    # איפוס הדגל כל חצות
    scheduler.add_job(
        func=reset_was_sent_today,
        trigger=CronTrigger(hour=0, minute=0),
        id='reset_was_sent_today',
        name='Reset the daily email flag at midnight',
        replace_existing=True
    )

    # שליחת התראות על קופונים שפג תוקף (אם תרצה)
    scheduler.add_job(
        func=send_expiration_warnings,
        trigger=CronTrigger(hour=8, minute=0),
        id='send_expiration_warnings',
        name='Send expiration warnings daily at 8:00',
        replace_existing=True
    )

    # בדיקת ה-flow של המייל היומי ב-10 בבוקר
    # ואז כל שעתיים (12,14,16,18,20,22) עד סוף היום
    # אם כבר נשלח - לא שולח שוב
    scheduler.add_job(
        func=daily_email_flow,
        trigger=CronTrigger(hour='10,12,14,16,18,20,22', minute=0),
        id='daily_email_flow',
        name='Check if daily email was sent; if not, send. Runs every 2 hours from 10 to 22.',
        replace_existing=True
    )

    scheduler.start()
    logging.info("Scheduler configured and started.")
