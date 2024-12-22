# uploads_routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from app.models import Coupon, Tag, Company, CouponUsage
from app.forms import UploadCouponsForm, AddCouponsBulkForm
from app.helpers import process_coupons_excel, get_coupon_data
from app.extensions import db
import os
import pandas as pd
import traceback
from datetime import datetime

uploads_bp = Blueprint('uploads', __name__)

@uploads_bp.route('/upload_coupons', methods=['GET', 'POST'])
@login_required
def upload_coupons():
    form = UploadCouponsForm()
    if form.validate_on_submit():
        file = form.file.data
        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        try:
            invalid_coupons, missing_optional_fields_messages = process_coupons_excel(file_path, current_user)

            for msg in missing_optional_fields_messages:
                flash(msg, 'warning')

            if invalid_coupons:
                flash('הקופונים הבאים לא היו תקינים ולא נוספו:<br>' + '<br>'.join(invalid_coupons), 'danger')
            else:
                flash('כל הקופונים נוספו בהצלחה!', 'success')
        except Exception as e:
            flash('אירעה שגיאה בעת עיבוד הקובץ.', 'danger')
            traceback.print_exc()

        return redirect(url_for('transactions.show_coupons'))

    return render_template('upload_coupons.html', form=form)

@uploads_bp.route('/add_coupons_bulk', methods=['GET', 'POST'])
@login_required
def add_coupons_bulk():
    form = AddCouponsBulkForm()
    companies = Company.query.all()
    tags = Tag.query.all()

    # Define choices before form validation
    for coupon_entry in form.coupons.entries:
        coupon_form = coupon_entry.form
        company_choices = [(str(company.id), company.name) for company in companies]
        company_choices.append(('other', 'אחר'))
        coupon_form.company_id.choices = company_choices

        tag_choices = [(str(tag.id), tag.name) for tag in tags]
        tag_choices.append(('other', 'אחר'))
        coupon_form.tag_id.choices = tag_choices

    if form.validate_on_submit():
        try:
            new_coupons_data = []
            for idx, coupon_entry in enumerate(form.coupons.entries):
                coupon_form = coupon_entry.form
                # Handle company_id
                if coupon_form.company_id.data == 'other':
                    company_name = coupon_form.other_company.data.strip()
                    if not company_name:
                        flash(f'שם החברה חסר בקופון #{idx + 1}.', 'danger')
                        continue
                else:
                    company_id = coupon_form.company_id.data
                    try:
                        company = db.session.get(Company, int(company_id))
                        if company:
                            company_name = company.name
                        else:
                            flash(f'חברה עם ID {company_id} לא נמצאה בקופון #{idx + 1}.', 'danger')
                            continue
                    except ValueError:
                        flash(f'ID החברה אינו תקין בקופון #{idx + 1}.', 'danger')
                        continue

                # Handle tag_id
                if coupon_form.tag_id.data == 'other':
                    tag_name = coupon_form.other_tag.data.strip()
                    if not tag_name:
                        flash(f'שם התגית חסר בקופון #{idx + 1}.', 'danger')
                        continue
                else:
                    tag_id = coupon_form.tag_id.data
                    try:
                        tag = db.session.get(Tag, int(tag_id))
                        if tag:
                            tag_name = tag.name
                        else:
                            flash(f'תגית עם ID {tag_id} לא נמצאה בקופון #{idx + 1}.', 'danger')
                            continue
                    except ValueError:
                        flash(f'ID התגית אינו תקין בקופון #{idx + 1}.', 'danger')
                        continue

                # Handle value and cost
                try:
                    value = float(coupon_form.value.data) if coupon_form.value.data else 0.0
                except ValueError:
                    flash(f'ערך הקופון אינו תקין בקופון #{idx + 1}.', 'danger')
                    continue

                try:
                    cost = float(coupon_form.cost.data) if coupon_form.cost.data else 0.0
                except ValueError:
                    flash(f'עלות הקופון אינה תקינה בקופון #{idx + 1}.', 'danger')
                    continue

                # Collect coupon data into a dictionary
                coupon_data = {
                    'קוד קופון': coupon_form.code.data.strip(),
                    'חברה': company_name,
                    'ערך מקורי': value,
                    'עלות': cost,
                    'תאריך תפוגה': coupon_form.expiration.data.strftime('%Y-%m-%d') if coupon_form.expiration.data else '',
                    'קוד לשימוש חד פעמי': coupon_form.is_one_time.data,
                    'מטרת הקופון': coupon_form.purpose.data.strip() if coupon_form.is_one_time.data and coupon_form.purpose.data else '',
                    'תיאור': coupon_form.description.data.strip() if coupon_form.description.data else '',
                    'תגיות': tag_name if tag_name else ''
                }

                new_coupons_data.append(coupon_data)

            # --- Create DataFrame and export to Excel ---
            if new_coupons_data:
                df_new_coupons = pd.DataFrame(new_coupons_data)

                export_folder = 'exports'  # Folder where files will be saved
                os.makedirs(export_folder, exist_ok=True)  # Create folder if it doesn't exist

                export_filename = f"new_coupons_{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                export_path = os.path.join(export_folder, export_filename)

                df_new_coupons.to_excel(export_path, index=False)
                current_app.logger.info(f"Exported new coupons to {export_path}")

                # --- Process the Excel file to add coupons ---
                invalid_coupons, missing_optional_fields_messages = process_coupons_excel(export_path, current_user)

                for msg in missing_optional_fields_messages:
                    flash(msg, 'warning')

                if invalid_coupons:
                    flash('הקופונים הבאים לא היו תקינים ולא נוספו:<br>' + '<br>'.join(invalid_coupons), 'danger')
                else:
                    flash('כל הקופונים נוספו בהצלחה!', 'success')

                current_app.logger.info("All coupons successfully processed and imported.")
                return redirect(url_for('transactions.show_coupons'))
            else:
                current_app.logger.info("No new coupons were added, so no export or import was made.")
                flash('לא נוספו קופונים חדשים.', 'info')
                return redirect(url_for('transactions.show_coupons'))

        except Exception as e:
            current_app.logger.error(f"Error during bulk coupon processing: {e}")
            traceback.print_exc()
            flash('אירעה שגיאה בעת עיבוד הקופונים. אנא נסה שוב.', 'danger')

    else:
        if form.is_submitted():
            current_app.logger.warning(f"Form validation failed: {form.errors}")

    return render_template('add_coupons_bulk.html', form=form, companies=companies, tags=tags)

from flask import Blueprint, send_file
import pandas as pd
from io import BytesIO
from flask_login import login_required
import os

uploads_bp = Blueprint('uploads', __name__, url_prefix='/uploads')  # ניתן לשנות את ה-url_prefix לפי הצורך

@uploads_bp.route('/download_template')
@login_required
def download_template():
    data = {
        'קוד קופון': ['ABC123', 'DEF456', 'GHI789'],
        'ערך מקורי': [100, 200, 150],
        'עלות': [50, 120, 80],
        'חברה': ['חברה א', 'חברה ב', 'חברה ג'],
        'תיאור': ['קופון למוצר א', 'הנחה במוצר ב', 'מבצע במוצר ג'],
        'תאריך תפוגה': ['2024-12-31', '2024-11-30', '2024-10-31'],
        'תגיות': ['מבצע, חדש', 'הנחה', 'מבצע, הנחה'],
        'קוד לשימוש חד פעמי': [False, True, False],
        'מטרת הקופון': ['', 'מטרה 2', ''],
        'סטטוס': ['פעיל', 'נוצל', 'פעיל']
    }

    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='תבנית קופונים')

    output.seek(0)

    return send_file(
        output,
        download_name='coupon_template.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
