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
                chrome_bin = possible_chrome_paths[1]  # Default to google-chrome-stable
                
            chrome_options.binary_location = chrome_bin
            
            driver = webdriver.Chrome(options=chrome_options)
            driver.get(
                "https://multipass.co.il/%d7%91%d7%a8%d7%95%d7%a8-%d7%99%d7%aa%d7%a8%d7%94/"
            )
            wait = WebDriverWait(driver, 30)
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
                chrome_bin = possible_chrome_paths[1]  # Default to google-chrome-stable
                
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
            return None

        # Add new transactions
        for idx, row in df_new.iterrows():
            transaction = CouponTransaction(
                coupon_id=coupon.id,
                transaction_date=row.get("transaction_date"),
                location=row.get("location", ""),
                recharge_amount=row.get("recharge_amount", 0.0),
                usage_amount=row.get("usage_amount", 0.0),
                reference_number=row.get("reference_number", ""),
            )
            db.session.add(transaction)

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
                
                logger.info(f"✅ SUCCESS: Coupon {coupon.code} updated successfully on attempt {attempt + 1}")
                logger.info(f"   - Attempt duration: {attempt_duration:.2f}s")
                logger.info(f"   - Total duration: {total_duration:.2f}s")
                logger.info(f"   - Records found: {len(result) if hasattr(result, '__len__') else 'N/A'}")
                
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


def get_coupon_data(coupon, save_directory="automatic_coupon_update/input_html"):
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
            debug_print("Initializing Selenium for Multipass")
            # Set Chrome binary path - try multiple possible locations
            possible_chrome_paths = [
                os.getenv('CHROME_BIN'),
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
                chrome_bin = possible_chrome_paths[1]  # Default to google-chrome-stable
                debug_print(f"⚠️ No Chrome found, using default: {chrome_bin}")
                
            chrome_options.binary_location = chrome_bin
            debug_print(f"Final Chrome binary setting: {chrome_bin}")
            debug_print("=== END CHROME DEBUG ===")
            
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

            # Handle reCAPTCHA
            debug_print("Handling reCAPTCHA")
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

            check_balance_button = wait.until(
                EC.element_to_be_clickable((By.ID, "submit"))
            )
            if check_balance_button.is_enabled():
                debug_print("Clicking submit button")
                check_balance_button.click()
            else:
                debug_print(
                    "Submit button is disabled. CAPTCHA may not be solved properly."
                )
                driver.quit()
                return None

            wait.until(EC.presence_of_element_located((By.XPATH, "//table")))
            time.sleep(10)

            page_html = driver.page_source
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"coupon_{coupon_number}_{timestamp}.html"
            file_path = os.path.join(save_directory, filename)
            debug_print(f"Saving page HTML to {file_path}")
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(page_html)

        except Exception as e:
            debug_print(
                f"An error occurred during Selenium operations (Multipass): {e}"
            )
            if driver:
                driver.quit()
            return None
        finally:
            if driver:
                driver.quit()

        try:
            debug_print("Reading tables from saved HTML")
            dfs = pd.read_html(file_path)
            os.remove(file_path)
            if not dfs:
                debug_print("No tables found in HTML (Multipass)")
                return None

            df = dfs[0]
            debug_print("Renaming columns for Multipass data")
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
                chrome_bin = possible_chrome_paths[1]  # Default to google-chrome-stable
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
            return None

    # -------------------- Handling BuyMe Scenario --------------------
    elif coupon_kind.lower() == "buyme":
        try:
            debug_print("Initializing Selenium for BuyMe")
            # Import webdriver_manager to manage the Chrome driver
            from webdriver_manager.chrome import ChromeDriverManager

            chrome_options.add_argument("--headless")  # Run in headless mode for production
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-features=VizDisplayCompositor")
            chrome_options.add_argument("--remote-debugging-port=9222")
            
            # Set Chrome binary path - try multiple possible locations
            possible_chrome_paths = [
                os.getenv('CHROME_BIN'),
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
                chrome_bin = possible_chrome_paths[1]  # Default to google-chrome-stable
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
            time.sleep(6)

            # Save the HTML before clicking to load details (coupon code, expiration date, load amount)
            before_click_file = os.path.join(
                save_directory, f"buyme_before_{coupon_number}.html"
            )
            with open(before_click_file, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            debug_print(f"Saved before-click HTML to {before_click_file}")

            # Click the "Where did I redeem" button to load usage details
            try:
                where_used_button = driver.find_element(
                    By.XPATH, "//button[contains(text(), 'איפה מימשתי')]"
                )
                driver.execute_script("arguments[0].click();", where_used_button)
                time.sleep(3)  # Wait for content to load
                debug_print("Clicked 'Where did I redeem' button")
            except Exception as e:
                debug_print(f"Error clicking 'Where did I redeem' button: {e}")
                driver.quit()
                return None

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
            return None

    # -------------------- Unsupported Coupon Type --------------------
    else:
        debug_print(f"Unsupported coupon kind: {coupon_kind}")
        return None

    # -------------------- Common Stage: Database Comparison and Update --------------------
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
            model="gpt-4o-mini",
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
                        model="gpt-4o-mini",
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
                logger.info(f"✅ Successfully retrieved data for coupon {coupon.code} (attempt duration: {attempt_duration:.2f}s, total: {total_duration:.2f}s)")
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
        # Launch browser in headless mode for production
        browser = p.chromium.launch(
            headless=True,
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
                             wait_until="domcontentloaded", timeout=30000)
                    debug_print("Navigated to Multipass website")
                    
                    # Wait for the card number input field
                    page.wait_for_selector("input#newcardid", timeout=30000)
                    debug_print("Found card number input field")
                    
                    # Clear and enter coupon number
                    cleaned_coupon_number = str(coupon_number).replace("-", "")
                    page.fill("input#newcardid", cleaned_coupon_number)
                    debug_print(f"Entered coupon number: {cleaned_coupon_number}")
                    
                    # Handle reCAPTCHA
                    debug_print("Handling reCAPTCHA")
                    # Wait for reCAPTCHA iframe
                    page.wait_for_selector("iframe[src*='recaptcha']", timeout=30000)
                    
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
                             wait_until="domcontentloaded", timeout=30000)
                    debug_print("Navigated to BuyMe website")
                    
                    # Wait for and fill the card number input
                    page.wait_for_selector("input[name='GiftCardNumber']", timeout=30000)
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
                        page.click("text=הצג פרטי שימוש", timeout=10000)
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
