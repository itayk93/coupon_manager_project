# app/scheduler_utils.py
import logging
from flask import render_template
from sqlalchemy.sql import text

from app.extensions import db
from app.models import Company
from app.helpers import send_email  # ודא שיש לך פונקציית send_email
                                    # ב-app.helpers או בקובץ אחר מתאים

def update_company_counts_and_send_email(app):
    """
    מעדכנת את ספירת הקופונים לכל חברה ולאחר מכן שולחת
    את תוצאות הטבלה במייל אל itayk93@gmail.com.
    """
    with app.app_context():
        try:
            # 1. עדכון העמודה company_count
            update_query = text("""
                UPDATE companies c
                SET company_count = COALESCE(subquery.company_count, 0)
                FROM (
                    SELECT c.id, COUNT(cp.company) AS company_count
                    FROM companies c
                    LEFT JOIN coupon cp ON c.name = cp.company
                    GROUP BY c.id
                ) AS subquery
                WHERE c.id = subquery.id;
            """)
            db.session.execute(update_query)
            db.session.commit()

            # 2. שליפת הנתונים המעודכנים
            updated_companies = Company.query.order_by(Company.company_count.desc()).all()

            # 3. בניית תוכן (HTML) להצגה במייל
            html_rows = []
            for comp in updated_companies:
                html_rows.append(
                    f"<tr><td>{comp.id}</td><td>{comp.name}</td><td>{comp.company_count}</td></tr>"
                )

            html_table = f"""
            <html>
            <head><meta charset="utf-8"></head>
            <body>
                <h2>תוצאות עדכניות של ספירת קופונים לחברות:</h2>
                <table border="1" cellpadding="4" cellspacing="0">
                    <thead>
                        <tr><th>ID</th><th>שם חברה</th><th>ספירה</th></tr>
                    </thead>
                    <tbody>
                        {''.join(html_rows)}
                    </tbody>
                </table>
            </body>
            </html>
            """

            # 4. שליחת מייל
            recipient_email = "itayk93@gmail.com"
            subject = "עדכון יומי: company_count"
            send_email(
                sender_email="CouponMasterIL2@gmail.com",
                sender_name="Coupon Master",
                recipient_email=recipient_email,
                recipient_name="Itay",
                subject=subject,
                html_content=html_table,
            )

            logging.info("Daily company_count update succeeded and email was sent.")

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in update_company_counts_and_send_email: {e}")

from sqlalchemy import text
from app.extensions import db


def get_coupons_expiring_in_30_days():
    query = text("""SELECT * 
FROM coupon 
WHERE expiration IS NOT NULL
AND TO_DATE(expiration, 'YYYY-MM-DD') 
    BETWEEN CURRENT_DATE AND (CURRENT_DATE + INTERVAL '30 days')
AND reminder_sent_30_days = FALSE
AND status = 'פעיל'   -- רק קופונים פעילים
AND is_for_sale = FALSE;  -- לא למכירה
""")
    result = db.session.execute(query)
    return result.fetchall()  # או עיבוד אחר


import datetime
import logging
from sqlalchemy.sql import text
from app.extensions import db


def load_status():
    """
    טוען מהטבלה אם המייל נשלח עבור התאריך הנוכחי.
    מחזיר True אם נשלח, אחרת False.
    """
    today = datetime.date.today()
    query = text("SELECT was_sent FROM daily_email_status WHERE date = :today")
    result = db.session.execute(query, {"today": today}).fetchone()

    return result[0] if result else False  # אם אין רשומה להיום, נחזיר False


def save_status(was_sent):
    """
    שומר בטבלה את מצב השליחה עבור התאריך הנוכחי.
    משתמש ב-UPSERT (INSERT ... ON CONFLICT) כך שהרשומה תתעדכן אם היא קיימת.
    """
    today = datetime.date.today()
    query = text("""
        INSERT INTO daily_email_status (date, was_sent)
        VALUES (:today, :was_sent)
        ON CONFLICT (date) DO UPDATE SET was_sent = EXCLUDED.was_sent;
    """)
    try:
        db.session.execute(query, {"today": today, "was_sent": was_sent})
        db.session.commit()
        logging.info(f"Updated email status for {today}: {was_sent}")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating email status: {e}")

import datetime
from sqlalchemy.sql import text
from app.extensions import db
import logging

def load_process_status(process):
    """
    טוען מהטבלה את הסטטוס של תהליך מסוים עבור התאריך הנוכחי.
    מחזיר True אם תהליך זה כבר בוצע היום, אחרת False.
    """
    today = datetime.date.today()
    query = text("SELECT was_sent FROM daily_email_status WHERE date = :today AND process = :process")
    result = db.session.execute(query, {"today": today, "process": process}).fetchone()
    return result[0] if result else False

def save_process_status(process, was_sent):
    """
    שומר בטבלה את סטטוס ביצוע התהליך (process) עבור התאריך הנוכחי.
    משתמש ב-UPsert (INSERT ... ON CONFLICT) כדי לעדכן או להוסיף את הרשומה.
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
