# app/routes/admin_coupon_tags_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.models import Coupon, Tag, coupon_tags
from app.extensions import db
from app.forms import ManageCouponTagForm
from sqlalchemy.exc import SQLAlchemyError
import logging

admin_coupon_tags_bp = Blueprint('admin_coupon_tags_bp', __name__)

# קביעת רמת הלוגינג
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


# app/routes/admin_coupon_tags_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.models import Coupon, Tag, coupon_tags
from app.extensions import db
from app.forms import ManageCouponTagForm
from sqlalchemy.exc import SQLAlchemyError
import logging

admin_coupon_tags_bp = Blueprint('admin_coupon_tags_bp', __name__)

# קביעת רמת הלוגינג
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


@admin_coupon_tags_bp.route('/admin/manage_coupon_tags', methods=['GET', 'POST'])
@login_required
def manage_coupon_tags():
    tags = Tag.query.all()
    tag_choices = [(tag.id, tag.name) for tag in tags]

    coupons = db.session.query(
        Coupon.id,
        Coupon.company,
        Tag.id.label('tag_id'),
        Tag.name.label('tag_name')
    ).outerjoin(coupon_tags, Coupon.id == coupon_tags.c.coupon_id) \
        .outerjoin(Tag, Tag.id == coupon_tags.c.tag_id) \
        .order_by(Coupon.id.asc()) \
        .all()

    forms = {}
    for coupon in coupons:
        form = ManageCouponTagForm(prefix=str(coupon.id))
        form.tag_id.choices = tag_choices
        form.coupon_id.data = coupon.id
        if coupon.tag_id:
            form.tag_id.data = coupon.tag_id
        forms[coupon.id] = form

    if request.method == 'POST':
        logger.info("Received POST request to update coupon tags.")
        for coupon_id, form in forms.items():
            if form.submit.data and form.validate_on_submit():
                logger.info(f"Processing form for coupon ID: {coupon_id}")
                tag_id = form.tag_id.data
                logger.info(f"Selected tag ID: {tag_id} for coupon ID: {coupon_id}")

                try:
                    coupon = Coupon.query.get(coupon_id)
                    if not coupon:
                        logger.error(f"Coupon with ID {coupon_id} not found.")
                        flash(f"קופון עם ID {coupon_id} לא נמצא במערכת.", 'danger')
                        continue

                    new_tag = Tag.query.get(tag_id)
                    if not new_tag:
                        logger.error(f"Tag with ID {tag_id} not found.")
                        flash(f"תגית עם ID {tag_id} לא נמצאה.", 'danger')
                        continue

                    logger.info(f"Attempting to update tags for coupon ID {coupon_id}")

                    # עדכון התגיות באמצעות ORM
                    coupon.tags = [new_tag]
                    db.session.commit()

                    logger.info(f"Successfully updated tag for coupon ID {coupon_id}")
                    flash('תגית הקופון עודכנה בהצלחה!', 'success')
                    return redirect(url_for('admin_coupon_tags_bp.manage_coupon_tags'))

                except SQLAlchemyError as e:
                    db.session.rollback()
                    logger.error(f"Database error while updating coupon {coupon_id}: {e}")
                    flash('אירעה שגיאה בעדכון תגית הקופון.', 'danger')

        logger.warning("No valid form was submitted.")
        flash('אירעה שגיאה בעדכון תגית הקופון.', 'danger')

    return render_template(
        'admin/admin_manage_coupon_tags.html',
        coupons=coupons,
        tags=tags,
        forms=forms
    )
