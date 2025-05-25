import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.extensions import db
from app.models import Coupon, Company   # <-- Added Company
from app.helpers import send_email
from flask import current_app

# Global variable to mark if we've already sent the daily email (for old functions - not in use when using the status table)
WAS_SENT_TODAY = False

# Create a Scheduler instance
scheduler = BackgroundScheduler()

def reset_was_sent_today():
    """
    Daily reset of the flag that marks if we've already sent the email.
    Runs at midnight (00:00).
    """
    global WAS_SENT_TODAY
    WAS_SENT_TODAY = False
    logging.info("reset_was_sent_today - Resetting WAS_SENT_TODAY to False")

from datetime import date, timedelta

def categorize_coupons(coupons):
    """
    Divides coupons into three categories: today, tomorrow, and rest of the month.
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

# --- Functions for sending notifications and updating data (code as shown, without major changes) ---

from flask import render_template
from sqlalchemy.sql import text

def send_expiration_warnings():
    """
    Sends notifications to users about coupons that are about to expire at different time points.
    """
    # Local import of create_app to prevent circular dependency
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

            # Assume we have the Company model with image_path
            company_obj = Company.query.filter_by(name=coupon.company).first()
            logo_filename = company_obj.image_path if company_obj and company_obj.image_path else "default_logo.png"
            # Assume images are in the static/logos directory
            logo_filepath = os.path.join(current_app.root_path, "static", "logos", "images", logo_filename)

            # Try to read the file and convert to Base64
            try:
                with open(logo_filepath, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            except Exception as e:
                # In case of error, use an empty string or some default logo
                logging.error(f"Error reading logo file {logo_filepath}: {e}")
                encoded_string = ""

            users[user_id]['coupons'].append({
                'coupon_id': coupon.coupon_id,
                'company': coupon.company,
                # Pass the Base64 string
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
    Function that sends the daily email only if it hasn't been sent today yet.
    """
    from app import create_app
    from scheduler_utils import update_company_counts_and_send_email
    from app.extensions import db
    from scheduler_utils import load_status, save_status  # Verify import is correct

    app = create_app()
    with app.app_context():  # Wrap all calls in Flask context
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
    Resets dismissed alerts for all users once a day.
    """
    try:
        db.session.execute(text("UPDATE users SET dismissed_expiring_alert_at = NULL"))
        db.session.commit()
        logging.info("reset_dismissed_alerts - All dismissed alerts reset successfully.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"reset_dismissed_alerts - Error resetting dismissed alerts: {e}")

# --- Functions for working with the status table (Supabase) ---
# Assume the load_process_status and save_process_status functions are defined in scheduler_utils.py, as shown in the previous message.
# If you're not already importing them, make sure they exist in this file.

from sqlalchemy.sql import text


def load_process_status(process):
    """
    Loads the status of a specific process (e.g., 'reset', 'expiration', 'daily_email', 'dismissed_reset')
    for the current date.
    """
    today = datetime.date.today()
    query = text("SELECT was_sent FROM daily_email_status WHERE date = :today AND process = :process")
    result = db.session.execute(query, {"today": today, "process": process}).fetchone()
    return result[0] if result else False

def save_process_status(process, was_sent):
    """
    Saves the status of a specific process for the current date.
    Uses UPSERT.
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

# --- Scheduler Configuration Function ---
def configure_scheduler():
    """
    Configures the Scheduler jobs so that each process (reset, notifications, daily email, dismissed alerts reset)
    is scheduled to run at fixed times (00:00 or 8:00), and if the system was down and the action wasn't performed,
    it will be executed the first time the system starts up on that day.
    """
    # Import create_app only inside the function to break the circle
    from app import create_app

    global scheduler
    if not scheduler.running:
        logging.info("Starting scheduler and adding jobs...")

        # --- Process A: Status Reset (reset) ---
        scheduler.add_job(
            func=lambda: save_process_status('reset', False),
            trigger=CronTrigger(hour=0, minute=0),
            id='reset_status',
            name='Reset daily status at 2:00',
            replace_existing=True
        )

        # --- Process B: Sending notifications about expired coupons (expiration warnings) ---
        scheduler.add_job(
            func=send_expiration_warnings,
            trigger=CronTrigger(hour=6, minute=0),
            id='expiration_warnings',
            name='Send expiration warnings at 8:00',
            replace_existing=True
        )

        # --- Process C: Sending daily email (daily email) ---
        scheduler.add_job(
            func=daily_email_flow,
            trigger=CronTrigger(hour=6, minute=0),
            id='daily_email',
            name='Send daily email at 8:00',
            replace_existing=True
        )

        # --- Process D: Resetting dismissed alerts (dismissed alerts reset) ---
        scheduler.add_job(
            func=reset_dismissed_alerts,
            trigger=CronTrigger(hour=0, minute=0),
            id='dismissed_reset',
            name='Reset dismissed alerts at 2:00',
            replace_existing=True
        )

        scheduler.start()
        logging.info("Scheduler started successfully with jobs: %s", scheduler.get_jobs())

        # Now check for each process – if not executed today, execute it immediately on the first startup of the system on that day
        app = create_app()
        with app.app_context():
            now = datetime.datetime.now()
            logging.info("Current time: %s:%s", now.hour, now.minute)

            # Process A: Status Reset (reset)
            if not load_process_status('reset'):
                logging.info("Process 'reset' not executed today. Executing reset process now...")
                save_process_status('reset', False)
            else:
                logging.info("Process 'reset' already executed today.")

            # Process B: Sending notifications (expiration warnings)
            if now.hour >= 6 and not load_process_status('expiration'):
                logging.info("Process 'expiration' not executed today and time is after 8:00. Executing expiration warnings now...")
                send_expiration_warnings()
                save_process_status('expiration', True)
            else:
                logging.info("Process 'expiration' already executed today or time is before 8:00.")

            # Process C: Sending daily email (daily email)
            if now.hour >= 6 and not load_process_status('daily_email'):
                logging.info("Process 'daily_email' not executed today and time is after 8:00. Executing daily email now...")
                daily_email_flow()
                save_process_status('daily_email', True)
            else:
                logging.info("Process 'daily_email' already executed today or time is before 8:00.")

            # Process D: Resetting dismissed alerts (dismissed alerts reset)
            if not load_process_status('dismissed_reset'):
                logging.info("Process 'dismissed_reset' not executed today. Executing dismissed alerts reset now...")
                reset_dismissed_alerts()
                save_process_status('dismissed_reset', True)
            else:
                logging.info("Process 'dismissed_reset' already executed today.")
    else:
        logging.info("Scheduler is already running, skipping re-initialization.")
