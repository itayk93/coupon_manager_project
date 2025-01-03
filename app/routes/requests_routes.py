from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import logging

from app.models import CouponRequest, User, Company, db
from app.forms import DeleteCouponRequestForm
from app.helpers import send_coupon_purchase_request_email, get_geo_location  # או הגדר כאן את get_geo_location

requests_bp = Blueprint('requests', __name__)
logger = logging.getLogger(__name__)

def log_user_activity(action, coupon_id=None):
    """
    פונקציה מרכזית לרישום activity log.
    """
    try:
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent', '')
        geo_location = get_geo_location(ip_address) if ip_address else None

        activity = {
            "user_id": current_user.id if current_user.is_authenticated else None,
            "coupon_id": coupon_id,
            "timestamp": datetime.utcnow(),
            "action": action,
            "device": user_agent[:50] if user_agent else None,
            "browser": user_agent.split(' ')[0][:50] if user_agent else None,
            "ip_address": ip_address[:45] if ip_address else None,
            "geo_location": geo_location[:100] if geo_location else None
        }

        db.session.execute(
            db.text("""
                INSERT INTO user_activities
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address, geo_location)
                VALUES
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address, :geo_location)
            """),
            activity
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
    log_user_activity("request_coupon_view")

    if request.method == 'POST':
        from app.models import Coupon, Transaction, Notification  # import כאן לצורך הדגמה
        coupon_id = request.form.get('coupon_id', type=int)
        coupon = Coupon.query.get_or_404(coupon_id)

        if coupon.user_id == current_user.id:
            flash('אינך יכול לקנות את הקופון שלך.', 'warning')
            return redirect(url_for('marketplace.marketplace'))

        if not coupon.is_available or not coupon.is_for_sale:
            flash('קופון זה אינו זמין למכירה.', 'danger')
            return redirect(url_for('marketplace.marketplace'))

        transaction = Transaction(
            coupon_id=coupon.id,
            buyer_id=current_user.id,
            seller_id=coupon.user_id,
            status='ממתין לאישור המוכר'
        )
        db.session.add(transaction)
        coupon.is_available = False

        notification = Notification(
            user_id=coupon.user_id,
            message=f"{current_user.first_name} {current_user.last_name} מבקש לקנות את הקופון שלך.",
            link=url_for('marketplace.my_transactions')
        )
        db.session.add(notification)
        db.session.commit()

        seller = coupon.user
        buyer = current_user
        try:
            send_coupon_purchase_request_email(seller, buyer, coupon)
            flash('בקשתך נשלחה והמוכר יקבל הודעה גם במייל.', 'success')
            log_user_activity("request_coupon_submitted", coupon_id=coupon.id)
        except Exception as e:
            requests_bp.logger.error(f'שגיאה בשליחת מייל למוכר: {e}')
            flash('הבקשה נשלחה אך לא הצלחנו לשלוח הודעה למוכר במייל.', 'warning')

        return redirect(url_for('marketplace.my_transactions'))

    return render_template('request_coupon.html')

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
