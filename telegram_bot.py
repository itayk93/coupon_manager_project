import os
import logging
import requests
import asyncio
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# הגדרת לוגר
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# טעינת משתני סביבה
load_dotenv()

# הגדרות
API_URL = os.getenv('API_URL', 'https://couponmasteril.com')  # שימוש בשרת הייצור כברירת מחדל
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_BOT_USERNAME = os.getenv('TELEGRAM_BOT_USERNAME')

# הגדרת headers לכל הבקשות
HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'X-Requested-With': 'XMLHttpRequest'  # הוספת header זה עוקף את בדיקת ה-CSRF
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בפקודת /start"""
    logger.info(f"Received /start command from user {update.message.from_user.username}")
    await update.message.reply_text(
        'ברוך הבא לבוט קופון מאסטר! 🎉\n\n'
        'כדי להתחבר לבוט, עליך:\n'
        '1. להיכנס לאתר https://couponmasteril.com\n'
        '2. להירשם או להתחבר לחשבון שלך\n'
        '3. ללחוץ על "התחבר לבוט טלגרם"\n'
        '4. להעתיק את קוד האימות ולשלוח אותו כאן\n\n'
        'אם כבר נרשמת, פשוט שלח את קוד האימות שקיבלת מהאתר.'
    )

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בקוד אימות שנשלח על ידי המשתמש"""
    token = update.message.text.strip()
    chat_id = update.message.chat_id
    username = update.message.from_user.username

    # שליחת הקוד לשרת לאימות
    try:
        logger.info(f"Sending verification request to {API_URL}/verify_telegram")
        logger.info(f"Request data: chat_id={chat_id}, username={username}, token={token}")
        
        response = requests.post(
            f'{API_URL}/verify_telegram',
            json={
                'chat_id': chat_id,
                'username': username,
                'token': token
            },
            headers=HEADERS,
            timeout=10
        )
        
        logger.info(f"Server response status code: {response.status_code}")
        logger.info(f"Server response content: {response.text}")
        
        if response.ok:
            try:
                data = response.json()
                if data.get('success'):
                    await update.message.reply_text('✅ התחברת בהצלחה!')
                    # קבלת הקופונים
                    await get_coupons(update, context)
                else:
                    error_msg = data.get('error', 'שגיאה לא ידועה')
                    if 'not registered' in error_msg.lower() or 'not found' in error_msg.lower():
                        await update.message.reply_text(
                            '❌ נראה שעדיין לא נרשמת לאתר!\n\n'
                            'כדי להתחבר לבוט, עליך:\n'
                            '1. להיכנס לאתר https://couponmasteril.com\n'
                            '2. להירשם או להתחבר לחשבון שלך\n'
                            '3. ללחוץ על "התחבר לבוט טלגרם"\n'
                            '4. להעתיק את קוד האימות ולשלוח אותו כאן'
                        )
                    else:
                        await update.message.reply_text(f'❌ שגיאה: {error_msg}')
            except ValueError as e:
                logger.error(f"JSON parsing error: {e}")
                logger.error(f"Response content: {response.text}")
                await update.message.reply_text('❌ אירעה שגיאה בעיבוד התשובה מהשרת')
        else:
            if response.status_code == 404:
                await update.message.reply_text(
                    '❌ נראה שעדיין לא נרשמת לאתר!\n\n'
                    'כדי להתחבר לבוט, עליך:\n'
                    '1. להיכנס לאתר https://couponmasteril.com\n'
                    '2. להירשם או להתחבר לחשבון שלך\n'
                    '3. ללחוץ על "התחבר לבוט טלגרם"\n'
                    '4. להעתיק את קוד האימות ולשלוח אותו כאן'
                )
            else:
                logger.error(f"Server error: {response.status_code}")
                logger.error(f"Response content: {response.text}")
                await update.message.reply_text(f'❌ שגיאת שרת: {response.status_code}')
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error: {e}")
        await update.message.reply_text('❌ אירעה שגיאה בתקשורת עם השרת')
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(f"Error details: {str(e)}")
        await update.message.reply_text('❌ אירעה שגיאה לא צפויה')

async def get_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """שולף את הקופונים של המשתמש"""
    chat_id = update.message.chat_id
    
    try:
        response = requests.post(
            f'{API_URL}/api/telegram_coupons',
            json={'chat_id': chat_id},
            headers=HEADERS,
            timeout=10
        )
        
        if response.ok and response.json().get('success'):
            coupons = response.json().get('coupons', [])
            if coupons:
                message = "הנה הקופונים שלך:\n\n"
                for coupon in coupons:
                    message += (
                        f"🏷️ קופון: {coupon['code']}\n"
                        f"💰 ערך: {coupon['value']}₪\n"
                        f"🏢 חברה: {coupon['company']}\n"
                        f"📅 תפוגה: {coupon['expiration'] or 'ללא'}\n"
                        f"📝 סטטוס: {coupon['status']}\n"
                        f"{'✅ זמין' if coupon['is_available'] else '❌ לא זמין'}\n\n"
                    )
                await update.message.reply_text(message)
            else:
                await update.message.reply_text('לא נמצאו קופונים')
        else:
            error_msg = response.json().get('error', 'שגיאה לא ידועה')
            await update.message.reply_text(f'❌ שגיאה: {error_msg}')
    except Exception as e:
        logger.error(f"Error in get_coupons: {e}")
        await update.message.reply_text('❌ אירעה שגיאה בתקשורת עם השרת')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מציג את רשימת הפקודות הזמינות"""
    help_text = (
        "📋 רשימת הפקודות הזמינות:\n\n"
        "/start - התחלת שיחה עם הבוט\n"
        "/help - הצגת רשימת הפקודות\n"
        "/coupons - הצגת הקופונים שלך\n\n"
        "כדי להתחבר, שלח את קוד האימות שקיבלת מהאתר."
    )
    await update.message.reply_text(help_text)

async def coupons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מציג את הקופונים של המשתמש"""
    await get_coupons(update, context)

def run_bot():
    """הפעלת הבוט"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN found in environment variables")
        return

    # יצירת event loop חדש
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # הוספת handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('coupons', coupons_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
    
    # הפעלת הבוט
    logger.info('הבוט פועל...')
    app.run_polling(drop_pending_updates=True)  # הוספת drop_pending_updates כדי למנוע שגיאות Conflict

if __name__ == '__main__':
    run_bot() 