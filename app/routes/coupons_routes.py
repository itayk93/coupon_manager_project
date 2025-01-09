# app/routes/coupons_routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, send_file
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text
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
from app.helpers import get_geo_location, get_public_ip
import traceback
import traceback

logger = logging.getLogger(__name__)

coupons_bp = Blueprint('coupons', __name__)
from sqlalchemy.sql import text

from datetime import datetime
from flask import request, current_app
from app.helpers import get_geo_location
from flask_login import current_user
from sqlalchemy.sql import text
from app.extensions import db

from app.helpers import get_geo_location, get_public_ip

def log_user_activity(action, coupon_id=None):
    try:
        ip_address = get_public_ip() or '0.0.0.0'
        geo_data = get_geo_location(ip_address)

        activity = {
            "user_id": current_user.id if current_user and current_user.is_authenticated else None,
            "coupon_id": coupon_id,
            "timestamp": datetime.utcnow(),
            "action": action,
            "device": request.headers.get('User-Agent', '')[:50],
            "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
            "ip_address": ip_address[:45] if ip_address else None if ip_address else None,
            "city": geo_data.get("city"),
            "region": geo_data.get("region"),
            "country": geo_data.get("country"),
        }

        db.session.execute(
            text("""
                INSERT INTO user_activities
                (user_id, coupon_id, timestamp, action, device, browser, ip_address, city, region, country)
                VALUES
                (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :city, :region, :country)
            """),
            activity
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging activity [{action}]: {e}")

@coupons_bp.route('/sell_coupon', methods=['GET', 'POST'])
@login_required
def sell_coupon():
    """
    מסך/נקודת קצה למכירת קופון. מאפשר הזנת פרטי הקופון,
    מחשב אוטומטית את אחוז ההנחה,
    ומוסיף תגית באופן אוטומטי לפי שם החברה (אם נמצאה).
    אין אפשרות ידנית לבחירת תגית.
    """
    # -- activity log snippet --
    log_user_activity("sell_coupon_view", None)

    form = SellCouponForm()

    # מביאים רק חברות (אין צורך בשליפת תגיות עבור בחירה ידנית)
    companies = Company.query.all()

    # מכינים רשימת אפשרויות לבחירת חברה
    company_choices = [('', 'בחר חברה')]
    company_choices += [(str(company.id), company.name) for company in companies]
    company_choices.append(('other', 'אחר'))
    form.company_select.choices = company_choices

    if form.validate_on_submit():
        # איסוף נתונים מהטופס
        expiration = form.expiration.data
        purpose = form.purpose.data.strip() if form.is_one_time.data and form.purpose.data else None

        try:
            value = float(form.value.data) if form.value.data else 0.0
        except:
            value = 0.0

        try:
            cost = float(form.cost.data) if form.cost.data else 0.0
        except:
            cost = 0.0

        # חישוב אחוז ההנחה (ערך לוגי לשימוש פנימי / תצוגה)
        if value > 0:
            discount_percentage = ((value - cost) / value) * 100
        else:
            discount_percentage = 0.0

        # טיפול בבחירת חברה
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

        # יצירת אובייקט קופון (ללא discount_percentage, כי לא קיים בעמודות המודל)
        new_coupon = Coupon(
            code=form.code.data.strip(),
            value=value,
            cost=cost,
            company=company.name,
            description=form.description.data.strip() if form.description.data else '',
            expiration=expiration,
            user_id=current_user.id,
            is_available=True,
            is_for_sale=True,
            is_one_time=form.is_one_time.data,
            purpose=purpose
            # אין discount_percentage כי הוא לא בעמודות Coupon
        )

        # ------------------------------------------------------------
        # זיהוי תגית אוטומטי לפי שם החברה
        # ------------------------------------------------------------
        chosen_company_name = company.name
        current_app.logger.info(f"[DEBUG] sell_coupon => chosen_company_name = '{chosen_company_name}'")

        found_tag = get_most_common_tag_for_company(chosen_company_name)
        current_app.logger.info(f"[DEBUG] sell_coupon => auto found_tag = '{found_tag}'")

        # אם נמצאה תגית תואמת, מוסיפים אותה
        if found_tag:
            new_coupon.tags.append(found_tag)

        # שמירה ב־DB
        db.session.add(new_coupon)
        try:
            db.session.commit()

            # -- activity log snippet --
            try:
                new_activity = {
                    "user_id": current_user.id,
                    "coupon_id": new_coupon.id,
                    "timestamp": datetime.utcnow(),
                    "action": "sell_coupon_created",
                    "device": request.headers.get('User-Agent', '')[:50],
                    "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                    "ip_address": ip_address[:45] if ip_address else None,
                    "geo_location": get_geo_location(ip_address)[:100]
                }
                db.session.execute(
                    text("""
                        INSERT INTO user_activities
                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                        VALUES
                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                    """),
                    new_activity
                )
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error logging activity [sell_coupon_created]: {e}")
            # -- end snippet --

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
        # אם הגענו ב־POST ויש שגיאות, מדפיסים log
        if request.method == 'POST':
            for field, errors in form.errors.items():
                for error in errors:
                    current_app.logger.error(f"Error in {field}: {error}")
            flash('יש לתקן את השגיאות בטופס.', 'danger')

    return render_template(
        'sell_coupon.html',
        form=form,
        companies=companies
    )


@coupons_bp.route('/coupons')
@login_required
def show_coupons():
    log_user_activity("show_coupons", None)

    coupons = Coupon.query.options(joinedload(Coupon.tags)).filter_by(user_id=current_user.id, is_for_sale=False).all()
    for coupon in coupons:
        update_coupon_status(coupon)
    db.session.commit()

    companies = Company.query.all()
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}

    active_coupons = [coupon for coupon in coupons if coupon.status == 'פעיל' and not coupon.is_one_time]
    active_one_time_coupons = [coupon for coupon in coupons if coupon.status == 'פעיל' and coupon.is_one_time]

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
    # -- activity log snippet --
    log_user_activity("upload_coupons_view", None)

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

        # -- activity log snippet --
        try:
            new_activity = {
                "user_id": current_user.id,
                "coupon_id": None,
                "timestamp": datetime.utcnow(),
                "action": "upload_coupons_submit",
                "device": request.headers.get('User-Agent', '')[:50],
                "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": get_geo_location(ip_address)[:100]
            }
            db.session.execute(
                text("""
                    INSERT INTO user_activities
                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                    VALUES
                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                """),
                new_activity
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error logging activity [upload_coupons_submit]: {e}")
        # -- end snippet --

        return redirect(url_for('coupons.show_coupons'))

    return render_template('upload_coupons.html', form=form)


@coupons_bp.route('/add_coupons_bulk', methods=['GET', 'POST'])
@login_required
def add_coupons_bulk():
    # -- activity log snippet --
    log_user_activity("add_coupons_bulk_view", None)

    form = AddCouponsBulkForm()
    companies = Company.query.all()
    tags = Tag.query.all()

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

            if new_coupons_data:
                df_new_coupons = pd.DataFrame(new_coupons_data)
                export_folder = 'exports'
                os.makedirs(export_folder, exist_ok=True)
                export_filename = f"new_coupons_{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                export_path = os.path.join(export_folder, export_filename)

                df_new_coupons.to_excel(export_path, index=False)
                current_app.logger.info(f"Exported new coupons to {export_path}")

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

        # -- activity log snippet --
        try:
            new_activity = {
                "user_id": current_user.id,
                "coupon_id": None,
                "timestamp": datetime.utcnow(),
                "action": "add_coupons_bulk_submit",
                "device": request.headers.get('User-Agent', '')[:50],
                "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": get_geo_location(ip_address)[:100]
            }
            db.session.execute(
                text("""
                    INSERT INTO user_activities
                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                    VALUES
                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                """),
                new_activity
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error logging activity [add_coupons_bulk_submit]: {e}")
        # -- end snippet --

    else:
        if form.is_submitted():
            current_app.logger.warning(f"Form validation failed: {form.errors}")

    return render_template('add_coupons.html', form=form, companies=companies, tags=tags)


def get_most_common_tag_for_company(company_name):
    results = db.session.query(Tag, func.count(Tag.id).label('tag_count')) \
        .join(coupon_tags, Tag.id == coupon_tags.c.tag_id) \
        .join(Coupon, Coupon.id == coupon_tags.c.coupon_id) \
        .filter(func.lower(Coupon.company) == func.lower(company_name)) \
        .group_by(Tag.id) \
        .order_by(func.count(Tag.id).desc(), Tag.id.asc()) \
        .all()
    if results:
        return results[0][0]
    else:
        return None


def get_most_common_tag_for_company(company_name):
    results = db.session.query(Tag, func.count(Tag.id).label('tag_count')) \
        .join(coupon_tags, Tag.id == coupon_tags.c.tag_id) \
        .join(Coupon, Coupon.id == coupon_tags.c.coupon_id) \
        .filter(func.lower(Coupon.company) == func.lower(company_name)) \
        .group_by(Tag.id) \
        .order_by(func.count(Tag.id).desc(), Tag.id.asc()) \
        .all()
    if results:
        current_app.logger.info(f"[DEBUG] get_most_common_tag_for_company({company_name}) => {results}")
        return results[0][0]
    else:
        return None


@coupons_bp.route('/add_coupon', methods=['GET', 'POST'])
@login_required
def add_coupon():
    # -- activity log snippet --
    log_user_activity("add_coupon_view", None)

    try:
        manual = request.args.get('manual', 'false').lower() == 'true'
        sms_form = SMSInputForm()
        coupon_form = CouponForm()
        show_coupon_form = manual

        companies = Company.query.all()
        tags = Tag.query.all()

        companies_list = [c.name for c in companies]

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

        if sms_form.validate_on_submit() and 'sms_text' in request.form:
            sms_text = sms_form.sms_text.data
            extracted_data_df, pricing_df = extract_coupon_detail_sms(sms_text, companies_list)
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

                if current_user.slots_automatic_coupons > 0:
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                else:
                    flash('אין לך מספיק סלוטים להוספת קופונים.', 'danger')
                    return redirect(url_for('coupons.add_coupon'))

                current_app.logger.info(f"[DEBUG] Sending to get_most_common_tag_for_company => '{chosen_company_name}'")
                found_tag = get_most_common_tag_for_company(chosen_company_name)
                current_app.logger.info(f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'")
                if found_tag:
                    tag_id = found_tag.id
                    tag_name = found_tag.name
                    current_app.logger.info(
                        f"[DEBUG] Received tag => '{tag_name}' (ID: {tag_id}) for company '{chosen_company_name}'")
                else:
                    current_app.logger.info(f"[DEBUG] No tag found for company '{chosen_company_name}'")

                if found_tag:
                    coupon_form.tag_id.data = str(found_tag.id)
                    coupon_form.other_tag.data = ''

                # -- activity log add_coupon_via_sms --
                log_user_activity("add_coupon_via_sms", None)

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

        if request.method == 'POST':
            if 'upload_image' in request.form and coupon_form.upload_image.data:
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

                            coupon_form.code.data = coupon_df.loc[0, 'קוד קופון']
                            coupon_form.cost.data = coupon_df.loc[0, 'עלות'] if pd.notnull(coupon_df.loc[0, 'עלות']) else 0
                            coupon_form.value.data = coupon_df.loc[0, 'ערך מקורי'] if pd.notnull(coupon_df.loc[0, 'ערך מקורי']) else 0
                            coupon_form.discount_percentage.data = coupon_df.loc[0, 'אחוז הנחה'] if pd.notnull(coupon_df.loc[0, 'אחוז הנחה']) else 0
                            try:
                                expiration_val = coupon_df.loc[0, 'תאריך תפוגה']
                                if pd.notnull(expiration_val):
                                    coupon_form.expiration.data = pd.to_datetime(expiration_val).date()
                            except Exception as e:
                                current_app.logger.error(f"[ERROR] parsing expiration date from image: {e}")

                            coupon_form.description.data = coupon_df.loc[0, 'תיאור'] if pd.notnull(coupon_df.loc[0, 'תיאור']) else ''
                            coupon_form.is_one_time.data = False
                            coupon_form.purpose.data = ''

                            if current_user.slots_automatic_coupons > 0:
                                current_user.slots_automatic_coupons -= 1
                                db.session.commit()
                            else:
                                flash('אין לך מספיק סלוטים להוספת קופונים.', 'danger')
                                return redirect(url_for('coupons.add_coupon'))

                            current_app.logger.info(f"[DEBUG] Sending to get_most_common_tag_for_company => '{chosen_company_name}'")
                            found_tag = get_most_common_tag_for_company(chosen_company_name)
                            current_app.logger.info(f"[DEBUG] Received tag => '{found_tag}' for company '{chosen_company_name}'")
                            if found_tag:
                                tag_id = found_tag.id
                                tag_name = found_tag.name
                                current_app.logger.info(
                                    f"[DEBUG] Received tag => '{tag_name}' (ID: {tag_id}) for company '{chosen_company_name}'")
                            else:
                                current_app.logger.info(f"[DEBUG] No tag found for company '{chosen_company_name}'")

                            if found_tag:
                                coupon_form.tag_id.data = str(found_tag.id)
                                coupon_form.other_tag.data = ''

                            # -- activity log snippet --
                            try:
                                new_activity = {
                                    "user_id": current_user.id,
                                    "coupon_id": None,
                                    "timestamp": datetime.utcnow(),
                                    "action": "add_coupon_via_image_upload",
                                    "device": request.headers.get('User-Agent', '')[:50],
                                    "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                                    "ip_address": ip_address[:45] if ip_address else None,
                                    "geo_location": get_geo_location(ip_address)[:100]
                                }
                                db.session.execute(
                                    text("""
                                        INSERT INTO user_activities
                                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                                        VALUES
                                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                                    """),
                                    new_activity
                                )
                                db.session.commit()
                            except Exception as e:
                                db.session.rollback()
                                current_app.logger.error(f"Error logging activity [add_coupon_via_image_upload]: {e}")
                            # -- end snippet --

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

            elif 'submit_coupon' in request.form and coupon_form.submit_coupon.data:
                current_app.logger.info("[DEBUG] Manual flow - user pressed submit_coupon")
                if coupon_form.validate_on_submit():
                    code = coupon_form.code.data.strip()
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

                    if selected_company_id == 'other':
                        if not other_company_name:
                            flash('יש להזין שם חברה חדשה.', 'danger')
                            return redirect(url_for('coupons.add_coupon', manual='true'))
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

                    if current_user.slots_automatic_coupons <= 0:
                        flash('אין לך מספיק סלוטים להוספת קופונים.', 'danger')
                        return redirect(url_for('coupons.add_coupon', manual='true'))

                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()

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

                    chosen_company_name = company.name
                    current_app.logger.info(f"[DEBUG] Manual flow => chosen_company_name = '{chosen_company_name}'")
                    found_tag = get_most_common_tag_for_company(chosen_company_name)
                    current_app.logger.info(f"[DEBUG] Manual flow => auto found_tag = '{found_tag}'")

                    if found_tag:
                        new_coupon.tags.append(found_tag)

                    db.session.add(new_coupon)

                    try:
                        db.session.commit()

                        # -- activity log snippet --
                        try:
                            new_activity = {
                                "user_id": current_user.id,
                                "coupon_id": new_coupon.id,
                                "timestamp": datetime.utcnow(),
                                "action": "add_coupon_manual_submit",
                                "device": request.headers.get('User-Agent', '')[:50],
                                "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                                "ip_address": ip_address[:45] if ip_address else None,
                                "geo_location": get_geo_location(ip_address)[:100]
                            }
                            db.session.execute(
                                text("""
                                    INSERT INTO user_activities
                                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                                    VALUES
                                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                                """),
                                new_activity
                            )
                            db.session.commit()
                        except Exception as e:
                            db.session.rollback()
                            current_app.logger.error(f"Error logging activity [add_coupon_manual_submit]: {e}")
                        # -- end snippet --

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
    log_user_activity("add_coupon_with_image_html_view", None)

    form = CouponForm()
    if request.method == 'POST':
        # שלב א: אם העלו תמונה
        image_file = request.files.get('coupon_image')
        if image_file and image_file.filename != '':
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            image_path = os.path.join(upload_folder, image_file.filename)
            image_file.save(image_path)

            try:
                coupon_df, pricing_df = extract_coupon_detail_image_proccess(
                    client_id=os.getenv('IMGUR_CLIENT_ID'),
                    image_path=image_path,
                    companies_list=[company.name for company in Company.query.all()]
                )
            except Exception as e:
                current_app.logger.error(f"Error extracting coupon from image: {e}")
                flash(f"אירעה שגיאה בעת עיבוד התמונה: {e}", "danger")
                return render_template('add_coupon_with_image.html', form=form)

            if not coupon_df.empty:
                # ממלאים את השדות לפי מה שהוחזר מעיבוד התמונה
                form.company_id.data = coupon_df.loc[0, 'חברה']
                form.code.data = coupon_df.loc[0, 'קוד קופון']
                form.cost.data = coupon_df.loc[0, 'עלות']
                form.value.data = coupon_df.loc[0, 'ערך מקורי']
                form.discount_percentage.data = coupon_df.loc[0, 'אחוז הנחה']

                try:
                    form.expiration.data = pd.to_datetime(coupon_df.loc[0, 'תאריך תפוגה']).date()
                except:
                    form.expiration.data = None

                form.description.data = coupon_df.loc[0, 'תיאור']
                flash("הטופס מולא בהצלחה. אנא בדוק וערוך אם נדרש.", "success")
            else:
                flash("לא ניתן היה לחלץ פרטי קופון מהתמונה.", "danger")

        # שלב ב: אם המשתמש שלח את הטופס הסופי (למשל כפתור שנקרא 'submit_coupon') => נשמור את הקופון
        elif 'submit_coupon' in request.form and form.validate_on_submit():
            # שלבי יצירת הקופון בדיוק כמו ב-`add_coupon_with_image`,
            # כולל מציאת החברה, שמירה במסד, ואז צירוף התגית (get_most_common_tag_for_company).
            selected_company_id = form.company_id.data
            other_company_name = (form.other_company.data or '').strip()

            if selected_company_id == 'other':
                # טיפול בחברה 'אחר'
                if not other_company_name:
                    flash('יש להזין שם חברה חדשה.', 'danger')
                    return redirect(url_for('coupons.add_coupon_with_image_html'))
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
                        return redirect(url_for('coupons.add_coupon_with_image_html'))
                except (ValueError, TypeError):
                    flash('חברה נבחרה אינה תקפה.', 'danger')
                    return redirect(url_for('coupons.add_coupon_with_image_html'))

            code = form.code.data.strip()
            try:
                value = float(form.value.data) if form.value.data else 0
            except ValueError:
                flash('ערך הקופון חייב להיות מספר.', 'danger')
                return render_template('add_coupon_with_image.html', form=form)

            try:
                cost = float(form.cost.data) if form.cost.data else 0
            except ValueError:
                flash('מחיר הקופון חייב להיות מספר.', 'danger')
                return render_template('add_coupon_with_image.html', form=form)

            description = form.description.data.strip() if form.description.data else ''
            expiration = form.expiration.data or None
            is_one_time = form.is_one_time.data
            purpose = form.purpose.data.strip() if is_one_time and form.purpose.data else None

            # בדיקת ייחודיות הקוד
            if Coupon.query.filter_by(code=code).first():
                flash('קוד קופון זה כבר קיים. אנא בחר קוד אחר.', 'danger')
                return redirect(url_for('coupons.add_coupon_with_image_html'))

            # בדיקת תאריך תפוגה
            current_date = datetime.utcnow().date()
            if expiration and expiration < current_date:
                flash('תאריך התפוגה של הקופון כבר עבר. אנא בחר תאריך תקין.', 'danger')
                return render_template('add_coupon_with_image.html', form=form)

            new_coupon = Coupon(
                code=code,
                value=value,
                cost=cost,
                company=company.name,
                description=description,
                expiration=expiration,
                user_id=current_user.id,
                is_one_time=is_one_time,
                purpose=purpose,
                used_value=0.0,
                status='פעיל'
            )

            # שלב צירוף התגית הנפוצה (כמו ב-manual flow)
            chosen_company_name = company.name
            found_tag = get_most_common_tag_for_company(chosen_company_name)
            if found_tag:
                new_coupon.tags.append(found_tag)

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

    return render_template('add_coupon_with_image.html', form=form)


@coupons_bp.route('/add_coupon_with_image', methods=['GET', 'POST'])
@login_required
def add_coupon_with_image():
    log_user_activity("add_coupon_with_image_view", None)

    upload_image_form = UploadImageForm()
    coupon_form = CouponForm()
    show_coupon_form = False

    # שליפת רשימת החברות מהדאטהבייס
    companies = Company.query.all()

    # הגדרת האפשרויות בשדה company_id בלבד (בלי תגיות)
    coupon_form.company_id.choices = [('', 'בחר')] + [(str(company.id), company.name) for company in companies] + [('other', 'אחר')]

    # אם העלו תמונה באמצעות הטופס העלאת תמונה
    if upload_image_form.validate_on_submit() and upload_image_form.submit_upload_image.data:
        image_file = upload_image_form.coupon_image.data
        if image_file:
            filename = secure_filename(image_file.filename)
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            image_path = os.path.join(upload_folder, filename)
            image_file.save(image_path)

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

                # חיפוש החברה המתאימה ביותר (Fuzzy Matching)
                best_match_ratio = 0
                best_company = None
                for comp in companies:
                    ratio = fuzz.token_set_ratio(company_name, comp.name)
                    if ratio > best_match_ratio:
                        best_match_ratio = ratio
                        best_company = comp

                # אם נמצא match מספיק טוב לחברה
                if best_company and best_match_ratio >= 90:
                    coupon_form.company_id.data = str(best_company.id)
                    coupon_form.other_company.data = ''
                else:
                    # אחרת נרשום אותה כ"אחר" ונמלא את שדה חברה חדשה
                    coupon_form.company_id.data = 'other'
                    coupon_form.other_company.data = company_name

                # מילוי יתר השדות
                try:
                    coupon_form.cost.data = float(coupon_data.get('עלות', 0))
                except ValueError:
                    coupon_form.cost.data = 0.0
                    flash('מחיר הקופון לא היה ניתן להמרה למספר, הוגדר כ-0.', 'warning')

                try:
                    coupon_form.value.data = float(coupon_data.get('ערך מקורי', 0))
                except ValueError:
                    coupon_form.value.data = 0.0
                    flash('ערך הקופון לא היה ניתן להמרה למספר, הוגדר כ-0.', 'warning')

                if 'אחוז הנחה' in coupon_df.columns:
                    try:
                        coupon_form.discount_percentage.data = float(coupon_data.get('אחוז הנחה', 0))
                    except ValueError:
                        coupon_form.discount_percentage.data = 0.0
                        flash('אחוז הנחה לא היה ניתן להמרה למספר, הוגדר כ-0.', 'warning')
                else:
                    coupon_form.discount_percentage.data = 0

                expiration_str = coupon_data.get('תאריך תפוגה')
                if expiration_str:
                    try:
                        coupon_form.expiration.data = datetime.strptime(expiration_str, '%Y-%m-%d').date()
                    except ValueError:
                        try:
                            coupon_form.expiration.data = datetime.strptime(expiration_str, '%d/%m/%Y').date()
                        except ValueError:
                            coupon_form.expiration.data = None
                            flash('תאריך התפוגה לא בפורמט תקין.', 'warning')
                else:
                    coupon_form.expiration.data = None

                coupon_form.code.data = coupon_data.get('קוד קופון')
                coupon_form.description.data = coupon_data.get('תיאור', '')
                coupon_form.is_one_time.data = bool(coupon_data.get('קוד לשימוש חד פעמי'))
                coupon_form.purpose.data = coupon_data.get('מטרת הקופון', '') if coupon_form.is_one_time.data else ''

                # הפחתת סלוטים (לדוגמה, אם במערכת יש הגבלה על מספר הקופונים האוטומטיים)
                if current_user.slots_automatic_coupons > 0:
                    current_user.slots_automatic_coupons -= 1
                    db.session.commit()
                else:
                    flash('אין לך מספיק סלוטים להוספת קופונים.', 'danger')
                    return redirect(url_for('coupons.add_coupon_with_image'))

                show_coupon_form = True
                flash("הטופס מולא בהצלחה. אנא בדוק וערוך אם נדרש.", "success")
            else:
                error_reason = "לא נמצאו נתונים בתמונה."
                if not pricing_df.empty and 'error_message' in pricing_df.columns:
                    error_reason = pricing_df.iloc[0]['error_message']
                flash(f"לא ניתן היה לחלץ פרטי קופון מהתמונה: {error_reason}", "danger")

    # אם שלחו את הטופס הסופי להוספת הקופון
    elif coupon_form.validate_on_submit() and coupon_form.submit_coupon.data:
        selected_company_id = coupon_form.company_id.data
        other_company_name = coupon_form.other_company.data.strip() if coupon_form.other_company.data else ''

        # טיפול בחברה (יצירה או שליפה)
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

        # בדיקה שהקוד לא קיים כבר
        if Coupon.query.filter_by(code=code).first():
            flash('קוד קופון זה כבר קיים. אנא בחר קוד אחר.', 'danger')
            return redirect(url_for('coupons.add_coupon_with_image'))

        # בדיקת תאריך תפוגה
        current_date = datetime.utcnow().date()
        if expiration and expiration < current_date:
            flash('תאריך התפוגה של הקופון כבר עבר. אנא בחר תאריך תקין.', 'danger')
            show_coupon_form = True
            return render_template(
                'add_coupon_with_image.html',
                coupon_form=coupon_form,
                upload_image_form=upload_image_form,
                show_coupon_form=show_coupon_form,
                form=coupon_form
            )

        new_coupon = Coupon(
            code=code,
            value=value,
            cost=cost,
            company=company.name,
            description=description,
            expiration=expiration,
            user_id=current_user.id,
            is_one_time=is_one_time,
            purpose=purpose,
            used_value=0.0,
            status='פעיל'
        )

        # *** כאן מוסיפים את התגית הנפוצה (כמו ב-manual flow) ***
        chosen_company_name = company.name
        found_tag = get_most_common_tag_for_company(chosen_company_name)
        if found_tag:
            new_coupon.tags.append(found_tag)

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
    # -- activity log snippet --
    log_user_activity("add_coupon_manual_view", None)

    coupon_form = CouponForm()
    if coupon_form.validate_on_submit():
        pass
    return render_template('add_coupon.html', coupon_form=coupon_form, show_coupon_form=True)


def convert_date_format(date_input):
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

    # -- activity log snippet --
    log_user_activity("edit_coupon_view", coupon.id)

    if coupon.user_id != current_user.id:
        flash('אינך מורשה לערוך קופון זה.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    form = EditCouponForm(obj=coupon)

    if form.validate_on_submit():
        try:
            old_value = coupon.value
            coupon.company = form.company.data.strip()
            coupon.code = form.code.data.strip()
            coupon.value = float(form.value.data)
            coupon.cost = float(form.cost.data)
            coupon.description = form.description.data or ''
            coupon.is_one_time = form.is_one_time.data
            coupon.purpose = form.purpose.data.strip() if form.is_one_time.data else None
            coupon.expiration = form.expiration.data if form.expiration.data else None

            if form.tags.data:
                if isinstance(form.tags.data, str) and form.tags.data:
                    tag_names = [tag.strip() for tag in form.tags.data.split(',') if tag.strip()]
                elif isinstance(form.tags.data, list):
                    tag_names = [tag.strip() for tag in form.tags.data if isinstance(tag, str) and tag.strip()]
                else:
                    tag_names = []
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

            if coupon.value != old_value:
                initial_transaction = CouponTransaction.query.filter_by(
                    coupon_id=coupon.id,
                    source='User',
                    reference_number='Initial'
                ).first()
                if initial_transaction:
                    initial_transaction.recharge_amount = coupon.value
                else:
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

            # -- activity log snippet --
            try:
                new_activity = {
                    "user_id": current_user.id,
                    "coupon_id": coupon.id,
                    "timestamp": datetime.utcnow(),
                    "action": "edit_coupon_submit",
                    "device": request.headers.get('User-Agent', '')[:50],
                    "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                    "ip_address": ip_address[:45] if ip_address else None,
                    "geo_location": get_geo_location(ip_address)[:100]
                }
                db.session.execute(
                    text("""
                        INSERT INTO user_activities
                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                        VALUES
                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                    """),
                    new_activity
                )
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error logging activity [edit_coupon_submit]: {e}")
            # -- end snippet --

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

    existing_tags = ', '.join([tag.name for tag in coupon.tags])
    top_tags = Tag.query.order_by(Tag.count.desc()).limit(3).all()
    top_tags = [tag.name for tag in top_tags]

    return render_template('edit_coupon.html', form=form, coupon=coupon, existing_tags=existing_tags, top_tags=top_tags)


@coupons_bp.route('/delete_coupons', methods=['GET', 'POST'])
@login_required
def select_coupons_to_delete():
    # -- activity log snippet --
    log_user_activity("select_coupons_to_delete_view", None)

    form = DeleteCouponsForm()
    coupons = Coupon.query.filter_by(user_id=current_user.id).order_by(Coupon.date_added.desc()).all()
    form.coupon_ids.choices = [(coupon.id, f"{coupon.company} - {coupon.code}") for coupon in coupons]

    if form.validate_on_submit():
        selected_ids = form.coupon_ids.data
        if selected_ids:
            Coupon.query.filter(Coupon.id.in_(selected_ids)).delete(synchronize_session=False)
            db.session.commit()

            try:
                new_activity = {
                    "user_id": current_user.id,
                    "coupon_id": None,
                    "timestamp": datetime.utcnow(),
                    "action": f"deleted_coupons_{selected_ids}",
                    "device": request.headers.get('User-Agent', '')[:50],
                    "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                    "ip_address": ip_address[:45] if ip_address else None,
                    "geo_location": get_geo_location(ip_address)[:100]
                }
                db.session.execute(
                    text("""
                        INSERT INTO user_activities
                            (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                        VALUES
                            (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                    """),
                    new_activity
                )
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error logging activity [deleted_coupons]: {e}")

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
    update_form = UpdateCouponUsageForm()

    log_user_activity("view_coupon", coupon.id)

    transactions = CouponTransaction.query.filter_by(coupon_id=coupon.id).order_by(
        CouponTransaction.transaction_date.asc()).all()

    companies = Company.query.all()
    company_logo_mapping = {company.name.lower(): company.image_path for company in companies}
    company_logo = company_logo_mapping.get(coupon.company.lower(), 'default_logo.png')

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






@coupons_bp.route('/delete_coupon/<int:id>', methods=['POST'])
@login_required
def delete_coupon(id):
    # -- activity log snippet --
    log_user_activity("delete_coupon_attempt", id)

    form = DeleteCouponForm()
    if form.validate_on_submit():
        coupon = Coupon.query.get_or_404(id)
        if coupon.user_id != current_user.id:
            flash('אינך מורשה למחוק קופון זה.', 'danger')
            return redirect(url_for('coupons.show_coupons'))

        transactions = Transaction.query.filter_by(coupon_id=coupon.id).all()
        if transactions:
            return redirect(url_for('coupons.confirm_delete_coupon', id=id))
        else:
            for tag in coupon.tags:
                tag.count -= 1
                if tag.count < 0:
                    tag.count = 0

            data_directory = "multipass/input_html"
            xlsx_filename = f"coupon_{coupon.code}_{coupon.id}.xlsx"
            xlsx_path = os.path.join(data_directory, xlsx_filename)
            if os.path.exists(xlsx_path):
                os.remove(xlsx_path)

            db.session.delete(coupon)
            try:
                db.session.commit()

                try:
                    success_activity = {
                        "user_id": current_user.id,
                        "coupon_id": id,
                        "timestamp": datetime.utcnow(),
                        "action": "delete_coupon_success",
                        "device": request.headers.get('User-Agent', '')[:50],
                        "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                        "ip_address": ip_address[:45] if ip_address else None,
                        "geo_location": get_geo_location(ip_address)[:100]
                    }
                    db.session.execute(
                        text("""
                            INSERT INTO user_activities 
                                (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                            VALUES 
                                (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                        """),
                        success_activity
                    )
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Error logging activity [delete_coupon_success]: {e}")

                flash(f'קופון "{coupon.code}" נמחק בהצלחה!', 'success')
                return redirect(url_for('coupons.show_coupons'))
            except:
                db.session.rollback()
                flash('שגיאה בעת מחיקת הקופון.', 'danger')
                return redirect(url_for('coupons.show_coupons'))
    else:
        flash('שגיאה במחיקת הקופון. נסה שוב.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

@coupons_bp.route('/confirm_delete_coupon/<int:id>', methods=['GET', 'POST'])
@login_required
def confirm_delete_coupon(id):
    coupon = Coupon.query.get_or_404(id)

    # -- activity log snippet --
    log_user_activity("confirm_delete_coupon_view", coupon.id)

    if coupon.user_id != current_user.id:
        flash('אינך מורשה למחוק קופון זה.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    form = ConfirmDeleteForm()
    if form.validate_on_submit():
        if form.submit.data:
            try:
                transactions = Transaction.query.filter_by(coupon_id=coupon.id).all()
                for transaction in transactions:
                    db.session.delete(transaction)

                for tag in coupon.tags:
                    tag.count -= 1
                    if tag.count < 0:
                        tag.count = 0

                data_directory = "multipass/input_html"
                xlsx_filename = f"coupon_{coupon.code}_{coupon.id}.xlsx"
                xlsx_path = os.path.join(data_directory, xlsx_filename)
                if os.path.exists(xlsx_path):
                    os.remove(xlsx_path)

                db.session.delete(coupon)
                db.session.commit()
                flash(f'קופון "{coupon.code}" נמחק בהצלחה!', 'success')
                return redirect(url_for('coupons.show_coupons'))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error deleting coupon {coupon.id}: {e}")
                flash('אירעה שגיאה במחיקת הקופון. נסה שוב.', 'danger')
        elif form.cancel.data:
            flash('המחיקה בוטלה.', 'info')
            return redirect(url_for('coupons.coupon_detail', id=id))

    return render_template('confirm_delete.html', coupon=coupon, form=form)


@coupons_bp.route('/edit_usage/<int:usage_id>', methods=['GET', 'POST'])
@login_required
def edit_usage(usage_id):
    usage = CouponUsage.query.get_or_404(usage_id)
    coupon = Coupon.query.get_or_404(usage.coupon_id)

    # -- activity log snippet --
    log_user_activity("edit_usage_view", coupon_id)

    if coupon.user_id != current_user.id:
        flash('אינך מורשה לערוך שימוש זה.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    if request.method == 'POST':
        new_used_amount = float(request.form['used_amount'])
        if new_used_amount <= 0:
            flash('כמות השימוש חייבת להיות חיובית.', 'danger')
            return redirect(url_for('coupons.edit_usage', usage_id=usage_id))

        coupon.used_value -= usage.used_amount
        if (coupon.used_value + new_used_amount) > coupon.value:
            flash('הכמות שהשתמשת בה גדולה מערך הקופון הנותר.', 'danger')
            coupon.used_value += usage.used_amount
            return redirect(url_for('coupons.edit_usage', usage_id=usage_id))

        usage.used_amount = new_used_amount
        coupon.used_value += new_used_amount
        update_coupon_status(coupon)

        db.session.commit()

        # -- activity log snippet --
        try:
            new_activity = {
                "user_id": current_user.id,
                "coupon_id": coupon.id,
                "timestamp": datetime.utcnow(),
                "action": "edit_usage_success",
                "device": request.headers.get('User-Agent', '')[:50],
                "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": get_geo_location(ip_address)[:100]
            }
            db.session.execute(
                text("""
                    INSERT INTO user_activities 
                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                    VALUES 
                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                """),
                new_activity
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error logging activity [edit_usage_success]: {e}")

        flash('רשומת השימוש עודכנה בהצלחה!', 'success')
        return redirect(url_for('coupons.coupon_detail', id=coupon.id))

    return render_template('edit_usage.html', usage=usage, coupon=coupon)




@coupons_bp.route('/update_all_coupons/process', methods=['GET', 'POST'])
@login_required
def update_all_coupons_route():
    # -- activity log snippet --
    log_user_activity("update_all_coupons_process", None)

    updated, failed = update_all_active_coupons(current_user.id)
    if updated:
        flash(f"הקופונים הבאים עודכנו: {', '.join(updated)}", "success")
    if failed:
        flash(f"הקופונים הבאים נכשלו: {', '.join(failed)}", "danger")
    return redirect(url_for('coupons.show_coupons'))


@coupons_bp.route('/get_tags')
@login_required
def get_tags():
    # -- activity log snippet --
    log_user_activity("get_tags", None)

    tags = [tag.name for tag in Tag.query.all()]
    return jsonify(tags)


@coupons_bp.route('/usage_order')
@login_required
def usage_order():
    # -- activity log snippet --
    log_user_activity("usage_order_view", None)

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
    # -- activity log snippet --
    log_user_activity("export_excel", None)

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


@coupons_bp.route('/export_pdf')
@login_required
def export_pdf():
    # -- activity log snippet --
    log_user_activity("export_pdf", None)


    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

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
    return send_file(output, download_name='coupons.pdf', as_attachment=True, mimetype='application/pdf')


@coupons_bp.route('/coupon_request/<int:id>', methods=['GET', 'POST'])
@login_required
def coupon_request_detail(id):
    coupon_request = CouponRequest.query.get_or_404(id)

    # אם הבקשה כבר טופלה, חזרה לשוק הקופונים
    if coupon_request.fulfilled:
        flash('בקשת הקופון כבר טופלה.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    delete_form = DeleteCouponRequestForm()

    if delete_form.validate_on_submit():
        db.session.delete(coupon_request)
        db.session.commit()
        flash('הבקשה נמחקה בהצלחה.', 'success')
        return redirect(url_for('marketplace.marketplace'))

    requester = User.query.get(coupon_request.user_id)
    company = Company.query.get(coupon_request.company)
    if not company:
        flash('החברה לא נמצאה.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    company_logo_mapping = {company.name.lower(): company.image_path for company in Company.query.all()}

    return render_template(
        'coupon_request_detail.html',
        coupon_request=coupon_request,
        requester=requester,
        company=company,
        company_logo_mapping=company_logo_mapping,
        delete_form=delete_form
    )


@coupons_bp.route('/delete_coupon_request/<int:id>', methods=['POST'])
@login_required
def delete_coupon_request(id):
    coupon_request = CouponRequest.query.get_or_404(id)

    # -- activity log snippet --
    log_user_activity("delete_coupon_request_attempt", None)

    if coupon_request.user_id != current_user.id:
        flash('אין לך הרשאה למחוק בקשה זו.', 'danger')
        return redirect(url_for('coupons.marketplace'))

    try:
        db.session.delete(coupon_request)
        db.session.commit()

        # לוג הצלחת המחיקה
        try:
            new_activity = {
                "user_id": current_user.id,
                "coupon_id": None,
                "timestamp": datetime.utcnow(),
                "action": "delete_coupon_request_success",
                "device": request.headers.get('User-Agent', '')[:50],
                "browser": request.headers.get('User-Agent', '').split(' ')[0][:50] if request.headers.get('User-Agent', '') else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": get_geo_location(ip_address)[:100]
            }
            db.session.execute(
                text("""
                    INSERT INTO user_activities
                        (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                    VALUES
                        (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
                """),
                new_activity
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error logging activity [delete_coupon_request_success]: {e}")

        flash('בקשת הקופון נמחקה בהצלחה.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting coupon request {id}: {e}")
        flash('אירעה שגיאה בעת מחיקת הבקשה.', 'danger')

    return redirect(url_for('transactions.my_transactions'))


def complete_transaction(transaction):
    # -- activity log snippet --
    try:
        user_agent = request.headers.get('User-Agent', '') if request else ''
        geo_location = get_geo_location(ip_address) if request else 'N/A'
        activity = {
            "user_id": transaction.seller_id,
            "coupon_id": transaction.coupon_id,
            "timestamp": datetime.utcnow(),
            "action": "complete_transaction",
            "device": user_agent[:50] if user_agent else None,
            "browser": user_agent.split(' ')[0][:50] if user_agent else None,
            "ip_address": ip_address[:45] if ip_address else None if ip_address != 'N/A' else 'N/A',
            "geo_location": geo_location[:100] if geo_location != 'N/A' else 'N/A'
        }
        db.session.execute(
            text("""
                INSERT INTO user_activities 
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                VALUES 
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
            """),
            activity
        )
        db.session.commit()
    except:
        db.session.rollback()
    # -- end snippet --

    try:
        coupon = transaction.coupon
        coupon.user_id = transaction.buyer_id
        coupon.is_for_sale = False
        coupon.is_available = True
        transaction.status = 'הושלם'

        notification_buyer = Notification(
            user_id=transaction.buyer_id,
            message='הקופון הועבר לחשבונך.',
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )
        notification_seller = Notification(
            user_id=transaction.seller_id,
            message='העסקה הושלמה והקופון הועבר לקונה.',
            link=url_for('transactions.my_transactions')
        )

        db.session.add(notification_buyer)
        db.session.add(notification_seller)
        db.session.commit()
        flash('העסקה הושלמה בהצלחה והקופון הועבר לקונה!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error completing transaction {transaction.id}: {e}")
        flash('אירעה שגיאה בעת השלמת העסקה. נא לנסות שוב.', 'danger')



@coupons_bp.route('/send_coupon_expiration_warning/<int:coupon_id>')
def send_coupon_expiration_warning(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)

    # -- activity log snippet --
    log_user_activity("send_coupon_expiration_warning", coupon.id)

    user = coupon.user
    expiration_date = coupon.expiration
    coupon_detail_link = url_for('coupons.coupon_detail', id=coupon.id, _external=True)

    html_content = render_template('emails/coupon_expiration_warning.html',
                                   user=user,
                                   coupon=coupon,
                                   expiration_date=expiration_date,
                                   coupon_detail_link=coupon_detail_link)

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

    # -- activity log snippet --
    log_user_activity("mark_coupon_as_used", coupon.id)

    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

    if not coupon.is_one_time:
        flash('הקופון אינו חד-פעמי.', 'warning')
        return redirect(url_for('coupons.coupon_detail', id=id))

    if coupon.status != 'פעיל':
        flash('הקופון כבר נוצל או פג תוקפו.', 'warning')
        return redirect(url_for('coupons.coupon_detail', id=id))

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
    log_user_activity("update_coupon_usage_from_multipass", coupon.id)

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
    log_user_activity("complete_transaction")

    from forms import UpdateCouponUsageForm, MarkCouponAsFullyUsedForm
    coupon = Coupon.query.get_or_404(id)
    is_owner = (current_user.id == coupon.user_id)

    if coupon.user_id != current_user.id:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('coupons.show_coupons'))

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
def update_all_active_coupons(user_id):
    if not current_user.is_admin:
        flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
        return redirect(url_for('index'))

    valid_coupon_pattern = re.compile(r'^\d{8,9}-\d{4}$')
    active_coupons = Coupon.query.filter(
        Coupon.status == 'פעיל',
        Coupon.is_one_time == False
    ).all()

    updated_coupons = []
    failed_coupons = []

    for coupon in active_coupons:
        if not valid_coupon_pattern.match(coupon.code):
            failed_coupons.append(coupon.code)
            continue

        print(valid_coupon_pattern.match(coupon.code))
        try:
            print(f"Updating {coupon.code}")
            df = get_coupon_data(coupon.code)
            if df is not None:
                total_usage = df['usage_amount'].sum()
                total_usage = float(total_usage)
                coupon.used_value = total_usage
                update_coupon_status(coupon)

                usage = CouponUsage(
                    coupon_id=coupon.id,
                    used_amount=total_usage,
                    timestamp=datetime.now(timezone.utc),
                    action='עדכון מרוכז',
                    details='עדכון מרוכז של שימוש בקופון מ-Multipass'
                )
                db.session.add(usage)

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

    db.session.commit()

    if updated_coupons:
        flash(f'הקופונים הבאים עודכנו בהצלחה: {", ".join(updated_coupons)}', 'success')
    if failed_coupons:
        flash(f'הקופונים הבאים לא עודכנו: {", ".join(failed_coupons)}', 'danger')

    return redirect(url_for('profile.index'))

@coupons_bp.route('/update_coupon_transactions', methods=['POST'])
@login_required
def update_coupon_transactions():
    log_user_activity("update_coupon_transactions_attempt")

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
            return redirect(url_for('transactions.coupon_detail', id=coupon.id))
        else:
            flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
            return redirect(url_for('transactions.my_transactions'))

    coupon_id = request.form.get('coupon_id')
    coupon_code = request.form.get('coupon_code')
    coupon = None
    if coupon_id:
        coupon = Coupon.query.get(coupon_id)
    elif coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()

    if not coupon:
        flash('לא ניתן לעדכן נתונים ללא מזהה קופון תקין.', 'danger')
        return redirect(url_for('transactions.my_transactions'))

    df = get_coupon_data(coupon.code)
    if df is not None:
        Transaction.query.filter_by(coupon_id=coupon.id, source='Multipass').delete()
        for index, row in df.iterrows():
            t = Transaction(
                coupon_id=coupon.id,
                card_number=row['card_number'],
                transaction_date=row['transaction_date'],
                location=row['location'],
                recharge_amount=row['recharge_amount'] or 0,
                usage_amount=row['usage_amount'] or 0,
                reference_number=row.get('reference_number', ''),
                source='Multipass'
            )
            db.session.add(t)

        total_used = df['usage_amount'].sum()
        coupon.used_value = total_used
        db.session.commit()

        flash(f'הנתונים עבור הקופון {coupon.code} עודכנו בהצלחה.', 'success')
        log_user_activity("update_coupon_transactions_success", coupon.id)
    else:
        flash(f'אירעה שגיאה בעת עדכון הנתונים עבור הקופון {coupon.code}.', 'danger')

    return redirect(url_for('coupons.coupon_detail', id=coupon.id))
