# wsgi.py
import os
import multiprocessing
import logging
from app import create_app, db
from app.telegram_bot import start_bot
from datetime import datetime, timezone

# הגדרת לוגר
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# יצירת אפליקציית Flask
app = create_app()

def run_flask():
    """הפעלת שרת ה-Flask"""
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

def run_bot():
    """הפעלת בוט הטלגרם"""
    try:
        logger.info("Starting Telegram bot...")
        start_bot()
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")

if __name__ == '__main__':
    # הפעלת הבוט בתהליך נפרד
    bot_process = multiprocessing.Process(target=run_bot)
    bot_process.start()
    
    # הפעלת שרת ה-Flask
    run_flask()
