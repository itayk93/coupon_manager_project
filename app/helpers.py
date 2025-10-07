import os
import sys
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

# Import Playwright only if available
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None

# from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint
from app.extensions import db
from app.models import (
    Coupon,
    CouponTransaction,
    Notification,
    Tag,
    coupon_tags,
    Transaction,
)
from itsdangerous import URLSafeTimedSerializer
from app.models import Company
import numpy as np
from sqlalchemy.sql import text
import pytz
from flask import flash  # Import the function for displaying user messages

# app/helpers.py
from app.models import FeatureAccess
from flask import render_template  # Import render_template
from sqlalchemy import func
from app.models import Tag, Coupon, coupon_tags
import openai
import json
import pandas as pd
import os
from datetime import datetime
from app.models import Company
import logging
from flask_mail import Message

load_dotenv()
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
IMGUR_CLIENT_ID = os.getenv("IMGUR_CLIENT_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
SENDER_NAME = "Coupon Master"
API_KEY = os.getenv("IPINFO_API_KEY")

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
#  Helper function for creating notifications
# ----------------------------------------------------------------
def create_notification(user_id, message, link):
    """
    Creates a new notification and adds it to the DB (don't forget to perform db.session.commit()
    where this function is called, or later in the flow).
    """
    tz_il = ZoneInfo("Asia/Jerusalem")
    now_il = datetime.now(tz_il)

    notification = Notification(
        user_id=user_id,
        message=message,
        link=link,
        timestamp=datetime.now(tz_il),  # Save according to Israel time
    )
    db.session.add(notification)


# ----------------------------------------------------------------
#  Helper function for updating coupon status
# ----------------------------------------------------------------
def update_coupon_status(coupon):
    """
    Updates the coupon status (active/used/expired) based on used_value and expiration date.
    Also sends a notification to the user if it has just become used or expired.
    """
    try:
        current_date = datetime.now(timezone.utc).date()
        old_status = (
            coupon.status or "פעיל"
        )  # If there's no status yet, assume 'active'
        new_status = "פעיל"

        # Check expiration
        if coupon.expiration:
            if isinstance(coupon.expiration, date):
                expiration_date = coupon.expiration
            else:
                try:
                    expiration_date = datetime.strptime(
                        coupon.expiration, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    logger.error(
                        f"Invalid date format for coupon {coupon.id}: {coupon.expiration}"
                    )
                    expiration_date = None

            if expiration_date and current_date > expiration_date:
                new_status = "פג תוקף"

        # Check if fully used
        if coupon.used_value >= coupon.value:
            new_status = "נוצל"

        # Update if there's actually a change
        if old_status != new_status:
            coupon.status = new_status
            logger.info(
                f"Coupon {coupon.id} status updated from '{old_status}' to '{new_status}'"
            )

    except Exception as e:
        logger.error(f"Error in update_coupon_status for coupon {coupon.id}: {e}")


# ----------------------------------------------------------------
#  Helper function for updating coupon usage amount
# ----------------------------------------------------------------
def update_coupon_usage(coupon, usage_amount, details="עדכון שימוש"):
    """
    Updates coupon usage (adds to used_value), calls status update,
    creates a usage record, and sends a notification about the update.

    :param coupon: The coupon object to update
    :param usage_amount: The amount of usage to add to used_value
    :param details: Description of the action for the usage record
    """
    from app.models import CouponUsage

    try:
        # Update the used value
        coupon.used_value += usage_amount
        update_coupon_status(coupon)

        # Create usage record
        usage = CouponUsage(
            coupon_id=coupon.id,
            used_amount=usage_amount,
            timestamp=datetime.now(timezone.utc),
            action="שימוש",
            details=details,
        )
        db.session.add(usage)

        # Send notification to user about the update
        """""" """
        create_notification(
            user_id=coupon.user_id,
            message=f"השימוש בקופון {coupon.code} עודכן (+{usage_amount} ש\"ח).",
            link=url_for('coupons.coupon_detail', id=coupon.id)
        )
        """ """"""

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating coupon usage for coupon {coupon.id}: {e}")
        raise


def get_coupon_data_old(coupon, save_directory="automatic_coupon_update/input_html"):
    """
    Activates Selenium to enter the Multipass or Max website (according to coupon.auto_download_details),
    downloads the relevant information and converts it to a DataFrame.
    Then, checks what already exists in the DB in the coupon_transaction table and compares,
    in order to add only new transactions and adjust the coupon status accordingly.

    Returns a DataFrame with only new transactions, or None if there are no new ones or if there was an error.
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
    coupon_kind = coupon.auto_download_details  # "Multipass" / "Max" (or other)
    card_exp = coupon.card_exp
    cvv = coupon.cvv

    # Basic Selenium options setup
    chrome_options = Options()
    # Only run headless in production environment or if explicitly set
    if os.getenv('FLASK_ENV') == 'production' or os.getenv('SELENIUM_HEADLESS', 'false').lower() == 'true':
        chrome_options.add_argument("--headless")  # Run in headless mode for production
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-features=VizDisplayCompositor")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-images")  # Prevent image loading
    chrome_options.add_argument(
        "--disable-extensions"
    )  # Disable unnecessary extensions
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    # For the "Max" coupon type, block images
    if coupon_kind == "Max":
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")

    df = None  # DataFrame to hold the scraped data

    # -------------------- Handling Multipass Scenario --------------------
    if coupon_kind == "Multipass":
        driver = None
        try:
            # Set Chrome binary path - try multiple possible locations
            possible_chrome_paths = [
                os.getenv('CHROME_BIN'),
                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                '/usr/bin/google-chrome-stable',
                '/usr/bin/google-chrome',
                '/usr/bin/chromium-browser',
                '/usr/bin/chromium',
                '/opt/google/chrome/chrome'
            ]
            
            chrome_bin = None
            for path in possible_chrome_paths:
                if path and os.path.isfile(path):
                    chrome_bin = path
                    break
            
            if not chrome_bin:
                chrome_bin = possible_chrome_paths[2]  # Default to google-chrome-stable
                
            chrome_options.binary_location = chrome_bin
            
            driver = webdriver.Chrome(options=chrome_options)
            driver.get(
                "https://multipass.co.il/%d7%91%d7%a8%d7%95%d7%a8-%d7%99%d7%aa%d7%a8%d7%94/"
            )
            wait = WebDriverWait(driver, 120)  # 2 minutes for Multipass
            time.sleep(5)

            card_number_field = driver.find_element(
                By.XPATH, "//input[@id='newcardid']"
            )
            card_number_field.clear()

            # cleaned_coupon_number = str(coupon_number[:-4]).replace("-", "")
            cleaned_coupon_number = str(coupon_number).replace("-", "")
            # print(cleaned_coupon_number)
            card_number_field.send_keys(cleaned_coupon_number)

            # Handle reCAPTCHA
            recaptcha_iframe = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//iframe[contains(@src, 'recaptcha')]")
                )
            )
            driver.switch_to.frame(recaptcha_iframe)

            checkbox = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, ".recaptcha-checkbox-border")
                )
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

        # Try to read the table from the saved HTML
        try:
            dfs = pd.read_html(file_path)
            os.remove(file_path)

            if not dfs:
                print("No tables found in HTML (Multipass).")
                return None

            df = dfs[0]

            # Change column names
            df = df.rename(
                columns={
                    "שם בית עסק": "location",
                    "סכום טעינת תקציב": "recharge_amount",
                    "סכום מימוש תקציב": "usage_amount",
                    "תאריך": "transaction_date",
                    "מספר אסמכתא": "reference_number",
                }
            )

            # Handle missing columns
            if "recharge_amount" not in df.columns:
                df["recharge_amount"] = 0.0
            if "usage_amount" not in df.columns:
                df["usage_amount"] = 0.0

            # Convert transaction date
            df["transaction_date"] = pd.to_datetime(
                df["transaction_date"], format="%H:%M %d/%m/%Y", errors="coerce"
            )

            # Convert numeric columns
            numeric_columns = ["recharge_amount", "usage_amount"]
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        except Exception as e:
            print(f"An error occurred during data parsing (Multipass): {e}")
            traceback.print_exc()
            return None

    # -------------------- Handling Max Scenario --------------------
    elif coupon_kind == "Max":
        try:
            # Set Chrome binary path - try multiple possible locations
            possible_chrome_paths = [
                os.getenv('CHROME_BIN'),
                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                '/usr/bin/google-chrome-stable',
                '/usr/bin/google-chrome',
                '/usr/bin/chromium-browser',
                '/usr/bin/chromium',
                '/opt/google/chrome/chrome'
            ]
            
            chrome_bin = None
            for path in possible_chrome_paths:
                if path and os.path.isfile(path):
                    chrome_bin = path
                    break
            
            if not chrome_bin:
                chrome_bin = possible_chrome_paths[2]  # Default to google-chrome-stable
                
            chrome_options.binary_location = chrome_bin
            
            # Use with so that Selenium closes automatically at the end
            with webdriver.Chrome(options=chrome_options) as driver:
                wait = WebDriverWait(driver, 30)
                driver.get("https://www.max.co.il/gift-card-transactions/main")

                def safe_find(by, value, timeout=10):
                    """ Attempts to find an element with a timeout """
                    return WebDriverWait(driver, timeout).until(
                        EC.visibility_of_element_located((by, value))
                    )

                card_number_field = safe_find(By.ID, "giftCardNumber")
                card_number_field.clear()
                card_number_field.send_keys(coupon_number)

                exp_field = safe_find(By.ID, "expDate")
                exp_field.clear()
                exp_field.send_keys(card_exp)

                cvv_field = safe_find(By.ID, "cvv")
                cvv_field.clear()
                cvv_field.send_keys(cvv)

                continue_button = wait.until(
                    EC.element_to_be_clickable((By.ID, "continue"))
                )
                continue_button.click()

                time.sleep(7)

                table = wait.until(
                    EC.presence_of_element_located((By.CLASS_NAME, "mat-table"))
                )

                headers = [
                    header.text.strip()
                    for header in table.find_elements(By.TAG_NAME, "th")
                ]
                rows = []

                # Table rows
                all_rows = table.find_elements(By.TAG_NAME, "tr")
                # The header is usually the first row, so we start from 1
                for row in all_rows[1:]:
                    cells = [
                        cell.text.strip()
                        for cell in row.find_elements(By.TAG_NAME, "td")
                    ]
                    if cells:
                        rows.append(cells)

                df = pd.DataFrame(rows, columns=headers)

                # Clean up and format data
                if "שולם בתאריך" in df.columns:
                    df["שולם בתאריך"] = pd.to_datetime(
                        df["שולם בתאריך"], format="%d.%m.%Y", errors="coerce"
                    )
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

                # Change column names
                col_map = {
                    "שולם בתאריך": "transaction_date",
                    "שם בית העסק": "location",
                    "סכום בשקלים": "amount",
                    "יתרה": "balance",
                    "פעולה": "action",
                    "הערות": "notes",
                }
                for k, v in col_map.items():
                    if k in df.columns:
                        df.rename(columns={k: v}, inplace=True)

                # Create usage_amount and recharge_amount columns based on action
                df["usage_amount"] = df.apply(
                    lambda x: x["amount"]
                    if ("action" in df.columns and x["action"] == "עסקה")
                    else 0.0,
                    axis=1,
                )
                df["recharge_amount"] = df.apply(
                    lambda x: -(x["amount"])
                    if ("action" in df.columns and x["action"] == "טעינה")
                    else 0.0,
                    axis=1,
                )

                # Add reference number column
                # *To allow identifying new transactions from DB*
                # For example, create a unique identifier based on row index
                df["reference_number"] = df.index.map(
                    lambda i: f"max_ref_{int(time.time())}_{i}"
                )

                # Drop unnecessary columns
                for col_to_drop in ["action", "notes"]:
                    if col_to_drop in df.columns:
                        df.drop(columns=[col_to_drop], inplace=True)

        except Exception as e:
            print(f"An error occurred during Selenium operations (Max): {e}")
            traceback.print_exc()
            return None

    else:
        # If there's any other case other than Multipass or Max, we can return None or handle it differently
        print(f"Unsupported coupon kind: {coupon_kind}")
        return None

    # At this point, we should have a ready df
    if df is None or df.empty:
        print("No data frame (df) was created or df is empty.")
        return None

    # ----------------------------------------------------------------------
    # Common Stage: Database Comparison and Update
    # ----------------------------------------------------------------------
    try:
        # Retrieve existing data from the database (only reference_number)
        existing_data = pd.read_sql_query(
            """
            SELECT reference_number
            FROM coupon_transaction
            WHERE coupon_id = %(coupon_id)s
            """,
            db.engine,
            params={"coupon_id": coupon.id},
        )

        # Check if the number of rows in the database is different from the new ones
        # If yes (in case there are more than 0 in the DB) - delete all and insert new
        if len(existing_data) != len(df):
            if len(existing_data) > 0:
                db.session.execute(
                    text("DELETE FROM coupon_transaction WHERE coupon_id = :coupon_id"),
                    {"coupon_id": coupon.id},
                )
                db.session.commit()

                # Update after deletion
                existing_data = pd.read_sql_query(
                    """
                    SELECT reference_number
                    FROM coupon_transaction
                    WHERE coupon_id = %(coupon_id)s
                    """,
                    db.engine,
                    params={"coupon_id": coupon.id},
                )

        existing_refs = set(existing_data["reference_number"].astype(str))

        # Convert reference_number to string for comparison
        df["reference_number"] = df["reference_number"].astype(str)

        # Filter out existing transactions (if any were left behind)
        df_new = df[~df["reference_number"].isin(existing_refs)]

        if df_new.empty:
            print("No new transactions to add (all references already exist in DB).")
            return pd.DataFrame()  # Return empty DataFrame instead of None

        # Add new transactions
        for idx, row in df_new.iterrows():
            # Handle invalid transaction_date values (NaT, NaN, etc.)
            transaction_date = row.get("transaction_date")
            if pd.isna(transaction_date) or str(transaction_date) in ['NaT', 'NaN', 'nat', 'nan']:
                transaction_date = None
                
            # Skip transactions with invalid data
            location = row.get("location", "")
            reference_number = row.get("reference_number", "")
            
            # Skip if location or reference contains error messages
            if any(invalid_text in str(location) for invalid_text in ["לא נמצאו רשומות", "לא נמצא", "שגיאה"]):
                print(f"Skipping invalid transaction with location: {location}")
                continue
                
            if any(invalid_text in str(reference_number) for invalid_text in ["לא נמצאו רשומות", "לא נמצא", "שגיאה"]):
                print(f"Skipping invalid transaction with reference: {reference_number}")
                continue
                
            try:
                transaction = CouponTransaction(
                    coupon_id=coupon.id,
                    transaction_date=transaction_date,
                    location=location,
                    recharge_amount=row.get("recharge_amount", 0.0),
                    usage_amount=row.get("usage_amount", 0.0),
                    reference_number=reference_number,
                )
                db.session.add(transaction)
            except ValueError as e:
                print(f"Skipping invalid transaction: {e}")
                continue

        # Update total usage in the database
        total_used = (
            db.session.query(func.sum(CouponTransaction.usage_amount))
            .filter_by(coupon_id=coupon.id)
            .scalar()
            or 0.0
        )
        coupon.used_value = float(total_used)

        # Check if the coupon is still active
        update_coupon_status(coupon)

        db.session.commit()

        print(
            f"Transactions for coupon {coupon.code} have been updated in the database."
        )
        return df_new  # Return the new transactions
    except Exception as e:
        print(f"An error occurred during data parsing or database operations: {e}")
        traceback.print_exc()
        db.session.rollback()
        return None


# Global debug flag to control print statements
DEBUG_MODE = True


def set_debug_mode(mode):
    """
    Set the debug mode for printing debug information.

    Args:
        mode (bool): True to enable debug prints, False to disable
    """
    global DEBUG_MODE
    DEBUG_MODE = mode


def set_debug_mode(mode):
    """
    Set the debug mode for printing debug information.

    Args:
        mode (bool): True to enable debug prints, False to disable
    """
    global DEBUG_MODE
    DEBUG_MODE = mode


def get_coupon_data_with_retry(coupon, max_retries=3, save_directory="automatic_coupon_update/input_html"):
    """
    Wrapper function for get_coupon_data with retry mechanism and advanced logging
    """
    import time
    import logging
    import os
    from datetime import datetime
    
    # Configure logger for multipass updates
    logger = logging.getLogger('multipass_updater')
    if not logger.handlers:
        # Create logs directory if it doesn't exist
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # Create file handler
        handler = logging.FileHandler('logs/multipass_updates.log')
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    start_time = datetime.now()
    logger.info(f"Starting update process for coupon {coupon.code} ({coupon.company})")
    
    for attempt in range(max_retries):
        attempt_start = datetime.now()
        try:
            logger.info(f"Attempt {attempt + 1}/{max_retries} for coupon {coupon.code}")
            
            result = get_coupon_data(coupon, save_directory)
            
            if result is not None:
                attempt_duration = (datetime.now() - attempt_start).total_seconds()
                total_duration = (datetime.now() - start_time).total_seconds()
                
                # Check if DataFrame is empty (no new data) vs has data
                records_count = len(result) if hasattr(result, '__len__') else 0
                if records_count > 0:
                    logger.info(f"✅ SUCCESS: Coupon {coupon.code} updated successfully on attempt {attempt + 1}")
                    logger.info(f"   - Attempt duration: {attempt_duration:.2f}s")
                    logger.info(f"   - Total duration: {total_duration:.2f}s")
                    logger.info(f"   - Records found: {records_count}")
                else:
                    logger.info(f"✅ SUCCESS: Coupon {coupon.code} processed successfully on attempt {attempt + 1} (no new data)")
                    logger.info(f"   - Attempt duration: {attempt_duration:.2f}s")
                    logger.info(f"   - Total duration: {total_duration:.2f}s")
                    logger.info(f"   - No new transactions found (all data already exists)")
                
                return result
            else:
                attempt_duration = (datetime.now() - attempt_start).total_seconds()
                logger.warning(f"❌ No data returned for coupon {coupon.code} on attempt {attempt + 1} (duration: {attempt_duration:.2f}s)")
                
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5  # Exponential backoff: 5, 10, 15 seconds
                    logger.info(f"   - Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    
        except Exception as e:
            attempt_duration = (datetime.now() - attempt_start).total_seconds()
            logger.error(f"💥 ERROR on attempt {attempt + 1} for coupon {coupon.code}: {str(e)}")
            logger.error(f"   - Error type: {type(e).__name__}")
            logger.error(f"   - Attempt duration: {attempt_duration:.2f}s")
            
            if attempt == max_retries - 1:
                total_duration = (datetime.now() - start_time).total_seconds()
                logger.error(f"🚫 FINAL FAILURE: All {max_retries} attempts failed for coupon {coupon.code}")
                logger.error(f"   - Total duration: {total_duration:.2f}s")
                raise e
            else:
                wait_time = (attempt + 1) * 5  # Exponential backoff
                logger.info(f"   - Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
    
    total_duration = (datetime.now() - start_time).total_seconds()
    logger.error(f"🚫 FINAL FAILURE: All {max_retries} attempts failed for coupon {coupon.code} (total duration: {total_duration:.2f}s)")
    return None




def analyze_captcha_with_gpt4o_vision_fullscreen(base64_image, instruction_text):
    """
    ניתוח CAPTCHA עם prompt משופר ויותר אגרסיבי
    """
    import openai
    import json
    
    try:
        openai.api_key = os.getenv("OPENAI_API_KEY")
        
        # הוראות ספציפיות ואגרסיביות יותר
        target_object = instruction_text.lower()
        
        prompt = f"""
        ADVANCED CAPTCHA ANALYSIS using 2024 Computer Vision Techniques: "{instruction_text}"
        
        You are analyzing a 3x3 grid of images using state-of-the-art object detection methods.
        Apply YOLO-style object detection thinking: scan systematically for ANY occurrence of the target.
        
        CRITICAL DETECTION RULES (Based on 2024 Research):
        1. CNN-style Feature Detection - Look for ANY presence of the target object:
           - Tiny objects in backgrounds (even 5-10% of image)
           - Partially occluded/hidden objects (even 30% visible counts)
           - Blurry, distorted, or unclear objects
           - Similar objects (motorcycle=bicycle, SUV=car, etc.)
           - Parts of objects (wheels, signs, partial structures)
        
        2. For BICYCLES specifically (BE VERY AGGRESSIVE):
           - ANY two-wheeled vehicle counts (bicycle, motorcycle, scooter, moped)
           - Look for wheels, handlebars, seats, pedals, or people riding
           - Check backgrounds and street scenes carefully - bikes appear in streets!
           - Even parked bikes, bike parts, or ANYTHING that could be related to cycling
           - If you see people who MIGHT be near bikes, include those squares too
           - Look for bike shops, bike racks, anything bicycle-related
        
        3. For TRAFFIC LIGHTS specifically:
           - Look for ANY traffic light, regardless of color (red, yellow, green, or even unlit)
           - Include hanging traffic lights, pole-mounted lights, traffic signal posts
           - Look for the characteristic shape: round/circular lights in vertical arrangement
           - Even partial, distant, or blurry traffic lights count
           - Check street scenes, intersections, urban backgrounds carefully
           - Traffic signals, pedestrian signals, stop lights, and traffic control devices all count
           - Look for the typical traffic light housing/box shape
           - Even if only part of the traffic light is visible, it counts
           - Pay special attention to poles and vertical structures that might have traffic lights

        4. For STAIRS specifically:
           - Look for ACTUAL step structures - horizontal lines creating steps
           - Include outdoor stairs, indoor stairs, building entrances with steps
           - Look for the characteristic pattern: multiple horizontal surfaces at different heights
           - Steps can be concrete, wood, stone, or any material
           - Include staircases, steps leading to buildings, porch steps
           - Even partial stairways visible in backgrounds count
           - Do NOT confuse with: flat surfaces, ramps, walls, or regular building features
        
        5. LSTM-style Sequential Analysis - Consider context:
           - Objects in street scenes often appear together
           - Urban environments = higher probability of traffic elements
           - Multiple similar objects may appear in sequence
        
        6. QUANTITY over MISSED MATCHES - Better to select extra squares than miss real bicycles
        7. Use confidence levels: "high" (80%+ sure), "medium" (50-80%), "low" (30-50%)
        8. When in doubt, INCLUDE IT - false positives are better than false negatives
        
        SYSTEMATIC GRID ANALYSIS (like YOLO object detection):
        Scan each cell using computer vision principles:
        - Row 0: [0,0] [0,1] [0,2] (top row) - check backgrounds and distant objects
        - Row 1: [1,0] [1,1] [1,2] (middle row) - check foreground and main subjects
        - Row 2: [2,0] [2,1] [2,2] (bottom row) - check partial/cut-off objects
        
        Return JSON format:
        {{
            "instruction_detected": "{instruction_text}",
            "captcha_bounds": {{"left": 600, "top": 270, "width": 300, "height": 300}},
            "matches_found": [
                {{"row": 0, "col": 2, "description": "traffic light visible on pole", "confidence": "high"}},
                {{"row": 1, "col": 1, "description": "partial traffic light in background", "confidence": "medium"}},
                {{"row": 2, "col": 2, "description": "traffic signal at intersection", "confidence": "high"}}
            ]
        }}
        
        APPLY 2024 AI RECOGNITION PRINCIPLES:
        - Use computer vision pattern matching
        - Apply object detection confidence scoring  
        - Consider contextual relationships between objects
        - Prioritize ANY visual evidence over perfect clarity
        
        CRITICAL: CAPTCHA requires finding ALL instances!
        - It's better to select 8-9 squares than miss 1-2 real matches
        - Err on the side of inclusion rather than exclusion
        - If unsure, SELECT IT anyway!
        
        SCAN ULTRA-AGGRESSIVELY - Include anything that might contain the target object!
        """
        
        response = openai.ChatCompletion.create(
            model="gpt-4o",  # שינוי למודל החזק יותר
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1500,
            temperature=0.1  # מעט יצירתיות כדי להיות יותר אגרסיבי
        )
        
        result = response.choices[0].message.content
        
        try:
            start_idx = result.find('{')
            end_idx = result.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = result[start_idx:end_idx]
                parsed_result = json.loads(json_str)
                
                # סינון משופר מבוסס מחקר 2024 - מספר רמות ביטחון
                filtered_matches = []
                if 'matches_found' in parsed_result:
                    high_confidence = []
                    medium_confidence = []
                    low_confidence = []
                    
                    for match in parsed_result['matches_found']:
                        confidence = match.get('confidence', 'low').lower()
                        if confidence in ['high', 'very high', 'certain']:
                            high_confidence.append(match)
                        elif confidence in ['medium', 'moderate', 'good']:
                            medium_confidence.append(match)
                        elif confidence in ['low', 'possible', 'maybe'] and confidence not in ['none', 'no', 'uncertain']:
                            low_confidence.append(match)
                    
                    # אסטרטגיה אגרסיבית: קח הכל - עדיף יותר מדי מאשר להחמיץ
                    filtered_matches = high_confidence + medium_confidence + low_confidence
                    
                    # אם בכלל אין matches, זה בעיה - בקש מ-GPT להיות יותר אגרסיבי
                    if not filtered_matches and DEBUG_MODE:
                        print(f"[GPT ANALYSIS] WARNING: No matches found at all! GPT might be too conservative.")
                    
                    if DEBUG_MODE:
                        print(f"[GPT ANALYSIS] Confidence breakdown: High={len(high_confidence)}, Medium={len(medium_confidence)}, Low={len(low_confidence)}")
                
                parsed_result['matches_found'] = filtered_matches
                
                if DEBUG_MODE:
                    print(f"[GPT ANALYSIS] Full response: {result}")
                    print(f"[GPT ANALYSIS] Accepted matches: {len(filtered_matches)}")
                    print(f"[GPT ANALYSIS] Final JSON: {parsed_result}")
                
                return parsed_result
        except Exception as json_error:
            if DEBUG_MODE:
                print(f"[GPT ANALYSIS] JSON parsing error: {json_error}")
                print(f"[GPT ANALYSIS] Raw response: {result}")
            
        return None
        
    except Exception as e:
        print(f"Error in GPT-4o analysis: {e}")
        return None



def calculate_captcha_click_coordinates_fullscreen(image_path, matches, captcha_bounds):
    """
    חישוב קואורדינטות לחיצה עבור CAPTCHA מתוך צילום מסך מלא - עם pyautogui
    """
    coordinates = []
    
    if not captcha_bounds:
        print("[COORDINATE CALC] No captcha bounds from GPT, using estimation")
        captcha_left = 600  # הערכה מעודכנת
        captcha_top = 270   # הערכה מעודכנת 
        captcha_width = 300
        captcha_height = 300
    else:
        captcha_left = captcha_bounds.get('left', 600)
        captcha_top = captcha_bounds.get('top', 270)
        captcha_width = captcha_bounds.get('width', 300)
        captcha_height = captcha_bounds.get('height', 300)
        
        print(f"[COORDINATE CALC] Using GPT bounds: left={captcha_left}, top={captcha_top}, w={captcha_width}, h={captcha_height}")
    
    cell_width = captcha_width // 3
    cell_height = captcha_height // 3
    
    for i, match in enumerate(matches):
        row = match['row']
        col = match['col']
        
        # חישוב קואורדינטות אבסולוטיות במסך (לפי המסך האמיתי, לא iframe)
        cell_left = captcha_left + (col * cell_width)
        cell_top = captcha_top + (row * cell_height)
        
        # מרכז התא - קואורדינטות מוחלטות במסך
        center_x = cell_left + (cell_width // 2)
        center_y = cell_top + (cell_height // 2)
        
        coordinates.append((center_x, center_y))
        
        print(f"[COORDINATE CALC] Match {i+1} (Row {row}, Col {col}):")
        print(f"  Cell area: ({cell_left}, {cell_top}) to ({cell_left + cell_width}, {cell_top + cell_height})")
        print(f"  Click point: ({center_x}, {center_y})")
        print(f"  Confidence: {match.get('confidence', 'unknown')}")
    
    return coordinates


def solve_captcha_challenge(driver, wait_timeout=120):
    """
    פותר CAPTCHA אוטומטי - בוחר שיטה לפי סוג ה-CAPTCHA
    
    - אם זה CAPTCHA של תמונות: משתמש בGPT Vision
    - אם זה CAPTCHA טקסט: משתמש ב-TrueCaptcha API
    - כ-fallback: משתמש באודיו
    """
    return solve_captcha_smart_detection(driver, wait_timeout)


def solve_captcha_smart_detection(driver, wait_timeout=120):
    """
    פונקציה חכמה לזיהוי סוג CAPTCHA ובחירת שיטת פתרון מתאימה
    """
    import time
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[SMART CAPTCHA SOLVER] {message}")
    
    try:
        debug_print("Starting smart CAPTCHA detection...")
        time.sleep(3)
        
        # חיפוש iframe של CAPTCHA
        captcha_iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'bframe')]")
        
        if not captcha_iframes:
            debug_print("No CAPTCHA iframe found - checking if button is enabled")
            submit_button = driver.find_element(By.ID, "submit")
            if not submit_button.get_attribute("disabled"):
                debug_print("Submit button is enabled - CAPTCHA already solved")
                return True
            else:
                debug_print("Submit button still disabled but no CAPTCHA iframe found")
                return False
        
        debug_print(f"Found {len(captcha_iframes)} CAPTCHA iframe(s)")
        
        # מעבר ל-iframe לבדיקת סוג ה-CAPTCHA
        driver.switch_to.frame(captcha_iframes[0])
        time.sleep(2)
        
        # בדיקה אם זה CAPTCHA של תמונות (image challenge)
        image_challenge_selectors = [
            ".rc-imageselect-desc",
            ".rc-imageselect-desc-no-canonical", 
            ".rc-imageselect-instructions",
            "td.rc-imageselect-desc-wrapper"
        ]
        
        is_image_captcha = False
        instruction_text = ""
        
        for selector in image_challenge_selectors:
            try:
                instruction_element = driver.find_element(By.CSS_SELECTOR, selector)
                if instruction_element and instruction_element.is_displayed():
                    instruction_text = instruction_element.text.strip()
                    if instruction_text:
                        is_image_captcha = True
                        debug_print(f"Detected IMAGE CAPTCHA with instruction: '{instruction_text}'")
                        break
            except:
                continue
        
        # חזרה ל-frame הראשי
        driver.switch_to.default_content()
        
        if is_image_captcha:
            # בדיקה אם Capsolver נכשל הרבה לאחרונה
            if not hasattr(solve_captcha_smart_detection, 'capsolver_failures'):
                solve_captcha_smart_detection.capsolver_failures = 0
            
            # אם Capsolver נכשל 3 פעמים רצופות, נעבור ישר ל-GPT
            if solve_captcha_smart_detection.capsolver_failures >= 3:
                debug_print("⚡ Capsolver failed too many times, skipping to GPT Vision")
                print(f"\n⚡ [SKIP] Capsolver נכשל יותר מדי, עובר ישר ל-GPT Vision ⚡\n")
                result = solve_captcha_challenge_with_image(driver, wait_timeout)
                if result:
                    solve_captcha_smart_detection.capsolver_failures = 0  # איפוס אם הצליח
                return result
            
            # ניסיון עם Capsolver
            debug_print("🤖 Using Capsolver API for image CAPTCHA (improved)")
            print(f"\n🤖 [CAPSOLVER] משתמש ב-Capsolver API לCAPTCHA תמונות: '{instruction_text}' 🤖\n")
            
            result = solve_captcha_with_capsolver_improved(driver, wait_timeout, instruction_text)
            if result:
                solve_captcha_smart_detection.capsolver_failures = 0  # איפוס אם הצליח
                return True
            else:
                # עדכון מונה כישלונות
                solve_captcha_smart_detection.capsolver_failures += 1
                debug_print(f"🖼️ Capsolver failed (failure #{solve_captcha_smart_detection.capsolver_failures}), falling back to GPT Vision")
                print(f"\n🖼️ [FALLBACK] Capsolver נכשל ({solve_captcha_smart_detection.capsolver_failures}/3), עובר ל-GPT Vision 🖼️\n")
                return solve_captcha_challenge_with_image(driver, wait_timeout)
        else:
            # אם זה לא CAPTCHA תמונות, נשתמש באודיו
            debug_print("🔊 Not image CAPTCHA, using audio solving")
            print(f"\n🔊 [AUDIO] לא זוהה CAPTCHA תמונות, עובר לפתרון אודיו 🔊\n")
            return solve_captcha_with_audio(driver, wait_timeout)
        
    except Exception as e:
        debug_print(f"Error in smart CAPTCHA detection: {e}")
        # כ-fallback אחרון, נשתמש באודיו
        debug_print("🔊 Using audio as final fallback")
        try:
            return solve_captcha_with_audio(driver, wait_timeout)
        except:
            return False


def solve_captcha_challenge_with_image(driver, wait_timeout=120):
    """
    פותר CAPTCHA אוטומטי עם pyautogui - עם שמירת צילום מסך לבדיקה (הפונקציה הישנה)
    """
    import time
    import base64
    import tempfile
    import os
    import pyautogui
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[CAPTCHA SOLVER] {message}")
    
    try:
        debug_print("Starting CAPTCHA solving process with pyautogui...")
        
        time.sleep(3)
        
        try:
            captcha_iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'bframe')]")
            
            if not captcha_iframes:
                debug_print("No image CAPTCHA iframe found - checking if button is enabled")
                submit_button = driver.find_element(By.ID, "submit")
                if not submit_button.get_attribute("disabled"):
                    debug_print("Submit button is enabled - CAPTCHA already solved")
                    return True
                else:
                    debug_print("Submit button still disabled but no CAPTCHA iframe found")
                    return False
            
            debug_print(f"Found {len(captcha_iframes)} CAPTCHA iframe(s)")
            
            # חזרה ל-frame הראשי לצילום מסך
            driver.switch_to.default_content()
            
            timestamp = int(time.time())
            
            # לפני צילום המסך, נוודא שהחלון פעיל
            debug_print("Bringing browser window to front...")
            try:
                # מעביר את הפוקוס לחלון הדפדפן
                driver.switch_to.window(driver.current_window_handle)
                
                # במק - נשתמש ב-AppleScript להבאת כרום לחזית
                import subprocess
                applescript = '''
                tell application "Google Chrome"
                    activate
                    tell front window to set index to 1
                end tell
                '''
                subprocess.run(['osascript', '-e', applescript], check=False)
                time.sleep(1)
                
                # לחיצה קלה על הדפדפן כדי להפעיל אותו
                pyautogui.click(720, 400)  # לחיצה במרכז המסך
                time.sleep(0.5)
            except Exception as e:
                debug_print(f"Error bringing window to front: {e}")
                pass
            
            # הזזת העכבר לקצה הימני לפני צילום המסך כדי שלא יפריע
            debug_print("Moving mouse to right edge before screenshot...")
            screen_width = pyautogui.size().width
            pyautogui.moveTo(screen_width - 10, 100)  # קצה ימני, גובה 100
            time.sleep(0.2)  # המתנה קצרה לוודא שהעכבר זז
            
            # צילום מסך מלא עם הפקודה המובנית של macOS
            debug_print("Taking FULL screen screenshot with macOS screencapture...")
            real_screenshot_path = f"/Users/itaykarkason/Desktop/captcha_fullscreen_{timestamp}.png"
            try:
                # שימוש בפקודת screencapture של macOS - הרבה יותר אמין
                import subprocess
                subprocess.run(['screencapture', real_screenshot_path], check=True)
                debug_print(f"Full screen screenshot saved to: {real_screenshot_path}")
            except Exception as e:
                debug_print(f"Failed to take screenshot with screencapture, falling back to pyautogui: {e}")
                # חזרה ל-pyautogui אם screencapture לא עובד
                # וודא שהעכבר עדיין בקצה הימני
                pyautogui.moveTo(screen_width - 10, 100)
                time.sleep(0.2)
                real_screenshot = pyautogui.screenshot()
                real_screenshot.save(real_screenshot_path)
                debug_print(f"Full screen screenshot saved to: {real_screenshot_path}")
            
            
            # השוואה בין גדלי התמונות
            selenium_size = driver.get_window_size()
            real_size = pyautogui.size()
            debug_print(f"Selenium window size: {selenium_size}")
            debug_print(f"Real screen size: {real_size}")
            
            # קבלת מיקום חלון הדפדפן
            window_position = driver.get_window_position()
            debug_print(f"Browser window position: {window_position}")
            
            # מציאת ההוראה
            driver.switch_to.frame(captcha_iframes[0])
            time.sleep(2)
            
            instruction_text = ""
            instruction_selectors = [
                ".rc-imageselect-desc-no-canonical",
                ".rc-imageselect-desc",
                ".rc-imageselect-instructions",
                "[class*='imageselect-desc']"
            ]
            
            for selector in instruction_selectors:
                try:
                    instruction_element = driver.find_element(By.CSS_SELECTOR, selector)
                    instruction_text = instruction_element.text.strip()
                    if instruction_text:
                        break
                except:
                    continue
            
            debug_print(f"CAPTCHA instruction: {instruction_text}")
            
            # חזרה ל-frame הראשי
            driver.switch_to.default_content()
            
            try:
                # שימוש בתמונת המסך המלא במקום בתמונת הSelenium
                with open(real_screenshot_path, "rb") as image_file:
                    base64_image = base64.b64encode(image_file.read()).decode('utf-8')
                
                # ניתוח עם GPT
                gpt_result = analyze_captcha_with_gpt4o_vision_fullscreen(base64_image, instruction_text)
                
                if not gpt_result or 'matches_found' not in gpt_result:
                    debug_print("GPT failed to analyze CAPTCHA")
                    return False
                
                matches = gpt_result['matches_found']
                captcha_bounds = gpt_result.get('captcha_bounds', {})
                
                debug_print(f"GPT found {len(matches)} high/medium confidence matches")
                
                if not matches:
                    debug_print("No reliable matches found by GPT")
                    
                    # בדיקה אם יש אפשרות ללחוץ על SKIP
                    if "skip" in instruction_text.lower() or "none" in instruction_text.lower():
                        debug_print("Instruction includes skip option, attempting to click SKIP button")
                        try:
                            # חיפוש כפתור SKIP
                            skip_button = driver.find_element(By.XPATH, "//button[contains(text(), 'SKIP') or contains(text(), 'Skip')]")
                            if skip_button:
                                skip_button.click()
                                debug_print("Clicked SKIP button successfully")
                                time.sleep(3)
                                
                                # בדיקה אם הכפתור submit התאפשר אחרי SKIP
                                try:
                                    submit_button = driver.find_element(By.ID, "submit")
                                    if not submit_button.get_attribute("disabled"):
                                        debug_print("Submit button enabled after SKIP")
                                        return True
                                except:
                                    pass
                        except Exception as skip_error:
                            debug_print(f"Failed to click SKIP button: {skip_error}")
                    
                    return False
                
                # חישוב קואורדינטות מתוקן - עם התאמה למסך האמיתי
                coordinates = calculate_captcha_click_coordinates_real_screen(
                    matches, captcha_bounds, window_position, selenium_size
                )
                
                debug_print("=== COORDINATE DETAILS ===")
                for i, (x, y) in enumerate(coordinates):
                    match = matches[i] if i < len(matches) else {}
                    debug_print(f"Match {i+1}: Row {match.get('row', '?')}, Col {match.get('col', '?')}")
                    debug_print(f"  -> Will click at REAL screen coordinates: ({x}, {y})")
                    debug_print(f"  -> Description: {match.get('description', 'N/A')}")
                    debug_print(f"  -> Confidence: {match.get('confidence', 'N/A')}")
                
                if coordinates:
                    # לחיצה עם pyautogui
                    debug_print("Using pyautogui for precise mouse clicks...")
                    click_on_captcha_coordinates_with_pyautogui(coordinates)
                    
                    # המתנה קצרה לפני לחיצה על VERIFY
                    debug_print("Waiting briefly before clicking VERIFY...")
                    time.sleep(2)
                    
                    try:
                        # מעבר ל-iframe של ה-CAPTCHA
                        driver.switch_to.frame(captcha_iframes[0])
                        
                        # חיפוש כפתור VERIFY עם מספר סלקטורים
                        verify_selectors = [
                            "#recaptcha-verify-button",
                            "button.rc-button-default",
                            ".rc-button-default",
                            "button[id*='verify']"
                        ]
                        
                        verify_button = None
                        for selector in verify_selectors:
                            try:
                                verify_button = driver.find_element(By.CSS_SELECTOR, selector)
                                if verify_button and verify_button.is_displayed():
                                    debug_print(f"Found VERIFY button with selector: {selector}")
                                    break
                            except:
                                continue
                        
                        if verify_button:
                            # בדיקה אם הכפתור זמין לחיצה
                            if verify_button.get_attribute("disabled"):
                                debug_print("VERIFY button is disabled, waiting...")
                                time.sleep(3)
                            
                            # לחיצה ישירה עם Selenium (הרבה יותר מהימן!)
                            debug_print("Clicking VERIFY button with Selenium")
                            verify_button.click()
                            debug_print("VERIFY button clicked successfully!")
                            
                        else:
                            debug_print("VERIFY button not found!")
                            driver.switch_to.default_content()
                            return False
                            
                        # חזרה ל-frame הראשי
                        driver.switch_to.default_content()
                        
                        # המתנה קצרה אחרי לחיצה
                        time.sleep(3)
                        
                    except Exception as verify_error:
                        debug_print(f"VERIFY button click failed: {verify_error}")
                        try:
                            driver.switch_to.default_content()
                        except:
                            pass
                        return False
                
                # בדיקה אם הCAPTCHA נפתר או שצריך לנסות שוב
                debug_print("Checking if CAPTCHA was solved successfully...")
                time.sleep(2)  # המתנה לטעינת התוצאה
                
                try:
                    # בדיקה אם יש הודעת "Please try again"
                    error_elements = driver.find_elements(By.CSS_SELECTOR, ".rc-imageselect-incorrect-response, .rc-imageselect-error-select-more, .rc-imageselect-error-dynamic-more")
                    
                    if error_elements and any(elem.is_displayed() for elem in error_elements):
                        debug_print("CAPTCHA failed - 'Please try again' message detected")
                        return False  # זה יגרום לניסיון נוסף
                    else:
                        debug_print("CAPTCHA verification completed successfully")
                        return True
                        
                except Exception as check_error:
                    debug_print(f"Error checking CAPTCHA result: {check_error}")
                    # אם לא יכולים לבדוק, נניח שזה עבר
                    debug_print("CAPTCHA verification completed (unable to verify)")
                    return True
                
            except Exception as gpt_error:
                debug_print(f"Error during GPT analysis: {gpt_error}")
                return False
        
        except Exception as iframe_error:
            debug_print(f"Error handling CAPTCHA iframe: {iframe_error}")
            try:
                driver.switch_to.default_content()
            except:
                pass
            return False
            
    except Exception as e:
        debug_print(f"General error in CAPTCHA solving: {e}")
        return False


def solve_captcha_with_audio(driver, wait_timeout=120):
    """
    פותר CAPTCHA אוטומטי באמצעות אודיו ו-Whisper transcription
    """
    import time
    import base64
    import tempfile
    import os
    import pyautogui
    import subprocess
    import requests
    import openai
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[AUDIO CAPTCHA SOLVER] {message}")
    
    try:
        debug_print("Starting CAPTCHA solving process with audio...")
        openai.api_key = os.getenv("OPENAI_API_KEY")
        
        time.sleep(3)
        
        try:
            # חיפוש iframe של CAPTCHA
            captcha_iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'bframe')]")
            
            if not captcha_iframes:
                debug_print("No CAPTCHA iframe found - checking if button is enabled")
                submit_button = driver.find_element(By.ID, "submit")
                if not submit_button.get_attribute("disabled"):
                    debug_print("Submit button is enabled - CAPTCHA already solved")
                    return True
                else:
                    debug_print("Submit button still disabled but no CAPTCHA iframe found")
                    return False
            
            debug_print(f"Found {len(captcha_iframes)} CAPTCHA iframe(s)")
            
            # מעבר ל-iframe של ה-CAPTCHA
            driver.switch_to.frame(captcha_iframes[0])
            time.sleep(2)
            
            # שלב 1: לחיצה על כפתור האודיו
            debug_print("Step 1: Looking for audio button...")
            audio_button = None
            audio_selectors = [
                "#recaptcha-audio-button",
                "button.rc-button-audio",
                ".rc-button-audio",
                "button[title*='audio']",
                "button[title*='Audio']"
            ]
            
            for selector in audio_selectors:
                try:
                    audio_button = driver.find_element(By.CSS_SELECTOR, selector)
                    if audio_button and audio_button.is_displayed():
                        debug_print(f"Found audio button with selector: {selector}")
                        break
                except:
                    continue
            
            if not audio_button:
                debug_print("Audio button not found!")
                driver.switch_to.default_content()
                return False
            
            # לחיצה על כפתור האודיו
            debug_print("Clicking audio button...")
            audio_button.click()
            time.sleep(3)
            
            # שלב 2: חיפוש כפתור PLAY
            debug_print("Step 2: Looking for PLAY button...")
            play_button = None
            play_selectors = [
                "button.rc-button-default",
                "#:2",
                "button[title='']",
                "button[aria-labelledby*='audio-instructions']",
                ".rc-button-default"
            ]
            
            for selector in play_selectors:
                try:
                    play_button = driver.find_element(By.CSS_SELECTOR, selector)
                    if play_button and play_button.is_displayed() and ("PLAY" in play_button.text or play_button.get_attribute("title") == ""):
                        debug_print(f"Found PLAY button with selector: {selector}")
                        break
                except:
                    continue
            
            if not play_button:
                debug_print("PLAY button not found!")
                driver.switch_to.default_content()
                return False
            
            # שלב 3: לחיצה על PLAY והקלטת אודיו
            debug_print("Step 3: Clicking PLAY and recording audio...")
            
            # הכנת קובץ להקלטה
            timestamp = int(time.time())
            audio_file_path = f"/Users/itaykarkason/Desktop/captcha_audio_{timestamp}.wav"
            
            # לחיצה על PLAY
            play_button.click()
            debug_print("Clicked PLAY button, starting audio recording...")
            
            # הקלטת אודיו עם SoundFlower או שיטה דומה
            # נשתמש ב-ffmpeg להקלטת האודיו מהמערכת
            try:
                # הקלטה למשך 10 שניות (בדרך כלל מספיק לCAPTCHA)
                ffmpeg_command = [
                    'ffmpeg', 
                    '-f', 'avfoundation',  # macOS audio input
                    '-i', ':0',  # מכשיר אודיו ברירת מחדל
                    '-t', '10',  # משך ההקלטה
                    '-y',  # overwrite if exists
                    audio_file_path
                ]
                
                debug_print("Starting audio recording with ffmpeg...")
                result = subprocess.run(ffmpeg_command, capture_output=True, text=True, timeout=15)
                debug_print(f"Audio recording completed. File saved to: {audio_file_path}")
                
            except subprocess.TimeoutExpired:
                debug_print("Audio recording timed out")
                return False
            except Exception as recording_error:
                debug_print(f"Error during audio recording: {recording_error}")
                # נסיון חלופי עם PyAudio אם ffmpeg לא זמין
                try:
                    import pyaudio
                    import wave
                    
                    CHUNK = 1024
                    FORMAT = pyaudio.paInt16
                    CHANNELS = 1
                    RATE = 44100
                    RECORD_SECONDS = 10
                    
                    p = pyaudio.PyAudio()
                    
                    stream = p.open(format=FORMAT,
                                    channels=CHANNELS,
                                    rate=RATE,
                                    input=True,
                                    frames_per_buffer=CHUNK)
                    
                    debug_print("Recording audio with PyAudio...")
                    frames = []
                    
                    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
                        data = stream.read(CHUNK)
                        frames.append(data)
                    
                    stream.stop_stream()
                    stream.close()
                    p.terminate()
                    
                    wf = wave.open(audio_file_path, 'wb')
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(p.get_sample_size(FORMAT))
                    wf.setframerate(RATE)
                    wf.writeframes(b''.join(frames))
                    wf.close()
                    
                    debug_print(f"Audio recorded with PyAudio: {audio_file_path}")
                    
                except ImportError:
                    debug_print("Neither ffmpeg nor PyAudio available for recording")
                    return False
                except Exception as pyaudio_error:
                    debug_print(f"PyAudio recording failed: {pyaudio_error}")
                    return False
            
            # שלב 4: Transcription עם OpenAI Whisper
            debug_print("Step 4: Transcribing audio with OpenAI Whisper...")
            
            if not os.path.exists(audio_file_path):
                debug_print(f"Audio file not found: {audio_file_path}")
                return False
            
            try:
                # שימוש בAPI הישן של OpenAI (גרסה 0.28.1)
                with open(audio_file_path, "rb") as audio_file:
                    transcript = openai.Audio.transcribe(
                        model="whisper-1",
                        file=audio_file,
                        language="en"  # CAPTCHA בדרך כלל באנגלית
                    )
                
                transcribed_text = transcript.text.strip()
                
                # הדפסת הטקסט במסוף כמו שביקשת
                print(f"\n🎯 [AUDIO TRANSCRIPTION] הטקסט שנשמע: '{transcribed_text}' 🎯\n")
                debug_print(f"Transcribed text: '{transcribed_text}'")
                
                if not transcribed_text:
                    debug_print("No text transcribed from audio")
                    return False
                
            except Exception as transcription_error:
                debug_print(f"Error during transcription: {transcription_error}")
                return False
            finally:
                # ניקוי קובץ האודיו
                if os.path.exists(audio_file_path):
                    os.remove(audio_file_path)
                    debug_print("Audio file cleaned up")
            
            # שלב 5: הקלדת הטקסט ולחיצה על VERIFY
            debug_print("Step 5: Entering transcribed text and clicking VERIFY...")
            
            # חיפוש שדה הקלט
            input_field = None
            input_selectors = [
                "#audio-response",
                "input[id*='audio']",
                "input.rc-audiochallenge-response-field",
                ".rc-audiochallenge-response-field"
            ]
            
            for selector in input_selectors:
                try:
                    input_field = driver.find_element(By.CSS_SELECTOR, selector)
                    if input_field and input_field.is_displayed():
                        debug_print(f"Found input field with selector: {selector}")
                        break
                except:
                    continue
            
            if not input_field:
                debug_print("Audio input field not found!")
                driver.switch_to.default_content()
                return False
            
            # הקלדת הטקסט
            input_field.clear()
            input_field.send_keys(transcribed_text)
            debug_print(f"Entered text: '{transcribed_text}'")
            time.sleep(1)
            
            # חיפוש כפתור VERIFY
            verify_button = None
            verify_selectors = [
                "#recaptcha-verify-button",
                "button.rc-button-default",
                ".rc-button-default",
                "button[id*='verify']"
            ]
            
            for selector in verify_selectors:
                try:
                    verify_button = driver.find_element(By.CSS_SELECTOR, selector)
                    if verify_button and verify_button.is_displayed():
                        debug_print(f"Found VERIFY button with selector: {selector}")
                        break
                except:
                    continue
            
            if not verify_button:
                debug_print("VERIFY button not found!")
                driver.switch_to.default_content()
                return False
            
            # לחיצה על VERIFY
            debug_print("Clicking VERIFY button...")
            verify_button.click()
            debug_print("VERIFY button clicked successfully!")
            
            # חזרה ל-frame הראשי
            driver.switch_to.default_content()
            
            # המתנה קצרה אחרי לחיצה
            time.sleep(3)
            
            # לולאה לטיפול ב-"Multiple correct solutions required"
            max_attempts = 5  # מקסימום 5 ניסיונות נוספים
            current_attempt = 1
            
            while current_attempt <= max_attempts:
                # בדיקה אם הCAPTCHA נפתר
                debug_print(f"Checking CAPTCHA result (attempt {current_attempt}/{max_attempts})...")
                time.sleep(3)
                
                try:
                    # בדיקה אם יש הודעת שגיאה או דרישה לפתרונות נוספים
                    driver.switch_to.frame(captcha_iframes[0])
                    error_elements = driver.find_elements(By.CSS_SELECTOR, ".rc-audiochallenge-error-message")
                    
                    error_message = ""
                    if error_elements:
                        for elem in error_elements:
                            if elem.is_displayed() and elem.text.strip():
                                error_message = elem.text.strip()
                                break
                    
                    if error_message:
                        debug_print(f"CAPTCHA message: {error_message}")
                        print(f"\n⚠️ [CAPTCHA STATUS] {error_message} ⚠️\n")
                        
                        # אם זה "Multiple correct solutions required" - ממשיך לניסיון הבא
                        if "multiple correct solutions required" in error_message.lower() or "solve more" in error_message.lower():
                            debug_print("Need to solve more audio challenges...")
                            print(f"\n🔄 [CAPTCHA] צריך לפתור עוד - מתחיל ניסיון {current_attempt + 1} 🔄\n")
                            
                            # חיפוש כפתור PLAY חדש
                            time.sleep(2)
                            play_button = None
                            for selector in play_selectors:
                                try:
                                    play_button = driver.find_element(By.CSS_SELECTOR, selector)
                                    if play_button and play_button.is_displayed():
                                        debug_print(f"Found new PLAY button with selector: {selector}")
                                        break
                                except:
                                    continue
                            
                            if not play_button:
                                debug_print("New PLAY button not found!")
                                driver.switch_to.default_content()
                                return False
                            
                            # חזרה לתהליך ההקלטה והתמלול
                            timestamp = int(time.time())
                            audio_file_path = f"/Users/itaykarkason/Desktop/captcha_audio_{timestamp}.wav"
                            
                            # לחיצה על PLAY החדש
                            play_button.click()
                            debug_print(f"Clicked new PLAY button (attempt {current_attempt + 1}), starting audio recording...")
                            
                            # הקלטת אודיו נוספת
                            try:
                                ffmpeg_command = [
                                    'ffmpeg', 
                                    '-f', 'avfoundation',
                                    '-i', ':0',
                                    '-t', '10',
                                    '-y',
                                    audio_file_path
                                ]
                                
                                debug_print(f"Starting additional audio recording with ffmpeg...")
                                result = subprocess.run(ffmpeg_command, capture_output=True, text=True, timeout=15)
                                debug_print(f"Additional audio recording completed. File saved to: {audio_file_path}")
                                
                            except Exception as recording_error:
                                debug_print(f"Error during additional audio recording: {recording_error}")
                                # נסיון חלופי עם PyAudio
                                try:
                                    import pyaudio
                                    import wave
                                    
                                    CHUNK = 1024
                                    FORMAT = pyaudio.paInt16
                                    CHANNELS = 1
                                    RATE = 44100
                                    RECORD_SECONDS = 10
                                    
                                    p = pyaudio.PyAudio()
                                    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
                                    
                                    debug_print(f"Recording additional audio with PyAudio...")
                                    frames = []
                                    
                                    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
                                        data = stream.read(CHUNK)
                                        frames.append(data)
                                    
                                    stream.stop_stream()
                                    stream.close()
                                    p.terminate()
                                    
                                    wf = wave.open(audio_file_path, 'wb')
                                    wf.setnchannels(CHANNELS)
                                    wf.setsampwidth(p.get_sample_size(FORMAT))
                                    wf.setframerate(RATE)
                                    wf.writeframes(b''.join(frames))
                                    wf.close()
                                    
                                    debug_print(f"Additional audio recorded with PyAudio: {audio_file_path}")
                                    
                                except Exception as pyaudio_error:
                                    debug_print(f"PyAudio additional recording failed: {pyaudio_error}")
                                    return False
                            
                            # תמלול נוסף
                            if os.path.exists(audio_file_path):
                                try:
                                    with open(audio_file_path, "rb") as audio_file:
                                        transcript = openai.Audio.transcribe(
                                            model="whisper-1",
                                            file=audio_file,
                                            language="en"
                                        )
                                    
                                    transcribed_text = transcript.text.strip()
                                    
                                    print(f"\n🎯 [ADDITIONAL AUDIO TRANSCRIPTION #{current_attempt + 1}] הטקסט שנשמע: '{transcribed_text}' 🎯\n")
                                    debug_print(f"Additional transcribed text: '{transcribed_text}'")
                                    
                                    if transcribed_text:
                                        # הקלדת הטקסט החדש
                                        for selector in input_selectors:
                                            try:
                                                input_field = driver.find_element(By.CSS_SELECTOR, selector)
                                                if input_field and input_field.is_displayed():
                                                    input_field.clear()
                                                    input_field.send_keys(transcribed_text)
                                                    debug_print(f"Entered additional text: '{transcribed_text}'")
                                                    break
                                            except:
                                                continue
                                        
                                        time.sleep(1)
                                        
                                        # לחיצה על VERIFY שוב
                                        for selector in verify_selectors:
                                            try:
                                                verify_button = driver.find_element(By.CSS_SELECTOR, selector)
                                                if verify_button and verify_button.is_displayed():
                                                    debug_print(f"Clicking VERIFY button again (attempt {current_attempt + 1})...")
                                                    verify_button.click()
                                                    debug_print(f"VERIFY button clicked again successfully!")
                                                    break
                                            except:
                                                continue
                                        
                                        time.sleep(3)
                                        current_attempt += 1
                                    else:
                                        debug_print("No additional text transcribed from audio")
                                        return False
                                        
                                except Exception as additional_transcription_error:
                                    debug_print(f"Error during additional transcription: {additional_transcription_error}")
                                    return False
                                finally:
                                    # ניקוי קובץ האודיו הנוסף
                                    if os.path.exists(audio_file_path):
                                        os.remove(audio_file_path)
                                        debug_print("Additional audio file cleaned up")
                            else:
                                debug_print("Additional audio file not found")
                                return False
                        else:
                            # שגיאה אחרת - לא "Multiple correct solutions"
                            debug_print("CAPTCHA failed with different error")
                            driver.switch_to.default_content()
                            return False
                    else:
                        # אין הודעת שגיאה - הCAPTCHA הצליח!
                        debug_print("Audio CAPTCHA verification completed successfully")
                        print(f"\n✅ [CAPTCHA SUCCESS] CAPTCHA נפתר בהצלחה! ✅\n")
                        driver.switch_to.default_content()
                        return True
                        
                except Exception as check_error:
                    debug_print(f"Error checking CAPTCHA result: {check_error}")
                    try:
                        driver.switch_to.default_content()
                    except:
                        pass
                    debug_print("Audio CAPTCHA verification completed (unable to verify)")
                    return True
            
            # אם הגענו עד כאן - עברנו את המקסימום ניסיונות
            debug_print(f"Maximum attempts ({max_attempts}) reached for multiple solutions")
            try:
                driver.switch_to.default_content()
            except:
                pass
            return False
        
        except Exception as iframe_error:
            debug_print(f"Error handling CAPTCHA iframe: {iframe_error}")
            try:
                driver.switch_to.default_content()
            except:
                pass
            return False
            
    except Exception as e:
        debug_print(f"General error in audio CAPTCHA solving: {e}")
        return False


def solve_captcha_with_capsolver(driver, wait_timeout=120, instruction_text=""):
    """
    פותר CAPTCHA אוטומטי באמצעות Capsolver API
    מזהה reCAPTCHA תמונות ושולח ל-API לפתרון
    """
    import time
    import base64
    import tempfile
    import os
    import requests
    import subprocess
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[CAPSOLVER] {message}")
    
    try:
        debug_print("Starting CAPTCHA solving process with Capsolver API...")
        
        # קבלת פרטי ה-API מהסביבה
        capsolver_api_key = os.getenv("CAPSOLVER_API_KEY")
        
        if not capsolver_api_key:
            debug_print("Capsolver API key not found in environment variables")
            return False
        
        debug_print(f"Using Capsolver API key: {capsolver_api_key[:8]}...")
        
        time.sleep(3)
        
        try:
            # חיפוש iframe של CAPTCHA
            captcha_iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'bframe')]")
            
            if not captcha_iframes:
                debug_print("No CAPTCHA iframe found - checking if button is enabled")
                submit_button = driver.find_element(By.ID, "submit")
                if not submit_button.get_attribute("disabled"):
                    debug_print("Submit button is enabled - CAPTCHA already solved")
                    return True
                else:
                    debug_print("Submit button still disabled but no CAPTCHA iframe found")
                    return False
            
            debug_print(f"Found {len(captcha_iframes)} CAPTCHA iframe(s)")
            
            # חזרה ל-frame הראשי לצילום מסך
            driver.switch_to.default_content()
            
            # צילום מסך מלא של הדפדפן
            timestamp = int(time.time())
            screenshot_path = f"/Users/itaykarkason/Desktop/truecaptcha_screenshot_{timestamp}.png"
            
            debug_print("Taking CAPTCHA screenshot for TrueCaptcha API...")
            try:
                # שימוש בפקודת screencapture של macOS
                subprocess.run(['screencapture', screenshot_path], check=True)
                debug_print(f"Screenshot saved to: {screenshot_path}")
            except Exception as e:
                debug_print(f"Failed to take screenshot: {e}")
                return False
            
            # הכנת התמונה לשליחה ל-API (עם דחיסה)
            debug_print("Compressing and encoding image for TrueCaptcha API...")
            try:
                from PIL import Image
                import io
                import pyautogui
                
                # פתיחת התמונה ודחיסה
                with Image.open(screenshot_path) as img:
                    # המרה ל-RGB אם צריך
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # גיזום לאזור CAPTCHA בלבד - חיתוך קטן וממוקד יותר
                    screen_size = pyautogui.size()
                    width, height = img.size
                    
                    # מיקום CAPTCHA מותאם למסך - חיתוך קטן יותר
                    if width >= 1440:  # מסך גדול
                        captcha_left = width // 2 - 180
                        captcha_top = height // 2 - 120  
                        captcha_right = width // 2 + 180
                        captcha_bottom = height // 2 + 180
                    else:  # מסך קטן יותר
                        captcha_left = width // 2 - 150
                        captcha_top = height // 2 - 100
                        captcha_right = width // 2 + 150
                        captcha_bottom = height // 2 + 150
                    
                    # וידוא שהחיתוך בגבולות התמונה
                    captcha_left = max(0, captcha_left)
                    captcha_top = max(0, captcha_top) 
                    captcha_right = min(width, captcha_right)
                    captcha_bottom = min(height, captcha_bottom)
                    
                    debug_print(f"Screen size: {screen_size}, Image size: {width}x{height}")
                    debug_print(f"CAPTCHA crop area: ({captcha_left}, {captcha_top}) to ({captcha_right}, {captcha_bottom})")
                    
                    # חיתוך לאזור CAPTCHA
                    img_cropped = img.crop((captcha_left, captcha_top, captcha_right, captcha_bottom))
                    debug_print(f"Cropped image to CAPTCHA area: {img_cropped.size}")
                    
                    # הקטנת תמונה לגודל קטן יותר לפני דחיסה
                    max_width = 300
                    max_height = 300
                    img_cropped.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                    debug_print(f"Resized image to: {img_cropped.size}")
                    
                    # שמירה זמנית עם דחיסה חזקה
                    buffer = io.BytesIO()
                    img_cropped.save(buffer, format='JPEG', quality=40, optimize=True)
                    
                    # בדיקת גודל והקטנה נוספת אם צריך
                    buffer_size = len(buffer.getvalue())
                    debug_print(f"Compressed image size: {buffer_size} bytes")
                    
                    if buffer_size > 20000:  # 20KB limit
                        debug_print("Image still too large, compressing to maximum...")
                        # הקטנה עוד יותר
                        img_cropped.thumbnail((200, 200), Image.Resampling.LANCZOS)
                        buffer = io.BytesIO()
                        img_cropped.save(buffer, format='JPEG', quality=30, optimize=True)
                        buffer_size = len(buffer.getvalue())
                        debug_print(f"Maximum compressed image size: {buffer_size} bytes")
                    
                    # קידוד ל-base64
                    base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    debug_print(f"Image encoded successfully (base64 size: {len(base64_image)} chars, file size: {buffer_size} bytes)")
                
            except Exception as e:
                debug_print(f"Failed to compress/encode image: {e}")
                # אם הדחיסה נכשלה, ננסה עם התמונה המקורית
                try:
                    with open(screenshot_path, "rb") as image_file:
                        base64_image = base64.b64encode(image_file.read()).decode('utf-8')
                    debug_print(f"Using original image (size: {len(base64_image)} chars)")
                except:
                    debug_print("Failed to read original image")
                    return False
            
            # שליחת הבקשה ל-TrueCaptcha API
            debug_print("Sending request to TrueCaptcha API...")
            api_url = "https://api.apitruecaptcha.org/one/gettext"
            
            api_payload = {
                "userid": truecaptcha_userid,
                "apikey": truecaptcha_api_key,
                "data": base64_image,
                "tag": "multipass_captcha",
                "case": "mixed"
            }
            
            try:
                debug_print("Making API request...")
                response = requests.post(api_url, json=api_payload, timeout=30)
                debug_print(f"API Response Status: {response.status_code}")
                debug_print(f"API Response Headers: {dict(response.headers)}")
                
                if response.status_code == 200:
                    result = response.json()
                    debug_print(f"API Response JSON: {result}")
                    
                    if "result" in result:
                        captcha_text = result["result"].strip()
                        debug_print(f"✅ CAPTCHA text detected: '{captcha_text}'")
                        print(f"\n🤖 [TRUECAPTCHA] זוהה טקסט CAPTCHA: '{captcha_text}' 🤖\n")
                        
                        # מעבר ל-iframe של ה-CAPTCHA להקלדת התוצאה
                        driver.switch_to.frame(captcha_iframes[0])
                        time.sleep(2)
                        
                        # חיפוש שדה הקלט של ה-CAPTCHA
                        input_selectors = [
                            "#audio-response",
                            ".rc-audiochallenge-response-field",
                            "input[name='audio_response']",
                            "input[type='text']"
                        ]
                        
                        input_field = None
                        for selector in input_selectors:
                            try:
                                input_field = driver.find_element(By.CSS_SELECTOR, selector)
                                if input_field and input_field.is_displayed():
                                    debug_print(f"Found input field with selector: {selector}")
                                    break
                            except:
                                continue
                        
                        if input_field:
                            # הקלדת הטקסט שזוהה
                            input_field.clear()
                            input_field.send_keys(captcha_text)
                            debug_print(f"Entered CAPTCHA text: '{captcha_text}'")
                            time.sleep(1)
                            
                            # חיפוש כפתור VERIFY
                            verify_button = None
                            verify_selectors = [
                                "#recaptcha-verify-button",
                                "button.rc-button-default",
                                ".rc-button-default",
                                "button[id*='verify']"
                            ]
                            
                            for selector in verify_selectors:
                                try:
                                    verify_button = driver.find_element(By.CSS_SELECTOR, selector)
                                    if verify_button and verify_button.is_displayed():
                                        debug_print(f"Found verify button with selector: {selector}")
                                        break
                                except:
                                    continue
                            
                            if verify_button:
                                verify_button.click()
                                debug_print("Clicked VERIFY button")
                                time.sleep(3)
                                
                                # בדיקה אם הCAPTCHA נפתר
                                driver.switch_to.default_content()
                                debug_print("Checking if CAPTCHA was solved successfully...")
                                
                                try:
                                    submit_button = driver.find_element(By.ID, "submit")
                                    if not submit_button.get_attribute("disabled"):
                                        debug_print("✅ CAPTCHA solved successfully with TrueCaptcha!")
                                        print(f"\n🎉 [SUCCESS] CAPTCHA נפתר בהצלחה עם TrueCaptcha! 🎉\n")
                                        return True
                                    else:
                                        debug_print("❌ CAPTCHA verification failed")
                                        print(f"\n❌ [FAILED] פתרון CAPTCHA נכשל ❌\n")
                                        return False
                                except Exception as check_error:
                                    debug_print(f"Error checking CAPTCHA result: {check_error}")
                                    return False
                            else:
                                debug_print("Could not find VERIFY button")
                                driver.switch_to.default_content()
                                return False
                        else:
                            debug_print("Could not find CAPTCHA input field")
                            driver.switch_to.default_content()
                            return False
                    else:
                        debug_print(f"No 'result' field in API response: {result}")
                        return False
                else:
                    debug_print(f"API request failed with status {response.status_code}")
                    debug_print(f"Response text: {response.text}")
                    return False
                    
            except requests.exceptions.RequestException as e:
                debug_print(f"Request error: {e}")
                return False
            except Exception as e:
                debug_print(f"Error processing API response: {e}")
                return False
            
        except Exception as iframe_error:
            debug_print(f"Error handling CAPTCHA iframe: {iframe_error}")
            try:
                driver.switch_to.default_content()
            except:
                pass
            return False
            
    except Exception as e:
        debug_print(f"General error in TrueCaptcha solving: {e}")
        return False


def solve_captcha_with_capsolver_new(driver, wait_timeout=120, instruction_text=""):
    """
    פותר CAPTCHA אוטומטי באמצעות Capsolver API
    מזהה reCAPTCHA תמונות ושולח ל-API לפתרון
    """
    import time
    import base64
    import os
    import requests
    import subprocess
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[CAPSOLVER] {message}")
    
    def extract_question_from_instruction(instruction_text):
        """חילוץ סוג האובייקט מההוראה של reCAPTCHA"""
        instruction_lower = instruction_text.lower()
        
        # מיפוי ההוראות לקודי Capsolver (לפי הדוקומנטציה הרשמית)
        question_mapping = {
            "crosswalks": "/m/014xcs",
            "traffic lights": "/m/015qff", 
            "bicycles": "/m/0199g",
            "cars": "/m/0k4j",
            "motorcycles": "/m/04_sv",
            "buses": "/m/01bjv",
            "bus": "/m/01bjv",
            "school bus": "/m/02yvhj",
            "taxis": "/m/0pg52",
            "tractors": "/m/013xlm",
            "bridges": "/m/015kr",
            "boats": "/m/019jd",
            "fire hydrants": "/m/01pns0",
            "fire hydrant": "/m/01pns0",
            "parking meters": "/m/015qbp",
            "stairs": "/m/01lynh",
            "chimneys": "/m/01jk_4",
            "palm trees": "/m/0cdl1",
            "mountains": "/m/09d_r",
            "hills": "/m/09d_r"
        }
        
        for key, value in question_mapping.items():
            if key in instruction_lower:
                debug_print(f"Matched '{key}' to code '{value}'")
                return value
        
        # ברירת מחדל - נחזיר את המילה הראשונה אחרי "with"
        words = instruction_lower.split()
        try:
            with_index = words.index("with")
            if with_index + 1 < len(words):
                return words[with_index + 1].rstrip('s')  # הסרת s בסוף
        except ValueError:
            pass
        
        return "/m/0k4j"  # ברירת מחדל - cars
    
    try:
        debug_print("Starting CAPTCHA solving process with Capsolver API...")
        
        # קבלת פרטי ה-API מהסביבה
        capsolver_api_key = os.getenv("CAPSOLVER_API_KEY")
        
        if not capsolver_api_key:
            debug_print("Capsolver API key not found in environment variables")
            return False
        
        debug_print(f"Using Capsolver API key: {capsolver_api_key[:8]}...")
        debug_print(f"Instruction text: '{instruction_text}'")
        
        # חילוץ סוג האובייקט מההוראה
        question = extract_question_from_instruction(instruction_text)
        debug_print(f"Extracted question for Capsolver: '{question}'")
        
        # הכנת רשימת קודים אלטרנטיביים לניסיון
        alternative_questions = []
        if question == "/m/01bjv":  # buses
            alternative_questions = ["/m/02yvhj"]  # school bus
            debug_print(f"Will also try alternatives: {alternative_questions}")
        elif question == "/m/0k4j":  # cars  
            alternative_questions = ["/m/0199g"]  # bicycles - לפעמים מתבלבל
            debug_print(f"Will also try alternatives: {alternative_questions}")
        
        all_questions = [question] + alternative_questions
        
        time.sleep(3)
        
        # חיפוש iframe של CAPTCHA
        captcha_iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'bframe')]")
        
        if not captcha_iframes:
            debug_print("No CAPTCHA iframe found - checking if button is enabled")
            submit_button = driver.find_element(By.ID, "submit")
            if not submit_button.get_attribute("disabled"):
                debug_print("Submit button is enabled - CAPTCHA already solved")
                return True
            else:
                debug_print("Submit button still disabled but no CAPTCHA iframe found")
                return False
        
        debug_print(f"Found {len(captcha_iframes)} CAPTCHA iframe(s)")
        
        # מעבר ל-iframe של CAPTCHA לצילום ישיר
        driver.switch_to.frame(captcha_iframes[0])
        time.sleep(2)
        
        debug_print("Taking direct screenshot of CAPTCHA iframe...")
        timestamp = int(time.time())
        
        try:
            from PIL import Image
            import io
            
            # צילום מסך ישיר של האלמנט CAPTCHA
            captcha_element = driver.find_element(By.CSS_SELECTOR, ".rc-imageselect-table, .rc-imageselect-challenge")
            if not captcha_element:
                captcha_element = driver.find_element(By.TAG_NAME, "body")
            
            # צילום מסך של האלמנט הספציפי
            screenshot_bytes = captcha_element.screenshot_as_png
            
            # שמירת התמונה המקורית לבדיקה
            screenshot_path = f"/Users/itaykarkason/Desktop/capsolver_screenshot_{timestamp}.png"
            with open(screenshot_path, "wb") as f:
                f.write(screenshot_bytes)
            debug_print(f"Direct CAPTCHA screenshot saved to: {screenshot_path}")
            
            # טעינת התמונה לעיבוד
            img = Image.open(io.BytesIO(screenshot_bytes))
            
            # המרה ל-RGB אם צריך
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            debug_print(f"CAPTCHA image size: {img.size}")
            
            # שמירה בפורמט JPEG
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=90, optimize=True)
            
            # שמירת התמונה העובדת לבדיקה
            processed_debug_path = f"/Users/itaykarkason/Desktop/capsolver_processed_debug_{timestamp}.png"
            img.save(processed_debug_path)
            debug_print(f"Processed image saved for debugging: {processed_debug_path}")
            
            # קידוד ל-base64
            base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
            debug_print(f"Image encoded successfully (base64 size: {len(base64_image)} chars)")
            
            # בדיקה נוספת - אורך בייטים ראשונים של base64
            debug_print(f"Base64 starts with: {base64_image[:50]}...")
            debug_print(f"Image dimensions after processing: {img.size}")
            
            # וידוא שהתמונה לא ריקה
            if len(base64_image) < 1000:
                debug_print("❌ Base64 image too small - possibly empty!")
                return False
            
        except Exception as e:
            debug_print(f"Failed to process image: {e}")
            return False
        
        # חזרה ל-frame הראשי לפני שליחת API
        driver.switch_to.default_content()
        
        # שליחת הבקשה ל-Capsolver API
        debug_print("Sending request to Capsolver API...")
        api_url = "https://api.capsolver.com/createTask"
        
        def try_capsolver_request(question_code):
            """מנסה בקשה לCapsolver עם קוד שאלה מסוים"""
            payload = {
                "clientKey": capsolver_api_key,
                "task": {
                    "type": "ReCaptchaV2Classification",
                    "websiteURL": "https://multipass.co.il",  # הוספת URL לדיוק טוב יותר
                    "image": base64_image,
                    "question": question_code
                }
            }
            debug_print(f"Trying question code: {question_code}")
            debug_print(f"Payload structure: clientKey={capsolver_api_key[:8]}..., task type={payload['task']['type']}")
            debug_print(f"Image size in payload: {len(base64_image)} chars")
            return requests.post(api_url, json=payload, timeout=30)
        
        # ניסיון עם כל הקודים ברצף
        for i, current_question in enumerate(all_questions):
            debug_print(f"Attempt {i+1}/{len(all_questions)} with question: {current_question}")
            response = try_capsolver_request(current_question)
            
            try:
                debug_print("Making API request...")
                debug_print(f"API Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    debug_print(f"API Response JSON: {result}")
                    
                    # דיבוג מפורט של התשובה
                    debug_print(f"Response keys: {list(result.keys())}")
                    debug_print(f"ErrorId: {result.get('errorId')}")
                    debug_print(f"Status: {result.get('status')}")
                    debug_print(f"TaskId: {result.get('taskId')}")
                    
                    if result.get('errorId') == 0 and 'solution' in result:
                        solution = result['solution']
                        debug_print(f"Solution received: {solution}")
                        debug_print(f"Solution keys: {list(solution.keys()) if isinstance(solution, dict) else 'Not a dict'}")
                        
                        # בדיקת שני סוגי תגובות: multi-object ו-single object
                        click_coordinates = []
                        
                        if 'objects' in solution and solution['objects']:
                            # Multi-object response - מערך של מספרים
                            click_coordinates = solution['objects']
                            debug_print(f"✅ Multi-object CAPTCHA solution: {click_coordinates}")
                            print(f"\n🤖 [CAPSOLVER] זוהו תמונות לקליקה: {click_coordinates} 🤖\n")
                            return perform_captcha_clicks(driver, captcha_iframes, click_coordinates)
                        elif solution.get('hasObject') == True:
                            # Single object response - צריך למצוא איפה האובייקט
                            debug_print("✅ Single object detected, but need to determine location")
                            debug_print("Single object mode not yet implemented")
                            continue  # נמשיך לקוד הבא
                        elif solution.get('hasObject') == False:
                            debug_print(f"❌ No objects found with question: {current_question}")
                            continue  # נמשיך לקוד הבא
                        else:
                            debug_print("❓ Unknown solution format")
                            debug_print(f"Solution details: {solution}")
                            continue
                    else:
                        debug_print(f"API returned error: {result}")
                        continue
                else:
                    debug_print(f"API request failed with status {response.status_code}")
                    debug_print(f"Response text: {response.text}")
                    continue
                    
            except requests.exceptions.RequestException as e:
                debug_print(f"Request error with question {current_question}: {e}")
                continue
            except Exception as e:
                debug_print(f"Error processing response for question {current_question}: {e}")
                continue
        
        # אם הגענו לכאן, כל הניסיונות נכשלו
        debug_print("❌ All Capsolver attempts failed")
        return False
            
    except Exception as e:
        debug_print(f"General error in Capsolver solving: {e}")
        return False


def solve_captcha_with_capsolver_improved(driver, wait_timeout=120, instruction_text=""):
    """
    פונקציה משופרת לפתרון CAPTCHA עם Capsolver API - גישות מרובות
    """
    import time
    import base64
    import os
    import requests
    import subprocess
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[CAPSOLVER IMPROVED] {message}")
    
    def extract_question_from_instruction(instruction_text):
        """חילוץ סוג האובייקט מההוראה של reCAPTCHA באמצעות GPT"""
        debug_print(f"GPT analyzing: '{instruction_text}'")
        
        try:
            # ייבוא נכון של OpenAI
            import openai
            if hasattr(openai, 'OpenAI'):
                from openai import OpenAI
            else:
                # גרסה ישנה של openai
                OpenAI = openai.OpenAI
            
            # בדיקת API key
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                debug_print("OpenAI API key not found, falling back to static mapping")
                return extract_question_static(instruction_text)
            
            client = OpenAI(api_key=openai_api_key, timeout=10.0)  # 10 second timeout
            
            prompt = f"""
reCAPTCHA instruction: "{instruction_text}"

Return the best Capsolver code:
/m/01bjv=bus /m/02yvhj=school_bus /m/0k4j=car /m/0199g=bicycle /m/04_sv=motorcycle 
/m/015qff=traffic_light /m/01pns0=fire_hydrant /m/014xcs=crosswalk /m/0pg52=taxi
/m/013xlm=tractor /m/015kr=bridge /m/07yv9=boat /m/01x3z=building /m/0cvnqh=stairs

Return ONLY the code (e.g., /m/0k4j). If unsure, return /m/0k4j.
"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=15,
                temperature=0,
                timeout=10  # 10 second timeout for the request
            )
            
            code = response.choices[0].message.content.strip()
            debug_print(f"GPT suggested: {code}")
            
            if code.startswith('/m/'):
                return code
            else:
                debug_print("Invalid GPT response, using static fallback")
                return extract_question_static(instruction_text)
                
        except Exception as e:
            debug_print(f"GPT failed: {e}, using static fallback")
            return extract_question_static(instruction_text)

    def get_recaptcha_site_key(driver):
        """מוצא את ה-site key של ReCaptcha"""
        try:
            # חיפוש site key בדף
            scripts = driver.find_elements(By.TAG_NAME, "script")
            for script in scripts:
                script_content = script.get_attribute("innerHTML") or ""
                if "data-sitekey" in script_content or "sitekey" in script_content:
                    # חיפוש regex של site key
                    import re
                    match = re.search(r'sitekey["\']?\s*[:\=]\s*["\']([^"\']+)["\']', script_content, re.IGNORECASE)
                    if match:
                        return match.group(1)
            
            # חיפוש בiframes
            iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha')]")
            for iframe in iframes:
                src = iframe.get_attribute("src")
                if "k=" in src:
                    import re
                    match = re.search(r'k=([^&]+)', src)
                    if match:
                        return match.group(1)
            
            debug_print("Could not find reCaptcha site key")
            return None
        except Exception as e:
            debug_print(f"Error finding site key: {e}")
            return None

    def wait_for_capsolver_result(api_url, api_key, task_id, driver, max_wait=60):
        """ממתין לתוצאת משימה אסינכרונית מCapsolver"""
        import time
        
        debug_print(f"Waiting for task {task_id} to complete...")
        
        for i in range(max_wait):
            try:
                time.sleep(2)  # המתנה של 2 שניות
                
                payload = {
                    "clientKey": api_key,
                    "taskId": task_id
                }
                
                response = requests.post(api_url.replace("createTask", "getTaskResult"), json=payload, timeout=10)
                
                if response.status_code == 200:
                    result = response.json()
                    debug_print(f"Task status check: {result}")
                    
                    if result.get('status') == 'ready':
                        solution = result.get('solution', {})
                        if 'gRecaptchaResponse' in solution:
                            debug_print("✅ Async task completed successfully!")
                            debug_print(f"🎯 Capsolver analyzed and solved: '{instruction_text}' challenge")
                            debug_print(f"📝 Full solution means Capsolver handled all image selection automatically")
                            debug_print(f"🔑 Final token: ...{solution['gRecaptchaResponse'][-20:]} (last 20 chars)")
                            return submit_recaptcha_response(driver, solution['gRecaptchaResponse'])
                    elif result.get('status') == 'processing':
                        debug_print(f"Task still processing... ({i+1}/{max_wait})")
                        continue
                    else:
                        debug_print(f"Task failed: {result}")
                        return False
                        
            except Exception as e:
                debug_print(f"Error checking task status: {e}")
                
        debug_print("Task timeout - taking too long")
        return False

    def submit_recaptcha_response(driver, g_recaptcha_response):
        """שולח את תשובת ReCaptcha לדף בשיטות מרובות"""
        try:
            debug_print("🔑 Submitting ReCaptcha response token...")
            debug_print(f"Token preview: {g_recaptcha_response[:50]}...{g_recaptcha_response[-20:]}")
            
            # שיטה 1: הזנת הטוקן לtextarea הסמויה
            debug_print("Method 1: Injecting token into g-recaptcha-response textarea")
            
            # מציאת ועדכון כל ה-textareas
            textareas_updated = 0
            
            # חיפוש לפי ID
            try:
                textarea_id = driver.find_element(By.ID, "g-recaptcha-response")
                driver.execute_script("arguments[0].style.display = 'block';", textarea_id)
                driver.execute_script("arguments[0].innerHTML = arguments[1];", textarea_id, g_recaptcha_response)
                driver.execute_script("arguments[0].value = arguments[1];", textarea_id, g_recaptcha_response)
                textareas_updated += 1
                debug_print("✅ Updated textarea by ID")
            except:
                debug_print("❌ No textarea found by ID")
            
            # חיפוש לפי NAME
            textareas_name = driver.find_elements(By.NAME, "g-recaptcha-response")
            for textarea in textareas_name:
                try:
                    driver.execute_script("arguments[0].style.display = 'block';", textarea)
                    driver.execute_script("arguments[0].innerHTML = arguments[1];", textarea, g_recaptcha_response)
                    driver.execute_script("arguments[0].value = arguments[1];", textarea, g_recaptcha_response)
                    textareas_updated += 1
                    debug_print("✅ Updated textarea by NAME")
                except:
                    pass
            
            debug_print(f"📝 Updated {textareas_updated} textarea(s)")
            
            # שיטה 2: הפעלת callback functions
            debug_print("Method 2: Triggering reCAPTCHA callback functions")
            
            # ניסיון מספר שיטות callback
            callback_methods = [
                # שיטה סטנדרטית
                f"___grecaptcha_cfg.clients[0].O.O.callback('{g_recaptcha_response}');",
                # שיטות אלטרנטיביות
                f"___grecaptcha_cfg.clients[0].callback('{g_recaptcha_response}');",
                f"___grecaptcha_cfg.clients[0].L.L.callback('{g_recaptcha_response}');",
                f"___grecaptcha_cfg.clients[0].M.M.callback('{g_recaptcha_response}');",
                f"___grecaptcha_cfg.clients[0].N.N.callback('{g_recaptcha_response}');",
                f"___grecaptcha_cfg.clients[0].P.P.callback('{g_recaptcha_response}');",
                # חיפוש אוטומטי של callback
                """
                try {
                    if (window.___grecaptcha_cfg && ___grecaptcha_cfg.clients) {
                        for (let client in ___grecaptcha_cfg.clients) {
                            for (let prop in ___grecaptcha_cfg.clients[client]) {
                                if (___grecaptcha_cfg.clients[client][prop] && 
                                    ___grecaptcha_cfg.clients[client][prop][prop] && 
                                    ___grecaptcha_cfg.clients[client][prop][prop].callback) {
                                    ___grecaptcha_cfg.clients[client][prop][prop].callback(arguments[0]);
                                    console.log('Callback triggered via', prop);
                                    return true;
                                }
                            }
                        }
                    }
                } catch(e) { console.log('Callback error:', e); }
                """
            ]
            
            callbacks_triggered = 0
            for method in callback_methods[:-1]:  # כל השיטות מלבד האחרונה
                try:
                    driver.execute_script(method)
                    callbacks_triggered += 1
                    debug_print(f"✅ Callback method {callbacks_triggered} executed")
                except Exception as e:
                    debug_print(f"❌ Callback method {callbacks_triggered + 1} failed: {str(e)[:50]}...")
            
            # הרצת השיטה האחרונה (חיפוש אוטומטי) עם הטוקן
            try:
                result = driver.execute_script(callback_methods[-1], g_recaptcha_response)
                if result:
                    callbacks_triggered += 1
                    debug_print("✅ Auto-discovery callback executed")
            except Exception as e:
                debug_print(f"❌ Auto-discovery callback failed: {str(e)[:50]}...")
            
            debug_print(f"🔄 Triggered {callbacks_triggered} callback method(s)")
            
            # שיטה 3: עדכון grecaptcha response ישירות
            debug_print("Method 3: Direct grecaptcha response update")
            try:
                driver.execute_script(f"""
                    if (window.grecaptcha) {{
                        window.grecaptcha.enterprise = window.grecaptcha.enterprise || {{}};
                        window.grecaptcha.enterprise.getResponse = function() {{ return '{g_recaptcha_response}'; }};
                        window.grecaptcha.getResponse = function() {{ return '{g_recaptcha_response}'; }};
                    }}
                """)
                debug_print("✅ Direct grecaptcha response updated")
            except Exception as e:
                debug_print(f"❌ Direct update failed: {e}")
            
            # שיטה 4: חיפוש כפתור Verify בתוך iframe של reCAPTCHA
            debug_print("Method 4: Looking for Verify button in reCAPTCHA iframe")
            
            verify_button_clicked = False
            
            # חיפוש בדף הראשי קודם
            main_page_buttons = [
                (By.ID, "submit"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, "input[type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Submit')]"),
                (By.XPATH, "//input[@value='Submit']")
            ]
            
            for selector_type, selector in main_page_buttons:
                try:
                    button = driver.find_element(selector_type, selector)
                    if button.is_enabled():
                        debug_print(f"✅ Found enabled submit button in main page: {selector}")
                        button.click()
                        verify_button_clicked = True
                        break
                except:
                    continue
            
            # אם לא נמצא בדף הראשי, חפש בתוך iframe של reCAPTCHA
            if not verify_button_clicked:
                debug_print("🔍 Searching for Verify button inside reCAPTCHA iframe...")
                
                try:
                    # מציאת iframe של reCAPTCHA
                    iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha')]")
                    
                    for i, iframe in enumerate(iframes):
                        try:
                            debug_print(f"Checking iframe {i+1}/{len(iframes)}")
                            driver.switch_to.frame(iframe)
                            
                            # חיפוש כפתור Verify בתוך iframe
                            verify_selectors = [
                                (By.ID, "recaptcha-verify-button"),
                                (By.CSS_SELECTOR, "button.rc-button-default"),
                                (By.XPATH, "//button[contains(text(), 'Verify')]"),
                                (By.XPATH, "//button[@title='Verify']"),
                                (By.CSS_SELECTOR, ".rc-button-default")
                            ]
                            
                            for selector_type, selector in verify_selectors:
                                try:
                                    verify_button = driver.find_element(selector_type, selector)
                                    if verify_button.is_enabled() and verify_button.is_displayed():
                                        debug_print(f"✅ Found Verify button in iframe: {selector}")
                                        verify_button.click()
                                        debug_print("🎯 Verify button clicked successfully!")
                                        verify_button_clicked = True
                                        break
                                except:
                                    continue
                            
                            # חזרה לדף הראשי
                            driver.switch_to.default_content()
                            
                            if verify_button_clicked:
                                break
                                
                        except Exception as iframe_error:
                            debug_print(f"Error checking iframe {i+1}: {str(iframe_error)[:50]}...")
                            try:
                                driver.switch_to.default_content()
                            except:
                                pass
                            continue
                
                except Exception as e:
                    debug_print(f"Error searching in iframes: {str(e)[:50]}...")
                    try:
                        driver.switch_to.default_content()
                    except:
                        pass
            
            if verify_button_clicked:
                debug_print("✅ Verify button found and clicked!")
            else:
                debug_print("ℹ️ No Verify button found - token injection may be sufficient")
            
            # לפי המחקר: עכשיו צריך ללחוץ על כפתור Submit הראשי!
            debug_print("🚀 CAPTCHA token processed - now waiting for Submit button")
            
            import time
            time.sleep(3)  # זמן לעיבוד הטוקן
            
            # וידוא שחזרנו לframe הראשי
            try:
                driver.switch_to.default_content()
                debug_print("✅ Switched back to main page content")
            except:
                pass
            
            # המתנה עד שכפתור Submit נהיה זמין ולחיצה עליו
            debug_print("🔍 Waiting for Submit button to become enabled...")
            
            submit_clicked = False
            max_wait_seconds = 15
            
            for wait_attempt in range(max_wait_seconds):
                try:
                    submit_button = driver.find_element(By.ID, "submit")
                    
                    if submit_button.is_enabled():
                        debug_print(f"✅ Submit button enabled after {wait_attempt + 1} seconds!")
                        debug_print("🎯 Clicking Submit button to complete CAPTCHA process...")
                        
                        # לחיצה על כפתור Submit
                        submit_button.click()
                        debug_print("✅ Submit button clicked successfully!")
                        
                        submit_clicked = True
                        break
                    else:
                        if wait_attempt == 0:
                            debug_print("⏳ Submit button still disabled, waiting for activation...")
                        elif wait_attempt % 3 == 0:  # הודעה כל 3 שניות
                            debug_print(f"⏳ Still waiting... ({wait_attempt + 1}/{max_wait_seconds})")
                        
                        time.sleep(1)
                        
                except Exception as e:
                    debug_print(f"❌ Error checking submit button: {str(e)[:50]}...")
                    time.sleep(1)
            
            if submit_clicked:
                debug_print("🎉 CAPTCHA process completed with Submit button click!")
                debug_print("📋 Form should now be processing...")
                return True
            else:
                debug_print("⚠️ Submit button never became enabled - trying alternative approach")
                debug_print("🔄 Based on Stack Overflow research: forcing submit via JavaScript")
                
                # פתרון מStack Overflow - כפיית submit via JavaScript
                try:
                    # ניסיון 1: לחיצה כפויה על submit
                    driver.execute_script("""
                        var submitBtn = document.getElementById('submit');
                        if (submitBtn) {
                            submitBtn.disabled = false;
                            submitBtn.click();
                        }
                    """)
                    debug_print("✅ Forced submit button click via JavaScript")
                    time.sleep(2)
                    return True
                    
                except Exception as e:
                    debug_print(f"❌ Forced submit failed: {e}")
                
                # ניסיון 2: רענון הדף (כמו ב-Stack Overflow)
                try:
                    debug_print("🔄 Trying page refresh to activate token (Stack Overflow method)")
                    driver.refresh()
                    time.sleep(3)
                    debug_print("✅ Page refreshed - token should be processed")
                    return True
                    
                except Exception as e:
                    debug_print(f"❌ Page refresh failed: {e}")
                    return False
            
            debug_print("✅ ReCaptcha token submission completed!")
            
        except Exception as e:
            debug_print(f"❌ Error submitting ReCaptcha response: {e}")
            return False

    def extract_question_static(instruction_text):
        """גיבוי סטטי למיפוי הוראות"""
        instruction_lower = instruction_text.lower()
        
        question_mapping = {
            "crosswalks": "/m/014xcs", "crosswalk": "/m/014xcs",
            "traffic lights": "/m/015qff", "traffic light": "/m/015qff", 
            "bicycles": "/m/0199g", "bicycle": "/m/0199g", "bike": "/m/0199g", "bikes": "/m/0199g",
            "cars": "/m/0k4j", "car": "/m/0k4j", "vehicle": "/m/0k4j", "vehicles": "/m/0k4j",
            "motorcycles": "/m/04_sv", "motorcycle": "/m/04_sv",
            "buses": "/m/01bjv", "bus": "/m/01bjv",
            "school buses": "/m/02yvhj", "school bus": "/m/02yvhj",
            "taxis": "/m/0pg52", "taxi": "/m/0pg52",
            "fire hydrants": "/m/01pns0", "fire hydrant": "/m/01pns0", "hydrant": "/m/01pns0",
            "boats": "/m/07yv9", "boat": "/m/07yv9",
            "stairs": "/m/0cvnqh", "stair": "/m/0cvnqh", "staircase": "/m/0cvnqh",
            "buildings": "/m/01x3z", "building": "/m/01x3z",
            "bridges": "/m/015kr", "bridge": "/m/015kr",
            "tractors": "/m/013xlm", "tractor": "/m/013xlm"
        }
        
        # חיפוש מדויק יותר
        for key, value in question_mapping.items():
            if key in instruction_lower:
                debug_print(f"Matched '{key}' to code '{value}'")
                return value
        
        # ברירת מחדל
        debug_print("No exact match found, using default cars code")
        return "/m/0k4j"
    
    try:
        debug_print("Starting improved CAPTCHA solving with Capsolver...")
        
        # קבלת API key
        capsolver_api_key = os.getenv("CAPSOLVER_API_KEY")
        if not capsolver_api_key:
            debug_print("Capsolver API key not found")
            return False
        
        debug_print(f"Using API key: {capsolver_api_key[:8]}...")
        debug_print(f"Instruction: '{instruction_text}'")
        
        # חילוץ קוד השאלה
        question_code = extract_question_from_instruction(instruction_text)
        debug_print(f"Question code: {question_code}")
        
        # עכשיו GPT בוחר את הקוד הנכון, אז לא צריך אלטרנטיבות
        all_questions = [question_code]
        debug_print(f"Using GPT-selected question code: {question_code}")
        
        time.sleep(2)
        
        # חיפוש iframe
        captcha_iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'bframe')]")
        if not captcha_iframes:
            debug_print("No CAPTCHA iframe found")
            return False
        
        debug_print(f"Found {len(captcha_iframes)} iframe(s)")
        
        # מעבר ל-iframe וצילום
        driver.switch_to.frame(captcha_iframes[0])
        time.sleep(2)
        
        debug_print("Taking high-quality screenshot...")
        timestamp = int(time.time())
        
        try:
            from PIL import Image
            import io
            
            # ניסיון מרובה לצילום איכותי
            approaches = [
                # גישה 1: צילום האלמנט הספציפי
                {"selector": ".rc-imageselect-table", "name": "table"},
                {"selector": ".rc-imageselect-challenge", "name": "challenge"}, 
                {"selector": ".rc-imageselect", "name": "imageselect"},
                {"selector": "body", "name": "body"}
            ]
            
            screenshot_bytes = None
            selected_approach = None
            
            for approach in approaches:
                try:
                    element = driver.find_element(By.CSS_SELECTOR, approach["selector"])
                    if element and element.is_displayed():
                        screenshot_bytes = element.screenshot_as_png
                        selected_approach = approach["name"]
                        debug_print(f"Screenshot taken using: {selected_approach}")
                        break
                except:
                    continue
            
            if not screenshot_bytes:
                debug_print("Failed to take screenshot with all approaches")
                return False
            
            # שמירת התמונה המקורית
            original_path = f"/Users/itaykarkason/Desktop/capsolver_improved_{timestamp}.png"
            with open(original_path, "wb") as f:
                f.write(screenshot_bytes)
            debug_print(f"Original screenshot saved: {original_path}")
            
            # עיבוד התמונה
            img = Image.open(io.BytesIO(screenshot_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            debug_print(f"Original image size: {img.size}")
            
            # גישות שונות לעיבוד התמונה
            image_variants = []
            
            # גרסה 1: איכות גבוהה
            buffer1 = io.BytesIO()
            img.save(buffer1, format='JPEG', quality=95, optimize=False)
            image_variants.append({
                "data": base64.b64encode(buffer1.getvalue()).decode('utf-8'),
                "name": "high_quality",
                "size": len(buffer1.getvalue())
            })
            
            # גרסה 2: איכות בינונית
            buffer2 = io.BytesIO()
            img.save(buffer2, format='JPEG', quality=85, optimize=True)
            image_variants.append({
                "data": base64.b64encode(buffer2.getvalue()).decode('utf-8'),
                "name": "medium_quality", 
                "size": len(buffer2.getvalue())
            })
            
            # גרסה 3: גרסה מוקטנת אם התמונה גדולה מ-500px
            if max(img.size) > 500:
                img_resized = img.copy()
                img_resized.thumbnail((500, 500), Image.Resampling.LANCZOS)
                buffer3 = io.BytesIO()
                img_resized.save(buffer3, format='JPEG', quality=90, optimize=True)
                image_variants.append({
                    "data": base64.b64encode(buffer3.getvalue()).decode('utf-8'),
                    "name": "resized_500px",
                    "size": len(buffer3.getvalue())
                })
            
            debug_print(f"Created {len(image_variants)} image variants")
            for variant in image_variants:
                debug_print(f"  {variant['name']}: {variant['size']} bytes")
            
            # חזרה ל-frame הראשי
            driver.switch_to.default_content()
            
            # ניסיון עם שתי גישות - classification וfull task
            api_url = "https://api.capsolver.com/createTask"
            
            # קבלת site key
            site_key = get_recaptcha_site_key(driver)
            debug_print(f"Found site key: {site_key}")
            
            # ניסיון ראשון - פתרון מלא של ReCaptcha V2 (מומלץ על ידי Capsolver)
            if site_key:
                debug_print("Trying full ReCaptcha V2 solution...")
                full_payload = {
                    "clientKey": capsolver_api_key,
                    "task": {
                        "type": "ReCaptchaV2TaskProxyLess",
                        "websiteURL": "https://multipass.co.il",
                        "websiteKey": site_key,
                        "isInvisible": False
                    }
                }
                
                try:
                    response = requests.post(api_url, json=full_payload, timeout=30)
                    debug_print(f"Full API Response Status: {response.status_code}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        debug_print(f"Full API Response: {result}")
                        
                        if result.get('errorId') == 0:
                            if result.get('status') == 'ready' and 'solution' in result:
                                # פתרון מיידי
                                solution = result['solution']
                                if 'gRecaptchaResponse' in solution:
                                    debug_print("✅ Full ReCaptcha solution received!")
                                    debug_print(f"🎯 Capsolver solved the challenge: '{instruction_text}'")
                                    debug_print(f"📝 Note: Full ReCaptcha solution doesn't show which images were selected")
                                    debug_print(f"🔑 Solution token length: {len(solution['gRecaptchaResponse'])} characters")
                                    return submit_recaptcha_response(driver, solution['gRecaptchaResponse'])
                            elif 'taskId' in result:
                                # משימה אסינכרונית - נחכה לתוצאה
                                task_id = result['taskId']
                                debug_print(f"Task created, waiting for result: {task_id}")
                                return wait_for_capsolver_result(api_url, capsolver_api_key, task_id, driver)
                except Exception as e:
                    debug_print(f"Full solution failed: {e}")
            
            # גיבוי - ניסיון עם image classification
            debug_print("Trying image classification as fallback...")
            for question in all_questions:
                debug_print(f"Trying question code: {question}")
                
                for variant in image_variants:
                    debug_print(f"  -> with {variant['name']} variant...")
                    
                    payload = {
                        "clientKey": capsolver_api_key,
                        "task": {
                            "type": "ReCaptchaV2Classification",
                            "websiteURL": "https://multipass.co.il",
                            "image": variant["data"],
                            "question": question
                        }
                    }
                
                try:
                    response = requests.post(api_url, json=payload, timeout=30)
                    debug_print(f"API Response Status: {response.status_code}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        debug_print(f"API Response: {result}")
                        
                        if result.get('errorId') == 0 and 'solution' in result:
                            solution = result['solution']
                            
                            if 'objects' in solution and solution['objects']:
                                click_coordinates = solution['objects']
                                debug_print(f"✅ SUCCESS with question {question} + {variant['name']}: {click_coordinates}")
                                print(f"\n🤖 [CAPSOLVER] זוהו תמונות לקליקה ({question}): {click_coordinates} 🤖\n")
                                return perform_captcha_clicks(driver, captcha_iframes, click_coordinates)
                            elif solution.get('hasObject') == True:
                                debug_print(f"Object detected but no coordinates with {question} + {variant['name']}")
                                continue
                            else:
                                debug_print(f"No objects found with {question} + {variant['name']}")
                                continue
                        else:
                            debug_print(f"API error with {question} + {variant['name']}: {result}")
                            continue
                    else:
                        debug_print(f"HTTP error {response.status_code} with {question} + {variant['name']}")
                        continue
                        
                except Exception as e:
                    debug_print(f"Request error with {question} + {variant['name']}: {e}")
                    continue
            
            debug_print("❌ All question codes and image variants failed")
            return False
            
        except Exception as e:
            debug_print(f"Image processing error: {e}")
            return False
            
    except Exception as e:
        debug_print(f"General error: {e}")
        return False


def perform_captcha_clicks(driver, captcha_iframes, click_coordinates):
    """מבצע קליקות על תמונות ה-CAPTCHA לפי התוצאות מ-Capsolver"""
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[CAPSOLVER CLICKS] {message}")
    
    try:
        debug_print(f"Performing clicks on coordinates: {click_coordinates}")
        
        # מעבר ל-iframe של CAPTCHA
        driver.switch_to.frame(captcha_iframes[0])
        time.sleep(2)
        
        # חיפוש הרשת של התמונות
        grid_elements = driver.find_elements(By.CSS_SELECTOR, ".rc-imageselect-table td")
        if not grid_elements:
            grid_elements = driver.find_elements(By.CSS_SELECTOR, ".rc-imageselect-tile")
        
        if not grid_elements:
            debug_print("Could not find CAPTCHA grid elements")
            driver.switch_to.default_content()
            return False
        
        debug_print(f"Found {len(grid_elements)} grid elements")
        
        # ביצוע קליקות לפי המספרים שחזרו מ-Capsolver
        for coord in click_coordinates:
            if isinstance(coord, int) and 1 <= coord <= len(grid_elements):
                try:
                    # המרה למספר אינדקס (Capsolver מחזיר 1-9, אבל רשימה מתחילה מ-0)
                    index = coord - 1
                    element = grid_elements[index]
                    
                    # קליקה על התמונה
                    driver.execute_script("arguments[0].click();", element)
                    debug_print(f"Clicked on grid element {coord} (index {index})")
                    time.sleep(0.5)
                    
                except Exception as click_error:
                    debug_print(f"Error clicking element {coord}: {click_error}")
                    continue
        
        time.sleep(2)
        
        # חיפוש כפתור VERIFY
        verify_selectors = [
            "#recaptcha-verify-button",
            ".rc-button-default",
            "button[id*='verify']"
        ]
        
        verify_button = None
        for selector in verify_selectors:
            try:
                verify_button = driver.find_element(By.CSS_SELECTOR, selector)
                if verify_button and verify_button.is_displayed():
                    debug_print(f"Found verify button with selector: {selector}")
                    break
            except:
                continue
        
        if verify_button:
            verify_button.click()
            debug_print("Clicked VERIFY button")
            time.sleep(3)
            
            # בדיקה אם הCAPTCHA נפתר
            driver.switch_to.default_content()
            debug_print("Checking if CAPTCHA was solved successfully...")
            
            try:
                submit_button = driver.find_element(By.ID, "submit")
                if not submit_button.get_attribute("disabled"):
                    debug_print("✅ CAPTCHA solved successfully with Capsolver!")
                    print(f"\n🎉 [SUCCESS] CAPTCHA נפתר בהצלחה עם Capsolver! 🎉\n")
                    return True
                else:
                    debug_print("❌ CAPTCHA verification failed")
                    return False
            except Exception as check_error:
                debug_print(f"Error checking CAPTCHA result: {check_error}")
                return False
        else:
            debug_print("Could not find VERIFY button")
            driver.switch_to.default_content()
            return False
            
    except Exception as e:
        debug_print(f"Error performing CAPTCHA clicks: {e}")
        try:
            driver.switch_to.default_content()
        except:
            pass
        return False


def analyze_and_click_captcha(driver, captcha_iframes, instruction_text, phase="initial"):
    """
    ניתוח ולחיצה על CAPTCHA עם תמיכה בשלבים
    """
    import time
    import base64
    import tempfile
    import os
    import pyautogui
    
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[{phase.upper()}] {message}")
    
    try:
        # חזרה ל-frame הראשי לצילום מסך
        driver.switch_to.default_content()
        
        # צילום מסך
        debug_print("Taking screenshot for analysis...")
        selenium_screenshot = driver.get_screenshot_as_png()
        
        # שמירת צילום מסך לבדיקה
        screenshot_path = f"/tmp/{phase}_screenshot_{int(time.time())}.png"
        with open(screenshot_path, "wb") as f:
            f.write(selenium_screenshot)
        debug_print(f"Screenshot saved to: {screenshot_path}")
        
        # קבלת מידע על החלון
        window_position = driver.get_window_position()
        selenium_size = driver.get_window_size()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
            temp_file.write(selenium_screenshot)
            temp_path = temp_file.name
        
        try:
            with open(temp_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            # ניתוח עם GPT - עם strategy שונה לכל phase
            if phase == "initial":
                gpt_result = analyze_captcha_aggressive(base64_image, instruction_text)
            else:  # verification
                gpt_result = analyze_captcha_verification(base64_image, instruction_text)
            
            if not gpt_result or 'matches_found' not in gpt_result:
                debug_print("GPT failed to analyze CAPTCHA")
                return False
            
            matches = gpt_result['matches_found']
            captcha_bounds = gpt_result.get('captcha_bounds', {})
            
            debug_print(f"GPT found {len(matches)} matches")
            
            if not matches:
                debug_print("No matches found - assuming current state is correct")
                return True  # אם אין מה לעשות, זה בסדר
            
            # חישוב קואורדינטות
            coordinates = calculate_captcha_click_coordinates_real_screen(
                matches, captcha_bounds, window_position, selenium_size
            )
            
            debug_print("=== COORDINATE DETAILS ===")
            for i, (x, y) in enumerate(coordinates):
                match = matches[i] if i < len(matches) else {}
                debug_print(f"Match {i+1}: Row {match.get('row', '?')}, Col {match.get('col', '?')}")
                debug_print(f"  -> Will click at: ({x}, {y})")
                debug_print(f"  -> {match.get('description', 'N/A')} ({match.get('confidence', 'N/A')})")
            
            if coordinates:
                debug_print("Clicking coordinates...")
                click_on_captcha_coordinates_with_pyautogui(coordinates)
                time.sleep(1)  # המתנה אחרי הלחיצות
            
            return True
                
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    except Exception as e:
        debug_print(f"Error in analyze_and_click_captcha: {e}")
        return False

def analyze_captcha_aggressive(base64_image, instruction_text):
    """
    ניתוח אגרסיבי לשלב הראשון
    """
    import openai
    import json
    
    try:
        openai.api_key = os.getenv("OPENAI_API_KEY")
        
        prompt = f"""
        INITIAL CAPTCHA SCAN: "{instruction_text}"
        
        This is the FIRST analysis. Be EXTREMELY aggressive in finding matches.
        
        RULES:
        1. Look for ANY possible presence of the target object
        2. Include everything that might be relevant
        3. Better to over-select than under-select
        4. Include borderline cases
        
        For the object "{instruction_text}":
        - Look in foreground AND background
        - Include partial views, blurry objects
        - Include similar objects (motorcycle for bicycle, etc.)
        - When in doubt, INCLUDE it
        
        Examine ALL 9 squares systematically and return matches.
        
        JSON format:
        {{
            "instruction_detected": "{instruction_text}",
            "captcha_bounds": {{"left": 605, "top": 275, "width": 370, "height": 370}},
            "matches_found": [
                {{"row": 0, "col": 0, "description": "possible target object", "confidence": "medium"}},
                {{"row": 1, "col": 2, "description": "clear target object", "confidence": "high"}}
            ]
        }}
        """
        
        response = openai.ChatCompletion.create(
            model="gpt-4o",  # שינוי למודל החזק יותר
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1500,
            temperature=0.2
        )
        
        result = response.choices[0].message.content
        
        try:
            start_idx = result.find('{')
            end_idx = result.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = result[start_idx:end_idx]
                parsed_result = json.loads(json_str)
                
                # סינון - קבל הכל חוץ מ-none
                filtered_matches = []
                if 'matches_found' in parsed_result:
                    for match in parsed_result['matches_found']:
                        confidence = match.get('confidence', 'low').lower()
                        if confidence not in ['none', 'no']:
                            filtered_matches.append(match)
                
                parsed_result['matches_found'] = filtered_matches
                
                if DEBUG_MODE:
                    print(f"[AGGRESSIVE] Found {len(filtered_matches)} potential matches")
                
                return parsed_result
        except Exception as json_error:
            if DEBUG_MODE:
                print(f"[AGGRESSIVE] JSON parsing error: {json_error}")
            
        return None
        
    except Exception as e:
        print(f"Error in aggressive analysis: {e}")
        return None

def analyze_captcha_verification(base64_image, instruction_text):
    """
    ניתוח לאימות - יותר זהיר ומדויק
    """
    import openai
    import json
    
    try:
        openai.api_key = os.getenv("OPENAI_API_KEY")
        
        prompt = f"""
        VERIFICATION SCAN: "{instruction_text}"
        
        This is the SECOND analysis for verification. Look at the current state of selected squares (marked in blue).
        
        TASK:
        1. Identify which squares are currently SELECTED (marked with blue checkmarks)
        2. Identify which squares should be ADDED (contain target but not selected)
        3. Identify which squares should be REMOVED (selected but don't contain target)
        
        Be more PRECISE this time:
        - Only include clear, obvious matches
        - Be strict about what qualifies as the target object
        - Focus on accuracy over completeness
        
        Return ONLY the changes needed:
        - Squares to ADD (unselected but should be selected)
        - Squares to REMOVE (selected but shouldn't be)
        
        JSON format:
        {{
            "instruction_detected": "{instruction_text}",
            "captcha_bounds": {{"left": 605, "top": 275, "width": 370, "height": 370}},
            "current_state": [
                {{"row": 0, "col": 2, "status": "selected", "correct": true}},
                {{"row": 1, "col": 1, "status": "unselected", "should_select": true}}
            ],
            "matches_found": [
                {{"row": 1, "col": 1, "description": "clear target object not yet selected", "confidence": "high", "action": "add"}},
                {{"row": 2, "col": 0, "description": "incorrectly selected square", "confidence": "high", "action": "remove"}}
            ]
        }}
        """
        
        response = openai.ChatCompletion.create(
            model="gpt-4o",  # שינוי למודל החזק יותר
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1500,
            temperature=0
        )
        
        result = response.choices[0].message.content
        
        try:
            start_idx = result.find('{')
            end_idx = result.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = result[start_idx:end_idx]
                parsed_result = json.loads(json_str)
                
                # סינון - רק high confidence למתוקנים
                filtered_matches = []
                if 'matches_found' in parsed_result:
                    for match in parsed_result['matches_found']:
                        confidence = match.get('confidence', 'low').lower()
                        if confidence in ['high', 'medium']:
                            filtered_matches.append(match)
                
                parsed_result['matches_found'] = filtered_matches
                
                if DEBUG_MODE:
                    print(f"[VERIFICATION] Found {len(filtered_matches)} corrections needed")
                
                return parsed_result
        except Exception as json_error:
            if DEBUG_MODE:
                print(f"[VERIFICATION] JSON parsing error: {json_error}")
            
        return None
        
    except Exception as e:
        print(f"Error in verification analysis: {e}")
        return None

def click_verify_button_smart(driver, captcha_iframes):
    """
    לחיצה חכמה על כפתור VERIFY
    """
    import pyautogui
    import time
    
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[VERIFY] {message}")
    
    try:
        debug_print("Looking for VERIFY button...")
        
        driver.switch_to.frame(captcha_iframes[0])
        time.sleep(1)
        
        # חיפוש כפתור VERIFY
        verify_selectors = [
            "#recaptcha-verify-button",
            ".rc-button-default",
            "button[id*='verify']",
            "input[value*='verify']",
            "input[value*='Verify']"
        ]
        
        verify_button = None
        for selector in verify_selectors:
            try:
                verify_button = driver.find_element(By.CSS_SELECTOR, selector)
                if verify_button and verify_button.is_displayed():
                    break
            except:
                continue
        
        if verify_button:
            # קבלת מיקום הכפתור
            location = verify_button.location_once_scrolled_into_view
            size = verify_button.size
            
            # מעבר חזרה ל-frame הראשי
            driver.switch_to.default_content()
            
            # קבלת מיקום החלון
            window_position = driver.get_window_position()
            
            # חישוב מיקום אמיתי
            real_x = window_position['x'] + location['x'] + size['width'] // 2
            real_y = window_position['y'] + 80 + location['y'] + size['height'] // 2  # +80 לכותרת הדפדפן
            
            debug_print(f"Clicking VERIFY at ({real_x}, {real_y})")
            pyautogui.click(real_x, real_y)
            time.sleep(2)
            
        else:
            debug_print("VERIFY button not found")
            driver.switch_to.default_content()
            
    except Exception as e:
        debug_print(f"Error clicking VERIFY: {e}")
        try:
            driver.switch_to.default_content()
        except:
            pass

def click_on_captcha_coordinates_with_pyautogui(coordinates):
    """
    לחיצה משופרת עם pyautogui - עם זמני המתנה מותאמים לCAPTCHA
    """
    import pyautogui
    import time
    
    try:
        # הגדרות מהירות
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.1
        
        print(f"[PYAUTOGUI CLICK] Clicking {len(coordinates)} coordinates with improved timing")
        
        # המתנה ראשונית לטעינת תמונות
        print(f"[PYAUTOGUI CLICK] Waiting for images to fully load...")
        time.sleep(2)
        
        for i, (x, y) in enumerate(coordinates):
            print(f"[PYAUTOGUI CLICK] Moving to ({x}, {y}) and clicking...")
            
            # תזוזה איטית יותר למניעת שגיאות
            pyautogui.moveTo(x, y, duration=0.3)
            time.sleep(0.2)
            
            # לחיצה
            pyautogui.click(x, y)
            
            print(f"[PYAUTOGUI CLICK] Clicked #{i+1} at ({x}, {y})")
            
            # המתנה ארוכה יותר בין לחיצות לרישום נכון
            time.sleep(0.8)
            
        # המתנה נוספת אחרי כל הלחיצות
        print(f"[PYAUTOGUI CLICK] All clicks completed, waiting for CAPTCHA to process...")
        time.sleep(3)
            
    except Exception as e:
        print(f"[PYAUTOGUI CLICK] Error clicking coordinates: {e}")


def calculate_captcha_click_coordinates_real_screen(matches, captcha_bounds, window_position, selenium_size):
    """
    חישוב קואורדינטות מדויק - מעודכן
    """
    coordinates = []
    
    # הגדרות מעודכנות לפי התמונה
    if not captcha_bounds:
        captcha_left_relative = 605
        captcha_top_relative = 275
        captcha_width = 370
        captcha_height = 370
    else:
        captcha_left_relative = captcha_bounds.get('left', 605)
        captcha_top_relative = captcha_bounds.get('top', 275)
        captcha_width = captcha_bounds.get('width', 370)
        captcha_height = captcha_bounds.get('height', 370)
    
    browser_x = window_position.get('x', 0)
    browser_y = window_position.get('y', 0)
    browser_title_height = 100  # מעט יותר גבוה
    
    captcha_real_left = browser_x + captcha_left_relative
    captcha_real_top = browser_y + browser_title_height + captcha_top_relative
    
    print(f"[COORDINATES] CAPTCHA real position: ({captcha_real_left}, {captcha_real_top})")
    
    cell_width = captcha_width // 3
    cell_height = captcha_height // 3
    
    for i, match in enumerate(matches):
        row = match['row']
        col = match['col']
        
        cell_real_left = captcha_real_left + (col * cell_width)
        cell_real_top = captcha_real_top + (row * cell_height)
        
        center_x = cell_real_left + (cell_width // 2)
        center_y = cell_real_top + (cell_height // 2)
        
        coordinates.append((center_x, center_y))
        
        print(f"[COORDINATES] Match {i+1}: ({center_x}, {center_y}) - {match.get('description', 'N/A')}")
    
    return coordinates

def get_coupon_data(coupon, save_directory="automatic_coupon_update/input_html"):
    # Import required modules at function level
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

    # Helper function to print debug messages when DEBUG_MODE is enabled
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[DEBUG] {message}")

    """
    This function uses Selenium to access a website (Multipass, Max, or BuyMe) based on the coupon.auto_download_details value.
    It downloads the relevant information, converts it into a DataFrame, compares it with existing records in the database,
    adds only new transactions, and updates the coupon's status accordingly.
    Returns a DataFrame containing new transactions or None if there are no new transactions or an error occurs.
    """
    debug_print(f"Starting coupon data retrieval for coupon: {coupon.code}")

    # Ensure that the save directory exists
    os.makedirs(save_directory, exist_ok=True)

    coupon_number = coupon.code
    coupon_kind = (
        coupon.auto_download_details
    )  # Expected values: "Multipass", "Max", "BuyMe", etc.
    card_exp = coupon.card_exp
    cvv = coupon.cvv

    # Configure basic Selenium Chrome options
    debug_print("Configuring Chrome options")
    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-images")  # Prevent image loading
    chrome_options.add_argument(
        "--disable-extensions"
    )  # Disable unnecessary extensions
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    # For the "Max" coupon type, block images
    if coupon_kind == "Max":
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")

    df = None  # DataFrame to hold the scraped data

    # -------------------- Handling Multipass Scenario --------------------
    if coupon_kind == "Multipass":
        driver = None
        try:
            debug_print("Initializing Selenium for Multipass")
            driver = webdriver.Chrome(options=chrome_options)
            driver.get(
                "https://multipass.co.il/%d7%91%d7%a8%d7%95%d7%a8-%d7%99%d7%aa%d7%a8%d7%94/"
            )
            wait = WebDriverWait(driver, 30)
            time.sleep(5)

            debug_print("Locating card number input field")
            card_number_field = driver.find_element(
                By.XPATH, "//input[@id='newcardid']"
            )
            card_number_field.clear()

            cleaned_coupon_number = str(coupon_number).replace("-", "")
            debug_print(f"Entering coupon number: {cleaned_coupon_number}")
            card_number_field.send_keys(cleaned_coupon_number)
            
            # בדיקה מוקדמת אם Submit button כבר מאופשר (ללא CAPTCHA)
            time.sleep(2)  # המתנה קצרה לטעינת הדף
            debug_print("🔍 Checking if Submit button is already enabled (no CAPTCHA needed)...")
            
            try:
                early_submit_check = driver.find_element(By.ID, "submit")
                disabled_attr = early_submit_check.get_attribute("disabled")
                is_enabled = early_submit_check.is_enabled()
                debug_print(f"🔍 Button state: disabled='{disabled_attr}', is_enabled={is_enabled}")
                
                if is_enabled and disabled_attr is None:
                    debug_print("✅ Submit button already enabled - no CAPTCHA required!")
                    debug_print("🚀 Clicking enabled submit button...")
                    early_submit_check.click()
                    # ממשיכים ישר לטעינת הנתונים ללא CAPTCHA
                    captcha_solved = True
                    time.sleep(5)  # המתנה לטעינת התוצאות
                    debug_print("⏩ Skipping CAPTCHA handling - proceeding to data extraction")
                else:
                    debug_print("⚠️ Submit button disabled - CAPTCHA handling required")
                    debug_print(f"⚠️ Button details: disabled='{disabled_attr}', is_enabled={is_enabled}")
                    captcha_solved = False
            except Exception as early_check_error:
                debug_print(f"❌ Could not check submit button early: {early_check_error}")
                captcha_solved = False

            # אם הכפתור כבר מאופשר, נדלג על כל הטיפול בCAPTCHA
            if captcha_solved:
                debug_print("✅ Submit button was already enabled, skipping all CAPTCHA handling")
            else:
                debug_print("Handling reCAPTCHA with advanced solver")
                
                # שלב 1: לחיצה על checkbox
                recaptcha_iframe = wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//iframe[contains(@src, 'recaptcha')]")
                    )
                )
                driver.switch_to.frame(recaptcha_iframe)
                checkbox = wait.until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, ".recaptcha-checkbox-border")
                    )
                )
                checkbox.click()
                debug_print("reCAPTCHA checkbox clicked")
                driver.switch_to.default_content()
                
                # שלב 2: בדיקה אם יש CAPTCHA תמונות ופתרון אוטומטי
                time.sleep(3)  # המתנה שה-CAPTCHA יטען
                
                # ניסיון לפתור CAPTCHA אם נדרש
                max_captcha_attempts = 3
                
                for attempt in range(max_captcha_attempts):
                    debug_print(f"CAPTCHA solving attempt {attempt + 1}/{max_captcha_attempts}")
                    
                    # בדיקה אם הכפתור כבר מאופשר
                    try:
                        submit_button = driver.find_element(By.ID, "submit")
                        if not submit_button.get_attribute("disabled"):
                            debug_print("Submit button is enabled - no CAPTCHA needed")
                            captcha_solved = True
                            break
                    except:
                        pass
                    
                    # ניסיון לפתור CAPTCHA
                    try:
                        captcha_result = solve_captcha_challenge(driver, wait_timeout=60)
                        if captcha_result:
                            debug_print("CAPTCHA solved successfully")
                            
                            # בדיקה שהdriver עדיין חי
                            try:
                                driver.current_url  # בדיקה פשוטה שהdriver עובד
                                debug_print("Driver is still active after CAPTCHA solving")
                                
                                # בדיקה נוספת - האם כפתור Submit זמין עכשיו?
                                debug_print("🔍 Checking if Submit button is now enabled...")
                                try:
                                    submit_button = driver.find_element(By.ID, "submit")
                                    if submit_button.is_enabled():
                                        debug_print("✅ Submit button is enabled - CAPTCHA was processed successfully!")
                                    else:
                                        debug_print("⚠️ Submit button still disabled - may need more processing time")
                                        time.sleep(3)  # זמן נוסף
                                        # בדיקה שוב
                                        if submit_button.is_enabled():
                                            debug_print("✅ Submit button enabled after additional wait")
                                        else:
                                            debug_print("⚠️ Submit button still disabled - continuing anyway")
                                except Exception as submit_check_error:
                                    debug_print(f"Could not check submit button: {submit_check_error}")
                                
                                captcha_solved = True
                                break
                            except Exception as driver_error:
                                debug_print(f"Driver died after CAPTCHA solving: {driver_error}")
                                return None
                        else:
                            debug_print(f"CAPTCHA solving attempt {attempt + 1} failed")
                    except Exception as captcha_error:
                        debug_print(f"❌ Error during CAPTCHA solving attempt {attempt + 1}: {captcha_error}")
                        debug_print(f"   Error type: {type(captcha_error).__name__}")
                        # המשך לניסיון הבא או לטיפול בחירום
                        
                    if attempt < max_captcha_attempts - 1:
                        time.sleep(5)  # המתנה לפני ניסיון נוסף
            
            if not captcha_solved:
                debug_print("⚠️ CAPTCHA not solved after all attempts")
                debug_print("🔍 Checking if page loaded anyway without CAPTCHA...")
                
                # בדיקה אם יש כבר תוכן בעמוד למרות שלא פתרנו CAPTCHA
                try:
                    submit_button = driver.find_element(By.ID, "submit")
                    if submit_button.get_attribute("disabled"):
                        debug_print("🔄 Submit button still disabled - forcing click anyway")
                        # כפיית לחיצה על כפתור disabled
                        driver.execute_script("""
                            var submitBtn = document.getElementById('submit');
                            if (submitBtn) {
                                submitBtn.disabled = false;
                                submitBtn.click();
                            }
                        """)
                        debug_print("✅ Forced click on disabled submit button")
                        captcha_solved = True  # מעדכנים שפתרנו את הבעיה
                        time.sleep(3)  # זמן לטעינת התוצאות אחרי לחיצה כפויה
                    else:
                        debug_print("✅ Submit button already enabled despite no CAPTCHA")
                        captcha_solved = True
                except Exception as submit_check_error:
                    debug_print(f"❌ Could not check/click submit button: {submit_check_error}")
                    return None
                
                if not captcha_solved:
                    debug_print("❌ Failed to proceed - no CAPTCHA solution and button still disabled")
                    return None
            # סיום הטיפול ב-CAPTCHA
            
            # בדיקה אם הכפתור כבר נלחץ בכפייה
            forced_click_done = False
            try:
                submit_button = driver.find_element(By.ID, "submit")
                if submit_button.get_attribute("disabled") is None and captcha_solved:
                    # אם השיטה הכפויה עבדה, לא צריך ללחוץ שוב
                    forced_click_done = True
                    debug_print("✅ Submit button was already clicked via forced method")
            except:
                pass
            
            if not forced_click_done:
                try:
                    check_balance_button = wait.until(
                        EC.element_to_be_clickable((By.ID, "submit"))
                    )
                    if check_balance_button.is_enabled():
                        debug_print("Submit button is enabled - clicking to get data")
                        debug_print("🚀 Clicking 'ברור יתרה' button...")
                        check_balance_button.click()
                        debug_print("✅ Submit button clicked successfully!")
                    else:
                        debug_print(
                            "Submit button is disabled. CAPTCHA may not be solved properly."
                        )
                        driver.quit()
                        return None
                except Exception as click_error:
                    debug_print(f"⚠️ Could not click submit button normally: {click_error}")
                    debug_print("🔄 Trying forced click as fallback...")
                    driver.execute_script("""
                        var submitBtn = document.getElementById('submit');
                        if (submitBtn) {
                            submitBtn.disabled = false;
                            submitBtn.click();
                        }
                    """)
                    debug_print("✅ Used forced click as fallback")
                    time.sleep(3)

            # סגירת CAPTCHA popup אם עדיין פתוח
            debug_print("🔍 Checking for open CAPTCHA popup to close...")
            try:
                # ניסיון למצוא ולסגור את החלון הקופץ של reCAPTCHA
                driver.execute_script("""
                    // סגירת כל החלונות הקופצים של reCAPTCHA
                    var recaptchaFrames = document.querySelectorAll('iframe[src*="recaptcha"]');
                    recaptchaFrames.forEach(function(frame) {
                        if (frame.style.visibility !== 'hidden') {
                            frame.style.display = 'none';
                            frame.style.visibility = 'hidden';
                        }
                    });
                    
                    // הסתרת כל האלמנטים של reCAPTCHA
                    var recaptchaElements = document.querySelectorAll('[class*="recaptcha"], [id*="recaptcha"]');
                    recaptchaElements.forEach(function(element) {
                        element.style.display = 'none';
                    });
                    
                    // לחיצה על כפתור סגירה אם קיים
                    var closeButtons = document.querySelectorAll('.rc-imageselect-close, [aria-label="Close"], .close');
                    closeButtons.forEach(function(btn) {
                        if (btn.offsetParent !== null) { // אם הכפתור נראה
                            btn.click();
                        }
                    });
                """)
                debug_print("✅ CAPTCHA popup closed/hidden")
                time.sleep(2)  # זמן קצר לסגירת הpopup
            except Exception as close_error:
                debug_print(f"⚠️ Could not close CAPTCHA popup: {close_error}")
            
            debug_print("⏳ Waiting for data table to load after CAPTCHA...")
            # המתנה ארוכה יותר לטעינת הנתונים אחרי קאפצ'ה
            try:
                wait_extended = WebDriverWait(driver, 30)  # 30 שניות במקום 10
                # ניסיון למצוא טבלה עם כמה selectors שונים
                table_found = False
                table_selectors = ["//table", ".table", "#dataTable", "table", "[role='table']"]
                
                for selector in table_selectors:
                    try:
                        if selector.startswith("//"):
                            wait_extended.until(EC.presence_of_element_located((By.XPATH, selector)))
                        else:
                            wait_extended.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                        debug_print(f"✅ Table found with selector: {selector}")
                        table_found = True
                        break
                    except Exception as selector_error:
                        debug_print(f"❌ Table not found with selector {selector}: {selector_error}")
                        continue
                
                if table_found:
                    debug_print("✅ Table element found, waiting additional time for full data load...")
                    time.sleep(15)  # המתנה נוספת לטעינת הנתונים המלאה
                else:
                    debug_print("⚠️ No table found with any selector, but continuing to save page HTML...")
                    time.sleep(10)  # המתנה קצרה יותר
                    
            except Exception as table_wait_error:
                debug_print(f"⚠️ Error waiting for table: {table_wait_error}, continuing anyway...")
                time.sleep(10)  # המתנה קצרה יותר אם יש בעיה
            
            debug_print("🔍 Checking page content after CAPTCHA and wait...")

            page_html = driver.page_source
            debug_print(f"📄 Page HTML length: {len(page_html)} characters")
            
            # בדיקה אם יש נתונים בטבלה
            if "אין נתונות להצגה" in page_html or "No data" in page_html:
                debug_print("⚠️ Page shows 'no data' message")
            else:
                debug_print("✅ Page appears to contain data")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"coupon_{coupon_number}_{timestamp}.html"
            file_path = os.path.join(save_directory, filename)
            
            debug_print(f"💾 Saving page HTML to {file_path}")
            debug_print(f"📁 Save directory: {save_directory}")
            debug_print(f"📝 File name: {filename}")
            
            # וידוא שהתיקייה קיימת
            os.makedirs(save_directory, exist_ok=True)
            debug_print(f"📁 Directory created/verified: {save_directory}")
            
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(page_html)
            debug_print(f"✅ Successfully saved HTML file ({len(page_html)} chars)")
            debug_print(f"📂 Full path: {os.path.abspath(file_path)}")
            debug_print("🎯 Selenium operations completed successfully - moving to data extraction")

        except Exception as e:
            debug_print(
                f"An error occurred during Selenium operations (Multipass): {e}"
            )
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            return None
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass  # ה-driver כבר נסגר

        try:
            debug_print("📊 Reading tables from saved HTML")
            dfs = pd.read_html(file_path)
            debug_print(f"🔍 Found {len(dfs)} table(s) in HTML")
            
            # שמירת קובץ לבדיקה אם אין טבלאות
            if not dfs:
                debug_print("❌ No tables found in HTML (Multipass)")
                backup_path = file_path.replace('.html', '_no_tables_found.html')
                import shutil
                shutil.copy2(file_path, backup_path)
                debug_print(f"🔍 Saved problematic HTML to: {backup_path}")
                os.remove(file_path)
                return None
            else:
                debug_print(f"✅ Successfully found {len(dfs)} table(s)")
                os.remove(file_path)

            df = dfs[0]
            debug_print(f"📊 Table has {len(df)} rows and {len(df.columns)} columns")
            debug_print(f"📋 Column names: {list(df.columns)}")
            debug_print("🔄 Renaming columns for Multipass data")
            df = df.rename(
                columns={
                    "שם בית עסק": "location",
                    "סכום טעינת תקציב": "recharge_amount",
                    "סכום מימוש תקציב": "usage_amount",
                    "תאריך": "transaction_date",
                    "מספר אסמכתא": "reference_number",
                }
            )
            debug_print("Handling missing numeric columns")
            if "recharge_amount" not in df.columns:
                df["recharge_amount"] = 0.0
            if "usage_amount" not in df.columns:
                df["usage_amount"] = 0.0

            debug_print("Converting transaction date")
            df["transaction_date"] = pd.to_datetime(
                df["transaction_date"], format="%H:%M %d/%m/%Y", errors="coerce"
            )

            debug_print("Converting numeric columns to proper format")
            numeric_columns = ["recharge_amount", "usage_amount"]
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            
            debug_print(f"🎉 Successfully processed Multipass data: {len(df)} rows")
            debug_print(f"📊 Final DataFrame columns: {list(df.columns)}")

        except Exception as e:
            debug_print(f"An error occurred during data parsing (Multipass): {e}")
            traceback.print_exc()
            return None

    # -------------------- Handling Max Scenario --------------------
    elif coupon_kind == "Max":
        try:
            debug_print("Initializing Selenium for Max")
            # Set Chrome binary path - try multiple possible locations
            possible_chrome_paths = [
                os.getenv('CHROME_BIN'),
                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                '/usr/bin/google-chrome-stable',
                '/usr/bin/google-chrome',
                '/usr/bin/chromium-browser',
                '/usr/bin/chromium',
                '/opt/google/chrome/chrome'
            ]
            
            # Debug: Check what Chrome binaries exist
            debug_print("=== DEBUGGING CHROME INSTALLATION ===")
            debug_print(f"CHROME_BIN env var: {os.getenv('CHROME_BIN')}")
            
            # Check what's actually in /usr/bin/
            import glob
            chrome_files = glob.glob('/usr/bin/*chrome*')
            debug_print(f"Chrome-related files in /usr/bin/: {chrome_files}")
            
            chrome_bin = None
            for path in possible_chrome_paths:
                if path and os.path.isfile(path):
                    chrome_bin = path
                    debug_print(f"✅ Found Chrome at: {chrome_bin}")
                    break
                elif path:
                    debug_print(f"❌ Chrome NOT found at: {path}")
            
            if not chrome_bin:
                chrome_bin = possible_chrome_paths[2]  # Default to google-chrome-stable
                debug_print(f"⚠️ No Chrome found, using default: {chrome_bin}")
                
            chrome_options.binary_location = chrome_bin
            debug_print(f"Final Chrome binary setting: {chrome_bin}")
            debug_print("=== END CHROME DEBUG ===")
            
            with webdriver.Chrome(options=chrome_options) as driver:
                wait = WebDriverWait(driver, 30)
                driver.get("https://www.max.co.il/gift-card-transactions/main")

                def safe_find(by, value, timeout=10):
                    debug_print(f"Searching for element: {by}={value}")
                    return WebDriverWait(driver, timeout).until(
                        EC.visibility_of_element_located((by, value))
                    )

                debug_print("Entering card details for Max")
                card_number_field = safe_find(By.ID, "giftCardNumber")
                card_number_field.clear()
                card_number_field.send_keys(coupon_number)

                exp_field = safe_find(By.ID, "expDate")
                exp_field.clear()
                exp_field.send_keys(card_exp)

                cvv_field = safe_find(By.ID, "cvv")
                cvv_field.clear()
                cvv_field.send_keys(cvv)

                debug_print("Clicking continue button for Max")
                continue_button = wait.until(
                    EC.element_to_be_clickable((By.ID, "continue"))
                )
                continue_button.click()

                time.sleep(7)
                debug_print("Locating transaction table for Max")
                table = wait.until(
                    EC.presence_of_element_located((By.CLASS_NAME, "mat-table"))
                )

                headers = [
                    header.text.strip()
                    for header in table.find_elements(By.TAG_NAME, "th")
                ]
                rows = []
                all_rows = table.find_elements(By.TAG_NAME, "tr")
                for row in all_rows[1:]:
                    cells = [
                        cell.text.strip()
                        for cell in row.find_elements(By.TAG_NAME, "td")
                    ]
                    if cells:
                        rows.append(cells)

                debug_print(f"Extracted {len(rows)} rows from Max table")
                df = pd.DataFrame(rows, columns=headers)
                debug_print("Cleaning Max data")
                if "שולם בתאריך" in df.columns:
                    df["שולם בתאריך"] = pd.to_datetime(
                        df["שולם בתאריך"], format="%d.%m.%Y", errors="coerce"
                    )
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

                debug_print("Renaming columns for Max data")
                col_map = {
                    "שולם בתאריך": "transaction_date",
                    "שם בית העסק": "location",
                    "סכום בשקלים": "amount",
                    "יתרה": "balance",
                    "פעולה": "action",
                    "הערות": "notes",
                }
                for k, v in col_map.items():
                    if k in df.columns:
                        df.rename(columns={k: v}, inplace=True)

                debug_print(
                    "Creating usage_amount and recharge_amount columns for Max data"
                )
                df["usage_amount"] = df.apply(
                    lambda x: x["amount"]
                    if ("action" in df.columns and "עסקה" in x["action"])
                    else 0.0,
                    axis=1,
                )
                df["recharge_amount"] = df.apply(
                    lambda x: -(x["amount"])
                    if ("action" in df.columns and x["action"] == "טעינה")
                    else 0.0,
                    axis=1,
                )

                debug_print("Adding reference number column for Max data")
                df["reference_number"] = df.index.map(
                    lambda i: f"max_ref_{int(time.time())}_{i}"
                )

                debug_print("Dropping unnecessary columns for Max data")
                for col_to_drop in ["action", "notes"]:
                    if col_to_drop in df.columns:
                        df.drop(columns=[col_to_drop], inplace=True)

        except Exception as e:
            debug_print(f"An error occurred during Selenium operations (Max): {e}")
            traceback.print_exc()
            df = None

    # -------------------- Handling BuyMe Scenario --------------------
    elif coupon_kind.lower() == "buyme":
        try:
            debug_print("Initializing Selenium for BuyMe")
            # Import webdriver_manager to manage the Chrome driver
            from webdriver_manager.chrome import ChromeDriverManager

            # Only run headless in production environment or if explicitly set
            if os.getenv('FLASK_ENV') == 'production' or os.getenv('SELENIUM_HEADLESS', 'false').lower() == 'true':
                chrome_options.add_argument("--headless")  # Run in headless mode for production
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-features=VizDisplayCompositor")
            chrome_options.add_argument("--remote-debugging-port=9222")
            
            # Set Chrome binary path - try multiple possible locations
            possible_chrome_paths = [
                os.getenv('CHROME_BIN'),
                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                '/usr/bin/google-chrome-stable',
                '/usr/bin/google-chrome',
                '/usr/bin/chromium-browser',
                '/usr/bin/chromium',
                '/opt/google/chrome/chrome'
            ]
            
            # Debug: Check what Chrome binaries exist
            debug_print("=== DEBUGGING CHROME INSTALLATION ===")
            debug_print(f"CHROME_BIN env var: {os.getenv('CHROME_BIN')}")
            
            # Check what's actually in /usr/bin/
            import glob
            chrome_files = glob.glob('/usr/bin/*chrome*')
            debug_print(f"Chrome-related files in /usr/bin/: {chrome_files}")
            
            chrome_bin = None
            for path in possible_chrome_paths:
                if path and os.path.isfile(path):
                    chrome_bin = path
                    debug_print(f"✅ Found Chrome at: {chrome_bin}")
                    break
                elif path:
                    debug_print(f"❌ Chrome NOT found at: {path}")
            
            if not chrome_bin:
                chrome_bin = possible_chrome_paths[2]  # Default to google-chrome-stable
                debug_print(f"⚠️ No Chrome found, using default: {chrome_bin}")
                
            chrome_options.binary_location = chrome_bin
            debug_print(f"Final Chrome binary setting: {chrome_bin}")
            debug_print("=== END CHROME DEBUG ===")
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)

            # Instead of a hardcoded URL, use the value from the coupon's buyme_coupon_url column
            if hasattr(coupon, "buyme_coupon_url") and coupon.buyme_coupon_url:
                url = coupon.buyme_coupon_url
            else:
                url = (
                    coupon_number
                    if coupon_number.startswith("http")
                    else "https://buyme.co.il/giftcard/76v3l74ci7l0q?utm_source=email&utm_medium=email&utm_campaign=giftcard_receive"
                )

            debug_print(f"Opening URL for BuyMe: {url}")
            driver.get(url)
            debug_print("⏳ Waiting 10 seconds for page to fully load...")
            time.sleep(10)  # Increased initial wait time

            # Check for Cloudflare challenge and wait for it to complete
            max_cloudflare_wait = 120  # seconds - increased for manual CAPTCHA solving
            cloudflare_wait_time = 0
            debug_print(f"🔍 Checking for Cloudflare challenges (max wait: {max_cloudflare_wait}s)")
            while cloudflare_wait_time < max_cloudflare_wait:
                if "Just a moment" in driver.page_source or "challenge-platform" in driver.page_source:
                    debug_print(f"🔒 Cloudflare challenge detected, waiting... ({cloudflare_wait_time}s) - Please solve any CAPTCHA manually")
                    time.sleep(2)
                    cloudflare_wait_time += 2
                else:
                    debug_print("✅ Cloudflare challenge completed or not present")
                    break
            
            if cloudflare_wait_time >= max_cloudflare_wait:
                debug_print("⚠️ Cloudflare challenge timeout - proceeding anyway")

            # Save the HTML before clicking to load details (coupon code, expiration date, load amount)
            before_click_file = os.path.join(
                save_directory, f"buyme_before_{coupon_number}.html"
            )
            with open(before_click_file, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            debug_print(f"Saved before-click HTML to {before_click_file}")

            # Click the "Where did I redeem" button to load usage details
            try:
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                
                # Wait up to 15 seconds total for the button to appear - try multiple possible texts
                debug_print("🔍 Looking for 'Where did I redeem' button (15s timeout total) - you can interact with the page manually")
                
                button_xpaths = [
                    "//button[contains(text(), 'איפה מימשתי')]",
                    "//button[contains(text(), 'איפה המימוש')]", 
                    "//button[contains(text(), 'פרטי המימוש')]",
                    "//button[contains(text(), 'היכן מומש')]",
                    "//a[contains(text(), 'איפה מימשתי')]",
                    "//a[contains(text(), 'איפה המימוש')]"
                ]
                
                # Create a combined XPath expression to find any of these buttons
                combined_xpath = " | ".join(button_xpaths)
                
                where_used_button = None
                try:
                    # Use short timeout for quick check - only 15 seconds total
                    wait = WebDriverWait(driver, 15)
                    where_used_button = wait.until(EC.element_to_be_clickable((By.XPATH, combined_xpath)))
                    debug_print("Found 'Where did I redeem' button")
                except:
                    pass  # Button not found within timeout
                
                if where_used_button:
                    driver.execute_script("arguments[0].click();", where_used_button)
                    time.sleep(3)  # Wait for content to load
                    debug_print("Clicked 'Where did I redeem' button")
                else:
                    raise Exception("Button not found with any of the expected texts")
            except Exception as e:
                debug_print(f"Error clicking 'Where did I redeem' button: {e}")
                debug_print("Button may not exist or page may not have loaded properly")
                # Don't quit - try to continue and see what we can extract
                debug_print("Continuing without clicking the button...")

            # Save the HTML after clicking (usage details)
            after_click_file = os.path.join(
                save_directory, f"buyme_after_{coupon_number}.html"
            )
            with open(after_click_file, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            debug_print(f"Saved after-click HTML to {after_click_file}")
            driver.quit()

            # Extract load details from the before-click HTML
            with open(before_click_file, "r", encoding="utf-8") as f:
                before_html = f.read()

            # Extract coupon code (if available)
            coupon_match = re.search(r"קוד שובר:\s*([\d\s\-]+)", before_html)
            coupon_code_extracted = (
                coupon_match.group(1).strip() if coupon_match else ""
            )

            # Extract expiration date (format dd.mm.yyyy)
            validity_match = re.search(r"בתוקף עד\s*([\d\.]+)", before_html)
            validity = validity_match.group(1).strip() if validity_match else ""
            if validity:
                try:
                    validity_date = pd.to_datetime(validity, format="%d.%m.%Y")
                    validity_formatted = validity_date.strftime("%Y-%m-%d")
                except Exception as e:
                    debug_print(f"Error processing validity date: {e}")
                    validity_formatted = validity
            else:
                validity_formatted = ""

            # Calculate load date as 5 years before expiration date
            if validity:
                try:
                    load_date = (validity_date - pd.DateOffset(years=5)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except Exception as e:
                    debug_print(f"Error calculating load date: {e}")
                    load_date = ""
            else:
                load_date = ""

            # Extract load amount based on the '₪' symbol
            load_amount_match = re.search(
                r'<div class="voucher-card__content__amount">₪<span>(\d+(?:\.\d+)?)</span></div>',
                before_html,
            )
            load_amount_str = (
                load_amount_match.group(1).strip() if load_amount_match else ""
            )
            load_amount = float(load_amount_str) if load_amount_str else 0.0

            # Extract business name from before-click HTML
            load_business_match = re.search(
                r'<div class="voucher-card__content__title string-to-html-element">(.*?)</div>',
                before_html,
            )
            load_business = (
                load_business_match.group(1).strip() if load_business_match else ""
            )

            # Extract usage details from the after-click HTML
            with open(after_click_file, "r", encoding="utf-8") as f:
                after_html = f.read()

            redeemed_dates = re.findall(
                r'<p class="redeem-history-item__info__date">([\d\.,:\s]+)</p>',
                after_html,
            )
            redeemed_places = re.findall(
                r'<p class="redeem-history-item__info__title">(.*?)</p>', after_html
            )
            usage_amounts = re.findall(
                r'<p class="redeem-history-item__info__amount">₪\s*(\d+(?:\.\d+)?)</p>',
                after_html,
            )

            transactions = []
            for date_str, place, amount_str in zip(
                redeemed_dates, redeemed_places, usage_amounts
            ):
                try:
                    redeemed_date = pd.to_datetime(date_str, format="%d.%m.%y, %H:%M")
                    redeemed_date_formatted = redeemed_date.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except Exception as e:
                    debug_print(f"Error processing redeemed date: {e}")
                    redeemed_date_formatted = date_str
                usage_amt = float(amount_str)
                transactions.append(
                    {
                        "transaction_date": redeemed_date_formatted,
                        "location": place,
                        "recharge_amount": 0.0,
                        "usage_amount": usage_amt,
                    }
                )

            # Add a load transaction row (recharge_amount is the load amount)
            if load_date and load_business:
                transactions.append(
                    {
                        "transaction_date": load_date,
                        "location": load_business,
                        "recharge_amount": load_amount,
                        "usage_amount": 0.0,
                    }
                )

            # Convert the transactions list to a DataFrame with defined column order
            df = pd.DataFrame(
                transactions,
                columns=[
                    "transaction_date",
                    "location",
                    "recharge_amount",
                    "usage_amount",
                ],
            )
            # Add additional columns for consistency with the Max branch
            df["amount"] = df.apply(
                lambda row: -row["recharge_amount"]
                if row["recharge_amount"] > 0
                else row["usage_amount"],
                axis=1,
            )
            df["balance"] = 0.0
            df["reference_number"] = df.index.map(
                lambda i: f"max_ref_{int(time.time())}_{i}"
            )

            # Delete temporary HTML files
            if os.path.exists(before_click_file):
                os.remove(before_click_file)
            if os.path.exists(after_click_file):
                os.remove(after_click_file)

        except Exception as e:
            debug_print(f"An error occurred during Selenium operations (BuyMe): {e}")
            traceback.print_exc()
            df = None

    # -------------------- Unsupported Coupon Type --------------------
    else:
        debug_print(f"Unsupported coupon kind: {coupon_kind}")
        df = None

    # -------------------- Common Stage: Database Comparison and Update --------------------
    if df is None:
        debug_print("No data to process - df is None")
        return None
        
    try:
        debug_print("Retrieving existing transactions from the database")
        existing_data = pd.read_sql_query(
            """
            SELECT reference_number
            FROM coupon_transaction
            WHERE coupon_id = %(coupon_id)s
            """,
            db.engine,
            params={"coupon_id": coupon.id},
        )

        debug_print("Checking if database entries differ from scraped data")
        if len(existing_data) != len(df):
            if len(existing_data) > 0:
                debug_print(
                    "Existing entries differ in number, deleting current records"
                )
                db.session.execute(
                    text("DELETE FROM coupon_transaction WHERE coupon_id = :coupon_id"),
                    {"coupon_id": coupon.id},
                )
                db.session.commit()
                existing_data = pd.read_sql_query(
                    """
                    SELECT reference_number
                    FROM coupon_transaction
                    WHERE coupon_id = %(coupon_id)s
                    """,
                    db.engine,
                    params={"coupon_id": coupon.id},
                )

        existing_refs = set(existing_data["reference_number"].astype(str))
        df["reference_number"] = df["reference_number"].astype(str)
        df_new = df[~df["reference_number"].isin(existing_refs)]

        if df_new.empty:
            debug_print(
                "No new transactions to add (all references already exist in DB)."
            )
            return None

        debug_print(f"Adding {len(df_new)} new transactions to the database")
        for idx, row in df_new.iterrows():
            transaction = CouponTransaction(
                coupon_id=coupon.id,
                transaction_date=row.get("transaction_date"),
                location=row.get("location", ""),
                recharge_amount=row.get("recharge_amount", 0.0),
                usage_amount=row.get("usage_amount", 0.0),
                reference_number=row.get("reference_number", ""),
                source="Multipass",
            )
            db.session.add(transaction)

        debug_print("Calculating total used value from transactions")
        total_used = (
            db.session.query(func.sum(CouponTransaction.usage_amount))
            .filter_by(coupon_id=coupon.id)
            .scalar()
            or 0.0
        )
        coupon.used_value = float(total_used)
        debug_print("Updating coupon status")
        update_coupon_status(coupon)
        db.session.commit()

        debug_print(
            f"Transactions for coupon {coupon.code} have been updated in the database."
        )
        return df_new
    except Exception as e:
        debug_print(f"An error occurred during database operations: {e}")
        traceback.print_exc()
        db.session.rollback()
        return None

def convert_coupon_data(file_path):
    # Read the HTML to DataFrame
    dfs = pd.read_html(file_path)
    df = dfs[0]
    print("Columns in DataFrame:", df.columns)
    print(df.head())

    # Extract the card number from the HTML
    with open(file_path, "r", encoding="utf-8") as file:
        html_content = file.read()
    card_number_pattern = r'כרטיס: </div> <div class="cardnumber">(\d+)</div>'
    card_number_match = re.search(card_number_pattern, html_content)
    card_number_extracted = (
        int(card_number_match.group(1)) if card_number_match else coupon_number
    )

    # Update mapping of columns according to current columns
    df = df.rename(
        columns={
            "שם בית עסק": "location",
            "סכום מימוש תקציב": "usage_amount",
            "תאריך": "transaction_date",
            "הטענה": "recharge_amount",  # Update the mapping according to the current columns
            "מספר אסמכתא": "reference_number",
        }
    )

    # Check if the columns exist
    expected_columns = [
        "transaction_date",
        "location",
        "usage_amount",
        "recharge_amount",
        "reference_number",
    ]
    missing_columns = [col for col in expected_columns if col not in df.columns]
    if missing_columns:
        print(f"Missing columns in DataFrame: {missing_columns}")
        for col in missing_columns:
            if col in ["recharge_amount", "usage_amount"]:
                df[col] = 0.0  # Set default value to 0.0
            else:
                df[col] = None  # Or set default value to None

    # Reorder columns
    df = df[
        [
            "transaction_date",
            "location",
            "usage_amount",
            "recharge_amount",
            "reference_number",
        ]
    ]

    # Convert transaction date with custom format
    df["transaction_date"] = pd.to_datetime(
        df["transaction_date"], format="%H:%M %d/%m/%Y", errors="coerce"
    )

    # Replace NaT with None
    print(df["transaction_date"])
    df["transaction_date"] = df["transaction_date"].where(
        pd.notnull(df["transaction_date"]), None
    )

    return df


def send_html_email(
    api_key: str,
    sender_email: str,
    sender_name: str,
    recipient_email: str,
    recipient_name: str,
    subject: str,
    html_content: str,
    add_timestamp: bool = True,
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
    - add_timestamp (bool): Whether to add timestamp to subject line.

    Returns:
    - dict: API response if successful.
    - None: If an exception occurs.
    """
    # Configure API key authorization
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = api_key

    # Create an instance of the TransactionalEmailsApi
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    # Define the email parameters
    if add_timestamp:
        # Use Israel timezone (UTC+3)
        israel_tz = ZoneInfo('Asia/Jerusalem')
        israel_time = datetime.now(israel_tz)
        final_subject = f"{subject} - {israel_time.strftime('%d%m%Y %H:%M')}"
    else:
        final_subject = subject
    
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient_email, "name": recipient_name}],
        sender={"email": sender_email, "name": sender_name},
        subject=final_subject,
        html_content=html_content,
    )

    try:
        # Send the email
        api_response = api_instance.send_transac_email(send_smtp_email)
        pprint(api_response)
        return api_response
    except ApiException as e:
        print(
            "Exception when calling TransactionalEmailsApi->send_transac_email: %s\n"
            % e
        )
        return None


def send_email(
    sender_email, sender_name, recipient_email, recipient_name, subject, html_content, add_timestamp=True
):
    """
    Sends a general email.

    :param sender_email: Sender's email address
    :param sender_name: Sender's name
    :param recipient_email: Recipient's email address
    :param recipient_name: Recipient's name
    :param subject: Subject of the email
    :param html_content: HTML content of the email
    :param add_timestamp: Whether to add timestamp to subject line
    """
    # Add the API key directly within the function
    api_key = BREVO_API_KEY

    try:
        send_html_email(
            api_key=api_key,
            sender_email=sender_email,
            sender_name=sender_name,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            subject=subject,
            html_content=html_content,
            add_timestamp=add_timestamp,
        )
    except Exception as e:
        raise Exception(f"Error sending email: {e}")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def require_login(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        # List of public routes
        allowed_routes = ["login", "register", "static"]

        # If the user is not logged in, redirect them to the login page
        if not current_user.is_authenticated:
            return redirect(url_for("login"))

        # Check if request.endpoint exists before accessing it and if the path is not in the public routes
        if (
            request.endpoint
            and not request.endpoint.startswith("static.")
            and request.endpoint not in allowed_routes
        ):
            # If the path is not public and the user is not logged in, return to login
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return decorated_view


def generate_confirmation_token(email):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return serializer.dumps(email, salt=current_app.config["SECURITY_PASSWORD_SALT"])


def confirm_token(token, expiration=3600):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    email = serializer.loads(
        token, salt=current_app.config["SECURITY_PASSWORD_SALT"], max_age=expiration
    )
    return email


def extract_coupon_detail_sms(coupon_text, companies_list):
    import openai
    import os
    from dotenv import load_dotenv
    import json
    import pandas as pd
    import requests
    from datetime import datetime as dt

    """
    Function to extract coupon details using GPT-4o.

    Parameters:
        coupon_text (str): Text containing coupon details.
        companies_list (list): List of existing companies in the database.

    Returns:
        tuple: DataFrame with coupon details matching the JSON schema, and another DataFrame with pricing and exchange rate.
    """
    # Set the API key
    openai.api_key = os.getenv("OPENAI_API_KEY")

    # Convert companies list to string
    companies_str = ", ".join(companies_list)

    # Define JSON schema
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
                        "סטטוס": {"type": "string", "enum": ["פעיל", "נוצל"]},
                    },
                    "required": [
                        "קוד קופון",
                        "ערך מקורי",
                        "עלות",
                        "חברה",
                        "תיאור",
                        "תאריך תפוגה",
                        "סטטוס",
                    ],
                },
            },
            "strict": True,
        }
    ]

    # Define prompt
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

    # Call the OpenAI API
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",  # שינוי למודל החזק יותר
            messages=[
                {"role": "system", "content": "אנא ספק פלט JSON לפי הכלי שסופק."},
                {"role": "user", "content": prompt},
            ],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "coupon_details"}},
        )

        response_data = response["choices"][0]["message"]["tool_calls"][0]["function"][
            "arguments"
        ]

        # Try to load as JSON
        try:
            coupon_data = json.loads(response_data)
        except json.JSONDecodeError:
            raise ValueError("השגיאה: הפלט שהתקבל אינו בפורמט JSON תקין.")

        # Convert the output to DataFrame
        coupon_df = pd.DataFrame([coupon_data])

        # Create another DataFrame with pricing data
        pricing_data = {
            "prompt_tokens": response["usage"]["prompt_tokens"],
            "completion_tokens": response["usage"]["completion_tokens"],
            "total_tokens": response["usage"]["total_tokens"],
            "id": response["id"],
            "object": response["object"],
            "created": dt.utcfromtimestamp(response["created"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "model": response["model"],
            # Add columns for prompt and response
            "prompt_text": prompt,
            "response_text": json.dumps(coupon_data, ensure_ascii=False),
        }

        # Calculate exchange rate
        try:
            exchange_rate_response = requests.get(
                "https://api.exchangerate-api.com/v4/latest/USD"
            )
            exchange_rate_data = exchange_rate_response.json()
            usd_to_ils_rate = exchange_rate_data["rates"]["ILS"]
        except Exception as e:
            print(f"Error fetching exchange rate: {e}")
            usd_to_ils_rate = 3.75  # Default value

        # Calculate prices
        pricing_data["cost_usd"] = pricing_data["total_tokens"] * 0.00004
        pricing_data["cost_ils"] = pricing_data["cost_usd"] * usd_to_ils_rate
        pricing_data["exchange_rate"] = usd_to_ils_rate

        pricing_df = pd.DataFrame([pricing_data])

        return coupon_df, pricing_df
    except openai.error.RateLimitError:
        # **📧 שליחת מייל במקרה של חריגה מהמכסה**
        recipients = ["couponmasteril2@gmail.com", "itayk93@gmail.com"]
        for recipient in recipients:
            send_email(
                sender_email="noreply@couponmasteril.com",
                sender_name="Coupon Master System",
                recipient_email=recipient,
                recipient_name="Admin",
                subject="⚠️ חריגה ממכסת OpenAI - ניתוח קופון מ-SMS",
                html_content=f"""
                <h2>התראת מערכת - חרגת ממכסת OpenAI</h2>
                <p>ניסיון לנתח קופון מתוך SMS נכשל עקב חריגה ממכסת השימוש.</p>
                <p><strong>מועד האירוע:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
                <br>
                <p>בברכה,<br>מערכת Coupon Master</p>
                """,
            )

        flash("הגעת למכסת השימוש שלך ב-OpenAI. יש לפנות למנהל התוכנה.", "danger")
        return pd.DataFrame(), pd.DataFrame()

    except openai.error.OpenAIError as e:
        flash("אירעה שגיאה ב-OpenAI. יש לפנות למנהל התוכנה.", "danger")
        print(f"❌ שגיאת OpenAI: {str(e)}")

        return pd.DataFrame(), pd.DataFrame()

    except Exception as e:
        flash("שגיאה כללית בעת עיבוד הודעת ה-SMS. נסה שוב מאוחר יותר.", "danger")
        print(f"❌ שגיאה כללית: {str(e)}")

        return pd.DataFrame(), pd.DataFrame()


def extract_coupon_detail_image_proccess(client_id, image_path, companies_list):
    import pandas as pd
    from datetime import datetime, timezone

    try:

        def extract_coupon_detail_image(image_path, companies_list):
            import openai
            import os
            from dotenv import load_dotenv
            import json
            import pandas as pd
            import requests
            import base64
            from datetime import datetime, timezone

            try:
                load_dotenv()
                openai.api_key = os.getenv("OPENAI_API_KEY")

                # Convert image to base64
                with open(image_path, "rb") as image_file:
                    base64_image = base64.b64encode(image_file.read()).decode('utf-8')
                
                # Determine image format
                image_extension = os.path.splitext(image_path)[1].lower()
                if image_extension in ['.jpg', '.jpeg']:
                    image_format = 'jpeg'
                elif image_extension == '.png':
                    image_format = 'png'
                elif image_extension == '.gif':
                    image_format = 'gif'
                elif image_extension == '.webp':
                    image_format = 'webp'
                else:
                    image_format = 'jpeg'  # default fallback

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
                            ],
                        },
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

                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4o",  # שינוי למודל החזק יותר
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "אנא נתח את התמונה הבאה והפק את פרטי הקופון:",
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/{image_format};base64,{base64_image}",
                                            "detail": "high",
                                        },
                                    },
                                    {"type": "text", "text": prompt},
                                ],
                            }
                        ],
                        functions=functions,
                        function_call={"name": "coupon_details"},
                        max_tokens=1000,
                    )

                    if "choices" in response and len(response["choices"]) > 0:
                        choice = response["choices"][0]
                        if "message" in choice and "function_call" in choice["message"]:
                            function_call = choice["message"]["function_call"]
                            if "arguments" in function_call:
                                response_data = function_call["arguments"]
                            else:
                                raise ValueError(
                                    "השגיאה: הפלט שהתקבל אינו מכיל arguments."
                                )
                        else:
                            raise ValueError(
                                "השגיאה: הפלט שהתקבל אינו מכיל function_call."
                            )
                    else:
                        raise ValueError("השגיאה: לא התקבלה תגובה תקינה מה-API.")

                    try:
                        coupon_data = json.loads(response_data)
                    except json.JSONDecodeError:
                        raise ValueError("השגיאה: הפלט שהתקבל אינו בפורמט JSON תקין.")

                    coupon_df = pd.DataFrame([coupon_data])

                    pricing_data = {
                        "prompt_tokens": response["usage"]["prompt_tokens"],
                        "completion_tokens": response["usage"]["completion_tokens"],
                        "total_tokens": response["usage"]["total_tokens"],
                        "id": response["id"],
                        "object": response["object"],
                        "created": datetime.fromtimestamp(
                            response["created"], tz=timezone.utc
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                        "model": response["model"],
                        "prompt_text": prompt,
                        "response_text": json.dumps(coupon_data, ensure_ascii=False),
                    }

                    try:
                        exchange_rate_response = requests.get(
                            "https://api.exchangerate-api.com/v4/latest/USD"
                        )
                        exchange_rate_data = exchange_rate_response.json()
                        usd_to_ils_rate = exchange_rate_data["rates"]["ILS"]
                    except Exception:
                        usd_to_ils_rate = 3.75

                    pricing_data["cost_usd"] = pricing_data["total_tokens"] * 0.00004
                    pricing_data["cost_ils"] = (
                        pricing_data["cost_usd"] * usd_to_ils_rate
                    )
                    pricing_data["exchange_rate"] = usd_to_ils_rate

                    pricing_df = pd.DataFrame([pricing_data])

                    return coupon_df, pricing_df

                except openai.error.RateLimitError:
                    # **📧 שליחת מייל במקרה של חריגה מהמכסה**
                    recipients = ["couponmasteril2@gmail.com", "itayk93@gmail.com"]
                    for recipient in recipients:
                        send_email(
                            sender_email="noreply@couponmasteril.com",
                            sender_name="Coupon Master System",
                            recipient_email=recipient,
                            recipient_name="Admin",
                            subject="⚠️ חריגה ממכסת OpenAI - ניתוח קופון מתמונה",
                            html_content=f"""
                            <h2>התראת מערכת - חרגת ממכסת OpenAI</h2>
                            <p>ניסיון לנתח קופון מתוך תמונה נכשל עקב חריגה ממכסת השימוש.</p>
                            <p><strong>מועד האירוע:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
                            <br>
                            <p>בברכה,<br>מערכת Coupon Master</p>
                            """,
                        )

                flash(
                    "הגעת למכסת השימוש שלך ב-OpenAI. יש לפנות למנהל התוכנה.", "danger"
                )
                return pd.DataFrame(), pd.DataFrame()

            except openai.error.OpenAIError as e:
                flash("אירעה שגיאה ב-OpenAI. יש לפנות למנהל התוכנה.", "danger")
                print(f"❌ שגיאת OpenAI: {str(e)}")

                return pd.DataFrame(), pd.DataFrame()

            except Exception as e:
                flash("שגיאה כללית בעת עיבוד התמונה. נסה שוב מאוחר יותר.", "danger")
                print(f"❌ שגיאה כללית: {str(e)}")

                return pd.DataFrame(), pd.DataFrame()

            except Exception:
                return pd.DataFrame(), pd.DataFrame()

        # Direct processing with base64 - no need for external image hosting
        coupon_df, pricing_df = extract_coupon_detail_image(
            image_path, companies_list
        )
        return coupon_df, pricing_df
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


def extract_coupon_from_base64_image(base64_image, image_format, companies_list):
    """
    Extract coupon details from a base64 encoded image using OpenAI's vision API.
    
    Args:
        base64_image (str): Base64 encoded image string
        image_format (str): Image format (e.g., 'jpeg', 'png', 'gif', 'webp')
        companies_list (list): List of company names for matching
    
    Returns:
        tuple: (coupon_df, pricing_df) - DataFrames containing coupon data and pricing info
    """
    import openai
    import os
    from dotenv import load_dotenv
    import json
    import pandas as pd
    import requests
    from datetime import datetime, timezone
    from flask import flash
    
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
                    ],
                },
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
        
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",  # שינוי למודל החזק יותר
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "אנא נתח את התמונה הבאה והפק את פרטי הקופון:",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/{image_format};base64,{base64_image}",
                                    "detail": "high",
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                functions=functions,
                function_call={"name": "coupon_details"},
                max_tokens=1000,
            )
            
            if "choices" in response and len(response["choices"]) > 0:
                choice = response["choices"][0]
                if "message" in choice and "function_call" in choice["message"]:
                    function_call = choice["message"]["function_call"]
                    if "arguments" in function_call:
                        response_data = function_call["arguments"]
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
                "prompt_tokens": response["usage"]["prompt_tokens"],
                "completion_tokens": response["usage"]["completion_tokens"],
                "total_tokens": response["usage"]["total_tokens"],
                "id": response["id"],
                "object": response["object"],
                "created": datetime.fromtimestamp(
                    response["created"], tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "model": response["model"],
                "prompt_text": prompt,
                "response_text": json.dumps(coupon_data, ensure_ascii=False),
            }
            
            try:
                exchange_rate_response = requests.get(
                    "https://api.exchangerate-api.com/v4/latest/USD"
                )
                exchange_rate_data = exchange_rate_response.json()
                usd_to_ils_rate = exchange_rate_data["rates"]["ILS"]
            except Exception:
                usd_to_ils_rate = 3.75
            
            pricing_data["cost_usd"] = pricing_data["total_tokens"] * 0.00004
            pricing_data["cost_ils"] = pricing_data["cost_usd"] * usd_to_ils_rate
            pricing_data["exchange_rate"] = usd_to_ils_rate
            pricing_df = pd.DataFrame([pricing_data])
            
            return coupon_df, pricing_df
            
        except openai.error.RateLimitError:
            # Send email in case of quota exceeded
            recipients = ["couponmasteril2@gmail.com", "itayk93@gmail.com"]
            for recipient in recipients:
                send_email(
                    sender_email="noreply@couponmasteril.com",
                    sender_name="Coupon Master System",
                    recipient_email=recipient,
                    recipient_name="Admin",
                    subject="⚠️ חריגה ממכסת OpenAI - ניתוח קופון מתמונה",
                    html_content=f"""
                    <h2>התראת מערכת - חרגת ממכסת OpenAI</h2>
                    <p>ניסיון לנתח קופון מתוך תמונה נכשל עקב חריגה ממכסת השימוש.</p>
                    <p><strong>מועד האירוע:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
                    <br>
                    <p>בברכה,<br>מערכת Coupon Master</p>
                    """,
                )
            flash("הגעת למכסת השימוש שלך ב-OpenAI. יש לפנות למנהל התוכנה.", "danger")
            return pd.DataFrame(), pd.DataFrame()
            
        except openai.error.OpenAIError as e:
            flash("אירעה שגיאה ב-OpenAI. יש לפנות למנהל התוכנה.", "danger")
            print(f"❌ שגיאת OpenAI: {str(e)}")
            return pd.DataFrame(), pd.DataFrame()
            
        except Exception as e:
            flash("שגיאה כללית בעת עיבוד התמונה. נסה שוב מאוחר יותר.", "danger")
            print(f"❌ שגיאה כללית: {str(e)}")
            return pd.DataFrame(), pd.DataFrame()
            
    except Exception as e:
        print(f"❌ שגיאה כללית בפונקציית base64: {str(e)}")
        return pd.DataFrame(), pd.DataFrame()


def send_coupon_purchase_request_email(seller, buyer, coupon):
    """
    Sends an email to the seller when a buyer requests to purchase a coupon.

    :param seller: The seller's User object
    :param buyer: The buyer's User object
    :param coupon: The Coupon object to be purchased
    """
    sender_email = SENDER_EMAIL
    sender_name = SENDER_NAME
    recipient_email = seller.email
    recipient_name = f"{seller.first_name} {seller.last_name}"
    subject = "בקשה חדשה לקופון שלך"

    # The email template is expected to be in templates/emails/new_coupon_request.html
    html_content = render_template(
        "emails/new_coupon_request.html",
        seller=seller,
        buyer=buyer,
        coupon=coupon,
        buyer_gender=buyer.gender,
        seller_gender=seller.gender,
    )

    send_email(
        sender_email=sender_email,
        sender_name=sender_name,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        subject=subject,
        # subject=f"{subject} - {datetime.now().strftime('%d%m%Y %H:%M')}",
        html_content=html_content,
    )


def update_coupon_status(coupon):
    try:
        current_date = datetime.now(timezone.utc).date()
        status = "פעיל"

        # Ensure coupon.expiration is a date object for comparison
        if coupon.expiration:
            if isinstance(coupon.expiration, date):
                expiration_date = coupon.expiration
            else:
                try:
                    expiration_date = datetime.strptime(
                        coupon.expiration, "%Y-%m-%d"
                    ).date()
                except ValueError as ve:
                    logger.error(
                        f"Invalid date format for coupon {coupon.id}: {coupon.expiration}"
                    )
                    expiration_date = None

            if expiration_date and current_date > expiration_date:
                status = "פג תוקף"
                # Check if notification was already sent
                if not coupon.notification_sent_pagh_tokev:
                    coupon.notification_sent_pagh_tokev = True
                    """""" """
                    notification = Notification(
                        user_id=coupon.user_id,
                        message=f"הקופון {coupon.code} פג תוקף.",
                        link=url_for('coupons.coupon_detail', id=coupon.id)
                    )
                    db.session.add(notification)
                    """ """"""

        # Check if fully used
        if coupon.used_value >= coupon.value:
            status = "נוצל"
            coupon.notification_sent_nutzel = True
            # Check if notification was already sent
            """""" """
            if not coupon.notification_sent_nutzel:
                notification = Notification(
                    user_id=coupon.user_id,
                    message=f"הקופון {coupon.code} נוצל במלואו.",
                    link=url_for('coupons.coupon_detail', id=coupon.id)
                )
                db.session.add(notification)
                """ """"""

        if coupon.status != status:
            coupon.status = status
            logger.info(f"Coupon {coupon.id} status updated to {status}")

    except Exception as e:
        logger.error(f"Error in update_coupon_status for coupon {coupon.id}: {e}")


DEBUG_PRINT = True  # Set to True to enable debug prints, False to disable


def process_coupons_excel(file_path, user):
    """
    Processes an Excel file containing coupon data and adds the coupons to the database.

    :param file_path: The path to the Excel file.
    :param user: The user who is uploading the coupons.
    :return: A tuple containing:
       1) invalid_coupons: List of errors in rows that failed to be added,
       2) missing_optional_fields_messages: List of messages about missing optional fields,
       3) new_coupons: List of Coupon objects that were successfully added to the database.
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
        # Read the Excel file with dtype as string to avoid NaT or unwanted type issues
        df = pd.read_excel(file_path, dtype=str)

        # Load existing tags from the database (cache them in a dict by name)
        existing_tags = {tag.name: tag for tag in Tag.query.all()}
        cache_tags = existing_tags.copy()

        invalid_coupons = []
        missing_optional_fields_messages = []
        new_coupons = []

        for index, row in df.iterrows():
            try:
                # Reading the coupon data from the row (as strings)
                # Handle code with nan check
                code_raw = row.get("קוד קופון", "")
                code = "" if pd.isna(code_raw) else str(code_raw).strip()
                
                # Handle value with nan check
                value_raw = row.get("ערך מקורי", "")
                value_str = "" if pd.isna(value_raw) else str(value_raw).strip()
                
                # Handle cost with nan check
                cost_raw = row.get("עלות", "")
                cost_str = "" if pd.isna(cost_raw) else str(cost_raw).strip()
                
                # Handle company name with nan check
                company_raw = row.get("חברה", "")
                company_name = "" if pd.isna(company_raw) else str(company_raw).strip()
                # Handle description with nan check
                description_raw = row.get("תיאור", "")
                description = "" if pd.isna(description_raw) else str(description_raw).strip()
                
                # Handle date string with nan check
                date_raw = row.get("תאריך תפוגה", "")
                date_str = "" if pd.isna(date_raw) else str(date_raw).strip()

                # Reading additional fields with nan checks
                one_time_raw = row.get("קוד לשימוש חד פעמי", "False")
                one_time_str = "False" if pd.isna(one_time_raw) else str(one_time_raw).strip()
                
                # Handle purpose with nan check
                purpose_raw = row.get("מטרת הקופון", "")
                purpose = "" if pd.isna(purpose_raw) else str(purpose_raw).strip()
                
                # Handle tags with nan check
                tags_raw = row.get("תגיות", "")
                tags_field = "" if pd.isna(tags_raw) else str(tags_raw).strip()

                # *** New fields with proper nan handling ***
                source_raw = row.get("מאיפה קיבלת את הקופון", "")
                source_val = "" if pd.isna(source_raw) else str(source_raw).strip()
                
                buyme_url_raw = row.get("כתובת URL של הקופון ל-BuyMe", "")
                buyme_url_val = "" if pd.isna(buyme_url_raw) else str(buyme_url_raw).strip()
                
                strauss_url_raw = row.get("כתובת URL של הקופון שטראוס פלוס", "")
                strauss_url_val = "" if pd.isna(strauss_url_raw) else str(strauss_url_raw).strip()
                
                xgiftcard_url_raw = row.get("כתובת URL של הקופון מXgiftcard", "")
                xgiftcard_url_val = "" if pd.isna(xgiftcard_url_raw) else str(xgiftcard_url_raw).strip()

                # Check for missing fields
                missing_fields = []
                if not code:
                    missing_fields.append("קוד קופון")
                if not value_str:
                    missing_fields.append("ערך מקורי")
                if not cost_str:
                    missing_fields.append("עלות")
                if not company_name:
                    missing_fields.append("חברה")

                if missing_fields:
                    invalid_coupons.append(
                        f'שורה {index + 2}: חסרים שדות חובה: {", ".join(missing_fields)}'
                    )
                    continue

                # Try to convert value and cost to floats
                try:
                    # Ensure value_str is stripped if it is a string
                    if isinstance(value_str, str):
                        value_str = value_str.strip()
                    value = float(value_str) if value_str else 0.0
                except ValueError:
                    invalid_coupons.append(
                        f"שורה {index + 2}: ערך מקורי אינו מספר תקין ({value_str})."
                    )
                    continue

                try:
                    # Ensure cost_str is stripped if it is a string
                    if isinstance(cost_str, str):
                        cost_str = cost_str.strip()
                    cost = float(cost_str) if cost_str else 0.0
                except ValueError:
                    invalid_coupons.append(
                        f"שורה {index + 2}: עלות אינה מספר תקין ({cost_str})."
                    )
                    continue

                # Parse expiration date
                try:
                    if not date_str.strip():
                        expiration = None
                    else:
                        expiration = None
                        possible_formats = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]
                        for fmt in possible_formats:
                            try:
                                dt = datetime.strptime(date_str, fmt)
                                expiration = dt.date()
                                break
                            except ValueError:
                                pass
                        if expiration is None:
                            missing_optional_fields_messages.append(
                                f'שורה {index + 2}: תאריך תפוגה בפורמט לא תקין (הוזן "{date_str}"). הוגדר כ-None.'
                            )
                            expiration = None
                except Exception as e:
                    expiration = None

                # Handle one_time as a boolean
                is_one_time = False
                if isinstance(one_time_str, bool):
                    is_one_time = one_time_str
                else:
                    lower_str = one_time_str.lower().strip()
                    if lower_str in ["true", "1", "כן"]:
                        is_one_time = True
                    else:
                        is_one_time = False

                # Handle the company: create it if it doesn't exist
                company = Company.query.filter_by(name=company_name).first()
                if not company:
                    company = Company(name=company_name, image_path="default_logo.png")
                    db.session.add(company)

                # Handle tags: find the most common tag or create a new one
                most_common_tag = (
                    db.session.query(Tag)
                    .join(coupon_tags, Tag.id == coupon_tags.c.tag_id)
                    .join(Coupon, Coupon.id == coupon_tags.c.coupon_id)
                    .filter(func.lower(Coupon.company) == func.lower(company_name))
                    .group_by(Tag.id)
                    .order_by(func.count(Tag.id).desc())
                    .first()
                )

                if not most_common_tag:
                    tag_name_for_company = f"Tag for {company_name}"
                    most_common_tag = Tag(name=tag_name_for_company, count=1)
                    db.session.add(most_common_tag)
                else:
                    most_common_tag.count += 1

                # Create the coupon and add it to the session
                new_coupon = Coupon(
                    code=code,
                    value=value,
                    cost=cost,
                    company=company.name,
                    description=str(description),
                    expiration=expiration,
                    user_id=user.id,
                    status="פעיל",  # Default status
                    is_one_time=is_one_time,
                    purpose=purpose,
                    source=source_val,  # The new value
                    buyme_coupon_url=buyme_url_val,  # The new value
                    strauss_coupon_url=strauss_url_val,  # The new value
                    xgiftcard_coupon_url=xgiftcard_url_val,  # The new value
                )
                new_coupon.tags.append(most_common_tag)
                db.session.add(new_coupon)
                new_coupons.append(new_coupon)

            except Exception as e:
                invalid_coupons.append(f"שורה {index + 2}: {str(e)}")

        # Commit all changes to the database
        db.session.commit()

        # Remove the processed file
        os.remove(file_path)

        # Flash messages
        if new_coupons:
            flash(
                f"הקופונים הבאים נטענו בהצלחה: {[coupon.code for coupon in new_coupons]}",
                "success",
            )

        if invalid_coupons:
            flash(
                "טעינת הקופונים נכשלה עבור השורות הבאות:<br>"
                + "<br>".join(invalid_coupons),
                "danger",
            )

        if missing_optional_fields_messages:
            flash(
                "הערות בנוגע לשדות אופציונליים:<br>"
                + "<br>".join(missing_optional_fields_messages),
                "warning",
            )

        return invalid_coupons, missing_optional_fields_messages, new_coupons

    except Exception as e:
        db.session.rollback()
        flash(f"אירעה שגיאה כללית: {str(e)}", "danger")
        raise e  # Re-raise exception to handle it in the calling function


def complete_transaction(transaction):
    try:
        coupon = transaction.coupon
        # Transfer ownership of the coupon to the buyer
        coupon.user_id = transaction.buyer_id
        # The coupon is no longer for sale
        coupon.is_for_sale = False
        # The coupon is now available again
        coupon.is_available = True

        # Update transaction status
        transaction.status = "הושלם"

        # Add notifications for both parties, log, etc.
        notification_buyer = Notification(
            user_id=transaction.buyer_id,
            message="הקופון הועבר לחשבונך.",
            link=url_for("transactions.coupon_detail", id=coupon.id),
        )
        notification_seller = Notification(
            user_id=transaction.seller_id,
            message="העסקה הושלמה והקופון הועבר לקונה.",
            link=url_for("transactions.my_transactions"),
        )

        db.session.add(notification_buyer)
        db.session.add(notification_seller)

        db.session.commit()
        flash("העסקה הושלמה בהצלחה והקופון הועבר לקונה!", "success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error completing transaction {transaction.id}: {e}")
        flash("אירעה שגיאה בעת השלמת העסקה. נא לנסות שוב.", "danger")


# -----------------------------------------------------------------------------
# Function to get the most common tag for a given company
# -----------------------------------------------------------------------------
def get_most_common_tag_for_company(company_name):
    """
    Finds the most common tag in coupons for the company with the given name
    """
    results = (
        db.session.query(Tag, func.count(Tag.id).label("tag_count"))
        .join(coupon_tags, Tag.id == coupon_tags.c.tag_id)
        .join(Coupon, Coupon.id == coupon_tags.c.coupon_id)
        .filter(func.lower(Coupon.company) == func.lower(company_name))
        .group_by(Tag.id)
        .order_by(func.count(Tag.id).desc(), Tag.id.asc())
        .all()
    )

    if results:
        # The first item in the list is the most common tag
        # print("[DEBUG] get_most_common_tag_for_company results =>", results)  # Debug output
        return results[0][0]
    else:
        # No tags match this company
        return None


def get_public_ip():
    try:
        response = requests.get("https://api.ipify.org?format=json")
        if response.status_code == 200:
            data = response.json()
            return data["ip"]
        else:
            print(f"Failed to get IP. Status code: {response.status_code}")
            return None
    except requests.RequestException as e:
        print(f"An error occurred: {e}")
        return None


def get_geo_location(ip_address):
    if not ip_address or not API_KEY:
        return {
            "city": None,
            "region": None,
            "country": None,
            "loc": None,
            "org": None,
            "timezone": None,
        }

    try:
        response = requests.get(
            f"https://ipinfo.io/{ip_address}/json?token={API_KEY}", timeout=5
        )
        response.raise_for_status()
        data = response.json()

        return {
            "city": data.get("city", None),
            "region": data.get("region", None),
            "country": data.get("country", None),
            "loc": data.get("loc", None),
            "org": data.get("org", None),
            "timezone": data.get("timezone", None),
        }

    except requests.RequestException as e:
        current_app.logger.error(f"Error retrieving geo location: {e}")
        return {
            "city": None,
            "region": None,
            "country": None,
            "loc": None,
            "org": None,
            "timezone": None,
        }


# app/helpers.py


def send_password_reset_email(user):
    try:
        token = generate_confirmation_token(user.email)
        reset_url = request.host_url.rstrip("/") + url_for(
            "auth.reset_password", token=token
        )
        html = render_template(
            "emails/password_reset_email.html", user=user, reset_link=reset_url
        )

        sender_email = "noreply@couponmasteril.com"
        sender_name = "Coupon Master"
        recipient_email = user.email
        recipient_name = user.first_name
        subject = "בקשת שחזור סיסמה - Coupon Master"

        # print(f"שליחת מייל שחזור לכתובת: {recipient_email}")
        # print(f"קישור שחזור: {reset_url}")

        response = send_email(
            sender_email=sender_email,
            sender_name=sender_name,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            subject=subject,
            html_content=html,
        )

        # print(f"תשובת השרת לשליחת המייל: {response}")

    except Exception as e:
        print(f"שגיאה בשליחת מייל שחזור סיסמה: {e}")


# app/helpers.py


def generate_password_reset_token(email, expiration=3600):
    """
    Creates a Time-Limited token for password reset.
    :param email: The email to which the token is linked
    :param expiration: Token validity duration in seconds (default: 3600 = 1 hour)
    :return: Signed token
    """
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return s.dumps(email, salt=current_app.config["SECURITY_PASSWORD_SALT"])


def confirm_password_reset_token(token, expiration=3600):
    """
    Checks the validity of the token and its expiration date for password reset.

    :param token: The token received in the URL
    :param expiration: Token validity duration in seconds (default: 3600 = 1 hour)
    :return: Email address if valid, otherwise raises an exception
    """
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    email = s.loads(
        token, salt=current_app.config["SECURITY_PASSWORD_SALT"], max_age=expiration
    )
    return email


def parse_user_usage_text(usage_text, user):
    openai.api_key = os.getenv("OPENAI_API_KEY")

    # Retrieve list of allowed companies from the system
    companies = {
        c.name.lower(): c.name for c in Company.query.all()
    }  # Dictionary for easy lookup
    companies_str = ", ".join(companies.keys())

    # Prompt that requires using only existing companies
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
    שים לב שאם אתה מקבל שם באנגלית - תבדוק גם את הגרסה בעברית ואת הגרסה באנגלית. ואם אתה מקבל שם בעברית - תבדוק גם את הגרסה באנגלית וגם את הגרסה בעברית.
    """

    prompt = f"""
    Here is a text describing coupon usage:
    \"\"\"{usage_text}\"\"\"

    You must return only companies from the existing list:
    {companies_str}

    **VERY IMPORTANT**: Be flexible when identifying company names - users may enter names with spelling errors or different spellings. Examples:
    - "קרפור" should be identified as "Carrefour"
    - "סופר סל" should be identified as "שופרסל" 
    - "גוד פארם" should be identified as "GoodPharm"
    - "פרי פיט" should be identified as "FreeFit"
    - "מקדונלד" or "מקדונלדז" should be identified as "מקדונלדס"
    - "ביי מי" should be identified as "BuyMe"
    - "וולט" should be identified as "Wolt"
    - "רולדין" or "roladin" should be matched correctly regardless of language

    In general, look for close matches even if spelling is incorrect, when comparing between English and Hebrew, or if letters are missing/extra.
    If the name is written inaccurately, note this in additional_info and ensure you return the correct company name.

    Each object in the output contains:
    - company: The company name **as it appears** in the list (do not invent names!)
    - amount_used: The amount used in NIS
    - coupon_value: The full value of the coupon (if in the text, otherwise empty)
    - additional_info: Additional description from the user

    Example output:
    [
      {{"company": "איקאה", "amount_used": 50, "coupon_value": 100, "additional_info": "Bought a chair"}},
      {{"company": "קרפור", "amount_used": 75, "coupon_value": null, "additional_info": "Grocery shopping"}}
    ]
    """
    # Call the GPT API
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",  # שינוי למודל החזק יותר
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
                                            "description": "שם החברה מתוך הרשימה בלבד",
                                        },
                                        "amount_used": {
                                            "type": "number",
                                            "description": 'כמה ש"ח נוצלו',
                                        },
                                        "coupon_value": {
                                            "type": ["number", "null"],
                                            "description": "כמה המשתמש שילם על הקופון (אם מופיע בטקסט, אחרת ריק)",
                                        },
                                        "additional_info": {
                                            "type": "string",
                                            "description": "פירוט נוסף על העסקה",
                                        },
                                    },
                                    "required": [
                                        "company",
                                        "amount_used",
                                        "coupon_value",
                                        "additional_info",
                                    ],
                                },
                            }
                        },
                        "required": ["usages"],
                    },
                }
            ],
        )

        # Extract the arguments
        content = response["choices"][0]["message"]["function_call"]["arguments"]

        # Try to convert the response to JSON
        try:
            usage_data = json.loads(content)
            usage_list = usage_data.get("usages", [])
        except json.JSONDecodeError:
            usage_list = []

        # Filter out companies not in the list
        print(usage_list)

        # Create DataFrame
        usage_df = pd.DataFrame(usage_list)

        # Process additional information for cost calculation
        usage_record = {
            "id": response["id"],
            "object": response["object"],
            "created": dt.utcfromtimestamp(response["created"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "model": response["model"],
            "prompt_tokens": response["usage"]["prompt_tokens"],
            "completion_tokens": response["usage"]["completion_tokens"],
            "total_tokens": response["usage"]["total_tokens"],
            "cost_usd": 0.0,  # Calculate based on your formula
            "cost_ils": 0.0,
            "exchange_rate": 3.75,
            "prompt_text": prompt,
            "response_text": content,
        }
        pricing_df = pd.DataFrame([usage_record])

        return usage_df, pricing_df

    except openai.error.RateLimitError:
        # **🚨 Handling case of exceeding usage limit 🚨**
        error_message = "⚠️ אזהרה: הגעת למכסת השימוש שלך ב-OpenAI. יש לפנות למנהל התוכנה להמשך טיפול."
        flash(error_message, "warning")
        print(error_message)

        # **📧 Sending automatic email to 2 admins:**
        recipients = ["couponmasteril2@gmail.com", "itayk93@gmail.com"]
        for recipient in recipients:
            send_email(
                sender_email="noreply@couponmasteril.com",
                sender_name="Coupon Master System",
                recipient_email=recipient,
                recipient_name="Admin",
                subject="⚠️ חריגה ממכסת OpenAI במערכת הקופונים",
                html_content="""
                <h2>התראת מערכת - חרגת ממכסת השימוש של OpenAI</h2>
                <p>שלום,</p>
                <p>נראה כי חרגת מהמכסה הזמינה ב-OpenAI, מה שמונע מהמערכת להמשיך לפעול כראוי.</p>
                <p>יש לבדוק את חשבון OpenAI ולעדכן את המכסה כדי להחזיר את המערכת לפעולה תקינה.</p>
                <p><strong>מועד האירוע:</strong> {}</p>
                <br>
                <p>בברכה,<br>מערכת Coupon Master</p>
                """.format(
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ),
            )

        return pd.DataFrame(), pd.DataFrame()

    except openai.error.OpenAIError as e:
        error_message = f"❌ שגיאת OpenAI: {str(e)}. יש לפנות למנהל התוכנה."
        flash(error_message, "danger")
        print(error_message)
        return pd.DataFrame(), pd.DataFrame()

    except Exception as e:
        error_message = f"❌ שגיאה כללית: {str(e)}. יש לפנות למנהל התוכנה."
        flash(error_message, "danger")
        print(error_message)
        return pd.DataFrame(), pd.DataFrame()


def decrypt_coupon_code(encrypted_code):
    try:
        encryption_key = os.getenv("ENCRYPTION_KEY")
        if not encryption_key:
            logging.error("ENCRYPTION_KEY not found in environment variables.")
            return None  # Return None if key is missing

        # Use your decryption function
        decrypted_code = some_decryption_function(encrypted_code, encryption_key)
        return decrypted_code
    except Exception as e:
        logging.error(f"Error decrypting coupon code: {e}")
        return None  # Return None instead of flashing a message


def get_greeting():
    israel_tz = pytz.timezone("Asia/Jerusalem")
    current_hour = datetime.now(israel_tz).hour

    if current_hour < 12:
        return "בוקר טוב"
    elif current_hour < 18:
        return "צהריים טובים"
    else:
        return "ערב טוב"


def has_feature_access(feature_name, user):
    """
    Checks user's access to a specific feature based on feature_access table:
    - If there's no row for feature_name => return False (closed to everyone)
    - If access_mode='V' => return True (open to everyone)
    - If access_mode='Admin' => return True only if user.is_admin
    - Otherwise return False
    """
    from app.models import FeatureAccess

    feature = FeatureAccess.query.filter_by(feature_name=feature_name).first()
    if not feature:
        # If no record exists => closed
        return False

    mode = feature.access_mode

    # If the user is anonymous (not logged in)
    if not user.is_authenticated:
        # If the feature is 'V' (open to everyone) => allow it for anonymous users too
        return mode == "V"

    # If the user is logged in:
    if mode == "V":
        return True
    elif mode == "Admin":
        return bool(user.is_admin)
    else:
        # ערך אחר (כולל NULL) => סגור לכולם
        return False


def send_password_change_email(user, token):
    """
    שליחת מייל אישור שינוי סיסמא.
    """
    try:
        confirmation_link = url_for(
            "profile.confirm_password_change", token=token, _external=True
        )

        html_content = render_template(
            "emails/password_change_confirmation.html",
            user=user,
            confirmation_link=confirmation_link,
        )

        send_email(
            sender_email="noreply@couponmasteril.com",
            sender_name="Coupon Master",
            recipient_email=user.email,
            recipient_name=f"{user.first_name} {user.last_name}",
            subject="אישור שינוי סיסמא - Coupon Master",
            html_content=html_content,
        )
        return True
    except Exception as e:
        current_app.logger.error(f"Error sending password change email: {str(e)}")
        return False


def get_current_month_year_hebrew():
    """
    Returns the current month and year in Hebrew, e.g., 'מאי 2024'.
    """
    import datetime
    months = [
        'ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני',
        'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'
    ]
    now = datetime.datetime.now()
    month_name = months[now.month - 1]
    return f"{month_name} {now.year}"


# ----------------------------------------------------------------
# Playwright-based coupon data retrieval
# ----------------------------------------------------------------

def get_coupon_data_with_playwright(coupon, max_retries=3, save_directory="automatic_coupon_update/input_html"):
    """
    Wrapper function for get_coupon_data_playwright with retry mechanism and advanced logging
    """
    if not PLAYWRIGHT_AVAILABLE:
        logging.error("Playwright is not available. Please install it with: pip install playwright")
        return None
        
    import time
    import logging
    import os
    from datetime import datetime
    
    # Configure logger for multipass updates
    logger = logging.getLogger('playwright_updater')
    if not logger.handlers:
        # Create logs directory if it doesn't exist
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        handler = logging.FileHandler('logs/playwright_update.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    total_start_time = datetime.now()
    logger.info(f"Starting update process for coupon {coupon.code} ({coupon.auto_download_details})")
    
    for attempt in range(max_retries):
        attempt_start = datetime.now()
        
        try:
            logger.info(f"Attempt {attempt + 1}/{max_retries} for coupon {coupon.code}")
            
            result = get_coupon_data_playwright(coupon, save_directory)
            
            if result is not None:
                attempt_duration = (datetime.now() - attempt_start).total_seconds()
                total_duration = (datetime.now() - total_start_time).total_seconds()
                
                # Check if DataFrame is empty (no new data) vs has data
                records_count = len(result) if hasattr(result, '__len__') else 0
                if records_count > 0:
                    logger.info(f"✅ SUCCESS: Coupon {coupon.code} updated successfully (attempt duration: {attempt_duration:.2f}s, total: {total_duration:.2f}s)")
                    logger.info(f"   - Records found: {records_count}")
                else:
                    logger.info(f"✅ SUCCESS: Coupon {coupon.code} processed successfully (no new data, attempt duration: {attempt_duration:.2f}s, total: {total_duration:.2f}s)")
                    logger.info(f"   - No new transactions found (all data already exists)")
                
                return result
            else:
                attempt_duration = (datetime.now() - attempt_start).total_seconds()
                logger.warning(f"❌ No data returned for coupon {coupon.code} on attempt {attempt + 1} (duration: {attempt_duration:.2f}s)")
                
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)  # Progressive backoff: 5s, 10s, 15s
                    logger.info(f"   - Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    
        except Exception as e:
            attempt_duration = (datetime.now() - attempt_start).total_seconds()
            logger.error(f"💥 Error on attempt {attempt + 1} for coupon {coupon.code}: {str(e)} (duration: {attempt_duration:.2f}s)")
            
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)
                logger.info(f"   - Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
    
    # All attempts failed
    total_duration = (datetime.now() - total_start_time).total_seconds()
    logger.error(f"🚫 FINAL FAILURE: All {max_retries} attempts failed for coupon {coupon.code} (total duration: {total_duration:.2f}s)")
    return None


def get_coupon_data_playwright(coupon, save_directory="automatic_coupon_update/input_html"):
    """
    Get coupon data using Playwright instead of Selenium
    """
    if not PLAYWRIGHT_AVAILABLE:
        logging.error("Playwright is not available. Please install it with: pip install playwright")
        return None
        
    import os
    from datetime import datetime
    import pandas as pd
    
    # Helper function to print debug messages when DEBUG_MODE is enabled
    def debug_print(message):
        if DEBUG_MODE:
            print(f"[PLAYWRIGHT DEBUG] {message}")
    
    debug_print(f"Starting coupon data retrieval with Playwright for coupon: {coupon.code}")
    
    # Ensure that the save directory exists
    os.makedirs(save_directory, exist_ok=True)
    
    coupon_number = coupon.code
    coupon_kind = coupon.auto_download_details or "Unknown"
    
    debug_print(f"Coupon kind detected: {coupon_kind}")
    
    with sync_playwright() as p:
        # Launch browser - headless only in production or if explicitly set
        is_headless = os.getenv('FLASK_ENV') == 'production' or os.getenv('SELENIUM_HEADLESS', 'false').lower() == 'true'
        browser = p.chromium.launch(
            headless=is_headless,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-features=VizDisplayCompositor'
            ]
        )
        
        try:
            page = browser.new_page()
            
            # Set viewport size
            page.set_viewport_size({"width": 1920, "height": 1080})
            
            debug_print("Playwright browser launched successfully")
            
            df = None  # DataFrame to hold the scraped data
            
            # -------------------- Handling Multipass Scenario --------------------
            if coupon_kind == "Multipass":
                debug_print("Processing Multipass coupon")
                
                try:
                    # Navigate to Multipass website
                    page.goto("https://multipass.co.il/%d7%91%d7%a8%d7%95%d7%a8-%d7%99%d7%aa%d7%a8%d7%94/", 
                             wait_until="domcontentloaded", timeout=120000)
                    debug_print("Navigated to Multipass website")
                    
                    # Wait for the card number input field
                    page.wait_for_selector("input#newcardid", timeout=120000)
                    debug_print("Found card number input field")
                    
                    # Clear and enter coupon number
                    cleaned_coupon_number = str(coupon_number).replace("-", "")
                    page.fill("input#newcardid", cleaned_coupon_number)
                    debug_print(f"Entered coupon number: {cleaned_coupon_number}")
                    
                    # Handle reCAPTCHA
                    debug_print("Handling reCAPTCHA")
                    # Wait for reCAPTCHA iframe
                    page.wait_for_selector("iframe[src*='recaptcha']", timeout=120000)
                    
                    # Switch to reCAPTCHA frame and click checkbox
                    recaptcha_frame = page.frame_locator("iframe[src*='recaptcha']")
                    recaptcha_frame.locator(".recaptcha-checkbox-border").click()
                    debug_print("Clicked reCAPTCHA checkbox")
                    
                    # Wait a moment for reCAPTCHA processing
                    page.wait_for_timeout(3000)
                    
                    # Click the submit button
                    page.click("input[type='submit'][value='בדוק יתרה']")
                    debug_print("Clicked submit button")
                    
                    # Wait for results
                    page.wait_for_timeout(5000)
                    
                    # Save HTML content
                    page_html = page.content()
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"multipass_{coupon_number}_{timestamp}.html"
                    file_path = os.path.join(save_directory, filename)
                    debug_print(f"Saving page HTML to {file_path}")
                    with open(file_path, "w", encoding="utf-8") as file:
                        file.write(page_html)
                    
                    # Extract balance information
                    # Look for balance text patterns
                    balance_text = page.inner_text("body")
                    debug_print("Extracted page text for balance parsing")
                    
                    # Parse balance from text (adapt this based on actual Multipass response)
                    usage_amount = 0.0
                    # Add your balance parsing logic here based on the actual HTML structure
                    
                    df = pd.DataFrame({
                        'usage_amount': [usage_amount],
                        'timestamp': [datetime.now()],
                        'method': ['Playwright']
                    })
                    
                    debug_print(f"Created DataFrame with usage_amount: {usage_amount}")
                    
                except Exception as e:
                    debug_print(f"Error in Multipass processing: {str(e)}")
                    return None
            
            # -------------------- Handling BuyMe Scenario --------------------
            elif coupon_kind == "BuyMe":
                debug_print("Processing BuyMe coupon")
                
                try:
                    # Navigate to BuyMe balance check page
                    page.goto("https://www.buyme.co.il/YitratKartis/CheckBalance", 
                             wait_until="domcontentloaded", timeout=15000)
                    debug_print("Navigated to BuyMe website")
                    
                    # Wait for and fill the card number input
                    page.wait_for_selector("input[name='GiftCardNumber']", timeout=15000)
                    page.fill("input[name='GiftCardNumber']", coupon_number)
                    debug_print(f"Entered coupon number: {coupon_number}")
                    
                    # Submit the form
                    page.click("input[type='submit']")
                    debug_print("Clicked submit button")
                    
                    # Wait for results
                    page.wait_for_timeout(5000)
                    
                    # Save HTML before processing
                    before_html = page.content()
                    before_file = os.path.join(save_directory, f"buyme_before_{coupon_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
                    with open(before_file, "w", encoding="utf-8") as f:
                        f.write(before_html)
                    
                    # Look for "Show Details" or similar button and click it
                    try:
                        page.click("text=הצג פרטי שימוש", timeout=15000)
                        debug_print("Clicked show details button")
                        page.wait_for_timeout(3000)
                        
                        # Save HTML after showing details
                        after_html = page.content()
                        after_file = os.path.join(save_directory, f"buyme_after_{coupon_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
                        with open(after_file, "w", encoding="utf-8") as f:
                            f.write(after_html)
                            
                    except Exception:
                        debug_print("No show details button found or failed to click")
                    
                    # Extract usage information from the page
                    page_text = page.inner_text("body")
                    debug_print("Extracted page text for usage parsing")
                    
                    # Parse usage data (adapt based on actual BuyMe structure)
                    usage_amount = 0.0
                    # Add your usage parsing logic here
                    
                    df = pd.DataFrame({
                        'usage_amount': [usage_amount],
                        'timestamp': [datetime.now()],
                        'method': ['Playwright']
                    })
                    
                    debug_print(f"Created DataFrame with usage_amount: {usage_amount}")
                    
                except Exception as e:
                    debug_print(f"Error in BuyMe processing: {str(e)}")
                    return None
            
            # -------------------- Handling Max Scenario --------------------
            elif coupon_kind == "Max":
                debug_print("Max coupon type not yet implemented with Playwright")
                return None
            
            else:
                debug_print(f"Unknown coupon type: {coupon_kind}")
                return None
                
        except Exception as e:
            debug_print(f"General error in Playwright processing: {str(e)}")
            return None
        finally:
            browser.close()
            debug_print("Browser closed")
    
    return df
