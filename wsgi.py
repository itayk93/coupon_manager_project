# wsgi.py
import os
import logging
from app import create_app
from telegram_bot import run_bot
import multiprocessing
import signal
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

def run_telegram_bot():
    """הפעלת בוט טלגרם"""
    try:
        run_bot()
    except Exception as e:
        logger.error(f"Error in telegram bot process: {str(e)}")

def signal_handler(signum, frame):
    """טיפול בסיגנלים"""
    logger.info(f"Received signal {signum}")
    sys.exit(0)

if __name__ == '__main__':
    # הגדרת handler לסיגנלים
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # יצירת אפליקציית Flask
    app = run_flask()
    
    # הפעלת בוט טלגרם בתהליך נפרד רק אם לא בסביבת פיתוח
    if os.environ.get('FLASK_ENV') != 'development':
        bot_process = multiprocessing.Process(target=run_telegram_bot)
        bot_process.start()
        logger.info("Started Telegram bot in separate process")
    
    # הפעלת שרת Flask
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
