# app/routes/coupons_routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, send_file
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError

import os
import pandas as pd
import traceback
import re
from io import BytesIO
from datetime import datetime, timezone

from app.extensions import db
from app.models import (
    Coupon, Company, Tag, CouponUsage, Transaction, Notification, CouponRequest, GptUsage, CouponTransaction
)
from app.forms import (
    ProfileForm, SellCouponForm, UploadCouponsForm, AddCouponsBulkForm, CouponForm,
    DeleteCouponsForm, ConfirmDeleteForm, MarkCouponAsUsedForm, EditCouponForm,
    ApproveTransactionForm, SMSInputForm, UpdateCouponUsageForm, DeleteCouponForm
)
from app.helpers import (
    update_coupon_status, get_coupon_data, process_coupons_excel,
    extract_coupon_detail_sms, extract_coupon_detail_image_proccess
)
from app.helpers import send_coupon_purchase_request_email, send_email
from fuzzywuzzy import fuzz

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Coupon, Notification, CouponUsage, CouponTransaction
from app.helpers import send_email, update_coupon_status, get_coupon_data
from datetime import datetime, timezone
import logging
from app.forms import UploadImageForm
from app.forms import DeleteCouponRequestForm
from app.models import User
from app.helpers import get_most_common_tag_for_company
from app.models import coupon_tags
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.helpers import (
    update_coupon_status, get_coupon_data, process_coupons_excel,
    extract_coupon_detail_sms, extract_coupon_detail_image_proccess,
    create_notification, update_coupon_usage, update_all_active_coupons
)
import logging

logger = logging.getLogger(__name__)

coupons_bp = Blueprint('coupons', __name__)


@coupons_bp.route('/sell_coupon', methods=['GET', 'POST'])
@login_required
def sell_coupon():
    form = SellCouponForm()

    # שליפת החברות והתגיות ממסד הנתונים
    companies = Company.query.all()
    tags = Tag.query.all()

    # הגדרת האפשרויות לשדות הבחירה, כולל אפשרות placeholder
    company_choices = [('', 'בחר חברה')]  # אפשרות placeholder
    company_choices += [(str(company.id), company.name) for company in companies]
    company_choices.append(('other', 'אחר'))
    form.company_select.choices = company_choices

    tag_choices = [('', 'בחר תגית')]  # אפשרות placeholder
    tag_choices += [(str(tag.id), tag.name) for tag in tags]
    tag_choices.append(('other', 'אחר'))
    form.tag_select.choices = tag_choices

    if form.validate_on_submit():
        # טיפול בשדות הטופס
        expiration = form.expiration.data
        purpose = form.purpose.data.strip() if form.is_one_time.data and form.purpose.data else None

        value = float(form.value.data)
        cost = float(form.cost.data)

        # חישוב אחוז ההנחה
        if value > 0:
            discount_percentage = ((value - cost) / value) * 100
        else:
            discount_percentage = 0.0

        # טיפול בבחירת החברה
        selected_company_id = form.company_select.data
        if selected_company_id == '':
            flash('יש לבחור חברה.', 'danger')
            return redirect(url_for('coupons.sell_coupon'))
        elif selected_company_id == 'other':
            company_name = form.other_company.data.strip()
            if not company_name:
                flash('יש להזין שם חברה חדשה.', 'danger')
                return redirect(url_for('coupons.sell_coupon'))
            existing_company = Company.query.filter_by(name=company_name).first()
            if existing_company:
                company = existing_company
            else:
                company = Company(name=company_name)
                db.session.add(company)
                try:
                    db.session.commit()
                    flash(f'החברה "{company_name}" נוספה בהצלחה.', 'success')
                except IntegrityError:
                    db.session.rollback()
                    flash('שגיאה בעת הוספת החברה. ייתכן שהחברה כבר קיימת.', 'danger')
                    return redirect(url_for('coupons.sell_coupon'))
        else:
            company = Company.query.get(int(selected_company_id))
            if not company:
                flash('החברה שנבחרה אינה תקפה.', 'danger')
                return redirect(url_for('coupons.sell_coupon'))

        # טיפול בבחירת התגית
        selected_tag_id = form.tag_select.data
        if selected_tag_id == '':
            flash('יש לבחור תגית.', 'danger')
            return redirect(url_for('coupons.sell_coupon'))
        elif selected_tag_id == 'other':
            tag_name = form.other_tag.data.strip()
            if not tag_name:
                flash('יש להזין שם תגית חדשה.', 'danger')
                return redirect(url_for('coupons.sell_coupon'))
            existing_tag = Tag.query.filter_by(name=tag_name).first()
            if existing_tag:
                tag = existing_tag
            else:
                tag = Tag(name=tag_name, count=1)
                db.session.add(tag)
                try:
                    db.session.commit()
                    flash(f'התגית "{tag_name}" נוספה בהצלחה.', 'success')
                except IntegrityError:
                    db.session.rollback()
                    flash('שגיאה בעת הוספת התגית. ייתכן שהתגית כבר קיימת.', 'danger')
                    return redirect(url_for('coupons.sell_coupon'))
        else:
            tag = Tag.query.get(int(selected_tag_id))
            if not tag:
                flash('התגית שנבחרה אינה תקפה.', 'danger')
                return redirect(url_for('coupons.sell_coupon'))

        # יצירת הקופון החדש
        new_coupon = Coupon(
            code=form.code.data.strip(),
            value=value,
            cost=cost,
            company=company.name,
            description=form.description.data.strip() if form.description.data else '',
            expiration=expiration,
            user_id=current_user.id,
            is_available=True,  # הקופון מסומן כזמין
            is_for_sale=True,  # הקופון מסומן למכירה
            is_one_time=form.is_one_time.data,
            purpose=purpose,
            discount_percentage=discount_percentage
        )
        current_app.logger.info(
            f"Coupon created: is_available={new_coupon.is_available}, is_for_sale={new_coupon.is_for_sale}")

        # הוספת התגית לקופון
        if tag:
            new_coupon.tags.append(tag)
            tag.count += 1  # עדכון ספירת התגית

        db.session.add(new_coupon)
        try:
            db.session.commit()
            flash('קופון למכירה נוסף בהצלחה!', 'success')
            return redirect(url_for('coupons.show_coupons'))
        except IntegrityError:
            db.session.rollback()
            flash('קוד הקופון כבר קיים. אנא בחר קוד אחר.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת הוספת הקופון. אנא נסה שוב מאוחר יותר.', 'danger')
            current_app.logger.error(f"Error adding coupon: {e}")
    else:
        if request.method == 'POST':
            flash('יש לתקן את השגיאות בטופס.', 'danger')

    return render_template('sell_coupon.html', form=form, companies=companies, tags=tags)

@coupons_bp.route('/coupons')
@login_required
def show_coupons():
    # שליפת כל הקופונים של המשתמש, למעט קופונים למכירה
    coupons = Coupon.query.options(joinedload(Coupon.tags)).filter_by(user_id=current_user.id, is_for_sale=False).all()
    for coupon in coupons:
        update_coupon_status(coupon)
    db.session.commit()

    # שליפת כל החברות ויצירת מילון מיפוי
    companies = Company.query.all()
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}

    # חלוקת הקופונים לקטגוריות
    active_coupons = [coupon for coupon in coupons if coupon.status == 'פעיל' and not coupon.is_one_time]
    active_one_time_coupons = [coupon for coupon in coupons if coupon.status == 'פעיל' and coupon.is_one_time]

    # קופונים שנוצלו ולא פעילים, ממויינים לפי תאריך ניצול אחרון ואז לפי שם החברה
    latest_usage_subquery = db.session.query(
        CouponUsage.coupon_id,
        func.max(CouponUsage.timestamp).label('latest_usage')
    ).group_by(CouponUsage.coupon_id).subquery()

    inactive_coupons_query = db.session.query(
        Coupon,
        latest_usage_subquery.c.latest_usage
    ).outerjoin(
        latest_usage_subquery,
        Coupon.id == latest_usage_subquery.c.coupon_id
    ).options(joinedload(Coupon.tags)).filter(
        Coupon.user_id == current_user.id,
        Coupon.status != 'פעיל',
        Coupon.is_for_sale == False
    ).order_by(
        latest_usage_subquery.c.latest_usage.desc().nullslast(),
        Coupon.company.asc()
    )

    inactive_coupons_with_usage = inactive_coupons_query.all()

    # קבלת קופונים למכירה
    coupons_for_sale = Coupon.query.filter_by(user_id=current_user.id, is_for_sale=True).order_by(
        Coupon.date_added.desc()).all()

    return render_template('coupons.html',
                           active_coupons=active_coupons,
                           active_one_time_coupons=active_one_time_coupons,
                           inactive_coupons_with_usage=inactive_coupons_with_usage,
                           coupons_for_sale=coupons_for_sale,
                           company_logo_mapping=company_logo_mapping)


@coupons_bp.route('/upload_coupons', methods=['GET', 'POST'])
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

        return redirect(url_for('coupons.show_coupons'))

    return render_template('upload_coupons.html', form=form)

@coupons_bp.route('/add_coupons_bulk', methods=['GET', 'POST'])
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
        current_app.logger.info("טופס אומת בהצלחה")
        try:
            new_coupons_data = []
            for idx, coupon_entry in enumerate(form.coupons.entries):
                coupon_form = coupon_entry.form
                # current_app.logger.info(f"עיבוד קופון #{idx + 1}: {coupon_form.data}")

                # Handle company_id
                if coupon_form.company_id.data == 'other':
                    company_name = coupon_form.other_company.data.strip()
                    if not company_name:
                        flash(f'שם החברה חסר בקופון #{idx + 1}.', 'danger')
                        current_app.logger.warning(f"Empty company name for coupon #{idx + 1}.")
                        continue
                else:
                    company_id = coupon_form.company_id.data
                    try:
                        company = db.session.get(Company, int(company_id))
                        if company:
                            company_name = company.name
                        else:
                            flash(f'חברה עם ID {company_id} לא נמצאה בקופון #{idx + 1}.', 'danger')
                            current_app.logger.warning(f"Company ID {company_id} not found for coupon #{idx + 1}.")
                            continue
                    except ValueError:
                        flash(f'ID החברה אינו תקין בקופון #{idx + 1}.', 'danger')
                        current_app.logger.warning(f"Invalid company ID format for coupon #{idx + 1}.")
                        continue

                # Handle tag_id
                if coupon_form.tag_id.data == 'other':
                    tag_name = coupon_form.other_tag.data.strip()
                    if not tag_name:
                        flash(f'שם התגית חסר בקופון #{idx + 1}.', 'danger')
                        current_app.logger.warning(f"Empty tag name for coupon #{idx + 1}.")
                        continue
                else:
                    tag_id = coupon_form.tag_id.data
                    try:
                        tag = db.session.get(Tag, int(tag_id))
                        if tag:
                            tag_name = tag.name
                        else:
                            flash(f'תגית עם ID {tag_id} לא נמצאה בקופון #{idx + 1}.', 'danger')
                            current_app.logger.warning(f"Tag ID {tag_id} not found for coupon #{idx + 1}.")
                            continue
                    except ValueError:
                        flash(f'ID התגית אינו תקין בקופון #{idx + 1}.', 'danger')
                        current_app.logger.warning(f"Invalid tag ID format for coupon #{idx + 1}.")
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
                    'תאריך תפוגה': coupon_form.expiration.data.strftime(
                        '%Y-%m-%d') if coupon_form.expiration.data else '',
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
                return redirect(url_for('coupons.show_coupons'))
            else:
                current_app.logger.info("No new coupons were added, so no export or import was made.")
                flash('לא נוספו קופונים חדשים.', 'info')
                return redirect(url_for('coupons.show_coupons'))
        except Exception as e:
            current_app.logger.error(f"Error during bulk coupon processing: {e}")
            traceback.print_exc()
            flash('אירעה שגיאה בעת עיבוד הקופונים. אנא נסה שוב.', 'danger')

    else:
        if form.is_submitted():
            current_app.logger.warning(f"Form validation failed: {form.errors}")

    return render_template('add_coupons.html', form=form, companies=companies, tags=tags)

# -----------------------------------------------------------------------------
# פונקציה לזיהוי התגית הנפוצה ביותר עבור חברה נתונה
# -----------------------------------------------------------------------------
def get_most_common_tag_for_company(company_name):
    """
    מציאת התגית הנפוצה ביותר בקופונים של החברה עם השם company_name
    """
    results = db.session.query(Tag, func.count(Tag.id).label('tag_count')) \
        .join(coupon_tags, Tag.id == coupon_tags.c.tag_id) \
        .join(Coupon, Coupon.id == coupon_tags.c.coupon_id) \
        .filter(func.lower(Coupon.company) == func.lower(company_name)) \
        .group_by(Tag.id) \
        .order_by(func.count(Tag.id).desc(), Tag.id.asc()) \
        .all()

    if results:
        # התגית הראשונה ברשימה היא הנפוצה ביותר
        print("[DEBUG] get_most_common_tag_for_company results =>", results)  # הדפסה לקונסול
        return results[0][0]
    else:
        # אין תגיות משויכות לחברה זו
        return None


# -----------------------------------------------------------------------------
# פונקציה לזיהוי התגית הנפוצה ביותר עבור חברה נתונה
# -----------------------------------------------------------------------------
def get_most_common_tag_for_company(company_name):
    """
    מציאת התגית הנפוצה ביותר בקופונים של החברה עם השם company_name
    """
    results = db.session.query(Tag, func.count(Tag.id).label('tag_count')) \
        .join(coupon_tags, Tag.id == coupon_tags.c.tag_id) \
        .join(Coupon, Coupon.id == coupon_tags.c.coupon_id) \
        .filter(func.lower(Coupon.company) == func.lower(company_name)) \
        .group_by(Tag.id) \
        .order_by(func.count(Tag.id).desc(), Tag.id.asc()) \
        .all()

    if results:
        current_app.logger.info(f"[DEBUG] get_most_common_tag_for_company({company_name}) => {results}")
        return results[0][0]  # התגית הנפוצה ביותר
    else:
        return None


@coupons_bp.route('/add_coupon', methods=['GET', 'POST'])
@login_required
def add_coupon():
    """
    מסך הוספת קופון - דרך SMS, דרך תמונה, או ידני.
    כעת בזרימה הידנית, אנו מאתרים אוטומטית את התגית הנפוצה ביותר
    על סמך שם החברה שבחר/הזין המשתמש.
    """
    try:
        # האם אנו במצב הזנה ידני?
        manual = request.args.get('manual', 'false').lower() == 'true'

        sms_form = SMSInputForm()
        coupon_form = CouponForm()
        show_coupon_form = manual

        # טען את כל החברות והתגיות מהדאטהבייס
        companies = Company.query.all()
        tags = Tag.query.all()

        # רשימת שמות החברות
        companies_list = [c.name for c in companies]

        # הגדרת האפשרויות לשדות company_id ו-tag_id
        coupon_form.company_id.choices = (
            [('', 'בחר')]
            + [(str(company.id), company.name) for company in companies]
            + [('other', 'אחר')]
        )
        coupon_form.tag_id.choices = (
            [('', 'בחר')]
            + [(str(tag.id), tag.name) for tag in tags]
            + [('other', 'אחר')]
        )

        # ---------------------------------------------------------------------
        # 1) טיפול בטופס SMS
        # ---------------------------------------------------------------------
        if sms_form.validate_on_submit() and 'sms_text' in request.form:
            sms_text = sms_form.sms_text.data

            # הפקת מידע מה-SMS
            extracted_data_df, pricing_df = extract_coupon_detail_sms(sms_text, companies_list)

            # שמירת gpt_usage אם הופקו נתוני תמחור
            if not pricing_df.empty:
                pricing_row = pricing_df.iloc[0]
                new_usage = GptUsage(
                    user_id=current_user.id,
                    created=datetime.strptime(pricing_row['created'], '%Y-%m-%d %H:%M:%S'),
                    id=pricing_row['id'],
                    object=pricing_row['object'],
                    model=pricing_row['model'],
                    prompt_tokens=int(pricing_row['prompt_tokens']),
                    completion_tokens=int(pricing_row['completion_tokens']),
                    total_tokens=int(pricing_row['total_tokens']),
                    cost_usd=float(pricing_row['cost_usd']),
                    cost_ils=float(pricing_row['cost_ils']),
                    exchange_rate=float(pricing_row['exchange_rate']),
                    prompt_text=str(pricing_row['prompt_text']),
                    response_text=str(pricing_row['response_text'])
                )
                db.session.add(new_usage)
                db.session.commit()

            if not extracted_data_df.empty:
                extracted_data = extracted_data_df.iloc[0].to_dict()

                # איתור חברה
                company_name = extracted_data.get('חברה', '').strip()
                best_match_ratio = 0
                best_company = None
                for comp in companies:
                    ratio = fuzz.token_set_ratio(company_name, comp.name)
                    if ratio > best_match_ratio:
                        best_match_ratio = ratio
                        best_company = comp

                if best_company and best_match_ratio >= 90:
                    coupon_form.company_id.data = str(best_company.id)
                    coupon_form.other_company.data = ''
                    chosen_company_name = best_company.name
                else:
                    coupon_form.company_id.data = 'other'
                    coupon_form.other_company.data = company_name
                    chosen_company_name = company_name

                # מילוי שדות
                coupon_form.code.data = extracted_data.get('קוד קופון')
                coupon_form.cost.data = extracted_data.get('ערך מקורי', 0) or 0
                try:
                    if extracted_data.get('תאריך תפוגה'):
                        coupon_form.expiration.data = datetime.strptime(
                            extracted_data['תאריך תפוגה'], '%Y-%m-%d'
                        ).date()
                except Exception as e:
                    current_app.logger.error(f"[ERROR] parsing expiration date: {e}")

                coupon_form.is_one_time.data = bool(extracted_data.get('קוד לשימוש חד פעמי'))
                coupon_form.purpose.data = extracted_data.get('מטרת הקופון', '')
                coupon_form.description.data = extracted_data.get('תיאור', '')
                coupon_form.value.data = 0
                coupon_form.discount_percentage.data = 0

                # הפחתת סלוטים
                if current_user.slots_automatic_coupons > 0:
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                else:
                    flash('אין לך מספיק סלוטים להוספת קופונים.', 'danger')
                    return redirect(url_for('coupons.add_coupon'))

                # תגית נפוצה (אוטומטית)
                current_app.logger.info(f"[DEBUG] Sending to get_most_common_tag_for_company => '{chosen_company_name}'")
                found_tag = get_most_common_tag_for_company(chosen_company_name)
                current_app.logger.info(f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'")

                if found_tag:
                    coupon_form.tag_id.data = str(found_tag.id)
                    coupon_form.other_tag.data = ''

                show_coupon_form = True
            else:
                flash('לא נמצאו נתונים בהודעת ה-SMS.', 'danger')

            return render_template(
                'add_coupon.html',
                coupon_form=coupon_form,
                sms_form=sms_form,
                show_coupon_form=show_coupon_form,
                companies=companies,
                tags=tags
            )

        # ---------------------------------------------------------------------
        # 2) טיפול בהעלאת תמונה
        # ---------------------------------------------------------------------
        if request.method == 'POST':
            if 'upload_image' in request.form and coupon_form.upload_image.data:
                # העלאת תמונה
                image_file = coupon_form.coupon_image.data
                if image_file and image_file.filename != '':
                    try:
                        flash("מתחיל בעיבוד התמונה...", "info")
                        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
                        if not os.path.exists(upload_folder):
                            os.makedirs(upload_folder)
                            flash(f"התקייה {upload_folder} נוצרה.", "info")

                        image_path = os.path.join(upload_folder, image_file.filename)
                        image_file.save(image_path)
                        flash(f"התמונה נשמרה ב-{image_path}.", "success")

                        if not companies_list:
                            flash("רשימת החברות ריקה. ודא שישנן חברות במערכת.", "warning")
                            return render_template('add_coupon.html',
                                                   coupon_form=coupon_form,
                                                   sms_form=sms_form,
                                                   show_coupon_form=show_coupon_form,
                                                   companies=companies,
                                                   tags=tags)

                        coupon_df, pricing_df = extract_coupon_detail_image_proccess(
                            client_id=os.getenv('IMGUR_CLIENT_ID'),
                            image_path=image_path,
                            companies_list=companies_list
                        )
                        flash("הפונקציה extract_coupon_detail_image_proccess הסתיימה.", "info")

                        if not coupon_df.empty:
                            flash("הופקו פרטי הקופון בהצלחה.", "success")

                            extracted_company = coupon_df.loc[0, 'חברה']
                            # איתור החברה הכי דומה
                            best_match_ratio = 0
                            best_company = None
                            for comp in companies:
                                ratio = fuzz.token_set_ratio(extracted_company, comp.name)
                                if ratio > best_match_ratio:
                                    best_match_ratio = ratio
                                    best_company = comp

                            if best_company and best_match_ratio >= 90:
                                coupon_form.company_id.data = str(best_company.id)
                                coupon_form.other_company.data = ''
                                chosen_company_name = best_company.name
                            else:
                                coupon_form.company_id.data = 'other'
                                coupon_form.other_company.data = extracted_company
                                chosen_company_name = extracted_company

                            # מילוי נתוני הקופון
                            coupon_form.code.data = coupon_df.loc[0, 'קוד קופון']
                            coupon_form.cost.data = coupon_df.loc[0, 'עלות'] if pd.notnull(
                                coupon_df.loc[0, 'עלות']) else 0
                            coupon_form.value.data = coupon_df.loc[0, 'ערך מקורי'] if pd.notnull(
                                coupon_df.loc[0, 'ערך מקורי']) else 0
                            coupon_form.discount_percentage.data = coupon_df.loc[0, 'אחוז הנחה'] if pd.notnull(
                                coupon_df.loc[0, 'אחוז הנחה']) else 0
                            try:
                                expiration_val = coupon_df.loc[0, 'תאריך תפוגה']
                                if pd.notnull(expiration_val):
                                    coupon_form.expiration.data = pd.to_datetime(expiration_val).date()
                            except Exception as e:
                                current_app.logger.error(f"[ERROR] parsing expiration date from image: {e}")

                            coupon_form.description.data = coupon_df.loc[0, 'תיאור'] \
                                if pd.notnull(coupon_df.loc[0, 'תיאור']) else ''
                            coupon_form.is_one_time.data = False
                            coupon_form.purpose.data = ''

                            # הפחתת סלוטים
                            if current_user.slots_automatic_coupons > 0:
                                current_user.slots_automatic_coupons -= 1
                                db.session.commit()
                            else:
                                flash('אין לך מספיק סלוטים להוספת קופונים.', 'danger')
                                return redirect(url_for('coupons.add_coupon'))

                            # תגית נפוצה (אוטומטית)
                            current_app.logger.info(f"[DEBUG] Sending to get_most_common_tag_for_company => '{chosen_company_name}'")
                            found_tag = get_most_common_tag_for_company(chosen_company_name)
                            current_app.logger.info(f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'")

                            if found_tag:
                                coupon_form.tag_id.data = str(found_tag.id)
                                coupon_form.other_tag.data = ''

                            show_coupon_form = True
                            flash("הטופס מולא בהצלחה. אנא בדוק וערוך אם נדרש.", "success")
                        else:
                            flash("לא ניתן היה לחלץ פרטי קופון מהתמונה.", "danger")
                    except Exception as e:
                        current_app.logger.error(f"[ERROR] processing image: {e}")
                        traceback.print_exc()
                        flash("אירעה שגיאה בעת עיבוד התמונה. אנא נסה שוב מאוחר יותר.", "danger")
                else:
                    flash("חובה להעלות תמונה.", "danger")

                return render_template('add_coupon.html',
                                       coupon_form=coupon_form,
                                       sms_form=sms_form,
                                       show_coupon_form=show_coupon_form,
                                       companies=companies,
                                       tags=tags)

            # -----------------------------------------------------------------
            # 3) טיפול בהזנה ידנית (Manual)
            # -----------------------------------------------------------------
            elif 'submit_coupon' in request.form and coupon_form.submit_coupon.data:
                current_app.logger.info("[DEBUG] Manual flow - user pressed submit_coupon")

                if coupon_form.validate_on_submit():
                    code = coupon_form.code.data.strip()
                    # המרות
                    try:
                        value = float(coupon_form.value.data) if coupon_form.value.data else 0
                    except Exception as e:
                        current_app.logger.error(f"[ERROR] converting value to float: {e}")
                        value = 0
                    try:
                        cost = float(coupon_form.cost.data) if coupon_form.cost.data else 0
                    except Exception as e:
                        current_app.logger.error(f"[ERROR] converting cost to float: {e}")
                        cost = 0

                    description = (coupon_form.description.data or '').strip()
                    expiration = coupon_form.expiration.data or None
                    is_one_time = coupon_form.is_one_time.data
                    purpose = (coupon_form.purpose.data.strip() if is_one_time else '') or None

                    selected_company_id = coupon_form.company_id.data
                    other_company_name = (coupon_form.other_company.data or '').strip()

                    # קביעה סופית של שם החברה
                    if selected_company_id == 'other':
                        if not other_company_name:
                            flash('יש להזין שם חברה חדשה.', 'danger')
                            return redirect(url_for('coupons.add_coupon', manual='true'))

                        # בדיקה אם החברה כבר קיימת
                        existing_company = Company.query.filter_by(name=other_company_name).first()
                        if existing_company:
                            company = existing_company
                        else:
                            company = Company(name=other_company_name, image_path='default_logo.png')
                            db.session.add(company)
                            db.session.flush()
                    else:
                        try:
                            selected_company_id = int(selected_company_id)
                            company = Company.query.get(selected_company_id)
                            if not company:
                                flash('חברה נבחרה אינה תקפה.', 'danger')
                                return redirect(url_for('coupons.add_coupon', manual='true'))
                        except (ValueError, TypeError):
                            flash('חברה נבחרה אינה תקפה.', 'danger')
                            return redirect(url_for('coupons.add_coupon', manual='true'))

                    # בדיקת סלוטים
                    if current_user.slots_automatic_coupons <= 0:
                        flash('אין לך מספיק סלוטים להוספת קופונים.', 'danger')
                        return redirect(url_for('coupons.add_coupon', manual='true'))

                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()

                    # יצירת הקופון
                    new_coupon = Coupon(
                        code=code,
                        value=value,
                        cost=cost,
                        company=company.name,
                        description=description,
                        expiration=expiration,
                        user_id=current_user.id,
                        is_one_time=is_one_time,
                        purpose=purpose
                    )

                    # כאן אנחנו קוראים ל־get_most_common_tag_for_company
                    # כדי לייחס את התגית הנפוצה (במקום קריאת השדות tag_id / other_tag).
                    chosen_company_name = company.name
                    current_app.logger.info(f"[DEBUG] Manual flow => chosen_company_name = '{chosen_company_name}'")
                    found_tag = get_most_common_tag_for_company(chosen_company_name)
                    current_app.logger.info(f"[DEBUG] Manual flow => auto found_tag = '{found_tag}'")

                    if found_tag:
                        new_coupon.tags.append(found_tag)
                    else:
                        # אין תגית נפוצה - אפשר (לבחירתך) ליצור תגית כללית,
                        # או להשאיר בלי תגיות
                        current_app.logger.info("[DEBUG] No common tag found. The coupon will have no tag.")

                    db.session.add(new_coupon)

                    try:
                        db.session.commit()
                        flash('קופון נוסף בהצלחה!', 'success')
                        return redirect(url_for('coupons.show_coupons'))
                    except IntegrityError as e:
                        db.session.rollback()
                        current_app.logger.error(f"[ERROR] IntegrityError adding coupon: {e}")
                        flash('קוד קופון זה כבר קיים. אנא בחר קוד אחר.', 'danger')
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.error(f"[ERROR] Error adding coupon: {e}")
                        flash('אירעה שגיאה בעת הוספת הקופון. נסה שוב.', 'danger')
                else:
                    flash("הטופס אינו תקין. אנא בדוק את הנתונים שהזנת.", "danger")

        # טעינה ראשונית של הדף (GET)
        return render_template(
            'add_coupon.html',
            coupon_form=coupon_form,
            sms_form=sms_form,
            show_coupon_form=show_coupon_form,
            companies=companies,
            tags=tags
        )

    except Exception as e:
        current_app.logger.error(f"[ERROR] Unhandled exception in add_coupon: {e}")
        traceback.print_exc()
        flash("אירעה שגיאה בלתי צפויה. אנא נסה שוב מאוחר יותר.", "danger")
        return redirect(url_for('coupons.add_coupon'))

@coupons_bp.route('/add_coupon_with_image.html', methods=['GET', 'POST'])
@login_required
def add_coupon_with_image_html():
    form = CouponForm()
    if request.method == 'POST':
        image_file = request.files.get('coupon_image')
        if image_file and image_file.filename != '':
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            image_path = os.path.join(upload_folder, image_file.filename)
            image_file.save(image_path)

            coupon_df, pricing_df = extract_coupon_detail_image_proccess(
                client_id=os.getenv('IMGUR_CLIENT_ID'),
                image_path=image_path,
                companies_list=[company.name for company in Company.query.all()]
            )
            if not coupon_df.empty:
                form.company_id.data = coupon_df.loc[0, 'חברה']
                form.code.data = coupon_df.loc[0, 'קוד קופון']
                form.cost.data = coupon_df.loc[0, 'עלות']
                form.value.data = coupon_df.loc[0, 'ערך מקורי']
                form.discount_percentage.data = coupon_df.loc[0, 'אחוז הנחה']
                form.expiration.data = pd.to_datetime(coupon_df.loc[0, 'תאריך תפוגה']).date()
                form.description.data = coupon_df.loc[0, 'תיאור']
                flash("הטופס מולא בהצלחה. אנא בדוק וערוך אם נדרש.", "success")
            else:
                flash("לא ניתן היה לחלץ פרטי קופון מהתמונה.", "danger")
    return render_template('add_coupon_with_image.html', form=form)

@coupons_bp.route('/add_coupon_with_image', methods=['GET', 'POST'])
@login_required
def add_coupon_with_image():
    upload_image_form = UploadImageForm()
    coupon_form = CouponForm()
    show_coupon_form = False

    # הגדרת הבחירות לשדות company_id ו-tag_id מתוך הדאטהבייס
    companies = Company.query.all()
    tags = Tag.query.all()

    # הגדרת הבחירות בצורה זהה ל-add_coupon
    coupon_form.company_id.choices = [('', 'בחר')] + [(str(company.id), company.name) for company in companies] + [('other', 'אחר')]
    coupon_form.tag_id.choices = [('', 'בחר')] + [(str(tag.id), tag.name) for tag in tags] + [('other', 'אחר')]

    if upload_image_form.validate_on_submit() and upload_image_form.submit_upload_image.data:
        # טיפול בהעלאת התמונה
        image_file = upload_image_form.coupon_image.data
        if image_file:
            filename = secure_filename(image_file.filename)
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            image_path = os.path.join(upload_folder, filename)
            image_file.save(image_path)

            # עיבוד התמונה והפקת פרטי הקופון
            try:
                coupon_df, pricing_df = extract_coupon_detail_image_proccess(
                    client_id=os.getenv('IMGUR_CLIENT_ID'),
                    image_path=image_path,
                    companies_list=[company.name for company in companies]
                )

            except Exception as e:
                current_app.logger.error(f"Error extracting coupon from image: {e}")
                flash(f"אירעה שגיאה בעת עיבוד התמונה: {e}", "danger")
                return render_template('add_coupon_with_image.html',
                                       coupon_form=coupon_form,
                                       upload_image_form=upload_image_form,
                                       show_coupon_form=show_coupon_form)

            if not coupon_df.empty:
                coupon_data = coupon_df.iloc[0].to_dict()
                company_name = coupon_data.get('חברה', '').strip()
                tag_name = coupon_data.get('תגיות', '').strip()

                # חיפוש החברה באמצעות fuzzy matching
                best_match_ratio = 0
                best_company = None
                for comp in companies:
                    ratio = fuzz.token_set_ratio(company_name, comp.name)
                    if ratio > best_match_ratio:
                        best_match_ratio = ratio
                        best_company = comp

                if best_company and best_match_ratio >= 90:
                    coupon_form.company_id.data = str(best_company.id)
                    coupon_form.other_company.data = ''
                else:
                    coupon_form.company_id.data = 'other'
                    coupon_form.other_company.data = company_name

                # חיפוש התגית באמצעות fuzzy matching
                best_tag_ratio = 0
                best_tag = None
                for tag in tags:
                    ratio = fuzz.token_set_ratio(tag_name, tag.name)
                    if ratio > best_tag_ratio:
                        best_tag_ratio = ratio
                        best_tag = tag

                if best_tag and best_tag_ratio >= 90:
                    coupon_form.tag_id.data = str(best_tag.id)
                    coupon_form.other_tag.data = ''
                else:
                    coupon_form.tag_id.data = 'other'
                    coupon_form.other_tag.data = tag_name

                # מילוי יתר השדות
                coupon_form.code.data = coupon_data.get('קוד קופון')
                coupon_form.cost.data = float(coupon_data.get('עלות', 0))
                coupon_form.value.data = float(coupon_data.get('ערך מקורי', 0))

                # אחוז הנחה
                if 'אחוז הנחה' in coupon_df.columns:
                    coupon_form.discount_percentage.data = float(coupon_data.get('אחוז הנחה', 0))
                else:
                    coupon_form.discount_percentage.data = 0  # ברירת מחדל

                # תאריך תפוגה
                expiration_str = coupon_data.get('תאריך תפוגה')
                if expiration_str:
                    try:
                        coupon_form.expiration.data = datetime.strptime(expiration_str, '%Y-%m-%d').date()
                    except ValueError:
                        coupon_form.expiration.data = None
                else:
                    coupon_form.expiration.data = None

                # תיאור
                coupon_form.description.data = coupon_data.get('תיאור', '')

                # קוד לשימוש חד פעמי ומטרת הקופון
                coupon_form.is_one_time.data = bool(coupon_data.get('קוד לשימוש חד פעמי'))
                coupon_form.purpose.data = coupon_data.get('מטרת הקופון', '') if coupon_form.is_one_time.data else ''

                # הפחתת סלוטים
                if current_user.slots_automatic_coupons > 0:
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                else:
                    flash('אין לך מספיק סלוטים להוספת קופונים.', 'danger')
                    return redirect(url_for('coupons.add_coupon_with_image'))

                show_coupon_form = True
                flash("הטופס מולא בהצלחה. אנא בדוק וערוך אם נדרש.", "success")
            else:
                # כאן נוסיף סיבה
                error_reason = "לא נמצאו נתונים בתמונה."
                # אם pricing_df מכיל מידע על השגיאה, אפשר לשלוף משם:
                if not pricing_df.empty and 'error_message' in pricing_df.columns:
                    error_reason = pricing_df.iloc[0]['error_message']

                flash(f"לא ניתן היה לחלץ פרטי קופון מהתמונה: {error_reason}", "danger")

    elif coupon_form.validate_on_submit() and coupon_form.submit_coupon.data:
        # טיפול בהגשת הטופס למילוי הקופון
        # מציאת או יצירת החברה
        selected_company_id = coupon_form.company_id.data
        other_company_name = coupon_form.other_company.data.strip() if coupon_form.other_company.data else ''

        if selected_company_id == 'other':
            if not other_company_name:
                flash('יש להזין שם חברה חדשה.', 'danger')
                return redirect(url_for('coupons.add_coupon_with_image'))
            existing_company = Company.query.filter_by(name=other_company_name).first()
            if existing_company:
                company = existing_company
            else:
                company = Company(name=other_company_name, image_path='default_logo.png')
                db.session.add(company)
                db.session.flush()
        else:
            try:
                selected_company_id = int(selected_company_id)
                company = Company.query.get(selected_company_id)
                if not company:
                    flash('חברה נבחרה אינה תקפה.', 'danger')
                    return redirect(url_for('coupons.add_coupon_with_image'))
            except (ValueError, TypeError):
                flash('חברה נבחרה אינה תקפה.', 'danger')
                return redirect(url_for('coupons.add_coupon_with_image'))

        # מציאת או יצירת התגית
        selected_tag_id = coupon_form.tag_id.data
        other_tag_name = coupon_form.other_tag.data.strip() if coupon_form.other_tag.data else ''
        if selected_tag_id == 'other':
            if not other_tag_name:
                flash('יש להזין שם תגית חדשה.', 'danger')
                return redirect(url_for('coupons.add_coupon_with_image'))
            existing_tag = Tag.query.filter_by(name=other_tag_name).first()
            if existing_tag:
                tag = existing_tag
            else:
                tag = Tag(name=other_tag_name, count=1)
                db.session.add(tag)
                db.session.flush()
        else:
            try:
                selected_tag_id = int(selected_tag_id)
                tag = Tag.query.get(selected_tag_id)
                if not tag:
                    flash('תגית נבחרה אינה תקפה.', 'danger')
                    return redirect(url_for('coupons.add_coupon_with_image'))
            except (ValueError, TypeError):
                flash('תגית נבחרה אינה תקפה.', 'danger')
                return redirect(url_for('coupons.add_coupon_with_image'))

        # בדיקת תקינות נתונים ושמירה למסד הנתונים
        code = coupon_form.code.data.strip()
        try:
            value = float(coupon_form.value.data)
        except ValueError:
            flash('ערך הקופון חייב להיות מספר.', 'danger')
            show_coupon_form = True
            return render_template(
                'add_coupon_with_image.html',
                coupon_form=coupon_form,
                upload_image_form=upload_image_form,
                show_coupon_form=show_coupon_form,
                form=coupon_form
            )
        try:
            cost = float(coupon_form.cost.data)
        except ValueError:
            flash('מחיר הקופון חייב להיות מספר.', 'danger')
            show_coupon_form = True
            return render_template(
                'add_coupon_with_image.html',
                coupon_form=coupon_form,
                upload_image_form=upload_image_form,
                show_coupon_form=show_coupon_form,
                form=coupon_form
            )
        description = coupon_form.description.data.strip() if coupon_form.description.data else ''
        expiration = coupon_form.expiration.data or None
        is_one_time = coupon_form.is_one_time.data
        purpose = coupon_form.purpose.data.strip() if is_one_time and coupon_form.purpose.data else None

        # בדיקת ייחודיות קוד הקופון
        if Coupon.query.filter_by(code=code).first():
            flash('קוד קופון זה כבר קיים. אנא בחר קוד אחר.', 'danger')
            return redirect(url_for('coupons.add_coupon_with_image'))

        # בדיקת תאריך תפוגה
        current_date = datetime.utcnow().date()
        if expiration and expiration < current_date:
            flash('תאריך התפוגה של הקופון כבר עבר. אנא עדכן תאריך או בחר קופון אחר.', 'danger')
            show_coupon_form = True
            return render_template(
                'add_coupon_with_image.html',
                coupon_form=coupon_form,
                upload_image_form=upload_image_form,
                show_coupon_form=show_coupon_form,
                form=coupon_form
            )

        # יצירת האובייקט החדש של הקופון
        new_coupon = Coupon(
            code=code,
            value=value,
            cost=cost,
            company=company.name,
            description=description,
            expiration=expiration,
            user_id=current_user.id,
            is_one_time=is_one_time,
            purpose=purpose
        )

        new_coupon.used_value = 0.0
        new_coupon.status = 'פעיל'

        new_coupon.tags.append(tag)

        db.session.add(new_coupon)
        try:
            db.session.commit()
            notification = Notification(
                user_id=current_user.id,
                message=f"הקופון {new_coupon.code} נוסף בהצלחה.",
                link=url_for('coupons.coupon_detail', id=new_coupon.id)
            )
            db.session.add(notification)
            db.session.commit()

            flash('קופון נוסף בהצלחה!', 'success')
            return redirect(url_for('coupons.show_coupons'))
        except IntegrityError:
            db.session.rollback()
            flash('קוד קופון זה כבר קיים. אנא בחר קוד אחר.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת הוספת הקופון. נסה שוב.', 'danger')
            current_app.logger.error(f"Error adding coupon: {e}")

        show_coupon_form = True

    return render_template('add_coupon_with_image.html',
                           coupon_form=coupon_form,
                           upload_image_form=upload_image_form,
                           show_coupon_form=show_coupon_form,
                           form=upload_image_form if not show_coupon_form else coupon_form)

@coupons_bp.route('/add_coupon_manual', methods=['GET', 'POST'])
@login_required
def add_coupon_manual():
    coupon_form = CouponForm()
    # אתחול הטופס ללא נתונים
    if coupon_form.validate_on_submit():
        # טיפול בהוספת הקופון
        pass
    return render_template('add_coupon.html', coupon_form=coupon_form, show_coupon_form=True)

def convert_date_format(date_input):
    """
    המרת תאריך מפורמט DD/MM/YYYY לפורמט YYYY-MM-DD.
    אם הפורמט אינו תקין, מחזיר None.
    """
    if isinstance(date_input, str):
        try:
            return datetime.strptime(date_input, '%d/%m/%Y').date()
        except ValueError:
            return None
    elif isinstance(date_input, datetime):
        return date_input.date()
    elif isinstance(date_input, datetime.date):
        return date_input
    else:
        return None

@coupons_bp.route('/edit_coupon/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_coupon(id):
    coupon = Coupon.query.get_or_404(id)

    # בדיקת הרשאות
    if coupon.user_id != current_user.id:
        flash('אינך מורשה לערוך קופון זה.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    form = EditCouponForm(obj=coupon)  # אתחול הטופס עם נתוני הקופון

    if form.validate_on_submit():
        try:
            old_value = coupon.value  # שמירת הערך הישן להשוואה

            # עדכון השדות
            coupon.company = form.company.data.strip()
            coupon.code = form.code.data.strip()
            coupon.value = float(form.value.data)
            coupon.cost = float(form.cost.data)
            coupon.description = form.description.data or ''
            coupon.is_one_time = form.is_one_time.data
            coupon.purpose = form.purpose.data.strip() if form.is_one_time.data else None
            coupon.expiration = form.expiration.data if form.expiration.data else None  # צריך להיות אובייקט date או None

            # טיפול בתגיות
            if form.tags.data:
                tag_names = [tag.strip() for tag in form.tags.data.split(',') if tag.strip()]
                coupon.tags.clear()
                for name in tag_names:
                    tag = Tag.query.filter_by(name=name).first()
                    if not tag:
                        tag = Tag(name=name, count=1)
                        db.session.add(tag)
                    else:
                        tag.count += 1
                    coupon.tags.append(tag)
            else:
                coupon.tags.clear()

            db.session.commit()

            # עדכון רשומת העסקה הראשונית אם הערך השתנה
            if coupon.value != old_value:
                initial_transaction = CouponTransaction.query.filter_by(
                    coupon_id=coupon.id,
                    source='User',
                    reference_number='Initial'
                ).first()
                if initial_transaction:
                    initial_transaction.recharge_amount = coupon.value
                else:
                    # יצירת רשומת עסקה ראשונית אם לא קיימת
                    initial_transaction = CouponTransaction(
                        coupon_id=coupon.id,
                        card_number=coupon.code,
                        transaction_date=datetime.utcnow(),
                        location='הטענה ראשונית',
                        recharge_amount=coupon.value,
                        usage_amount=0.0,
                        reference_number='Initial',
                        source='User'
                    )
                    db.session.add(initial_transaction)
                db.session.commit()

            flash('הקופון עודכן בהצלחה.', 'success')
            return redirect(url_for('coupons.coupon_detail', id=coupon.id))

        except IntegrityError:
            db.session.rollback()
            flash('קוד קופון זה כבר קיים. אנא בחר קוד אחר.', 'danger')

        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת עדכון הקופון. נסה שוב.', 'danger')
            current_app.logger.error(f"Error updating coupon: {e}")

    elif request.method == 'GET':
        # מילוי הטופס עם נתוני הקופון הקיימים
        if coupon.expiration:
            if isinstance(coupon.expiration, str):
                try:
                    coupon.expiration = datetime.strptime(coupon.expiration, '%Y-%m-%d').date()
                except ValueError:
                    try:
                        coupon.expiration = datetime.strptime(coupon.expiration, '%d/%m/%Y').date()
                    except ValueError:
                        coupon.expiration = None
        form.expiration.data = coupon.expiration
        form.tags.data = ', '.join([tag.name for tag in coupon.tags])

    # הכנת תגיות קיימות והצעות לתגיות
    existing_tags = ', '.join([tag.name for tag in coupon.tags])
    top_tags = Tag.query.order_by(Tag.count.desc()).limit(3).all()
    top_tags = [tag.name for tag in top_tags]

    return render_template('edit_coupon.html', form=form, coupon=coupon, existing_tags=existing_tags, top_tags=top_tags)

@coupons_bp.route('/delete_coupons', methods=['GET', 'POST'])
@login_required
def select_coupons_to_delete():
    form = DeleteCouponsForm()
    # שליפת הקופונים של המשתמש ומיון מהחדש לישן לפי date_added
    coupons = Coupon.query.filter_by(user_id=current_user.id).order_by(Coupon.date_added.desc()).all()

    # הגדרת הבחירות לשדה ה-select
    form.coupon_ids.choices = [(coupon.id, f"{coupon.company} - {coupon.code}") for coupon in coupons]

    if form.validate_on_submit():
        selected_ids = form.coupon_ids.data
        if selected_ids:
            # מחיקת הקופונים שנבחרו
            Coupon.query.filter(Coupon.id.in_(selected_ids)).delete(synchronize_session=False)
            db.session.commit()
            flash('הקופונים נמחקו בהצלחה.', 'success')
        else:
            flash('לא נבחרו קופונים למחיקה.', 'warning')
        return redirect(url_for('coupons.show_coupons'))

    return render_template('delete_coupons.html', form=form, coupons=coupons)

def get_companies():
    response = supabase.table("companies").select("*").execute()
    if response.status_code == 200:
        return response.data
    else:
        print("Error fetching companies:", response.error_message)
        return []

@coupons_bp.route('/coupon_detail/<int:id>')
@login_required
def coupon_detail(id):
    coupon = Coupon.query.get_or_404(id)
    is_owner = coupon.user_id == current_user.id
    mark_form = MarkCouponAsUsedForm()
    delete_form = DeleteCouponForm()
    update_form = UpdateCouponUsageForm()  # ודא שיש לך את הטופס הזה

    # שאילתת עסקאות ממיינות לפי תאריך
    transactions = CouponTransaction.query.filter_by(coupon_id=coupon.id).order_by(
        CouponTransaction.transaction_date.asc()).all()

    # שליפת כל החברות ויצירת מילון מיפוי עבור לוגואים
    companies = Company.query.all()
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}
    company_logo = company_logo_mapping.get(coupon.company.lower(), 'default_logo.png')  # הגדר לוגו ברירת מחדל אם אין

    # חישוב אחוז ההנחה אם הקופון למכירה
    discount_percentage = None
    if coupon.is_for_sale and coupon.value > 0:
        discount_percentage = ((coupon.cost - coupon.value) / coupon.cost) * 100
        discount_percentage = round(discount_percentage, 2)

    return render_template(
        'coupon_detail.html',
        coupon=coupon,
        is_owner=is_owner,
        mark_form=mark_form,
        delete_form=delete_form,
        update_form=update_form,
        transactions=transactions,
        company_logo=company_logo,
        discount_percentage=discount_percentage
    )

@coupons_bp.route('/update_coupon_transactions', methods=['POST'])
@login_required
def update_coupon_transactions():
    # בדיקת הרשאות
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        coupon_id = request.form.get('coupon_id')
        coupon_code = request.form.get('coupon_code')

        coupon = None
        if coupon_id:
            coupon = Coupon.query.get(coupon_id)
        elif coupon_code:
            coupon = Coupon.query.filter_by(code=coupon_code).first()

        if coupon:
            return redirect(url_for('coupons.coupon_detail', id=coupon.id))
        else:
            flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
            return redirect(url_for('coupons.show_coupons'))

    # קבלת הנתונים מהטופס
    coupon_id = request.form.get('coupon_id')
    coupon_code = request.form.get('coupon_code')
    print(f"coupon_id: {coupon_id}, coupon_code: {coupon_code}")

    coupon = None
    if coupon_id:
        coupon = Coupon.query.get(coupon_id)
    elif coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()

    if not coupon:
        flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    # קבלת הנתונים ועדכון העסקאות
    df = get_coupon_data(coupon.code)
    if df is not None:
        # מחיקת עסקאות קודמות שהגיעו מ-Multipass בלבד
        CouponTransaction.query.filter_by(coupon_id=coupon.id, source='Multipass').delete()

        # הוספת עסקאות חדשות
        for index, row in df.iterrows():
            transaction = CouponTransaction(
                coupon_id=coupon.id,
                card_number=row['card_number'],
                transaction_date=row['transaction_date'],
                location=row['location'],
                recharge_amount=row['recharge_amount'] or 0,
                usage_amount=row['usage_amount'] or 0,
                reference_number=row.get('reference_number', ''),
                source='Multipass'  # ציון שהעסקה הגיעה מ-Multipass
            )
            db.session.add(transaction)

        # עדכון השדה used_value של הקופון
        total_used = df['usage_amount'].sum()
        coupon.used_value = total_used

        db.session.commit()
        flash(f'הנתונים עבור הקופון {coupon.code} עודכנו בהצלחה.', 'success')
    else:
        flash(f'אירעה שגיאה בעת עדכון הנתונים עבור הקופון {coupon.code}.', 'danger')

    return redirect(url_for('coupons.coupon_detail', id=coupon.id))

@coupons_bp.route('/mark_coupon_as_fully_used/<int:id>', methods=['POST'])
@login_required
def mark_coupon_as_fully_used(id):
    coupon = Coupon.query.get_or_404(id)

    # בדיקת הרשאה
    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    # בדיקה אם הקופון כבר נוצל או לא פעיל
    if coupon.status != 'פעיל':
        flash('הקופון כבר נוצל או לא פעיל.', 'warning')
        return redirect(url_for('coupons.coupon_detail', id=id))

    # בדיקה אם הקופון הוא לא חד-פעמי (כי לחד-פעמי כבר יש רוטה אחרת)
    if coupon.is_one_time:
        flash('קופון זה הוא חד-פעמי. אנא השתמש בכפתור המתאים לו.', 'warning')
        return redirect(url_for('coupons.coupon_detail', id=id))

    # מחשבים כמה עוד נותר להשתמש
    remaining_amount = coupon.value - coupon.used_value
    if remaining_amount <= 0:
        flash('אין ערך נותר בקופון, הוא כבר נוצל במלואו.', 'info')
        return redirect(url_for('coupons.coupon_detail', id=id))

    # ביצוע העדכון
    try:
        # עדכון הערך הנוצל
        coupon.used_value = coupon.value
        update_coupon_status(coupon)  # יעדכן את הסטטוס ל"נוצל"

        # יצירת רשומת שימוש
        usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=remaining_amount,
            timestamp=datetime.now(timezone.utc),
            action='נוצל',
            details='הקופון סומן כנוצל לגמרי על ידי המשתמש.'
        )
        db.session.add(usage)

        # יצירת התראה למשתמש
        notification = Notification(
            user_id=coupon.user_id,
            message=f"הקופון {coupon.code} נוצל במלואו.",
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )
        db.session.add(notification)

        db.session.commit()
        flash('הקופון סומן כנוצל לגמרי בהצלחה.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error marking coupon as fully used: {e}")
        flash('אירעה שגיאה בעת סימון הקופון כנוצל.', 'danger')

    return redirect(url_for('coupons.coupon_detail', id=id))

@coupons_bp.route('/update_coupon/<int:id>', methods=['GET', 'POST'])
@login_required
def update_coupon(id):
    coupon = Coupon.query.get_or_404(id)

    # בדיקת הרשאות
    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לעדכן קופון זה.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    # בדיקת אם הקופון הוא חד-פעמי
    if coupon.is_one_time:
        coupon.status = "נוצל"
        try:
            db.session.commit()
            flash('סטטוס הקופון עודכן בהצלחה ל"נוצל".', 'success')
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת עדכון סטטוס הקופון.', 'danger')
            current_app.logger.error(f"Error updating one-time coupon status: {e}")
        return redirect(url_for('coupons.coupon_detail', id=id))

    form = UpdateCouponUsageForm()
    if form.validate_on_submit():
        new_used_amount = form.used_amount.data
        if new_used_amount < 0:
            flash('כמות השימוש חייבת להיות חיובית.', 'danger')
            return redirect(url_for('coupons.update_coupon_usage', id=id))

        if (coupon.used_value + new_used_amount) > coupon.value:
            flash('הכמות שהשתמשת בה גדולה מערך הקופון הנותר.', 'danger')
            return redirect(url_for('coupons.update_coupon_usage', id=id))

        try:
            # עדכון כמות השימוש
            coupon.used_value += new_used_amount
            update_coupon_status(coupon)

            # יצירת רשומת שימוש חדשה
            usage = CouponUsage(
                coupon_id=coupon.id,
                used_amount=new_used_amount,
                timestamp=datetime.now(timezone.utc),
                action='שימוש',
                details=f'השתמשת ב-{new_used_amount} ש"ח מהקופון.'
            )
            db.session.add(usage)

            # יצירת התראה למשתמש
            notification = Notification(
                user_id=coupon.user_id,
                message=f"השתמשת ב-{new_used_amount} ש״ח בקופון {coupon.code}.",
                link=url_for('coupons.coupon_detail', id=coupon.id)
            )
            db.session.add(notification)

            db.session.commit()
            flash('כמות השימוש עודכנה בהצלחה.', 'success')
            return redirect(url_for('coupons.coupon_detail', id=id))
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת עדכון כמות השימוש.', 'danger')
            current_app.logger.error(f"Error updating coupon usage: {e}")

    return render_template('update_coupon_usage.html', form=form, coupon=coupon)

@coupons_bp.route('/delete_coupon/<int:id>', methods=['POST'])
@login_required
def delete_coupon(id):
    form = DeleteCouponForm()
    if form.validate_on_submit():
        coupon = Coupon.query.get_or_404(id)
        if coupon.user_id != current_user.id:
            flash('אינך מורשה למחוק קופון זה.', 'danger')
            return redirect(url_for('coupons.show_coupons'))

        # בדיקת עסקאות קשורות
        transactions = Transaction.query.filter_by(coupon_id=coupon.id).all()
        if transactions:
            # נוביל לדף אישור המחיקה
            return redirect(url_for('coupons.confirm_delete_coupon', id=id))
        else:
            # המשך במחיקה כרגיל
            # הפחתת ספירת התגיות
            for tag in coupon.tags:
                tag.count -= 1
                if tag.count < 0:
                    tag.count = 0

            # מחיקת קובץ ה-Excel הקשור
            data_directory = "multipass/input_html"
            xlsx_filename = f"coupon_{coupon.code}_{coupon.id}.xlsx"
            xlsx_path = os.path.join(data_directory, xlsx_filename)
            if os.path.exists(xlsx_path):
                os.remove(xlsx_path)

            db.session.delete(coupon)
            db.session.commit()
            flash(f'קופון "{coupon.code}" נמחק בהצלחה!', 'success')
            return redirect(url_for('coupons.show_coupons'))
    else:
        flash('שגיאה במחיקת הקופון. נסה שוב.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

@coupons_bp.route('/confirm_delete_coupon/<int:id>', methods=['GET', 'POST'])
@login_required
def confirm_delete_coupon(id):
    coupon = Coupon.query.get_or_404(id)
    if coupon.user_id != current_user.id:
        flash('אינך מורשה למחוק קופון זה.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    form = ConfirmDeleteForm()
    if form.validate_on_submit():
        if form.submit.data:
            try:
                # מחיקת העסקאות הקשורות
                transactions = Transaction.query.filter_by(coupon_id=coupon.id).all()
                for transaction in transactions:
                    db.session.delete(transaction)

                # הפחתת ספירת התגיות
                for tag in coupon.tags:
                    tag.count -= 1
                    if tag.count < 0:
                        tag.count = 0

                # מחיקת קובץ ה-Excel הקשור
                data_directory = "multipass/input_html"
                xlsx_filename = f"coupon_{coupon.code}_{coupon.id}.xlsx"
                xlsx_path = os.path.join(data_directory, xlsx_filename)
                if os.path.exists(xlsx_path):
                    os.remove(xlsx_path)

                # מחיקת הקופון
                db.session.delete(coupon)
                db.session.commit()
                flash(f'קופון "{coupon.code}" נמחק בהצלחה!', 'success')
                return redirect(url_for('coupons.show_coupons'))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error deleting coupon {coupon.id}: {e}")
                flash('אירעה שגיאה במחיקת הקופון. נסה שוב.', 'danger')
        elif form.cancel.data:
            # ביטול המחיקה
            flash('המחיקה בוטלה.', 'info')
            return redirect(url_for('coupons.coupon_detail', id=id))

    return render_template('confirm_delete.html', coupon=coupon, form=form)

@coupons_bp.route('/edit_usage/<int:usage_id>', methods=['GET', 'POST'])
@login_required
def edit_usage(usage_id):
    usage = CouponUsage.query.get_or_404(usage_id)
    coupon = Coupon.query.get_or_404(usage.coupon_id)
    if coupon.user_id != current_user.id:
        flash('אינך מורשה לערוך שימוש זה.', 'danger')
        return redirect(url_for('coupons.show_coupons'))
    if request.method == 'POST':
        new_used_amount = float(request.form['used_amount'])
        if new_used_amount <= 0:
            flash('כמות השימוש חייבת להיות חיובית.', 'danger')
            return redirect(url_for('coupons.edit_usage', usage_id=usage_id))

        # Adjust the used_value
        coupon.used_value -= usage.used_amount
        if (coupon.used_value + new_used_amount) > coupon.value:
            flash('הכמות שהשתמשת בה גדולה מערך הקופון הנותר.', 'danger')
            coupon.used_value += usage.used_amount  # Revert the change
            return redirect(url_for('coupons.edit_usage', usage_id=usage_id))

        usage.used_amount = new_used_amount
        coupon.used_value += new_used_amount

        update_coupon_status(coupon)

        db.session.commit()
        flash('רשומת השימוש עודכנה בהצלחה!', 'success')
        return redirect(url_for('coupons.coupon_detail', id=coupon.id))

    return render_template('edit_usage.html', usage=usage, coupon=coupon)

@coupons_bp.route('/update_all_coupons')
@login_required
def update_all_coupons():
    # קבלת כל הקופונים הפעילים של המשתמש הנוכחי שאינם נוצלו עד הסוף
    active_coupons = Coupon.query.filter(
        Coupon.user_id == current_user.id,
        Coupon.status == 'פעיל'
    ).order_by(Coupon.date_added.desc()).all()

    if not active_coupons:
        flash('אין קופונים פעילים לעדכן.', 'info')
        return redirect(url_for('coupons.show_coupons'))

    updated_coupons = []
    failed_coupons = []

    for coupon in active_coupons:
        # בדיקת פורמט הקוד
        pattern = r'^(\d+)-(\d{4})$'
        match = re.match(pattern, coupon.code)
        if match:
            coupon_number_input = match.group(1)
            # קריאת הפונקציה לקבלת הנתונים
            df = get_coupon_data(coupon_number_input)
            if df is not None and 'שימוש' in df.columns:
                # עדכון השדה used_value עם סך 'שימוש'
                total_used = df['שימוש'].sum()
                if isinstance(total_used, (pd.Series, pd.DataFrame)):
                    # אם total_used הוא Series, קבל את הערך הבודד
                    total_used = total_used.iloc[0] if not total_used.empty else 0.0
                else:
                    total_used = float(total_used) if not pd.isna(total_used) else 0.0

                # עדכון הערך החדש
                coupon.used_value = total_used
                update_coupon_status(coupon)

                db.session.commit()

                # שמירת ה-DataFrame כקובץ xlsx
                data_directory = "multipass/input_html"
                os.makedirs(data_directory, exist_ok=True)
                xlsx_filename = f"coupon_{coupon.code}_{coupon.id}.xlsx"
                xlsx_path = os.path.join(data_directory, xlsx_filename)
                df.to_excel(xlsx_path, index=False)

                updated_coupons.append(coupon.code)
            else:
                failed_coupons.append(coupon.code)
        else:
            failed_coupons.append(coupon.code)

    # הצגת הודעות למשתמש
    if updated_coupons:
        flash('הקופונים הבאים עודכנו בהצלחה: ' + ', '.join(updated_coupons), 'success')
    if failed_coupons:
        flash('הקופונים הבאים לא עודכנו: ' + ', '.join(failed_coupons), 'danger')

    return redirect(url_for('coupons.show_coupons'))

@coupons_bp.route('/update_all_coupons/process', methods=['POST'])
@login_required
def update_all_coupons_route():
    # עדכון מרוכז לכל הקופונים הפעילים של המשתמש
    updated, failed = update_all_active_coupons(current_user.id)
    if updated:
        flash(f"הקופונים הבאים עודכנו: {', '.join(updated)}", "success")
    if failed:
        flash(f"הקופונים הבאים נכשלו: {', '.join(failed)}", "danger")
    return redirect(url_for('coupons.show_coupons'))

@coupons_bp.route('/get_tags')
@login_required
def get_tags():
    tags = [tag.name for tag in Tag.query.all()]
    return jsonify(tags)

@coupons_bp.route('/usage_order')
@login_required
def usage_order():
    valid_coupons = Coupon.query.filter(Coupon.status == 'פעיל', Coupon.user_id == current_user.id).order_by(
        (Coupon.used_value / Coupon.value).desc()
    ).all()

    expired_coupons = Coupon.query.filter(Coupon.status == 'פג תוקף', Coupon.user_id == current_user.id).order_by(
        (Coupon.used_value / Coupon.value).desc()
    ).all()

    return render_template('usage_order.html', valid_coupons=valid_coupons, expired_coupons=expired_coupons)

@coupons_bp.route('/export_excel')
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

    # שימוש בבלוק with לניהול ExcelWriter
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='קופונים')

    output.seek(0)

    return send_file(
        output,
        download_name='coupons.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@coupons_bp.route('/export_pdf')
@login_required
def export_pdf():
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.units import mm

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
    return send_file(output, download_name='coupons.pdf', as_attachment=True, mimetype='application/pdf')

@coupons_bp.route('/request_to_buy/<int:coupon_id>', methods=['POST'])
@login_required
def request_to_buy(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    if coupon.user_id == current_user.id:
        flash('אינך יכול לקנות את הקופון שלך.', 'warning')
        return redirect(url_for('coupons.marketplace'))

    if not coupon.is_available or not coupon.is_for_sale:
        flash('קופון זה אינו זמין למכירה.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    # יצירת טרנזקציה חדשה
    transaction = Transaction(
        coupon_id=coupon.id,
        buyer_id=current_user.id,
        seller_id=coupon.user_id,
        status='ממתין לאישור המוכר'
    )
    db.session.add(transaction)

    # סימון הקופון כלא זמין
    coupon.is_available = False

    # יצירת התראה למוכר
    notification = Notification(
        user_id=coupon.user_id,
        message=f"{current_user.first_name} {current_user.last_name} מבקש לקנות את הקופון שלך.",
        link=url_for('marketplace.my_transactions')
    )
    db.session.add(notification)
    db.session.commit()

    # עדכון זמן שליחת הבקשה מהקונה
    transaction.buyer_request_sent_at = datetime.utcnow()
    db.session.commit()

    # שליחת מייל למוכר
    seller = coupon.user
    buyer = current_user
    try:
        send_coupon_purchase_request_email(seller, buyer, coupon)
        flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
    except Exception as e:
        current_app.logger.error(f'שגיאה בשליחת מייל למוכר: {e}')
        flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

    return redirect(url_for('marketplace.my_transactions'))

@coupons_bp.route('/buy_coupon', methods=['POST'])
@login_required
def buy_coupon():
    """
    רוטה לטיפול בבקשת קנייה של קופון.
    """
    coupon_id = request.form.get('coupon_id', type=int)
    if not coupon_id:
        flash('קופון לא תקין.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    coupon = Coupon.query.get_or_404(coupon_id)

    # בדיקת אם המשתמש מנסה לקנות את הקופון שלו
    if coupon.user_id == current_user.id:
        flash('אינך יכול לקנות את הקופון שלך.', 'warning')
        return redirect(url_for('coupons.marketplace'))

    # בדיקת זמינות הקופון למכירה
    if not coupon.is_available or not coupon.is_for_sale:
        flash('קופון זה אינו זמין למכירה.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    # יצירת טרנזקציה חדשה
    transaction = Transaction(
        coupon_id=coupon.id,
        buyer_id=current_user.id,
        seller_id=coupon.user_id,
        status='ממתין לאישור המוכר'
    )
    db.session.add(transaction)

    # סימון הקופון כלא זמין
    coupon.is_available = False

    # יצירת התראה למוכר
    notification = Notification(
        user_id=coupon.user_id,
        message=f"{current_user.first_name} {current_user.last_name} מבקש לקנות את הקופון שלך.",
        link=url_for('marketplace.my_transactions')
    )
    db.session.add(notification)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating transaction: {e}")
        flash('אירעה שגיאה בעת יצירת העסקה. נסה שוב מאוחר יותר.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    # שליחת מייל למוכר באמצעות הפונקציה הנפרדת
    seller = coupon.user
    buyer = current_user
    try:
        send_coupon_purchase_request_email(seller, buyer, coupon)
        flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
    except Exception as e:
        current_app.logger.error(f'שגיאה בשליחת מייל למוכר: {e}')
        flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

    return redirect(url_for('marketplace.my_transactions'))

@coupons_bp.route('/coupon_request/<int:id>', methods=['GET', 'POST'])
@login_required
def coupon_request_detail(id):
    coupon_request = CouponRequest.query.get_or_404(id)

    # אם הבקשה כבר טופלה, חזרה לשוק הקופונים
    if coupon_request.fulfilled:
        flash('בקשת הקופון כבר טופלה.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    # יצירת טופס מחיקה
    delete_form = DeleteCouponRequestForm()

    # אם הטופס הוגש
    if delete_form.validate_on_submit():
        # מחיקת הבקשה
        db.session.delete(coupon_request)
        db.session.commit()
        flash('הבקשה נמחקה בהצלחה.', 'success')
        return redirect(url_for('coupons.marketplace'))  # חזרה לשוק הקופונים

    # שליפת פרטי המבקש
    requester = User.query.get(coupon_request.user_id)

    # שליפת החברה לפי ה-ID מהבקשה
    company = Company.query.get(coupon_request.company)

    # אם החברה לא נמצאה
    if not company:
        flash('החברה לא נמצאה.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    # יצירת מילון של מיפוי לוגו של החברה
    company_logo_mapping = {company.name.lower(): company.image_path for company in Company.query.all()}

    return render_template(
        'coupon_request_detail.html',
        coupon_request=coupon_request,
        requester=requester,
        company=company,  # העברת אובייקט החברה
        company_logo_mapping=company_logo_mapping,
        delete_form=delete_form  # שליחה של הטופס לתבנית
    )

@coupons_bp.route('/delete_coupon_request/<int:id>', methods=['POST'])
@login_required
def delete_coupon_request(id):
    coupon_request = CouponRequest.query.get_or_404(id)

    # בדיקת הרשאה: המשתמש יכול למחוק רק בקשות שהוא יצר
    if coupon_request.user_id != current_user.id:
        flash('אין לך הרשאה למחוק בקשה זו.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    try:
        db.session.delete(coupon_request)
        db.session.commit()
        flash('בקשת הקופון נמחקה בהצלחה.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting coupon request {id}: {e}")
        flash('אירעה שגיאה בעת מחיקת הבקשה.', 'danger')

    return redirect(url_for('coupons.marketplace'))


def complete_transaction(transaction):
    try:
        coupon = transaction.coupon
        # העברת הבעלות על הקופון לקונה
        coupon.user_id = transaction.buyer_id
        # הקופון כבר לא למכירה
        coupon.is_for_sale = False
        # הקופון כעת זמין שוב לשימוש
        coupon.is_available = True

        # עדכון סטטוס העסקה
        transaction.status = 'הושלם'

        # אפשר להוסיף התראות לשני הצדדים, רישום לוג, וכדומה
        notification_buyer = Notification(
            user_id=transaction.buyer_id,
            message='הקופון הועבר לחשבונך.',
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )
        notification_seller = Notification(
            user_id=transaction.seller_id,
            message='העסקה הושלמה והקופון הועבר לקונה.',
            link=url_for('marketplace.my_transactions')
        )

        db.session.add(notification_buyer)
        db.session.add(notification_seller)

        db.session.commit()
        flash('העסקה הושלמה בהצלחה והקופון הועבר לקונה!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error completing transaction {transaction.id}: {e}")
        flash('אירעה שגיאה בעת השלמת העסקה. נא לנסות שוב.', 'danger')

@coupons_bp.route('/approve_transaction/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def approve_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('marketplace.my_transactions'))

    form = ApproveTransactionForm()
    if form.validate_on_submit():
        transaction.seller_phone = form.seller_phone.data
        transaction.seller_approved = True
        transaction.coupon_code_entered = True
        db.session.commit()

        # לאחר שהמוכר אישר את העסקה, נשלח מייל לקונה
        seller = transaction.seller
        buyer = transaction.buyer
        coupon = transaction.coupon

        html_content = render_template('emails/seller_approved_transaction.html',
                                       seller=seller, buyer=buyer, coupon=coupon)

        try:
            send_email(
                sender_email='itayk93@gmail.com',
                sender_name='MaCoupon',
                recipient_email=buyer.email,
                recipient_name=f'{buyer.first_name} {buyer.last_name}',
                subject='המוכר אישר את העסקה',
                html_content=html_content
            )
            flash('אישרת את העסקה והמייל נשלח לקונה בהצלחה.', 'success')
        except Exception as e:
            current_app.logger.error(f"Error sending seller approved email: {e}")
            flash('העסקה אושרה, אך לא הצלחנו לשלוח מייל לקונה.', 'warning')

        return redirect(url_for('marketplace.my_transactions'))

    return render_template('approve_transaction.html', form=form, transaction=transaction)

@coupons_bp.route('/decline_transaction/<int:transaction_id>')
@login_required
def decline_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.seller_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('marketplace.my_transactions'))

    # החזרת הקופון לזמינות
    coupon = transaction.coupon
    coupon.is_available = True
    db.session.delete(transaction)
    db.session.commit()
    flash('דחית את העסקה.', 'info')
    return redirect(url_for('marketplace.my_transactions'))

@coupons_bp.route('/confirm_transaction/<int:transaction_id>')
@login_required
def confirm_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('marketplace.my_transactions'))

    transaction.status = 'הושלם'
    # העברת הבעלות על הקופון
    coupon = transaction.coupon
    coupon.user_id = current_user.id
    coupon.is_available = True
    db.session.commit()
    flash('אישרת את העסקה. הקופון הועבר לחשבונך.', 'success')
    return redirect(url_for('marketplace.my_transactions'))

@coupons_bp.route('/cancel_transaction/<int:transaction_id>')
@login_required
def cancel_transaction(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    if transaction.buyer_id != current_user.id:
        flash('אין לך הרשאה לפעולה זו.', 'danger')
        return redirect(url_for('marketplace.my_transactions'))

    # החזרת הקופון לזמינות
    coupon = transaction.coupon
    coupon.is_available = True
    db.session.delete(transaction)
    db.session.commit()
    flash('ביטלת את העסקה.', 'info')
    return redirect(url_for('marketplace.my_transactions'))

@coupons_bp.route('/send_coupon_expiration_warning/<int:coupon_id>')
def send_coupon_expiration_warning(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    user = coupon.user
    expiration_date = coupon.expiration
    coupon_detail_link = url_for('coupons.coupon_detail', id=coupon.id, _external=True)

    html_content = render_template('emails/coupon_expiration_warning.html', user=user, coupon=coupon,
                                   expiration_date=expiration_date, coupon_detail_link=coupon_detail_link)

    send_email(
        sender_email='itayk93@gmail.com',
        sender_name='MaCoupon',
        recipient_email=user.email,
        recipient_name=f'{user.first_name} {user.last_name}',
        subject='התראה על תפוגת תוקף קופון',
        html_content=html_content
    )

    flash('אימייל התראה על תפוגת תוקף קופון נשלח.', 'success')
    return redirect(url_for('coupons.show_coupons'))


@coupons_bp.route('/mark_coupon_as_used/<int:id>', methods=['POST'])
@login_required
def mark_coupon_as_used(id):
    coupon = Coupon.query.get_or_404(id)
    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    if not coupon.is_one_time:
        flash('הקופון אינו חד-פעמי.', 'warning')
        return redirect(url_for('coupons.coupon_detail', id=id))

    if coupon.status != 'פעיל':
        flash('הקופון כבר נוצל או פג תוקפו.', 'warning')
        return redirect(url_for('coupons.coupon_detail', id=id))

    # סימון כנוצל
    try:
        coupon.used_value = coupon.value
        update_coupon_status(coupon)
        usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=coupon.value,
            timestamp=datetime.now(timezone.utc),
            action='נוצל',
            details='הקופון סומן כנוצל על ידי המשתמש.'
        )
        db.session.add(usage)
        notification = Notification(
            user_id=coupon.user_id,
            message=f"הקופון {coupon.code} שלך ניצל.",
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )
        db.session.add(notification)
        db.session.commit()
        flash('הקופון סומן כנוצל בהצלחה.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking coupon as used: {e}")
        flash('אירעה שגיאה בעת סימון הקופון כנוצל.', 'danger')

    return redirect(url_for('coupons.coupon_detail', id=id))


@coupons_bp.route('/update_coupon_usage_from_multipass/<int:id>', methods=['GET', 'POST'])
@login_required
def update_coupon_usage_from_multipass(id):
    # נניח שרק למנהל יש הרשאה
    if current_user.email != 'itayk93@gmail.com':
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('coupons.coupon_detail', id=id))

    coupon = Coupon.query.get_or_404(id)
    if coupon.is_one_time:
        flash('הקופון הוא חד-פעמי ואין צורך בעדכון שימוש מ-Multipass.', 'warning')
        return redirect(url_for('coupons.coupon_detail', id=id))

    df = get_coupon_data(coupon.code)
    if df is None:
        flash('לא ניתן לעדכן את השימוש מ-Multipass.', 'danger')
        return redirect(url_for('coupons.coupon_detail', id=id))

    try:
        total_usage = df['שימוש'].sum()
        total_usage = float(total_usage)
        coupon.used_value = total_usage
        update_coupon_status(coupon)
        usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=total_usage,
            timestamp=datetime.now(timezone.utc),
            action='עדכון מ-Multipass',
            details='שימוש מעודכן מ-Multipass.'
        )
        db.session.add(usage)
        notification = Notification(
            user_id=coupon.user_id,
            message=f"השימוש בקופון {coupon.code} עודכן מ-Multipass.",
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )
        db.session.add(notification)
        db.session.commit()
        flash('השימוש עודכן בהצלחה מ-Multipass.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating coupon usage from Multipass: {e}")
        flash('אירעה שגיאה בעת עדכון השימוש.', 'danger')

    return redirect(url_for('coupons.coupon_detail', id=id))


@coupons_bp.route('/update_coupon_usage/<int:id>', methods=['GET', 'POST'])
@login_required
def update_coupon_usage_route(id):
    from forms import UpdateCouponUsageForm, MarkCouponAsFullyUsedForm
    coupon = Coupon.query.get_or_404(id)
    is_owner = (current_user.id == coupon.user_id)

    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    # אם הקופון חד-פעמי ואין צורך להוסיף כמות שימוש (מסמנים כנוצל)
    if coupon.is_one_time:
        coupon.status = 'נוצל'
        try:
            db.session.commit()
            flash('סטטוס הקופון עודכן בהצלחה ל"נוצל".', 'success')
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating one-time coupon status: {e}")
            flash('אירעה שגיאה בעת עדכון סטטוס הקופון.', 'danger')
        return redirect(url_for('coupons.coupon_detail', id=id))

    form = UpdateCouponUsageForm()
    mark_fully_used_form = MarkCouponAsFullyUsedForm()

    if form.validate_on_submit():
        new_used_amount = form.used_amount.data
        if new_used_amount < 0:
            flash('כמות השימוש חייבת להיות חיובית.', 'danger')
            return redirect(url_for('coupons.update_coupon_usage', id=id))

        if (coupon.used_value + new_used_amount) > coupon.value:
            flash('הכמות שהשתמשת בה גדולה מערך הקופון הנותר.', 'danger')
            return redirect(url_for('coupons.update_coupon_usage', id=id))

        try:
            update_coupon_usage(coupon, new_used_amount, details='שימוש ידני')
            flash('כמות השימוש עודכנה בהצלחה.', 'success')
            return redirect(url_for('coupons.coupon_detail', id=coupon.id))
        except Exception as e:
            flash('אירעה שגיאה בעת עדכון כמות השימוש.', 'danger')
            logger.error(f"Error updating coupon usage: {e}")

    return render_template('update_coupon_usage.html',
                           form=form,
                           coupon=coupon,
                           is_owner=is_owner,
                           mark_fully_used_form=mark_fully_used_form)


@coupons_bp.route('/update_all_active_coupons', methods=['POST'])
@login_required
def update_all_active_coupons():
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('index'))

    # תבנית לזהות את מבנה הקוד
    valid_coupon_pattern = re.compile(r'^\d{8,9}-\d{4}$')

    # שליפת כל הקופונים הפעילים שאינם חד-פעמיים
    active_coupons = Coupon.query.filter(
        Coupon.status == 'פעיל',
        Coupon.is_one_time == False
    ).all()

    updated_coupons = []
    failed_coupons = []

    for coupon in active_coupons:
        # בדיקת מבנה הקוד
        if not valid_coupon_pattern.match(coupon.code):
            failed_coupons.append(coupon.code)
            continue

        print(valid_coupon_pattern.match(coupon.code))
        try:
            print(f"Updating {coupon.code}")
            # קריאה ל-Multipass לקבלת נתוני הקופון
            df = get_coupon_data(coupon.code)
            if df is not None:
                # סך כל השימוש בקופון
                total_usage = df['usage_amount'].sum()
                total_usage = float(total_usage)  # הבטחת המרה למספר

                # עדכון הערכים של הקופון
                coupon.used_value = total_usage
                update_coupon_status(coupon)

                # הוספת רשומת שימוש
                usage = CouponUsage(
                    coupon_id=coupon.id,
                    used_amount=total_usage,
                    timestamp=datetime.now(timezone.utc),
                    action='עדכון מרוכז',
                    details='עדכון מרוכז של שימוש בקופון מ-Multipass'
                )
                db.session.add(usage)

                # יצירת התראה למשתמש
                notification = Notification(
                    user_id=coupon.user_id,
                    message=f"השימוש בקופון {coupon.code} עודכן מ-Multipass.",
                    link=url_for('coupons.coupon_detail', id=coupon.id)
                )
                db.session.add(notification)

                updated_coupons.append(coupon.code)
            else:
                failed_coupons.append(coupon.code)

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error updating coupon {coupon.code}: {e}")
            failed_coupons.append(coupon.code)

    # שמירת השינויים
    db.session.commit()

    # הצגת הודעות למשתמש
    if updated_coupons:
        flash(f'הקופונים הבאים עודכנו בהצלחה: {", ".join(updated_coupons)}', 'success')
    if failed_coupons:
        flash(f'הקופונים הבאים לא עודכנו: {", ".join(failed_coupons)}', 'danger')

    return redirect(url_for('index'))
