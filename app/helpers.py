import os
import time
import re
import logging
import traceback
import requests
import pandas as pd
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, date
from dotenv import load_dotenv
from flask import current_app, render_template, url_for, flash
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint
from app.extensions import db
from app.models import (
    Coupon, CouponTransaction, Notification,
    Tag, coupon_tags, Transaction
)

load_dotenv()
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
IMGUR_CLIENT_ID = os.getenv("IMGUR_CLIENT_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_NAME = "MaCoupon"

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
#  פונקציית עזר ליצירת התראה
# ----------------------------------------------------------------
def create_notification(user_id, message, link):
    """
    יוצרת התראה חדשה ומוסיפה אותה ל-DB (לא שוכחת לבצע db.session.commit()
    במקום שקורא לפונקציה זו, או בהמשך הזרימה).
    """
    tz_il = ZoneInfo('Asia/Jerusalem')
    now_il = datetime.now(tz_il)

    notification = Notification(
        user_id=user_id,
        message=message,
        link=link,
        timestamp=datetime.now(tz_il)  # שמור לפי שעון ישראל
    )
    db.session.add(notification)

# ----------------------------------------------------------------
#  פונקציית עזר לעדכון סטטוס קופון
# ----------------------------------------------------------------
def update_coupon_status(coupon):
    """
    מעדכנת את הסטטוס של הקופון (פעיל/נוצל/פג תוקף) לפי used_value ותאריך התפוגה.
    כמו כן, שולחת התראה למשתמש אם זה עתה הפך לנוצל או לפג תוקף.
    """
    try:
        current_date = datetime.now(timezone.utc).date()
        old_status = coupon.status or 'פעיל'  # במקרה שאין עדיין סטטוס, נניח 'פעיל'
        new_status = 'פעיל'

        # בדיקת פג תוקף
        if coupon.expiration:
            if isinstance(coupon.expiration, date):
                expiration_date = coupon.expiration
            else:
                try:
                    expiration_date = datetime.strptime(coupon.expiration, '%Y-%m-%d').date()
                except ValueError:
                    logger.error(f"Invalid date format for coupon {coupon.id}: {coupon.expiration}")
                    expiration_date = None

            if expiration_date and current_date > expiration_date:
                new_status = 'פג תוקף'

        # בדיקת נוצל לגמרי
        if coupon.used_value >= coupon.value:
            new_status = 'נוצל'

        # עדכון בפועל אם אכן יש שינוי
        if old_status != new_status:
            coupon.status = new_status
            logger.info(f"Coupon {coupon.id} status updated from '{old_status}' to '{new_status}'")

            # שליחת התראה רק אם שונה ל'נוצל' או 'פג תוקף'
            if new_status == 'נוצל' and not coupon.notification_sent_nutzel:
                create_notification(
                    user_id=coupon.user_id,
                    message=f"הקופון {coupon.code} נוצל במלואו.",
                    link=url_for('coupons.coupon_detail', id=coupon.id)
                )
                coupon.notification_sent_nutzel = True

            elif new_status == 'פג תוקף' and not coupon.notification_sent_pagh_tokev:
                create_notification(
                    user_id=coupon.user_id,
                    message=f"הקופון {coupon.code} פג תוקף.",
                    link=url_for('coupons.coupon_detail', id=coupon.id)
                )
                coupon.notification_sent_pagh_tokev = True

    except Exception as e:
        logger.error(f"Error in update_coupon_status for coupon {coupon.id}: {e}")

# ----------------------------------------------------------------
#  פונקציית עזר לעדכון כמות שימוש בקופון
# ----------------------------------------------------------------
def update_coupon_usage(coupon, usage_amount, details='עדכון שימוש'):
    """
    מעדכנת שימוש בקופון (מוסיפה ל-used_value), קוראת לעדכון סטטוס,
    יוצרת רשומת שימוש, ושולחת התראה על העדכון.

    :param coupon: אובייקט הקופון לעדכן
    :param usage_amount: כמות השימוש להוסיף ל-used_value
    :param details: תיאור הפעולה לרשומת השימוש
    """
    from app.models import CouponUsage
    try:
        # עדכון הערך שנוצל
        coupon.used_value += usage_amount
        update_coupon_status(coupon)

        # יצירת רשומת שימוש
        usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=usage_amount,
            timestamp=datetime.now(timezone.utc),
            action='שימוש',
            details=details
        )
        db.session.add(usage)

        # שליחת התראה למשתמש על העדכון
        create_notification(
            user_id=coupon.user_id,
            message=f"השימוש בקופון {coupon.code} עודכן (+{usage_amount} ש\"ח).",
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating coupon usage for coupon {coupon.id}: {e}")
        raise

# ----------------------------------------------------------------
#  פונקציית עזר לעדכון מרוכז של כל הקופונים הפעילים של משתמש
# ----------------------------------------------------------------
def update_all_active_coupons(user_id):
    """
    מעדכנת באופן מרוכז את כל הקופונים הפעילים (status='פעיל') של המשתמש user_id,
    על-ידי קריאה ל-get_coupon_data והוספת סכום השימוש (usage_amount) מהטבלה שהתקבלה.

    :param user_id: מזהה המשתמש
    :return: (updated_coupons, failed_coupons) - רשימות של קודים שהצליחו/נכשלו
    """
    active_coupons = Coupon.query.filter_by(user_id=user_id, status='פעיל').all()
    updated_coupons = []
    failed_coupons = []

    for coupon in active_coupons:
        try:
            df = get_coupon_data(coupon.code)
            if df is not None and not df.empty:
                total_usage = df['usage_amount'].sum()
                # ההפרש בין total_usage הנוכחי ל-used_value הקיים
                additional_usage = total_usage - coupon.used_value
                if additional_usage > 0:
                    update_coupon_usage(coupon, additional_usage, details='עדכון מרוכז')
                updated_coupons.append(coupon.code)
            else:
                failed_coupons.append(coupon.code)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating coupon {coupon.code}: {e}")
            failed_coupons.append(coupon.code)

    return updated_coupons, failed_coupons




def get_coupon_data(coupon_number, save_directory="multipass/input_html"):
    """
    Fetches coupon data from the Multipass website using Selenium, parses the HTML,
    saves data to Excel, and updates the database and coupon_transaction table.

    Parameters:
    coupon_number (str): The coupon number to query.
    save_directory (str): Directory where the HTML and Excel files will be saved.

    Returns:
    pd.DataFrame: DataFrame containing the coupon data, or None in case of an error.
    """
    os.makedirs(save_directory, exist_ok=True)

    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get("https://multipass.co.il/%d7%91%d7%a8%d7%95%d7%a8-%d7%99%d7%aa%d7%a8%d7%94/")
        wait = WebDriverWait(driver, 30)

        card_number_field = wait.until(
            EC.visibility_of_element_located((By.ID, "newcardid"))
        )
        card_number_field.clear()
        card_number_field.send_keys(str(coupon_number).split("-")[0])

        print("Coupon number entered.")

        recaptcha_iframe = wait.until(
            EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'recaptcha')]"))
        )
        driver.switch_to.frame(recaptcha_iframe)

        checkbox = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".recaptcha-checkbox-border"))
        )
        checkbox.click()
        print("reCAPTCHA checkbox clicked.")

        driver.switch_to.default_content()

        check_balance_button = wait.until(
            EC.element_to_be_clickable((By.ID, "submit"))
        )

        if check_balance_button.is_enabled():
            print("'Check Balance' button is enabled. Clicking the button...")
            check_balance_button.click()
        else:
            print("Submit button is still disabled. Please ensure the CAPTCHA is solved correctly.")
            return None

        wait.until(
            EC.presence_of_element_located((By.XPATH, "//table"))  # עדכון לפי המבנה הנוכחי
        )

        time.sleep(10)

        page_html = driver.page_source

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"coupon_{coupon_number}_{timestamp}.html"
        file_path = os.path.join(save_directory, filename)

        with open(file_path, "w", encoding="utf-8") as file:
            file.write(page_html)

        print(f"Page HTML saved to {file_path}")

    except Exception as e:
        print(f"An error occurred during Selenium operations: {e}")
        driver.quit()
        return None

    finally:
        driver.quit()

    try:
        # קריאת ה-HTML ל-DataFrame
        import pandas as pd
        dfs = pd.read_html(file_path)
        # Assuming the table we need is the first one
        df = dfs[0]

        # Extract the card number from the HTML
        with open(file_path, 'r', encoding='utf-8') as file:
            html_content = file.read()
        # card_number_pattern = r'כרטיס: </div> <div class="cardnumber">(\d+)</div>'
        # card_number_match = re.search(card_number_pattern, html_content)
        # card_number_extracted = int(card_number_match.group(1)) if card_number_match else coupon_number

        # Add the card number as a column
        df['card_number'] = coupon_number

        # בדיקה אם העמודה 'שימוש' קיימת ואם לא, יוצרים אותה
        if 'שימוש' not in df.columns:
            df['שימוש'] = 0  # או כל ערך התחלתי אחר שתרצה לתת לעמודה

        # Reorder columns if needed
        df = df.rename(columns={
            'שם בית עסק': 'location',
            'סכום טעינת תקציב': 'recharge_amount',
            'סכום מימוש תקציב': 'usage_amount',
            'תאריך': 'transaction_date',
            'מספר אסמכתא': 'reference_number',
        })
        if 'recharge_amount' not in df.columns:
            df['recharge_amount'] = None

        if 'usage_amount' not in df.columns:
            df['usage_amount'] = None
        df = df[['card_number', 'transaction_date', 'location', 'recharge_amount', 'usage_amount', 'reference_number']]

        # הוספת העמודה 'card_number' מתוך קוד הקופון אם לא קיימת
        if 'card_number' not in df.columns:
            # card_number_extracted = str(coupon_number).split("-")[0]
            df['card_number'] = coupon_number

        # בדיקה האם העמודה 'card_number' קיימת
        print("Columns in DataFrame:", df.columns)
        if 'card_number' not in df.columns:
            print("Error: 'card_number' column is missing in the DataFrame.")
            return None

        # המרת תאריך
        df['transaction_date'] = pd.to_datetime(df['transaction_date'], format='%H:%M %d/%m/%Y', errors='coerce')
        df['transaction_date'] = df['transaction_date'].apply(lambda x: x.to_pydatetime() if pd.notnull(x) else None)

        # המרת עמודות מספריות, החלפה של ערכים לא חוקיים ב-0.0
        numeric_columns = ['recharge_amount', 'usage_amount', 'discount_amount', 'benefit_loaded', 'benefit_used']

        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

        # הדפסת עמודות לאחר הניקוי
        print("DataFrame after cleaning:")
        print(df.head())

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        xlsx_filename = f"coupon_{coupon_number}_{timestamp}.xlsx"
        xlsx_path = os.path.join(save_directory, xlsx_filename)
        df.to_excel(xlsx_path, index=False)
        print(f"DataFrame saved to {xlsx_path}")

        # --- עדכון מסד הנתונים ---
        coupon = Coupon.query.filter_by(code=coupon_number).first()
        if not coupon:
            print(f"Coupon with code {coupon_number} not found in database.")
            return df

        import pandas as pd

        # שליפת כל השורות מהדאטהבייס עבור הקופון
        sql_query = """
        SELECT *
        FROM coupon_transaction
        WHERE coupon_id = %(coupon_id)s;
        """

        # משיכת כל הנתונים הקיימים מהדאטהבייס ל-DataFrame
        existing_data = pd.read_sql_query(
            sql_query,
            db.engine,  # שימוש ב-db.engine
            params={'coupon_id': coupon.id}
        )

        existing_data = existing_data.drop(['id'], axis=1)
        existing_data = existing_data.drop(['coupon_id'], axis=1)
        df = pd.concat([df, existing_data])

        # Convert transaction_date to datetime and sort
        df['transaction_date'] = pd.to_datetime(df['transaction_date'])
        df = df.sort_values(by='transaction_date')

        # Drop duplicates
        df = df.drop_duplicates(
            subset=['card_number', 'transaction_date', 'location', 'recharge_amount', 'usage_amount'])

        # Fill NaN values in specific columns with 0
        df[['recharge_amount', 'usage_amount']] = df[['recharge_amount', 'usage_amount']].fillna(0)

        # עיבוד השוואת הנתונים
        for index, row in df.iterrows():
            # יצירת סדרת נתונים לשורה החדשה
            new_row = pd.Series({
                'coupon_id': coupon.id,
                'card_number': row['card_number'],
                'transaction_date': row['transaction_date'],
                'location': row['location'],
                'recharge_amount': row['recharge_amount'],
                'usage_amount': row['usage_amount'],
                'reference_number': row['reference_number']
            })
            existing_row = existing_data[existing_data['card_number'] == row['card_number']]
            existing_row = existing_row[existing_row['transaction_date'] == row['transaction_date']]
            existing_row = existing_row[existing_row['location'] == row['location']]
            existing_row = existing_row[existing_row['recharge_amount'] == row['recharge_amount']]
            existing_row = existing_row[existing_row['usage_amount'] == row['usage_amount']]

            if len(existing_row) == 0:
                transaction = CouponTransaction(
                    coupon_id=coupon.id,
                    card_number=new_row['card_number'],
                    transaction_date=new_row['transaction_date'],
                    location=new_row['location'],
                    recharge_amount=new_row['recharge_amount'],
                    usage_amount=new_row['usage_amount'],
                    reference_number=new_row['reference_number']
                )
                db.session.add(transaction)

        # עדכון הערך הכולל
        total_used = db.session.query(db.func.sum(CouponTransaction.usage_amount)).filter_by(
            coupon_id=coupon.id).scalar() or 0.0
        coupon.used_value = total_used

        # עדכון סטטוס הקופון
        update_coupon_status(coupon)

        # שמירה סופית של כל השינויים
        db.session.commit()

        print(f"Transactions for coupon {coupon.code} have been updated in the database.")

        return df

    except Exception as e:
        print(f"An error occurred during data parsing or database operations: {e}")
        traceback.print_exc()
        db.session.rollback()
        return None


def convert_coupon_data(file_path):
    # קריאת ה-HTML ל-DataFrame
    dfs = pd.read_html(file_path)
    df = dfs[0]
    print("Columns in DataFrame:", df.columns)
    print(df.head())

    # Extract the card number from the HTML
    with open(file_path, 'r', encoding='utf-8') as file:
        html_content = file.read()
    card_number_pattern = r'כרטיס: </div> <div class="cardnumber">(\d+)</div>'
    card_number_match = re.search(card_number_pattern, html_content)
    card_number_extracted = int(card_number_match.group(1)) if card_number_match else coupon_number

    # Add the card number as a column
    df['card_number'] = card_number_extracted

    # עדכון מיפוי העמודות בהתאם לעמודות הנוכחיות
    df = df.rename(columns={
        'שם בית עסק': 'location',
        'סכום מימוש תקציב': 'usage_amount',
        'תאריך': 'transaction_date',
        'הטענה': 'recharge_amount',  # עדכון המיפוי בהתאם
        'מספר אסמכתא': 'reference_number'
    })

    # בדיקה אם העמודות קיימות
    expected_columns = ['card_number', 'transaction_date', 'location', 'usage_amount', 'recharge_amount',
                        'reference_number']
    missing_columns = [col for col in expected_columns if col not in df.columns]
    if missing_columns:
        print(f"Missing columns in DataFrame: {missing_columns}")
        for col in missing_columns:
            if col in ['recharge_amount', 'usage_amount']:
                df[col] = 0.0  # הגדרת ערך ברירת מחדל ל-0.0
            else:
                df[col] = None  # או ערך ברירת מחדל מתאים

    # סידור העמודות
    df = df[['card_number', 'transaction_date', 'location', 'usage_amount', 'recharge_amount', 'reference_number']]

    # המרת תאריך עם פורמט מותאם
    df['transaction_date'] = pd.to_datetime(df['transaction_date'], format='%H:%M %d/%m/%Y', errors='coerce')

    # החלפת NaT ב-None
    print(df['transaction_date'])
    df['transaction_date'] = df['transaction_date'].where(pd.notnull(df['transaction_date']), None)

    # שמירת ה-DataFrame כ-Excel
    save_directory = "/Users/itaykarkason/Desktop/coupon_manager_project/multipass/input_html"
    xlsx_filename = f"coupon_test.xlsx"
    xlsx_path = os.path.join(save_directory, xlsx_filename)
    df.to_excel(xlsx_path, index=False)

    return df


def send_html_email(
        api_key: str,
        sender_email: str,
        sender_name: str,
        recipient_email: str,
        recipient_name: str,
        subject: str,
        html_content: str
):
    """
    Sends an HTML email using the Brevo (SendinBlue) API.

    Parameters:
    - api_key (str): Your Brevo API key.
    - sender_email (str): Sender's email address.
    - sender_name (str): Sender's name.
    - recipient_email (str): Recipient's email address.
    - recipient_name (str): Recipient's name.
    - subject (str): Subject of the email.
    - html_content (str): HTML content of the email.

    Returns:
    - dict: API response if successful.
    - None: If an exception occurs.
    """
    # Configure API key authorization
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = api_key

    # Create an instance of the TransactionalEmailsApi
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

    # Define the email parameters
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient_email, "name": recipient_name}],
        sender={"email": sender_email, "name": sender_name},
        subject=f"{subject} - {datetime.now().strftime('%d%m%Y %H:%M')}",
        html_content=html_content
    )

    try:
        # Send the email
        api_response = api_instance.send_transac_email(send_smtp_email)
        pprint(api_response)
        return api_response
    except ApiException as e:
        print("Exception when calling TransactionalEmailsApi->send_transac_email: %s\n" % e)
        return None


def send_email(sender_email, sender_name, recipient_email, recipient_name, subject, html_content):
    """
    שליחת מייל כללי.

    :param sender_email: כתובת המייל של השולח
    :param sender_name: שם השולח
    :param recipient_email: כתובת המייל של הנמען
    :param recipient_name: שם הנמען
    :param subject: נושא המייל
    :param html_content: תוכן המייל בפורמט HTML
    """
    # הוספת ה-API key ישירות בתוך הפונקציה
    api_key = BREVO_API_KEY

    try:
        send_html_email(
            api_key=api_key,
            sender_email=sender_email,
            sender_name=sender_name,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            subject=f"{subject} - {datetime.now().strftime('%d%m%Y %H:%M')}",
            html_content=html_content
        )
    except Exception as e:
        raise Exception(f"Error sending email: {e}")


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def require_login(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        # רשימת נתיבים ציבוריים
        allowed_routes = ['login', 'register', 'static']

        # אם המשתמש לא מחובר, הפנה אותו לדף התחברות
        if not current_user.is_authenticated:
            return redirect(url_for('login'))

        # בדוק אם request.endpoint קיים לפני גישה ואם הנתיב לא בנתיבים הציבוריים
        if request.endpoint and not request.endpoint.startswith('static.') and request.endpoint not in allowed_routes:
            # אם הנתיב אינו ציבורי והוא לא מחובר, החזר הפנייה ל-login
            return redirect(url_for('login'))

        return func(*args, **kwargs)

    return decorated_view


def generate_confirmation_token(email):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt=current_app.config['SECURITY_PASSWORD_SALT'])


def confirm_token(token, expiration=3600):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    email = serializer.loads(
        token,
        salt=current_app.config['SECURITY_PASSWORD_SALT'],
        max_age=expiration
    )
    return email


def extract_coupon_detail_sms(coupon_text, companies_list):
    import openai
    import os
    from dotenv import load_dotenv
    import json
    import pandas as pd
    import requests
    from datetime import datetime

    """
    פונקציה לקבלת פרטי קופון באמצעות GPT-4o.

    Parameters:
        coupon_text (str): טקסט המכיל את פרטי הקופון.
        companies_list (list): רשימת החברות הקיימות במסד הנתונים.

    Returns:
        tuple: טבלת DataFrame עם פרטי הקופון התואם לסכמת ה-JSON שהוגדרה, ו-DataFrame נוסף עם פרטי העלות והשער.
    """
    # הגדרת מפתח ה-API
    openai.api_key = os.getenv("OPENAI_API_KEY")

    # המרת רשימת החברות למחרוזת
    companies_str = ", ".join(companies_list)

    # הגדרת סכמת JSON
    tools = [
        {
            "type": "function",
            "function": {
                "name": "coupon_details",
                "description": "Extract coupon details from text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "קוד קופון": {"type": "string"},
                        "ערך מקורי": {"type": "number"},
                        "עלות": {"type": "number"},
                        "חברה": {"type": "string"},
                        "תיאור": {"type": "string"},
                        "תאריך תפוגה": {"type": "string", "format": "date"},
                        "תגיות": {"type": "string"},
                        "קוד לשימוש חד פעמי": {"type": "boolean"},
                        "מטרת הקופון": {"type": "string"},
                        "סטטוס": {"type": "string", "enum": ["פעיל", "נוצל"]}
                    },
                    "required": ["קוד קופון", "ערך מקורי", "עלות", "חברה", "תיאור", "תאריך תפוגה", "קוד לשימוש חד פעמי",
                                 "סטטוס"]
                }
            },
            "strict": True
        }
    ]

    # פרומפט למודל
    prompt = f"""
    בהתבסס על המידע הבא:
    {coupon_text}

    אלו הן רשימת החברות הקיימות במאגר שלנו:
    {companies_str}

    אנא זיהה את החברה מהטקסט:
    - אם שם החברה שזיהית דומה מאוד (מעל 90% דמיון) לאחת החברות ברשימה, השתמש בשם החברה כפי שהוא מופיע ברשימה.
    - אם לא קיימת התאמה מספקת, השתמש בשם החברה המקורי שזיהית.

    אנא ספק פלט JSON עם המפתחות הבאים:
    - קוד קופון
    - ערך מקורי
    - עלות
    - חברה
    - תיאור
    - תאריך תפוגה
    - תגיות
    - קוד לשימוש חד פעמי
    - מטרת הקופון
    - סטטוס

    בנוסף, ודא שהמידע נכון ומלא, במיוחד:
    - 'ערך מקורי' חייב להיות בערך המשוער של המוצר או השירות.
    - 'חברה' היא הרשת או הארגון המספק את ההטבה, תוך שימוש בהנחיה שלעיל לגבי רשימת החברות.
    - 'תגיות' כוללות רק מילה אחת רלוונטית, כגון 'מבצע' או 'הנחה'.
    """

    # קריאה ל-API של OpenAI
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "אנא ספק פלט JSON לפי הכלי שסופק."},
            {"role": "user", "content": prompt}
        ],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "coupon_details"}}
    )

    response_data = response['choices'][0]['message']['tool_calls'][0]['function']['arguments']

    # ניסיון לטעון כ-JSON
    try:
        coupon_data = json.loads(response_data)
    except json.JSONDecodeError:
        raise ValueError("השגיאה: הפלט שהתקבל אינו בפורמט JSON תקין.")

    # המרת הפלט ל-DataFrame
    coupon_df = pd.DataFrame([coupon_data])

    # יצירת DataFrame נוסף עם פרטי העלות
    pricing_data = {
        "prompt_tokens": response['usage']['prompt_tokens'],
        "completion_tokens": response['usage']['completion_tokens'],
        "total_tokens": response['usage']['total_tokens'],
        "id": response['id'],
        "object": response['object'],
        "created": datetime.utcfromtimestamp(response['created']).strftime('%Y-%m-%d %H:%M:%S'),
        "model": response['model'],
        # הוספת עמודות עבור הפרומפט והפלט
        "prompt_text": prompt,
        "response_text": json.dumps(coupon_data, ensure_ascii=False)
    }

    # משיכת שער דולר עדכני
    try:
        exchange_rate_response = requests.get("https://api.exchangerate-api.com/v4/latest/USD")
        exchange_rate_data = exchange_rate_response.json()
        usd_to_ils_rate = exchange_rate_data["rates"]["ILS"]
    except Exception as e:
        print(f"Error fetching exchange rate: {e}")
        usd_to_ils_rate = 3.75  # ברירת מחדל

    # חישוב מחירים
    pricing_data["cost_usd"] = pricing_data["total_tokens"] * 0.00004
    pricing_data["cost_ils"] = pricing_data["cost_usd"] * usd_to_ils_rate
    pricing_data["exchange_rate"] = usd_to_ils_rate

    pricing_df = pd.DataFrame([pricing_data])

    return coupon_df, pricing_df

def extract_coupon_detail_image_proccess(client_id, image_path, companies_list):
    import pandas as pd
    from datetime import datetime, timezone

    try:
        def upload_image_to_imgur(client_id, image_path):
            import requests
            try:
                url = "https://api.imgur.com/3/upload"
                headers = {
                    "Authorization": f"Client-ID {client_id}"
                }
                with open(image_path, "rb") as image_file:
                    data = {
                        "image": image_file.read(),
                        "type": "file"
                    }
                    response = requests.post(url, headers=headers, files=data)
                    if response.status_code == 429:
                        print("השתמשת יותר מדי, imgur חוסמים אותך מלהעלות תמונות חדשות")
                        print(response.status_code)
                    if response.status_code == 200:
                        json_data = response.json()
                        return json_data["data"]["link"], json_data["data"]["deletehash"]
                    else:
                        return None, None
            except Exception as e:
                return None, None

        def extract_coupon_detail_image(coupon_image_url, companies_list):
            import openai
            import os
            from dotenv import load_dotenv
            import json
            import pandas as pd
            import requests
            from datetime import datetime, timezone

            try:
                load_dotenv()
                openai.api_key = os.getenv("OPENAI_API_KEY")

                companies_str = ", ".join(companies_list)

                functions = [
                    {
                        "name": "coupon_details",
                        "description": "Extract coupon details from image.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "קוד קופון": {"type": "string"},
                                "ערך מקורי": {"type": "number"},
                                "עלות": {"type": "number"},
                                "חברה": {"type": "string"},
                                "תיאור": {"type": "string"},
                                "תאריך תפוגה": {"type": "string", "format": "date"},
                            },
                            "required": [
                                "קוד קופון",
                                "ערך מקורי",
                                "עלות",
                                "חברה",
                                "תיאור",
                                "תאריך תפוגה",
                            ]
                        }
                    }
                ]

                prompt = f"""
                אנא נתח את התמונה הבאה והפק את פרטי הקופון:

                אלו הן רשימת החברות הקיימות במאגר שלנו:
                {companies_str}

                אנא זיהה את החברה מהתמונה:
                - אם שם החברה שזיהית דומה מאוד (מעל 90% דמיון) לאחת החברות ברשימה, השתמש בשם החברה כפי שהוא מופיע ברשימה.
                - אם לא קיימת התאמה מספקת, השתמש בשם החברה המקורי שזיהית.

                אנא ספק פלט JSON עם המפתחות הבאים:
                - קוד קופון
                - ערך מקורי
                - עלות
                - חברה
                - תיאור
                - תאריך תפוגה

                בנוסף, ודא שהמידע נכון ומלא, במיוחד:
                - 'ערך מקורי' חייב להיות בערך המשוער של המוצר או השירות.
                - 'חברה' היא הרשת או הארגון המספק את ההטבה, תוך שימוש בהנחיה שלעיל לגבי רשימת החברות.
                """

                response = openai.ChatCompletion.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "אנא נתח את התמונה הבאה והפק את פרטי הקופון:"},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": coupon_image_url,
                                        "detail": "high"
                                    },
                                },
                                {"type": "text", "text": prompt}
                            ],
                        }
                    ],
                    functions=functions,
                    function_call={"name": "coupon_details"},
                    max_tokens=1000
                )

                if 'choices' in response and len(response['choices']) > 0:
                    choice = response['choices'][0]
                    if 'message' in choice and 'function_call' in choice['message']:
                        function_call = choice['message']['function_call']
                        if 'arguments' in function_call:
                            response_data = function_call['arguments']
                        else:
                            raise ValueError("השגיאה: הפלט שהתקבל אינו מכיל arguments.")
                    else:
                        raise ValueError("השגיאה: הפלט שהתקבל אינו מכיל function_call.")
                else:
                    raise ValueError("השגיאה: לא התקבלה תגובה תקינה מה-API.")

                try:
                    coupon_data = json.loads(response_data)
                except json.JSONDecodeError:
                    raise ValueError("השגיאה: הפלט שהתקבל אינו בפורמט JSON תקין.")

                coupon_df = pd.DataFrame([coupon_data])

                pricing_data = {
                    "prompt_tokens": response['usage']['prompt_tokens'],
                    "completion_tokens": response['usage']['completion_tokens'],
                    "total_tokens": response['usage']['total_tokens'],
                    "id": response['id'],
                    "object": response['object'],
                    "created": datetime.fromtimestamp(response['created'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    "model": response['model'],
                    "prompt_text": prompt,
                    "response_text": json.dumps(coupon_data, ensure_ascii=False)
                }

                try:
                    exchange_rate_response = requests.get("https://api.exchangerate-api.com/v4/latest/USD")
                    exchange_rate_data = exchange_rate_response.json()
                    usd_to_ils_rate = exchange_rate_data["rates"]["ILS"]
                except Exception:
                    usd_to_ils_rate = 3.75

                pricing_data["cost_usd"] = pricing_data["total_tokens"] * 0.00004
                pricing_data["cost_ils"] = pricing_data["cost_usd"] * usd_to_ils_rate
                pricing_data["exchange_rate"] = usd_to_ils_rate

                pricing_df = pd.DataFrame([pricing_data])

                return coupon_df, pricing_df
            except Exception:
                return pd.DataFrame(), pd.DataFrame()

        def delete_image_from_imgur(client_id, delete_hash):
            import requests
            try:
                url = f"https://api.imgur.com/3/image/{delete_hash}"
                headers = {
                    "Authorization": f"Client-ID {client_id}"
                }
                response = requests.delete(url, headers=headers)
                if response.status_code == 200:
                    return "התמונה נמחקה בהצלחה!"
                else:
                    return None
            except Exception:
                return None

        coupon_image_url, delete_hash = upload_image_to_imgur(client_id, image_path)
        if coupon_image_url is None or delete_hash is None:
            return pd.DataFrame(), pd.DataFrame()
        coupon_df, pricing_df = extract_coupon_detail_image(coupon_image_url, companies_list)
        if coupon_df.empty and pricing_df.empty:
            return pd.DataFrame(), pd.DataFrame()
        delete_image_from_imgur(client_id, delete_hash)
        return coupon_df, pricing_df
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

from flask import render_template  # ייבוא render_template


def send_coupon_purchase_request_email(seller, buyer, coupon):
    """
    שולח מייל למוכר כאשר לקוח מבקש לקנות קופון.

    :param seller: אובייקט ה-User של המוכר
    :param buyer: אובייקט ה-User של הקונה
    :param coupon: אובייקט ה-Coupon שנדרש לקנייה
    """
    sender_email = SENDER_EMAIL
    sender_name = SENDER_NAME
    recipient_email = seller.email
    recipient_name = f"{seller.first_name} {seller.last_name}"
    subject = "בקשה חדשה לקופון שלך"

    # תבנית האימייל אמורה להיות ממוקמת ב-templates/emails/new_coupon_request.html
    html_content = render_template('emails/new_coupon_request.html', seller=seller, buyer=buyer, coupon=coupon)

    send_email(
        sender_email=sender_email,
        sender_name=sender_name,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        subject=f"{subject} - {datetime.now().strftime('%d%m%Y %H:%M')}",
        html_content=html_content
    )



def update_coupon_status(coupon):
    try:
        current_date = datetime.now(timezone.utc).date()
        status = 'פעיל'

        # Ensure coupon.expiration is a date object for comparison
        if coupon.expiration:
            if isinstance(coupon.expiration, date):
                expiration_date = coupon.expiration
            else:
                try:
                    expiration_date = datetime.strptime(coupon.expiration, '%Y-%m-%d').date()
                except ValueError as ve:
                    logger.error(f"Invalid date format for coupon {coupon.id}: {coupon.expiration}")
                    expiration_date = None

            if expiration_date and current_date > expiration_date:
                status = 'פג תוקף'
                # Check if notification was already sent
                if not coupon.notification_sent_pagh_tokev:
                    notification = Notification(
                        user_id=coupon.user_id,
                        message=f"הקופון {coupon.code} פג תוקף.",
                        link=url_for('coupons.coupon_detail', id=coupon.id)
                    )
                    db.session.add(notification)
                    coupon.notification_sent_pagh_tokev = True

        # Check if fully used
        if coupon.used_value >= coupon.value:
            status = 'נוצל'
            # Check if notification was already sent
            if not coupon.notification_sent_nutzel:
                notification = Notification(
                    user_id=coupon.user_id,
                    message=f"הקופון {coupon.code} נוצל במלואו.",
                    link=url_for('coupons.coupon_detail', id=coupon.id)
                )
                db.session.add(notification)
                coupon.notification_sent_nutzel = True

        if coupon.status != status:
            coupon.status = status
            logger.info(f"Coupon {coupon.id} status updated to {status}")

    except Exception as e:
        logger.error(f"Error in update_coupon_status for coupon {coupon.id}: {e}")

def process_coupons_excel(file_path, user):
    """
    Processes an Excel file containing coupon data and adds the coupons to the database.

    :param file_path: The path to the Excel file.
    :param user: The user who is uploading the coupons.
    :return: A tuple containing lists of invalid coupons and messages about missing optional fields.
    """
    try:
        df = pd.read_excel(file_path)
        existing_tags = {tag.name: tag for tag in Tag.query.all()}
        cache_tags = existing_tags.copy()

        invalid_coupons = []
        missing_optional_fields_messages = []

        for index, row in df.iterrows():
            try:
                # Reading fields with default values
                code = str(row.get('קוד קופון', '')).strip()
                value = row.get('ערך מקורי', None)
                cost = row.get('עלות', None)
                company = str(row.get('חברה', '')).strip()
                description = row.get('תיאור', '')
                expiration = row.get('תאריך תפוגה', '')
                tags_input = row.get('תגיות', '')

                # Status of the coupon from the 'סטטוס' column, or default to 'פעיל'
                status = row.get('סטטוס', 'פעיל')
                if isinstance(status, str):
                    status = status.strip()
                else:
                    status = 'פעיל'

                if status not in ['פעיל', 'נוצל']:
                    status = 'פעיל'

                # Convert 'קוד לשימוש חד פעמי' field to boolean
                is_one_time_raw = row.get('קוד לשימוש חד פעמי', False)
                if isinstance(is_one_time_raw, str):
                    is_one_time = is_one_time_raw.strip().lower() in ['true', '1', 'כן', 'yes']
                else:
                    is_one_time = bool(is_one_time_raw)

                # Set 'purpose' field based on 'is_one_time'
                purpose = row.get('מטרת הקופון', '').strip() if is_one_time else None

                # Check required fields
                missing_fields = []
                if not code:
                    missing_fields.append('קוד קופון')
                if value is None or pd.isna(value):
                    missing_fields.append('ערך מקורי')
                if cost is None or pd.isna(cost):
                    missing_fields.append('עלות')
                if not company:
                    missing_fields.append('חברה')
                if missing_fields:
                    invalid_coupons.append(f'בשורה {index + 2} חסרים שדות חובה: {", ".join(missing_fields)}')
                    continue

                # Set 'used_value' based on status
                if status == 'נוצל':
                    used_value = value
                else:
                    used_value = 0.0

                # Process optional fields
                missing_optional_fields = []
                description = '' if pd.isna(description) else description
                if pd.isna(expiration) or not str(expiration).strip():
                    expiration = None
                    missing_optional_fields.append('תאריך תפוגה')
                else:
                    try:
                        if isinstance(expiration, str):
                            expiration_date = datetime.strptime(expiration, '%d/%m/%Y').date()
                        else:
                            expiration_date = expiration.date()
                        expiration = expiration_date
                    except ValueError:
                        missing_optional_fields.append('תאריך תפוגה (פורמט לא תקין)')
                        expiration = None

                tags_input = '' if pd.isna(tags_input) else tags_input

                if missing_optional_fields:
                    missing_fields_str = ', '.join(missing_optional_fields)
                    missing_optional_fields_messages.append(
                        f'בשורה {index + 2} חסרו שדות: {missing_fields_str}. הערכים עלו כריקים.'
                    )

                # Create the coupon
                new_coupon = Coupon(
                    code=code,
                    value=value,
                    cost=cost,
                    company=company,
                    description=description,
                    expiration=expiration,
                    user_id=user.id,
                    is_one_time=is_one_time,
                    purpose=purpose,
                    status=status,
                    used_value=used_value  # Set 'used_value' accordingly
                )

                # Handle tags
                if tags_input:
                    tag_names = [tag.strip() for tag in str(tags_input).split(',')]
                    for name in tag_names:
                        if name:
                            tag = cache_tags.get(name)
                            if not tag:
                                tag = Tag(name=name, count=1)
                                db.session.add(tag)
                                cache_tags[name] = tag
                            else:
                                tag.count += 1
                            new_coupon.tags.append(tag)

                db.session.add(new_coupon)
            except Exception as e:
                traceback.print_exc()
                invalid_coupons.append(f'בשורה {index + 2}: {str(e)}')
                continue

        db.session.commit()

        os.remove(file_path)
        return invalid_coupons, missing_optional_fields_messages

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        raise e  # Re-raise exception to handle it in the calling function

def complete_transaction(transaction):
    try:
        coupon = transaction.coupon
        # העברת הבעלות על הקופון לקונה
        coupon.user_id = transaction.buyer_id
        # הקופון כבר לא למכירה
        coupon.is_for_sale = False
        # הקופון כעת זמין שוב לשימוש
        coupon.is_available = True

        # עדכון סטטוס העסקה
        transaction.status = 'הושלם'

        # אפשר להוסיף התראות לשני הצדדים, רישום לוג, וכדומה
        notification_buyer = Notification(
            user_id=transaction.buyer_id,
            message='הקופון הועבר לחשבונך.',
            link=url_for('transactions.coupon_detail', id=coupon.id)
        )
        notification_seller = Notification(
            user_id=transaction.seller_id,
            message='העסקה הושלמה והקופון הועבר לקונה.',
            link=url_for('transactions.my_transactions')
        )

        db.session.add(notification_buyer)
        db.session.add(notification_seller)

        db.session.commit()
        flash('העסקה הושלמה בהצלחה והקופון הועבר לקונה!', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error completing transaction {transaction.id}: {e}")
        flash('אירעה שגיאה בעת השלמת העסקה. נא לנסות שוב.', 'danger')

from sqlalchemy import func
from app.models import Tag, Coupon, coupon_tags

# -----------------------------------------------------------------------------
# פונקציה לזיהוי התגית הנפוצה ביותר עבור חברה נתונה
# -----------------------------------------------------------------------------
def get_most_common_tag_for_company(company_name):
    """
    מציאת התגית הנפוצה ביותר בקופונים של החברה עם השם company_name
    """
    results = db.session.query(Tag, func.count(Tag.id).label('tag_count')) \
        .join(coupon_tags, Tag.id == coupon_tags.c.tag_id) \
        .join(Coupon, Coupon.id == coupon_tags.c.coupon_id) \
        .filter(func.lower(Coupon.company) == func.lower(company_name)) \
        .group_by(Tag.id) \
        .order_by(func.count(Tag.id).desc(), Tag.id.asc()) \
        .all()

    if results:
        # התגית הראשונה ברשימה היא הנפוצה ביותר
        print("[DEBUG] get_most_common_tag_for_company results =>", results)  # הדפסה לקונסול
        return results[0][0]
    else:
        # אין תגיות משויכות לחברה זו
        return None

