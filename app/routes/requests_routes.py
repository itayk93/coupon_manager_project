from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
)
from flask_login import login_required, current_user
from datetime import datetime
import logging

from app.models import CouponRequest, User, Company, db
from app.forms import RequestCouponForm, DeleteCouponRequestForm
from app.helpers import get_geo_location  # פונקציה אופציונלית לדוגמה
from sqlalchemy.sql import text

requests_bp = Blueprint("requests", __name__)
logger = logging.getLogger(__name__)


def log_user_activity(action, coupon_id=None):
    """
    Function to log user activity.
    """
    try:
        ip_address = request.remote_addr
        user_agent = request.headers.get("User-Agent", "")
        geo_location = get_geo_location(ip_address) if ip_address else None

        db.session.execute(
            db.text(
                """
                INSERT INTO user_activities
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                VALUES
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
            """
            ),
            {
                "user_id": current_user.id if current_user.is_authenticated else None,
                "coupon_id": coupon_id,
                "timestamp": datetime.utcnow(),
                "action": action,
                "device": user_agent[:50] if user_agent else None,
                "browser": user_agent.split(" ")[0][:50] if user_agent else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": geo_location[:100] if geo_location else None,
            },
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging activity [{action}]: {e}")


@requests_bp.route("/coupon_request/<int:id>", methods=["GET", "POST"])
@login_required
def coupon_request_detail(id):
    # log_user_activity("coupon_request_detail_view")

    coupon_request = CouponRequest.query.get_or_404(id)

    if coupon_request.fulfilled:
        flash("בקשת הקופון כבר טופלה.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    delete_form = DeleteCouponRequestForm()

    if delete_form.validate_on_submit():
        db.session.delete(coupon_request)
        db.session.commit()
        flash("הבקשה נמחקה בהצלחה.", "success")
        # log_user_activity("coupon_request_deleted")
        return redirect(url_for("marketplace.marketplace"))

    requester = User.query.get(coupon_request.user_id)
    company = Company.query.get(coupon_request.company)

    if not company:
        flash("החברה לא נמצאה.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    company_logo_mapping = {c.name.lower(): c.image_path for c in Company.query.all()}

    return render_template(
        "coupon_request_detail.html",
        coupon_request=coupon_request,
        requester=requester,
        company=company,
        company_logo_mapping=company_logo_mapping,
        delete_form=delete_form,
    )


@requests_bp.route("/delete_coupon_request/<int:id>", methods=["POST"])
@login_required
def delete_coupon_request(id):
    # log_user_activity("delete_coupon_request_attempt")

    coupon_request = CouponRequest.query.get_or_404(id)
    if coupon_request.user_id != current_user.id:
        flash("אין לך הרשאה למחוק בקשה זו.", "danger")
        return redirect(url_for("marketplace.marketplace"))

    try:
        db.session.delete(coupon_request)
        db.session.commit()
        flash("בקשת הקופון נמחקה בהצלחה.", "success")
        # log_user_activity("delete_coupon_request_success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting coupon request {id}: {e}")
        flash("אירעה שגיאה בעת מחיקת הבקשה.", "danger")

    return redirect(url_for("marketplace.marketplace"))


@requests_bp.route("/request_coupon", methods=["GET", "POST"])
@login_required
def request_coupon():
    """
    Coupon Request Screen:
    - The user selects an existing company or 'other' to enter a new company.
    - Fills in the requested cost, requested value, discount percentage, coupon code (optional), and additional description.
    - Saved to the coupon_requests table.
    """
    # log_user_activity("request_coupon_view")

    form = RequestCouponForm()

    # שליפת חברות קיימות מה-DB והכנסתן ל-choices
    companies = Company.query.all()
    # נוסיף אופציה של "אחר" בסוף הרשימה
    form.company.choices = [(str(c.id), c.name) for c in companies] + [("other", "אחר")]

    if form.validate_on_submit():
        # מקבלים ערכים מהטופס
        selected_company_id = form.company.data
        other_company_name = (
            form.other_company.data.strip() if form.other_company.data else ""
        )
        cost = form.cost.data
        value = form.value.data
        discount_percentage = form.discount_percentage.data
        code = form.code.data.strip() if form.code.data else ""
        description = form.description.data.strip() if form.description.data else ""

        # Determine the company name (if "other" is selected - take from the text, otherwise take from the DB)
        if selected_company_id == "other":
            # User entered a new company
            company_name = other_company_name
        else:
            # User selected an existing company
            existing_company = Company.query.get_or_404(int(selected_company_id))
            company_name = existing_company.name

        # Save the request to the DB
        coupon_req = CouponRequest(
            company=company_name,
            other_company=other_company_name,  # אם המשתמש באמת הזין משהו
            code=code,
            value=value if value else 0.0,
            cost=cost if cost else 0.0,
            description=description,
            user_id=current_user.id,
            date_requested=datetime.utcnow(),
            fulfilled=False,
        )

        try:
            db.session.add(coupon_req)
            db.session.commit()
            flash("בקשת הקופון נרשמה בהצלחה!", "success")
            # log_user_activity("request_coupon_submitted")
            return redirect(url_for("marketplace.marketplace"))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating coupon request: {e}")
            flash("אירעה שגיאה בעת שמירת הבקשה למסד הנתונים.", "danger")

    # If GET or validation error occurred, display the form
    return render_template("request_coupon.html", form=form, companies=companies)


@requests_bp.route("/buy_slots", methods=["GET", "POST"])
@login_required
def buy_slots():
    from app.forms import BuySlotsForm

    # log_user_activity("buy_slots_view")

    form = BuySlotsForm()
    if form.validate_on_submit():
        try:
            slot_amount = int(form.slot_amount.data)
            if slot_amount not in [10, 20, 50]:
                flash("כמות סלוטים לא תקפה.", "danger")
                return redirect(url_for("requests.buy_slots"))

            current_user.slots += slot_amount
            db.session.commit()
            flash(f"רכשת {slot_amount} סלוטים בהצלחה!", "success")
            # log_user_activity("buy_slots_success")
            return redirect(url_for("requests.buy_slots"))
        except ValueError:
            flash("כמות סלוטים לא תקפה.", "danger")
            return redirect(url_for("requests.buy_slots"))

    return render_template("buy_slots.html", slots=current_user.slots, form=form)
