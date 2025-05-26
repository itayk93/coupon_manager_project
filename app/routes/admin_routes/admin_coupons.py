from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
)
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Coupon, CouponUsage, Notification
from datetime import datetime, timezone
from app.helpers import get_coupon_data, update_coupon_status
import logging

admin_coupons_bp = Blueprint(
    "admin_coupons_bp",
    __name__,
    template_folder="templates",
    url_prefix="/admin/coupons",
)


@admin_coupons_bp.before_request
def require_admin():
    """בדיקה שהמשתמש הנוכחי הוא אדמין; אם לא – מפנה לדף אחר."""
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("אין לך הרשאה להיכנס לעמוד זה (מנהלים בלבד).", "danger")
        return redirect(url_for("profile.index"))


@admin_coupons_bp.route("/", methods=["GET"])
def index():
    """
    עמוד ראשי לניהול קופונים עם auto_download_details:
    1) טפסים למעלה – לעדכון ערך לקופון יחיד + כפתורי עדכון מרוכז.
    2) טבלה למטה – מציגה את כל הקופונים שיש להם auto_download_details (בכל סטטוס).
    """
    # שליפת כל הקופונים (לרשימת הבחירה)
    all_coupons = Coupon.query.all()

    # שליפת distinct של auto_download_details שישנם בטבלה
    auto_download_values = (
        db.session.query(Coupon.auto_download_details)
        .distinct()
        .filter(Coupon.auto_download_details.isnot(None))
        .all()
    )
    auto_values_clean = [row[0] for row in auto_download_values if row[0]]

    # הטבלה למטה – מציגה *כל* הקופונים שיש להם auto_download_details
    table_coupons = Coupon.query.filter(Coupon.auto_download_details.isnot(None)).all()

    return render_template(
        "admin/admin_auto_coupons.html",
        coupons=all_coupons,  # לרשימת הבחירה למעלה
        auto_download_values=auto_values_clean,
        table_coupons=table_coupons,  # לטבלה למטה
    )


@admin_coupons_bp.route("/update_coupon", methods=["POST"])
def update_auto_download_details():
    """
    מעדכן ערך של auto_download_details בקופון יחיד.
    """
    coupon_id = request.form.get("coupon_id")
    auto_value = request.form.get("auto_value", "").strip()

    if not coupon_id:
        flash("לא נבחר קופון", "danger")
        return redirect(url_for("admin_bp.admin_coupons_bp.index"))

    coupon = Coupon.query.get(coupon_id)
    if not coupon:
        flash("הקופון לא קיים במערכת", "danger")
        return redirect(url_for("admin_bp.admin_coupons_bp.index"))

    old_value = coupon.auto_download_details
    coupon.auto_download_details = auto_value if auto_value else None

    try:
        db.session.commit()
        flash(
            f"עודכן auto_download_details מ-'{old_value}' ל-'{coupon.auto_download_details}' "
            f"עבור קופון ID {coupon.id}.",
            "success",
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"שגיאה בעדכון auto_download_details: {e}")
        flash("אירעה שגיאה בעת העדכון. בדוק לוגים.", "danger")

    return redirect(url_for("admin_bp.admin_coupons_bp.index"))


@admin_coupons_bp.route("/update_all_active", methods=["POST"])
def update_all_active_coupons():
    """
    עדכון מרוכז - *רק* לקופונים הפעילים שיש להם auto_download_details != NULL.
    """
    active_auto_coupons = Coupon.query.filter(
        Coupon.status == "פעיל", Coupon.auto_download_details.isnot(None)
    ).all()

    updated_coupons = []
    failed_coupons = []

    for cpn in active_auto_coupons:
        try:
            df = get_coupon_data(cpn)
            if df is not None:
                total_usage = float(df["usage_amount"].sum())
                cpn.used_value = total_usage
                update_coupon_status(cpn)

                usage = CouponUsage(
                    coupon_id=cpn.id,
                    used_amount=total_usage,
                    timestamp=datetime.now(timezone.utc),
                    action="עדכון מרוכז (רק פעילים)",
                    details="עדכון אוטומטי",
                )
                db.session.add(usage)

                """""" """
                notification = Notification(
                    user_id=cpn.user_id,
                    message=f"השימוש בקופון {cpn.code} עודכן אוטומטית ({cpn.auto_download_details}).",
                    link=url_for('coupons.coupon_detail', id=cpn.id)
                )
                db.session.add(notification)
                """ """"""

                updated_coupons.append(str(cpn.id))
            else:
                failed_coupons.append(str(cpn.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating coupon {cpn.id}: {e}")
            failed_coupons.append(str(cpn.id))

    db.session.commit()

    if updated_coupons:
        flash(
            f'עודכנו בהצלחה (פעילים) קופונים: {", ".join(updated_coupons)}', "success"
        )
    if failed_coupons:
        flash(f'(פעילים) נכשלו בעדכון: {", ".join(failed_coupons)}', "danger")

    return redirect(url_for("admin_bp.admin_coupons_bp.index"))


@admin_coupons_bp.route("/update_all_any", methods=["POST"])
def update_all_any_coupons():
    """
    עדכון מרוכז - *כל הקופונים* (פעילים או לא) שיש להם auto_download_details != NULL.
    """
    auto_coupons = Coupon.query.filter(Coupon.auto_download_details.isnot(None)).all()

    updated_coupons = []
    failed_coupons = []

    for cpn in auto_coupons:
        try:
            df = get_coupon_data(cpn)
            if df is not None:
                total_usage = float(df["usage_amount"].sum())
                cpn.used_value = total_usage
                update_coupon_status(cpn)

                usage = CouponUsage(
                    coupon_id=cpn.id,
                    used_amount=total_usage,
                    timestamp=datetime.now(timezone.utc),
                    action="עדכון מרוכז (הכל)",
                    details="עדכון אוטומטי",
                )
                db.session.add(usage)

                """""" """
                notification = Notification(
                    user_id=cpn.user_id,
                    message=f"השימוש בקופון {cpn.code} עודכן אוטומטית ({cpn.auto_download_details}).",
                    link=url_for('coupons.coupon_detail', id=cpn.id)
                )
                db.session.add(notification)
                """ """"""

                updated_coupons.append(str(cpn.id))
            else:
                failed_coupons.append(str(cpn.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating coupon {cpn.id}: {e}")
            failed_coupons.append(str(cpn.id))

    db.session.commit()

    if updated_coupons:
        flash(f'עודכנו בהצלחה (כללי) קופונים: {", ".join(updated_coupons)}', "success")
    if failed_coupons:
        flash(f'(כללי) נכשלו בעדכון: {", ".join(failed_coupons)}', "danger")

    return redirect(url_for("admin_bp.admin_coupons_bp.index"))
