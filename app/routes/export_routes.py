# export_routes.py

from flask import Blueprint, send_file
from flask_login import login_required, current_user
from app.models import Coupon
from app.extensions import db
import pandas as pd
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

export_bp = Blueprint('export', __name__)

@export_bp.route('/export_excel')
@login_required
def export_excel():
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

    return send_file(
        output,
        download_name='coupons.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@export_bp.route('/export_pdf')
@login_required
def export_pdf():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Register a font that supports Hebrew
    pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))

    coupons = Coupon.query.filter_by(user_id=current_user.id).all()
    output = BytesIO()
    p = canvas.Canvas(output, pagesize=letter)
    p.setFont('DejaVuSans', 12)

    y = 750
    for coupon in coupons:
        text = f"קוד קופון: {coupon.code}, חברה: {coupon.company}, ערך נותר: {coupon.remaining_value} ש\"ח"
        p.drawRightString(550, y, text)  # Adjust position for RTL
        y -= 20
        if y < 50:
            p.showPage()
            p.setFont('DejaVuSans', 12)
            y = 750

    p.save()
    output.seek(0)
    return send_file(
        output,
        download_name='coupons.pdf',
        as_attachment=True,
        mimetype='application/pdf'
    )
