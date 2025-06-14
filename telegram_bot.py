import os
import logging
import requests
import asyncio
import psycopg2
import hashlib
import secrets
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import asyncpg
from enum import Enum

# טעינת משתני סביבה
load_dotenv()

# הגדרת לוגר
logging.basicConfig(
    format=os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO'))
)
logger = logging.getLogger(__name__)

# הגדרות
API_URL = os.getenv('API_URL', 'https://couponmasteril.com')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_BOT_USERNAME = os.getenv('TELEGRAM_BOT_USERNAME')
ENABLE_BOT = os.getenv('ENABLE_BOT', 'True').lower() == 'true'

# הגדרת headers לכל הבקשות
HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}

# הגדרת מפתח ההצפנה
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise ValueError("No ENCRYPTION_KEY set for encryption")
cipher_suite = Fernet(ENCRYPTION_KEY.encode())

def decrypt_coupon_code(encrypted_code):
    """מפענח קוד קופון מוצפן"""
    try:
        if encrypted_code and encrypted_code.startswith('gAAAAA'):
            value = encrypted_code.encode()
            decrypted_value = cipher_suite.decrypt(value)
            return decrypted_value.decode()
        return encrypted_code
    except Exception as e:
        logger.error(f"Error decrypting coupon code: {e}")
        return encrypted_code

# הגדרת חיבור לבסיס הנתונים
def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv('DB_NAME', 'coupon_manager'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgres'),
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432')
    )

# משתנה גלובלי לשמירת ההודעה הראשונה
first_message = None
user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat_id = update.message.chat_id
    
    try:
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
        conn = await asyncpg.connect(database_url, statement_cache_size=0)
        
        # Check if user is already authenticated
        query = """
            SELECT user_id 
            FROM telegram_users 
            WHERE telegram_chat_id = $1 
            AND is_verified = true
        """
        user = await conn.fetchrow(query, chat_id)
        
        if user:
            await update.message.reply_text(
                "🎉 ברוך הבא חזרה! אתה כבר מחובר למערכת.\n"
                "💡 השתמש בפקודה /disconnect אם אתה רוצה להתנתק."
            )
            
            # Send menu
            menu_text = (
                "🏠 **התפריט הראשי שלך**\n\n"
                "בחר מה שאתה רוצה לעשות:\n\n"
                "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
                "2️⃣ **חיפוש לפי חברה** - מצא קופונים של חברה ספציפית\n"
                "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
                "4️⃣ **התנתק** - יאללה ביי!\n\n"
                "📱 פשוט שלח לי את המספר שרלוונטי לך\n"
                "🔄 רוצה לחזור לתפריט? כתוב 'תפריט' בכל זמן"
            )
            await update.message.reply_text(menu_text)
        else:
            await update.message.reply_text(
                "👋 היי שם! ברוך הבא לבוט הקופונים שלך!\n\n"
                "🔐 כדי להתחיל, אני צריך שתשלח לי את קוד האימות שקיבלת מהאתר\n"
                "📩 פשוט העתק אותו והדבק כאן"
            )
        
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text(
            "😅 אופס! משהו השתבש. תנסה שוב בעוד רגע?"
        )

async def get_user_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """שליפת שלושת הקופונים הראשונים של משתמש לפי chat_id"""
    chat_id = update.message.chat_id
    
    try:
        # קבלת ה-DATABASE_URL מהמשתנים הסביבתיים
        database_url = os.getenv('DATABASE_URL')
        
        # חיבור למסד הנתונים ב-Supabase
        conn = await asyncpg.connect(database_url)
        
        # שליפת user_id לפי chat_id מטבלת telegram_users
        user_query = "SELECT user_id FROM telegram_users WHERE chat_id = $1"
        user_id = await conn.fetchval(user_query, chat_id)
        
        if user_id:
            # שליפת שלושת הקופונים הראשונים של המשתמש
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
        
        # סגירת החיבור למסד הנתונים
        await conn.close()
    
    except Exception as e:
        await update.message.reply_text(f"אירעה שגיאה: {str(e)}")
        
async def get_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """שולף את הקופונים של המשתמש"""
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
    """מציג את רשימת הפקודות הזמינות"""
    help_text = (
        "📋 רשימת הפקודות הזמינות:\n\n"
        "/start - התחלת שיחה עם הבוט\n"
        "/help - הצגת רשימת הפקודות\n"
        "/coupons - הצגת הקופונים שלך\n\n"
        "כדי להתחבר, שלח את קוד האימות שקיבלת מהאתר."
    )
    await update.message.reply_text(help_text)

async def coupons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מציג את הקופונים של המשתמש"""
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
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
        conn = await asyncpg.connect(database_url, statement_cache_size=0)

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
            if user_message in ['1', '2', '3', '4']:
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
                menu_text = (
                    "🏠 **התפריט הראשי שלך**\n\n"
                    "בחר מה שאתה רוצה לעשות:\n\n"
                    "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
                    "2️⃣ **חיפוש לפי חברה** - מצא קופונים של חברה ספציפית\n"
                    "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
                    "4️⃣ **התנתק** - יאללה ביי!\n\n"
                    "📱 פשוט שלח לי את המספר שרלוונטי לך"
                )
                await update.message.reply_text(menu_text)
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
                menu_text = (
                    "🏠 **התפריט הראשי שלך**\n\n"
                    "בחר מה שאתה רוצה לעשות:\n\n"
                    "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
                    "2️⃣ **חיפוש לפי חברה** - מצא קופונים של חברה ספציפית\n"
                    "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
                    "4️⃣ **התנתק** - יאללה ביי!\n\n"
                    "📱 פשוט שלח לי את המספר שרלוונטי לך"
                )
                await update.message.reply_text(menu_text)
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
                            "⏰ הקוד פג תוקף. קח קוד חדש מהאתר ותחזור"
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
    """מטפל בפקודת /disconnect"""
    chat_id = update.message.chat_id
    
    try:
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
        conn = await asyncpg.connect(database_url, statement_cache_size=0)
        
        # בדיקה אם המשתמש מחובר
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
        
        # עדכון סטטוס המשתמש ושמירת זמן ההתנתקות
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
                    "✅ התנתקת בהצלחה! כדי להתחבר מחדש, עליך לקבל קוד אימות חדש מהאתר.",
                    "✅ התנתקת בהצלחה! כדי להתחבר מחדש, עלייך לקבל קוד אימות חדש מהאתר."
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
    """מטפל בבחירת חברה מהרשימה"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    try:
        # בדיקה אם המשתמש מחובר
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
        conn = await asyncpg.connect(database_url, statement_cache_size=0)
        
        # בדיקה אם המשתמש מאומת
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
            
        # שליפת החברות של המשתמש
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
            
        # בדיקה אם הבחירה תקינה
        try:
            choice = int(user_message)
            if choice < 1 or choice > len(companies):
                raise ValueError("Invalid choice")
        except ValueError:
            # אם הבחירה לא תקינה, מציג את הרשימה מחדש
            message = "🏢 **בחר חברה מהרשימה:**\n\n"
            for i, company in enumerate(companies, 1):
                message += f"{i}. {company['company']}\n"
            await update.message.reply_text(message)
            await conn.close()
            return
            
        # שליפת הקופונים של החברה שנבחרה
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
            # הפרדת הקופונים לשני סוגים
            regular_coupons = [c for c in coupons if not c['is_one_time']]
            one_time_coupons = [c for c in coupons if c['is_one_time']]
            
            # הצגת קופונים רגילים
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
            
            # הצגת קופונים חד פעמיים
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
            
        # שליחת התפריט מחדש
        menu_text = (
            "🏠 **התפריט הראשי שלך**\n\n"
            "בחר מה שאתה רוצה לעשות:\n\n"
            "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
            "2️⃣ **חיפוש לפי חברה** - מצא קופונים של חברה ספציפית\n"
            "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
            "4️⃣ **התנתק** - יאללה ביי!\n\n"
            "📱 פשוט שלח לי את המספר שרלוונטי לך"
        )
        await update.message.reply_text(menu_text)
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
                        '🤷‍♂️ עדיין אין לך קופונים פעילים. בוא נוסיף כמה!',
                        '🤷‍♀️ עדיין אין לך קופונים פעילים. בואי נוסיף כמה!'
                    )
                )
                
            # Send menu again
            menu_text = get_gender_specific_text(
                user_gender,
                "🏠 **התפריט הראשי שלך**\n\n"
                "בחר מה שאתה רוצה לעשות:\n\n"
                "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
                "2️⃣ **חיפוש לפי חברה** - מצא קופונים של חברה ספציפית\n"
                "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
                "4️⃣ **התנתק** - יאללה ביי!\n\n"
                "📱 פשוט שלח לי את המספר שרלוונטי לך",
                "🏠 **התפריט הראשי שלך**\n\n"
                "בחרי מה את רוצה לעשות:\n\n"
                "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
                "2️⃣ **חיפוש לפי חברה** - מצאי קופונים של חברה ספציפית\n"
                "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
                "4️⃣ **התנתק** - יאללה ביי!\n\n"
                "📱 פשוט שלחי לי את המספר שרלוונטי לך"
            )
            await update.message.reply_text(menu_text)
            
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
        else:
            # Send menu again if choice is invalid
            menu_text = get_gender_specific_text(
                user_gender,
                "🏠 **התפריט הראשי שלך**\n\n"
                "בחר מה שאתה רוצה לעשות:\n\n"
                "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
                "2️⃣ **חיפוש לפי חברה** - מצא קופונים של חברה ספציפית\n"
                "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
                "4️⃣ **התנתק** - יאללה ביי!\n\n"
                "📱 פשוט שלח לי את המספר שרלוונטי לך",
                "🏠 **התפריט הראשי שלך**\n\n"
                "בחרי מה את רוצה לעשות:\n\n"
                "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
                "2️⃣ **חיפוש לפי חברה** - מצאי קופונים של חברה ספציפית\n"
                "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
                "4️⃣ **התנתק** - יאללה ביי!\n\n"
                "📱 פשוט שלחי לי את המספר שרלוונטי לך"
            )
            await update.message.reply_text(menu_text)
        
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

# שמירת מצב ותשובות לכל משתמש
user_coupon_states = {}  # chat_id: {'state': CouponCreationState, 'data': {...}, 'edit_field': None}

# שליפת רשימת חברות מה-DB
async def get_companies_list(user_id):
    database_url = os.getenv('DATABASE_URL')
    if database_url.startswith('postgresql+psycopg2://'):
        database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
    import asyncpg
    conn = await asyncpg.connect(database_url, statement_cache_size=0)
    companies = await conn.fetch("SELECT DISTINCT company FROM coupon WHERE user_id = $1 ORDER BY company ASC", user_id)
    await conn.close()
    return [c['company'] for c in companies]

# התחלת תהליך הוספת קופון
async def start_coupon_creation(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    chat_id = update.message.chat_id
    companies = await get_companies_list(user_id)
    user_coupon_states[chat_id] = {'state': CouponCreationState.CHOOSE_COMPANY, 'data': {}, 'companies': companies}
    msg = "בחר חברה:\n"
    for i, c in enumerate(companies, 1):
        msg += f"{i}. {c}\n"
    msg += f"{len(companies)+1}. אחר"
    await update.message.reply_text(msg)

# פונקציה לחזרה לתפריט הראשי
async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id):
    """מחזיר את המשתמש לתפריט הראשי ומנקה את מצב הקופון"""
    user_coupon_states.pop(chat_id, None)
    menu_text = (
        "🏠 **התפריט הראשי שלך**\n\n"
        "בחר מה שאתה רוצה לעשות:\n\n"
        "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
        "2️⃣ **חיפוש לפי חברה** - מצא קופונים של חברה ספציפית\n"
        "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
        "4️⃣ **התנתק** - יאללה ביי!\n\n"
        "📱 פשוט שלח לי את המספר שרלוונטי לך\n"
        "🔄 רוצה לחזור לתפריט? כתוב 'תפריט' בכל זמן"
    )
    await update.message.reply_text(menu_text)

# פונקציה לבדיקת מילות מפתח לשדה ריק
def is_empty_field(text):
    """בודק אם הטקסט נחשב כשדה ריק"""
    empty_keywords = ['אין', 'לא', 'ריק', 'ללא', 'none', 'no', 'empty', '']
    return text.strip().lower() in empty_keywords

# המשך תהליך הוספת קופון (שלב אחר שלב)
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

    # בדיקה אם המשתמש רוצה לחזור לתפריט הראשי
    if text.lower() in ['תפריט', 'חזור', 'ביטול', 'exit', 'menu', 'cancel']:
        await return_to_main_menu(update, context, chat_id)
        return

    # שלב בחירת חברה
    if state == CouponCreationState.CHOOSE_COMPANY:
        try:
            choice = int(text)
            if 1 <= choice <= len(companies):
                data['company'] = companies[choice-1]
                state_obj['state'] = CouponCreationState.ENTER_CODE
                await update.message.reply_text("מה קוד הקופון/הקוד המזהה?")
            elif choice == len(companies)+1:
                state_obj['state'] = CouponCreationState.ENTER_NEW_COMPANY
                await update.message.reply_text("מה שם החברה החדשה?")
            else:
                raise ValueError
        except Exception:
            await update.message.reply_text("אנא בחר מספר תקין מהרשימה.")
        return

    # שלב הזנת שם חברה חדשה
    if state == CouponCreationState.ENTER_NEW_COMPANY:
        if not text:
            await update.message.reply_text("יש להזין שם חברה חדשה.")
            return
        data['company'] = text
        state_obj['state'] = CouponCreationState.ENTER_CODE
        await update.message.reply_text("מה קוד הקופון/הקוד המזהה?")
        return

    # שלב קוד קופון
    if state == CouponCreationState.ENTER_CODE:
        if not text:
            await update.message.reply_text("יש להזין קוד קופון.")
            return
        data['code'] = text
        state_obj['state'] = CouponCreationState.ENTER_COST
        await update.message.reply_text("כמה שילמת על הקופון?")
        return

    # שלב מחיר
    if state == CouponCreationState.ENTER_COST:
        try:
            if not text.isdigit():
                await update.message.reply_text("אנא הזן מספר שלם בלבד. כמה שילמת על הקופון?")
                return
            data['cost'] = float(text)
            state_obj['state'] = CouponCreationState.ENTER_VALUE
            await update.message.reply_text("כמה הקופון שווה בפועל?")
        except ValueError:
            await update.message.reply_text("אנא הזן מספר שלם בלבד. כמה שילמת על הקופון?")
        return

    # שלב ערך
    if state == CouponCreationState.ENTER_VALUE:
        try:
            if not text.replace('.','',1).isdigit():
                await update.message.reply_text("אנא הזן מספר בלבד. כמה הקופון שווה בפועל?")
                return
            data['value'] = float(text)
            state_obj['state'] = CouponCreationState.ENTER_EXPIRATION
            await update.message.reply_text(
                "מה תאריך תפוגה של הקופון? (פורמט: DD/MM/YYYY)\n"
                "אם אין תאריך תפוגה, כתוב 'אין'"
            )
        except ValueError:
            await update.message.reply_text("אנא הזן מספר בלבד. כמה הקופון שווה בפועל?")
        return

    # תאריך תפוגה
    if state == CouponCreationState.ENTER_EXPIRATION:
        try:
            if is_empty_field(text):
                data['expiration'] = None
            else:
                data['expiration'] = datetime.strptime(text, "%d/%m/%Y").date()
        except Exception:
            await update.message.reply_text(
                "פורמט תאריך לא תקין. נסה שוב (DD/MM/YYYY)\n"
                "אם אין תאריך תפוגה, כתוב 'אין'"
            )
            return
        state_obj['state'] = CouponCreationState.ENTER_DESCRIPTION
        await update.message.reply_text(
            "יש תיאור או הערות על הקופון?\n"
            "אם אין תיאור, כתוב 'אין'"
        )
        return

    # תיאור
    if state == CouponCreationState.ENTER_DESCRIPTION:
        data['description'] = None if is_empty_field(text) else text
        state_obj['state'] = CouponCreationState.ENTER_SOURCE
        await update.message.reply_text(
            "מאיפה קיבלת את הקופון?\n"
            "אם לא רלוונטי, כתוב 'אין'"
        )
        return

    # מקור
    if state == CouponCreationState.ENTER_SOURCE:
        data['source'] = None if is_empty_field(text) else text
        state_obj['state'] = CouponCreationState.ASK_CREDIT_CARD
        await update.message.reply_text("האם להכניס תוקף כרטיס ו-CVV? (כן/לא)")
        return

    # האם להכניס פרטי כרטיס
    if state == CouponCreationState.ASK_CREDIT_CARD:
        if text.lower() == 'כן':
            state_obj['state'] = CouponCreationState.ENTER_CVV
            await update.message.reply_text("מה ה-CVV?")
        else:
            data['cvv'] = None
            data['card_exp'] = None
            state_obj['state'] = CouponCreationState.ASK_ONE_TIME
            await update.message.reply_text("האם זה קוד לשימוש חד פעמי? (כן/לא)")
        return

    # CVV
    if state == CouponCreationState.ENTER_CVV:
        # בדיקה שהקלט הוא מספר בין 3-4 ספרות
        if not text.isdigit() or len(text) not in [3, 4]:
            await update.message.reply_text("אנא הזן CVV תקין (3 או 4 ספרות)")
            return
        data['cvv'] = text
        state_obj['state'] = CouponCreationState.ENTER_CARD_EXP
        await update.message.reply_text("מה תוקף הכרטיס? (פורמט: MM/YY)")
        return

    # תוקף כרטיס
    if state == CouponCreationState.ENTER_CARD_EXP:
        try:
            # בדיקת פורמט MM/YY
            if not '/' in text or len(text) != 5:
                raise ValueError("פורמט לא תקין")
            
            month, year = text.split('/')
            
            # בדיקה שהחודש הוא מספר בין 1-12
            if not month.isdigit() or not (1 <= int(month) <= 12):
                raise ValueError("חודש לא תקין")
            
            # בדיקה שהשנה היא מספר בן 2 ספרות
            if not year.isdigit() or len(year) != 2:
                raise ValueError("שנה לא תקינה")
            
            data['card_exp'] = text
            state_obj['state'] = CouponCreationState.ASK_ONE_TIME
            await update.message.reply_text("האם זה קוד לשימוש חד פעמי? (כן/לא)")
        except ValueError as e:
            await update.message.reply_text(
                "פורמט לא תקין. אנא הזן תאריך בפורמט MM/YY (למשל: 12/28)"
            )
        return

    # שימוש חד פעמי
    if state == CouponCreationState.ASK_ONE_TIME:
        data['is_one_time'] = text.lower() == 'כן'
        if data['is_one_time']:
            state_obj['state'] = CouponCreationState.ENTER_PURPOSE
            await update.message.reply_text(
                "מה מטרת הקופון?\n"
                "אם אין מטרה, כתוב 'אין'"
            )
        else:
            data['purpose'] = None
            state_obj['state'] = CouponCreationState.SUMMARY
            await send_coupon_summary(update, data)
        return

    # מטרה
    if state == CouponCreationState.ENTER_PURPOSE:
        data['purpose'] = None if is_empty_field(text) else text
        state_obj['state'] = CouponCreationState.SUMMARY
        await send_coupon_summary(update, data)
        return

    # עריכה
    if state == CouponCreationState.EDIT_FIELD:
        field = state_obj['edit_field']
        if field == 'ערך בפועל':
            try:
                if not text.isdigit():
                    await update.message.reply_text("אנא הזן מספר שלם בלבד. כמה הקופון שווה בפועל?")
                    return
                data['value'] = float(text)
                state_obj['state'] = CouponCreationState.SUMMARY
                await send_coupon_summary(update, data)
            except ValueError:
                await update.message.reply_text("אנא הזן מספר שלם בלבד. כמה הקופון שווה בפועל?")
        elif field == 'מחיר ששולם':
            try:
                if not text.isdigit():
                    await update.message.reply_text("אנא הזן מספר שלם בלבד. כמה שילמת על הקופון?")
                    return
                data['cost'] = float(text)
                state_obj['state'] = CouponCreationState.SUMMARY
                await send_coupon_summary(update, data)
            except ValueError:
                await update.message.reply_text("אנא הזן מספר שלם בלבד. כמה שילמת על הקופון?")
        else:
            data[field] = text
            state_obj['state'] = CouponCreationState.SUMMARY
            await send_coupon_summary(update, data)
        return

    # אישור סופי
    if state == CouponCreationState.CONFIRM_SAVE:
        if text.lower() == 'כן':
            await save_coupon_to_db(update, data, user_id)
            await update.message.reply_text("✅ הקופון נשמר בהצלחה!")
            user_coupon_states.pop(chat_id, None)
            await return_to_main_menu(update, context, chat_id)
        else:
            await update.message.reply_text("איזה שדה תרצה לערוך? (כתוב את שם השדה)")
            state_obj['state'] = CouponCreationState.EDIT_FIELD
        return

# שליחת סיכום לאישור
async def send_coupon_summary(update, data):
    # יצירת רשימת שדות עם ערכים
    fields = []
    empty_fields = []
    
    # שדות חובה - תמיד יוצגו
    fields.append(f"🏢 חברה: {data.get('company','לא צוין')}")
    fields.append(f"🎫 קוד קופון: {data.get('code','לא צוין')}")
    fields.append(f"💰 מחיר ששולם: {data.get('cost','לא צוין')}")
    fields.append(f"💎 ערך בפועל: {data.get('value','לא צוין')}")
    fields.append(f"🔒 שימוש חד פעמי: {'כן' if data.get('is_one_time') else 'לא'}")
    
    # שדות אופציונליים - יוצגו רק אם יש להם ערך
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
    
    # בניית ההודעה
    summary = "📋 סיכום הקופון החדש:\n\n"
    summary += "\n".join(fields)
    
    # הוספת שדות ריקים בסוף
    if empty_fields:
        summary += "\n\nשדות ריקים:\n"
        summary += "\n".join(empty_fields)
    
    summary += "\n\nהאם הפרטים נכונים? (כן/לא)"
    
    chat_id = update.message.chat_id
    user_coupon_states[chat_id]['state'] = CouponCreationState.CONFIRM_SAVE
    await update.message.reply_text(summary)

# שמירת קופון ל-DB
async def save_coupon_to_db(update, data, user_id):
    database_url = os.getenv('DATABASE_URL')
    if database_url.startswith('postgresql+psycopg2://'):
        database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
    import asyncpg
    conn = await asyncpg.connect(database_url, statement_cache_size=0)
    # בדוק אם החברה קיימת, אם לא - הוסף
    company_name = data.get('company')
    company_row = await conn.fetchrow("SELECT id FROM companies WHERE name = $1", company_name)
    if not company_row:
        await conn.execute("INSERT INTO companies (name, image_path) VALUES ($1, $2)", company_name, 'default_logo.png')
    
    # המרת תאריך למחרוזת אם קיים
    expiration_date = data.get('expiration')
    if expiration_date:
        expiration_date = expiration_date.strftime('%Y-%m-%d')
    
    # הצפנת קוד ותיאור
    code = data.get('code')
    description = data.get('description')
    if code and not code.startswith('gAAAAA'):
        code = cipher_suite.encrypt(code.encode()).decode()
    if description and not description.startswith('gAAAAA'):
        description = cipher_suite.encrypt(description.encode()).decode()
    
    # הוספת קופון
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

# הוספת handler כללי להמשך תהליך הוספת קופון
async def handle_coupon_fsm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    state_obj = user_coupon_states.get(chat_id)
    if state_obj:
        # שליפת user_id
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
    # אם לא בתהליך קופון, המשך רגיל
    await handle_code(update, context)

async def handle_number_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בהודעות מספרים (בחירות תפריט)"""
    chat_id = update.message.chat_id
    user_message = update.message.text.strip()
    
    try:
        # בדיקה אם המשתמש מחובר
        database_url = os.getenv('DATABASE_URL')
        if database_url.startswith('postgresql+psycopg2://'):
            database_url = database_url.replace('postgresql+psycopg2://', 'postgresql://', 1)
        
        conn = await asyncpg.connect(database_url, statement_cache_size=0)
        
        # בדיקה אם המשתמש מאומת
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
        
        # טיפול בבחירת תפריט
        if user_message in ['1', '2', '3', '4']:
            await handle_menu_option(update, context)
        else:
            # שליחת התפריט מחדש אם הבחירה לא תקינה
            menu_text = (
                "🏠 **התפריט הראשי שלך**\n\n"
                "בחר מה שאתה רוצה לעשות:\n\n"
                "1️⃣ **הקופונים שלי** - כל הקופונים הפעילים שלך\n"
                "2️⃣ **חיפוש לפי חברה** - מצא קופונים של חברה ספציפית\n"
                "3️⃣ **הוסף קופון חדש** - רגע אחד ונוסיף לך קופון\n"
                "4️⃣ **התנתק** - יאללה ביי!\n\n"
                "📱 פשוט שלח לי את המספר שרלוונטי לך"
            )
            await update.message.reply_text(menu_text)
        
        await conn.close()
        
    except Exception as e:
        logger.error(f"Error in handle_number_message: {e}")
        await update.message.reply_text(
            "❌ אירעה שגיאה בטיפול בבקשה. אנא נסה שוב מאוחר יותר."
        )

# פונקציה לקבלת מגדר המשתמש
async def get_user_gender(user_id):
    """שולף את מגדר המשתמש מהדאטהבייס"""
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

# פונקציה לקבלת טקסט מותאם למגדר
def get_gender_specific_text(gender, male_text, female_text):
    """מחזיר טקסט מותאם למגדר"""
    if gender == 'female':
        return female_text
    return male_text

def run_bot():
    """הפעלת הבוט"""
    try:
        if not ENABLE_BOT:
            logger.info("Bot is disabled via ENABLE_BOT environment variable")
            return

        if not TELEGRAM_BOT_TOKEN:
            logger.error("No TELEGRAM_BOT_TOKEN provided")
            return

        if not TELEGRAM_BOT_USERNAME:
            logger.error("No TELEGRAM_BOT_USERNAME provided")
            return

        if not os.getenv('DATABASE_URL'):
            logger.error("No DATABASE_URL provided")
            return

        logger.info("הבוט פועל...")
        
        # יצירת אפליקציית הבוט
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        
        # הוספת handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("coupons", coupons_command))
        application.add_handler(CommandHandler("disconnect", disconnect))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_number_message))
        
        # הפעלת הבוט עם טיפול בסיום
        try:
            application.run_polling(allowed_updates=Update.ALL_TYPES)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Error in bot polling: {str(e)}")
            logger.exception("Full traceback:")
        finally:
            logger.info("Bot process ending...")
            application.stop()
            application.shutdown()
        
    except Exception as e:
        logger.error(f"Error in run_bot: {str(e)}")
        logger.exception("Full traceback:")
        raise

if __name__ == '__main__':
    run_bot()
