import os
import logging
import requests
import asyncio
import psycopg2
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
import pytz
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import asyncpg
from enum import Enum
import httpx
import re
from fuzzywuzzy import fuzz

# Import GPT analysis function
import sys
sys.path.append('/app')
from app.helpers import extract_coupon_detail_sms

# Load environment variables
load_dotenv()

# Setup detailed logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('telegram_bot.log')
    ]
)

# Setup specific logger for httpx
httpx_logger = logging.getLogger('httpx')
httpx_logger.setLevel(logging.INFO)

# Setup specific logger for bot
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuration
API_URL = os.getenv('API_URL', 'https://couponmasteril.com')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_BOT_USERNAME = os.getenv('TELEGRAM_BOT_USERNAME')
ENABLE_BOT = os.getenv('ENABLE_BOT', 'True').lower() == 'true'

# Session timeout configuration - configurable via environment variable
SESSION_TIMEOUT_MINUTES = int(os.getenv('SESSION_TIMEOUT_MINUTES', '10080'))

# Reminder time configuration (hour and minute in Israel time)
REMINDER_HOUR = int(os.getenv('REMINDER_HOUR', '10'))
REMINDER_MINUTE = int(os.getenv('REMINDER_MINUTE', '0'))

# Business logic constants
MAX_COUPON_VALUE = 100000  # Maximum value for coupon price/value
MAX_AI_TEXT_LENGTH = 1000  # Maximum text length for AI analysis

# Log important settings (without passwords)
logger.info(f"Bot Configuration:")
logger.info(f"API_URL: {API_URL}")
logger.info(f"TELEGRAM_BOT_USERNAME: {TELEGRAM_BOT_USERNAME}")
logger.info(f"ENABLE_BOT: {ENABLE_BOT}")
logger.info(f"SESSION_TIMEOUT_MINUTES: {SESSION_TIMEOUT_MINUTES}")
logger.info(f"REMINDER_TIME: {REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d} Israel time")
logger.info(f"DATABASE_URL configured: {'Yes' if os.getenv('DATABASE_URL') else 'No'}")

# Setup headers for all requests
HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}

# Setup encryption key
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise ValueError("No ENCRYPTION_KEY set for encryption")
cipher_suite = Fernet(ENCRYPTION_KEY.encode())

def calculate_first_sunday_of_month(year=None, month=None):
    """Calculate the date of the first Sunday of a given month (or current month if not specified)"""
    from datetime import date, timedelta
    
    if year is None or month is None:
        today = date.today()
        year = today.year
        month = today.month
    
    # Get first day of the month
    first_day = date(year, month, 1)
    
    # Find first Sunday (weekday 6 = Sunday, weekday 0 = Monday)
    days_until_sunday = (6 - first_day.weekday()) % 7
    first_sunday = first_day + timedelta(days=days_until_sunday)
    
    return first_sunday.day

def calculate_first_sunday_of_next_month():
    """Calculate the first Sunday of the next month"""
    from datetime import date, timedelta
    
    today = date.today()
    
    # Move to next month
    if today.month == 12:
        next_year = today.year + 1
        next_month = 1
    else:
        next_year = today.year
        next_month = today.month + 1
    
    # Use the existing function with next month parameters
    return calculate_first_sunday_of_month(next_year, next_month)

async def update_monthly_summary_day_for_next_month():
    """Update the monthly summary day setting for next month after sending summaries"""
    try:
        from datetime import date, timedelta
        
        # Calculate next month
        today = date.today()
        if today.month == 12:
            next_month = 1
            next_year = today.year + 1
        else:
            next_month = today.month + 1
            next_year = today.year
        
        # Calculate first Sunday of next month
        next_month_first_sunday = calculate_first_sunday_of_month(next_year, next_month)
        
        # Update the setting in database
        conn = await get_async_db_connection()
        await conn.execute("""
            UPDATE bot_settings 
            SET value = $1, updated_at = CURRENT_TIMESTAMP 
            WHERE key = 'monthly_summary_day'
        """, str(next_month_first_sunday))
        await conn.close()
        
        # Update local config
        reminder_config['monthly_summary_day'] = next_month_first_sunday
        
        logger.info(f"Updated monthly_summary_day for next month ({next_month}/{next_year}) to: {next_month_first_sunday}")
        
    except Exception as e:
        logger.error(f"Could not update monthly summary day for next month: {e}")

async def save_monthly_day_config(day):
    """Save monthly summary day configuration to database"""
    try:
        conn = await get_async_db_connection()
        await conn.execute("""
            INSERT INTO bot_settings (key, value, updated_at) 
            VALUES ('monthly_summary_day', $1, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET 
                value = EXCLUDED.value, 
                updated_at = CURRENT_TIMESTAMP
        """, str(day))
        
        await conn.close()
        
        # Update local config
        reminder_config['monthly_summary_day'] = day
        
        logger.info(f"Saved monthly day config to database: {day}")
        
    except Exception as e:
        logger.error(f"Could not save monthly day config to database: {e}")

async def update_monthly_summary_day_to_20():
    """Update monthly summary day to 20"""
    try:
        conn = await get_async_db_connection()
        await conn.execute("""
            INSERT INTO bot_settings (key, value, updated_at) 
            VALUES ('monthly_summary_day', '20', CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET 
                value = EXCLUDED.value, 
                updated_at = CURRENT_TIMESTAMP
        """)
        await conn.close()
        logger.info("Updated monthly_summary_day to 20")
    except Exception as e:
        logger.error(f"Error updating monthly_summary_day: {e}")

async def save_last_monthly_summary_date(date_str):
    """Save the date when monthly summary was last sent"""
    try:
        conn = await get_async_db_connection()
        await conn.execute("""
            INSERT INTO bot_settings (key, value, updated_at) 
            VALUES ('last_monthly_summary_sent', $1, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET 
                value = EXCLUDED.value, 
                updated_at = CURRENT_TIMESTAMP
        """, date_str)
        await conn.close()
        
        # Update local config
        reminder_config['last_monthly_summary_sent'] = date_str
        
        logger.info(f"Saved last monthly summary date: {date_str}")
        
    except Exception as e:
        logger.error(f"Could not save last monthly summary date: {e}")

# Global variables
reminder_config = {
    'hour': REMINDER_HOUR,
    'minute': REMINDER_MINUTE,
    'monthly_summary_day': calculate_first_sunday_of_month(),  # Default: Calculated first Sunday date
    'last_monthly_summary_sent': None  # Track when last summary was sent
}

# Global variable to store bot context
context_app = None

# Global variable to control scheduler restart
scheduler_task = None
scheduler_stop_event = None

# Function to load reminder time from database
async def load_reminder_config():
    """Load reminder configuration from database"""
    try:
        conn = await get_async_db_connection()
        # Try to create settings table if it doesn't exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key VARCHAR(50) PRIMARY KEY,
                value VARCHAR(100) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Load reminder hour, minute, monthly summary day, and last sent date
        hour_result = await conn.fetchrow("SELECT value FROM bot_settings WHERE key = 'reminder_hour'")
        minute_result = await conn.fetchrow("SELECT value FROM bot_settings WHERE key = 'reminder_minute'")
        monthly_day_result = await conn.fetchrow("SELECT value FROM bot_settings WHERE key = 'monthly_summary_day'")
        last_sent_result = await conn.fetchrow("SELECT value FROM bot_settings WHERE key = 'last_monthly_summary_sent'")
        
        if hour_result:
            reminder_config['hour'] = int(hour_result['value'])
            logger.info(f"Loaded reminder hour: {reminder_config['hour']}")
        if minute_result:
            reminder_config['minute'] = int(minute_result['value'])
            logger.info(f"Loaded reminder minute: {reminder_config['minute']}")
        if monthly_day_result:
            reminder_config['monthly_summary_day'] = int(monthly_day_result['value'])
            logger.info(f"Loaded monthly summary day: {reminder_config['monthly_summary_day']}")
        else:
            logger.info("No monthly_summary_day found in database")
        if last_sent_result:
            reminder_config['last_monthly_summary_sent'] = last_sent_result['value']
            logger.info(f"Loaded last monthly summary sent date: {reminder_config['last_monthly_summary_sent']}")
        else:
            logger.info("No last_monthly_summary_sent found in database")
            
        await conn.close()
        logger.info(f"Final reminder config: {reminder_config}")
        
    except Exception as e:
        logger.warning(f"Could not load reminder config from database, using defaults: {e}")
        # Use default values from environment variables
        pass

# Function to save reminder time to database
async def save_reminder_config():
    """Save reminder configuration to database"""
    try:
        conn = await get_async_db_connection()
        
        # Try to create settings table if it doesn't exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key VARCHAR(50) PRIMARY KEY,
                value VARCHAR(100) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert or update reminder hour, minute and monthly summary day
        await conn.execute("""
            INSERT INTO bot_settings (key, value, updated_at) 
            VALUES ('reminder_hour', $1, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET 
                value = EXCLUDED.value, 
                updated_at = CURRENT_TIMESTAMP
        """, str(reminder_config['hour']))
        
        await conn.execute("""
            INSERT INTO bot_settings (key, value, updated_at) 
            VALUES ('reminder_minute', $1, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET 
                value = EXCLUDED.value, 
                updated_at = CURRENT_TIMESTAMP
        """, str(reminder_config['minute']))
        
        await conn.execute("""
            INSERT INTO bot_settings (key, value, updated_at) 
            VALUES ('monthly_summary_day', $1, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET 
                value = EXCLUDED.value, 
                updated_at = CURRENT_TIMESTAMP
        """, str(reminder_config['monthly_summary_day']))
        
        await conn.close()
        logger.info(f"Saved reminder config to database: {reminder_config['hour']:02d}:{reminder_config['minute']:02d}, monthly_summary_day: {reminder_config['monthly_summary_day']}")
        
    except Exception as e:
        logger.error(f"Could not save reminder config to database: {e}")

async def initialize_monthly_summary_settings():
    """Initialize monthly summary settings in database - called from wsgi.py on server startup"""
    try:
        conn = await get_async_db_connection()
        
        # Check if monthly_summary_day setting exists
        existing_setting = await conn.fetchrow("SELECT value FROM bot_settings WHERE key = 'monthly_summary_day'")
        
        if not existing_setting:
            # Calculate the actual date of first Sunday of current month
            first_sunday_date = calculate_first_sunday_of_month()
            
            # Insert the calculated date
            await conn.execute("""
                INSERT INTO bot_settings (key, value, updated_at) 
                VALUES ('monthly_summary_day', $1, CURRENT_TIMESTAMP)
            """, str(first_sunday_date))
            logger.info(f"Added monthly_summary_day setting to database with calculated first Sunday date: {first_sunday_date}")
        else:
            logger.info(f"Monthly summary day setting already exists with value: {existing_setting['value']}")
        
        await conn.close()
        
    except Exception as e:
        logger.error(f"Could not initialize monthly summary settings: {e}")

def decrypt_coupon_code(encrypted_code):
    """Decrypt encrypted coupon code"""
    try:
        if encrypted_code and encrypted_code.startswith('gAAAAA'):
            value = encrypted_code.encode()
            decrypted_value = cipher_suite.decrypt(value)
            return decrypted_value.decode()
        return encrypted_code
    except Exception as e:
        logger.error(f"Error decrypting coupon code: {e}")
        return encrypted_code

def validate_monetary_value(value_str, field_name, allow_zero=False):
    """
    Validate monetary value with business rules
    Returns (is_valid, parsed_value, error_message)
    """
    try:
        # Check if it's a valid number
        if not value_str.replace('.', '', 1).replace('-', '', 1).isdigit():
            return False, None, f"אנא הזן מספר תקין עבור {field_name}"
        
        value = float(value_str)
        
        # Check for negative values
        if value < 0:
            return False, None, f"{field_name} לא יכול להיות קטן מ-0"
        
        # Check for zero when not allowed
        if not allow_zero and value == 0:
            return False, None, f"{field_name} חייב להיות גדול מ-0"
        
        # Check for maximum value
        if value > MAX_COUPON_VALUE:
            return False, None, f"{field_name} לא יכול להיות גדול מ-{MAX_COUPON_VALUE:,} שח"
        
        return True, value, None
        
    except ValueError:
        return False, None, f"אנא הזן מספר תקין עבור {field_name}"

def validate_date_format(date_str):
    """
    Validate date format and check for logical errors
    Returns (is_valid, parsed_date, error_message)
    """
    try:
        # Check basic format
        if not re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', date_str):
            return False, None, "פורמט תאריך לא תקין. השתמש ב-DD/MM/YYYY"
        
        day, month, year = map(int, date_str.split('/'))
        
        # Check month range
        if month < 1 or month > 12:
            return False, None, "חודש לא תקין (1-12)"
        
        # Check day range
        if day < 1 or day > 31:
            return False, None, "יום לא תקין (1-31)"
        
        # Use datetime to validate the actual date
        parsed_date = datetime.strptime(date_str, "%d/%m/%Y").date()
        return True, parsed_date, None
        
    except ValueError as e:
        if "day is out of range for month" in str(e):
            return False, None, f"יום {day} לא קיים בחודש {month}"
        return False, None, "תאריך לא תקין"

def validate_ai_text_input(text):
    """
    Validate AI text input for length and content
    Returns (is_valid, error_message)
    """
    if len(text) > MAX_AI_TEXT_LENGTH:
        return False, f"הטקסט ארוך מדי. מקסימום {MAX_AI_TEXT_LENGTH} תווים"
    
    if len(text.strip()) < 10:
        return False, "הטקסט קצר מדי. אנא הוסף יותר פרטים"
    
    return True, None

# Setup database connection
def get_db_connection():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    # Remove the +psycopg2 part from the URL for direct psycopg2 connection
    if database_url.startswith('postgresql+psycopg2://'):
        database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
    return psycopg2.connect(database_url)

async def get_async_db_connection():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    # Remove the +psycopg2 part from the URL for asyncpg connection
    if database_url.startswith('postgresql+psycopg2://'):
        database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
    return await asyncpg.connect(database_url, statement_cache_size=0)

async def check_session_validity(chat_id):
    """
    Check if user session is still valid based on verification_expires_at timestamp
    Returns (is_valid, user_id, user_gender)
    """
    try:
        conn = await get_async_db_connection()
        
        # Check if user exists and session is valid
        query = """
            SELECT user_id, verification_expires_at 
            FROM telegram_users 
            WHERE telegram_chat_id = $1 
            AND is_verified = true
        """
        user = await conn.fetchrow(query, chat_id)
        
        if not user:
            await conn.close()
            return False, None, None
        
        # Check if session has expired
        current_time = datetime.now(timezone.utc)
        if user['verification_expires_at'] <= current_time:
            # Session expired - disconnect user
            await disconnect_user_session(conn, chat_id)
            await conn.close()
            return False, None, None
        
        # Session is valid - get user gender
        user_gender = await get_user_gender(user['user_id'])
        await conn.close()
        return True, user['user_id'], user_gender
        
    except Exception as e:
        logger.error(f"Error checking session validity: {e}")
        return False, None, None

async def disconnect_user_session(conn, chat_id):
    """
    Disconnect user session by updating database
    """
    try:
        update_query = """
            UPDATE telegram_users 
            SET telegram_chat_id = NULL,
                telegram_username = NULL,
                is_verified = false,
                last_interaction = NOW(),
                disconnected_at = NOW(),
                is_disconnected = true
            WHERE telegram_chat_id = $1
        """
        await conn.execute(update_query, chat_id)
        logger.info(f"User session disconnected due to timeout: chat_id={chat_id}")
    except Exception as e:
        logger.error(f"Error disconnecting user session: {e}")

async def update_session_expiry(chat_id):
    """
    Update session expiry time for active user
    """
    try:
        conn = await get_async_db_connection()
        
        # Update expiry time to current time + SESSION_TIMEOUT_MINUTES
        new_expiry = datetime.now(timezone.utc) + timedelta(minutes=SESSION_TIMEOUT_MINUTES)
        
        update_query = """
            UPDATE telegram_users 
            SET verification_expires_at = $1,
                last_interaction = NOW()
            WHERE telegram_chat_id = $2
            AND is_verified = true
        """
        await conn.execute(update_query, new_expiry, chat_id)
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error updating session expiry: {e}")

# Check if user is admin
async def is_user_admin(user_id):
    """Check if user has admin privileges"""
    try:
        conn = await get_async_db_connection()
        query = "SELECT is_admin FROM users WHERE id = $1"
        result = await conn.fetchrow(query, user_id)
        await conn.close()
        return result['is_admin'] if result else False
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

# Global variable to store first message
first_message = None
user_states = {}

def get_main_menu_text(user_gender, slots=0):
    """Return main menu text with updated options"""
    return get_gender_specific_text(
        user_gender,
        "🏠 מה תרצה לעשות?\n\n"
        "1️⃣ הקופונים שלי\n"
        "2️⃣ חיפוש לפי חברה\n"
        "3️⃣ הוספת קופון חדש\n"
        "4️⃣ עדכון שימוש בקופון\n"
        "5️⃣ למחוק קופון\n"
        "6️⃣ להתנתק\n"
        "-------------------\n"
        "🤖 אפשרויות עם AI\n"
        f"(נותרו לך עוד {slots} סלוטים לשימוש ביכולות AI)\n"
        "7️⃣ הוספת קופון חדש מטקסט חופשי\n\n"
        "שלח לי מספר מ-1 עד 7",
        "🏠 מה תרצי לעשות?\n\n"
        "1️⃣ הקופונים שלי\n"
        "2️⃣ חיפוש לפי חברה\n"
        "3️⃣ הוספת קופון חדש\n"
        "4️⃣ עדכון שימוש בקופון\n"
        "5️⃣ למחוק קופון\n"
        "6️⃣ להתנתק\n"
        "-------------------\n"
        "🤖 אפשרויות עם AI\n"
        f"(נותרו לך עוד {slots} סלוטים לשימוש ביכולות AI)\n"
        "7️⃣ הוספת קופון חדש מטקסט חופשי\n\n"
        "שלחי לי מספר מ-1 עד 7"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat_id = update.message.chat_id
    
    # Clear any existing session data
    user_coupon_states.pop(chat_id, None)
    user_states.pop(chat_id, None)
    
    try:
        conn = await get_async_db_connection()
        
        # Check if user is already authenticated and session is valid
        query = """
            SELECT user_id, verification_expires_at 
            FROM telegram_users 
            WHERE telegram_chat_id = $1 
            AND is_verified = true
        """
        user = await conn.fetchrow(query, chat_id)
        
        if user:
            # Check if session is still valid
            current_time = datetime.now(timezone.utc)
            if user['verification_expires_at'] > current_time:
                # Session is valid - update expiry and continue
                await update_session_expiry(chat_id)
                
                # Get user gender
                user_gender = await get_user_gender(user['user_id'])
                # Get slots_automatic_coupons
                slots = 0
                try:
                    slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user['user_id'])
                    if slots_row:
                        slots = slots_row['slots_automatic_coupons']
                except Exception as e:
                    logger.error(f"Error fetching slots_automatic_coupons: {e}")
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "יאללה! הצלחנו 🎉\n\n"
                        "עכשיו אתה מחובר לבוט הקופונים\n"
                        "יכול לקבל עדכונים ולנהל את הקופונים שלך\n\n"
                        "בואו נתחיל?",
                        "יאללה! הצלחנו 🎉\n\n"
                        "עכשיו את מחוברת לבוט הקופונים\n"
                        "יכולה לקבל עדכונים ולנהל את הקופונים שלך\n\n"
                        "בואי נתחיל?"
                    )
                )
                # Send menu
                await update.message.reply_text(get_main_menu_text(user_gender, slots))
            else:
                # Session expired - disconnect user
                await disconnect_user_session(conn, chat_id)
                await update.message.reply_text(
                    "⏰ הפעלה שלך פגה תוקף\n"
                    "אנא התחבר שוב עם קוד אימות חדש מהאתר"
                )
        else:
            # For new users, we'll use a default male text since we don't know their gender yet
            await update.message.reply_text(
                "היי! 👋\n"
                "ברוך הבא לבוט הקופונים\n\n"
                "כדי להתחיל, שלח לי את קוד האימות מהאתר\n"
                "פשוט העתק והדבק כאן"
            )
        
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text(
            "אופס! 😅\n"
            "משהו השתבש מהצד שלנו\n\n"
            "תנסה שוב בעוד רגע?\n"
            "או כתוב /start להתחיל מחדש"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display available commands list (admin only)"""
    chat_id = update.message.chat_id
    
    # Check if user is connected and get user_id
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    
    # Check if user is admin - if not, show main menu instead
    if not is_valid or not user_id or not await is_user_admin(user_id):
        # If user is connected but not admin, show main menu
        if is_valid and user_id:
            conn = await get_async_db_connection()
            slots = 0
            try:
                slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user_id)
                if slots_row:
                    slots = slots_row['slots_automatic_coupons']
            except Exception as e:
                logger.error(f"Error fetching slots_automatic_coupons: {e}")
            await conn.close()
            
            await update.message.reply_text(get_main_menu_text(user_gender, slots))
        return
    
    help_text = (
        "📋 רשימת הפקודות זמינות למנהלים:\n\n"
        "/start - התחלת שיחה עם הבוט\n"
        "/help - הצגת רשימת הפקודות\n"
        "/test_reminders - בדיקת תזכורות קופונים\n"
        "/test_monthly - בדיקת סיכום חודשי\n"
        "/change_reminder_time - שינוי זמן התזכורת יומית\n"
        "/change_monthly_day - שינוי יום הסיכום החודשי\n"
    )
    
    await update.message.reply_text(help_text)

async def test_monthly_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test monthly summary for admin"""
    chat_id = update.message.chat_id
    
    # Check if user is connected and is admin
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    if not await is_user_admin(user_id):
        await update.message.reply_text("❌ פקודה זו זמינה למנהלים בלבד")
        return

    await update.message.reply_text("🧪 בודק הודעה חודשית...")
    
    try:
        # Send monthly summary to admin
        await send_monthly_summary(chat_id, user_id, user_gender)
        
        await update.message.reply_text("✅ הודעה חודשית נשלחה לבדיקה")
        
    except Exception as e:
        logger.error(f"Error in test_monthly_summary_command: {e}")
        await update.message.reply_text(f"❌ שגיאה בבדיקת הודעה חודשית: {str(e)}")

async def test_reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test reminder functionality (admin only) - shows what would be sent without sending"""
    chat_id = update.message.chat_id
    
    # Add debug logging
    logger.info(f"test_reminders_command called by chat_id {chat_id}")
    
    # Check if user is connected and is admin
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    if not await is_user_admin(user_id):
        await update.message.reply_text("❌ פקודה זו זמינה למנהלים בלבד")
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    await update.message.reply_text(
        f"🔔 מריץ בדיקת תזכורות...\n"
        f"שעת תזכורת נוכחית: {reminder_config['hour']:02d}:{reminder_config['minute']:02d} (שעון ישראל)"
    )
    
    # Test reminder check - DRY RUN (doesn't send actual messages)
    logger.info(f"Running test check for expiring coupons from test_reminders_command")
    await test_check_expiring_coupons(chat_id)
    
    await update.message.reply_text("✅ בדיקת תזכורות הושלמה")

async def test_monthly_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test monthly summary functionality (admin only)"""
    chat_id = update.message.chat_id
    
    # Add debug logging
    logger.info(f"test_monthly_summary_command called by chat_id {chat_id}")
    
    # Check if user is connected and is admin
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    if not await is_user_admin(user_id):
        await update.message.reply_text("❌ פקודה זו זמינה למנהלים בלבד")
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    await update.message.reply_text("📊 שולח סיכום חודשי לבדיקה...")
    
    try:
        # Send monthly summary to the admin
        await send_monthly_summary(chat_id, user_id, user_gender)
        await update.message.reply_text("✅ הסיכום החודשי נשלח בהצלחה!")
        
    except Exception as e:
        logger.error(f"Error in test_monthly_summary_command: {e}")
        await update.message.reply_text(f"❌ שגיאה בשליחת הסיכום החודשי: {str(e)}")

# Add this to user_states tracking at the top of the file
# user_states = {}  # This already exists, just showing where it is

async def change_monthly_day_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change monthly summary day (admin only)"""
    chat_id = update.message.chat_id
    
    # Add debug logging
    logger.info(f"change_monthly_day_command called by chat_id {chat_id}")
    
    # Check if user is connected and is admin
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    if not await is_user_admin(user_id):
        await update.message.reply_text("❌ פקודה זו זמינה למנהלים בלבד")
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    # Parse arguments
    args = context.args
    if len(args) == 0:
        # No arguments provided - set state and wait for input
        user_states[chat_id] = "waiting_for_monthly_day"
        next_sunday = calculate_first_sunday_of_next_month()
        await update.message.reply_text(
            "📅 הזן את היום בחודש לשליחת הסיכום החודשי\n"
            "לדוגמה: 1 (לראשון בחודש)\n"
            "או: 15 (ל-15 בחודש)\n"
            "או: 20 (ל-20 בחודש)\n"
            f"או: ראשון (ליום ראשון הראשון - יהיה ב-{next_sunday} בחודש הבא)"
        )
        return
    elif len(args) != 1:
        await update.message.reply_text(
            "❌ פורמט שגוי. השתמש ב:\n"
            "/change_monthly_day <יום>\n"
            "לדוגמה: /change_monthly_day 20\n"
            "או: /change_monthly_day ראשון"
        )
        return
    
    try:
        arg = args[0].strip()
        
        if arg.lower() in ['ראשון', 'יום ראשון', 'יום ראשון הראשון', 'sunday', 'first sunday']:
            # Calculate first Sunday of next month
            day = calculate_first_sunday_of_next_month()
            special_mode = True
        else:
            day = int(arg)
            special_mode = False
            
            if not (1 <= day <= 31):
                raise ValueError("יום חייב להיות בין 1 ל-31")
        
        # Save to database
        await save_monthly_day_config(day)
        
        if special_mode:
            await update.message.reply_text(
                f"✅ יום הסיכום החודשי עודכן ליום ראשון הראשון בחודש\n"
                f"החודש הבא זה יהיה ב-{day} בחודש"
            )
        else:
            await update.message.reply_text(
                f"✅ יום הסיכום החודשי עודכן ל-{day} בחודש"
            )
        
        logger.info(f"Monthly day updated to {day} by user {user_id} (special mode: {special_mode})")
        
    except ValueError as e:
        await update.message.reply_text(f"❌ שגיאה: {str(e)}")
    except Exception as e:
        logger.error(f"Error updating monthly day: {e}")
        await update.message.reply_text("❌ אירעה שגיאה בעדכון יום הסיכום החודשי")

async def change_reminder_time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change reminder time (admin only)"""
    chat_id = update.message.chat_id
    
    # Add debug logging
    logger.info(f"change_reminder_time_command called by chat_id {chat_id}")
    
    # Check if user is connected and is admin
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    if not await is_user_admin(user_id):
        await update.message.reply_text("❌ פקודה זו זמינה למנהלים בלבד")
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    # Parse arguments
    args = context.args
    if len(args) == 0:
        # No arguments provided - set state and wait for input
        user_states[chat_id] = "waiting_for_reminder_time"
        await update.message.reply_text(
            "⏰ הזן את השעה והדקה לתזכורת\n"
            "לדוגמה: 21:20 או 21 20\n"
            "או: 9:30 או 9 30"
        )
        return
    elif len(args) != 2:
        await update.message.reply_text(
            "❌ פורמט שגוי. השתמש ב:\n"
            "/change_reminder_time <שעה> <דקה>\n"
            "לדוגמה: /change_reminder_time 18 30"
        )
        return
    
    try:
        hour = int(args[0])
        minute = int(args[1])
        
        if not (0 <= hour <= 23):
            raise ValueError("שעה חייבת להיות בין 0 ל-23")
        if not (0 <= minute <= 59):
            raise ValueError("דקה חייבת להיות בין 0 ל-59")
        
        # Update reminder config
        reminder_config['hour'] = hour
        reminder_config['minute'] = minute
        
        # Save to database
        await save_reminder_config()
        
        await update.message.reply_text(
            f"✅ שעת התזכורת עודכנה ל-{hour:02d}:{minute:02d} (שעון ישראל)\n"
            f"התזכורת הבאה תישלח בשעה זו"
        )
        
        logger.info(f"Reminder time updated to {hour:02d}:{minute:02d} Israel time by user {user_id}")
        
    except ValueError as e:
        await update.message.reply_text(f"❌ שגיאה: {str(e)}")


# Add this new function to handle reminder time input
async def handle_reminder_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reminder time input when in waiting state"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    # Check if user is admin (redundant check for safety)
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid or not await is_user_admin(user_id):
        user_states.pop(chat_id, None)
        return
    
    try:
        # Support both "21 20" and "21:20" formats
        if ':' in user_message:
            parts = user_message.split(':')
        else:
            parts = user_message.split()
            
        if len(parts) != 2:
            await update.message.reply_text(
                "❌ פורמט שגוי. הזן שעה ודקה\n"
                "לדוגמה: 21:20 או 21 20"
            )
            return
        
        hour = int(parts[0])
        minute = int(parts[1])
        
        if not (0 <= hour <= 23):
            raise ValueError("שעה חייבת להיות בין 0 ל-23")
        if not (0 <= minute <= 59):
            raise ValueError("דקה חייבת להיות בין 0 ל-59")
        
        # Update reminder config
        reminder_config['hour'] = hour
        reminder_config['minute'] = minute
        
        # Save to database
        await save_reminder_config()
        
        # Restart scheduler with new configuration
        await restart_scheduler()
        
        # Clear state
        user_states.pop(chat_id, None)
        
        await update.message.reply_text(
            f"✅ שעת התזכורת עודכנה ל-{hour:02d}:{minute:02d} (שעון ישראל)\n"
            f"התזכורת הבאה תישלח בשעה זו"
        )
        
        logger.info(f"Reminder time updated to {hour:02d}:{minute:02d} Israel time by user {user_id}")
        
        # Send menu again
        conn = await get_async_db_connection()
        slots = 0
        try:
            slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user_id)
            if slots_row:
                slots = slots_row['slots_automatic_coupons']
        except Exception as e:
            logger.error(f"Error fetching slots_automatic_coupons: {e}")
        await conn.close()
        
        await update.message.reply_text(get_main_menu_text(user_gender, slots))
        
    except ValueError as e:
        await update.message.reply_text(f"❌ שגיאה: {str(e)}")

async def handle_monthly_day_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle monthly day input when in waiting state"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    # Check if user is admin (redundant check for safety)
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid or not await is_user_admin(user_id):
        user_states.pop(chat_id, None)
        return
    
    try:
        user_input = user_message.strip()
        
        if user_input.lower() in ['ראשון', 'יום ראשון', 'יום ראשון הראשון', 'sunday', 'first sunday']:
            # Calculate first Sunday of next month
            day = calculate_first_sunday_of_next_month()
            special_mode = True
        else:
            day = int(user_input)
            special_mode = False
            
            if not (1 <= day <= 31):
                raise ValueError("יום חייב להיות בין 1 ל-31")
        
        # Save to database
        await save_monthly_day_config(day)
        
        # Clear state
        user_states.pop(chat_id, None)
        
        if special_mode:
            await update.message.reply_text(
                f"✅ יום הסיכום החודשי עודכן ליום ראשון הראשון בחודש\n"
                f"החודש הבא זה יהיה ב-{day} בחודש"
            )
        else:
            await update.message.reply_text(
                f"✅ יום הסיכום החודשי עודכן ל-{day} בחודש"
            )
        
        logger.info(f"Monthly day updated to {day} by user {user_id} (special mode: {special_mode})")
        
        # Send menu again
        conn = await get_async_db_connection()
        slots = 0
        try:
            slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user_id)
            if slots_row:
                slots = slots_row['slots_automatic_coupons']
        except Exception as e:
            logger.error(f"Error fetching slots_automatic_coupons: {e}")
        await conn.close()
        
        await update.message.reply_text(get_main_menu_text(user_gender, slots))
        
    except ValueError as e:
        await update.message.reply_text(f"❌ שגיאה: {str(e)}")

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (verification code) and authenticate user"""
    user_message = update.message.text.strip()
    chat_id = update.message.chat_id

    # Print received code to console
    logger.info(f"[CONSOLE] User entered code: {user_message}")

    # Check if user is waiting for reminder time input
    if user_states.get(chat_id) == "waiting_for_reminder_time":
        await handle_reminder_time_input(update, context)
        return
    
    # Check if user is waiting for monthly day input
    if user_states.get(chat_id) == "waiting_for_monthly_day":
        await handle_monthly_day_input(update, context)
        return

    # Check if user is in company selection mode for coupon usage update
    if user_states.get(chat_id) == "choose_company_for_usage":
        await handle_company_choice_for_usage(update, context)
        return

    # Check if user is in company selection mode for coupon deletion
    if user_states.get(chat_id) == "choose_company_for_delete":
        await handle_company_choice_for_delete(update, context)
        return

    # Check if user is in company selection mode
    if user_states.get(chat_id) == "choose_company":
        await handle_company_choice(update, context)
        return

    try:
        conn = await get_async_db_connection()

        # Check if user is already connected with valid session
        existing_user_query = """
            SELECT user_id, is_verified, verification_expires_at 
            FROM telegram_users 
            WHERE telegram_chat_id = $1 
            AND is_verified = true
        """
        existing_user = await conn.fetchrow(existing_user_query, chat_id)
        
        if existing_user:
            # Check if session is still valid
            current_time = datetime.now(timezone.utc)
            if existing_user['verification_expires_at'] > current_time:
                # Session is valid - check if this is a menu selection
                if user_message in ['1', '2', '3', '4', '5', '6', '7']:
                    await handle_menu_option(update, context)
                    await conn.close()
                    return
                else:
                    logger.warning(f"[DEBUG] handle_code: User already connected chat_id={chat_id}")
                    user_gender = await get_user_gender(existing_user['user_id'])
                    await update.message.reply_text(
                        get_gender_specific_text(
                            user_gender,
                            "👍 אתה כבר מחובר! השתמש בתפריט למטה",
                            "👍 את כבר מחוברת! השתמשי בתפריט למטה"
                        )
                    )
                    # Send menu and update session expiry
                    await update_session_expiry(chat_id)
                    slots = 0
                    try:
                        slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", existing_user['user_id'])
                        if slots_row:
                            slots = slots_row['slots_automatic_coupons']
                    except Exception as e:
                        logger.error(f"Error fetching slots_automatic_coupons: {e}")
                    await update.message.reply_text(get_main_menu_text(user_gender, slots))
                    await conn.close()
                    return
            else:
                # Session expired - disconnect user
                await disconnect_user_session(conn, chat_id)

        # Fetch all records with this code for debugging
        all_rows = await conn.fetch("SELECT * FROM telegram_users WHERE verification_token = $1", user_message)
        logger.warning(f"[DEBUG] handle_code: All records with this code: {all_rows}")

        # Check code against table - search for unverified record
        query = """
            SELECT * FROM telegram_users 
            WHERE verification_token = $1 
            AND verification_expires_at > NOW()
            AND is_verified = false
            AND (blocked_until IS NULL OR blocked_until < NOW())
            LIMIT 1
        """
        user = await conn.fetchrow(query, user_message)
        logger.warning(f"[DEBUG] handle_code: SELECT result for verification: {user}")

        if user:
            logger.warning(f"[DEBUG] handle_code: Found valid user user_id={user['user_id']}")
            
            # Get user gender
            user_gender = await get_user_gender(user['user_id'])
            
            # Calculate session expiry time
            session_expiry = datetime.now(timezone.utc) + timedelta(minutes=SESSION_TIMEOUT_MINUTES)
            
            # Update existing record instead of deleting and creating new
            update_query = """
                UPDATE telegram_users 
                SET telegram_chat_id = $1,
                    telegram_username = $2,
                    is_verified = true,
                    last_interaction = NOW(),
                    verification_attempts = 0,
                    last_verification_attempt = NULL,
                    verification_expires_at = $3
                WHERE user_id = $4
                AND verification_token = $5
                RETURNING user_id
            """
            
            logger.warning(f"[DEBUG] handle_code: Updating user user_id={user['user_id']} chat_id={chat_id}")
            updated_user = await conn.fetchrow(
                update_query, 
                chat_id,
                update.message.from_user.username,
                session_expiry,
                user['user_id'],
                user_message
            )
            logger.warning(f"[DEBUG] handle_code: User update result: {updated_user}")

            if updated_user:
                logger.warning(f"[DEBUG] handle_code: Verification successful! Sending menu.")
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "🎉 **יאללה! הצלחנו!**\n\n"
                        "עכשיו אתה מחובר ותוכל לקבל עדכונים על הקופונים שלך\n"
                        "💡 רוצה להתנתק? פשוט כתוב /disconnect",
                        "🎉 **יאללה! הצלחנו!**\n\n"
                        "עכשיו את מחוברת ותוכלי לקבל עדכונים על הקופונים שלך\n"
                        "💡 רוצה להתנתק? פשוט כתובי /disconnect"
                    )
                )
                # Get slots_automatic_coupons
                slots = 0
                try:
                    slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user['user_id'])
                    if slots_row:
                        slots = slots_row['slots_automatic_coupons']
                except Exception as e:
                    logger.error(f"Error fetching slots_automatic_coupons: {e}")
                await update.message.reply_text(get_main_menu_text(user_gender, slots))
            else:
                logger.error(f"[DEBUG] handle_code: User update failed!")
                await update.message.reply_text(
                    "😅 אופס! משהו השתבש בתהליך. תנסה שוב בעוד רגע?"
                )
        else:
            logger.warning(f"[DEBUG] handle_code: No suitable user found for verification. Checking blocking...")
            
            # Check if user is blocked
            blocked_query = """
                SELECT blocked_until 
                FROM telegram_users 
                WHERE verification_token = $1 
                AND blocked_until > NOW()
            """
            blocked_user = await conn.fetchrow(blocked_query, user_message)
            logger.warning(f"[DEBUG] handle_code: Blocking result: {blocked_user}")
            
            if blocked_user:
                await update.message.reply_text(
                    f"⛔ חשבונך חסום עד {blocked_user['blocked_until']}.\n"
                    "תנסה שוב אחר כך, אוקיי?"
                )
            else:
                # Show debug info and update attempt count
                debug_query = """
                    SELECT verification_token, is_verified, verification_expires_at, is_disconnected, blocked_until
                    FROM telegram_users 
                    WHERE verification_token = $1
                """
                debug_info = await conn.fetchrow(debug_query, user_message)
                logger.warning(f"[DEBUG] handle_code: debug_info: {debug_info}")
                
                # Update attempt count for records with this code
                await conn.execute("""
                    UPDATE telegram_users 
                    SET verification_attempts = verification_attempts + 1,
                        last_verification_attempt = NOW()
                    WHERE verification_token = $1
                """, user_message)
                
                # More detailed error message
                if debug_info:
                    if debug_info['is_verified']:
                        await update.message.reply_text(
                            "🤔 הקוד הזה כבר שומש. תצטרך לקבל קוד חדש מהאתר"
                        )
                    elif debug_info['verification_expires_at'] <= datetime.now(timezone.utc):
                        await update.message.reply_text(
                            "הקוד פג תוקף ⏰\n"
                            "קח קוד חדש מהאתר ובוא נתחיל"
                        )
                    else:
                        await update.message.reply_text(
                            "🙄 הקוד לא נכון. תבדוק שוב ותנסה?"
                        )
                else:
                    await update.message.reply_text(
                        "🔍 הקוד לא קיים במערכת. תבדוק שהעתקת נכון?"
                    )
        
        await conn.close()
        
    except Exception as e:
        logger.error(f"[DEBUG] handle_code: Exception: {e}")
        await update.message.reply_text(
            "😅 משהו השתבש. תנסה שוב בעוד רגע?"
        )

async def disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /disconnect command"""
    chat_id = update.message.chat_id
    
    try:
        conn = await get_async_db_connection()
        
        # Check if user is connected
        check_query = """
            SELECT user_id, is_verified, verification_token
            FROM telegram_users 
            WHERE telegram_chat_id = $1
        """
        user = await conn.fetchrow(check_query, chat_id)
        
        if not user or not user['is_verified']:
            await update.message.reply_text(
                "❌ לא נמצא משתמש מחובר."
            )
            await conn.close()
            return
            
        # Get user gender
        user_gender = await get_user_gender(user['user_id'])
        
        # Update user status and save disconnection time
        update_query = """
            UPDATE telegram_users 
            SET telegram_chat_id = NULL,
                telegram_username = NULL,
                is_verified = false,
                last_interaction = NOW(),
                disconnected_at = NOW(),
                verification_expires_at = NOW(),
                is_disconnected = true
            WHERE telegram_chat_id = $1
            AND is_verified = true
            RETURNING user_id
        """
        result = await conn.execute(update_query, chat_id)
        
        if result == "UPDATE 1":
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "התנתקת בהצלחה ✅\n\n"
                    "כדי להתחבר מחדש:\n"
                    "קח קוד חדש מהאתר ושלח לי אותו",
                    "התנתקת בהצלחה ✅\n\n"
                    "כדי להתחבר מחדש:\n"
                    "קחי קוד חדש מהאתר ושלחי לי אותו"
                )
            )
        else:
            await update.message.reply_text(
                "❌ לא נמצא משתמש מחובר."
            )
        
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error in disconnect command: {e}")
        await update.message.reply_text(
            "❌ אירעה שגיאה בתהליך ההתנתקות. אנא נסה שוב מאוחר יותר."
        )

async def handle_company_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle company selection from list"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    # Check session validity first
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    try:
        # Check if user is connected
        conn = await get_async_db_connection()
            
        # Fetch user companies
        companies_query = """
            SELECT DISTINCT company 
            FROM coupon 
            WHERE user_id = $1 
            AND status = 'פעיל' 
            ORDER BY company ASC
        """
        companies = await conn.fetch(companies_query, user_id)
        
        if not companies:
            await update.message.reply_text('לא נמצאו חברות פעילות')
            await conn.close()
            return
            
        # Check if choice is valid
        try:
            choice = int(user_message)
            if choice < 1 or choice > len(companies):
                raise ValueError("Invalid choice")
        except ValueError:
            # If choice is invalid, show list again
            message = "🏢 **בחר חברה מהרשימה:**\n\n"
            for i, company in enumerate(companies, 1):
                message += f"{i}. {company['company']}\n"
            message += get_gender_specific_text(
                user_gender,
                "\nלא רואה את החברה? בחר \"אחר\"",
                "\nלא רואה את החברה? בחרי \"אחר\""
            )
            await update.message.reply_text(message)
            await conn.close()
            return
            
        # Fetch coupons for selected company
        selected_company = companies[choice - 1]['company']
        coupons_query = """
            SELECT c.*, 
                   CASE 
                       WHEN c.expiration IS NULL OR c.expiration::timestamp > NOW() THEN true 
                       ELSE false 
                   END as is_available
            FROM coupon c
            WHERE c.user_id = $1
            AND c.status = 'פעיל'
            AND c.company = $2
            ORDER BY c.date_added DESC
        """
        coupons = await conn.fetch(coupons_query, user_id, selected_company)
        
        if coupons:
            # Separate coupons into two types
            regular_coupons = [c for c in coupons if not c['is_one_time']]
            one_time_coupons = [c for c in coupons if c['is_one_time']]
            
            # Display regular coupons
            if regular_coupons:
                message = f"🔄 קופונים רגילים של {selected_company}:\n\n"
                for coupon in regular_coupons:
                    remaining_value = coupon['value'] - coupon['used_value']
                    decrypted_code = decrypt_coupon_code(coupon['code'])
                    message += (
                        f"🏷️ קוד: {decrypted_code}\n"
                        f"💰 ערך: {coupon['value']}₪\n"
                        f"💵 נותר לשימוש: {remaining_value}₪\n"
                        f"📅 תפוגה: {coupon['expiration'] or 'ללא'}\n\n"
                    )
                await update.message.reply_text(message)
            
            # Display one-time coupons
            if one_time_coupons:
                message = f"🎫 קופונים חד פעמיים של {selected_company}:\n\n"
                for coupon in one_time_coupons:
                    remaining_value = coupon['value'] - coupon['used_value']
                    decrypted_code = decrypt_coupon_code(coupon['code'])
                    message += (
                        f"🏷️ קוד: {decrypted_code}\n"
                        f"💰 ערך: {coupon['value']}₪\n"
                        f"💵 נותר לשימוש: {remaining_value}₪\n"
                        f"🎯 מטרה: {coupon['purpose']}\n"
                        f"📅 תפוגה: {coupon['expiration'] or 'ללא'}\n\n"
                    )
                await update.message.reply_text(message)
        else:
            await update.message.reply_text(f'לא נמצאו קופונים פעילים עבור {selected_company}')
            
        # Send menu again
        slots = 0
        try:
            slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user_id)
            if slots_row:
                slots = slots_row['slots_automatic_coupons']
        except Exception as e:
            logger.error(f"Error fetching slots_automatic_coupons: {e}")
        await update.message.reply_text(get_main_menu_text(user_gender, slots))
        user_states.pop(chat_id, None)
        await conn.close()
        return
    except Exception as e:
        logger.error(f"Error in handle_company_choice: {e}")
        await update.message.reply_text(
            "❌ אירעה שגיאה בטיפול בבקשה. אנא נסה שוב מאוחר יותר."
        )

async def handle_company_choice_for_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle company selection for coupon usage update"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    # Check session validity first
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    try:
        conn = await get_async_db_connection()
            
        # Fetch user companies with active coupons
        companies_query = """
            SELECT DISTINCT company 
            FROM coupon 
            WHERE user_id = $1 
            AND status = 'פעיל' 
            ORDER BY company ASC
        """
        companies = await conn.fetch(companies_query, user_id)
        
        if not companies:
            await update.message.reply_text('לא נמצאו חברות פעילות')
            await conn.close()
            return
            
        # Check if choice is valid
        try:
            choice = int(user_message)
            if choice < 1 or choice > len(companies):
                raise ValueError("Invalid choice")
        except ValueError:
            # If choice is invalid, show list again
            message = "🏢 **בחר חברה מהרשימה:**\n\n"
            for i, company in enumerate(companies, 1):
                message += f"{i}. {company['company']}\n"
            await update.message.reply_text(message)
            await conn.close()
            return
            
        # Fetch coupons for selected company
        selected_company = companies[choice - 1]['company']
        coupons_query = """
            SELECT id, code, value, used_value, company, expiration, is_one_time, purpose
            FROM coupon
            WHERE user_id = $1
            AND status = 'פעיל'
            AND company = $2
            ORDER BY date_added DESC
        """
        coupons = await conn.fetch(coupons_query, user_id, selected_company)
        
        if coupons:
            # Display coupons with selection numbers
            message = f"🎯 **בחר קופון מ{selected_company} לעדכון שימוש:**\n\n"
            for i, coupon in enumerate(coupons, 1):
                remaining_value = coupon['value'] - coupon['used_value']
                decrypted_code = decrypt_coupon_code(coupon['code'])
                coupon_type = "🎫 חד פעמי" if coupon['is_one_time'] else "🔄 רגיל"
                
                message += (
                    f"{i}. {coupon_type}\n"
                    f"   🏷️ קוד: {decrypted_code}\n"
                    f"   💰 ערך כולל: {coupon['value']}₪\n"
                    f"   💵 נותר לשימוש: {remaining_value}₪\n"
                )
                if coupon['is_one_time'] and coupon['purpose']:
                    message += f"   🎯 מטרה: {coupon['purpose']}\n"
                message += "\n"
            
            message += get_gender_specific_text(
                user_gender,
                "כתוב את מספר הקופון (מתוך הרשימה) שברצונך לעדכן:",
                "כתבי את מספר הקופון (מתוך הרשימה) שברצונך לעדכן:"
            )
            
            # Store coupons data for next step
            user_coupon_states[chat_id] = {
                'state': CouponCreationState.CHOOSE_COUPON_FOR_USAGE,
                'data': {},
                'coupons': coupons,
                'user_id': user_id
            }
            
            await update.message.reply_text(message)
        else:
            await update.message.reply_text(f'לא נמצאו קופונים פעילים עבור {selected_company}')
            # Return to main menu
            await return_to_main_menu(update, context, chat_id)
            
        await conn.close()
        user_states.pop(chat_id, None)  # Clear company selection state
        
    except Exception as e:
        logger.error(f"Error in handle_company_choice_for_usage: {e}")
        await update.message.reply_text(
            "❌ אירעה שגיאה בטיפול בבקשה. אנא נסה שוב מאוחר יותר."
        )

async def handle_company_choice_for_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle company selection for coupon deletion"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    # Check session validity first
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    try:
        conn = await get_async_db_connection()
            
        # Fetch user companies with active coupons
        companies_query = """
            SELECT DISTINCT company 
            FROM coupon 
            WHERE user_id = $1 
            AND status = 'פעיל' 
            ORDER BY company ASC
        """
        companies = await conn.fetch(companies_query, user_id)
        
        if not companies:
            await update.message.reply_text('לא נמצאו חברות פעילות')
            await conn.close()
            return
            
        # Check if choice is valid
        try:
            choice = int(user_message)
            if choice < 1 or choice > len(companies):
                raise ValueError("Invalid choice")
        except ValueError:
            # If choice is invalid, show list again
            message = "🏢 **בחר חברה מהרשימה:**\n\n"
            for i, company in enumerate(companies, 1):
                message += f"{i}. {company['company']}\n"
            await update.message.reply_text(message)
            await conn.close()
            return
            
        # Fetch coupons for selected company
        selected_company = companies[choice - 1]['company']
        coupons_query = """
            SELECT id, code, value, used_value, company, expiration, is_one_time, purpose
            FROM coupon
            WHERE user_id = $1
            AND status = 'פעיל'
            AND company = $2
            ORDER BY date_added DESC
        """
        coupons = await conn.fetch(coupons_query, user_id, selected_company)
        
        if coupons:
            # Display coupons with selection numbers
            message = f"🗑️ **בחר קופון מ{selected_company} למחיקה:**\n\n"
            for i, coupon in enumerate(coupons, 1):
                remaining_value = coupon['value'] - coupon['used_value']
                decrypted_code = decrypt_coupon_code(coupon['code'])
                coupon_type = "🎫 חד פעמי" if coupon['is_one_time'] else "🔄 רגיל"
                
                message += (
                    f"{i}. {coupon_type}\n"
                    f"   🏷️ קוד: {decrypted_code}\n"
                    f"   💰 ערך כולל: {coupon['value']}₪\n"
                    f"   💵 נותר לשימוש: {remaining_value}₪\n"
                )
                if coupon['is_one_time'] and coupon['purpose']:
                    message += f"   🎯 מטרה: {coupon['purpose']}\n"
                message += "\n"
            
            message += get_gender_specific_text(
                user_gender,
                "כתוב את מספר הקופון(מתוך הרשימה) שברצונך למחוק:",
                "כתבי את מספר הקופון(מתוך הרשימה) שברצונך למחוק:"
            )
            
            # Store coupons data for next step
            user_coupon_states[chat_id] = {
                'state': CouponCreationState.CHOOSE_COUPON_FOR_DELETE,
                'data': {},
                'coupons': coupons,
                'user_id': user_id
            }
            
            await update.message.reply_text(message)
        else:
            await update.message.reply_text(f'לא נמצאו קופונים פעילים עבור {selected_company}')
            # Return to main menu
            await return_to_main_menu(update, context, chat_id)
            
        await conn.close()
        user_states.pop(chat_id, None)  # Clear company selection state
        
    except Exception as e:
        logger.error(f"Error in handle_company_choice_for_delete: {e}")
        await update.message.reply_text(
            "❌ אירעה שגיאה בטיפול בבקשה. אנא נסה שוב מאוחר יותר."
        )

async def handle_menu_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu option selection"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    # Check session validity first
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    try:
        # Check if user is connected
        conn = await get_async_db_connection()
        
        # Handle menu options
        if user_message == "1":
            # Fetch user's active coupons
            coupons_query = """
                SELECT c.*, 
                       CASE 
                           WHEN c.expiration IS NULL OR c.expiration::timestamp > NOW() THEN true 
                           ELSE false 
                       END as is_available
                FROM coupon c
                WHERE c.user_id = $1
                AND c.status = 'פעיל'
                ORDER BY c.company ASC, c.date_added DESC
            """
            coupons = await conn.fetch(coupons_query, user_id)
            
            if coupons:
                # Separate coupons into two types
                regular_coupons = [c for c in coupons if not c['is_one_time']]
                one_time_coupons = [c for c in coupons if c['is_one_time']]
                
                # Display regular coupons
                if regular_coupons:
                    message = get_gender_specific_text(
                        user_gender,
                        "🔄 **הקופונים הרגילים שלך:**\n\n",
                        "🔄 **הקופונים הרגילים שלך:**\n\n"
                    )
                    for coupon in regular_coupons:
                        remaining_value = coupon['value'] - coupon['used_value']
                        decrypted_code = decrypt_coupon_code(coupon['code'])
                        message += (
                            f"🏢 **{coupon['company']}**\n"
                            f"🏷️ קוד: {decrypted_code}\n"
                            f"💰 ערך: {coupon['value']}₪\n"
                            f"💵 נותר: {remaining_value}₪\n"
                            f"📅 תפוגה: {coupon['expiration'] or 'בלי תפוגה'}\n\n"
                        )
                    await update.message.reply_text(message)
                
                # Display one-time coupons
                if one_time_coupons:
                    message = get_gender_specific_text(
                        user_gender,
                        "🎫 **הקופונים החד פעמיים שלך:**\n\n",
                        "🎫 **הקופונים החד פעמיים שלך:**\n\n"
                    )
                    for coupon in one_time_coupons:
                        remaining_value = coupon['value'] - coupon['used_value']
                        decrypted_code = decrypt_coupon_code(coupon['code'])
                        message += (
                            f"🏢 **{coupon['company']}**\n"
                            f"🏷️ קוד: {decrypted_code}\n"
                            f"💰 ערך: {coupon['value']}₪\n"
                            f"💵 נותר: {remaining_value}₪\n"
                            f"🎯 מטרה: {coupon['purpose']}\n"
                            f"📅 תפוגה: {coupon['expiration'] or 'בלי תפוגה'}\n\n"
                        )
                    await update.message.reply_text(message)
            else:
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "עדיין אין לך קופונים מחברות שונות 🏢\n"
                        "בוא נוסיף את הראשון?",
                        "עדיין אין לך קופונים מחברות שונות 🏢\n"
                        "בואי נוסיף את הראשון?"
                    )
                )
                
            # Send menu again
            slots = 0
            try:
                slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user_id)
                if slots_row:
                    slots = slots_row['slots_automatic_coupons']
            except Exception as e:
                logger.error(f"Error fetching slots_automatic_coupons: {e}")
            await update.message.reply_text(get_main_menu_text(user_gender, slots))
            
        elif user_message == "2":
            # Set user state for company selection
            user_states[chat_id] = "choose_company"
            
            # Fetch user's companies
            companies_query = """
                SELECT DISTINCT company 
                FROM coupon 
                WHERE user_id = $1 
                AND status = 'פעיל' 
                ORDER BY company ASC
            """
            companies = await conn.fetch(companies_query, user_id)
            
            if companies:
                message = get_gender_specific_text(
                    user_gender,
                    "🏢 **בחר חברה מהרשימה:**\n\n",
                    "🏢 **בחרי חברה מהרשימה:**\n\n"
                )
                for i, company in enumerate(companies, 1):
                    message += f"{i}. {company['company']}\n"
                message += get_gender_specific_text(
                    user_gender,
                    "\nלא רואה את החברה? בחר \"אחר\"",
                    "\nלא רואה את החברה? בחרי \"אחר\""
                )
                await update.message.reply_text(message)
            else:
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        '🤷‍♂️ לא מצאתי חברות פעילות',
                        '🤷‍♀️ לא מצאתי חברות פעילות'
                    )
                )
                # Reset user state
                user_states.pop(chat_id, None)
                
        elif user_message == "3":
            await start_coupon_creation(update, context, user_id)
            await conn.close()
            return
            
        elif user_message == "4":
            # Start coupon usage update process
            await start_coupon_usage_update(update, context, user_id)
            await conn.close()
            return
            
        elif user_message == "5":
            # Start coupon deletion process
            await start_coupon_deletion(update, context, user_id)
            await conn.close()
            return
            
        elif user_message == "6":
            await disconnect(update, context)
            
        elif user_message == "7":
            # AI free text analysis
            await start_ai_text_analysis(update, context, user_id)
            await conn.close()
            return
            
        else:
            # Send menu again if choice is invalid
            slots = 0
            try:
                slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user_id)
                if slots_row:
                    slots = slots_row['slots_automatic_coupons']
            except Exception as e:
                logger.error(f"Error fetching slots_automatic_coupons: {e}")
            await update.message.reply_text(get_main_menu_text(user_gender, slots))
        
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error in handle_menu_option: {e}")
        await update.message.reply_text(
            "😅 יש לי בעיה טכנית. תנסה שוב?"
        )

async def start_coupon_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    """Start coupon deletion process"""
    chat_id = update.message.chat_id
    
    # Check session validity first
    is_valid, valid_user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    try:
        conn = await get_async_db_connection()
        
        # Fetch user's companies with active coupons
        companies_query = """
            SELECT DISTINCT company 
            FROM coupon 
            WHERE user_id = $1 
            AND status = 'פעיל' 
            ORDER BY company ASC
        """
        companies = await conn.fetch(companies_query, user_id)
        
        if not companies:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אין לך קופונים פעילים למחיקה 🤷‍♂️",
                    "אין לך קופונים פעילים למחיקה 🤷‍♀️"
                )
            )
            await return_to_main_menu(update, context, chat_id)
            await conn.close()
            return
        
        # Set user state for company selection for deletion
        user_states[chat_id] = "choose_company_for_delete"
        
        # Show companies list
        message = get_gender_specific_text(
            user_gender,
            "🗑️ **מאיזה חברה תרצה למחוק קופון?**\n\n",
            "🗑️ **מאיזה חברה תרצי למחוק קופון?**\n\n"
        )
        for i, company in enumerate(companies, 1):
            message += f"{i}. {company['company']}\n"
        
        message += get_gender_specific_text(
            user_gender,
            "\nבחר מספר מהרשימה:",
            "\nבחרי מספר מהרשימה:"
        )
        
        await update.message.reply_text(message)
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error in start_coupon_deletion: {e}")
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "😅 אירעה שגיאה בתהליך. נסה שוב מהתפריט הראשי",
                "😅 אירעה שגיאה בתהליך. נסי שוב מהתפריט הראשי"
            )
        )
        await return_to_main_menu(update, context, chat_id)

async def start_coupon_usage_update(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    """Start coupon usage update process"""
    chat_id = update.message.chat_id
    
    # Check session validity first
    is_valid, valid_user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    try:
        conn = await get_async_db_connection()
        
        # Fetch user's companies with active coupons
        companies_query = """
            SELECT DISTINCT company 
            FROM coupon 
            WHERE user_id = $1 
            AND status = 'פעיל' 
            ORDER BY company ASC
        """
        companies = await conn.fetch(companies_query, user_id)
        
        if not companies:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אין לך קופונים פעילים לעדכון שימוש 🤷‍♂️",
                    "אין לך קופונים פעילים לעדכון שימוש 🤷‍♀️"
                )
            )
            await return_to_main_menu(update, context, chat_id)
            await conn.close()
            return
        
        # Set user state for company selection for usage update
        user_states[chat_id] = "choose_company_for_usage"
        
        # Show companies list
        message = get_gender_specific_text(
            user_gender,
            "📝 **איזה חברה רוצה לעדכן שימוש בקופון?**\n\n",
            "📝 **איזה חברה רוצית לעדכן שימוש בקופון?**\n\n"
        )
        for i, company in enumerate(companies, 1):
            message += f"{i}. {company['company']}\n"
        
        message += get_gender_specific_text(
            user_gender,
            "\nבחר מספר מהרשימה:",
            "\nבחרי מספר מהרשימה:"
        )
        
        await update.message.reply_text(message)
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error in start_coupon_usage_update: {e}")
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "😅 אירעה שגיאה בתהליך. נסה שוב מהתפריט הראשי",
                "😅 אירעה שגיאה בתהליך. נסי שוב מהתפריט הראשי"
            )
        )
        await return_to_main_menu(update, context, chat_id)

# --- FSM states for coupon creation ---
class CouponCreationState(Enum):
    CHOOSE_COMPANY = 1
    ENTER_NEW_COMPANY = 2
    ENTER_CODE = 3
    ENTER_COST = 4
    ENTER_VALUE = 5
    ENTER_DISCOUNT = 6
    VALIDATE_ECONOMIC = 7
    ENTER_EXPIRATION = 8
    ENTER_DESCRIPTION = 9
    ENTER_SOURCE = 10
    ASK_CREDIT_CARD = 11
    ENTER_CVV = 12
    ENTER_CARD_EXP = 13
    ASK_ONE_TIME = 14
    ENTER_PURPOSE = 15
    SUMMARY = 16
    EDIT_FIELD = 17
    CONFIRM_SAVE = 18
    FUZZY_MATCH = 19
    AI_TEXT_INPUT = 20
    AI_CONFIRM = 21
    EDIT_FIELD_SELECTION = 22  # New state for field selection during edit
    EDIT_FIELD_CONFIRM = 23    # New state for confirming fuzzy matched field
    EDIT_FIELD_VALUE = 24      # New state for entering new field value
    CHOOSE_COUPON_FOR_USAGE = 25  # New state for selecting coupon for usage update
    ASK_USAGE_TYPE = 26           # New state for asking usage type (partial/full)
    ENTER_USAGE_AMOUNT = 27       # New state for entering usage amount
    CONFIRM_USAGE_UPDATE = 28     # New state for confirming usage update
    CHOOSE_COUPON_FOR_DELETE = 29  # New state for selecting coupon for deletion
    CONFIRM_DELETE = 30            # New state for confirming deletion

# Store state and responses for each user
user_coupon_states = {}  # chat_id: {'state': CouponCreationState, 'data': {...}, 'edit_field': None}

# Helper function to get available editable fields
def get_editable_fields():
    """Return list of editable field names"""
    return [
        'חברה',
        'קוד קופון', 
        'מחיר ששולם',
        'ערך בפועל',
        'שימוש חד פעמי',
        'תאריך תפוגה',
        'תיאור',
        'מקור',
        'CVV',
        'תוקף כרטיס',
        'מטרה'
    ]

# Helper function to find best field match using fuzzy matching
def find_best_field_match(input_text):
    """Find best matching field using fuzzy matching"""
    fields = get_editable_fields()
    best_match = None
    best_ratio = 0
    
    for field in fields:
        ratio = fuzz.ratio(input_text.lower(), field.lower())
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = field
    
    return best_match, best_ratio

# Helper function to start AI text analysis
async def start_ai_text_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    """Start AI free text analysis process"""
    chat_id = update.message.chat_id
    
    # Check session validity first
    is_valid, valid_user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    try:
        # Update user's slots_automatic_coupons
        conn = await get_async_db_connection()
        update_query = """
            UPDATE users 
            SET slots_automatic_coupons = slots_automatic_coupons - 1 
            WHERE id = $1
        """
        await conn.execute(update_query, user_id)
        await conn.close()
        
        user_coupon_states[chat_id] = {
            'state': CouponCreationState.AI_TEXT_INPUT, 
            'data': {},
            'user_id': user_id
        }
        
        # Get user gender
        user_gender = await get_user_gender(user_id)
        
        # Gender-specific text with length limitation info
        msg = get_gender_specific_text(
            user_gender,
            f"🤖 **הוספת קופון חדש עם AI**\n\n"
            f"תכתוב את פרטי הקופון המלאים\n"
            f"(שם חברה, כמה שילמת עליו, כמה הוא שווה בפועל, תאריך תפוגה וכו')\n\n"
            f"📝 דוגמה:\n"
            f"\"קניתי קופון של מקדונלדס ב88 שקל ששווה 100 שקל, תוקף עד 30/06/2025\"\n\n"
            f"⚠️ מקסימום {MAX_AI_TEXT_LENGTH} תווים\n\n"
            f"כתוב את כל הפרטים שיש לך:",
            f"🤖 **הוספת קופון חדש עם AI**\n\n"
            f"תכתבי את פרטי הקופון המלאים\n"
            f"(שם חברה, כמה שילמת עליו, כמה הוא שווה בפועל, תאריך תפוגה וכו')\n\n"
            f"📝 דוגמה:\n"
            f"\"קניתי קופון של מקדונלדס ב88 שקל ששווה 100 שקל, תוקף עד 30/06/2025\"\n\n"
            f"⚠️ מקסימום {MAX_AI_TEXT_LENGTH} תווים\n\n"
            f"כתבי את כל הפרטים שיש לך:"
        )
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"Error updating slots_automatic_coupons: {e}")
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "😅 אירעה שגיאה בעדכון הנתונים\n"
                "אנא נסה שוב מאוחר יותר",
                "😅 אירעה שגיאה בעדכון הנתונים\n"
                "אנא נסי שוב מאוחר יותר"
            )
        )
        await return_to_main_menu(update, context, chat_id)

# Function to handle AI text analysis
async def handle_ai_text_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, text):
    """Analyze free text using GPT and return summary"""
    chat_id = update.message.chat_id
    user_gender = await get_user_gender(user_id)
    
    # Validate AI text input
    is_valid, error_msg = validate_ai_text_input(text)
    if not is_valid:
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                f"❌ {error_msg}\n\nתנסה שוב עם טקסט באורך מתאים:",
                f"❌ {error_msg}\n\nתנסי שוב עם טקסט באורך מתאים:"
            )
        )
        return
    
    try:
        # Send loading message
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "🤖 מנתח את הטקסט עם GPT...\n⏳ אנא המתן רגע",
                "🤖 מנתחת את הטקסט עם GPT...\n⏳ אנא המתיני רגע"
            )
        )
        
        # Get companies list from database
        companies = await get_companies_list(user_id)
        
        # Call GPT function
        extracted_data_df, pricing_df = extract_coupon_detail_sms(text, companies)
        
        if not extracted_data_df.empty:
            # Convert data to dictionary
            extracted_data = extracted_data_df.iloc[0].to_dict()
            
            # Convert data for JSON serialization
            for key, value in extracted_data.items():
                if hasattr(value, 'isna') and value.isna():
                    extracted_data[key] = None
                elif hasattr(value, 'item'):  # numpy types
                    extracted_data[key] = value.item()
            
            # Validate extracted monetary values
            cost = extracted_data.get('עלות', 0) or 0
            value = extracted_data.get('ערך מקורי', 0) or 0
            
            # Apply business rules validation
            cost_valid, cost_value, cost_error = validate_monetary_value(str(cost), "המחיר ששולם", allow_zero=True)
            value_valid, value_value, value_error = validate_monetary_value(str(value), "הערך בפועל", allow_zero=False)
            
            if not cost_valid or not value_valid:
                error_message = cost_error or value_error
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        f"❌ {error_message}\n\nתנסה שוב עם ערכים תקינים:",
                        f"❌ {error_message}\n\nתנסי שוב עם ערכים תקינים:"
                    )
                )
                return
            
            # Save data in user state
            data = {
                'company': extracted_data.get('חברה', ''),
                'code': extracted_data.get('קוד קופון', ''),
                'cost': cost_value,
                'value': value_value,
                'description': extracted_data.get('תיאור', '') or None,
                'expiration': None,
                'source': None,
                'cvv': None,
                'card_exp': None,
                'is_one_time': False,
                'purpose': None
            }
            
            # Handle expiration date with validation
            try:
                expiration_str = extracted_data.get('תאריך תפוגה')
                if expiration_str and expiration_str != 'None':
                    # Try to parse the date and validate it
                    is_valid_date, parsed_date, date_error = validate_date_format(expiration_str.replace('-', '/'))
                    if is_valid_date:
                        data['expiration'] = parsed_date
                    else:
                        logger.warning(f"Invalid date from AI: {expiration_str}, error: {date_error}")
            except Exception as e:
                logger.error(f"Error parsing expiration date from AI: {e}")
            
            # Update user state
            user_coupon_states[chat_id]['data'] = data
            user_coupon_states[chat_id]['state'] = CouponCreationState.AI_CONFIRM
            
            # Send summary for confirmation
            await send_ai_coupon_summary(update, data, user_gender)
            
        else:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "😅 לא הצלחתי לנתח את הטקסט\n"
                    "תוכל לנסות שוב עם פרטים יותר ברורים?\n"
                    "או לבחור 3 מהתפריט להוספה ידנית",
                    "😅 לא הצלחתי לנתח את הטקסט\n"
                    "תוכלי לנסות שוב עם פרטים יותר ברורים?\n"
                    "או לבחור 3 מהתפריט להוספה ידנית"
                )
            )
            await return_to_main_menu(update, context, chat_id)
            
    except Exception as e:
        logger.error(f"Error in AI text analysis: {e}")
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "😅 אירעה שגיאה בניתוח הטקסט\n"
                "תנסה שוב או בחר אפשרות אחרת מהתפריט",
                "😅 אירעה שגיאה בניתוח הטקסט\n"
                "תנסי שוב או בחרי אפשרות אחרת מהתפריט"
            )
        )
        await return_to_main_menu(update, context, chat_id)

# Function to send AI coupon summary for confirmation
async def send_ai_coupon_summary(update, data, user_gender):
    """Send AI analyzed coupon summary for user confirmation"""
    
    # Create list of fields with values
    fields = []
    empty_fields = []
    
    # Required fields - always displayed
    fields.append(f"🏢 חברה: {data.get('company','לא צוין')}")
    fields.append(f"🎫 קוד קופון: {data.get('code','לא צוין')}")
    fields.append(f"💰 מחיר ששולם: {data.get('cost','לא צוין')}")
    fields.append(f"💎 ערך בפועל: {data.get('value','לא צוין')}")
    fields.append(f"🔒 שימוש חד פעמי: {'כן' if data.get('is_one_time') else 'לא'}")
    
    # Optional fields - displayed only if they have values
    if data.get('expiration'):
        fields.append(f"📅 תאריך תפוגה: {data['expiration']}")
    else:
        empty_fields.append("📅 תאריך תפוגה: לא צוין")
        
    if data.get('description'):
        fields.append(f"📝 תיאור: {data['description']}")
    else:
        empty_fields.append("📝 תיאור: לא צוין")
        
    if data.get('source'):
        fields.append(f"🎯 מקור: {data['source']}")
    else:
        empty_fields.append("🎯 מקור: לא צוין")
        
    if data.get('cvv'):
        fields.append(f"💳 CVV: {data['cvv']}")
    else:
        empty_fields.append("💳 CVV: לא צוין")
        
    if data.get('card_exp'):
        fields.append(f"💳 תוקף כרטיס: {data['card_exp']}")
    else:
        empty_fields.append("💳 תוקף כרטיס: לא צוין")
        
    if data.get('purpose'):
        fields.append(f"🎯 מטרה: {data['purpose']}")
    else:
        empty_fields.append("🎯 מטרה: לא צוין")
    
    # Build message
    summary = "🤖 **ניתוח AI הושלם!**\n\n"
    summary += "📋 סיכום הקופון החדש:\n\n"
    summary += "\n".join(fields)
    
    # Add empty fields at the end
    if empty_fields:
        summary += "\n\nשדות ריקים:\n"
        summary += "\n".join(empty_fields)
    
    summary += get_gender_specific_text(
        user_gender,
        "\n\nהאם הפרטים נכונים? (כן/לא)",
        "\n\nהאם הפרטים נכונים? (כן/לא)"
    )
    
    await update.message.reply_text(summary)

# Get companies list from DB
async def get_companies_list(user_id):
    database_url = os.getenv('DATABASE_URL')
    if database_url.startswith('postgresql+psycopg2://'):
        database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
    import asyncpg
    conn = await asyncpg.connect(database_url, statement_cache_size=0)
    # Query to show all companies in system
    companies = await conn.fetch("SELECT DISTINCT name FROM companies ORDER BY name ASC")
    await conn.close()
    return [c['name'] for c in companies]

# Start coupon creation process
async def start_coupon_creation(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    chat_id = update.message.chat_id
    
    # Check session validity first
    is_valid, valid_user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    companies = await get_companies_list(user_id)
    user_coupon_states[chat_id] = {'state': CouponCreationState.FUZZY_MATCH, 'data': {}, 'companies': companies}
    
    # Get user gender
    user_gender = await get_user_gender(user_id)
    
    # Gender-specific text
    msg = get_gender_specific_text(
        user_gender,
        "מה שם החברה של הקופון?",
        "מה שם החברה של הקופון?"
    )
    await update.message.reply_text(msg)

async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id):
    """Return user to main menu and clear coupon state"""
    user_coupon_states.pop(chat_id, None)
    
    # Check session validity first
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    # Get user gender
    conn = await get_async_db_connection()
    
    # Get slots for menu
    slots = 0
    if user_id:
        try:
            slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user_id)
            if slots_row:
                slots = slots_row['slots_automatic_coupons']
        except Exception as e:
            logger.error(f"Error fetching slots_automatic_coupons: {e}")
    
    await conn.close()
    
    await update.message.reply_text(get_main_menu_text(user_gender, slots))

# Function to check if text is considered empty field
def is_empty_field(text):
    """Check if text is considered empty field"""
    empty_keywords = ['אין', 'לא', 'ריק', 'ללא', 'none', 'no', 'empty', '']
    return text.strip().lower() in empty_keywords

# Continue coupon creation process (step by step)
async def handle_coupon_creation(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    if not state_obj:
        await update.message.reply_text("שגיאה פנימית. נסה שוב מהתפריט.")
        return
    
    # Check session validity first for any coupon creation step
    is_valid, valid_user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        # Clear coupon state and return session expired message
        user_coupon_states.pop(chat_id, None)
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    state = state_obj['state']
    data = state_obj['data']
    companies = state_obj.get('companies', [])
    text = update.message.text.strip()

    # Get user gender
    user_gender = await get_user_gender(user_id)

    # Check if user wants to return to main menu
    if text.lower() in ['תפריט', 'חזור', 'ביטול', 'exit', 'menu', 'cancel']:
        await return_to_main_menu(update, context, chat_id)
        return

    # Handle coupon selection for usage update
    if state == CouponCreationState.CHOOSE_COUPON_FOR_USAGE:
        await handle_coupon_selection_for_usage(update, context, text, user_id)
        return

    # Handle coupon selection for deletion
    if state == CouponCreationState.CHOOSE_COUPON_FOR_DELETE:
        await handle_coupon_selection_for_delete(update, context, text, user_id)
        return

    # Handle delete confirmation
    if state == CouponCreationState.CONFIRM_DELETE:
        await handle_delete_confirmation(update, context, text, user_id)
        return

    # Handle usage type selection (partial or full)
    if state == CouponCreationState.ASK_USAGE_TYPE:
        await handle_usage_type_selection(update, context, text, user_id)
        return

    # Handle usage amount entry
    if state == CouponCreationState.ENTER_USAGE_AMOUNT:
        await handle_usage_amount_entry(update, context, text, user_id)
        return

    # Handle usage update confirmation
    if state == CouponCreationState.CONFIRM_USAGE_UPDATE:
        await handle_usage_update_confirmation(update, context, text, user_id)
        return

    # Handle AI free text analysis
    if state == CouponCreationState.AI_TEXT_INPUT:
        await handle_ai_text_analysis(update, context, user_id, text)
        return

    # Handle AI confirmation
    if state == CouponCreationState.AI_CONFIRM:
        if text.lower() not in ['כן', 'לא']:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אנא ענה רק 'כן' או 'לא'",
                    "אנא עני רק 'כן' או 'לא'"
                )
            )
            return
            
        if text.lower() == 'כן':
            await save_coupon_to_db(update, data, user_id)
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "✅ הקופון נשמר בהצלחה!",
                    "✅ הקופון נשמר בהצלחה!"
                )
            )
            await return_to_main_menu(update, context, chat_id)
        else:
            # User wants to edit - move to edit field selection
            state_obj['state'] = CouponCreationState.EDIT_FIELD_SELECTION
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "איזה שדה תרצה לערוך? כתוב את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:\n\n"
                    "💡 שדה זה אחד מפרטי הקופון כמו:\n"
                    "• שם החברה\n"
                    "• קוד הקופון\n"
                    "  וכו׳",
                    "איזה שדה תרצי לערוך? כתבי את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:\n\n"
                    "💡 שדה זה אחד מפרטי הקופון כמו:\n"
                    "• שם החברה\n"
                    "• קוד הקופון\n"
                    "  וכו׳",
                )
            )
        return

    # Handle field selection for editing
    if state == CouponCreationState.EDIT_FIELD_SELECTION:
        best_match, best_ratio = find_best_field_match(text)
        
        if best_ratio == 100:
            # Exact match - proceed to edit
            state_obj['edit_field'] = best_match
            state_obj['state'] = CouponCreationState.EDIT_FIELD_VALUE
            await ask_for_field_value(update, best_match, user_gender)
        elif best_ratio >= 90:
            # Good match - ask for confirmation
            state_obj['suggested_field'] = best_match
            state_obj['state'] = CouponCreationState.EDIT_FIELD_CONFIRM
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    f"האם התכוונת ל\"{best_match}\"? (כן/לא)",
                    f"האם התכוונת ל\"{best_match}\"? (כן/לא)"
                )
            )
        else:
            # Poor match - ask to try again
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "לא מצאתי את השם של השדה שאתה רוצה לערוך, תסתכל בהודעה המסכמת ותגיד לי במדויק את שם השדה",
                    "לא מצאתי את השם של השדה שאת רוצה לערוך, תסתכלי בהודעה המסכמת ותגידי לי במדויק את שם השדה"
                )
            )
        return

    # Handle field confirmation for fuzzy match
    if state == CouponCreationState.EDIT_FIELD_CONFIRM:
        if text.lower() not in ['כן', 'לא']:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אנא ענה רק 'כן' או 'לא'",
                    "אנא עני רק 'כן' או 'לא'"
                )
            )
            return
            
        if text.lower() == 'כן':
            # User confirmed - proceed to edit
            suggested_field = state_obj.get('suggested_field')
            state_obj['edit_field'] = suggested_field
            state_obj['state'] = CouponCreationState.EDIT_FIELD_VALUE
            await ask_for_field_value(update, suggested_field, user_gender)
        else:
            # User declined - ask for field name again
            state_obj['state'] = CouponCreationState.EDIT_FIELD_SELECTION
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "איזה שדה תרצה לערוך? כתוב את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:\n\n"
                    "💡 שדה זה אחד מפרטי הקופון כמו:\n"
                    "• שם החברה\n"
                    "• קוד הקופון\n"
                    "  וכו׳",
                    "איזה שדה תרצי לערוך? כתבי את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:\n\n"
                    "💡 שדה זה אחד מפרטי הקופון כמו:\n"
                    "• שם החברה\n"
                    "• קוד הקופון\n"
                    "  וכו׳",
                )
            )
        return

    # Handle new field value entry
    if state == CouponCreationState.EDIT_FIELD_VALUE:
        edit_field = state_obj.get('edit_field')
        await handle_field_edit(update, context, edit_field, text, data, user_gender)
        return

    # Fuzzy company name matching stage
    if state == CouponCreationState.FUZZY_MATCH:
        
        # Find best matches
        matches = []
        for company in companies:
            ratio = fuzz.ratio(text.lower(), company.lower())
            if ratio >= 90:  # Only matches above 90%
                matches.append((company, ratio))
        
        # Sort by match percentage
        matches.sort(key=lambda x: x[1], reverse=True)
        
        if matches:
            # Show matches to user
            msg = get_gender_specific_text(
                user_gender,
                "בחר את האפשרות המתאימה:",
                "בחרי את האפשרות המתאימה:"
            )
            for i, (company, ratio) in enumerate(matches, 1):
                msg += f"\n{i}. {company}"
            msg += f"\n{len(matches)+1}. זו חברה אחרת"
            
            # Save matches in current state
            state_obj['matches'] = matches
            state_obj['state'] = CouponCreationState.CHOOSE_COMPANY
            await update.message.reply_text(msg)
        else:
            # Check if this is first or second attempt
            if 'fuzzy_attempt' not in state_obj:
                # First attempt
                state_obj['fuzzy_attempt'] = 1
                msg = get_gender_specific_text(
                    user_gender,
                    "לא מצאתי התאמות דומות. האם תוכל לכתוב שוב את שם החברה? (ניתן לנסות לכתוב גם באנגלית)",
                    "לא מצאתי התאמות דומות. האם תוכלי לכתוב שוב את שם החברה? (ניתן לנסות לכתוב גם באנגלית)"
                )
                await update.message.reply_text(msg)
            else:
                # Second attempt - continue as new company
                data['company'] = text
                state_obj['state'] = CouponCreationState.ENTER_CODE
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "מה קוד הקופון/הקוד המזהה?",
                        "מה קוד הקופון/הקוד המזהה?"
                    )
                )
        return

    # Company selection from matches stage
    if state == CouponCreationState.CHOOSE_COMPANY:
        try:
            choice = int(text)
            matches = state_obj.get('matches', [])
            
            if 1 <= choice <= len(matches):
                # Selection from matches
                data['company'] = matches[choice-1][0]
                state_obj['state'] = CouponCreationState.ENTER_CODE
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "מה קוד הקופון/הקוד המזהה?",
                        "מה קוד הקופון/הקוד המזהה?"
                    )
                )
            elif choice == len(matches) + 1:
                # Selection of new company
                state_obj['state'] = CouponCreationState.ENTER_NEW_COMPANY
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "מה שם החברה החדשה?",
                        "מה שם החברה החדשה?"
                    )
                )
            else:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אנא בחר מספר תקין מהרשימה.",
                    "אנא בחרי מספר תקין מהרשימה."
                )
            )
        return

    # Enter new company name stage
    if state == CouponCreationState.ENTER_NEW_COMPANY:
        if not text:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "יש להזין שם חברה חדשה.",
                    "יש להזין שם חברה חדשה."
                )
            )
            return
        
        # Check if this new company name already exists with fuzzy matching
        best_match = None
        best_ratio = 0
        for company in companies:
            ratio = fuzz.ratio(text.lower(), company.lower())
            if ratio == 100:  # Exact match
                best_match = company
                best_ratio = ratio
                break
        
        if best_ratio == 100:
            # Found exact match - use existing company
            data['company'] = best_match
        else:
            # No exact match - use as new company
            data['company'] = text
            
        state_obj['state'] = CouponCreationState.ENTER_CODE
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה קוד הקופון/הקוד המזהה?",
                "מה קוד הקופון/הקוד המזהה?"
            )
        )
        return

    # Coupon code stage
    if state == CouponCreationState.ENTER_CODE:
        if not text:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "יש להזין קוד קופון.",
                    "יש להזין קוד קופון."
                )
            )
            return
        data['code'] = text
        state_obj['state'] = CouponCreationState.ENTER_COST
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                f"כמה שילמת על הקופון?",
                f"כמה שילמת על הקופון?"
            )
        )
        return

    # Price stage with enhanced validation
    if state == CouponCreationState.ENTER_COST:
        is_valid, value, error_msg = validate_monetary_value(text, "המחיר ששולם", allow_zero=True)
        if not is_valid:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    f"❌ {error_msg}\n\nכמה שילמת על הקופון? (0-{MAX_COUPON_VALUE:,} שח)",
                    f"❌ {error_msg}\n\nכמה שילמת על הקופון? (0-{MAX_COUPON_VALUE:,} שח)"
                )
            )
            return
        
        data['cost'] = value
        state_obj['state'] = CouponCreationState.ENTER_VALUE
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                f"כמה הקופון שווה בפועל?",
                f"כמה הקופון שווה בפועל?"
            )
        )
        return

    # Value stage with enhanced validation
    if state == CouponCreationState.ENTER_VALUE:
        is_valid, value, error_msg = validate_monetary_value(text, "הערך בפועל", allow_zero=False)
        if not is_valid:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    f"❌ {error_msg}\n\nכמה הקופון שווה בפועל? (1-{MAX_COUPON_VALUE:,} שח)",
                    f"❌ {error_msg}\n\nכמה הקופון שווה בפועל? (1-{MAX_COUPON_VALUE:,} שח)"
                )
            )
            return
        
        cost = data.get('cost', 0)
        
        # Check if value is greater than cost (for non-zero cost)
        if cost > 0 and value <= cost:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    f"😊 רגע, משהו לא מסתדר כאן!\n\n"
                    f"שילמת על הקופון {cost}₪ אבל הערך שהזנת הוא {value}₪\n"
                    f"הערך בפועל צריך להיות יותר ממה ששילמת, כדי שתהיה לך הנחה!\n\n"
                    f"בוא נתחיל מחדש:\n"
                    f"כמה שילמת על הקופון?",
                    f"😊 רגע, משהו לא מסתדר כאן!\n\n"
                    f"שילמת על הקופון {cost}₪ אבל הערך שהזנת הוא {value}₪\n"
                    f"הערך בפועל צריך להיות יותר ממה ששילמת, כדי שתהיה לך הנחה!\n\n"
                    f"בואי נתחיל מחדש:\n"
                    f"כמה שילמת על הקופון?"
                )
            )
            # Reset to cost entry stage
            state_obj['state'] = CouponCreationState.ENTER_COST
            return
        
        data['value'] = value
        
        # Calculate discount percentage and show celebration message
        if cost > 0:
            discount_percentage = round(((value - cost) / value) * 100)
            celebration_msg = get_gender_specific_text(
                user_gender,
                f"🎉 יפה! השגת {discount_percentage}% הנחה! כל הכבוד! 🎉",
                f"🎉 יפה! השגת {discount_percentage}% הנחה! כל הכבוד! 🎉"
            )
        else:
            celebration_msg = get_gender_specific_text(
                user_gender,
                f"🎉 יפה! קופון חינמי בשווי {value}₪! זה 100% הנחה! 🎉",
                f"🎉 יפה! קופון חינמי בשווי {value}₪! זה 100% הנחה! 🎉"
            )
        await update.message.reply_text(celebration_msg)
        
        state_obj['state'] = CouponCreationState.ENTER_EXPIRATION
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה תאריך התפוגה של הקופון? (פורמט: DD/MM/YYYY)\n"
                "אם אין תאריך תפוגה, כתוב 'אין'",
                "מה תאריך התפוגה של הקופון? (פורמט: DD/MM/YYYY)\n"
                "אם אין תאריך תפוגה, כתובי 'אין'"
            )
        )
        return

    # Expiration date with enhanced validation
    if state == CouponCreationState.ENTER_EXPIRATION:
        if is_empty_field(text):
            data['expiration'] = None
        else:
            is_valid, parsed_date, error_msg = validate_date_format(text)
            if not is_valid:
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        f"❌ {error_msg}\n\nנסה שוב (DD/MM/YYYY) או כתוב 'אין' אם אין תאריך תפוגה",
                        f"❌ {error_msg}\n\nנסי שוב (DD/MM/YYYY) או כתבי 'אין' אם אין תאריך תפוגה"
                    )
                )
                return
            data['expiration'] = parsed_date
            
        state_obj['state'] = CouponCreationState.ENTER_DESCRIPTION
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "יש לך הערה או תיאור לקופון? 📝\n\n"
                "💡 המלצה: אפשר להוסיף פה את ה-SMS שקיבלת כשקנית את הקופון\n\n"
                "אם אין - פשוט תכתוב 'אין'",
                "יש לך הערה או תיאור לקופון? 📝\n\n"
                "💡 המלצה: אפשר להוסיף פה את ה-SMS שקיבלת כשקנית את הקופון\n\n"
                "אם אין - פשוט תכתבי 'אין'"
            )
        )
        return

    # Description
    if state == CouponCreationState.ENTER_DESCRIPTION:
        data['description'] = None if is_empty_field(text) else text
        state_obj['state'] = CouponCreationState.ENTER_SOURCE
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מאיפה קיבלת את הקופון?\n"
                "אם לא רלוונטי, תכתוב 'אין\n\n'"
                "יעזור לך בעתיד אם ישאלו אותך בבית העסק",
                "מאיפה קיבלת את הקופון?\n"
                "אם לא רלוונטי, תכתבי 'אין\n\n'"
                "יעזור לך בעתיד אם ישאלו אותך בבית העסק"
            )
        )
        return
    
    # Source
    if state == CouponCreationState.ENTER_SOURCE:
        data['source'] = None if is_empty_field(text) else text
        state_obj['state'] = CouponCreationState.ASK_CREDIT_CARD
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "האם להכניס תוקף כרטיס ו-CVV? (כן/לא)",
                "האם להכניס תוקף כרטיס ו-CVV? (כן/לא)"
            )
        )
        return

    # Whether to enter credit card details
    if state == CouponCreationState.ASK_CREDIT_CARD:
        if text.lower() not in ['כן', 'לא']:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אנא ענה רק 'כן' או 'לא'",
                    "אנא עני רק 'כן' או 'לא'"
                )
            )
            return
            
        if text.lower() == 'כן':
            state_obj['state'] = CouponCreationState.ENTER_CVV
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "מה ה-CVV?",
                    "מה ה-CVV?"
                )
            )
        else:
            data['cvv'] = None
            data['card_exp'] = None
            state_obj['state'] = CouponCreationState.ASK_ONE_TIME
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "האם זה קוד לשימוש חד פעמי? (כן/לא)\n\n"
                    "הסבר: קופון שחייבים להשתמש בכל הסכום שלו בקניה הקרוב (למשל - קפה חינם, כניסה לחדר כושר וכו׳)",
                    "האם זה קוד לשימוש חד פעמי? (כן/לא)\n\n"
                    "הסבר: קופון שחייבים להשתמש בכל הסכום שלו בקניה הקרוב (למשל - קפה חינם, כניסה לחדר כושר וכו׳)",
                )
            )
        return

    # CVV
    if state == CouponCreationState.ENTER_CVV:
        # Check input is 3-4 digit number
        if not text.isdigit() or len(text) not in [3, 4]:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אנא הזן CVV תקין (3 או 4 ספרות)",
                    "אנא הזיני CVV תקין (3 או 4 ספרות)"
                )
            )
            return
        data['cvv'] = text
        state_obj['state'] = CouponCreationState.ENTER_CARD_EXP
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה תוקף הכרטיס? (פורמט: MM/YY)",
                "מה תוקף הכרטיס? (פורמט: MM/YY)"
            )
        )
        return

    # Card expiration with enhanced validation
    if state == CouponCreationState.ENTER_CARD_EXP:
        try:
            # Check MM/YY format
            if not re.match(r'^\d{2}/\d{2}$', text):
                raise ValueError("Invalid format")
            
            month, year = text.split('/')
            
            # Check month is number between 1-12
            if not month.isdigit() or not (1 <= int(month) <= 12):
                raise ValueError("Invalid month")
            
            # Check year is 2-digit number
            if not year.isdigit() or len(year) != 2:
                raise ValueError("Invalid year")
            
            data['card_exp'] = text
            state_obj['state'] = CouponCreationState.ASK_ONE_TIME
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "האם זה קוד לשימוש חד פעמי? (כן/לא)",
                    "האם זה קוד לשימוש חד פעמי? (כן/לא)"
                )
            )
        except ValueError:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "פורמט לא תקין. אנא הזן תאריך בפורמט MM/YY (למשל: 12/28)",
                    "פורמט לא תקין. אנא הזיני תאריך בפורמט MM/YY (למשל: 12/28)"
                )
            )
        return

    # One-time use
    if state == CouponCreationState.ASK_ONE_TIME:
        if text.lower() not in ['כן', 'לא']:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אנא ענה רק 'כן' או 'לא'",
                    "אנא עני רק 'כן' או 'לא'"
                )
            )
            return
            
        data['is_one_time'] = text.lower() == 'כן'
        if data['is_one_time']:
            state_obj['state'] = CouponCreationState.ENTER_PURPOSE
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "מה מטרת הקופון?\n"
                    "אם אין מטרה, כתוב 'אין'\n\n"
                    "למשל: קפה חינם, כניסה לחדר כושר וכו׳",
                    "מה מטרת הקופון?\n"
                    "אם אין מטרה, כתבי 'אין'\n\n"
                    "למשל: קפה חינם, כניסה לחדר כושר וכו׳",
                )
            )
        else:
            data['purpose'] = None
            state_obj['state'] = CouponCreationState.SUMMARY
            await send_coupon_summary(update, data, user_gender)
        return

    # Purpose
    if state == CouponCreationState.ENTER_PURPOSE:
        data['purpose'] = None if is_empty_field(text) else text
        state_obj['state'] = CouponCreationState.SUMMARY
        await send_coupon_summary(update, data, user_gender)
        return

    # Confirmation summary
    if state == CouponCreationState.CONFIRM_SAVE:
        if text.lower() not in ['כן', 'לא']:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אנא ענה רק 'כן' או 'לא'",
                    "אנא עני רק 'כן' או 'לא'"
                )
            )
            return
            
        if text.lower() == 'כן':
            await save_coupon_to_db(update, data, user_id)
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "✅ הקופון נשמר בהצלחה!",
                    "✅ הקופון נשמר בהצלחה!"
                )
            )
            await return_to_main_menu(update, context, chat_id)
        else:
            # User wants to edit - move to edit field selection
            state_obj['state'] = CouponCreationState.EDIT_FIELD_SELECTION
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "איזה שדה תרצה לערוך? כתוב את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:\n\n"
                    "💡 שדה זה אחד מפרטי הקופון כמו:\n"
                    "• שם החברה\n"
                    "• קוד הקופון\n"
                    "  וכו׳",
                    "איזה שדה תרצי לערוך? כתבי את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:\n\n"
                    "💡 שדה זה אחד מפרטי הקופון כמו:\n"
                    "• שם החברה\n"
                    "• קוד הקופון\n"
                    "  וכו׳",
                )
            )
        return

# Handle coupon selection for usage update
async def handle_coupon_selection_for_usage(update: Update, context: ContextTypes.DEFAULT_TYPE, text, user_id):
    """Handle coupon selection for usage update"""
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    user_gender = await get_user_gender(user_id)
    
    try:
        choice = int(text)
        coupons = state_obj.get('coupons', [])
        
        if choice < 1 or choice > len(coupons):
            raise ValueError("Invalid choice")
        
        # Get selected coupon
        selected_coupon = coupons[choice - 1]
        state_obj['selected_coupon'] = selected_coupon
        state_obj['state'] = CouponCreationState.ASK_USAGE_TYPE
        
        # Show coupon details and ask for usage type
        remaining_value = selected_coupon['value'] - selected_coupon['used_value']
        decrypted_code = decrypt_coupon_code(selected_coupon['code'])
        
        message = get_gender_specific_text(
            user_gender,
            f"📝 **עדכון שימוש בקופון:**\n\n"
            f"🏢 חברה: {selected_coupon['company']}\n"
            f"🏷️ קוד: {decrypted_code}\n"
            f"💰 ערך כולל: {selected_coupon['value']}₪\n"
            f"💵 נותר לשימוש: {remaining_value}₪\n\n"
            f"מה ברצונך לעשות?\n\n"
            f"1️⃣ לעדכן סכום שהשתמשת\n"
            f"2️⃣ לסמן כנוצל לגמרי\n\n"
            f"כתוב 1 או 2:",
            f"📝 **עדכון שימוש בקופון:**\n\n"
            f"🏢 חברה: {selected_coupon['company']}\n"
            f"🏷️ קוד: {decrypted_code}\n"
            f"💰 ערך כולל: {selected_coupon['value']}₪\n"
            f"💵 נותר לשימוש: {remaining_value}₪\n\n"
            f"מה ברצונך לעשות?\n\n"
            f"1️⃣ לעדכן סכום שהשתמשת\n"
            f"2️⃣ לסמן כנוצל לגמרי\n\n"
            f"כתבי 1 או 2:"
        )
        
        await update.message.reply_text(message)
        
    except ValueError:
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "אנא בחר מספר תקין מהרשימה.",
                "אנא בחרי מספר תקין מהרשימה."
            )
        )

# Handle coupon selection for deletion
async def handle_coupon_selection_for_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, text, user_id):
    """Handle coupon selection for deletion"""
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    user_gender = await get_user_gender(user_id)
    
    try:
        choice = int(text)
        coupons = state_obj.get('coupons', [])
        
        if choice < 1 or choice > len(coupons):
            raise ValueError("Invalid choice")
        
        # Get selected coupon
        selected_coupon = coupons[choice - 1]
        state_obj['selected_coupon'] = selected_coupon
        state_obj['state'] = CouponCreationState.CONFIRM_DELETE
        
        # Show coupon details and ask for confirmation
        remaining_value = selected_coupon['value'] - selected_coupon['used_value']
        decrypted_code = decrypt_coupon_code(selected_coupon['code'])
        
        message = get_gender_specific_text(
            user_gender,
            f"⚠️ **אישור מחיקת קופון:**\n\n"
            f"🏢 חברה: {selected_coupon['company']}\n"
            f"🏷️ קוד: {decrypted_code}\n"
            f"💰 ערך כולל: {selected_coupon['value']}₪\n"
            f"💵 נותר לשימוש: {remaining_value}₪\n\n"
            f"❗ האם אתה בטוח שברצונך למחוק את הקופון הזה?\n"
            f"פעולה זו לא ניתנת לביטול!\n\n"
            f"כתוב 'כן' לאישור או 'לא' לביטול:",
            f"⚠️ **אישור מחיקת קופון:**\n\n"
            f"🏢 חברה: {selected_coupon['company']}\n"
            f"🏷️ קוד: {decrypted_code}\n"
            f"💰 ערך כולל: {selected_coupon['value']}₪\n"
            f"💵 נותר לשימוש: {remaining_value}₪\n\n"
            f"❗ האם את בטוחה שברצונך למחוק את הקופון הזה?\n"
            f"פעולה זו לא ניתנת לביטול!\n\n"
            f"כתבי 'כן' לאישור או 'לא' לביטול:"
        )
        
        await update.message.reply_text(message)
        
    except ValueError:
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "אנא בחר מספר תקין מהרשימה.",
                "אנא בחרי מספר תקין מהרשימה."
            )
        )

# Handle delete confirmation
async def handle_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, text, user_id):
    """Handle deletion confirmation"""
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    user_gender = await get_user_gender(user_id)
    
    if text.lower() not in ['כן', 'לא']:
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "אנא ענה רק 'כן' או 'לא'",
                "אנא עני רק 'כן' או 'לא'"
            )
        )
        return
    
    if text.lower() == 'כן':
        # Execute the deletion
        await execute_coupon_deletion(update, context, state_obj, user_id)
        await return_to_main_menu(update, context, chat_id)
    else:
        # Cancel and return to main menu
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "המחיקה בוטלה. חוזר לתפריט הראשי.",
                "המחיקה בוטלה. חוזרת לתפריט הראשי."
            )
        )
        await return_to_main_menu(update, context, chat_id)

# Execute coupon deletion
async def execute_coupon_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, state_obj, user_id):
    """Execute the actual coupon deletion in database"""
    chat_id = update.message.chat_id
    user_gender = await get_user_gender(user_id)
    selected_coupon = state_obj.get('selected_coupon')
    
    # Check if user is verified for deletion
    if not await is_user_verified_for_deletion(user_id):
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "❌ אין לך הרשאה למחיקת קופונים. אנא וודא שאימתת את החיבור לטלגרם.",
                "❌ אין לך הרשאה למחיקת קופונים. אנא וודאי שאימתת את החיבור לטלגרם."
            )
        )
        return
    
    try:
        conn = await get_async_db_connection()
        
        # Check if coupon has related transactions
        check_transactions_query = """
            SELECT COUNT(*) as transaction_count
            FROM coupon_transaction 
            WHERE coupon_id = $1
        """
        transaction_result = await conn.fetchrow(check_transactions_query, selected_coupon['id'])
        transaction_count = transaction_result['transaction_count'] if transaction_result else 0
        
        # Check if coupon has regular transactions (sales)
        check_sales_query = """
            SELECT COUNT(*) as sales_count
            FROM transactions 
            WHERE coupon_id = $1
        """
        sales_result = await conn.fetchrow(check_sales_query, selected_coupon['id'])
        sales_count = sales_result['sales_count'] if sales_result else 0
        
        total_related_records = transaction_count + sales_count
        
        if total_related_records > 0:
            # If coupon has related records, perform cascade deletion
            try:
                # Start transaction
                async with conn.transaction():
                    # Delete related coupon_transaction records first
                    if transaction_count > 0:
                        await conn.execute(
                            "DELETE FROM coupon_transaction WHERE coupon_id = $1", 
                            selected_coupon['id']
                        )
                    
                    # Delete related transaction records  
                    if sales_count > 0:
                        await conn.execute(
                            "DELETE FROM transactions WHERE coupon_id = $1", 
                            selected_coupon['id']
                        )
                    
                    # Delete the coupon itself
                    result = await conn.execute(
                        "DELETE FROM coupon WHERE id = $1 AND user_id = $2",
                        selected_coupon['id'], user_id
                    )
                
                decrypted_code = decrypt_coupon_code(selected_coupon['code'])
                success_msg = get_gender_specific_text(
                    user_gender,
                    f"🗑️ הקופון נמחק בהצלחה!\n\n"
                    f"🏢 חברה: {selected_coupon['company']}\n"
                    f"🏷️ קוד: {decrypted_code}\n"
                    f"הקופון הוסר מהמערכת לצמיתות.",
                    f"🗑️ הקופון נמחק בהצלחה!\n\n"
                    f"🏢 חברה: {selected_coupon['company']}\n"
                    f"🏷️ קוד: {decrypted_code}\n"
                    f"הקופון הוסר מהמערכת לצמיתות."
                )
                
            except Exception as cascade_error:
                logger.error(f"Error in cascade deletion: {cascade_error}")
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        f"❌ שגיאה במחיקת הקופון: הקופון קשור ל-{total_related_records} עסקאות. לא ניתן למחוק אותו.",
                        f"❌ שגיאה במחיקת הקופון: הקופון קשור ל-{total_related_records} עסקאות. לא ניתן למחוק אותו."
                    )
                )
                return
        else:
            # Simple deletion for coupons without related records
            result = await conn.execute(
                "DELETE FROM coupon WHERE id = $1 AND user_id = $2",
                selected_coupon['id'], user_id
            )
            
            if result == "DELETE 1":
                decrypted_code = decrypt_coupon_code(selected_coupon['code'])
                success_msg = get_gender_specific_text(
                    user_gender,
                    f"🗑️ הקופון נמחק בהצלחה!\n\n"
                    f"🏢 חברה: {selected_coupon['company']}\n"
                    f"🏷️ קוד: {decrypted_code}\n"
                    f"הקופון הוסר מהמערכת לצמיתות.",
                    f"🗑️ הקופון נמחק בהצלחה!\n\n"
                    f"🏢 חברה: {selected_coupon['company']}\n"
                    f"🏷️ קוד: {decrypted_code}\n"
                    f"הקופון הוסר מהמערכת לצמיתות."
                )
            else:
                success_msg = get_gender_specific_text(
                    user_gender,
                    "❌ שגיאה במחיקת הקופון. יתכן שהקופון כבר נמחק.",
                    "❌ שגיאה במחיקת הקופון. יתכן שהקופון כבר נמחק."
                )
        
        await update.message.reply_text(success_msg)
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error executing coupon deletion: {e}")
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "😅 אירעה שגיאה במחיקת הקופון. אנא נסה שוב מאוחר יותר.",
                "😅 אירעה שגיאה במחיקת הקופון. אנא נסי שוב מאוחר יותר."
            )
        )

# Handle usage type selection (partial or full)
async def handle_usage_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, text, user_id):
    """Handle usage type selection"""
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    user_gender = await get_user_gender(user_id)
    selected_coupon = state_obj.get('selected_coupon')
    
    if text not in ['1', '2']:
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "אנא בחר 1 או 2 בלבד.",
                "אנא בחרי 1 או 2 בלבד."
            )
        )
        return
    
    if text == '1':
        # Partial usage - ask for amount
        state_obj['usage_type'] = 'partial'
        state_obj['state'] = CouponCreationState.ENTER_USAGE_AMOUNT
        
        remaining_value = selected_coupon['value'] - selected_coupon['used_value']
        
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                f"💰 כמה שקלים השתמשת מהקופון?\n\n"
                f"💡 זכור: נותר לשימוש {remaining_value}₪\n"
                f"אתה יכול להזין סכום בין 1 ל-{remaining_value}₪:",
                f"💰 כמה שקלים השתמשת מהקופון?\n\n"
                f"💡 זכרי: נותר לשימוש {remaining_value}₪\n"
                f"את יכולה להזין סכום בין 1 ל-{remaining_value}₪:"
            )
        )
    else:
        # Full usage - mark as fully used
        state_obj['usage_type'] = 'full'
        remaining_value = selected_coupon['value'] - selected_coupon['used_value']
        state_obj['usage_amount'] = remaining_value
        state_obj['state'] = CouponCreationState.CONFIRM_USAGE_UPDATE
        
        decrypted_code = decrypt_coupon_code(selected_coupon['code'])
        
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                f"✅ **אישור עדכון שימוש:**\n\n"
                f"אני אעדכן שבקופון של {selected_coupon['company']} השתמשת ב-{remaining_value} שקל וניצלת את כל הקופון.\n"
                f"הקופון יירשם כמנוצל לגמרי.\n\n"
                f"האם לאשר? (כן/לא)",
                f"✅ **אישור עדכון שימוש:**\n\n"
                f"אני אעדכן שבקופון של {selected_coupon['company']} השתמשת ב-{remaining_value} שקל וניצלת את כל הקופון.\n"
                f"הקופון יירשם כמנוצל לגמרי.\n\n"
                f"האם לאשר? (כן/לא)"
            )
        )

# Handle usage amount entry
async def handle_usage_amount_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, text, user_id):
    """Handle usage amount entry"""
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    user_gender = await get_user_gender(user_id)
    selected_coupon = state_obj.get('selected_coupon')
    
    # Validate amount
    is_valid, amount, error_msg = validate_monetary_value(text, "הסכום שהשתמשת", allow_zero=False)
    if not is_valid:
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                f"❌ {error_msg}\n\nאנא הזן סכום תקין:",
                f"❌ {error_msg}\n\nאנא הזיני סכום תקין:"
            )
        )
        return
    
    remaining_value = selected_coupon['value'] - selected_coupon['used_value']
    
    # Check if amount is not greater than remaining value
    if amount > remaining_value:
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                f"❌ לא ניתן לסמן שהשתמשת ב-{amount}₪ כי נותר רק {remaining_value}₪ בקופון!\n\n"
                f"אנא הזן סכום עד {remaining_value}₪:",
                f"❌ לא ניתן לסמן שהשתמשת ב-{amount}₪ כי נותר רק {remaining_value}₪ בקופון!\n\n"
                f"אנא הזיני סכום עד {remaining_value}₪:"
            )
        )
        return
    
    # Store usage amount and move to confirmation
    state_obj['usage_amount'] = amount
    state_obj['state'] = CouponCreationState.CONFIRM_USAGE_UPDATE
    
    # Check if this amount will fully use the coupon
    will_be_fully_used = (selected_coupon['used_value'] + amount) >= selected_coupon['value']
    new_remaining = remaining_value - amount
    
    if will_be_fully_used:
        message = get_gender_specific_text(
            user_gender,
            f"✅ **אישור עדכון שימוש:**\n\n"
            f"אני אעדכן שבקופון של {selected_coupon['company']} השתמשת ב-{amount} שקל וניצלת את כל הקופון.\n"
            f"הקופון יירשם כמנוצל לגמרי.\n\n"
            f"האם לאשר? (כן/לא)",
            f"✅ **אישור עדכון שימוש:**\n\n"
            f"אני אעדכן שבקופון של {selected_coupon['company']} השתמשת ב-{amount} שקל וניצלת את כל הקופון.\n"
            f"הקופון יירשם כמנוצל לגמרי.\n\n"
            f"האם לאשר? (כן/לא)"
        )
    else:
        message = get_gender_specific_text(
            user_gender,
            f"✅ **אישור עדכון שימוש:**\n\n"
            f"אני אעדכן שבקופון של {selected_coupon['company']} השתמשת ב-{amount} שקל.\n"
            f"אחרי העדכון יישאר לך להשתמש בעוד {new_remaining} שקל עד ניצול מלא של הקופון.\n\n"
            f"האם לאשר? (כן/לא)",
            f"✅ **אישור עדכון שימוש:**\n\n"
            f"אני אעדכן שבקופון של {selected_coupon['company']} השתמשת ב-{amount} שקל.\n"
            f"אחרי העדכון יישאר לך להשתמש בעוד {new_remaining} שקל עד ניצול מלא של הקופון.\n\n"
            f"האם לאשר? (כן/לא)"
        )
    
    await update.message.reply_text(message)

# Handle usage update confirmation
async def handle_usage_update_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, text, user_id):
    """Handle usage update confirmation"""
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    user_gender = await get_user_gender(user_id)
    
    if text.lower() not in ['כן', 'לא']:
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "אנא ענה רק 'כן' או 'לא'",
                "אנא עני רק 'כן' או 'לא'"
            )
        )
        return
    
    if text.lower() == 'כן':
        # Execute the usage update
        await execute_usage_update(update, context, state_obj, user_id)
        await return_to_main_menu(update, context, chat_id)
    else:
        # Cancel and return to main menu
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "העדכון בוטל. חוזר לתפריט הראשי.",
                "העדכון בוטל. חוזרת לתפריט הראשי."
            )
        )
        await return_to_main_menu(update, context, chat_id)

# Execute usage update in database
async def execute_usage_update(update: Update, context: ContextTypes.DEFAULT_TYPE, state_obj, user_id):
    """Execute the actual usage update in database"""
    chat_id = update.message.chat_id
    user_gender = await get_user_gender(user_id)
    selected_coupon = state_obj.get('selected_coupon')
    usage_amount = state_obj.get('usage_amount')
    usage_type = state_obj.get('usage_type')
    
    try:
        conn = await get_async_db_connection()
        
        # Calculate new used_value
        new_used_value = selected_coupon['used_value'] + usage_amount
        
        # Determine if coupon will be fully used
        will_be_fully_used = new_used_value >= selected_coupon['value']
        new_status = 'נוצל' if will_be_fully_used else 'פעיל'
        
        # Update coupon table
        update_coupon_query = """
            UPDATE coupon 
            SET used_value = $1, status = $2
            WHERE id = $3
        """
        await conn.execute(update_coupon_query, new_used_value, new_status, selected_coupon['id'])
        
        # Add entry to coupon_usage table
        if will_be_fully_used or usage_type == 'full':
            # Full usage
            insert_usage_query = """
                INSERT INTO coupon_usage (coupon_id, used_amount, timestamp, action, details)
                VALUES ($1, $2, NOW(), 'נוצל לגמרי', 'סומן על ידי המשתמש כ"נוצל לגמרי".')
            """
            action_text = "נוצל לגמרי"
        else:
            # Partial usage
            insert_usage_query = """
                INSERT INTO coupon_usage (coupon_id, used_amount, timestamp, action, details)
                VALUES ($1, $2, NOW(), 'שימוש', 'שימוש ידני')
            """
            action_text = "שימוש"
        
        await conn.execute(insert_usage_query, selected_coupon['id'], usage_amount)
        
        # Send success message
        if will_be_fully_used or usage_type == 'full':
            success_msg = get_gender_specific_text(
                user_gender,
                f"🎉 עודכן בהצלחה!\n\n"
                f"הקופון של {selected_coupon['company']} סומן כמנוצל לגמרי.\n"
                f"השתמשת ב-{usage_amount} שקל והקופון הושלם.",
                f"🎉 עודכן בהצלחה!\n\n"
                f"הקופון של {selected_coupon['company']} סומן כמנוצל לגמרי.\n"
                f"השתמשת ב-{usage_amount} שקל והקופון הושלם."
            )
        else:
            remaining = selected_coupon['value'] - new_used_value
            success_msg = get_gender_specific_text(
                user_gender,
                f"🎉 עודכן בהצלחה!\n\n"
                f"בקופון של {selected_coupon['company']} השתמשת ב-{usage_amount} שקל.\n"
                f"נותר לך עוד {remaining} שקל לשימוש.",
                f"🎉 עודכן בהצלחה!\n\n"
                f"בקופון של {selected_coupon['company']} השתמשת ב-{usage_amount} שקל.\n"
                f"נותר לך עוד {remaining} שקל לשימוש."
            )
        
        await update.message.reply_text(success_msg)
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error executing usage update: {e}")
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "😅 אירעה שגיאה בעדכון הקופון. אנא נסה שוב מאוחר יותר.",
                "😅 אירעה שגיאה בעדכון הקופון. אנא נסי שוב מאוחר יותר."
            )
        )

# Helper function to ask for field value based on field type
async def ask_for_field_value(update, field_name, user_gender):
    """Ask user for new value based on field type"""
    if field_name == 'חברה':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה שם החברה החדש?",
                "מה שם החברה החדש?"
            )
        )
    elif field_name == 'קוד קופון':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה הקוד החדש?",
                "מה הקוד החדש?"
            )
        )
    elif field_name == 'מחיר ששולם':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                f"כמה שילמת על הקופון?",
                f"כמה שילמת על הקופון?"
            )
        )
    elif field_name == 'ערך בפועל':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                f"כמה הקופון שווה בפועל?",
                f"כמה הקופון שווה בפועל?"
            )
        )
    elif field_name == 'שימוש חד פעמי':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "האם זה קוד לשימוש חד פעמי? (כן/לא)",
                "האם זה קוד לשימוש חד פעמי? (כן/לא)"
            )
        )
    elif field_name == 'תאריך תפוגה':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה תאריך תפוגה של הקופון? (פורמט: DD/MM/YYYY)\nאם אין תאריך תפוגה, כתוב 'אין'",
                "מה תאריך תפוגה של הקופון? (פורמט: DD/MM/YYYY)\nאם אין תאריך תפוגה, כתובי 'אין'"
            )
        )
    elif field_name == 'תיאור':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה התיאור החדש של הקופון?\nאם אין תיאור, כתוב 'אין'",
                "מה התיאור החדש של הקופון?\nאם אין תיאור, כתובי 'אין'"
            )
        )
    elif field_name == 'מקור':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מאיפה קיבלת את הקופון?\nאם לא רלוונטי, כתוב 'אין'",
                "מאיפה קיבלת את הקופון?\nאם לא רלוונטי, כתובי 'אין'"
            )
        )
    elif field_name == 'CVV':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה ה-CVV החדש? (3 או 4 ספרות)",
                "מה ה-CVV החדש? (3 או 4 ספרות)"
            )
        )
    elif field_name == 'תוקף כרטיס':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה תוקף הכרטיס החדש? (פורמט: MM/YY)",
                "מה תוקף הכרטיס החדש? (פורמט: MM/YY)"
            )
        )
    elif field_name == 'מטרה':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "מה מטרת הקופון החדשה?\nאם אין מטרה, כתוב 'אין'",
                "מה מטרת הקופון החדשה?\nאם אין מטרה, כתובי 'אין'"
            )
        )

# Helper function to handle field editing
async def handle_field_edit(update, context, field_name, new_value, data, user_gender):
    """Handle editing of specific field"""
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    
    try:
        if field_name == 'חברה':
            data['company'] = new_value
        elif field_name == 'קוד קופון':
            data['code'] = new_value
        elif field_name == 'מחיר ששולם':
            is_valid, value, error_msg = validate_monetary_value(new_value, "המחיר ששולם", allow_zero=True)
            if not is_valid:
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        f"❌ {error_msg}\n\nכמה שילמת על הקופון? (0-{MAX_COUPON_VALUE:,} שח)",
                        f"❌ {error_msg}\n\nכמה שילמת על הקופון? (0-{MAX_COUPON_VALUE:,} שח)"
                    )
                )
                return
            
            new_cost = value
            current_value = data.get('value', 0)
            
            # Check if current value is less than or equal to new cost (only if cost > 0)
            if new_cost > 0 and current_value <= new_cost:
                data['cost'] = new_cost
                # Need to update value as well - ask for new value
                state_obj['edit_field'] = 'ערך בפועל'
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        f"😊 רגע, משהו לא מסתדר כאן!\n\n"
                        f"המחיר החדש ששולם הוא {new_cost}₪ אבל הערך בפועל הנוכחי הוא {current_value}₪\n"
                        f"הערך בפועל צריך להיות יותר ממה ששילמת, כדי שתהיה לך הנחה!\n\n"
                        f"כמה הקופון שווה בפועל?",
                        f"😊 רגע, משהו לא מסתדר כאן!\n\n"
                        f"המחיר החדש ששולם הוא {new_cost}₪ אבל הערך בפועל הנוכחי הוא {current_value}₪\n"
                        f"הערך בפועל צריך להיות יותר ממה ששילמת, כדי שתהיה לך הנחה!\n\n"
                        f"כמה הקופון שווה בפועל?"
                    )
                )
                return
            else:
                data['cost'] = new_cost
                # Check if we need to continue to ask for value (when coming from value edit error)
                if state_obj.get('continue_to_value'):
                    state_obj.pop('continue_to_value', None)
                    state_obj['edit_field'] = 'ערך בפועל'
                    await update.message.reply_text(
                        get_gender_specific_text(
                            user_gender,
                            f"כמה הקופון שווה בפועל?",
                            f"כמה הקופון שווה בפועל?"
                        )
                    )
                    return
                
        elif field_name == 'ערך בפועל':
            is_valid, value, error_msg = validate_monetary_value(new_value, "הערך בפועל", allow_zero=False)
            if not is_valid:
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        f"❌ {error_msg}\n\nכמה הקופון שווה בפועל? (1-{MAX_COUPON_VALUE:,} שח)",
                        f"❌ {error_msg}\n\nכמה הקופון שווה בפועל? (1-{MAX_COUPON_VALUE:,} שח)"
                    )
                )
                return
            
            new_value_float = value
            current_cost = data.get('cost', 0)
            
            # Check if new value is less than or equal to current cost (only if cost > 0)
            if current_cost > 0 and new_value_float <= current_cost:
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        f"😊 רגע, משהו לא מסתדר כאן!\n\n"
                        f"שילמת על הקופון {current_cost}₪ אבל הערך שהזנת הוא {new_value_float}₪\n"
                        f"הערך בפועל צריך להיות יותר ממה ששילמת, כדי שתהיה לך הנחה!\n\n"
                        f"בוא נתחיל מחדש:\n"
                        f"כמה שילמת על הקופון?",
                        f"😊 רגע, משהו לא מסתדר כאן!\n\n"
                        f"שילמת על הקופון {current_cost}₪ אבל הערך שהזנת הוא {new_value_float}₪\n"
                        f"הערך בפועל צריך להיות יותר ממה ששילמת, כדי שתהיה לך הנחה!\n\n"
                        f"בואי נתחיל מחדש:\n"
                        f"כמה שילמת על הקופון?"
                    )
                )
                # Switch to editing cost field and flag that we need to continue to value
                state_obj['edit_field'] = 'מחיר ששולם'
                state_obj['continue_to_value'] = True
                return
            else:
                data['value'] = new_value_float
                # Calculate and show discount percentage
                if current_cost > 0:
                    discount_percentage = round(((new_value_float - current_cost) / new_value_float) * 100)
                    celebration_msg = get_gender_specific_text(
                        user_gender,
                        f"🎉 יפה! השגת {discount_percentage}% הנחה! כל הכבוד! 🎉",
                        f"🎉 יפה! השגת {discount_percentage}% הנחה! כל הכבוד! 🎉"
                    )
                else:
                    celebration_msg = get_gender_specific_text(
                        user_gender,
                        f"🎉 יפה! קופון חינמי בשווי {new_value_float}₪! זה 100% הנחה! 🎉",
                        f"🎉 יפה! קופון חינמי בשווי {new_value_float}₪! זה 100% הנחה! 🎉"
                    )
                await update.message.reply_text(celebration_msg)
                
        elif field_name == 'שימוש חד פעמי':
            if new_value.lower() not in ['כן', 'לא']:
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "אנא ענה רק 'כן' או 'לא'",
                        "אנא עני רק 'כן' או 'לא'"
                    )
                )
                return
            data['is_one_time'] = new_value.lower() == 'כן'
        elif field_name == 'תאריך תפוגה':
            if is_empty_field(new_value):
                data['expiration'] = None
            else:
                is_valid, parsed_date, error_msg = validate_date_format(new_value)
                if not is_valid:
                    await update.message.reply_text(
                        get_gender_specific_text(
                            user_gender,
                            f"❌ {error_msg}\n\nנסה שוב (DD/MM/YYYY) או כתוב 'אין' אם אין תאריך תפוגה",
                            f"❌ {error_msg}\n\nנסי שוב (DD/MM/YYYY) או כתבי 'אין' אם אין תאריך תפוגה"
                        )
                    )
                    return
                data['expiration'] = parsed_date
        elif field_name == 'תיאור':
            data['description'] = None if is_empty_field(new_value) else new_value
        elif field_name == 'מקור':
            data['source'] = None if is_empty_field(new_value) else new_value
        elif field_name == 'CVV':
            if not new_value.isdigit() or len(new_value) not in [3, 4]:
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "אנא הזן CVV תקין (3 או 4 ספרות)",
                        "אנא הזיני CVV תקין (3 או 4 ספרות)"
                    )
                )
                return
            data['cvv'] = new_value
        elif field_name == 'תוקף כרטיס':
            if not re.match(r'^\d{2}/\d{2}$', new_value):
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "פורמט לא תקין. אנא הזן תאריך בפורמט MM/YY (למשל: 12/28)",
                        "פורמט לא תקין. אנא הזיני תאריך בפורמט MM/YY (למשל: 12/28)"
                    )
                )
                return
            data['card_exp'] = new_value
        elif field_name == 'מטרה':
            data['purpose'] = None if is_empty_field(new_value) else new_value
        
        # After successful edit, show updated summary
        if state_obj.get('state') == CouponCreationState.EDIT_FIELD_VALUE:
            # Determine if this was from AI or regular flow
            from_ai = any(state in [CouponCreationState.AI_CONFIRM] for state in [state_obj.get('original_state')])
            
            if from_ai:
                state_obj['state'] = CouponCreationState.AI_CONFIRM
                await send_ai_coupon_summary(update, data, user_gender)
            else:
                state_obj['state'] = CouponCreationState.SUMMARY
                await send_coupon_summary(update, data, user_gender)
    
    except Exception as e:
        logger.error(f"Error in handle_field_edit: {e}")
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "אירעה שגיאה בעריכת השדה. נסה שוב.",
                "אירעה שגיאה בעריכת השדה. נסי שוב."
            )
        )

# Send summary for confirmation
async def send_coupon_summary(update, data, user_gender):
    """Send coupon summary for user confirmation"""
    # Create list of fields with values
    fields = []
    empty_fields = []
    
    # Required fields - always displayed
    fields.append(f"🏢 חברה: {data.get('company','לא צוין')}")
    fields.append(f"🎫 קוד קופון: {data.get('code','לא צוין')}")
    fields.append(f"💰 מחיר ששולם: {data.get('cost','לא צוין')}")
    fields.append(f"💎 ערך בפועל: {data.get('value','לא צוין')}")
    fields.append(f"🔒 שימוש חד פעמי: {'כן' if data.get('is_one_time') else 'לא'}")
    
    # Optional fields - displayed only if they have values
    if data.get('expiration'):
        fields.append(f"📅 תאריך תפוגה: {data['expiration']}")
    else:
        empty_fields.append("📅 תאריך תפוגה: לא צוין")
        
    if data.get('description'):
        fields.append(f"📝 תיאור: {data['description']}")
    else:
        empty_fields.append("📝 תיאור: לא צוין")
        
    if data.get('source'):
        fields.append(f"🎯 מקור: {data['source']}")
    else:
        empty_fields.append("🎯 מקור: לא צוין")
        
    if data.get('cvv'):
        fields.append(f"💳 CVV: {data['cvv']}")
    else:
        empty_fields.append("💳 CVV: לא צוין")
        
    if data.get('card_exp'):
        fields.append(f"💳 תוקף כרטיס: {data['card_exp']}")
    else:
        empty_fields.append("💳 תוקף כרטיס: לא צוין")
        
    if data.get('purpose'):
        fields.append(f"🎯 מטרה: {data['purpose']}")
    else:
        empty_fields.append("🎯 מטרה: לא צוין")
    
    # Build message
    summary = "📋 סיכום הקופון החדש:\n\n"
    summary += "\n".join(fields)
    
    # Add empty fields at the end
    if empty_fields:
        summary += "\n\nשדות ריקים:\n"
        summary += "\n".join(empty_fields)
    
    summary += "\n\nהאם הפרטים נכונים? (כן/לא)"
    
    chat_id = update.message.chat_id
    user_coupon_states[chat_id]['state'] = CouponCreationState.CONFIRM_SAVE
    await update.message.reply_text(summary)

# Save coupon to DB
async def save_coupon_to_db(update, data, user_id):
    database_url = os.getenv('DATABASE_URL')
    if database_url.startswith('postgresql+psycopg2://'):
        database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
    import asyncpg
    conn = await asyncpg.connect(database_url, statement_cache_size=0)
    # Check if company exists, if not - add it
    company_name = data.get('company')
    company_row = await conn.fetchrow("SELECT id FROM companies WHERE name = $1", company_name)
    if not company_row:
        await conn.execute("INSERT INTO companies (name, image_path) VALUES ($1, $2)", company_name, 'default_logo.png')
    
    # Convert date to string if exists
    expiration_date = data.get('expiration')
    if expiration_date:
        expiration_date = expiration_date.strftime('%Y-%m-%d')
    
    # Encrypt code and description
    code = data.get('code')
    description = data.get('description')
    if code and not code.startswith('gAAAAA'):
        code = cipher_suite.encrypt(code.encode()).decode()
    if description and not description.startswith('gAAAAA'):
        description = cipher_suite.encrypt(description.encode()).decode()
    
    # Add coupon
    await conn.execute(
        """
        INSERT INTO coupon (code, value, cost, company, expiration, description, source, cvv, card_exp, is_one_time, purpose, user_id, status, used_value, date_added, is_available, is_for_sale)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'פעיל', 0, NOW(), true, false)
        """,
        code, data.get('value'), data.get('cost'), company_name,
        expiration_date, description, data.get('source'),
        data.get('cvv'), data.get('card_exp'), data.get('is_one_time'), data.get('purpose'), user_id
    )
    await conn.close()

# Add general handler to continue coupon addition process
async def handle_coupon_fsm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    if state_obj:
        # Fetch user_id
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        import asyncpg
        conn = await asyncpg.connect(database_url, statement_cache_size=0)
        user = await conn.fetchrow("SELECT user_id FROM telegram_users WHERE telegram_chat_id = $1 AND is_verified = true", chat_id)
        await conn.close()
        if user:
            await handle_coupon_creation(update, context, user['user_id'])
            return
    # If not in coupon process, continue normally
    await handle_code(update, context)

async def handle_number_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle number messages (menu choices)"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    # Check session validity first
    is_valid, user_id, user_gender = await check_session_validity(chat_id)
    if not is_valid:
        await update.message.reply_text(
            "⏰ הפעלה שלך פגה תוקף\n"
            "אנא התחבר שוב עם קוד אימות חדש מהאתר"
        )
        return
    
    # Update session expiry
    await update_session_expiry(chat_id)
    
    try:
        # Check if user is connected
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
        conn = await asyncpg.connect(database_url, statement_cache_size=0)
        
        # Handle menu selection
        if user_message in ['1', '2', '3', '4', '5', '6', '7']:
            await handle_menu_option(update, context)
        else:
            # Send menu again if choice is invalid
            slots = 0
            try:
                slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user_id)
                if slots_row:
                    slots = slots_row['slots_automatic_coupons']
            except Exception as e:
                logger.error(f"Error fetching slots_automatic_coupons: {e}")
            await update.message.reply_text(get_main_menu_text(user_gender, slots))
        
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error in handle_number_message: {e}")
        await update.message.reply_text(
            "❌ אירעה שגיאה בטיפול בבקשה. אנא נסה שוב מאוחר יותר."
        )

# Function to get user gender
async def get_user_gender(user_id):
    """Fetch user gender from database"""
    try:
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
        conn = await asyncpg.connect(database_url, statement_cache_size=0)
        query = "SELECT gender FROM users WHERE id = $1"
        result = await conn.fetchrow(query, user_id)
        await conn.close()
        return result['gender'] if result else None
    except Exception as e:
        logger.error(f"Error getting user gender: {e}")
        return None

async def is_user_verified_for_deletion(user_id):
    """Check if user is verified and has permission to delete coupons"""
    try:
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
        conn = await asyncpg.connect(database_url, statement_cache_size=0)
        query = """
            SELECT is_verified, is_active 
            FROM telegram_users 
            WHERE user_id = $1 AND is_active = true AND is_verified = true
        """
        result = await conn.fetchrow(query, user_id)
        await conn.close()
        
        # User is verified if they have an active and verified telegram connection
        return result is not None
        
    except Exception as e:
        logger.error(f"Error checking user verification for deletion: {e}")
        return False

# Function to get gender-specific text
def get_gender_specific_text(gender, male_text, female_text):
    """Return gender-specific text"""
    if gender == 'female':
        return female_text
    return male_text

# Daily coupon expiration reminder functions
def format_days_remaining(days):
    """Format days remaining in Hebrew"""
    if days == 0:
        return "היום"
    elif days == 1:
        return "מחר"
    elif days == 7:
        return "בעוד שבוע"
    else:
        return f"בעוד {days} ימים"

async def send_expiration_reminder(chat_id, coupons, user_gender):
    """Send expiration reminder message to user"""
    try:
        logger.info(f"Attempting to send reminder to chat_id {chat_id}")
        if context_app is None:
            logger.error("Bot instance not available for sending reminders - context_app is None")
            return
        
        bot = context_app.bot
        if bot is None:
            logger.error("Bot object is None")
            return
        
        logger.info(f"Bot instance available, preparing message for {len(coupons)} coupons")
        
        message = get_gender_specific_text(
            user_gender,
            "🔔 **תזכורת קופונים**\n\n"
            "התוקף של הקופונים הבאים שלך יפוגו בקרוב:\n\n",
            "🔔 **תזכורת קופונים**\n\n"
            "התוקף של הקופונים הבאים שלך יפוגו בקרוב:\n\n"
        )
        
        for coupon in coupons:
            # Calculate days remaining
            expiration_date = coupon['expiration']
            if isinstance(expiration_date, str):
                expiration_date = datetime.strptime(expiration_date, '%Y-%m-%d').date()
            
            today = datetime.now(pytz.timezone('Asia/Jerusalem')).date()
            days_remaining = (expiration_date - today).days
            
            remaining_value = coupon['value'] - coupon['used_value']
            decrypted_code = decrypt_coupon_code(coupon['code'])
            
            time_text = format_days_remaining(days_remaining)
            
            message += (
                f"🏢 **{coupon['company']}**\n"
                f"🏷️ קוד: {decrypted_code}\n"
                f"💰 ערך: {coupon['value']}₪\n"
                f"💵 נותר: {remaining_value}₪\n"
                f"⏰ יפוג תוקף: {time_text}\n\n"
            )
        
        message += get_gender_specific_text(
            user_gender,
            "💡 זכור להשתמש בקופונים לפני שיפוגו!",
            "💡 זכרי להשתמש בקופונים לפני שיפוגו!"
        )
        
        logger.info(f"Sending message to chat_id {chat_id}")
        await bot.send_message(chat_id=chat_id, text=message)
        logger.info(f"Successfully sent expiration reminder to chat_id {chat_id} for {len(coupons)} coupons")
        
    except Exception as e:
        logger.error(f"Error sending expiration reminder to chat_id {chat_id}: {e}")

async def send_monthly_summary(chat_id, user_id, user_gender):
    """Send GPT-powered monthly summary message to user"""
    try:
        logger.info(f"Attempting to send GPT-powered monthly summary to user {user_id}, chat_id {chat_id}")
        if context_app is None:
            logger.error("Bot instance not available for sending monthly summary - context_app is None")
            return
        
        bot = context_app.bot
        if bot is None:
            logger.error("Bot object is None")
            return
        
        # Get current month and year 
        now = datetime.now()
        prev_month = now.month - 1 if now.month > 1 else 12
        prev_year = now.year if now.month > 1 else now.year - 1
        
        # Generate GPT-powered summary text
        try:
            # Import the GPT function from statistics routes
            from app.routes.statistics_routes import get_monthly_summary_text_with_gpt
            from app import create_app
            
            # Create Flask app context
            app = create_app()
            with app.app_context():
                gpt_message = get_monthly_summary_text_with_gpt(
                    user_id=user_id, 
                    month=prev_month, 
                    year=prev_year,
                    user_gender=user_gender or 'male'
                )
            
            logger.info(f"GPT message generated successfully for user {user_id}")
            summary_text = gpt_message
            
        except Exception as gpt_error:
            logger.error(f"Error generating GPT message for user {user_id}: {str(gpt_error)}")
            
            # Fallback to basic message
            month_names = {
                1: 'ינואר', 2: 'פברואר', 3: 'מרץ', 4: 'אפריל',
                5: 'מאי', 6: 'יוני', 7: 'יולי', 8: 'אוגוסט',
                9: 'ספטמבר', 10: 'אוקטובר', 11: 'נובמבר', 12: 'דצמבר'
            }
            
            month_name = month_names.get(prev_month, str(prev_month))
            
            summary_text = f"""📅 הסיכום החודשי שלך - {month_name} {prev_year}

🎯 **נתונים מהחודש שעבר:**
• זה הסיכום החודשי האוטומטי שלך
• כדי לראות סטטיסטיקות מפורטות, כנס לאתר

📊 **הסטטיסטיקות המלאות זמינות באתר:**
• עמוד הסטטיסטיקות מציג את כל הנתונים המפורטים
• תוכל לסנן לפי חודשים שונים
• מידע על חיסכון, שימוש וחברות פופולריות

💬 רוצה לנהל את הקופונים שלך? כתוב לי בכל עת!"""
        
        logger.info(f"Sending monthly summary to chat_id {chat_id}")
        await bot.send_message(chat_id=chat_id, text=summary_text, parse_mode='Markdown')
        logger.info(f"Successfully sent monthly summary to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error sending monthly summary to user {user_id}, chat_id {chat_id}: {e}")

async def send_monthly_summaries_to_all_users():
    """Send monthly summary to all connected users on the first day of the month"""
    try:
        logger.info("Starting monthly summary send to all users")
        conn = await get_async_db_connection()
        
        # Get all connected users
        users_query = """
            SELECT DISTINCT tu.telegram_chat_id, tu.user_id
            FROM telegram_users tu
            WHERE tu.is_verified = true 
            AND tu.telegram_chat_id IS NOT NULL
            AND tu.verification_expires_at > NOW()
        """
        users = await conn.fetch(users_query)
        
        logger.info(f"Sending monthly summaries to {len(users)} connected users")
        
        for user in users:
            user_id = user['user_id']
            chat_id = user['telegram_chat_id']
            
            # Get user gender
            user_gender = await get_user_gender(user_id)
            
            # Send monthly summary
            await send_monthly_summary(chat_id, user_id, user_gender)
            
            # Add a small delay between sends to avoid hitting rate limits
            await asyncio.sleep(0.1)
            
            logger.info(f"Sent monthly summary to user {user_id}")
        
        await conn.close()
        logger.info("Completed sending monthly summaries to all users")
        
    except Exception as e:
        logger.error(f"Error in send_monthly_summaries_to_all_users: {e}", exc_info=True)

async def check_expiring_coupons_for_all_users(source="unknown"):
    """Check all users for expiring coupons and send reminders"""
    try:
        logger.info(f"Starting coupon expiration check from source: {source}")
        conn = await get_async_db_connection()
        
        # Get all connected users
        users_query = """
            SELECT DISTINCT tu.telegram_chat_id, tu.user_id
            FROM telegram_users tu
            WHERE tu.is_verified = true 
            AND tu.telegram_chat_id IS NOT NULL
            AND tu.verification_expires_at > NOW()
        """
        users = await conn.fetch(users_query)
        
        logger.info(f"Checking expiring coupons for {len(users)} connected users")
        
        for user in users:
            user_id = user['user_id']
            chat_id = user['telegram_chat_id']
            
            # Get user's expiring coupons
            coupons_query = """
                SELECT * 
                FROM coupon
                WHERE user_id = $1
                  AND status = 'פעיל'
                  AND expiration IS NOT NULL
                  AND expiration::date >= CURRENT_DATE
                  AND expiration::date < CURRENT_DATE + INTERVAL '7 days'
            """
            coupons = await conn.fetch(coupons_query, user_id)
            
            if coupons:
                # Get user gender
                user_gender = await get_user_gender(user_id)
                
                # Send reminder
                await send_expiration_reminder(chat_id, coupons, user_gender)
                
                logger.info(f"Sent reminder to user {user_id} for {len(coupons)} expiring coupons")
        
        await conn.close()
        logger.info("Completed checking expiring coupons for all users")
        
    except Exception as e:
        logger.error(f"Error in check_expiring_coupons_for_all_users: {e}", exc_info=True)

async def test_check_expiring_coupons(admin_chat_id):
    """Test version - shows what reminders would be sent without actually sending them"""
    try:
        # Get the bot instance
        from telegram.ext import Application
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        bot = app.bot
        logger.info("Starting test coupon expiration check")
        conn = await get_async_db_connection()
        
        # Get all connected users
        users_query = """
            SELECT DISTINCT tu.telegram_chat_id, tu.user_id
            FROM telegram_users tu
            WHERE tu.is_verified = true 
            AND tu.telegram_chat_id IS NOT NULL
            AND tu.verification_expires_at > NOW()
        """
        users = await conn.fetch(users_query)
        
        total_users = len(users)
        users_with_expiring_coupons = 0
        total_expiring_coupons = 0
        
        for user in users:
            user_id = user['user_id']
            chat_id = user['telegram_chat_id']
            
            # Get user's expiring coupons
            coupons_query = """
                SELECT * 
                FROM coupon
                WHERE user_id = $1
                  AND status = 'פעיל'
                  AND expiration IS NOT NULL
                  AND expiration::date >= CURRENT_DATE
                  AND expiration::date < CURRENT_DATE + INTERVAL '7 days'
            """
            coupons = await conn.fetch(coupons_query, user_id)
            
            if coupons:
                users_with_expiring_coupons += 1
                total_expiring_coupons += len(coupons)
                
                # Get user gender
                user_gender = await get_user_gender(user_id)
                
                # Build the message that WOULD be sent (for preview)
                coupons_list = []
                for coupon in coupons:
                    # Handle expiration date - could be string or date object
                    expiration_date = coupon['expiration']
                    if isinstance(expiration_date, str):
                        from datetime import datetime
                        expiration_date = datetime.strptime(expiration_date, '%Y-%m-%d').date()
                    elif hasattr(expiration_date, 'date'):
                        expiration_date = expiration_date.date()
                    
                    days_until_expiry = (expiration_date - datetime.now().date()).days
                    if days_until_expiry == 0:
                        expiry_text = "היום"
                    elif days_until_expiry == 1:
                        expiry_text = "מחר"
                    else:
                        expiry_text = f"בעוד {days_until_expiry} ימים"
                    
                    remaining_value = coupon.get('remaining_value', coupon.get('value', 0))
                    coupon_text = f"🏢 {coupon['company']}\n"
                    coupon_text += f"🏷️ קוד: {coupon['code']}\n"
                    coupon_text += f"💰 ערך: {coupon['value']}₪\n"
                    coupon_text += f"💵 נותר: {remaining_value}₪\n"
                    coupon_text += f"⏰ יפוג תוקף: {expiry_text}"
                    coupons_list.append(coupon_text)
                
                # Just count, don't send preview messages
        
        # Send brief summary only to the admin who requested the test
        if users_with_expiring_coupons > 0:
            summary_message = f"✅ מערכת התזכורות פעילה - {users_with_expiring_coupons} משתמשים יקבלו תזכורות"
        else:
            summary_message = "✅ מערכת התזכורות פעילה - אין קופונים שיפוגו השבוע"
        
        await bot.send_message(chat_id=admin_chat_id, text=summary_message)
        
        await conn.close()
        logger.info("Completed test check for expiring coupons")
        
    except Exception as e:
        logger.error(f"Error in test_check_expiring_coupons: {e}", exc_info=True)
        # Get the bot instance for error message
        from telegram.ext import Application
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        bot = app.bot
        await bot.send_message(chat_id=admin_chat_id, text=f"❌ שגיאה בבדיקת התזכורות: {str(e)}")

async def schedule_daily_reminder():
    """Schedule daily reminder at configured time in Israel timezone"""
    global scheduler_stop_event
    
    logger.info(f"Starting daily reminder scheduler with time {reminder_config['hour']:02d}:{reminder_config['minute']:02d}")
    
    while True:
        try:
            # Get current time in Israel timezone
            israel_tz = pytz.timezone('Asia/Jerusalem')
            now = datetime.now(israel_tz)
            
            logger.info(f"Current Israel time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Reload config from database to get latest settings
            await load_reminder_config()
            
            # Calculate next reminder time using current config
            next_reminder = now.replace(
                hour=reminder_config['hour'], 
                minute=reminder_config['minute'], 
                second=0, 
                microsecond=0
            )
            
            if now >= next_reminder:
                # If it's already past reminder time today, schedule for tomorrow
                next_reminder += timedelta(days=1)
                logger.info(f"Reminder time has passed today, scheduling for tomorrow: {next_reminder.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                logger.info(f"Next reminder scheduled for today: {next_reminder.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Calculate seconds until next reminder
            sleep_seconds = (next_reminder - now).total_seconds()
            
            logger.info(f"Next coupon expiration check scheduled at {next_reminder.strftime('%Y-%m-%d %H:%M:%S')} Israel time (in {sleep_seconds:.0f} seconds)")
            
            # Sleep until reminder time with checks for stop event
            sleep_interval = min(sleep_seconds, 300)  # Check every 5 minutes max
            elapsed = 0
            
            while elapsed < sleep_seconds:
                if scheduler_stop_event and scheduler_stop_event.is_set():
                    logger.info("Scheduler stop event received, restarting with new config")
                    return
                
                wait_time = min(sleep_interval, sleep_seconds - elapsed)
                await asyncio.sleep(wait_time)
                elapsed += wait_time
            
            # Run the check
            logger.info(f"Running scheduled coupon expiration check at {reminder_config['hour']:02d}:{reminder_config['minute']:02d} Israel time...")
            await check_expiring_coupons_for_all_users(source="scheduled_reminder")
            
            # Check if it's time to send monthly summaries based on configuration
            current_time = datetime.now(pytz.timezone('Asia/Jerusalem'))
            monthly_day_setting = reminder_config.get('monthly_summary_day', calculate_first_sunday_of_month())
            reminder_hour = reminder_config.get('hour', 10)
            reminder_minute = reminder_config.get('minute', 0)
            last_sent_date = reminder_config.get('last_monthly_summary_sent')
            
            # Create current date string for comparison
            current_date_str = current_time.strftime('%Y-%m-%d')
            
            # Debug logging for monthly summary checks
            logger.info(f"Monthly summary check - Day: {current_time.day}/{monthly_day_setting}, Hour: {current_time.hour}/{reminder_hour}, Minute: {current_time.minute}/{reminder_minute}, Last sent: {last_sent_date}, Today: {current_date_str}")
            if current_time.day == monthly_day_setting:
                logger.info(f"Monthly summary day check - Day matches! ✓")
                if current_time.hour == reminder_hour:
                    logger.info(f"Monthly summary hour check - Hour matches! ✓")
                    if current_time.minute >= reminder_minute and current_time.minute < reminder_minute + 30:
                        logger.info(f"Monthly summary minute check - Minute in range! ✓")
                        if last_sent_date != current_date_str:
                            logger.info(f"Monthly summary date check - Not sent today! ✓ - Will send now")
                        else:
                            logger.info(f"Monthly summary date check - Already sent today ✗")
                    else:
                        logger.info(f"Monthly summary minute check - Minute not in range ✗")
                else:
                    logger.info(f"Monthly summary hour check - Hour doesn't match ✗")
            else:
                logger.info(f"Monthly summary day check - Day doesn't match ✗")
            
            # Check if today is the configured day and time for monthly summaries
            # AND we haven't sent it yet this month
            if (current_time.day == monthly_day_setting and
                current_time.hour == reminder_hour and
                current_time.minute >= reminder_minute and
                current_time.minute < reminder_minute + 30 and  # Within 30 minutes of configured time
                last_sent_date != current_date_str):  # Haven't sent today
                
                logger.info(f"It's day {monthly_day_setting} of the month at {reminder_hour:02d}:{reminder_minute:02d} - sending monthly summaries...")
                await send_monthly_summaries_to_all_users()
                
                # Update last sent date to prevent duplicate sends
                await save_last_monthly_summary_date(current_date_str)
                
                # Update the setting for next month's first Sunday (only if using automatic calculation)
                if monthly_day_setting == calculate_first_sunday_of_month():
                    await update_monthly_summary_day_for_next_month()
            
        except Exception as e:
            logger.error(f"Error in schedule_daily_reminder: {e}", exc_info=True)
            # Wait 1 hour before retrying
            await asyncio.sleep(3600)

async def restart_scheduler():
    """Restart the scheduler task with new configuration"""
    global scheduler_task, scheduler_stop_event
    
    try:
        # Stop current scheduler if running
        if scheduler_task and not scheduler_task.done():
            if scheduler_stop_event:
                scheduler_stop_event.set()
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        
        # Create new stop event
        scheduler_stop_event = asyncio.Event()
        
        # Start new scheduler task
        scheduler_task = asyncio.create_task(schedule_daily_reminder())
        logger.info("Scheduler restarted with new configuration")
        
    except Exception as e:
        logger.error(f"Error restarting scheduler: {e}", exc_info=True)

def create_bot_application():
    """
    Create and return bot application without running it.
    This allows external modules to control when and how the bot runs.
    """
    import signal
    import time
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Bot application creation timed out")
    
    try:
        logger.info("=== create_bot_application() started ===")
        print("=== create_bot_application() started ===", flush=True)
        
        # Set timeout for the entire function (60 seconds)
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(60)
        
        # Check if bot is enabled
        logger.info(f"Checking ENABLE_BOT: {ENABLE_BOT}")
        print(f"Checking ENABLE_BOT: {ENABLE_BOT}", flush=True)
        if not ENABLE_BOT:
            logger.warning("טלגרם בוט מושבת - מדלג על יצירת האפליקציה")
            print("טלגרם בוט מושבת - מדלג על יצירת האפליקציה", flush=True)
            return None
        
        # Log python-telegram-bot version for debugging
        import telegram
        logger.info(f"יוצר את אפליקציית הבוט... (python-telegram-bot version: {telegram.__version__})")
        print(f"יוצר את אפליקציית הבוט... (python-telegram-bot version: {telegram.__version__})", flush=True)
        
        # Validate token exists
        logger.info(f"Checking TELEGRAM_BOT_TOKEN: {'SET' if TELEGRAM_BOT_TOKEN else 'NOT SET'}")
        print(f"Checking TELEGRAM_BOT_TOKEN: {'SET' if TELEGRAM_BOT_TOKEN else 'NOT SET'}", flush=True)
        if not TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN is not set")
            print("TELEGRAM_BOT_TOKEN is not set", flush=True)
            return None
        
        # Create application with error handling
        logger.info("Creating Application with token...")
        print("Creating Application with token...", flush=True)
        
        # Add timeout and connection settings for better deploy compatibility
        app = (Application.builder()
               .token(TELEGRAM_BOT_TOKEN)
               .connect_timeout(30.0)  # 30 seconds connection timeout
               .read_timeout(30.0)     # 30 seconds read timeout
               .write_timeout(30.0)    # 30 seconds write timeout
               .build())
        
        logger.info("Application created successfully")
        print("Application created successfully", flush=True)
        
        # Add all handlers
        logger.info("Adding command handlers...")
        print("Adding command handlers...", flush=True)
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('help', help_command))
        app.add_handler(CommandHandler('disconnect', disconnect))
        app.add_handler(CommandHandler('test_reminders', test_reminders_command))
        app.add_handler(CommandHandler('test_monthly', test_monthly_summary_command))
        app.add_handler(CommandHandler('change_reminder_time', change_reminder_time_command))
        app.add_handler(CommandHandler('change_monthly_day', change_monthly_day_command))
        
        # First handle regular text messages (verification code)
        logger.info("Adding message handlers...")
        print("Adding message handlers...", flush=True)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coupon_fsm))
        
        # Then handle number messages (menu choices)
        app.add_handler(MessageHandler(filters.Regex(r'^\d+$'), handle_number_message))
        
        # Store app globally for reminder function
        global context_app
        context_app = app
        
        logger.info("אפליקציית הבוט נוצרה בהצלחה")
        print("אפליקציית הבוט נוצרה בהצלחה", flush=True)
        
        # Cancel timeout
        signal.alarm(0)
        return app
        
    except TimeoutError as e:
        logger.error(f"Timeout creating bot application: {e}")
        print(f"Timeout creating bot application: {e}", flush=True)
        signal.alarm(0)
        return None
        
    except Exception as e:
        logger.error(f"שגיאה ביצירת אפליקציית הבוט: {e}", exc_info=True)
        print(f"שגיאה ביצירת אפליקציית הבוט: {e}", flush=True)
        import traceback
        print(f"Full traceback: {traceback.format_exc()}", flush=True)
        signal.alarm(0)  # Make sure to cancel alarm
        return None

def run_bot():
    """
    Create and run the bot application.
    """
    app = create_bot_application()
    if app:
        # Store app globally for reminder function
        global context_app
        context_app = app
        
        # Start daily reminder scheduler in background
        async def start_scheduler(app):
            global scheduler_task, scheduler_stop_event
            # Fix monthly summary day to 20 (one-time fix)
            await update_monthly_summary_day_to_20()
            # Load reminder config from database first
            await load_reminder_config()
            # Wait a bit for bot to be fully initialized
            await asyncio.sleep(2)
            # Create stop event
            scheduler_stop_event = asyncio.Event()
            # Start scheduler task
            scheduler_task = asyncio.create_task(schedule_daily_reminder())
        
        # Add scheduler to bot startup
        app.post_init = start_scheduler
        
        try:
            app.run_polling(
                allowed_updates=['message', 'callback_query'],
                drop_pending_updates=True
            )
        except Exception as polling_error:
            logger.error(f"Error in run_polling: {polling_error}", exc_info=True)
            raise

if __name__ == '__main__':
    try:
        run_bot()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise