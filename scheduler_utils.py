# app/scheduler_utils.py
import logging
from flask import render_template
from sqlalchemy.sql import text

from app.extensions import db
from app.models import Company, Coupon
from app.helpers import send_email  # ודא שיש לך פונקציית send_email
                                    # ב-app.helpers או בקובץ אחר מתאים
from sqlalchemy import text
from app.extensions import db


def update_company_counts_and_send_email_old(app):
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
                sender_email="noreply@couponmasteril.com‏",
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

def update_company_counts_and_send_email(app):
    """
    מעדכנת את ספירת הקופונים לכל חברה ושולחת במייל דוח שמציג
    עבור כל חברה:
      - שם החברה
      - מספר הקופונים (company_count)
      - מחיר ממוצע לקופון (ממוצע עמודת cost)
      - אחוז הנחה ממוצע (ממוצע עמודת discount_percentage, כאשר ערך NULL מתורגם ל-0)
      - התאריך של הקופון האחרון שהוזן (הערך המקסימלי של date_added)
    """
    with app.app_context():
        try:
            # 1. עדכון העמודה company_count בטבלת companies
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

            # 2. שליפת סטטיסטיקות מהטבלת coupon עם המרות מתאימות
            stats_query = text("""
                SELECT
                    company,
                    COUNT(*) AS coupon_count,
                    ROUND(AVG(cost)::numeric, 2) AS avg_cost,
                    ROUND(AVG(value)::numeric, 2) AS avg_coupon_value,
                    ROUND(AVG(((value - cost) / NULLIF(value, 0)) * 100)::numeric, 2) AS avg_discount,
                    MAX(date_added) AS last_added
                FROM coupon
                GROUP BY company
                ORDER BY coupon_count DESC;  -- מיון לפי סה"כ קופונים
            """)
            # שימוש ב-.mappings() כדי לקבל תוצאה כמילונים (dict)
            coupon_stats = db.session.execute(stats_query).mappings().all()

            # 3. בניית תוכן HTML משופר עם CSS פנימי
            html_content = f"""
            <html>
              <head>
                <meta charset="utf-8">
                <style>
                  body {{
                    font-family: Arial, sans-serif;
                    background-color: #f4f4f4;
                    margin: 0;
                    padding: 20px;
                    direction: rtl;  /* הוספת RTL */
                  }}
                  .container {{
                    background-color: #fff;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 0 10px rgba(0,0,0,0.1);
                    max-width: 800px;
                    margin: auto;
                  }}
                  h2 {{
                    color: #333;
                    text-align: center;
                  }}
                  table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 20px;
                  }}
                  th, td {{
                    padding: 12px;
                    border: 1px solid #ddd;
                    text-align: center;
                  }}
                  th {{
                    background-color: #007BFF;
                    color: #fff;
                  }}
                  tr:nth-child(even) {{
                    background-color: #f9f9f9;
                  }}
                  .footer {{
                    margin-top: 20px;
                    text-align: center;
                    font-size: 0.9em;
                    color: #777;
                  }}
                </style>
              </head>
              <body>
                <div class="container">
                  <h2>דוח עדכון יומי: נתוני קופונים לחברות</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>שם חברה</th>
                        <th>סה"כ קופונים בדאטהבייס</th>
                        <th>מחיר קניית קופון ממוצע (₪)</th>
                        <th>שווי ממוצע של קופון (₪)</th>
                        <th>אחוז הנחה ממוצע (%)</th>
                        <th>קופון אחרון</th>
                      </tr>
                    </thead>
                    <tbody>
            """
            for row in coupon_stats:
                company = row['company']
                coupon_count = row['coupon_count']
                avg_cost = row['avg_cost'] if row['avg_cost'] is not None else "N/A"
                avg_coupon_value = row['avg_coupon_value'] if row['avg_coupon_value'] is not None else "N/A"
                avg_discount = row['avg_discount'] if row['avg_discount'] is not None else "N/A"
                last_added = row['last_added'].strftime("%Y-%m-%d %H:%M:%S") if row['last_added'] else "N/A"
                html_content += f"""
                      <tr>
                        <td>{company}</td>
                        <td>{coupon_count}</td>
                        <td>{avg_cost}</td>
                        <td>{avg_coupon_value}</td>
                        <td>{avg_discount}</td>
                        <td>{last_added}</td>
                      </tr>
                """
            html_content += f"""
                    </tbody>
                  </table>
                  <div class="footer">
                    <p>דוח זה נוצר אוטומטית בתאריך: {datetime.date.today().strftime("%Y-%m-%d")}</p>
                  </div>
                </div>
              </body>
            </html>
            """

            # 4. שליחת המייל
            recipient_email = "itayk93@gmail.com"
            subject = "דוח יומי: נתוני קופונים לחברות"
            send_email(
                sender_email="noreply@couponmasteril.com‏",
                sender_name="Coupon Master",
                recipient_email=recipient_email,
                recipient_name="Itay",
                subject=subject,
                html_content=html_content,
            )

            logging.info("Daily company update and coupon statistics email sent successfully.")

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in update_company_counts_and_send_email: {e}")

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

from app import create_app

def load_status():
    """
    טוען מהטבלה אם המייל נשלח עבור התאריך הנוכחי.
    מחזיר True אם נשלח, אחרת False.
    """
    app = create_app()  # יצירת מופע של האפליקציה
    with app.app_context():  # שימוש ב-context כדי למנוע שגיאות
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
        INSERT INTO daily_email_status (date, process, was_sent)
        VALUES (:today, 'default', :was_sent)
        ON CONFLICT (date, process) DO UPDATE SET was_sent = EXCLUDED.was_sent;
    """)
    try:
        db.session.execute(query, {"today": today, "was_sent": was_sent})
        db.session.commit()
        logging.info("Updated email status for %s: %s", today, was_sent)
    except Exception as e:
        db.session.rollback()
        logging.error("Error updating email status: %s", e)

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

def save_process_status_old(process, was_sent):
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


def save_process_status(process, was_sent):
    """
    שומר את סטטוס ביצוע התהליך (process) עבור התאריך הנוכחי.
    במקום להשתמש ב-ON CONFLICT, נבדוק קודם אם קיימת רשומה עבור (date, process)
    """
    today = datetime.date.today()
    # בדיקה האם קיימת רשומה עבור תאריך ותהליך נתון
    existing = db.session.execute(
        text("SELECT * FROM daily_email_status WHERE date = :today AND process = :process"),
        {"today": today, "process": process}
    ).fetchone()

    if existing:
        update_query = text("UPDATE daily_email_status SET was_sent = :was_sent WHERE date = :today AND process = :process")
        db.session.execute(update_query, {"today": today, "process": process, "was_sent": was_sent})
    else:
        insert_query = text("INSERT INTO daily_email_status (date, process, was_sent) VALUES (:today, :process, :was_sent)")
        db.session.execute(insert_query, {"today": today, "process": process, "was_sent": was_sent})
    try:
        db.session.commit()
        logging.info("Updated status for process '%s' for date %s: %s", process, today, was_sent)
    except Exception as e:
        db.session.rollback()
        logging.error("Error updating status for process '%s': %s", process, e)
