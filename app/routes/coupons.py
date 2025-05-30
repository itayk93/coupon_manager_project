from flask import jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app.models.user_tour_progress import UserTourProgress
from app.models.database import db

@coupons_bp.route('/update_coupon_detail_timestamp', methods=['POST'])
@login_required
def update_coupon_detail_timestamp():
    try:
        # Get the user's tour progress record
        tour_progress = UserTourProgress.query.filter_by(user_id=current_user.id).first()
        
        if tour_progress:
            # Update the timestamp
            tour_progress.coupon_detail_timestamp = datetime.utcnow()
            db.session.commit()
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Tour progress record not found'}), 404
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500 

@coupons_bp.route('/coupon/<int:id>')
@login_required
def coupon_detail(id):
    coupon = Coupon.query.get_or_404(id)
    is_owner = coupon.user_id == current_user.id
    
    # Get the user's tour progress
    tour_progress = UserTourProgress.query.filter_by(user_id=current_user.id).first()
    coupon_detail_timestamp = tour_progress.coupon_detail_timestamp if tour_progress else None
    
    # Rest of your existing code...
    
    return render_template('coupon_detail.html',
                         coupon=coupon,
                         is_owner=is_owner,
                         coupon_detail_timestamp=coupon_detail_timestamp,
                         # ... rest of your template variables ...
                         ) 