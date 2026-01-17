# הגדרות סביבה מדויקות להפעלת `coupon_manager_project`

המסמך הזה מסביר בדיוק את כל מה שעליך להתקין כדי שהפרויקט יעבוד **באותה גרסה** כמו במקור: גרסת Python, פיפ והספריות עם המינימום המדויק או הפינים כפי שמופיע ב`requirements.txt`.
---

## 1. Python
- להוריד ולהתקין את **Python 3.12.7** (https://www.python.org/downloads/release/python-3127/).  
  - כן להשתמש בגרסת CPython הרשמית, לא בגרסה של מערכת אחרת (למשל לא ב-PyPy).  
  - לאחר ההתקנה, אמת את הגרסה:
    ```bash
    python3 --version  # אמור להחזיר Python 3.12.7
    ```

## 2. pip
- הפיפ שמגיע עם Python 3.12.7 הוא **pip 23.3.1**. לאחר ההתקנה הראשונית נעשה לו נעילה כך:
  ```bash
  python3 -m pip install --upgrade pip==23.3.1
  python3 -m pip --version  # אמור להחזיר pip 23.3.1
  ```
- זה מונע שינויים אוטומטיים שעלולים לשבור תלותות בדיוק.

## 3. יצירת סביבה וירטואלית
```bash
cd "/Users/itaykarkason/Python Projects/coupon_manager_project"
python3 -m venv .venv
source .venv/bin/activate  # ב-Windows: .venv\Scripts\activate
python -m pip install --upgrade pip==23.3.1  # לוודא ש-pip מתעדכן גם בתוך הסביבה
```

## 4. רשימת ספריות עם גרסה מדויקת
הגרסאות המדויקות שכבר מופיעות ב`requirements.txt` (או שהן הגרסאות המינימליות שמופיעות עם `>=`) הן המקור הרשמי לאותה "אחידות". להלן ההעתק המדויק של קובץ התלויות:

```
alembic==1.13.3
Flask-Migrate==4.0.7
SQLAlchemy>=2.0.36
pandas>=2.2.0
selenium==4.19.0
playwright>=1.48.0
wtforms==3.0.1
Flask-WTF==1.2.1
requests==2.31.0
itsdangerous==2.2.0
Jinja2==3.1.4
MarkupSafe==2.1.5
Flask-Login==0.6.3
gunicorn
email-validator
openpyxl
psycopg2-binary>=2.9.10
python-dotenv
sib-api-v3-sdk==7.6.0
cryptography
pycryptodome>=3.20.0
fuzzywuzzy==0.18.0
python-Levenshtein>=0.25.0
reportlab==4.2.5
openai==0.28.1
xlsxwriter
thefuzz
plotly
requests-oauthlib==1.3.1
Flask==3.0.3
Werkzeug==3.0.4
Flask-SQLAlchemy==3.1.1
flask-dance==7.1.0
webdriver-manager
flask_mail
python-telegram-bot==20.7
asyncpg>=0.30.0
pytz==2024.1
beautifulsoup4==4.12.3
Pillow>=10.3.0
redis==5.0.0
rq==1.15.1
Flask-Caching==2.1.0
colorlog==6.7.0
# apscheduler - הוסר (החלפת אותו ב-cron חיצוני)
```

> לאחר ההתקנה מומלץ לשמור את הגרסאות המדויקות עם `pip freeze`:
```
pip install -r requirements.txt
pip freeze > requirements.lock
```
הקובץ `requirements.lock` יאכסן את גרסאות החבילות המלאות שלך ויאפס את הסביבה במקרה שתרצה לשחזר אותה בעתיד.

## 5. התקנת התלויות
בצע את ההתקנה מתוך הסביבה הוירטואלית באמצעות:
```bash
pip install -r requirements.txt
```
אם אתה צריך להבטיח גרסה מסוימת מעבר להמתואמת בקובץ, השתמש בפקודה מפורשת:
```bash
pip install package==X.Y.Z
```
לאחר ההתקנה רענן את הנעילה:
```bash
pip freeze > requirements.lock
```

## 6. בדיקות סופיות
1. רענן את הרשימה עם `pip freeze > installed.txt`.
2. השווה את הקובץ `installed.txt` ל-`requirements.lock` ול-`requirements.txt` כדי לוודא התאמות.
3. הרץ את הפקודות הבאות:
   ```bash
   flask db upgrade
   python wsgi.py
   ```

## 7. סיכום
- Python 3.12.7 + pip 23.3.1
- סביבה וירטואלית `.venv`
- `requirements.txt` כבסיס והנחיה ליצירת `requirements.lock` לטעינה מדויקת
- `flask db upgrade` ו-`python wsgi.py` לאימות החיבור
