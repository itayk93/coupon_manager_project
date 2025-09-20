# app/routes/api_routes.py

from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from app.models import User, Coupon, Company, CouponRequest, Transaction
from app.extensions import db
from datetime import datetime
import logging

api_bp = Blueprint('api', __name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@api_bp.route('/api/auth/login', methods=['POST'])
def api_login():
    """API endpoint for user authentication"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        # Find user by email
        user = User.query.filter_by(email=email).first()
        
        if not user:
            logger.warning(f"Login attempt for non-existent user: {email}")
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Check password
        if not user.check_password(password):
            logger.warning(f"Failed login attempt for user: {email}")
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Check if user is confirmed
        if not user.is_confirmed:
            return jsonify({'error': 'Please confirm your email address'}), 401
        
        # Check if user is deleted
        if user.is_deleted:
            return jsonify({'error': 'Account has been deleted'}), 401
        
        # Login successful
        login_user(user, remember=True)
        logger.info(f"Successful login for user: {email}")
        
        # Return user data
        user_data = {
            'id': user.id,
            'email': user.email,
            'firstName': user.first_name,
            'lastName': user.last_name,
            'age': user.age,
            'gender': user.gender,
            'profileDescription': user.profile_description,
            'profileImage': user.profile_image,
            'isConfirmed': user.is_confirmed,
            'isAdmin': user.is_admin,
            'isDeleted': user.is_deleted,
            'slots': user.slots,
            'slotsAutomaticCoupons': user.slots_automatic_coupons,
            'newsletterSubscription': user.newsletter_subscription,
            'telegramMonthlySummary': user.telegram_monthly_summary,
            'showWhatsappBanner': user.show_whatsapp_banner,
            'createdAt': user.created_at.isoformat() if user.created_at else None,
            'daysSinceRegister': user.days_since_register
        }
        
        return jsonify({
            'message': 'Login successful',
            'user': user_data
        }), 200
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@api_bp.route('/api/auth/register', methods=['POST'])
def api_register():
    """API endpoint for user registration"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        email = data.get('email')
        password = data.get('password')
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        
        if not all([email, password, first_name, last_name]):
            return jsonify({'error': 'All fields are required'}), 400
        
        # Check if user already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return jsonify({'error': 'User with this email already exists'}), 409
        
        # Create new user
        new_user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_confirmed=True,  # For API registration, auto-confirm
            slots=0,
            slots_automatic_coupons=50
        )
        new_user.set_password(password)
        
        db.session.add(new_user)
        db.session.commit()
        
        logger.info(f"New user registered via API: {email}")
        
        # Return user data
        user_data = {
            'id': new_user.id,
            'email': new_user.email,
            'firstName': new_user.first_name,
            'lastName': new_user.last_name,
            'isConfirmed': new_user.is_confirmed,
            'isAdmin': new_user.is_admin,
            'slots': new_user.slots,
            'slotsAutomaticCoupons': new_user.slots_automatic_coupons,
            'createdAt': new_user.created_at.isoformat() if new_user.created_at else None
        }
        
        return jsonify({
            'message': 'Registration successful',
            'user': user_data
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Registration error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@api_bp.route('/api/auth/logout', methods=['POST'])
@login_required
def api_logout():
    """API endpoint for user logout"""
    try:
        logout_user()
        return jsonify({'message': 'Logout successful'}), 200
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@api_bp.route('/api/coupons/user/<int:user_id>', methods=['GET'])
@login_required
def api_get_user_coupons(user_id):
    """Get coupons for a specific user"""
    try:
        # Check if current user can access these coupons
        if current_user.id != user_id and not current_user.is_admin:
            return jsonify({'error': 'Unauthorized'}), 403
        
        coupons = Coupon.query.filter_by(user_id=user_id).order_by(Coupon.date_added.desc()).all()
        
        coupon_list = []
        for coupon in coupons:
            coupon_data = {
                'id': coupon.id,
                'code': coupon.code,
                'description': coupon.description,
                'value': coupon.value,
                'cost': coupon.cost,
                'company': coupon.company,
                'expiration': coupon.expiration.isoformat() if coupon.expiration else None,
                'dateAdded': coupon.date_added.isoformat() if coupon.date_added else None,
                'usedValue': coupon.used_value,
                'status': coupon.status,
                'isAvailable': coupon.is_available,
                'isForSale': coupon.is_for_sale,
                'purpose': coupon.purpose,
                'remainingValue': coupon.remaining_value,
                'usagePercentage': coupon.usage_percentage
            }
            coupon_list.append(coupon_data)
        
        return jsonify({'coupons': coupon_list}), 200
        
    except Exception as e:
        logger.error(f"Error fetching user coupons: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@api_bp.route('/api/coupons', methods=['POST'])
@login_required
def api_add_coupon():
    """Add a new coupon"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        required_fields = ['code', 'value', 'cost', 'company']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        new_coupon = Coupon(
            code=data['code'],
            description=data.get('description'),
            value=float(data['value']),
            cost=float(data['cost']),
            company=data['company'],
            expiration=datetime.fromisoformat(data['expiration'].replace('Z', '+00:00')) if data.get('expiration') else None,
            user_id=current_user.id,
            purpose=data.get('purpose'),
            status='פעיל'
        )
        
        db.session.add(new_coupon)
        db.session.commit()
        
        logger.info(f"New coupon added via API by user {current_user.id}")
        
        return jsonify({
            'message': 'Coupon added successfully',
            'coupon': {
                'id': new_coupon.id,
                'code': new_coupon.code,
                'value': new_coupon.value,
                'company': new_coupon.company
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding coupon: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@api_bp.route('/api/coupons/<int:coupon_id>/use', methods=['POST'])
@login_required
def api_use_coupon(coupon_id):
    """Mark coupon as used (partial or full)"""
    try:
        data = request.get_json()
        if not data or 'used_amount' not in data:
            return jsonify({'error': 'used_amount is required'}), 400
        
        used_amount = float(data['used_amount'])
        
        coupon = Coupon.query.get(coupon_id)
        if not coupon:
            return jsonify({'error': 'Coupon not found'}), 404
        
        # Check if current user owns this coupon
        if coupon.user_id != current_user.id and not current_user.is_admin:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Update used value
        coupon.used_value += used_amount
        
        # Update status if fully used
        if coupon.used_value >= coupon.value:
            coupon.status = 'נוצל'
        
        db.session.commit()
        
        logger.info(f"Coupon {coupon_id} usage updated by user {current_user.id}")
        
        return jsonify({
            'message': 'Coupon usage updated',
            'coupon': {
                'id': coupon.id,
                'usedValue': coupon.used_value,
                'remainingValue': coupon.remaining_value,
                'status': coupon.status
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating coupon usage: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@api_bp.route('/api/companies', methods=['GET'])
def api_get_companies():
    """Get all companies"""
    try:
        companies = Company.query.order_by(Company.name).all()
        
        company_list = []
        for company in companies:
            company_data = {
                'id': company.id,
                'name': company.name,
                'imagePath': company.image_path,
                'companyCount': company.company_count
            }
            company_list.append(company_data)
        
        return jsonify({'companies': company_list}), 200
        
    except Exception as e:
        logger.error(f"Error fetching companies: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@api_bp.route('/api/marketplace/coupons', methods=['GET'])
def api_get_marketplace_coupons():
    """Get marketplace coupons"""
    try:
        coupons = Coupon.query.filter_by(
            is_for_sale=True,
            is_available=True,
            status='פעיל'
        ).order_by(Coupon.date_added.desc()).all()
        
        coupon_list = []
        for coupon in coupons:
            coupon_data = {
                'id': coupon.id,
                'description': coupon.description,
                'value': coupon.value,
                'cost': coupon.cost,
                'company': coupon.company,
                'expiration': coupon.expiration.isoformat() if coupon.expiration else None,
                'remainingValue': coupon.remaining_value
            }
            coupon_list.append(coupon_data)
        
        return jsonify({'coupons': coupon_list}), 200
        
    except Exception as e:
        logger.error(f"Error fetching marketplace coupons: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@api_bp.route('/api/marketplace/requests', methods=['GET'])
def api_get_coupon_requests():
    """Get coupon requests"""
    try:
        requests = CouponRequest.query.filter_by(fulfilled=False).order_by(CouponRequest.date_requested.desc()).all()
        
        request_list = []
        for req in requests:
            request_data = {
                'id': req.id,
                'company': req.company,
                'value': req.value,
                'cost': req.cost,
                'description': req.description,
                'dateRequested': req.date_requested.isoformat() if req.date_requested else None
            }
            request_list.append(request_data)
        
        return jsonify({'requests': request_list}), 200
        
    except Exception as e:
        logger.error(f"Error fetching coupon requests: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@api_bp.route('/api/statistics/user/<int:user_id>', methods=['GET'])
@login_required
def api_get_user_statistics(user_id):
    """Get user statistics"""
    try:
        # Check if current user can access these statistics
        if current_user.id != user_id and not current_user.is_admin:
            return jsonify({'error': 'Unauthorized'}), 403
        
        coupons = Coupon.query.filter_by(user_id=user_id).all()
        
        total_value = sum(coupon.value for coupon in coupons)
        total_savings = sum(max(0, coupon.value - coupon.cost) for coupon in coupons)
        total_used = sum(coupon.used_value for coupon in coupons)
        total_remaining = sum(coupon.remaining_value for coupon in coupons)
        
        active_coupons = [c for c in coupons if c.status == 'פעיל']
        expiring_soon = [c for c in active_coupons if c.expiration and 
                        (c.expiration - datetime.now().date()).days <= 7]
        
        stats = {
            'totalValue': total_value,
            'totalSavings': total_savings,
            'totalUsed': total_used,
            'totalRemaining': total_remaining,
            'totalCoupons': len(coupons),
            'activeCoupons': len(active_coupons),
            'expiringSoon': len(expiring_soon),
            'averageDiscount': (total_savings / total_value * 100) if total_value > 0 else 0
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        logger.error(f"Error fetching user statistics: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500