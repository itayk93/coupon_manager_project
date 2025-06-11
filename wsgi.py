# wsgi.py
from dotenv import load_dotenv
import os
from app import create_app
from telegram_bot import run_bot
import multiprocessing
import logging

# טוען את משתני הסביבה מה-.env
load_dotenv()

# הגדרת לוגר
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# יוצר מופע Flask מהפונקציה create_app שבקובץ app/__init__.py
app = create_app()

def run_flask():
    """הפעלת שרת ה-Flask"""
    app.run(host='0.0.0.0', port=5001)

if __name__ == '__main__':
    # הפעלת הבוט בתהליך נפרד
    bot_process = multiprocessing.Process(target=run_bot)
    bot_process.start()
    logger.info('הבוט פועל...')
    
    # הפעלת שרת ה-Flask
    run_flask()
