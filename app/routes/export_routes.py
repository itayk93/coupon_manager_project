from flask import Blueprint, send_file, request, current_app, flash
from flask_login import login_required, current_user
from datetime import datetime
import logging
import pandas as pd
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.models import Coupon
from app.extensions import db
from app.helpers import get_geo_location  # או הגדר כאן את הפונקציה

export_bp = Blueprint('export', __name__)
logger = logging.getLogger(__name__)

def log_user_activity(action):
    try:
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent', '')
        geo_location = get_geo_location(ip_address) if ip_address else None

        activity = {
            "user_id": current_user.id if current_user.is_authenticated else None,
            "coupon_id": None,
            "timestamp": datetime.utcnow(),
            "action": action,
            "device": user_agent[:50] if user_agent else None,
            "browser": user_agent.split(' ')[0][:50] if user_agent else None,
            "ip_address": ip_address[:45] if ip_address else None,
            "geo_location": geo_location[:100] if geo_location else None
        }

        db.session.execute(
            db.text("""
                INSERT INTO user_activities
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                VALUES
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
            """),
            activity
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging activity [{action}]: {e}")

@export_bp.route('/export_excel')
@login_required
def export_excel():
    #log_user_activity("export_excel_view")

    coupons = Coupon.query.filter_by(user_id=current_user.id).all()
    data = []
    for coupon in coupons:
        data.append({
            'קוד קופון': coupon.code,
            'חברה': coupon.company,
            'ערך מקורי': coupon.value,
            'עלות': coupon.cost,
            'ערך שהשתמשת בו': coupon.used_value,
            'ערך נותר': coupon.remaining_value,
            'סטטוס': coupon.status,
            'תאריך תפוגה': coupon.expiration or '',
            'תאריך הוספה': coupon.date_added.strftime('%Y-%m-%d %H:%M'),
            'תיאור': coupon.description or ''
        })

    df = pd.DataFrame(data)
    output = BytesIO()

    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='קופונים')

    output.seek(0)

    flash('קובץ אקסל נוצר בהצלחה.', 'success')
    #log_user_activity("export_excel_downloaded")

    return send_file(
        output,
        download_name='coupons.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@export_bp.route('/export_pdf')
@login_required
def export_pdf():
    #log_user_activity("export_pdf_view")

    pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))

    coupons = Coupon.query.filter_by(user_id=current_user.id).all()
    output = BytesIO()
    p = canvas.Canvas(output, pagesize=letter)
    p.setFont('DejaVuSans', 12)

    y = 750
    for coupon in coupons:
        text = f"קוד קופון: {coupon.code}, חברה: {coupon.company}, ערך נותר: {coupon.remaining_value} ש\"ח"
        p.drawRightString(550, y, text)
        y -= 20
        if y < 50:
            p.showPage()
            p.setFont('DejaVuSans', 12)
            y = 750

    p.save()
    output.seek(0)

    flash('קובץ PDF נוצר בהצלחה.', 'success')
    #log_user_activity("export_pdf_downloaded")

    return send_file(
        output,
        download_name='coupons.pdf',
        as_attachment=True,
        mimetype='application/pdf'
    )
