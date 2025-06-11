from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app.models import TelegramUser, User
from app.extensions import db
import secrets
from datetime import datetime, timezone, timedelta
import logging

telegram_bp = Blueprint('telegram', __name__)
logger = logging.getLogger(__name__)

def get_telegram_config():
    """Get Telegram configuration from environment variables"""
    config = {
        'bot_username': current_app.config.get('TELEGRAM_BOT_USERNAME'),
        'bot_token': current_app.config.get('TELEGRAM_BOT_TOKEN'),
        'chat_id': current_app.config.get('TELEGRAM_CHAT_ID')
    }
    missing = [k for k, v in config.items() if not v]
    if missing:
        logger.error(f"Missing Telegram configuration: {', '.join(missing)}")
        return None
    return config

@telegram_bp.route('/connect_telegram', methods=['GET'])
@login_required
def connect_telegram():
    """
    מציג את הדף להתחברות לבוט הטלגרם
    """
    config = get_telegram_config()
    if not config:
        return render_template('telegram/error.html', error="הבוט לא מוגדר כראוי. אנא פנה למנהל המערכת.")
    existing_connection = TelegramUser.query.filter_by(user_id=current_user.id).first()
    if existing_connection and existing_connection.is_verified:
        return render_template('telegram/already_connected.html')
    verification_token = secrets.token_urlsafe(32)
    if existing_connection:
        existing_connection.verification_token = verification_token
        existing_connection.verification_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        existing_connection.is_verified = False
    else:
        new_connection = TelegramUser(
            user_id=current_user.id,
            telegram_chat_id=0,  # יוגדר מאוחר יותר
            verification_token=verification_token,
            verification_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            ip_address=request.remote_addr,
            device_info=request.user_agent.string
        )
        db.session.add(new_connection)
    db.session.commit()
    return render_template('telegram/connect.html', 
                         verification_token=verification_token,
                         bot_username=config['bot_username'])

@telegram_bp.route('/verify_telegram', methods=['POST'])
def verify_telegram():
    """אימות משתמש טלגרם"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        # בדיקת שדות חובה
        required_fields = ['chat_id', 'token']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({
                'success': False,
                'error': f'Missing required fields: {", ".join(missing_fields)}'
            }), 400

        chat_id = data.get('chat_id')
        token = data.get('token')
        username = data.get('username')

        # חיפוש משתמש לפי טוקן
        telegram_user = TelegramUser.query.filter_by(verification_token=token).first()
        if not telegram_user:
            return jsonify({
                'success': False,
                'error': 'Invalid verification code'
            }), 400

        # בדיקת תאריך תפוגה
        if telegram_user.verification_expires_at < datetime.utcnow():
            return jsonify({
                'success': False,
                'error': 'Verification code has expired'
            }), 400

        # עדכון פרטי המשתמש
        telegram_user.telegram_chat_id = chat_id
        telegram_user.telegram_username = username
        telegram_user.is_verified = True
        telegram_user.last_interaction = datetime.utcnow()
        telegram_user.verification_token = None  # ניקוי הטוקן לאחר אימות מוצלח
        telegram_user.verification_expires_at = None  # ניקוי תאריך התפוגה

        try:
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'Telegram account verified successfully'
            })
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Database error in verify_telegram: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'Database error occurred'
            }), 500

    except Exception as e:
        current_app.logger.error(f"Error in verify_telegram: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@telegram_bp.route('/api/telegram_coupons', methods=['POST'])
def get_telegram_coupons():
    """מחזיר את הקופונים של המשתמש"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        chat_id = data.get('chat_id')
        if not chat_id:
            return jsonify({'success': False, 'error': 'Missing chat_id'}), 400

        # חיפוש המשתמש לפי chat_id
        telegram_user = TelegramUser.query.filter_by(
            telegram_chat_id=chat_id,
            is_verified=True
        ).first()

        if not telegram_user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        # קבלת הקופונים של המשתמש
        user = User.query.get(telegram_user.user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        coupons = []
        for coupon in user.coupons:
            coupons.append({
                'code': coupon.code,
                'value': coupon.value,
                'company': coupon.company.name if coupon.company else 'Unknown',
                'expiration': coupon.expiration_date.strftime('%Y-%m-%d') if coupon.expiration_date else None,
                'status': coupon.status,
                'is_available': coupon.is_available
            })

        return jsonify({
            'success': True,
            'coupons': coupons
        })

    except Exception as e:
        logger.error(f"Error in get_telegram_coupons: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500 