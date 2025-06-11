import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import requests
from datetime import datetime, timezone

# טעינת משתני סביבה
load_dotenv()

# הגדרת לוגר
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# קבלת טוקן הבוט ממשתני הסביבה
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_URL = os.getenv('API_URL', 'https://couponmasteril.com')

# הגדרת headers לבקשות HTTP
HEADERS = {
    'User-Agent': 'TelegramBot/1.0',
    'Content-Type': 'application/json'
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בפקודת /start"""
    try:
        user = update.effective_user
        logger.info(f"Received /start command from user {user.username if user else 'None'}")
        
        welcome_message = (
            "ברוכים הבאים לבוט קופון מאסטר! 🎉\n\n"
            "כדי להתחבר לבוט, אנא בצע את הפעולות הבאות:\n"
            "1. היכנס לאתר https://couponmasteril.com\n"
            "2. התחבר או צור חשבון\n"
            "3. לחץ על 'התחבר לבוט טלגרם' בפרופיל שלך\n"
            "4. העתק את קוד האימות שתקבל\n"
            "5. שלח את הקוד לבוט זה\n\n"
            "אחרי שתתחבר, תוכל לקבל עדכונים על קופונים חדשים ומועדפים!"
        )
        
        await update.message.reply_text(welcome_message)
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")
        await update.message.reply_text("אירעה שגיאה. אנא נסה שוב מאוחר יותר.")

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בקוד אימות"""
    try:
        code = update.message.text.strip()
        chat_id = update.effective_chat.id
        username = update.effective_user.username if update.effective_user else None
        
        logger.info(f"Sending verification request to {API_URL}/verify_telegram")
        logger.info(f"Request data: chat_id={chat_id}, username={username}, token={code}")
        
        response = requests.post(
            f"{API_URL}/verify_telegram",
            json={
                'chat_id': chat_id,
                'username': username,
                'token': code
            },
            headers=HEADERS
        )
        
        logger.info(f"Server response status code: {response.status_code}")
        logger.info(f"Server response content: {response.text}")
        
        if response.status_code == 200:
            await update.message.reply_text("התחברת בהצלחה! 🎉\nמעכשיו תקבל עדכונים על קופונים חדשים ומועדפים.")
        else:
            error_msg = response.json().get('error', 'אירעה שגיאה בהתחברות')
            await update.message.reply_text(f"שגיאה: {error_msg}")
            
    except Exception as e:
        logger.error(f"Error handling code: {str(e)}")
        await update.message.reply_text("אירעה שגיאה. אנא נסה שוב מאוחר יותר.")

def run_bot():
    """הפעלת הבוט"""
    try:
        # בדיקה אם הבוט כבר רץ
        if os.environ.get('TELEGRAM_BOT_RUNNING'):
            logger.info("Telegram bot is already running")
            return

        os.environ['TELEGRAM_BOT_RUNNING'] = '1'
        
        # יצירת אפליקציית הבוט
        application = Application.builder().token(TOKEN).build()
        
        # הוספת handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))
        
        # הפעלת הבוט
        logger.info("הבוט פועל...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Error running bot: {str(e)}")
    finally:
        os.environ.pop('TELEGRAM_BOT_RUNNING', None)

if __name__ == '__main__':
    run_bot() 