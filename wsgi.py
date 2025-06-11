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

# הגדרת דגל להפעלת הבוט - שים True כדי להפעיל את הבוט, False כדי לכבות אותו
ENABLE_BOT = True

def start_telegram_bot():
    """הפעלת הבוט טלגרם בתהליך נפרד"""
    try:
        logger.info("Starting Telegram bot...")
        run_bot()
    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}")

# הפעלת הבוט רק אם הדגל מופעל
if ENABLE_BOT:
    # הפעלת הבוט בתהליך נפרד
    bot_process = multiprocessing.Process(target=start_telegram_bot)
    bot_process.daemon = True  # התהליך ייסגר כשהאפליקציה נסגרת
    bot_process.start()

if __name__ == '__main__':
    # הפעלת שרת Flask
    app.run(host='0.0.0.0', port=10000)
