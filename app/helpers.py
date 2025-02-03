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
from selenium.webdriver.chrome.service import Service
#from webdriver_manager.chrome import ChromeDriverManager
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
from itsdangerous import URLSafeTimedSerializer
from app.models import Company
import numpy as np
from sqlalchemy.sql import text
import pytz
load_dotenv()
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
IMGUR_CLIENT_ID = os.getenv("IMGUR_CLIENT_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
SENDER_NAME = "Coupon Master"
API_KEY = os.getenv("IPINFO_API_KEY")

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

'''''''''''''''
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
'''''''''''''''


def get_coupon_data(coupon, save_directory="automatic_coupon_update/input_html"):
    """
    מפעילה Selenium כדי להיכנס לאתר Multipass או Max (לפי coupon.auto_download_details),
    מורידה את המידע הרלוונטי וממירה אותו ל-DataFrame.
    לאחר מכן, בודקת מה כבר קיים ב-DB בטבלת coupon_transaction ומשווה,
    במטרה להוסיף עסקאות חדשות בלבד ולהתאים את הסטטוס של הקופון בהתאם.

    מחזירה DataFrame עם עסקאות חדשות בלבד, או None אם אין חדשות או אם הייתה שגיאה.
    """
    import os
    import time
    import traceback
    import pandas as pd
    from datetime import datetime
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from sqlalchemy import func, text

    from app.extensions import db
    from app.models import CouponTransaction
    from app.helpers import update_coupon_status

    os.makedirs(save_directory, exist_ok=True)

    coupon_number = coupon.code
    coupon_kind = coupon.auto_download_details  # "Multipass" / "Max" (או אחר)
    card_exp = coupon.card_exp
    cvv = coupon.cvv

    # הגדרת אופציות בסיסיות ל-Selenium
    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-images")  # מניעת טעינת תמונות
    chrome_options.add_argument("--disable-extensions")  # מניעת הרחבות מיותרות
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # אם מדובר ב-Max, נוסיף מצב Headless
    if coupon_kind == "Max":
        chrome_options.add_argument("--headless=new")  # מצב Headless חדש יותר, תומך ביכולות מתקדמות
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")  # חוסם תמונות מהדפדפן

    df = None  # כאן נאחסן את ה-DataFrame המתקבל

    # ----------------------------------------------------------------------
    # טיפול במצב של Multipass
    # ----------------------------------------------------------------------
    if coupon_kind == "Multipass":
        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.get("https://multipass.co.il/%d7%91%d7%a8%d7%95%d7%a8-%d7%99%d7%aa%d7%a8%d7%94/")
            wait = WebDriverWait(driver, 30)
            time.sleep(5)

            card_number_field = driver.find_element(By.XPATH, "//input[@id='newcardid']")
            card_number_field.clear()

            cleaned_coupon_number = str(coupon_number[:-4]).replace("-", "")
            #print(cleaned_coupon_number)
            card_number_field.send_keys(cleaned_coupon_number)

            # טיפול ב-reCAPTCHA
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
                check_balance_button.click()
            else:
                print("Submit button is still disabled. CAPTCHA not solved properly?")
                driver.quit()
                return None

            wait.until(EC.presence_of_element_located((By.XPATH, "//table")))
            time.sleep(10)

            page_html = driver.page_source
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"coupon_{coupon_number}_{timestamp}.html"
            file_path = os.path.join(save_directory, filename)

            with open(file_path, "w", encoding="utf-8") as file:
                file.write(page_html)

        except Exception as e:
            print(f"An error occurred during Selenium operations (Multipass): {e}")
            if driver:
                driver.quit()
            return None
        finally:
            if driver:
                driver.quit()

        # ניסיון לקרוא את הטבלה מתוך ה-HTML שנשמר
        try:
            dfs = pd.read_html(file_path)
            os.remove(file_path)

            if not dfs:
                print("No tables found in HTML (Multipass).")
                return None

            df = dfs[0]

            # שינוי שמות עמודות
            df = df.rename(columns={
                'שם בית עסק': 'location',
                'סכום טעינת תקציב': 'recharge_amount',
                'סכום מימוש תקציב': 'usage_amount',
                'תאריך': 'transaction_date',
                'מספר אסמכתא': 'reference_number',
            })

            # טיפול בעמודות חסרות
            if 'recharge_amount' not in df.columns:
                df['recharge_amount'] = 0.0
            if 'usage_amount' not in df.columns:
                df['usage_amount'] = 0.0

            # המרת תאריך
            df['transaction_date'] = pd.to_datetime(
                df['transaction_date'],
                format='%H:%M %d/%m/%Y',
                errors='coerce'
            )

            # המרת עמודות מספריות
            numeric_columns = ['recharge_amount', 'usage_amount']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

        except Exception as e:
            print(f"An error occurred during data parsing (Multipass): {e}")
            traceback.print_exc()
            return None

    # ----------------------------------------------------------------------
    # טיפול במצב של Max
    # ----------------------------------------------------------------------
    elif coupon_kind == "Max":
        try:
            # משתמשים ב-with כך ש-Selenium יסגר אוטומטית בסיום
            with webdriver.Chrome(options=chrome_options) as driver:
                wait = WebDriverWait(driver, 30)
                driver.get("https://www.max.co.il/gift-card-transactions/main")

                def safe_find(by, value, timeout=10):
                    """ מנסה למצוא אלמנט עם זמן המתנה """
                    return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((by, value)))

                card_number_field = safe_find(By.ID, "giftCardNumber")
                card_number_field.clear()
                card_number_field.send_keys(coupon_number)

                exp_field = safe_find(By.ID, "expDate")
                exp_field.clear()
                exp_field.send_keys(card_exp)

                cvv_field = safe_find(By.ID, "cvv")
                cvv_field.clear()
                cvv_field.send_keys(cvv)

                continue_button = wait.until(EC.element_to_be_clickable((By.ID, "continue")))
                continue_button.click()

                time.sleep(7)

                table = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "mat-table")))

                headers = [header.text.strip() for header in table.find_elements(By.TAG_NAME, "th")]
                rows = []

                # שורות הטבלה
                all_rows = table.find_elements(By.TAG_NAME, "tr")
                # שורת הכותרות היא בדרך-כלל הראשונה, לכן נתחיל מ-1
                for row in all_rows[1:]:
                    cells = [cell.text.strip() for cell in row.find_elements(By.TAG_NAME, "td")]
                    if cells:
                        rows.append(cells)

                df = pd.DataFrame(rows, columns=headers)

                # ניקוי וטיוב נתונים
                if "שולם בתאריך" in df.columns:
                    df["שולם בתאריך"] = pd.to_datetime(df["שולם בתאריך"], format="%d.%m.%Y", errors='coerce')
                else:
                    df["שולם בתאריך"] = None

                if "סכום בשקלים" in df.columns:
                    df["סכום בשקלים"] = (
                        df["סכום בשקלים"]
                        .str.replace("₪", "", regex=False)
                        .str.strip()
                        .replace("", "0")
                        .astype(float)
                    )
                else:
                    df["סכום בשקלים"] = 0.0

                if "יתרה" in df.columns:
                    df["יתרה"] = (
                        df["יתרה"]
                        .str.replace("₪", "", regex=False)
                        .str.strip()
                        .replace("", "0")
                        .astype(float)
                    )
                else:
                    df["יתרה"] = 0.0

                # שינוי שמות העמודות
                col_map = {
                    "שולם בתאריך": "transaction_date",
                    "שם בית העסק": "location",
                    "סכום בשקלים": "amount",
                    "יתרה": "balance",
                    "פעולה": "action",
                    "הערות": "notes"
                }
                for k, v in col_map.items():
                    if k in df.columns:
                        df.rename(columns={k: v}, inplace=True)

                # יצירת עמודות usage_amount ו-recharge_amount על-פי הפעולה
                df["usage_amount"] = df.apply(
                    lambda x: x["amount"] if ("action" in df.columns and x["action"] == "עסקה") else 0.0,
                    axis=1
                )
                df["recharge_amount"] = df.apply(
                    lambda x: -(x["amount"]) if ("action" in df.columns and x["action"] == "טעינה") else 0.0,
                    axis=1
                )

                # הוספת עמודת reference_number
                # *כדי שניתן יהיה לזהות רשומות חדשות מול DB*
                # למשל - ניצור מזהות ייחודית ע"פ אינדקס השורה
                df["reference_number"] = df.index.map(lambda i: f"max_ref_{int(time.time())}_{i}")

                # הסרה של עמודות שלא צריך
                for col_to_drop in ["action", "notes"]:
                    if col_to_drop in df.columns:
                        df.drop(columns=[col_to_drop], inplace=True)

        except Exception as e:
            print(f"An error occurred during Selenium operations (Max): {e}")
            traceback.print_exc()
            return None

    else:
        # אם יש מצב אחר שאיננו Multipass או Max, אפשר להחזיר None או לטפל אחרת
        print(f"Unsupported coupon kind: {coupon_kind}")
        return None

    # בשלב זה, אמור להיות לנו df מוכן
    if df is None or df.empty:
        print("No data frame (df) was created or df is empty.")
        return None

    # ----------------------------------------------------------------------
    # שלב משותף – בדיקת הנתונים מול ה-DB ועדכון
    # ----------------------------------------------------------------------
    try:
        # שליפת הקיימים מה-DB (reference_number בלבד)
        existing_data = pd.read_sql_query(
            """
            SELECT reference_number
            FROM coupon_transaction
            WHERE coupon_id = %(coupon_id)s
            """,
            db.engine,
            params={"coupon_id": coupon.id}
        )

        # נבדוק אם מספר השורות ב-DB שונה ממספר השורות החדשות
        # אם כן (במקרה שיש יותר מ-0 ב-DB) - נמחק את כולן ונכניס מחדש
        if len(existing_data) != len(df):
            if len(existing_data) > 0:
                db.session.execute(
                    text("DELETE FROM coupon_transaction WHERE coupon_id = :coupon_id"),
                    {"coupon_id": coupon.id}
                )
                db.session.commit()

                # עדכון אחרי מחיקה
                existing_data = pd.read_sql_query(
                    """
                    SELECT reference_number
                    FROM coupon_transaction
                    WHERE coupon_id = %(coupon_id)s
                    """,
                    db.engine,
                    params={"coupon_id": coupon.id}
                )

        existing_refs = set(existing_data['reference_number'].astype(str))

        # המרת reference_number ל-string כדי להשוות נכון
        df['reference_number'] = df['reference_number'].astype(str)

        # סינון רשומות שכבר קיימות (אם במקרה נשארו כאלה)
        df_new = df[~df['reference_number'].isin(existing_refs)]

        if df_new.empty:
            print("No new transactions to add (all references already exist in DB).")
            return None

        # הוספת רשומות חדשות
        for idx, row in df_new.iterrows():
            transaction = CouponTransaction(
                coupon_id=coupon.id,
                transaction_date=row.get('transaction_date'),
                location=row.get('location', ''),
                recharge_amount=row.get('recharge_amount', 0.0),
                usage_amount=row.get('usage_amount', 0.0),
                reference_number=row.get('reference_number', '')
            )
            db.session.add(transaction)

        # עדכון סה"כ שימוש בפועל
        total_used = db.session.query(func.sum(CouponTransaction.usage_amount)) \
                         .filter_by(coupon_id=coupon.id).scalar() or 0.0
        coupon.used_value = float(total_used)

        # קריאה לפונקציית עדכון הסטטוס (לדוגמה: האם הקופון אזל, עדיין פעיל וכו')
        update_coupon_status(coupon)

        db.session.commit()

        print(f"Transactions for coupon {coupon.code} have been updated in the database.")
        return df_new  # מחזירים את העסקאות החדשות
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

    # עדכון מיפוי העמודות בהתאם לעמודות הנוכחיות
    df = df.rename(columns={
        'שם בית עסק': 'location',
        'סכום מימוש תקציב': 'usage_amount',
        'תאריך': 'transaction_date',
        'הטענה': 'recharge_amount',  # עדכון המיפוי בהתאם
        'מספר אסמכתא': 'reference_number'
    })

    # בדיקה אם העמודות קיימות
    expected_columns = ['transaction_date', 'location', 'usage_amount', 'recharge_amount',
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
    df = df[['transaction_date', 'location', 'usage_amount', 'recharge_amount', 'reference_number']]

    # המרת תאריך עם פורמט מותאם
    df['transaction_date'] = pd.to_datetime(df['transaction_date'], format='%H:%M %d/%m/%Y', errors='coerce')

    # החלפת NaT ב-None
    print(df['transaction_date'])
    df['transaction_date'] = df['transaction_date'].where(pd.notnull(df['transaction_date']), None)

    # שמירת ה-DataFrame כ-Excel
    #save_directory = "/Users/itaykarkason/Desktop/coupon_manager_project/automatic_coupon_update/input_html"
    #xlsx_filename = f"coupon_test.xlsx"
    #xlsx_path = os.path.join(save_directory, xlsx_filename)
    #df.to_excel(xlsx_path, index=False)

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
                        "סטטוס": {"type": "string", "enum": ["פעיל", "נוצל"]}
                    },
                    "required": ["קוד קופון", "ערך מקורי", "עלות", "חברה", "תיאור", "תאריך תפוגה",
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
    - סטטוס

    בנוסף, ודא שהמידע נכון ומלא, במיוחד:
    - 'ערך מקורי' חייב להיות בערך המשוער של המוצר או השירות. ככה שאם כתוב לדוגמא: ״שובר בסך 100 ש״ח״ אז הערך המקורי יהיה 100.
    - 'חברה' היא הרשת או הארגון המספק את ההטבה, תוך שימוש בהנחיה שלעיל לגבי רשימת החברות.
    - 'תגיות' כוללות רק מילה אחת רלוונטית, כגון 'מבצע' או 'הנחה'.
    - אם לא מצויין בפועל מילים שאומרות בכמה הקופון נקנה. אז הערך של ״עלות״ צריך להיות 0. אם כתוב לדוגמא: ״קניתי ב88 שקל״, אז הערך של עלות יהיה 88.
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
        subject=subject,
        #subject=f"{subject} - {datetime.now().strftime('%d%m%Y %H:%M')}",
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
    :return: A tuple containing:
       1) invalid_coupons: רשימת שגיאות בשורות שנכשלו/לא הוספו,
       2) missing_optional_fields_messages: רשימת התראות על שדות אופציונליים חסרים,
       3) new_coupons: רשימת אובייקטי Coupon שהתווספו בהצלחה לדאטהבייס.
    """
    from app.models import Coupon, Company, Tag, coupon_tags
    from datetime import datetime
    import pandas as pd
    import os
    from sqlalchemy import func
    from app.extensions import db
    from flask import flash
    from sqlalchemy.exc import IntegrityError

    try:
        # במקום להשתמש ב-parse_dates=["תאריך תפוגה"] (שעלול להחזיר NaT),
        # נקרא כטקסט ונמיר ידנית (אם קיים).
        df = pd.read_excel(file_path, dtype=str)  # קורא את כל העמודות כמחרוזות
        # אם בכל זאת אתה רוצה לקרוא את חלק מהשדות כמספרים, אפשר אח"כ להמיר אותם.
        # כאן, לקריאה פשוטה, נשתמש במחרוזות בלבד.

        existing_tags = {tag.name: tag for tag in Tag.query.all()}  # טעינת תגיות קיימות
        cache_tags = existing_tags.copy()

        invalid_coupons = []
        missing_optional_fields_messages = []
        new_coupons = []

        for index, row in df.iterrows():
            try:
                # 1. קריאת הנתונים מהשדות (במחרוזת).
                code = str(row.get('קוד קופון', '')).strip()
                value_str = row.get('ערך מקורי', '')  # מחרוזת
                cost_str = row.get('עלות', '')  # מחרוזת
                company_name = str(row.get('חברה', '')).strip()
                description = row.get('תיאור', '') or ''
                date_str = row.get('תאריך תפוגה', '') or ''

                # 2. קריאה של שדות בוליאניים/טקסט נוספים (אם יש).
                one_time_str = row.get('קוד לשימוש חד פעמי', 'False')  # אם לא קיים, ברירת מחדל False
                purpose = row.get('מטרת הקופון', '') or ''
                tags_field = row.get('תגיות', '') or ''

                # 3. בדיקת ערכים חסרים
                missing_fields = []
                if not code:
                    missing_fields.append('קוד קופון')
                if not value_str:
                    missing_fields.append('ערך מקורי')
                if not cost_str:
                    missing_fields.append('עלות')
                if not company_name:
                    missing_fields.append('חברה')

                if missing_fields:
                    invalid_coupons.append(
                        f'שורה {index + 2}: חסרים שדות חובה: {", ".join(missing_fields)}'
                    )
                    continue

                # 4. המרת value ו-cost למספרים (אם לא ניתנים להמרה, תופס ValueError)
                try:
                    value = float(value_str)
                except ValueError:
                    invalid_coupons.append(
                        f'שורה {index + 2}: ערך מקורי אינו מספר תקין ({value_str}).'
                    )
                    continue

                try:
                    cost = float(cost_str)
                except ValueError:
                    invalid_coupons.append(
                        f'שורה {index + 2}: עלות אינה מספר תקין ({cost_str}).'
                    )
                    continue

                # 5. המרת תאריך תפוגה
                # === זהו החלק הקריטי לתיקון "strptime() argument 1 must be str, not NaTType" ===
                # אם date_str ריק => expiration = None
                # אם לא ריק => ננסה פרסינג בפורמט אחר (כמו %d/%m/%Y או %Y-%m-%d).
                try:
                    if not date_str.strip():
                        # לא הוזן תאריך, פשוט נגדיר None
                        expiration = None
                    else:
                        # כן הוזן ערך => ננסה להמיר
                        # אפשר לנסות קודם %Y-%m-%d, ואם נכשל - %d/%m/%Y, וכו'.
                        expiration = None
                        # ננסה מערך פורמטים רלוונטיים
                        possible_formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
                        for fmt in possible_formats:
                            try:
                                dt = datetime.strptime(date_str, fmt)
                                expiration = dt.date()
                                break
                            except ValueError:
                                pass
                        if expiration is None:
                            # לא הצלחנו להמיר => נתייחס כאל אין תאריך
                            # או אם אתה רוצה לציין בשגיאה => תלוי בך.
                            missing_optional_fields_messages.append(
                                f'שורה {index + 2}: תאריך תפוגה בפורמט לא תקין (הוזן "{date_str}"). הוגדר כ-None.'
                            )
                            expiration = None
                except Exception as e:
                    expiration = None

                # 🟡 אם תאריך התפוגה הוא היום או תאריך שחלף - נוסיף אזהרה, אך עדיין נוסיף את הקופון למערכת 🟡
                if expiration and expiration <= datetime.today().date():
                    missing_optional_fields_messages.append(
                        f'שורה {index + 2}: תאריך התפוגה של הקופון הוא היום או תאריך שחלף ({expiration}). '
                        f'הקופון נכנס למערכת אך מוגדר כ"פג תוקף". '
                        f'אם ברצונך לשנות את הסטטוס שלו, ניתן לערוך אותו ממסך "קופונים שנוצלו והלא פעילים".'
                    )

                # 6. המרת one_time_str לבוליאני
                is_one_time = False
                if isinstance(one_time_str, bool):
                    is_one_time = one_time_str
                else:
                    # ננסה לראות אם זה "True"/"False" או "1"/"0"
                    lower_str = one_time_str.lower().strip()
                    if lower_str in ['true', '1', 'כן']:
                        is_one_time = True
                    else:
                        is_one_time = False

                # 7. טיפול בחברה: אם לא קיימת, ניצור
                from app.models import Company
                company = Company.query.filter_by(name=company_name).first()
                if not company:
                    company = Company(name=company_name, image_path="default_logo.png")
                    db.session.add(company)

                # 8. מציאת / יצירת תגית אוטומטית (כמו שעשינו בעבר)
                from app.models import Tag, coupon_tags, Coupon
                most_common_tag = db.session.query(Tag) \
                    .join(coupon_tags, Tag.id == coupon_tags.c.tag_id) \
                    .join(Coupon, Coupon.id == coupon_tags.c.coupon_id) \
                    .filter(func.lower(Coupon.company) == func.lower(company_name)) \
                    .group_by(Tag.id) \
                    .order_by(func.count(Tag.id).desc()) \
                    .first()
                if not most_common_tag:
                    # אם לא נמצאה תגית, ניצור אחת עם שם גנרי
                    tag_name_for_company = f"Tag for {company_name}"
                    most_common_tag = Tag(name=tag_name_for_company, count=1)
                    db.session.add(most_common_tag)
                else:
                    most_common_tag.count += 1

                # 9. יצירת הקופון ושמירתו
                new_coupon = Coupon(
                    code=code,
                    value=value,
                    cost=cost,
                    company=company.name,
                    description=str(description),
                    expiration=expiration,
                    user_id=user.id,
                    status='פעיל',  # ברירת מחדל
                    is_one_time=is_one_time,
                    purpose=purpose
                )
                # מוסיפים את התגית
                new_coupon.tags.append(most_common_tag)
                db.session.add(new_coupon)
                new_coupons.append(new_coupon)

            except Exception as e:
                invalid_coupons.append(f'שורה {index + 2}: {str(e)}')

        # שמירת כל הנתונים למסד
        db.session.commit()

        # מחיקת הקובץ לאחר עיבוד
        os.remove(file_path)

        # Flash Messages
        if new_coupons:
            flash(f"הקופונים הבאים נטענו בהצלחה: {[coupon.code for coupon in new_coupons]}", "success")

        if invalid_coupons:
            flash(f"טעינת הקופונים נכשלה עבור השורות הבאות:<br>{'<br>'.join(invalid_coupons)}", "danger")

        if missing_optional_fields_messages:
            flash(f"הערות בנוגע לשדות אופציונליים:<br>{'<br>'.join(missing_optional_fields_messages)}", "warning")

        return invalid_coupons, missing_optional_fields_messages, new_coupons

    except Exception as e:
        db.session.rollback()
        flash(f"אירעה שגיאה כללית: {str(e)}", "danger")
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


def get_public_ip():
    try:
        response = requests.get('https://api.ipify.org?format=json')
        if response.status_code == 200:
            data = response.json()
            return data['ip']
        else:
            print(f"Failed to get IP. Status code: {response.status_code}")
            return None
    except requests.RequestException as e:
        print(f"An error occurred: {e}")
        return None



def get_geo_location(ip_address):
    # טוען משתני סביבה מקובץ .env
    """
    פונקציה לשליפת מידע גיאוגרפי מבוסס IP באמצעות ipinfo.io.
    """
    if not ip_address or not API_KEY:
        return {
            "city": None,
            "region": None,
            "country": None,
            "loc": None,
            "org": None,
            "timezone": None
        }

    try:
        response = requests.get(f"https://ipinfo.io/{ip_address}/json?token={API_KEY}", timeout=5)
        response.raise_for_status()
        data = response.json()

        return {
            "city": data.get("city", None),
            "region": data.get("region", None),
            "country": data.get("country", None),
            "loc": data.get("loc", None),
            "org": data.get("org", None),
            "timezone": data.get("timezone", None)
        }

    except requests.RequestException as e:
        current_app.logger.error(f"Error retrieving geo location: {e}")
        return {
            "city": None,
            "region": None,
            "country": None,
            "loc": None,
            "org": None,
            "timezone": None
        }

# app/helpers.py

def send_password_reset_email(user):
    try:
        token = generate_confirmation_token(user.email)
        reset_url = url_for('auth.reset_password', token=token, _external=True)
        html = render_template('emails/password_reset_email.html', user=user, reset_link=reset_url)

        sender_email = 'CouponMasterIL2@gmail.com'
        sender_name = 'Coupon Master'
        recipient_email = user.email
        recipient_name = user.first_name
        subject = "בקשת שחזור סיסמה - Coupon Master"

        #print(f"שליחת מייל שחזור לכתובת: {recipient_email}")
        #print(f"קישור שחזור: {reset_url}")

        response = send_email(
            sender_email=sender_email,
            sender_name=sender_name,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            subject=subject,
            html_content=html
        )

        #print(f"תשובת השרת לשליחת המייל: {response}")

    except Exception as e:
        print(f"שגיאה בשליחת מייל שחזור סיסמה: {e}")


# app/helpers.py

def generate_password_reset_token(email, expiration=3600):
    """
    יוצרת טוקן מסוג Time-Limited עבור שחזור סיסמה.
    :param email: האימייל שאליו משוייך הטוקן
    :param expiration: משך התוקף בשניות (ברירת מחדל: 3600 = שעה)
    :return: מחרוזת טוקן חתום
    """
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps(email, salt=current_app.config['SECURITY_PASSWORD_SALT'])

def confirm_password_reset_token(token, expiration=3600):
    """
    בודקת את תקינות הטוקן ותוקפו עבור שחזור סיסמה.

    :param token: המחרוזת שהגיעה ב-URL
    :param expiration: פג תוקף בשניות (ברירת מחדל: 3600 = שעה)
    :return: כתובת האימייל אם תקין, אחרת יזרק חריג (Exception)
    """
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    email = s.loads(
        token,
        salt=current_app.config['SECURITY_PASSWORD_SALT'],
        max_age=expiration
    )
    return email


import openai
import json
import pandas as pd
import os
from datetime import datetime
from app.models import Company  # נניח שזה מביא את החברות מה-DB

def parse_user_usage_text(usage_text, user):
    openai.api_key = os.getenv("OPENAI_API_KEY")

    # שליפת רשימת החברות המותרות מהמערכת
    companies = {c.name.lower(): c.name for c in Company.query.all()}  # מילון לשמירה על התאמה בשם
    companies_str = ", ".join(companies.keys())

    # פרומפט מותאם שמכריח שימוש בחברות הקיימות בלבד
    prompt = f"""
    להלן טקסט המתאר שימוש בקופונים:
    \"\"\"{usage_text}\"\"\"

    יש להחזיר רק חברות מהרשימה הקיימת:
    {companies_str}

    כל אובייקט בפלט מכיל:
    - company: שם החברה **כפי שהוא מופיע** ברשימה (אין להמציא שמות!)
    - amount_used: סכום השימוש בש"ח
    - coupon_value: הערך המלא של הקופון (אם קיים בטקסט, אחרת ריק)
    - additional_info: תיאור נוסף מהמשתמש

    דוגמה לפלט:
    [
      {{"company": "איקאה", "coupon_value": 50, "amount_paid": 25, "additional_info": "קניית כיסא"}},
      {{"company": "קסטרו", "coupon_value": "", "amount_paid": "", "additional_info": "חולצה במבצע"}}
    ]
    """

    # קריאה ל-GPT
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        functions=[
            {
                "name": "parse_coupon_usage",
                "description": "Extracts coupon usage details from the text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "usages": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "company": {
                                        "type": "string",
                                        "description": "שם החברה מתוך הרשימה בלבד"
                                    },
                                    "amount_used": {
                                        "type": "number",
                                        "description": "כמה ש\"ח נוצלו"
                                    },
                                    "coupon_value": {
                                        "type": ["number", "null"],
                                        "description": "כמה המשתמש שילם על הקופון (אם מופיע בטקסט, אחרת ריק)"
                                    },
                                    "additional_info": {
                                        "type": "string",
                                        "description": "פירוט נוסף על העסקה"
                                    }
                                },
                                "required": [
                                    "company",
                                    "amount_used",
                                    "coupon_value",
                                    "additional_info"
                                ]
                            }
                        }
                    },
                    "required": ["usages"]
                }
            }
        ]
    )

    # חילוץ ה-arguments
    content = response["choices"][0]["message"]["function_call"]["arguments"]

    # ניסיון להמיר את התשובה ל-JSON
    try:
        usage_data = json.loads(content)
        usage_list = usage_data.get("usages", [])
    except json.JSONDecodeError:
        usage_list = []

    # סינון רשומות עם חברות שאינן ברשימה
    print(usage_list)

    # יצירת DataFrame
    usage_df = pd.DataFrame(usage_list)

    # עיבוד מידע נוסף עבור חישוב עלויות
    usage_record = {
        "id": response["id"],
        "object": response["object"],
        "created": datetime.utcfromtimestamp(response["created"]).strftime('%Y-%m-%d %H:%M:%S'),
        "model": response["model"],
        "prompt_tokens": response["usage"]["prompt_tokens"],
        "completion_tokens": response["usage"]["completion_tokens"],
        "total_tokens": response["usage"]["total_tokens"],
        "cost_usd": 0.0,  # תחשב לפי הנוסחה שלך
        "cost_ils": 0.0,
        "exchange_rate": 3.75,  # נניח
        "prompt_text": prompt,
        "response_text": content
    }
    pricing_df = pd.DataFrame([usage_record])

    return usage_df, pricing_df


import logging

def decrypt_coupon_code(encrypted_code):
    try:
        encryption_key = os.getenv("ENCRYPTION_KEY")
        if not encryption_key:
            logging.error("ENCRYPTION_KEY not found in environment variables.")
            return None  # מחזיר None אם המפתח חסר

        # הפעלת אלגוריתם הפענוח שלך
        decrypted_code = some_decryption_function(encrypted_code, encryption_key)
        return decrypted_code
    except Exception as e:
        logging.error(f"Error decrypting coupon code: {e}")
        return None  # מחזיר None במקום להפעיל flash()

def get_greeting():
    israel_tz = pytz.timezone('Asia/Jerusalem')
    current_hour = datetime.now(israel_tz).hour

    if current_hour < 12:
        return "בוקר טוב"
    elif current_hour < 18:
        return "צהריים טובים"
    else:
        return "ערב טוב"

