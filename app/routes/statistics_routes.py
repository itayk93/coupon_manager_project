# app/routes/statistics_routes.py

from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, extract, and_, or_, cast, Date
from app.extensions import db
from app.models import Coupon, CouponUsage, CouponTransaction, User

statistics_bp = Blueprint('statistics', __name__, url_prefix='/statistics')

@statistics_bp.route('/')
@login_required
def statistics_page():
    """עמוד הסטטיסטיקות הראשי"""
    return render_template('statistics.html', title='סטטיסטיקות')

@statistics_bp.route('/api/data')
@login_required
def get_statistics_data():
    """API להחזרת נתוני סטטיסטיקות לפי חודש ושנה"""
    try:
        month = request.args.get('month', type=int)
        year = request.args.get('year', type=int)
        all_months = request.args.get('all_months', type=bool, default=False)
        
        # אם לא נקבע חודש/שנה, נחזיר את החודש הנוכחי
        if not year:
            now = datetime.now()
            year = now.year
        
        if not month and not all_months:
            now = datetime.now()
            month = now.month
        
        # חישוב סטטיסטיקות
        if all_months:
            stats = calculate_all_time_statistics(current_user.id, year)
        else:
            stats = calculate_monthly_statistics(current_user.id, month, year)
        
        return jsonify({
            'success': True,
            'data': stats,
            'month': month if not all_months else 'all',
            'year': year,
            'all_months': all_months
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in get_statistics_data: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'שגיאה בטעינת הנתונים'
        }), 500

def calculate_monthly_statistics(user_id, month, year):
    """חישוב סטטיסטיקות חודשיות למשתמש"""
    
    # Create date range for the month
    from datetime import date
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    
    # 1. מספר קופונים חדשים שנוספו בחודש
    new_coupons_count = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date
    ).scalar() or 0
    
    # Count used new coupons added this month
    used_new_coupons_count = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date,
        Coupon.status == 'נוצל'
    ).scalar() or 0
    
    # Calculate savings only from active coupons added this month
    total_savings = db.session.query(func.sum(Coupon.value - Coupon.cost)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date,
        Coupon.status == 'פעיל',
        Coupon.exclude_saving == False
    ).scalar() or 0
    
    # 3. החברות הפופולריות ביותר (לפי שימוש בחודש)
    # שילוב של CouponUsage ו-CouponTransaction כמו בעמוד פרטי הקופון
    
    # ספירת השימושים מ-CouponUsage (שימושים ידניים)
    usage_companies = db.session.query(
        Coupon.company,
        func.count(CouponUsage.id).label('usage_count')
    ).join(CouponUsage, Coupon.id == CouponUsage.coupon_id).filter(
        Coupon.user_id == user_id,
        CouponUsage.timestamp >= start_date,
        CouponUsage.timestamp < end_date,
        ~CouponUsage.details.like('%Multipass%')  # מתעלם מרשומות Multipass ב-CouponUsage
    ).group_by(Coupon.company).all()
    
    # ספירת השימושים מ-CouponTransaction (שימושים אוטומטיים מMultipass)
    transaction_companies = db.session.query(
        Coupon.company,
        func.count(CouponTransaction.id).label('usage_count')
    ).join(CouponTransaction, Coupon.id == CouponTransaction.coupon_id).filter(
        Coupon.user_id == user_id,
        CouponTransaction.transaction_date >= start_date,
        CouponTransaction.transaction_date < end_date,
        CouponTransaction.usage_amount > 0  # רק שימושים (לא הטענות)
    ).group_by(Coupon.company).all()
    
    # שילוב התוצאות
    company_usage_dict = {}
    for company, count in usage_companies:
        company_usage_dict[company] = company_usage_dict.get(company, 0) + count
    
    for company, count in transaction_companies:
        company_usage_dict[company] = company_usage_dict.get(company, 0) + count
    
    # מיון והגבלה ל-5 חברות הפופולריות ביותר
    popular_companies = sorted(company_usage_dict.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # 4. סטטיסטיקות שימוש נוספות
    # אחוז ניצול קופונים
    total_coupons = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date
    ).scalar() or 0
    
    fully_used_coupons = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date,
        Coupon.used_value >= Coupon.value
    ).scalar() or 0
    
    partially_used_coupons = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date,
        and_(Coupon.used_value > 0, Coupon.used_value < Coupon.value)
    ).scalar() or 0
    
    unused_coupons = total_coupons - fully_used_coupons - partially_used_coupons
    
    # 5. ממוצע חיסכון לקופון
    average_savings = total_savings / new_coupons_count if new_coupons_count > 0 else 0
    
    # 6. קופונים שפגים תוקף החודש הבא - עם פרטי החברות
    expiring_coupons = 0
    expiring_companies = []
    try:
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        
        all_active_coupons = db.session.query(Coupon).filter(
            Coupon.user_id == user_id,
            Coupon.status == 'פעיל',
            Coupon.expiration.isnot(None),
            (Coupon.value - Coupon.used_value) > 0
        ).all()
        
        for coupon in all_active_coupons:
            if coupon.expiration:
                # Handle both string and date formats
                exp_date = coupon.expiration
                if isinstance(exp_date, str):
                    try:
                        exp_date = datetime.strptime(exp_date, '%Y-%m-%d').date()
                    except:
                        continue
                
                if exp_date.month == next_month and exp_date.year == next_year:
                    expiring_coupons += 1
                    expiring_companies.append(coupon.company)
    except:
        expiring_coupons = 0
        expiring_companies = []
    
    # 7. השוואה לחודש הקודם
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    
    prev_start_date = date(prev_year, prev_month, 1)
    if prev_month == 12:
        prev_end_date = date(prev_year + 1, 1, 1)
    else:
        prev_end_date = date(prev_year, prev_month + 1, 1)
    
    prev_month_coupons = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= prev_start_date,
        Coupon.date_added < prev_end_date
    ).scalar() or 0
    
    prev_month_savings = db.session.query(func.sum(Coupon.value - Coupon.cost)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= prev_start_date,
        Coupon.date_added < prev_end_date,
        Coupon.status == 'פעיל',
        Coupon.exclude_saving == False
    ).scalar() or 0
    
    # 8. ערך כולל של קופונים (כמו בעמוד הראשי)
    total_active_value = db.session.query(func.sum(Coupon.value - Coupon.used_value)).filter(
        Coupon.user_id == user_id,
        Coupon.is_for_sale == False,
        or_(Coupon.exclude_saving.is_(None), Coupon.exclude_saving != True)
    ).scalar() or 0
    
    return {
        'basic_stats': {
            'new_coupons_count': new_coupons_count,
            'used_new_coupons_count': used_new_coupons_count,
            'total_savings': round(total_savings, 2),
            'average_savings': round(average_savings, 2),
            'total_active_value': round(total_active_value, 2)
        },
        'usage_stats': {
            'total_coupons': total_coupons,
            'fully_used': fully_used_coupons,
            'partially_used': partially_used_coupons,
            'unused': unused_coupons,
            'usage_percentage': round((fully_used_coupons / total_coupons * 100) if total_coupons > 0 else 0, 1)
        },
        'popular_companies': [
            {'name': company, 'usage_count': count} 
            for company, count in popular_companies
        ],
        'alerts': {
            'expiring_next_month': expiring_coupons,
            'expiring_companies': expiring_companies
        },
        'comparison': {
            'prev_month_coupons': prev_month_coupons,
            'prev_month_savings': round(prev_month_savings, 2),
            'coupons_change': new_coupons_count - prev_month_coupons,
            'savings_change': round(total_savings - prev_month_savings, 2)
        }
    }

def calculate_all_time_statistics(user_id, year):
    """חישוב סטטיסטיקות על כל הנתונים לשנה נתונה"""
    
    # Create date range for the entire year
    from datetime import date
    start_date = date(year, 1, 1)
    end_date = date(year + 1, 1, 1)
    
    # 1. מספר קופונים חדשים שנוספו בשנה
    new_coupons_count = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date
    ).scalar() or 0
    
    # 2. חיסכון כספי (הפרש בין ערך לעלות) - רק מקופונים פעילים
    total_savings = db.session.query(func.sum(Coupon.value - Coupon.cost)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date,
        Coupon.status == 'פעיל',
        Coupon.exclude_saving == False
    ).scalar() or 0
    
    # 3. החברות הפופולריות ביותר (לפי שימוש בשנה)
    # שילוב של CouponUsage ו-CouponTransaction כמו בעמוד פרטי הקופון
    
    # ספירת השימושים מ-CouponUsage (שימושים ידניים)
    usage_companies = db.session.query(
        Coupon.company,
        func.count(CouponUsage.id).label('usage_count')
    ).join(CouponUsage, Coupon.id == CouponUsage.coupon_id).filter(
        Coupon.user_id == user_id,
        CouponUsage.timestamp >= start_date,
        CouponUsage.timestamp < end_date,
        ~CouponUsage.details.like('%Multipass%')  # מתעלם מרשומות Multipass ב-CouponUsage
    ).group_by(Coupon.company).all()
    
    # ספירת השימושים מ-CouponTransaction (שימושים אוטומטיים מMultipass)
    transaction_companies = db.session.query(
        Coupon.company,
        func.count(CouponTransaction.id).label('usage_count')
    ).join(CouponTransaction, Coupon.id == CouponTransaction.coupon_id).filter(
        Coupon.user_id == user_id,
        CouponTransaction.transaction_date >= start_date,
        CouponTransaction.transaction_date < end_date,
        CouponTransaction.usage_amount > 0  # רק שימושים (לא הטענות)
    ).group_by(Coupon.company).all()
    
    # שילוב התוצאות
    company_usage_dict = {}
    for company, count in usage_companies:
        company_usage_dict[company] = company_usage_dict.get(company, 0) + count
    
    for company, count in transaction_companies:
        company_usage_dict[company] = company_usage_dict.get(company, 0) + count
    
    # מיון והגבלה ל-5 חברות הפופולריות ביותר
    popular_companies = sorted(company_usage_dict.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # 4. סטטיסטיקות שימוש נוספות
    total_coupons = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date
    ).scalar() or 0
    
    fully_used_coupons = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date,
        Coupon.used_value >= Coupon.value
    ).scalar() or 0
    
    partially_used_coupons = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date,
        and_(Coupon.used_value > 0, Coupon.used_value < Coupon.value)
    ).scalar() or 0
    
    unused_coupons = total_coupons - fully_used_coupons - partially_used_coupons
    
    # 5. ממוצע חיסכון לקופון
    average_savings = total_savings / new_coupons_count if new_coupons_count > 0 else 0
    
    # 6. קופונים שפגים תוקף החודשים הקרובים
    expiring_coupons = 0
    expiring_companies = []
    try:
        from datetime import datetime, timedelta
        next_month_date = datetime.now().date() + timedelta(days=30)
        
        all_active_coupons = db.session.query(Coupon).filter(
            Coupon.user_id == user_id,
            Coupon.status == 'פעיל',
            Coupon.expiration.isnot(None),
            (Coupon.value - Coupon.used_value) > 0
        ).all()
        
        for coupon in all_active_coupons:
            if coupon.expiration:
                exp_date = coupon.expiration
                if isinstance(exp_date, str):
                    try:
                        exp_date = datetime.strptime(exp_date, '%Y-%m-%d').date()
                    except:
                        continue
                
                if exp_date <= next_month_date:
                    expiring_coupons += 1
                    expiring_companies.append(coupon.company)
    except:
        expiring_coupons = 0
        expiring_companies = []
    
    # 7. השוואה לשנה הקודמת
    prev_year = year - 1
    prev_start_date = date(prev_year, 1, 1)
    prev_end_date = date(prev_year + 1, 1, 1)
    
    prev_year_coupons = db.session.query(func.count(Coupon.id)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= prev_start_date,
        Coupon.date_added < prev_end_date
    ).scalar() or 0
    
    prev_year_savings = db.session.query(func.sum(Coupon.value - Coupon.cost)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= prev_start_date,
        Coupon.date_added < prev_end_date,
        Coupon.exclude_saving == False
    ).scalar() or 0
    
    # 8. ערך כולל של קופונים (כמו בעמוד הראשי)
    total_active_value = db.session.query(func.sum(Coupon.value - Coupon.used_value)).filter(
        Coupon.user_id == user_id,
        Coupon.is_for_sale == False,
        or_(Coupon.exclude_saving.is_(None), Coupon.exclude_saving != True)
    ).scalar() or 0
    
    return {
        'basic_stats': {
            'new_coupons_count': new_coupons_count,
            'total_savings': round(total_savings, 2),
            'average_savings': round(average_savings, 2),
            'total_active_value': round(total_active_value, 2)
        },
        'usage_stats': {
            'total_coupons': total_coupons,
            'fully_used': fully_used_coupons,
            'partially_used': partially_used_coupons,
            'unused': unused_coupons,
            'usage_percentage': round((fully_used_coupons / total_coupons * 100) if total_coupons > 0 else 0, 1)
        },
        'popular_companies': [
            {'name': company, 'usage_count': count} 
            for company, count in popular_companies
        ],
        'alerts': {
            'expiring_next_month': expiring_coupons,
            'expiring_companies': expiring_companies
        },
        'comparison': {
            'prev_month_coupons': prev_year_coupons,
            'prev_month_savings': round(prev_year_savings, 2),
            'coupons_change': new_coupons_count - prev_year_coupons,
            'savings_change': round(total_savings - prev_year_savings, 2)
        }
    }
def get_monthly_summary_text_with_gpt(user_id, month, year, user_gender='male'):
    """יצירת טקסט סיכום חודשי מותאם אישית עם GPT-4o-mini - 5 סגנונות שונים"""
    import openai
    import os
    import random
    from flask import current_app
    
    with current_app.app_context():
        try:
            # הגדרת OpenAI API Key (גרסה ישנה של OpenAI)
            openai.api_key = os.getenv('OPENAI_API_KEY')
            
            # Get user data and statistics
            user = User.query.get(user_id)
            user_first_name = user.first_name if user else "משתמש"
            stats = calculate_monthly_statistics(user_id, month, year)
            
            month_names = {
                1: 'ינואר', 2: 'פברואר', 3: 'מרץ', 4: 'אפריל',
                5: 'מאי', 6: 'יוני', 7: 'יולי', 8: 'אוגוסט',
                9: 'ספטמבר', 10: 'אוקטובר', 11: 'נובמבר', 12: 'דצמבר'
            }
            month_name = month_names.get(month, str(month))
            
            # Build basic data for all prompts
            user_pronoun = "אתה" if user_gender == 'male' else "את"
            continue_phrase = "תמשיך" if user_gender == 'male' else "תמשיכי"
            chef_emoji = "👨‍🍳" if user_gender == 'male' else "👩‍🍳"
            
            usage_percentage = round((stats['basic_stats']['used_new_coupons_count']/stats['basic_stats']['new_coupons_count']*100) if stats['basic_stats']['new_coupons_count'] else 0)
            
            # Calculate savings percentage for used coupons
            used_coupons_total_cost = 0
            used_coupons_total_value = 0
            if stats['basic_stats']['used_new_coupons_count'] > 0:
                # This is an approximation - we'd need to query the actual used coupons for precise calculation
                savings_percentage = round((stats['basic_stats']['total_savings'] / (stats['basic_stats']['total_savings'] + stats['basic_stats']['total_savings'] / 0.3)) * 100) if stats['basic_stats']['total_savings'] > 0 else 0
            else:
                savings_percentage = 0

            # Base data for all prompts
            base_data = f"""
נתוני המשתמש:
- קופונים חדשים שנוספו: {stats['basic_stats']['new_coupons_count']}
- קופונים חדשים שנוצלו: {stats['basic_stats']['used_new_coupons_count']}
- אחוז ניצול קופונים חדשים: {usage_percentage}%
- סה"כ ערך קופונים זמינים: ₪{stats['basic_stats']['total_active_value']:.0f}
- אחוז ניצול קופונים: {stats['usage_stats']['usage_percentage']:.1f}%
- החברות הפופולריות: {[f"{comp['name']} ({comp['usage_count']} שימושים)" for comp in stats['popular_companies'][:3]]}
- שינוי מהחודש הקודם: {'+' if stats['comparison']['coupons_change'] >= 0 else ''}{stats['comparison']['coupons_change']} קופונים
- קופונים פגי תוקף החודש הבא: {stats['alerts']['expiring_next_month']}
- חברות של קופונים פגי תוקף: {stats['alerts']['expiring_companies']}

הנחיות חשובות:
- במקום "ערך פעיל בקופונים" - תמיד כתוב "סה"כ [סכום] ש"ח בקופונים" או "יש לך [סכום] ש"ח בקופונים"
- לגבי קופונים פגי תוקף: אם יש קופונים שפגים תוקף בחודש הבא - הזכר זאת כהתראה חשובה
- אם אין קופונים פגי תוקף בחודש הבא - אל תזכיר את זה בכלל, או כתוב "אין קופונים פגי תוקף החודש הבא"
- אל תתייחס לקופונים שפגו תוקף בחודש הנוכחי או הקודם
- כתוב רק תוכן מותאם אישית על הנתונים של המשתמש - אל תכלול רשימות כלליות או טקסטים שיווקיים קבועים מראש
- התמקד בסיכום האישי של המשתמש בלבד
"""
            
            # 5 סגנונות שונים של פרומפטים
            style_prompts = [
                # סגנון 1: חברותי ומעודד
                f"""
אתה כותב הודעות חברותיות ומעודדות למשתמשים באפליקציית ניהול קופונים.
כתוב הודעת סיכום חודשי בסגנון חברותי ומעודד עבור חודש {month_name} {year}.

{base_data}

דרישות הסגנון:
1. התחל עם "📆 סיכום {month_name} 📆" או "היי {user_first_name},"
2. השתמש באמוג'י מינימלי (1-2 למשפט מקסימום)
3. כתוב משפטים קצרים וחברותיים
4. אל תכתוב יותר מ-120 מילים
5. השתמש בטון חם וחברותי
6. הזכר את משפט הניצול: "ניצלת {stats['basic_stats']['used_new_coupons_count']} קופונים מתוך {stats['basic_stats']['new_coupons_count']} הקופונים החדשים שהוספת החודש - {usage_percentage}%!!"
7. סיים עם "{continue_phrase} ככה! כל הכבוד 💪"
8. כתוב בגוף שני {user_pronoun}
""",

                # סגנון 2: יצירתי ומאופק
                f"""
אתה כותב הודעות יצירתיות אך מאופקות למשתמשים באפליקציית ניהול קופונים.
כתוב הודעת סיכום חודשי בסגנון יצירתי ומאופק עבור חודש {month_name} {year}.

{base_data}

דרישות הסגנון:
1. התחל עם "🎨 {month_name} בסקיצה 🎨" או "📊 הפלטה של {month_name}"
2. השתמש במטפורות יצירתיות מאופקות (ציור, עיצוב, סקיצה)
3. כתוב בסגנון יצירתי אך רגוע
4. אל תכתוב יותר מ-120 מילים
5. השתמש בטון אמנותי מאופק ולא מתלהב
6. הזכר את משפט הניצול: "סקצת {stats['basic_stats']['used_new_coupons_count']} קופונים מתוך {stats['basic_stats']['new_coupons_count']} הרעיונות שלך - {usage_percentage}%. עבודה מקצועית."
7. סיים עם "{continue_phrase} לעצב את החיסכון שלך 🎨"
8. כתוב בגוף שני {user_pronoun}
9. אל תשתמש באמוג'י מוגזם או מילים כמו "מדהים", "נהדר", "מופלא"
""",

                # סגנון 3: שמח ומתלהב
                f"""
אתה כותב הודעות שמחות ומתלהבות למשתמשים באפליקציית ניהול קופונים.
כתוב הודעת סיכום חודשי בסגנון שמח ומתלהב עבור חודש {month_name} {year}.

{base_data}

דרישות הסגנון:
1. התחל עם "🎉 וואו! איזה {month_name} מדהים! 🎉"
2. השתמש באמוג'י יותר (2-3 למשפט)
3. כתוב בסגנון שמח ומתלהב
4. אל תכתוב יותר מ-120 מילים
5. השתמש בטון חגיגי ומתרגש
6. הזכר את משפט הניצול: "ניצלת {stats['basic_stats']['used_new_coupons_count']} קופונים מתוך {stats['basic_stats']['new_coupons_count']} החדשים - {usage_percentage}%! מדהים! 🔥"
7. סיים עם "{continue_phrase} להיות כוכב החיסכון! 🌟✨"
8. כתוב בגוף שני {user_pronoun}
""",

                # סגנון 4: הומוריסטי וקליל
                f"""
אתה כותב הודעות הומוריסטיות וקלילות למשתמשים באפליקציית ניהול קופונים.
כתוב הודעת סיכום חודשי בסגנון הומוריסטי וקליל עבור חודש {month_name} {year}.

{base_data}

דרישות הסגנון:
1. התחל עם "😄 החשבון של {month_name} הגיע! (אבל הפעם זה חשבון טוב) 😄"
2. השתמש באמוג'י בצורה קלילה (1-2 למשפט)
3. כתוב בסגנון קליל ומשעשע
4. אל תכתוב יותר מ-120 מילים
5. השתמש בטון הומוריסטי וחברותי
6. הזכר את משפט הניצול: "ניצלת {stats['basic_stats']['used_new_coupons_count']} מתוך {stats['basic_stats']['new_coupons_count']} קופונים - {usage_percentage}%! (יש מקום לשיפור, אבל מי ספר?)"
7. סיים עם "{continue_phrase} לחסוך כמו שף! {chef_emoji}💰"
8. כתוב בגוף שני {user_pronoun}
""",

                # סגנון 5: מוטיבציוני וחיובי
                f"""
אתה כותב הודעות מוטיבציוניות וחיוביות למשתמשים באפליקציית ניהול קופונים.
כתוב הודעת סיכום חודשי בסגנון מוטיבציוני וחיובי עבור חודש {month_name} {year}.

{base_data}

דרישות הסגנון:
1. התחל עם "💪 {user_first_name}, {month_name} היה חודש של הישגים! 💪"
2. השתמש באמוג'י מוטיבציוני (1-2 למשפט)
3. כתוב בסגנון מעודד ומוטיבציוני
4. אל תכתוב יותר מ-120 מילים
5. השתמש בטון חיובי ומחזק
6. הזכר את משפט הניצול: "הצלחת לנצל {stats['basic_stats']['used_new_coupons_count']} קופונים מתוך {stats['basic_stats']['new_coupons_count']} החדשים - {usage_percentage}%! כל קופון הוא הישג!"
7. סיים עם "כל יום הוא הזדמנות חדשה לחסוך יותר! {continue_phrase} חזק! 🚀"
8. כתוב בגוף שני {user_pronoun}
"""
            ]
            
            # בחירת פרומפט רנדומלי
            selected_prompt = random.choice(style_prompts)
            
            # קריאה ל-GPT API (גרסה ישנה של OpenAI 0.28.1)
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "אתה כותב הודעות מעניינות ומגוונות לאפליקציית ניהול קופונים. תמיד כתוב בעברית בלבד ובסגנון המבוקש."},
                    {"role": "user", "content": selected_prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            
            gpt_message = response.choices[0].message.content.strip()
            
            # שמירת העלות ומידע על השימוש ב-GPT
            if hasattr(response, 'usage'):
                current_app.logger.info(f"GPT usage for monthly summary - Tokens: {response.usage.total_tokens}")
            
            return gpt_message
            
        except Exception as e:
            current_app.logger.error(f"Error generating GPT monthly summary: {str(e)}")
            # במקרה של שגיאה, חזור להודעה הבסיסית
            return get_monthly_summary_text_fallback(user_id, month, year, user_gender)
        
def get_monthly_summary_text_fallback(user_id, month, year, user_gender='male'):
    """הודעת גיבוי אם GPT לא עובד"""
    from flask import current_app
    
    with current_app.app_context():
        # Get user data
        user = User.query.get(user_id)
        user_first_name = user.first_name if user else "משתמש"
        stats = calculate_monthly_statistics(user_id, month, year)
        
        month_names = {
            1: 'ינואר', 2: 'פברואר', 3: 'מרץ', 4: 'אפריל',
            5: 'מאי', 6: 'יוני', 7: 'יולי', 8: 'אוגוסט',
            9: 'ספטמבר', 10: 'אוקטובר', 11: 'נובמבר', 12: 'דצמבר'
        }
        
        month_name = month_names.get(month, str(month))
        
        used_new = stats['basic_stats'].get('used_new_coupons_count', 0)
        new_count = stats['basic_stats'].get('new_coupons_count', 0)
        percent_used = round((used_new / new_count * 100) if new_count else 0)
        
        # Build the message in short and direct style
        message = f"📆 סיכום {month_name} 📆\n\n"
        
        message += f"היי {user_first_name},\n"
        message += f"ניצלת {used_new} קופונים מתוך {new_count} הקופונים החדשים שהוספת החודש - {percent_used}%!! 👏\n\n"
        
        # אחוז ניצול
        usage_pct = stats['usage_stats']['usage_percentage']
        if usage_pct > 70:
            message += f"ניצלת {usage_pct:.0f}% מהקופונים שלך!\n\n"
        elif usage_pct > 40:
            message += f"ניצלת {usage_pct:.0f}% מהקופונים שלך - יש מקום לשיפור.\n\n"
        elif usage_pct > 0:
            message += f"ניצלת {usage_pct:.0f}% מהקופונים שלך - כדאי להשתמש יותר בקופונים.\n\n"
        
        # Total coupon value available
        if stats['basic_stats']['total_active_value'] > 0:
            message += f"יש לך סה\"כ ₪{stats['basic_stats']['total_active_value']:.0f} בקופונים!\n\n"
        
        # Popular companies (only if exists)
        if stats['popular_companies'] and len(stats['popular_companies']) > 0:
            top_company = stats['popular_companies'][0]['name']
            message += f"החברה הפופולרית ביותר: {top_company}\n\n"
        
        # Expiration alerts for NEXT month only
        if stats['alerts']['expiring_next_month'] > 0:
            expiring_companies = stats['alerts']['expiring_companies']
            next_month_name = month_names.get(month + 1 if month < 12 else 1, "החודש הבא")
            if stats['alerts']['expiring_next_month'] == 1:
                company_name = expiring_companies[0] if expiring_companies else "לא ידוע"
                message += f"⚠️ יש לך קופון של {company_name} שיפוג תוקף ב{next_month_name}.\n\n"
            else:
                if expiring_companies:
                    # Show first 2 companies if there are multiple
                    companies_text = ", ".join(expiring_companies[:2])
                    if len(expiring_companies) > 2:
                        companies_text += " ועוד"
                    message += f"⚠️ יש לך {stats['alerts']['expiring_next_month']} קופונים שיפגו תוקף ב{next_month_name} ({companies_text}).\n\n"
                else:
                    message += f"⚠️ יש לך {stats['alerts']['expiring_next_month']} קופונים שיפגו תוקף ב{next_month_name}.\n\n"
        else:
            # No expiring coupons next month
            next_month_name = month_names.get(month + 1 if month < 12 else 1, "החודש הבא")
            message += f"אין קופונים פגי תוקף ב{next_month_name}.\n\n"
        
        # סיום מותאם למין
        if user_gender == 'female':
            message += "תמשיכי ככה! כל הכבוד 💪"
        else:
            message += "תמשיך ככה! כל הכבוד 💪"
        
        return message

# שמירה על הפונקציה הישנה לתאימות לאחור
def get_monthly_summary_text(user_id, month, year):
    """Wrapper function - uses GPT by default"""
    return get_monthly_summary_text_with_gpt(user_id, month, year)

