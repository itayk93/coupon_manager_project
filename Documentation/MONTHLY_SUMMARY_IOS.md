# 📱 סיכום חודשי באפליקציית iOS – אפיון מלא

מטרה: להביא לאפליקציה חוויית סיכום חודשי כמו בטלגרם (ראו `coupon_manager_project/docs/telegram_monthly_summary.md`), עם התראה חודשית (APNs) שמובילה למסך RTL עשיר ואנימטיבי, וזמינות הסיכום גם ממסך ההגדרות.

## זרימת קצה־לקצה
- 🎯 **ייצור סיכום (שרת)**: מנגנון השרת שמייצר סיכום GPT/פולבאק (אותו טקסט כמו בטלגרם) מריץ תזמון חודשי. עם יצירת הסיכום:  
  1) שמירת הרשומה בבסיס הנתונים (month, year, summary_text, stats snapshot, style, created_at).  
  2) שליחת APNs למשתמש עם `type: monthly_summary`, `summary_id`, `month`, `year`, `style` (friendly/creative/...).
- 🔔 **התראה במכשיר**: ההודעה מקומית/מרוחקת עם טקסט קצר "סיכום נובמבר מוכן! ראה כמה חסכת". לחיצה → פתיחת מסך סיכום.
- 📲 **מסך סיכום**: מוצג כ-sheet/Navigation push מעל `CouponsListView`, RTL מלא (ראו הנחיות RTL בהמשך), אנימציה/לוטי בכניסה. כולל טקסט הסיכום, KPI-ים וכפתורי פעולה.
- ⚙️ **גישה ידנית**: בפרופיל/הגדרות תהיה כניסה "סיכומים חודשיים" + רשימת חודשים אחרונים. בחירה ב"חודש נובמבר" תציג את אותו המסך (גם הוא RTL מלא).

## API – שימוש ב-production (couponmasteril.com)
נשתמש בשרת הקיים (כמו בטלגרם) כדי לייצר ולהגיש את הסיכום. מומלץ לחשוף נקודות קצה (אם לא קיימות) על אותו דומיין `https://couponmasteril.com`:

- `GET /api/mobile/monthly-summary?month=MM&year=YYYY`  
  Headers: `Authorization: Bearer <user_token>`, `X-User-Id: <user_id>` (או מזהה מתוך הטוקן).  
  Response (200):  
  ```json
  {
    "summary_id": "ms-2025-11-123",
    "month": 11,
    "year": 2025,
    "month_name_he": "נובמבר",
    "style": "friendly",
    "summary_text": "📆 סיכום נובמבר...\n...",
    "stats": { /* מבנה זהה ל-calculate_monthly_statistics */ },
    "generated_at": "2025-12-01T10:00:00Z"
  }
  ```
  Errors: 401 (טוקן לא תקף), 404 (אין סיכום שנוצר), 500 (שגיאת GPT/שרת) – במקרה כזה להחזיר `summary_text` פולבאק אם יש.

- `GET /api/mobile/monthly-summary/list?limit=12`  
  מחזיר רשימת חודשים זמינים: `[{summary_id, month, year, month_name_he, style, generated_at}]`.

- (אופציונלי) `POST /api/mobile/monthly-summary/ack`  
  Body: `{ "summary_id": "...", "read": true }` כדי לסמן שנקרא.

**הערה:** צד השרת משתמש באותן פונקציות קיימות (`get_monthly_summary_text_with_gpt` / `fallback` + `calculate_monthly_statistics`) ולכן אין לוגיקה חדשה – רק מעטפת API. Auth: אפשר למחזר את טוקן הסופבייס/Session שכבר נשמר באפליקציה (או להוסיף JWT ייעודי שנשלח מהאתר לאחר התחברות).

## מקור נתונים ו-API
- נקרא לשרת (API הראשי) לנקודת קצה חדשה, לדוגמה:  
  `GET /api/monthly-summary?user_id=<id>&month=<mm>&year=<yyyy>`  
  מחזיר JSON עם:  
  - `summary_id`: מזהה ייחודי (לסנכרון עם push).  
  - `month`, `year`, `month_name_he`.  
  - `summary_text`: הטקסט שנוצר (GPT או fallback).  
  - `style`: friendly | creative | happy | humorous | motivational.  
  - `stats`: אובייקט אחד-לאחד עם `calculate_monthly_statistics` (new_coupons_count, used_new_coupons_count, total_savings, total_active_value, usage_percentage, popular_companies[5], expiring_next_month, expiring_companies[], comparison deltas).  
  - `generated_at`: תאריך יצירה.  
  - `cta_links` (אופציונלי): למשל deep link לסטטיסטיקות באפליקציה.
- קאשינג: שמירה ב-UserDefaults/App Group של הסיכום האחרון `{month, year} -> MonthlySummaryModel`. תוקף 24 שעות.
- שגיאות/אופליין: אם ה-API נכשל, לבקש `fallback=true` ולקבל `summary_text` גיבוי שמבוסס על `get_monthly_summary_text_fallback` (כמו בטלגרם). אם גם זה נכשל – להראות סט Skeleton + כפתור "נסה שוב".

## אינטגרציה בקוד האפליקציה (קבצים קיימים)
- `NotificationManager.swift`:  
  - להוסיף טיפול ב-userInfo `type == "monthly_summary"` ב-`userNotificationCenter(_:didReceive:...)`: פוסט `NotificationCenter` עם שם `NavigateToMonthlySummary` ונתוני `summaryId`, `month`, `year`.  
  - לשמור שהבקשה לא תימחק אוטומטית (לא למחוק את כל pending בלוח זמנים הזה).
- `ContentView.swift` / `CouponsListView.swift`:  
  - מאזין ל-`NavigateToMonthlySummary` ומרים `MonthlySummaryView` (sheet) מעל.  
  - בעת onAppear, אם יש `PendingMonthlySummaryId` ב-App Group (מ-deeplink/notification ב-AppDelegate) – לפתוח את המסך ולמשוך מה-API.
- `AppDelegate.swift`:  
  - כשהתראה נפתחת ברקע, לשמור את `summary_id`/`month`/`year` ב-App Group ולהעלות NotificationCenter event אחרי שהמשתמש נכנס.
- `ProfileView.swift` (כרטיס "הגדרות כלליות"):  
  - כפתור "סיכומים חודשיים" → פותח `MonthlySummariesListView` עם רשימת חודשים זמינים (נטען מ-API: `GET /api/monthly-summary/list?user_id=<id>&limit=12`).

## רכיבי UI מוצעים
- `MonthlySummaryView` (חדש):  
  - **Hero**: גרדיאנט בצבעי כחול-טורקיז, אנימציית קונפטי/גרף קצר (Lottie) בכניסה. RTL באמצעות `.environment(\.layoutDirection, .rightToLeft)`.  
  - **כותרת**: "📆 סיכום {month_name_he} {year}" + צ׳יפ סגנון (חברותי/יצירתי/...).  
  - **טקסט הסיכום**: מוצג בבלוק Markdown-friendly עם חיתוך שורות ושמירת אימוג׳ים.  
  - **KPI Cards** (grid 2x2):  
    - "קופונים חדשים": `stats.basic_stats.new_coupons_count`  
    - "ניצול קופונים חדשים": "`used/new` + אחוז"  
    - "חיסכון חודשי": `₪total_savings`  
    - "ערך פעיל": `₪total_active_value`  
  - **Pop Highlights**:  
    - חברות פופולריות: עד 3 צ׳יפים עם חברה + שימושים.  
    - התראת תפוגה חודש הבא: badge אדום עם `expiring_next_month` + שמות חברות (ראשונות).  
    - שינוי מול חודש קודם: חיצים ירוק/אדום על `coupons_change` ו-`savings_change`.
  - **CTA**:  
    - כפתור "פתח סטטיסטיקות" → מוביל ל-`SavingsReportView` עם פילטר חודש המדווח.  
    - כפתור משני "שיתוף" → `UIActivityViewController` עם טקסט הסיכום.  
    - כפתור "סגור" בפינה (X) + swipe-down.
  - **מצבי טעינה/שגיאה**: Skeleton cards בזמן fetch; שגיאה מציגה toast/alert RTL.
- `MonthlySummariesListView` (חדש): רשימת חודשים (קוביות עם רקע בהיר, אייקון חודש) עם אינדיקציה "נקרא/חדש". לחיצה פותחת `MonthlySummaryView` עם הנתון הקיים או fetch מה-API.

### RTL – הנחיות מחייבות לכל רכיב
- בכל View/Sheet חדש: `.environment(\.layoutDirection, .rightToLeft)` + יישור טקסטים/סטאקים ל-`.trailing`/`.leading` בהתאם ל-RTL.  
- כפתורי ניווט/CTA: איקונים מימין לטקסט; Chevron/Back icon פונה שמאלה אבל ממוקם בימין טולבר (בהתאם ל-`NavigationBar` RTL).  
- גרידים/כרטיסים: להשתמש ב-`alignment: .trailing` בכותרות, ו-spacing סימטרי; ערכי KPI מיושרים לימין.  
- רשימות חודשים: כותרות/טקסט/Badge מיושרים לימין; אינדיקטור "חדש" בימין הכרטיס.  
- מודלים/Alert/Toast: טקסטים מיושרים לימין; אם משתמשים ב-`Alert`, לדאוג ל-`semanticContentAttribute = .forceRightToLeft` (UIKit) או סביבת RTL ב-SwiftUI.  
- אנימציה/לוטי: אין תלות כיוון, אבל אם יש motion, לוודא שאין כיוון חץ שמאל→ימין שמבלבל.  
- VoiceOver: תיאורים בעברית, סדר פוקוס מימין לשמאל.

## מודל נתונים חדש (אפליקציה)
```swift
struct MonthlySummaryModel: Codable, Identifiable {
    let id: String // summary_id
    let month: Int
    let year: Int
    let monthName: String
    let style: String // friendly/creative/...
    let summaryText: String
  let stats: MonthlyStats
  let generatedAt: Date
}

struct MonthlyStats: Codable {
    let newCouponsCount: Int
    let usedNewCouponsCount: Int
    let totalSavings: Double
    let totalActiveValue: Double
    let usagePercentage: Double
    let popularCompanies: [CompanyUsage] // name + usage_count
    let expiringNextMonth: Int
    let expiringCompanies: [String]
    let couponsChange: Int
    let savingsChange: Double
}
```

## התראה חודשית (APNs) – תוכן מוצע
- Title: שם האפליקציה (מתוך `NotificationManager` / bundle display name).
- Body: `"סיכום {month_name} מוכן! גילינו כמה חסכת ומה מחכה לחודש הבא."`
- userInfo: `{ "type": "monthly_summary", "summary_id": "...", "month": 11, "year": 2025, "style": "friendly" }`
- קטגוריה ייעודית (לשיקול עתידי): מאפשרת כפתור "פתח סיכום" ו-"אחר כך".

## הגדרות והרשאות
- קיימת הרשמת push ב-`ContentView.registerForPushNotifications()`. אין שינוי בהרשאה.  
- העדפה: להוסיף שדה אפליקטיבי `monthlySummaryEnabled` (UserDefaults + synced לשרת). ברירת מחדל: פעיל אם המשתמש Opt-in בטלגרם (`telegram_monthly_summary=true`), אחרת להשאיר off.  
- ממשק משתמש: טוגל ב-`ProfileView` בתוך "הגדרות כלליות" (מחייב sync לשדה שרת/סופבייס).

## ניווט ודיפ־לינקים
- Notification tap → `NavigateToMonthlySummary` → `MonthlySummaryView`.
- קיצור הגדרות: `coupmanager://monthly-summary?month=11&year=2025&summary_id=...` לטובת Deeplink מהתראה/ווידג׳ט.
- רשימת הסיכומים: מאפשרת ניווט אחורה ל-`CouponsListView` + חזרה למסך הקודם.

## עיצוב ואנימציה (RTL-first)
- רקע גרדיאנט דו־טוני (כחול → טורקיז), טקסט מיושר לימין, אייקונים של חיסכון/גרף.
- אנימציה: Lottie קצר (confetti/graph) בעת הופעה; micro-interaction בלחיצה על כרטיסי KPI (scale + spring).
- נגישות: Dynamic Type, VoiceOver labels בעברית, contrast ≥ 4.5 בחלון טקסט.

## ניטור ובדיקות
- לוגים: הדפסת `summary_id`, זמן טעינה, סטטוס API, מקור טקסט (GPT/fallback).
- בדיקות:  
  - יחידה: parsing `MonthlySummaryModel` + caching.  
  - Snapshot: מסך RTL במצבי light/dark.  
  - אינטגרציה: קבלת push mock ב-Simulator עם `xcrun simctl push`.
- דיבוג: כפתור "שלח התראת סיכום דמה" ב-`AdminSettingsView` (dev only) ששולח notification מקומי עם userInfo המתאים ומרים את המסך.

## משימות יישום
1) **API (שרת קיים ב-couponmasteril.com)**: לחשוף/לאמת את נקודות הקצה `monthly-summary` ו-`list` (שימוש בפונקציות הקיימות).  
2) **Push**: לשלוח APNs עם userInfo type monthly_summary בסיום יצירת הסיכום החודשי.  
3) **אפליקציה**:  
- Notification handling (`NotificationManager`, `AppDelegate`, `CouponsListView`).  
  - Service `MonthlySummaryService` שקורא ל-`couponmasteril.com` עם Bearer token של המשתמש.  
  - ViewModel + models + caching.  
  - `MonthlySummaryView` + `MonthlySummariesListView` + כפתור בהגדרות.  
   - הקפדה על RTL בכל מסך/Alert/Toast/CTA.  
4) **UX**: לוטי/אנימציות, RTL, placeholders לשגיאה/טעינה.  
5) **בדיקות**: יחידה (parsing, caching), Snapshot (RTL Light/Dark), אינטגרציה (push mock עם `simctl push`), ושגיאת API.
