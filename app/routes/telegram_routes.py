from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app.models import TelegramUser
from app.extensions import db
import secrets
from datetime import datetime, timezone, timedelta
import logging
import random

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

@telegram_bp.route('/bot', methods=['GET'])
@login_required
def telegram_bot_page():
    """
    עמוד שיווקי לבוט הטלגרם
    """
    from flask_wtf.csrf import generate_csrf
    
    config = get_telegram_config()
    if not config:
        return render_template('telegram/error.html', error="הבוט לא מוגדר כראוי. אנא פנה למנהל המערכת.")
    
    # בדיקה האם המשתמש כבר מחובר
    existing_connection = TelegramUser.query.filter_by(user_id=current_user.id).first()
    is_connected = existing_connection and existing_connection.is_verified
    
    return render_template('telegram/bot_landing.html', 
                         bot_username=config['bot_username'],
                         is_connected=is_connected,
                         csrf_token=generate_csrf)

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
    verification_token = ''.join(random.choices('0123456789', k=6))
    if existing_connection:
        existing_connection.verification_token = verification_token
        existing_connection.verification_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        existing_connection.is_verified = False
        existing_connection.disconnected_at = None
        existing_connection.is_disconnected = False
    else:
        new_connection = TelegramUser(
            user_id=current_user.id,
            telegram_chat_id=0,  # יוגדר מאוחר יותר
            verification_token=verification_token,
            verification_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            ip_address=request.remote_addr,
            device_info=request.user_agent.string
        )
        db.session.add(new_connection)
    db.session.commit()
    return render_template('telegram/connect.html', 
                         verification_token=verification_token,
                         bot_username=config['bot_username'])

@telegram_bp.route('/generate_token', methods=['POST'])
@login_required
def generate_token():
    """
    API endpoint לייצור טוקן חדש עבור עמוד הבוט
    """
    try:
        config = get_telegram_config()
        if not config:
            return jsonify({'success': False, 'error': 'הבוט לא מוגדר כראוי'}), 500
        
        # יצירת קוד אימות אקראי
        verification_token = ''.join(random.choices('0123456789', k=6))
        
        # בדיקה האם יש חיבור קיים
        existing_connection = TelegramUser.query.filter_by(user_id=current_user.id).first()
        
        if existing_connection:
            existing_connection.verification_token = verification_token
            existing_connection.verification_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
            existing_connection.is_verified = False
            existing_connection.disconnected_at = None
            existing_connection.is_disconnected = False
        else:
            new_connection = TelegramUser(
                user_id=current_user.id,
                telegram_chat_id=0,
                verification_token=verification_token,
                verification_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                ip_address=request.remote_addr,
                device_info=request.user_agent.string
            )
            db.session.add(new_connection)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'token': verification_token,
            'expires_in_minutes': 10
        })
        
    except Exception as e:
        logger.error(f"Error in generate_token: {str(e)}")
        return jsonify({'success': False, 'error': 'אירעה שגיאה ביצירת הטוקן'}), 500

@telegram_bp.route('/verify_telegram', methods=['POST'])
def verify_telegram():
    """מאמת את קוד האימות מהבוט"""
    try:
        data = request.get_json()
        chat_id = data.get('chat_id')
        username = data.get('username')
        token = data.get('token')
        
        logger.info(f"Verifying token: {token} for chat_id: {chat_id}")
        
        if not all([chat_id, token]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
            
        # חיפוש המשתמש לפי הטוקן
        telegram_user = TelegramUser.query.filter_by(verification_token=token).first()
        
        if not telegram_user:
            logger.error(f"Token not found: {token}")
            return jsonify({'success': False, 'error': 'Invalid token'}), 400
            
        if telegram_user.is_blocked():
            logger.error(f"User is blocked: {telegram_user.user_id}")
            return jsonify({'success': False, 'error': 'Too many attempts. Please try again later.'}), 429
            
        if telegram_user.verification_expires_at < datetime.now(timezone.utc):
            logger.error(f"Token expired: {token}")
            return jsonify({'success': False, 'error': 'Token expired'}), 400
            
        # עדכון פרטי המשתמש
        telegram_user.telegram_chat_id = chat_id
        telegram_user.telegram_username = username
        telegram_user.is_verified = True
        telegram_user.reset_verification_attempts()
        telegram_user.last_interaction = datetime.now(timezone.utc)
        
        db.session.commit()
        
        logger.info(f"Successfully verified user: {telegram_user.user_id}")
        return jsonify({
            'success': True,
            'message': 'Successfully connected to Telegram bot'
        })
        
    except Exception as e:
        logger.error(f"Error in verify_telegram: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@telegram_bp.route('/api/telegram_coupons', methods=['POST'])
def get_telegram_coupons():
    data = request.get_json()
    chat_id = data.get('chat_id')
    if not chat_id:
        return jsonify({'success': False, 'error': 'Missing chat_id'}), 400
    telegram_user = TelegramUser.query.filter_by(telegram_chat_id=chat_id, is_verified=True).first()
    if not telegram_user:
        return jsonify({'success': False, 'error': 'User not verified'}), 403
    user = telegram_user.user
    coupons = user.coupons if user else []
    def coupon_to_dict(c):
        return {
            'id': c.id,
            'code': c.code,
            'description': c.description,
            'value': c.value,
            'cost': c.cost,
            'company': c.company,
            'expiration': c.expiration.isoformat() if c.expiration else None,
            'status': c.status,
            'is_available': c.is_available
        }
    return jsonify({'success': True, 'coupons': [coupon_to_dict(c) for c in coupons]})