import os
import logging
import requests
import asyncio
import psycopg2
import hashlib
import secrets
from datetime import datetime, timezone
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

# Log important settings (without passwords)
logger.info(f"Bot Configuration:")
logger.info(f"API_URL: {API_URL}")
logger.info(f"TELEGRAM_BOT_USERNAME: {TELEGRAM_BOT_USERNAME}")
logger.info(f"ENABLE_BOT: {ENABLE_BOT}")
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

# Global variable to store first message
first_message = None
user_states = {}

def get_main_menu_text(user_gender, slots=0):
    """Return main menu text"""
    return get_gender_specific_text(
        user_gender,
        "🏠 מה תרצה לעשות?\n\n"
        "1️⃣ הקופונים שלי\n"
        "2️⃣ חיפוש לפי חברה\n"
        "3️⃣ הוספת קופון חדש\n"
        "4️⃣ להתנתק\n"
        "-------------------\n"
        "🤖 אפשרויות עם AI\n"
        f"(נותרו לך עוד {slots} סלוטים לשימוש ביכולות AI)\n"
        "5️⃣ ניתוח קופון בטקסט חופשי\n\n"
        "שלח לי מספר מ-1 עד 5",
        "🏠 מה תרצי לעשות?\n\n"
        "1️⃣ הקופונים שלי\n"
        "2️⃣ חיפוש לפי חברה\n"
        "3️⃣ הוספת קופון חדש\n"
        "4️⃣ להתנתק\n"
        "-------------------\n"
        "🤖 אפשרויות עם AI\n"
        f"(נותרו לך עוד {slots} סלוטים לשימוש ביכולות AI)\n"
        "5️⃣ ניתוח קופון בטקסט חופשי\n\n"
        "שלחי לי מספר מ-1 עד 5"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat_id = update.message.chat_id
    
    # Clear any existing session data
    user_coupon_states.pop(chat_id, None)
    user_states.pop(chat_id, None)
    
    try:
        conn = await get_async_db_connection()
        
        # Check if user is already authenticated
        query = """
            SELECT user_id 
            FROM telegram_users 
            WHERE telegram_chat_id = $1 
            AND is_verified = true
        """
        user = await conn.fetchrow(query, chat_id)
        
        if user:
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

async def get_user_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch first three user coupons by chat_id"""
    chat_id = update.message.chat_id
    
    try:
        # Get DATABASE_URL from environment variables
        database_url = os.getenv('DATABASE_URL')
        
        # Connect to Supabase database
        conn = await asyncpg.connect(database_url)
        
        # Fetch user_id by chat_id from telegram_users table
        user_query = "SELECT user_id FROM telegram_users WHERE chat_id = $1"
        user_id = await conn.fetchval(user_query, chat_id)
        
        if user_id:
            # Fetch first three user coupons
            coupons_query = """
                SELECT id, code, value, company, expiration, status
                FROM coupons
                WHERE user_id = $1
                LIMIT 3
            """
            coupons = await conn.fetch(coupons_query, user_id)
            
            if coupons:
                message = "הנה שלושת הקופונים הראשונים שלך:\n\n"
                for coupon in coupons:
                    message += (
                        f"מזהה: {coupon['id']}\n"
                        f"קוד: {coupon['code']}\n"
                        f"ערך: {coupon['value']}\n"
                        f"חברה: {coupon['company']}\n"
                        f"תאריך תפוגה: {coupon['expiration']}\n"
                        f"סטטוס: {coupon['status']}\n\n"
                    )
                await update.message.reply_text(message)
            else:
                await update.message.reply_text("לא נמצאו קופונים עבורך.")
        else:
            await update.message.reply_text("לא נמצא משתמש עם ה-chat_id הזה.")
        
        # Close database connection
        await conn.close()
    
    except Exception as e:
        await update.message.reply_text(f"אירעה שגיאה: {str(e)}")
        
async def get_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch user coupons"""
    chat_id = update.message.chat_id
    
    try:
        response = requests.post(
            f'{API_URL}/api/telegram_coupons',
            json={'chat_id': chat_id},
            headers=HEADERS,
            timeout=10
        )
        
        if response.ok and response.json().get('success'):
            coupons = response.json().get('coupons', [])
            if coupons:
                message = "הנה הקופונים שלך:\n\n"
                for coupon in coupons:
                    message += (
                        f"🏷️ קופון: {coupon['code']}\n"
                        f"💰 ערך: {coupon['value']}₪\n"
                        f"🏢 חברה: {coupon['company']}\n"
                        f"📅 תפוגה: {coupon['expiration'] or 'ללא'}\n"
                        f"📝 סטטוס: {coupon['status']}\n"
                        f"{'✅ זמין' if coupon['is_available'] else '❌ לא זמין'}\n\n"
                    )
                await update.message.reply_text(message)
            else:
                await update.message.reply_text('לא נמצאו קופונים')
        else:
            error_msg = response.json().get('error', 'שגיאה לא ידועה')
            await update.message.reply_text(f'❌ שגיאה: {error_msg}')
    except Exception as e:
        logger.error(f"Error in get_coupons: {e}")
        await update.message.reply_text('❌ אירעה שגיאה בתקשורת עם השרת')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display available commands list"""
    help_text = (
        "📋 רשימת הפקודות הזמינות:\n\n"
        "/start - התחלת שיחה עם הבוט\n"
        "/help - הצגת רשימת הפקודות\n"
        "/coupons - הצגת הקופונים שלך\n\n"
        "כדי להתחבר, שלח את קוד האימות שקיבלת מהאתר."
    )
    await update.message.reply_text(help_text)

async def coupons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display user coupons"""
    await get_coupons(update, context)

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (verification code) and authenticate user"""
    user_message = update.message.text.strip()
    chat_id = update.message.chat_id

    # Print received code to console
    logger.info(f"[CONSOLE] User entered code: {user_message}")

    # Check if user is in company selection mode
    if user_states.get(chat_id) == "choose_company":
        await handle_company_choice(update, context)
        return

    try:
        conn = await get_async_db_connection()

        # Check if user is already connected
        existing_user_query = """
            SELECT user_id, is_verified 
            FROM telegram_users 
            WHERE telegram_chat_id = $1 
            AND is_verified = true
        """
        existing_user = await conn.fetchrow(existing_user_query, chat_id)
        
        if existing_user:
            # If user is connected, check if this is a menu selection
            if user_message in ['1', '2', '3', '4', '5']:
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
                # Send menu
                await update.message.reply_text(get_main_menu_text(user_gender))
                await conn.close()
                return

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
            
            # Update existing record instead of deleting and creating new
            update_query = """
                UPDATE telegram_users 
                SET telegram_chat_id = $1,
                    telegram_username = $2,
                    is_verified = true,
                    last_interaction = NOW(),
                    verification_attempts = 0,
                    last_verification_attempt = NULL,
                    verification_expires_at = NOW() + INTERVAL '5 minutes'
                WHERE user_id = $3
                AND verification_token = $4
                RETURNING user_id
            """
            
            logger.warning(f"[DEBUG] handle_code: Updating user user_id={user['user_id']} chat_id={chat_id}")
            updated_user = await conn.fetchrow(
                update_query, 
                chat_id,
                update.message.from_user.username,
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
                    slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", existing_user['user_id'])
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
    
    try:
        # Check if user is connected
        conn = await get_async_db_connection()
        
        # Check if user is verified
        query = """
            SELECT user_id 
            FROM telegram_users 
            WHERE telegram_chat_id = $1 
            AND is_verified = true
        """
        user = await conn.fetchrow(query, chat_id)
        
        if not user:
            await update.message.reply_text(
                "❌ אתה לא מחובר. אנא התחבר קודם באמצעות קוד האימות."
            )
            await conn.close()
            return
            
        # Get user gender
        user_gender = await get_user_gender(user['user_id'])
            
        # Fetch user companies
        companies_query = """
            SELECT DISTINCT company 
            FROM coupon 
            WHERE user_id = $1 
            AND status = 'פעיל' 
            ORDER BY company ASC
        """
        companies = await conn.fetch(companies_query, user['user_id'])
        
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
        coupons = await conn.fetch(coupons_query, user['user_id'], selected_company)
        
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
            slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user['user_id'])
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

async def handle_menu_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu option selection"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    try:
        # Check if user is connected
        conn = await get_async_db_connection()
        
        # Check if user is verified
        query = """
            SELECT user_id 
            FROM telegram_users 
            WHERE telegram_chat_id = $1 
            AND is_verified = true
        """
        user = await conn.fetchrow(query, chat_id)
        
        if not user:
            await update.message.reply_text(
                "😬 אתה לא מחובר. בוא נתחבר קודם עם קוד האימות"
            )
            await conn.close()
            return
            
        # Get user gender
        user_gender = await get_user_gender(user['user_id'])
        
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
            coupons = await conn.fetch(coupons_query, user['user_id'])
            
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
                slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user['user_id'])
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
            companies = await conn.fetch(companies_query, user['user_id'])
            
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
            await start_coupon_creation(update, context, user['user_id'])
            await conn.close()
            return
            
        elif user_message == "4":
            await disconnect(update, context)
            
        elif user_message == "5":
            # New option - AI free text analysis
            await start_ai_text_analysis(update, context, user['user_id'])
            await conn.close()
            return
            
        else:
            # Send menu again if choice is invalid
            slots = 0
            try:
                slots_row = await conn.fetchrow("SELECT slots_automatic_coupons FROM users WHERE id = $1", user['user_id'])
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
        
        # Gender-specific text
        msg = get_gender_specific_text(
            user_gender,
            "🤖 **ניתוח טקסט חופשי עם AI**\n\n"
            "תכתוב את פרטי הקופון המלאים\n"
            "(שם חברה, כמה שילמת עליו, כמה הוא שווה בפועל, תאריך תפוגה וכו')\n\n"
            "📝 דוגמה:\n"
            "\"קניתי קופון של מקדונלדס ב88 שקל ששווה 100 שקל, תוקף עד 30/06/2025\"\n\n"
            "כתוב את כל הפרטים שיש לך:",
            "🤖 **ניתוח טקסט חופשי עם AI**\n\n"
            "תכתבי את פרטי הקופון המלאים\n"
            "(שם חברה, כמה שילמת עליו, כמה הוא שווה בפועל, תאריך תפוגה וכו')\n\n"
            "📝 דוגמה:\n"
            "\"קניתי קופון של מקדונלדס ב88 שקל ששווה 100 שקל, תוקף עד 30/06/2025\"\n\n"
            "כתבי את כל הפרטים שיש לך:"
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
    
    try:
        # Send loading message
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "🤖 מנתח את הטקסט עם AI...\n⏳ אנא המתן רגע",
                "🤖 מנתחת את הטקסט עם AI...\n⏳ אנא המתיני רגע"
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
            
            # Save data in user state
            data = {
                'company': extracted_data.get('חברה', ''),
                'code': extracted_data.get('קוד קופון', ''),
                'cost': extracted_data.get('עלות', 0) or 0,
                'value': extracted_data.get('ערך מקורי', 0) or 0,
                'description': extracted_data.get('תיאור', '') or None,
                'expiration': None,
                'source': None,
                'cvv': None,
                'card_exp': None,
                'is_one_time': False,
                'purpose': None
            }
            
            # Handle expiration date
            try:
                expiration_str = extracted_data.get('תאריך תפוגה')
                if expiration_str and expiration_str != 'None':
                    data['expiration'] = datetime.strptime(expiration_str, "%Y-%m-%d").date()
            except Exception as e:
                logger.error(f"Error parsing expiration date: {e}")
            
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
    
    # Get user gender
    conn = await get_async_db_connection()
    query = """
        SELECT user_id 
        FROM telegram_users 
        WHERE telegram_chat_id = $1 
        AND is_verified = true
    """
    user = await conn.fetchrow(query, chat_id)
    user_gender = await get_user_gender(user['user_id']) if user else None
    await conn.close()
    
    await update.message.reply_text(get_main_menu_text(user_gender))

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
                    "איזה שדה תרצה לערוך? כתוב את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:",
                    "איזה שדה תרצי לערוך? כתבי את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:"
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
                    "איזה שדה תרצה לערוך? כתוב את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:",
                    "איזה שדה תרצי לערוך? כתבי את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:"
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
        from fuzzywuzzy import fuzz
        
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
                    "לא מצאתי התאמות דומות. האם תוכל לכתוב שוב את שם החברה?",
                    "לא מצאתי התאמות דומות. האם תוכלי לכתוב שוב את שם החברה?"
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
                "כמה שילמת על הקופון?",
                "כמה שילמת על הקופון?"
            )
        )
        return

    # Price stage
    if state == CouponCreationState.ENTER_COST:
        try:
            if not text.isdigit():
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "אנא הזן מספר שלם בלבד. כמה שילמת על הקופון?",
                        "אנא הזיני מספר שלם בלבד. כמה שילמת על הקופון?"
                    )
                )
                return
            data['cost'] = float(text)
            state_obj['state'] = CouponCreationState.ENTER_VALUE
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "כמה הקופון שווה בפועל?",
                    "כמה הקופון שווה בפועל?"
                )
            )
        except ValueError:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אנא הזן מספר שלם בלבד. כמה שילמת על הקופון?",
                    "אנא הזיני מספר שלם בלבד. כמה שילמת על הקופון?"
                )
            )
        return

    # Value stage
    if state == CouponCreationState.ENTER_VALUE:
        try:
            if not text.replace('.','',1).isdigit():
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "אנא הזן מספר בלבד. כמה הקופון שווה בפועל?",
                        "אנא הזיני מספר בלבד. כמה הקופון שווה בפועל?"
                    )
                )
                return
            data['value'] = float(text)
            state_obj['state'] = CouponCreationState.ENTER_EXPIRATION
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "מה תאריך תפוגה של הקופון? (פורמט: DD/MM/YYYY)\n"
                    "אם אין תאריך תפוגה, כתוב 'אין'",
                    "מה תאריך תפוגה של הקופון? (פורמט: DD/MM/YYYY)\n"
                    "אם אין תאריך תפוגה, כתובי 'אין'"
                )
            )
        except ValueError:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "אנא הזן מספר בלבד. כמה הקופון שווה בפועל?",
                    "אנא הזיני מספר בלבד. כמה הקופון שווה בפועל?"
                )
            )
        return

    # Expiration date
    if state == CouponCreationState.ENTER_EXPIRATION:
        try:
            if is_empty_field(text):
                data['expiration'] = None
            else:
                data['expiration'] = datetime.strptime(text, "%d/%m/%Y").date()
        except Exception:
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "פורמט תאריך לא תקין. נסה שוב (DD/MM/YYYY)\n"
                    "אם אין תאריך תפוגה, תכתוב 'אין'",
                    "פורמט תאריך לא תקין. נסי שוב (DD/MM/YYYY)\n"
                    "אם אין תאריך תפוגה, תכתבי 'אין'"
                )
            )
            return
        state_obj['state'] = CouponCreationState.ENTER_DESCRIPTION
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "יש תיאור או הערות על הקופון?\n"
                "אם אין תיאור, תכתוב 'אין'",
                "יש תיאור או הערות על הקופון?\n"
                "אם אין תיאור, תכתבי 'אין'"
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
                "אם לא רלוונטי, תכתוב 'אין'",
                "מאיפה קיבלת את הקופון?\n"
                "אם לא רלוונטי, תכתבי 'אין'"
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
                    "האם זה קוד לשימוש חד פעמי? (כן/לא)",
                    "האם זה קוד לשימוש חד פעמי? (כן/לא)"
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

    # Card expiration
    if state == CouponCreationState.ENTER_CARD_EXP:
        try:
            # Check MM/YY format
            if not '/' in text or len(text) != 5:
                raise ValueError("פורמט לא תקין")
            
            month, year = text.split('/')
            
            # Check month is number between 1-12
            if not month.isdigit() or not (1 <= int(month) <= 12):
                raise ValueError("חודש לא תקין")
            
            # Check year is 2-digit number
            if not year.isdigit() or len(year) != 2:
                raise ValueError("שנה לא תקינה")
            
            data['card_exp'] = text
            state_obj['state'] = CouponCreationState.ASK_ONE_TIME
            await update.message.reply_text(
                get_gender_specific_text(
                    user_gender,
                    "האם זה קוד לשימוש חד פעמי? (כן/לא)",
                    "האם זה קוד לשימוש חד פעמי? (כן/לא)"
                )
            )
        except ValueError as e:
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
                    "אם אין מטרה, כתוב 'אין'",
                    "מה מטרת הקופון?\n"
                    "אם אין מטרה, כתובי 'אין'"
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
                    "איזה שדה תרצה לערוך? כתוב את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:",
                    "איזה שדה תרצי לערוך? כתבי את שם השדה בדיוק כמו שמופיע בהודעה המסכמת:"
                )
            )
        return

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
                "כמה שילמת על הקופון?",
                "כמה שילמת על הקופון?"
            )
        )
    elif field_name == 'ערך בפועל':
        await update.message.reply_text(
            get_gender_specific_text(
                user_gender,
                "כמה הקופון שווה בפועל?",
                "כמה הקופון שווה בפועל?"
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
            if not new_value.isdigit():
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "אנא הזן מספר שלם בלבד. כמה שילמת על הקופון?",
                        "אנא הזיני מספר שלם בלבד. כמה שילמת על הקופון?"
                    )
                )
                return
            data['cost'] = float(new_value)
        elif field_name == 'ערך בפועל':
            if not new_value.replace('.','',1).isdigit():
                await update.message.reply_text(
                    get_gender_specific_text(
                        user_gender,
                        "אנא הזן מספר בלבד. כמה הקופון שווה בפועל?",
                        "אנא הזיני מספר בלבד. כמה הקופון שווה בפועל?"
                    )
                )
                return
            data['value'] = float(new_value)
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
                try:
                    data['expiration'] = datetime.strptime(new_value, "%d/%m/%Y").date()
                except Exception:
                    await update.message.reply_text(
                        get_gender_specific_text(
                            user_gender,
                            "פורמט תאריך לא תקין. נסה שוב (DD/MM/YYYY)\nאם אין תאריך תפוגה, כתוב 'אין'",
                            "פורמט תאריך לא תקין. נסי שוב (DD/MM/YYYY)\nאם אין תאריך תפוגה, כתובי 'אין'"
                        )
                    )
                    return
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
    
    try:
        # Check if user is connected
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
        conn = await asyncpg.connect(database_url, statement_cache_size=0)
        
        # Check if user is verified
        query = """
            SELECT user_id 
            FROM telegram_users 
            WHERE telegram_chat_id = $1 
            AND is_verified = true
        """
        user = await conn.fetchrow(query, chat_id)
        
        if not user:
            await update.message.reply_text(
                "❌ אתה לא מחובר. אנא התחבר קודם באמצעות קוד האימות."
            )
            await conn.close()
            return
        
        # Get user gender
        user_gender = await get_user_gender(user['user_id'])
        
        # Handle menu selection
        if user_message in ['1', '2', '3', '4', '5']:
            await handle_menu_option(update, context)
        else:
            # Send menu again if choice is invalid
            await update.message.reply_text(get_main_menu_text(user_gender))
        
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

# Function to get gender-specific text
def get_gender_specific_text(gender, male_text, female_text):
    """Return gender-specific text"""
    if gender == 'female':
        return female_text
    return male_text

def create_bot_application():
    """
    Create and return bot application without running it.
    This allows external modules to control when and how the bot runs.
    """
    try:
        # Check if bot is enabled
        if not ENABLE_BOT:
            logger.warning("טלגרם בוט מושבת - מדלג על יצירת האפליקציה")
            return None
            
        logger.info("יוצר את אפליקציית הבוט...")
        
        # Create application
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Add all handlers
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('help', help_command))
        app.add_handler(CommandHandler('coupons', coupons_command))
        app.add_handler(CommandHandler('disconnect', disconnect))
        
        # First handle regular text messages (verification code)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coupon_fsm))
        
        # Then handle number messages (menu choices)
        app.add_handler(MessageHandler(filters.Regex(r'^\d+$'), handle_number_message))
        
        logger.info("אפליקציית הבוט נוצרה בהצלחה")
        return app
        
    except Exception as e:
        logger.error(f"שגיאה ביצירת אפליקציית הבוט: {e}")
        return None

def run_bot():
    """
    Create and run the bot application.
    """
    app = create_bot_application()
    if app:
        app.run_polling(allowed_updates=['message', 'callback_query'])

if __name__ == '__main__':
    try:
        run_bot()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise