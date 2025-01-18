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
                sender_name="MaCoupon",
                recipient_email=recipient_email,
                recipient_name="Itay",
                subject=subject,
                html_content=html_table,
            )

            logging.info("Daily company_count update succeeded and email was sent.")

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in update_company_counts_and_send_email: {e}")
