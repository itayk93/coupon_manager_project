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

def run_flask():
    """הפעלת שרת ה-Flask"""
    app = create_app()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

def run_telegram_bot():
    """הפעלת בוט הטלגרם"""
    try:
        run_bot()
    except Exception as e:
        logger.error(f"Error running Telegram bot: {str(e)}")

# יצירת אפליקציית Flask
app = create_app()

if __name__ == '__main__':
    # הפעלת שרת ה-Flask
    flask_process = multiprocessing.Process(target=run_flask)
    flask_process.start()
    
    # הפעלת בוט הטלגרם
    bot_process = multiprocessing.Process(target=run_telegram_bot)
    bot_process.start()
    
    # המתנה לסיום התהליכים
    flask_process.join()
    bot_process.join()
