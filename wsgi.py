# wsgi.py
import os
import multiprocessing
import logging
from app import create_app
import sys

# הגדרת לוגר
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def run_flask():
    """הפעלת שרת Flask"""
    app = create_app()
    return app

def run_bot():
    """הפעלת בוט טלגרם"""
    try:
        # מניעת הפעלה כפולה של הבוט
        if os.environ.get('TELEGRAM_BOT_RUNNING'):
            logger.info("Telegram bot is already running")
            return

        os.environ['TELEGRAM_BOT_RUNNING'] = '1'
        from telegram_bot import run_bot as start_telegram_bot
        logger.info("Starting Telegram bot...")
        start_telegram_bot()
    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}")
    finally:
        os.environ.pop('TELEGRAM_BOT_RUNNING', None)

if __name__ == '__main__':
    # הפעלת שרת Flask
    app = run_flask()
    
    # הפעלת בוט טלגרם בתהליך נפרד רק אם אנחנו לא בסביבת פיתוח
    if os.environ.get('FLASK_ENV') != 'development':
        bot_process = multiprocessing.Process(target=run_bot)
        bot_process.daemon = True  # הגדרת התהליך כ-daemon כדי שיסגר אוטומטית כשהתהליך הראשי נסגר
        bot_process.start()
    
    # הפעלת שרת Flask
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
else:
    # עבור gunicorn
    app = run_flask()
