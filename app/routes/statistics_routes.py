# app/routes/statistics_routes.py

from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, extract, and_, or_, cast, Date
from app.extensions import db
from app.models import Coupon, CouponUsage, CouponTransaction

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
    
    # 2. חיסכון כספי (הפרש בין ערך לעלות)
    total_savings = db.session.query(func.sum(Coupon.value - Coupon.cost)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date,
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
        Coupon.exclude_saving == False
    ).scalar() or 0
    
    # 8. ערך כולל של קופונים פעילים
    total_active_value = db.session.query(func.sum(Coupon.value - Coupon.used_value)).filter(
        Coupon.user_id == user_id,
        Coupon.status == 'פעיל',
        (Coupon.value - Coupon.used_value) > 0
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
    
    # 2. חיסכון כספי (הפרש בין ערך לעלות)
    total_savings = db.session.query(func.sum(Coupon.value - Coupon.cost)).filter(
        Coupon.user_id == user_id,
        Coupon.date_added >= start_date,
        Coupon.date_added < end_date,
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
    
    # 8. ערך כולל של קופונים פעילים
    total_active_value = db.session.query(func.sum(Coupon.value - Coupon.used_value)).filter(
        Coupon.user_id == user_id,
        Coupon.status == 'פעיל',
        (Coupon.value - Coupon.used_value) > 0
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
    """יצירת טקסט סיכום חודשי מותאם אישית עם GPT-4o-mini"""
    import openai
    import os
    from flask import current_app
    
    with current_app.app_context():
        try:
            # הגדרת OpenAI API Key (גרסה ישנה של OpenAI)
            openai.api_key = os.getenv('OPENAI_API_KEY')
            
            # קבלת הנתונים הסטטיסטיים
            stats = calculate_monthly_statistics(user_id, month, year)
            
            month_names = {
                1: 'ינואר', 2: 'פברואר', 3: 'מרץ', 4: 'אפריל',
                5: 'מאי', 6: 'יוני', 7: 'יולי', 8: 'אוגוסט',
                9: 'ספטמבר', 10: 'אוקטובר', 11: 'נובמבר', 12: 'דצמבר'
            }
            month_name = month_names.get(month, str(month))
            
            # בניית הprompt לGPT
            user_pronoun = "אתה" if user_gender == 'male' else "את"
            
            prompt = f"""
אתה כותב הודעות קצרות וישירות למשתמשים באפליקציית ניהול קופונים.
כתוב הודעת סיכום חודשי בסגנון קצר וישיר עבור חודש {month_name} {year}.

נתוני המשתמש:
- קופונים חדשים שנוספו: {stats['basic_stats']['new_coupons_count']}
- חיסכון כולל: ₪{stats['basic_stats']['total_savings']:.0f}
- חיסכון ממוצע לקופון: ₪{stats['basic_stats']['average_savings']:.0f}
- ערך פעיל בקופונים: ₪{stats['basic_stats']['total_active_value']:.0f}
- אחוז ניצול קופונים: {stats['usage_stats']['usage_percentage']:.1f}%
- החברות הפופולריות: {[f"{comp['name']} ({comp['usage_count']} שימושים)" for comp in stats['popular_companies'][:3]]}
- שינוי מהחודש הקודם: {'+' if stats['comparison']['coupons_change'] >= 0 else ''}{stats['comparison']['coupons_change']} קופונים
- שינוי חיסכון מהחודש הקודם: {'+' if stats['comparison']['savings_change'] >= 0 else ''}₪{stats['comparison']['savings_change']:.0f}
- קופונים פגי תוקף החודש הבא: {stats['alerts']['expiring_next_month']}
- חברות של קופונים פגי תוקף: {stats['alerts']['expiring_companies']}

דרישות הסגנון:
1. התחל עם "📆 סיכום {month_name} 📆" או "היי איתי," 
2. השתמש באמוג'י מינימלי (1-2 למשפט מקסימום)
3. כתוב משפטים קצרים וישירים
4. אל תכתוב יותר מ-120 מילים
5. השתמש בטון חברותי אבל לא מתלהב מדי
6. הזכר רק את הנתונים החשובים ביותר
7. אם יש קופונים פגי תוקף - הזכר זאת עם שם החברה
8. לאחוז ניצול כתוב "ניצלת X% מהקופונים שלך!" במקום "אחוז הניצול שלך"
9. סיים עם "תמשיך ככה! כל הכבוד 💪" (או "תמשיכי" לנשים)
10. כתוב בגוף שני {user_pronoun}

דוגמא לסגנון הרצוי:
"📆 סיכום מאי 📆

היי איתי,
הוספת 5 קופונים חדשים וחסכת ₪200 החודש 👏

ניצלת 75% מהקופונים שלך!

דרך אגב, יש לך קופון של מקדונלדס שיפוג תוקף החודש הבא.

תמשיך ככה! כל הכבוד 💪"
"""

            # קריאה ל-GPT API (גרסה ישנה של OpenAI 0.28.1)
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "אתה כותב הודעות חברתיות ומעודדות לאפליקציית ניהול קופונים. תמיד כתוב בעברית בלבד."},
                    {"role": "user", "content": prompt}
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
        stats = calculate_monthly_statistics(user_id, month, year)
        
        month_names = {
            1: 'ינואר', 2: 'פברואר', 3: 'מרץ', 4: 'אפריל',
            5: 'מאי', 6: 'יוני', 7: 'יולי', 8: 'אוגוסט',
            9: 'ספטמבר', 10: 'אוקטובר', 11: 'נובמבר', 12: 'דצמבר'
        }
        
        month_name = month_names.get(month, str(month))
        
        # בניית ההודעה בסגנון קצר וישיר
        message = f"📆 סיכום {month_name} 📆\n\n"
        
        message += "היי איתי,\n"
        message += f"הוספת {stats['basic_stats']['new_coupons_count']} קופונים חדשים וחסכת ₪{stats['basic_stats']['total_savings']:.0f} החודש"
        
        # הוסף אמוג'י בהתאם לביצועים
        if stats['basic_stats']['new_coupons_count'] > 5:
            message += " 👏\n\n"
        elif stats['basic_stats']['new_coupons_count'] > 0:
            message += " 👍\n\n"
        else:
            message += "\n\n"
        
        # אחוז ניצול
        usage_pct = stats['usage_stats']['usage_percentage']
        if usage_pct > 70:
            message += f"ניצלת {usage_pct:.0f}% מהקופונים שלך!\n\n"
        elif usage_pct > 40:
            message += f"ניצלת {usage_pct:.0f}% מהקופונים שלך - יש מקום לשיפור.\n\n"
        elif usage_pct > 0:
            message += f"ניצלת {usage_pct:.0f}% מהקופונים שלך - כדאי להשתמש יותר בקופונים.\n\n"
        
        # החברות הפופולריות (רק אם יש)
        if stats['popular_companies'] and len(stats['popular_companies']) > 0:
            top_company = stats['popular_companies'][0]['name']
            message += f"החברה הפופולרית ביותר: {top_company}\n\n"
        
        # התראות על תוקף
        if stats['alerts']['expiring_next_month'] > 0:
            expiring_companies = stats['alerts']['expiring_companies']
            if stats['alerts']['expiring_next_month'] == 1:
                company_name = expiring_companies[0] if expiring_companies else "לא ידוע"
                message += f"דרך אגב, יש לך קופון של {company_name} שיפוג תוקף החודש הבא.\n\n"
            else:
                if expiring_companies:
                    # Show first 2 companies if there are multiple
                    companies_text = ", ".join(expiring_companies[:2])
                    if len(expiring_companies) > 2:
                        companies_text += " ועוד"
                    message += f"דרך אגב, יש לך {stats['alerts']['expiring_next_month']} קופונים שיפגו תוקף החודש הבא ({companies_text}).\n\n"
                else:
                    message += f"דרך אגב, יש לך {stats['alerts']['expiring_next_month']} קופונים שיפגו תוקף החודש הבא.\n\n"
        
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