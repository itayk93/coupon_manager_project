# wsgi.py
import os
import logging
import multiprocessing
from app import create_app
from telegram_bot import run_bot

# הגדרת לוגר
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# יצירת אפליקציית Flask
app = create_app()


def start_telegram_bot():
    """הפעלת הבוט טלגרם בתהליך נפרד"""
    try:
        logger.info("Starting Telegram bot...")
        logger.info(f"Bot enabled: {os.getenv('ENABLE_BOT', 'True')}")
        logger.info(f"Bot token exists: {bool(os.getenv('TELEGRAM_BOT_TOKEN'))}")
        logger.info(f"Bot username exists: {bool(os.getenv('TELEGRAM_BOT_USERNAME'))}")
        logger.info(f"Database URL exists: {bool(os.getenv('DATABASE_URL'))}")
        run_bot()
    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}")
        logger.exception("Full traceback:")

if __name__ == '__main__':
    # הפעלת הבוט בתהליך נפרד
    bot_process = multiprocessing.Process(target=start_telegram_bot)
    bot_process.daemon = True  # התהליך ייסגר כשהאפליקציה נסגרת
    bot_process.start()
    
    # הפעלת שרת Flask
    app.run(host='0.0.0.0', port=10000)
