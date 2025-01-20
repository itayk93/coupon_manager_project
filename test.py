import os
import time
import traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def get_coupon_data(coupon_number, card_exp, cvv, save_directory="automatic_coupon_update/input_html"):
    """
    ממלא את פרטי הכרטיס בטופס באתר Max ולוחץ על "בואו נתקדם"

    Parameters:
    coupon_number (str): מספר כרטיס הקופון
    card_exp (str): תוקף הכרטיס בפורמט MM/YY
    cvv (str): CVV של הכרטיס
    save_directory (str): תיקייה לשמירת ה-HTML לאחר שליחת הנתונים

    Returns:
    str: נתיב הקובץ שנשמר
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
        driver.get("https://www.max.co.il/gift-card-transactions/main")
        wait = WebDriverWait(driver, 30)

        # הזנת מספר כרטיס
        card_number_field = wait.until(EC.visibility_of_element_located((By.ID, "giftCardNumber")))
        card_number_field.clear()
        card_number_field.send_keys(coupon_number)

        # הזנת תוקף
        exp_field = wait.until(EC.visibility_of_element_located((By.ID, "expDate")))
        exp_field.clear()
        exp_field.send_keys(card_exp)

        # הזנת CVV
        cvv_field = wait.until(EC.visibility_of_element_located((By.ID, "cvv")))
        cvv_field.clear()
        cvv_field.send_keys(cvv)

        # לחיצה על כפתור 'בואו נתקדם'
        continue_button = wait.until(EC.element_to_be_clickable((By.ID, "continue")))
        continue_button.click()

        print("✅ הנתונים הוזנו והכפתור 'בואו נתקדם' נלחץ בהצלחה!")

        # זמן המתנה לטעינת הדף החדש
        time.sleep(5)
        input()
        # שמירת ה-HTML של הדף החדש
        html_content = driver.page_source
        html_file_path = os.path.join(save_directory, f"coupon_{coupon_number}.html")
        with open(html_file_path, "w", encoding="utf-8") as file:
            file.write(html_content)
        print(f"📄 HTML נשמר ב: {html_file_path}")

    except Exception as e:
        print(f"❌ שגיאה במהלך ביצוע הסקריפט: {e}")
        traceback.print_exc()

    finally:
        driver.quit()

    return html_file_path

# קריאה לפונקציה עם הנתונים והנתיב
coupon_number = "7221301011968146"
card_exp = "1229"
cvv = "466"
save_directory = "/Users/itaykarkason/Desktop/coupon_manager_project/automatic_coupon_update/input_html"

get_coupon_data(coupon_number, card_exp, cvv, save_directory)
