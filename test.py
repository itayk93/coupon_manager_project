import os
import time
import traceback
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def get_coupon_data(coupon_number, card_exp, cvv, save_directory="/Users/itaykarkason/Desktop/coupon_manager_project/automatic_coupon_update"):
    """
    ממלא את פרטי הכרטיס בטופס באתר Max, לוחץ על "בואו נתקדם",
    מזהה את הטבלה, ממיר אותה ל-DataFrame ושומר כקובץ Excel.
    """
    os.makedirs(save_directory, exist_ok=True)

    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-images")  # מניעת טעינת תמונות
    chrome_options.add_argument("--disable-extensions")  # מניעת הרחבות מיותרות
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")  # חוסם תמונות מהדפדפן
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    print("🚀 הפעלת דפדפן עם הגבלות משאבים...")
    with webdriver.Chrome(options=chrome_options) as driver:
        try:
            driver.get("https://www.max.co.il/gift-card-transactions/main")
            wait = WebDriverWait(driver, 30)

            def safe_find(by, value, timeout=10):
                """ מנסה למצוא אלמנט עם זמן המתנה """
                return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((by, value)))

            print("🔍 מילוי מספר כרטיס...")
            card_number_field = safe_find(By.ID, "giftCardNumber")
            card_number_field.clear()
            card_number_field.send_keys(coupon_number)

            print("🔍 מילוי תוקף...")
            exp_field = safe_find(By.ID, "expDate")
            exp_field.clear()
            exp_field.send_keys(card_exp)

            print("🔍 מילוי CVV...")
            cvv_field = safe_find(By.ID, "cvv")
            cvv_field.clear()
            cvv_field.send_keys(cvv)

            print("✅ הנתונים הוזנו, לוחץ על הכפתור...")
            continue_button = wait.until(EC.element_to_be_clickable((By.ID, "continue")))
            continue_button.click()

            print("⏳ ממתין לטעינת הדף החדש...")
            time.sleep(7)

            print("📊 מזהה את הטבלה בדף...")
            table = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "mat-table")))

            print("✅ טבלה נמצאה, שולף נתונים...")
            headers = [header.text.strip() for header in table.find_elements(By.TAG_NAME, "th")]
            rows = []
            for row in table.find_elements(By.TAG_NAME, "tr")[1:]:  # מדלג על שורת הכותרות
                cells = [cell.text.strip() for cell in row.find_elements(By.TAG_NAME, "td")]
                if cells:
                    rows.append(cells)

            df = pd.DataFrame(rows, columns=headers)

            # Converting date column to datetime
            df["שולם בתאריך"] = pd.to_datetime(df["שולם בתאריך"], format="%d.%m.%Y")

            # Converting currency columns to float
            df["סכום בשקלים"] = df["סכום בשקלים"].str.replace("₪", "").astype(float)
            df["יתרה"] = df["יתרה"].str.replace("₪", "").astype(float)

            # Renaming columns
            df.rename(columns={
                "שולם בתאריך": "transaction_date",
                "שם בית העסק": "location",
                "סכום בשקלים": "amount",
                "יתרה": "balance",
                "פעולה": "action"
            }, inplace=True)

            # Creating new columns for usage and recharge amounts
            df["usage_amount"] = df.apply(lambda x: x["amount"] if x["action"] == "עסקה" else None, axis=1)
            df["recharge_amount"] = df.apply(lambda x: -(x["amount"]) if x["action"] == "טעינה" else None, axis=1)

            df.drop(columns=["action", "הערות"], inplace=True)

            return df

        except Exception as e:
            print(f"❌ שגיאה במהלך שליפת הטבלה: {e}")
            traceback.print_exc()
            return None

# דוגמה לקריאה לפונקציה
if __name__ == "__main__":
    coupon_number = "7221301011968146"
    card_exp = "12/29"
    cvv = "566"
    save_directory = "/Users/itaykarkason/Desktop/coupon_manager_project/automatic_coupon_update"
    file_path = get_coupon_data(coupon_number, card_exp, cvv, save_directory)

    if file_path:
        print(f"🎉 קובץ ה-Excel מוכן: {file_path}")

    file_path = "/Users/itaykarkason/Desktop/coupon_manager_project/automatic_coupon_update/transactions.xlsx"
    df = pd.read_excel(file_path)
    print(df)