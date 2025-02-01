import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.models import Coupon, Tag, coupon_tags
from app.extensions import db
from sqlalchemy.exc import SQLAlchemyError

admin_coupon_tags_bp = Blueprint('admin_coupon_tags_bp', __name__, url_prefix='/admin/coupon-tags')

# הגדרת לוגינג – ניתן לשנות את רמת הלוגים לפי הצורך
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

@admin_coupon_tags_bp.route('/', methods=['GET', 'POST'])
@login_required
def manage_coupon_tags():
    tags = Tag.query.all()

    # שליפת הקופונים עם הצטרפות לטבלאות (על מנת לקבל את תגיתם הנוכחית)
    coupons = db.session.query(
        Coupon.id,
        Coupon.company,
        Coupon.auto_download_details,
        Tag.id.label('tag_id'),
        Tag.name.label('tag_name')
    ).outerjoin(coupon_tags, Coupon.id == coupon_tags.c.coupon_id) \
     .outerjoin(Tag, Tag.id == coupon_tags.c.tag_id) \
     .order_by(Coupon.id.asc()) \
     .all()

    if request.method == 'POST':
        logger.info("Received POST request to update coupon data.")
        submitted_coupon_id = request.form.get("coupon_id")
        if not submitted_coupon_id:
            flash("לא סופק ID לקופון.", "danger")
            return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))
        coupon = Coupon.query.get(submitted_coupon_id)
        if not coupon:
            flash(f"קופון עם ID {submitted_coupon_id} לא נמצא במערכת.", "danger")
            return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))
        
        # טיפול בעדכון תגית
        if "update_tag" in request.form:
            tag_id = request.form.get("tag_id")
            logger.info(f"Updating tag for coupon {submitted_coupon_id} to tag {tag_id}.")
            new_tag = Tag.query.get(tag_id)
            if not new_tag:
                flash(f"תגית עם ID {tag_id} לא נמצאה.", "danger")
                return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))
            try:
                # עדכון הקשר Many-to-Many – החלפת כל התגיות בתגית החדשה
                coupon.tags = [new_tag]
                db.session.commit()
                flash("תגית הקופון עודכנה בהצלחה!", "success")
            except SQLAlchemyError as e:
                db.session.rollback()
                logger.error(f"Error updating tag for coupon {submitted_coupon_id}: {e}")
                flash("אירעה שגיאה בעדכון תגית הקופון.", "danger")
        
        # טיפול בעדכון הורדה אוטומטית
        elif "update_auto" in request.form:
            new_auto = request.form.get("auto_download_details")
            logger.info(f"Updating auto_download_details for coupon {submitted_coupon_id} to {new_auto}.")
            try:
                coupon.auto_download_details = new_auto
                db.session.commit()
                flash("הורדה אוטומטית עודכנה בהצלחה!", "success")
            except SQLAlchemyError as e:
                db.session.rollback()
                logger.error(f"Error updating auto_download_details for coupon {submitted_coupon_id}: {e}")
                flash("אירעה שגיאה בעדכון הורדה אוטומטית.", "danger")
        else:
            flash("לא נבחר סוג עדכון.", "danger")
        
        return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))

    return render_template(
        'admin/admin_manage_coupon_tags.html',
        coupons=coupons,
        tags=tags
    )
