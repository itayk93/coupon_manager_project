import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.models import Coupon, Tag, coupon_tags
from app.extensions import db
from sqlalchemy.exc import SQLAlchemyError

admin_coupon_tags_bp = Blueprint(
    "admin_coupon_tags_bp", __name__, url_prefix="/admin/coupon-tags"
)

# Set up logging configuration
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


@admin_coupon_tags_bp.route("/", methods=["GET", "POST"])
@login_required
def manage_coupon_tags():
    """
    Main route for managing coupon categories. Handles displaying all coupons and their categories
    as well as processing single coupon category or auto download updates.
    """
    # Get all available tags for dropdowns, sorted alphabetically by name
    tags = Tag.query.order_by(Tag.name).all()

    # Retrieve coupons with their current tag information
    coupons = (
        db.session.query(
            Coupon.id,
            Coupon.company,
            Coupon.auto_download_details,
            Tag.id.label("tag_id"),
            Tag.name.label("tag_name"),
        )
        .outerjoin(coupon_tags, Coupon.id == coupon_tags.c.coupon_id)
        .outerjoin(Tag, Tag.id == coupon_tags.c.tag_id)
        .order_by(Tag.id.is_(None).desc(), Coupon.id.desc())
        .all()
    )

    # Handle POST requests for single coupon updates
    if request.method == "POST":
        logger.info("Received POST request to update coupon data.")
        submitted_coupon_id = request.form.get("coupon_id")

        if not submitted_coupon_id:
            flash("לא סופק ID לקופון.", "danger")
            return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))

        coupon = Coupon.query.get(submitted_coupon_id)
        if not coupon:
            flash(f"קופון עם ID {submitted_coupon_id} לא נמצא במערכת.", "danger")
            return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))

        # Handle tag update
        if "update_tag" in request.form:
            tag_id = request.form.get("tag_id")
            logger.info(
                f"Updating category for coupon {submitted_coupon_id} to tag {tag_id}."
            )

            new_tag = Tag.query.get(tag_id)
            if not new_tag:
                flash(f"תגית עם ID {tag_id} לא נמצאה.", "danger")
                return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))

            try:
                # Update the many-to-many relationship - replace all categories with the new category
                coupon.tags = [new_tag]
                db.session.commit()
                flash("קטגוריית הקופון עודכנה בהצלחה!", "success")
            except SQLAlchemyError as e:
                db.session.rollback()
                logger.error(
                    f"Error updating category for coupon {submitted_coupon_id}: {e}"
                )
                flash("אירעה שגיאה בעדכון קטגוריית הקופון.", "danger")

        # Handle auto download update
        elif "update_auto" in request.form:
            new_auto = request.form.get("auto_download_details")
            logger.info(
                f"Updating auto_download_details for coupon {submitted_coupon_id} to {new_auto}."
            )

            try:
                coupon.auto_download_details = new_auto
                db.session.commit()
                flash("הורדה אוטומטית עודכנה בהצלחה!", "success")
            except SQLAlchemyError as e:
                db.session.rollback()
                logger.error(
                    f"Error updating auto_download_details for coupon {submitted_coupon_id}: {e}"
                )
                flash("אירעה שגיאה בעדכון הורדה אוטומטית.", "danger")
        else:
            flash("לא נבחר סוג עדכון.", "danger")

        return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))

    return render_template(
        "admin/admin_manage_coupon_tags.html", coupons=coupons, tags=tags
    )


@admin_coupon_tags_bp.route("/update-multiple", methods=["POST"])
@login_required
def update_multiple_tags():
    """
    New route to handle batch updating of categories for multiple coupons at once.
    Receives a comma-separated list of coupon IDs and a target tag ID.
    """
    coupon_ids_str = request.form.get("coupon_ids", "")
    tag_id = request.form.get("tag_id")

    # Validate inputs
    if not coupon_ids_str or not tag_id:
        flash("נדרשים מזהי קופונים ותגית.", "danger")
        return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))

    # Parse coupon IDs
    try:
        coupon_ids = [
            int(id_str) for id_str in coupon_ids_str.split(",") if id_str.strip()
        ]
    except ValueError:
        flash("פורמט לא תקין של מזהי קופונים.", "danger")
        return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))

    if not coupon_ids:
        flash("לא נבחרו קופונים.", "warning")
        return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))

    # Get the target tag
    tag = Tag.query.get(tag_id)
    if not tag:
        flash(f"תגית עם ID {tag_id} לא נמצאה.", "danger")
        return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))

    # Update all selected coupons
    try:
        # Get all coupons to update
        coupons = Coupon.query.filter(Coupon.id.in_(coupon_ids)).all()
        updated_count = 0

        for coupon in coupons:
            coupon.tags = [tag]  # Replace all existing tags with the new one
            updated_count += 1

        db.session.commit()
        flash(
            f"{updated_count} קופונים עודכנו בהצלחה עם הקטגוריה '{tag.name}'!",
            "success",
        )
        logger.info(f"Batch updated {updated_count} coupons with tag {tag_id}")
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Error batch updating coupons with tag {tag_id}: {e}")
        flash("אירעה שגיאה בעדכון הקופונים.", "danger")

    return redirect(url_for("admin_coupon_tags_bp.manage_coupon_tags"))
