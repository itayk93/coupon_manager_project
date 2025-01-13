from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import logging

from app.models import CouponRequest, User, Company, db
from app.forms import DeleteCouponRequestForm,RequestCouponForm
from app.helpers import send_coupon_purchase_request_email, get_geo_location  # או הגדר כאן את get_geo_location

requests_bp = Blueprint('requests', __name__)
logger = logging.getLogger(__name__)
from sqlalchemy.sql import text

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from datetime import datetime
import logging

from app.models import CouponRequest, User, Company, db
from app.forms import RequestCouponForm, DeleteCouponRequestForm
from app.helpers import get_geo_location  # פונקציה אופציונלית לדוגמה
from sqlalchemy.sql import text

requests_bp = Blueprint('requests', __name__)
logger = logging.getLogger(__name__)

def log_user_activity(action, coupon_id=None):
    """
    פונקציה לרישום פעילות המשתמש (activity log).
    """
    try:
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent', '')
        geo_location = get_geo_location(ip_address) if ip_address else None

        db.session.execute(
            db.text("""
                INSERT INTO user_activities
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                VALUES
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
            """),
            {
                "user_id": current_user.id if current_user.is_authenticated else None,
                "coupon_id": coupon_id,
                "timestamp": datetime.utcnow(),
                "action": action,
                "device": user_agent[:50] if user_agent else None,
                "browser": user_agent.split(' ')[0][:50] if user_agent else None,
                "ip_address": ip_address[:45] if ip_address else None,
                "geo_location": geo_location[:100] if geo_location else None
            }
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error logging activity [{action}]: {e}")

@requests_bp.route('/coupon_request/<int:id>', methods=['GET', 'POST'])
@login_required
def coupon_request_detail(id):
    log_user_activity("coupon_request_detail_view")

    coupon_request = CouponRequest.query.get_or_404(id)

    if coupon_request.fulfilled:
        flash('בקשת הקופון כבר טופלה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    delete_form = DeleteCouponRequestForm()

    if delete_form.validate_on_submit():
        db.session.delete(coupon_request)
        db.session.commit()
        flash('הבקשה נמחקה בהצלחה.', 'success')
        log_user_activity("coupon_request_deleted")
        return redirect(url_for('marketplace.marketplace'))

    requester = User.query.get(coupon_request.user_id)
    company = Company.query.get(coupon_request.company)

    if not company:
        flash('החברה לא נמצאה.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    company_logo_mapping = {c.name.lower(): c.image_path for c in Company.query.all()}

    return render_template(
        'coupon_request_detail.html',
        coupon_request=coupon_request,
        requester=requester,
        company=company,
        company_logo_mapping=company_logo_mapping,
        delete_form=delete_form
    )

@requests_bp.route('/delete_coupon_request/<int:id>', methods=['POST'])
@login_required
def delete_coupon_request(id):
    log_user_activity("delete_coupon_request_attempt")

    coupon_request = CouponRequest.query.get_or_404(id)
    if coupon_request.user_id != current_user.id:
        flash('אין לך הרשאה למחוק בקשה זו.', 'danger')
        return redirect(url_for('marketplace.marketplace'))

    try:
        db.session.delete(coupon_request)
        db.session.commit()
        flash('בקשת הקופון נמחקה בהצלחה.', 'success')
        log_user_activity("delete_coupon_request_success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting coupon request {id}: {e}")
        flash('אירעה שגיאה בעת מחיקת הבקשה.', 'danger')

    return redirect(url_for('marketplace.marketplace'))


@requests_bp.route('/request_coupon', methods=['GET', 'POST'])
@login_required
def request_coupon():
    """
    מסך בקשת קופון:
    - המשתמש בוחר חברה קיימת או 'other' להזנת חברה חדשה.
    - ממלא עלות מבוקשת, ערך מבוקש, אחוז הנחה, קוד קופון (לא חובה) והסבר נוסף.
    - נשמר לטבלת coupon_requests.
    """
    log_user_activity("request_coupon_view")

    form = RequestCouponForm()

    # שליפת חברות קיימות מה-DB והכנסתן ל-choices
    companies = Company.query.all()
    # נוסיף אופציה של "אחר" בסוף הרשימה
    form.company.choices = [(str(c.id), c.name) for c in companies] + [('other', 'אחר')]

    if form.validate_on_submit():
        # מקבלים ערכים מהטופס
        selected_company_id = form.company.data
        other_company_name = form.other_company.data.strip() if form.other_company.data else ''
        cost = form.cost.data
        value = form.value.data
        discount_percentage = form.discount_percentage.data
        code = form.code.data.strip() if form.code.data else ''
        description = form.description.data.strip() if form.description.data else ''

        # קובעים את שם החברה (אם בחרו "other" - ניקח מהטקסט, אחרת ניקח מה-DB)
        if selected_company_id == 'other':
            # משתמש הזין חברה חדשה
            company_name = other_company_name
            # אפשר לשמור גם כ-company object חדש, במידה ורוצים לעדכן בטבלת companies:
            # new_company = Company(name=company_name, image_path='default.png')
            # db.session.add(new_company)
            # db.session.flush()
            # ואז company_name = new_company.name
        else:
            # משתמש בחר חברה קיימת
            existing_company = Company.query.get_or_404(int(selected_company_id))
            company_name = existing_company.name

        # נרשום ל-DB את הבקשה
        coupon_req = CouponRequest(
            company=company_name,
            other_company=other_company_name,  # אם המשתמש באמת הזין משהו
            code=code,
            value=value if value else 0.0,
            cost=cost if cost else 0.0,
            description=description,
            user_id=current_user.id,
            date_requested=datetime.utcnow(),
            fulfilled=False
        )
        # אם רוצים גם לשמור discount_percentage ב-DB, צריך לוודא שיש עמודה כזו ב-CouponRequest
        # לדוגמה:
        # coupon_req.discount_percentage = discount_percentage

        try:
            db.session.add(coupon_req)
            db.session.commit()
            flash('בקשת הקופון נרשמה בהצלחה!', 'success')
            log_user_activity("request_coupon_submitted")
            return redirect(url_for('marketplace.marketplace'))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating coupon request: {e}")
            flash('אירעה שגיאה בעת שמירת הבקשה למסד הנתונים.', 'danger')

    # אם GET או נפלה שגיאת ולידציה, נציג את הטופס
    return render_template('request_coupon.html', form=form, companies=companies)

@requests_bp.route('/buy_slots', methods=['GET', 'POST'])
@login_required
def buy_slots():
    from app.forms import BuySlotsForm

    log_user_activity("buy_slots_view")

    form = BuySlotsForm()
    if form.validate_on_submit():
        try:
            slot_amount = int(form.slot_amount.data)
            if slot_amount not in [10, 20, 50]:
                flash('כמות סלוטים לא תקפה.', 'danger')
                return redirect(url_for('requests.buy_slots'))

            current_user.slots += slot_amount
            db.session.commit()
            flash(f'רכשת {slot_amount} סלוטים בהצלחה!', 'success')
            log_user_activity("buy_slots_success")
            return redirect(url_for('requests.buy_slots'))
        except ValueError:
            flash('כמות סלוטים לא תקפה.', 'danger')
            return redirect(url_for('requests.buy_slots'))

    return render_template('buy_slots.html', slots=current_user.slots, form=form)
