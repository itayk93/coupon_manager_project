"""
מודול לחישוב אנליטיקה מתקדמת למייל היומי
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.io as pio
from datetime import datetime, date, timedelta
from sqlalchemy.sql import text
from app.extensions import db
from app.models import AdminSettings
import base64
import logging

# הגדרת תבנית Plotly לעברית
pio.templates.default = "plotly_white"

def get_report_options():
    """קבלת אפשרויות הדוח מההגדרות"""
    default_options = {
        'chart_coupons_by_company': True,
        'chart_value_pie': True,
        'chart_weekly_trend': True,
        'chart_price_histogram': False,
        'metrics_roi': True,
        'metrics_recent_activity': True,
        'metrics_expiring': True,
        'metrics_top_companies': True,
        'insights_top3': True,
        'insights_weekly_comparison': True,
        'insights_expiring_alerts': True,
        'analytics_conversion_rate': False,
        'analytics_time_to_sell': False,
        'analytics_profitable_companies': False,
        'segmentation_categories': False,
        'segmentation_price_ranges': False,
        'comparisons_monthly': False,
    }
    return AdminSettings.get_setting('email_report_options', default_options)

def get_basic_stats():
    """חישוב נתונים בסיסיים למייל"""
    query = text("""
        SELECT
            company,
            COUNT(*) AS coupon_count,
            ROUND(AVG(cost)::numeric, 2) AS avg_cost,
            ROUND(AVG(value)::numeric, 2) AS avg_coupon_value,
            ROUND(AVG(((value - cost) / NULLIF(value, 0)) * 100)::numeric, 2) AS avg_discount,
            MAX(date_added) AS last_added,
            SUM(value) AS total_value,
            SUM(cost) AS total_cost
        FROM coupon
        WHERE status = 'פעיל'
        GROUP BY company
        ORDER BY coupon_count DESC
    """)
    
    results = db.session.execute(query).mappings().all()
    return [dict(row) for row in results]

def get_weekly_trend_data():
    """נתונים למגמת השבוע האחרון"""
    week_ago = date.today() - timedelta(days=7)
    
    query = text("""
        SELECT 
            DATE(date_added) as date,
            COUNT(*) as coupons_added
        FROM coupon 
        WHERE date_added >= :week_ago
        GROUP BY DATE(date_added)
        ORDER BY date
    """)
    
    results = db.session.execute(query, {"week_ago": week_ago}).mappings().all()
    return [dict(row) for row in results]

def get_expiring_coupons():
    """קופונים שפגים השבוע הבא"""
    next_week = date.today() + timedelta(days=7)
    
    query = text("""
        SELECT company, COUNT(*) as expiring_count
        FROM coupon 
        WHERE expiration IS NOT NULL 
        AND TO_DATE(expiration, 'YYYY-MM-DD') BETWEEN CURRENT_DATE AND :next_week
        AND status = 'פעיל'
        GROUP BY company
        ORDER BY expiring_count DESC
    """)
    
    results = db.session.execute(query, {"next_week": next_week}).mappings().all()
    return [dict(row) for row in results]

def get_recent_activity():
    """פעילות אחרונה"""
    today = date.today()
    week_ago = today - timedelta(days=7)
    
    query = text("""
        SELECT 
            COUNT(CASE WHEN DATE(date_added) = :today THEN 1 END) as today_count,
            COUNT(CASE WHEN DATE(date_added) >= :week_ago THEN 1 END) as week_count,
            COUNT(CASE WHEN DATE(date_added) >= :week_ago AND DATE(date_added) < :today THEN 1 END) as previous_days_count
        FROM coupon
    """)
    
    result = db.session.execute(query, {"today": today, "week_ago": week_ago}).mappings().first()
    return dict(result) if result else {}

def get_new_users_count():
    """ספירת משתמשים חדשים השבוע"""
    today = date.today()
    week_ago = today - timedelta(days=7)
    
    query = text("""
        SELECT COUNT(*) as new_users_count
        FROM users 
        WHERE DATE(created_at) >= :week_ago
    """)
    
    result = db.session.execute(query, {"week_ago": week_ago}).mappings().first()
    return result['new_users_count'] if result else 0

def create_coupons_by_company_chart(data):
    """יצירת גרף עמודות מודרני - כמות קופונים לכל חברה"""
    if not data:
        return None
    
    # לקחת את ה-10 חברות המובילות
    top_companies = data[:10]
    
    # צבעים מודרניים מהפלטה שלך
    colors = ['#4a5568', '#718096', '#68d391', '#4299e1', '#805ad5', 
              '#48bb78', '#ed8936', '#f56565', '#9f7aea', '#38d9a9']
    
    fig = go.Figure(data=[
        go.Bar(
            x=[item['company'] for item in top_companies],
            y=[item['coupon_count'] for item in top_companies],
            text=[f"<b>{item['coupon_count']}</b>" for item in top_companies],
            textposition='auto',
            textfont=dict(size=14, color='white'),
            marker=dict(
                color=colors[:len(top_companies)],
                line=dict(color='rgba(255,255,255,0.1)', width=1),
                pattern_fillmode="overlay",
                pattern_fgcolor="rgba(255,255,255,0.05)"
            ),
            hovertemplate='<b>%{x}</b><br>קופונים: %{y}<extra></extra>',
            hoverlabel=dict(bgcolor="rgba(74, 85, 104, 0.9)", font_color="white")
        )
    ])
    
    fig.update_layout(
        title=dict(
            text='<b>📊 כמות קופונים לכל חברה</b>',
            font=dict(size=18, color='#2d3748', family='Inter'),
            x=0.5
        ),
        xaxis=dict(
            title=dict(text='<b>חברה</b>', font=dict(size=14, color='#4a5568')),
            tickfont=dict(size=12, color='#4a5568'),
            showgrid=False,
            tickangle=45
        ),
        yaxis=dict(
            title=dict(text='<b>כמות קופונים</b>', font=dict(size=14, color='#4a5568')),
            tickfont=dict(size=12, color='#4a5568'),
            showgrid=True,
            gridcolor='rgba(74, 85, 104, 0.1)',
            gridwidth=1
        ),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(255,255,255,0.95)',
        height=450,
        margin=dict(l=60, r=40, t=80, b=120),
        font=dict(family='Inter, Arial', size=12),
        showlegend=False,
        hovermode='x unified'
    )
    
    return fig.to_html(full_html=False, include_plotlyjs=True, config={'displayModeBar': False})

def create_value_pie_chart(data):
    """יצירת גרף עוגה מודרני - חלוקה לפי שווי קופונים"""
    if not data:
        return None
    
    # לקחת את ה-8 חברות המובילות לפי שווי
    sorted_by_value = sorted(data, key=lambda x: x['total_value'], reverse=True)[:8]
    
    # צבעים אלגנטיים מהפלטה שלך
    colors = ['#4a5568', '#718096', '#68d391', '#4299e1', '#805ad5', 
              '#48bb78', '#ed8936', '#f56565']
    
    fig = go.Figure(data=[
        go.Pie(
            labels=[item['company'] for item in sorted_by_value],
            values=[item['total_value'] for item in sorted_by_value],
            hole=0.4,
            textinfo='label+percent+value',
            texttemplate='<b>%{label}</b><br>%{percent}<br>₪%{value:,.0f}',
            textfont=dict(size=11, color='white'),
            textposition='inside',
            marker=dict(
                colors=colors[:len(sorted_by_value)],
                line=dict(color='rgba(255,255,255,0.8)', width=2)
            ),
            hovertemplate='<b>%{label}</b><br>שווי: ₪%{value:,.0f}<br>אחוז: %{percent}<extra></extra>',
            hoverlabel=dict(bgcolor="rgba(74, 85, 104, 0.9)", font_color="white"),
            rotation=90
        )
    ])
    
    fig.update_layout(
        title=dict(
            text='<b>💰 חלוקת שווי הקופונים לפי חברות</b>',
            font=dict(size=18, color='#2d3748', family='Inter'),
            x=0.5
        ),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(255,255,255,0.95)',
        height=550,
        margin=dict(l=20, r=20, t=80, b=20),
        font=dict(family='Inter, Arial', size=12),
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="rgba(74, 85, 104, 0.2)",
            borderwidth=1
        )
    )
    
    return fig.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

def create_weekly_trend_chart(trend_data):
    """יצירת גרף קווים מודרני - מגמת השבוע האחרון"""
    if not trend_data:
        return None
    
    fig = go.Figure()
    
    # קו המגמה
    fig.add_trace(go.Scatter(
        x=[item['date'] for item in trend_data],
        y=[item['coupons_added'] for item in trend_data],
        mode='lines+markers',
        name='קופונים שנוספו',
        line=dict(
            color='#4a5568',
            width=4,
            shape='spline',
            smoothing=0.3
        ),
        marker=dict(
            size=10,
            color='#68d391',
            line=dict(color='white', width=2)
        ),
        fill='tonexty',
        fillcolor='rgba(104, 211, 145, 0.1)',
        hovertemplate='<b>%{x}</b><br>קופונים: %{y}<extra></extra>',
        hoverlabel=dict(bgcolor="rgba(74, 85, 104, 0.9)", font_color="white")
    ))
    
    # קו בסיס לצביעה
    fig.add_trace(go.Scatter(
        x=[item['date'] for item in trend_data],
        y=[0] * len(trend_data),
        mode='lines',
        line=dict(width=0),
        showlegend=False,
        hoverinfo='skip'
    ))
    
    fig.update_layout(
        title=dict(
            text='<b>📈 מגמת הוספת קופונים - 7 ימים אחרונים</b>',
            font=dict(size=18, color='#2d3748', family='Inter'),
            x=0.5
        ),
        xaxis=dict(
            title=dict(text='<b>תאריך</b>', font=dict(size=14, color='#4a5568')),
            tickfont=dict(size=12, color='#4a5568'),
            showgrid=True,
            gridcolor='rgba(74, 85, 104, 0.1)',
            gridwidth=1
        ),
        yaxis=dict(
            title=dict(text='<b>קופונים שנוספו</b>', font=dict(size=14, color='#4a5568')),
            tickfont=dict(size=12, color='#4a5568'),
            showgrid=True,
            gridcolor='rgba(74, 85, 104, 0.1)',
            gridwidth=1
        ),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(255,255,255,0.95)',
        height=450,
        margin=dict(l=60, r=40, t=80, b=60),
        font=dict(family='Inter, Arial', size=12),
        showlegend=False,
        hovermode='x unified'
    )
    
    return fig.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

def create_price_histogram(data):
    """יצירת היסטוגרמה מודרנית - התפלגות מחירי קופונים"""
    if not data:
        return None
    
    # יצירת רשימה של כל המחירים
    all_costs = []
    for item in data:
        # הוספת מחיר בממוצע כמה פעמים יש קופונים של החברה הזאת
        all_costs.extend([item['avg_cost']] * item['coupon_count'])
    
    fig = go.Figure(data=[
        go.Histogram(
            x=all_costs,
            nbinsx=25,
            marker=dict(
                color='#4a5568',
                opacity=0.8,
                line=dict(color='rgba(255,255,255,0.6)', width=1)
            ),
            hovertemplate='מחיר: ₪%{x}<br>כמות: %{y}<extra></extra>',
            hoverlabel=dict(bgcolor="rgba(74, 85, 104, 0.9)", font_color="white")
        )
    ])
    
    fig.update_layout(
        title=dict(
            text='<b>💹 התפלגות מחירי קופונים</b>',
            font=dict(size=18, color='#2d3748', family='Inter'),
            x=0.5
        ),
        xaxis=dict(
            title=dict(text='<b>מחיר (₪)</b>', font=dict(size=14, color='#4a5568')),
            tickfont=dict(size=12, color='#4a5568'),
            showgrid=True,
            gridcolor='rgba(74, 85, 104, 0.1)',
            gridwidth=1
        ),
        yaxis=dict(
            title=dict(text='<b>כמות קופונים</b>', font=dict(size=14, color='#4a5568')),
            tickfont=dict(size=12, color='#4a5568'),
            showgrid=True,
            gridcolor='rgba(74, 85, 104, 0.1)',
            gridwidth=1
        ),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(255,255,255,0.95)',
        height=450,
        margin=dict(l=60, r=40, t=80, b=60),
        font=dict(family='Inter, Arial', size=12),
        showlegend=False,
        bargap=0.1
    )
    
    return fig.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

def calculate_roi_metrics(data):
    """חישוב מטריקות ROI"""
    if not data:
        return {}
    
    total_value = sum(item['total_value'] for item in data)
    total_cost = sum(item['total_cost'] for item in data)
    
    if total_value > 0:
        average_roi = ((total_value - total_cost) / total_value) * 100
    else:
        average_roi = 0
    
    return {
        'total_value': total_value,
        'total_cost': total_cost,
        'average_roi': round(average_roi, 2),
        'total_savings': total_value - total_cost
    }

def get_top_insights(data, recent_activity, expiring_coupons):
    """יצירת 3 תובנות מרכזיות"""
    insights = []
    
    if data:
        # תובנה 1: החברה המובילה
        top_company = data[0]
        insights.append(f"🏆 {top_company['company']} מובילה עם {top_company['coupon_count']} קופונים פעילים")
        
        # תובנה 2: פעילות השבוע
        if recent_activity.get('week_count', 0) > 0:
            insights.append(f"📈 השבוע נוספו {recent_activity['week_count']} קופונים חדשים למערכת")
        
        # תובנה 3: התראת תפוגה
        if expiring_coupons:
            total_expiring = sum(item['expiring_count'] for item in expiring_coupons)
            insights.append(f"⚠️ {total_expiring} קופונים עומדים לפוג תוקף השבוע הקרוב")
    
    return insights[:3]  # רק 3 תובנות

def generate_enhanced_email_content(app):
    """יצירת תוכן המייל המשופר"""
    with app.app_context():
        # קבלת אפשרויות הדוח
        options = get_report_options()
        
        # איסוף נתונים בסיסיים
        basic_stats = get_basic_stats()
        
        # חישוב נתונים נוספים לפי הצורך
        weekly_trend = get_weekly_trend_data() if options.get('chart_weekly_trend') else []
        expiring_coupons = get_expiring_coupons() if options.get('metrics_expiring') else []
        recent_activity = get_recent_activity() if options.get('metrics_recent_activity') else {}
        roi_metrics = calculate_roi_metrics(basic_stats) if options.get('metrics_roi') else {}
        new_users_count = get_new_users_count() if options.get('metrics_recent_activity') else 0
        
        # יצירת גרפים
        charts = {}
        if options.get('chart_coupons_by_company'):
            charts['coupons_by_company'] = create_coupons_by_company_chart(basic_stats)
        
        if options.get('chart_value_pie'):
            charts['value_pie'] = create_value_pie_chart(basic_stats)
        
        if options.get('chart_weekly_trend'):
            charts['weekly_trend'] = create_weekly_trend_chart(weekly_trend)
        
        if options.get('chart_price_histogram'):
            charts['price_histogram'] = create_price_histogram(basic_stats)
        
        # יצירת תובנות
        insights = []
        if options.get('insights_top3'):
            insights = get_top_insights(basic_stats, recent_activity, expiring_coupons)
        
        # יצירת HTML - משתמש בתבנית מותאמת למייל
        from flask import render_template
        html_content = render_template(
            'emails/email_optimized_report.html',
            basic_stats=basic_stats,
            charts=charts,
            insights=insights,
            roi_metrics=roi_metrics,
            recent_activity=recent_activity,
            expiring_coupons=expiring_coupons,
            new_users_count=new_users_count,
            options=options,
            report_date=date.today().strftime("%Y-%m-%d")
        )
        
        return html_content


def generate_full_email_content(app):
    """יצירת תוכן המייל המלא לצפייה בדפדפן"""
    with app.app_context():
        # קבלת אפשרויות הדוח
        options = get_report_options()
        
        # איסוף נתונים בסיסיים
        basic_stats = get_basic_stats()
        
        # חישוב נתונים נוספים לפי הצורך
        weekly_trend = get_weekly_trend_data() if options.get('chart_weekly_trend') else []
        expiring_coupons = get_expiring_coupons() if options.get('metrics_expiring') else []
        recent_activity = get_recent_activity() if options.get('metrics_recent_activity') else {}
        roi_metrics = calculate_roi_metrics(basic_stats) if options.get('metrics_roi') else {}
        new_users_count = get_new_users_count() if options.get('metrics_recent_activity') else 0
        
        # יצירת גרפים
        charts = {}
        if options.get('chart_coupons_by_company'):
            charts['coupons_by_company'] = create_coupons_by_company_chart(basic_stats)
        
        if options.get('chart_value_pie'):
            charts['value_pie'] = create_value_pie_chart(basic_stats)
        
        if options.get('chart_weekly_trend'):
            charts['weekly_trend'] = create_weekly_trend_chart(weekly_trend)
        
        if options.get('chart_price_histogram'):
            charts['price_histogram'] = create_price_histogram(basic_stats)
        
        # יצירת תובנות
        insights = []
        if options.get('insights_top3'):
            insights = get_top_insights(basic_stats, recent_activity, expiring_coupons)
        
        # יצירת HTML מלא
        from flask import render_template
        html_content = render_template(
            'emails/enhanced_daily_report.html',
            basic_stats=basic_stats,
            charts=charts,
            insights=insights,
            roi_metrics=roi_metrics,
            recent_activity=recent_activity,
            expiring_coupons=expiring_coupons,
            new_users_count=new_users_count,
            options=options,
            report_date=date.today().strftime("%Y-%m-%d")
        )
        
        return html_content