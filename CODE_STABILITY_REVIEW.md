# סקירת יציבות קוד — מסקנות ליישום

## סטטוס יישום (עודכן 2026-06-12)

| # | ממצא | סטטוס |
|---|------|--------|
| 1 | טוקנים מבוססי hash() | ✅ תוקן — HMAC ב-`app/utils/tokens.py`, מימוש יחיד |
| 2 | Scheduler לכל worker | ✅ תוקן — ברירת מחדל כבוי + נעילת flock |
| 3 | בוט טלגרם לכל worker | ✅ תוקן — נעילת flock, רק worker אחד מריץ |
| 4 | db.create_all בפרודקשן | ✅ תוקן — רץ רק על SQLite (פיתוח/טסטים) |
| 5 | סודות ברירת מחדל | ✅ תוקן — SECRET_KEY חובה בפרודקשן; salt נגזר ממנו; CRON_API_TOKEN בלי דיפולט |
| 6 | Dockerfile מריץ main.py שלא קיים | ✅ תוקן — gunicorn |
| 7 | פיצול helpers.py | ⚠️ חלקי — נתיבים קשיחים תוקנו (`_debug_artifact_path`); הפיצול המבני נדחה (refactor גדול) |
| 8 | except: חשופים | ✅ תוקן — כל 48 הוחלפו ב-`except Exception`; `except: pass` ב-scheduler מתעד ועושה rollback |
| 9 | commit בלי rollback | ✅ תוקן — teardown גלובלי + `safe_commit()` ב-`app/utils/db_utils.py` |
| 10 | ערבוב זמנים | ⚠️ חלקי — תוקנה ההשוואה ב-models.py; שאר המופעים הם תצוגה בלבד |
| 11 | קבצים מתים | ✅ נמחקו (5 קבצים, ~2,000 שורות) |
| 12 | סוד ב-URL של cron | ⏸️ הושאר בכוונה — שינוי ישבור את ה-cron החיצוני; לטפל יחד עם עדכון הגדרת ה-cron |
| 13 | CSRF exempt נכשל בשקט | ✅ תוקן — כשל מפיל את עליית האפליקציה |
| 14 | requirements לא נעולים | ✅ תוקן — הכל נעול לגרסאות העובדות |
| 15 | float() על קלט | ✅ נבדק — כל הנקודות כבר היו מוגנות |
| 16 | Selenium ב-scheduler | ✅ נפתר עקיף — scheduler כבוי כברירת מחדל |
| 17 | circular imports | ✅ תוקן — imports של routes/helpers הוסטו לתוך create_app |
| בונוס | SQLALCHEMY_ENGINE_OPTIONS שבר SQLite/טסטים | ✅ תוקן — pool options רק ל-Postgres |

**אומת:** 15/15 טסטים עוברים, האפליקציה עולה ומגישה דפים, אכיפת סודות בפרודקשן עובדת, wsgi נטען תקין.

**לפני deploy:** לוודא ש-`SECRET_KEY` מוגדר ב-render (קיים ב-render.yaml). שינוי ה-salt יפסיל טוקני איפוס-סיסמה שכבר נשלחו במייל — חד-פעמי.

---

תאריך: 2026-06-12
היקף: סריקה של כל קוד ה-Python בפרויקט (~32,000 שורות) בדגש על נקודות שבירה — קונפיגורציה, תהליכי רקע, טיפול בשגיאות, ועקביות נתונים.

---

## 🔴 קריטי — יכול לשבור פרודקשן או ליצור באג שקשה לאתר

### 1. טוקני ביטול הרשמה מבוססים על `hash()` של פייתון — שבורים מעצם הגדרתם
**קבצים:** `app/__init__.py:215-221`, `app/routes/admin_routes/admin_newsletter_routes.py:13-19`

```python
return str(abs(hash(f"{user.email}{user.id}")))[:10]
```

`hash()` של פייתון מקבל seed אקראי **בכל הפעלת תהליך** (hash randomization). המשמעות:
- לינק ביטול הרשמה שנוצר ב-worker אחד של gunicorn **לא יעבור אימות** ב-worker אחר (רצים 4 workers).
- כל לינק שנשלח במייל מפסיק לעבוד אחרי restart של השרת.
- בנוסף זה לא קריפטוגרפי — ניתן לניחוש.

**תיקון:** להחליף ל-`itsdangerous.URLSafeSerializer` (כבר מותקן) או HMAC עם `SECRET_KEY`. למחוק את אחד משני המימושים הכפולים (יש אחד ב-`__init__.py` ואחד ב-`admin_newsletter_routes.py`).

### 2. ה-Scheduler רץ פעם אחת לכל worker — משימות מתבצעות 4 פעמים
**קבצים:** `app/__init__.py:256-263`, `app/scheduler.py`, `render.yaml` (`--workers 4`)

`create_app()` מפעיל `TaskScheduler` בכל worker. עם 4 workers, כל משימה מתוזמנת (עדכון קופונים, מיילים) תרוץ עד 4 פעמים במקביל — מיילים כפולים, race על `next_run`. ההערה בשורה 211 אומרת "Scheduler functionality removed - now using external cron jobs" אבל בשורה 256 הוא עדיין מופעל.

**תיקון:** אם עברתם ל-cron חיצוני — להסיר את ההפעלה לגמרי (ולמחוק את `ENABLE_SCHEDULER` או לשנות ברירת מחדל ל-False). אם לא — להוסיף נעילה (advisory lock ב-Postgres או Redis lock) כך שרק worker אחד מריץ.

### 3. בוט הטלגרם מופעל בכל worker — Conflict מובנה
**קובץ:** `wsgi.py` (בלוק ה-`else` בסוף — "WSGI Mode")

ב-gunicorn עם 4 workers, `start_bot_if_enabled()` נקרא 4 פעמים → 4 תהליכי polling על אותו token. טלגרם מרשה אחד בלבד; השאר נופלים על `TelegramConflict` (כבר תופסים את זה ב-except, כלומר הבעיה מוכרת אבל לא נפתרה — איזה worker "זוכה" אקראי, ואחרי restart זה יכול להתנדנד).

**תיקון:** להריץ את הבוט כתהליך נפרד (worker/service נפרד ב-render) ולא בתוך ה-web workers. לחלופין, webhook במקום polling.

### 4. `db.create_all()` בתוך `create_app()` לצד Flask-Migrate
**קובץ:** `app/__init__.py:202`

שני מנגנוני סכמה מתחרים: `create_all()` יוצר טבלאות שלא עברו דרך מיגרציה → המיגרציות מפסיקות לשקף את ה-DB האמיתי, ומיגרציה עתידית תיכשל או תדרוס. בנוסף, 4 workers מריצים את זה במקביל בעליית שרת — race על DDL.

**תיקון:** למחוק את `db.create_all()` ולנהל סכמה רק דרך `flask db upgrade` (בשלב deploy, לא בעליית האפליקציה).

### 5. ברירות מחדל לא-בטוחות לסודות
**קובץ:** `app/config.py:28,44,53`

```python
SECRET_KEY = os.getenv("SECRET_KEY", "default_secret_key")
SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "default_salt")
CRON_API_TOKEN = os.getenv("CRON_API_TOKEN", "your-secure-api-token-here")
```

אם משתנה סביבה חסר (typo, סביבה חדשה), האפליקציה עולה בשקט עם סוד ידוע — sessions ניתנים לזיוף, טוקני reset-password ניתנים לזיוף. זו תקלה שמתגלה רק כשמישהו מנצל אותה.

**תיקון:** בפרודקשן — `raise RuntimeError` אם `SECRET_KEY`/`SECURITY_PASSWORD_SALT` לא מוגדרים. עדיף שהאפליקציה לא תעלה מאשר שתעלה פגיעה.

### 6. `Dockerfile` מריץ קובץ שלא קיים
**קובץ:** `Dockerfile:35` — `CMD ["python", "main.py"]`

אין `main.py` בפרויקט. ב-render זה עובד רק כי `startCommand` ב-`render.yaml` דורס את ה-CMD. כל הרצה של ה-image בלי override (לוקאלית, פלטפורמה אחרת) תקרוס מיד.

**תיקון:** לשנות ל-`CMD ["gunicorn", "--bind", "0.0.0.0:10000", "wsgi:app"]`.

---

## 🟠 גבוה — שבירות מבנית

### 7. `app/helpers.py` — 6,396 שורות שמערבבות שרת web עם אוטומציית דפדפן
הקובץ מכיל גם פונקציות עזר של האפליקציה וגם קוד Selenium/CAPTCHA/pyautogui. בעיות קונקרטיות:
- **נתיב קשיח למחשב שלך:** `app/helpers.py:1510` — `"/Users/itaykarkason/Desktop/captcha_fullscreen_..."`. נשבר בכל סביבה אחרת.
- **`import pyautogui`** (6 מופעים) — לא מופיע ב-`requirements.txt`, ובשרת ללא display זה זורק חריגה בזמן import של הפונקציה. כל route שנוגע בנתיב הזה בפרודקשן יקרוס.
- `app/__init__.py` עושה `from app.helpers import has_feature_access` — כלומר כל האפליקציה תלויה בקובץ שמכיל קוד scraping מקומי.

**תיקון:** לפצל — קוד scraping/CAPTCHA לחבילה נפרדת (`scraping/`) שלא נטענת על ידי השרת; נתיבים קשיחים → משתני סביבה/`tempfile`; להוסיף את התלויות החסרות ל-requirements או להסיר את הקוד.

### 8. 48 `except:` חשופים ו-402 `except Exception` רחבים
רובם ב-`app/helpers.py` (ראו `grep -rn "except:" app`). דוגמה מסוכנת במיוחד — `app/scheduler.py:124-127`:

```python
try:
    db_session.commit()
except:
    pass
```

כשל בכתיבת לוג שגיאה נבלע לחלוטין — המשימה נכשלה ואין שום עדות. `except:` חשוף תופס גם `KeyboardInterrupt`/`SystemExit` ומונע כיבוי נקי.

**תיקון:** מינימום — להחליף כל `except:` ב-`except Exception as e` עם `logger.exception(...)`. ב-`except: pass` להוסיף לפחות rollback + לוג.

### 9. חוסר איזון commit/rollback — 245 קריאות commit מול 135 rollback
חלק גדול מה-routes עושים `db.session.commit()` בלי try/except. כש-commit נכשל (constraint, ניתוק), ה-session נשאר "מורעל" וה-request הבא באותו worker עלול לקבל `PendingRollbackError`.

**תיקון:** דפוס אחיד — helper כמו `safe_commit()` שעושה commit עם rollback בכשל, או teardown handler גלובלי שעושה rollback אם ה-session dirty.

### 10. ערבוב datetime נאיבי ו-aware (76 מופעים של `datetime.now()`/`utcnow()`)
דוגמה: `app/models.py:283` — `datetime.now().replace(tzinfo=None)` (זמן מקומי של השרת!) לצד `datetime.now(pytz.UTC)` ב-scheduler. השוואות בין השניים שגויות בשעתיים-שלוש (שעון ישראל מול UTC) או זורקות `TypeError`. באגים של "הקופון פג מוקדם מדי" / "המשימה רצה בשעה לא נכונה" נובעים בדיוק מזה.

**תיקון:** תקן אחד — לאחסן הכל UTC aware (`datetime.now(timezone.utc)`), ולהמיר לשעון ישראל רק בתצוגה (כבר יש `to_israel_time_filter`).

### 11. קבצים מתים/כפולים שמזמינים עריכה של הקובץ הלא נכון
- `app/routes/profile_routes_backup.py` (1,238 שורות)
- `app/routes/admin_routes/admin_dashboard_routes copy.py`
- `app/routes/admin_routes/admin_dashboard_routes_first_dashboard.py`
- `app/routes/profile_routes/__init__.py.py` (סיומת כפולה)
- `reproduce_issue.py` בשורש

**תיקון:** למחוק (git שומר היסטוריה). קוד מת הוא המקום הקלאסי שבו תיקון "מצליח" אבל לא משפיע כי נערך הקובץ הלא נכון.

---

## 🟡 בינוני — כדאי לתקן בהזדמנות

### 12. endpoint של cron מוגן רק במחרוזת ב-URL
`app/routes/cron_routes.py:8` — `'/cron/keep-alive/A5d8F2gH3jK4lPq9wE7rT1zU0iO/'`. הסוד מקודד בקוד (וב-git), מופיע בלוגים של proxies. עדיף header `Authorization` שמושווה ל-env var (כמו שכבר נעשה ב-`coupons_api_routes.py:493`).

### 13. exemptions של CSRF עטופים ב-try/except שרק מדפיס warning
`app/__init__.py:235-249` — אם ה-import נכשל, ה-endpoints של ה-cron נשארים עם CSRF ונכשלים בשקט (ה-cron החיצוני יקבל 400 ואיש לא ישים לב). עדיף שהכשל יפיל את עליית האפליקציה.

### 14. `requirements.txt` מעורב — חלק נעול וחלק לא
`gunicorn`, `flask_mail`, `openpyxl`, `webdriver-manager`, `email-validator`, `xlsxwriter`, `plotly` ועוד — בלי גרסה. כל deploy עלול למשוך גרסת major חדשה ולשבור. בנוסף `openai==0.28.1` — API ישן מאוד שכבר הוסר מה-SDK החדש; שדרוג בטעות ישבור את כל הקריאות.

**תיקון:** לנעול הכל (`pip freeze` לקובץ lock או מעבר ל-`uv`/`pip-tools`).

### 15. המרות `float()` על קלט משתמש בלי הגנה
למשל `app/routes/coupons_routes.py:391,396,1389-1390` — `float(coupon["value"])` על נתון שמגיע מבחוץ. ערך לא-מספרי → 500. לעטוף בולידציה (WTForms כבר עושה חלק — לוודא שכל הנתיבים עוברים דרכו) או try/except עם הודעת שגיאה למשתמש.

### 16. עדכון קופונים מתוזמן מריץ Selenium בתוך thread של ה-web worker
`app/scheduler.py:161-214` קורא ל-`get_coupon_data` (שמפעיל דפדפן) מתוך ה-scheduler thread של gunicorn worker. דפדפן + 120s timeout של gunicorn + זיכרון של plan free ב-render = קריסות worker. אם נשארים עם scraping — להריץ אותו רק כ-cron/worker נפרד (כפי שכבר חלקית נעשה עם `automatic_coupon_update`).

### 17. `import` בתוך `create_app` מ-`coupons_routes` בשורה הראשונה של `app/__init__.py`
`app/__init__.py:8` מייבא מ-`app.routes.coupons_routes` (קובץ של 6,352 שורות) עוד לפני יצירת האפליקציה, וגם תלוי ב-`app.helpers`. זה מקור קלאסי ל-circular imports — כל שינוי סדר imports באחד הקבצים יכול לשבור את עליית האפליקציה. להעביר פונקציות משותפות (`to_israel_time_filter`, `has_feature_access`) למודול utils קטן ועצמאי.

---

## סדר יישום מומלץ

| שלב | סעיפים | מאמץ | סיכון אם לא מטפלים |
|-----|--------|------|---------------------|
| 1 | 1 (טוקנים), 5 (סודות), 6 (Dockerfile) | קטן | לינקים שבורים ללקוחות, זיוף sessions |
| 2 | 2+3 (scheduler/bot per-worker), 4 (create_all) | בינוני | משימות כפולות, drift של סכמה |
| 3 | 8+9 (excepts, commits), 10 (זמנים) | בינוני-גדול | באגים שקטים שקשה לאתר |
| 4 | 7 (פיצול helpers), 11 (קבצים מתים), 12-17 | מתמשך | תחזוקתיות |

הערה: הסריקה כיסתה את `app/`, `scripts/`, קבצי ה-entry (`wsgi.py`, `app.py`, `telegram_bot.py`) וקונפיגורציית deploy. תיקיות ה-scraping (`scrape_buyme`, `scrape_multipass`, `automatic_coupon_update`) נסקרו חלקית — סביר שסעיפים 7-8 חלים גם עליהן.
