# wsgi.py
import os
import multiprocessing
import logging
from app import create_app
from telegram_bot import run_bot

# הגדרת לוגר
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# יצירת מופע Flask
app = create_app()

def run_telegram_bot():
    """הפעלת בוט טלגרם"""
    try:
        logger.info('Starting Telegram bot...')
        run_bot()
    except Exception as e:
        logger.error(f"Error running Telegram bot: {e}")

# הפעלת הבוט בתהליך נפרד
if os.getenv('FLASK_ENV') != 'development':
    logger.info('Starting Telegram bot in production mode...')
    bot_process = multiprocessing.Process(target=run_telegram_bot)
    bot_process.start()

if __name__ == '__main__':
    # הפעלת בוט טלגרם בתהליך נפרד (רק בסביבת פיתוח)
    if os.getenv('FLASK_ENV') == 'development':
        bot_process = multiprocessing.Process(target=run_telegram_bot)
        bot_process.start()
    
    # הפעלת שרת Flask
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5001)))
