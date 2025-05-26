from flask import Blueprint, abort, current_app, render_template_string
from flask_login import login_required, current_user
import os
import sys
import pandas as pd
import requests
import re
from dotenv import load_dotenv
import plotly.express as px
import plotly.graph_objects as go
from plotly.offline import plot as plotly_plot
from app.extensions import db
from sqlalchemy.sql import text
from flask import (
    Blueprint,
    abort,
    current_app,
    render_template_string,
    request,
    jsonify,
)

# טוען משתני סביבה
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "❌ שגיאה: יש להגדיר את SUPABASE_URL ואת SUPABASE_ANON_KEY בקובץ .env"
    )

admin_dashboard_bp = Blueprint("admin_dashboard_bp", __name__)


def is_admin(user):
    # פונקציה לבדיקת הרשאות מנהל – עדכן בהתאם למערכת שלך
    return getattr(user, "is_admin", False)


#########################################
# פונקציות לשליפת ועיבוד הנתונים
#########################################


def fetch_data() -> pd.DataFrame:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{SUPABASE_URL}/rest/v1/coupon"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        df = pd.DataFrame(data)

        # סינון קופונים שמסומן בהם exclude_saving = True
        if "exclude_saving" in df.columns:
            df = df[df["exclude_saving"] != True]

        if "date_added" in df.columns:
            df["date_added"] = pd.to_datetime(df["date_added"], errors="coerce")
        if "expiration" in df.columns:
            df["expiration"] = pd.to_datetime(df["expiration"], errors="coerce")
        return df
    else:
        print("⚠️ שגיאה בשליפת הנתונים:", response.text)
        return pd.DataFrame()


def calculate_discount(df: pd.DataFrame) -> pd.DataFrame:
    """
    מחשב את עמודת discount_percentage אם היא לא קיימת או ריקה
    """
    if (
        "discount_percentage" not in df.columns
        or df["discount_percentage"].isnull().all()
    ):
        df["discount_percentage"] = df.apply(
            lambda row: ((row["value"] - row["cost"]) / row["value"] * 100)
            if row.get("value", 0) != 0
            else None,
            axis=1,
        )
    # עיגול לשתי ספרות אחרי הנקודה
    df["discount_percentage"] = df["discount_percentage"].round(2)
    return df


def set_layout(fig):
    fig.update_layout(
        autosize=True,
        margin=dict(l=20, r=20, t=50, b=80),  # להגדיל ל-120 או יותר
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )


#########################################
# פונקציות לשליפת נתונים נוספים – משתמשים, פעילויות וחברות
#########################################


def fetch_users() -> pd.DataFrame:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{SUPABASE_URL}/rest/v1/users"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return pd.DataFrame(data)
    else:
        print("⚠️ שגיאה בשליפת המשתמשים:", response.text)
        return pd.DataFrame()


def fetch_active_users_count() -> int:
    stmt = text(
        """
        SELECT COUNT(DISTINCT user_id) AS active_users_count
        FROM user_activities
        WHERE timestamp >= NOW() - INTERVAL '48 HOURS'
          AND user_id IS NOT NULL
    """
    )

    row = db.session.execute(stmt).fetchone()
    if not row:
        return 0
    return row.active_users_count


def fetch_companies() -> list:
    stmt = text("SELECT DISTINCT name FROM companies")
    result = db.session.execute(stmt).fetchall()
    return [row.name for row in result]


#########################################
# דשבורד חדש – KPI ותרשים "ערך וקופון ממוצע לכל החברות" עם תיבת בחירה רב-ברירתית
#########################################


def build_new_dashboard() -> str:
    df_all = fetch_data()
    if df_all.empty:
        return """
        <div id="new_dashboard">
            <div class="kpi-container">
                <div class="kpi">
                    <div class="kpi-value">❌</div>
                    <div class="kpi-label">אין נתונים זמינים</div>
                </div>
            </div>
            <div style='text-align:center; color:red;'>❌ לא נמצאו נתונים להמשך עיבוד.</div>
        </div>
        """

    df_all = calculate_discount(df_all)

    # חישובי KPI
    if "status" in df_all.columns:
        active_coupons = df_all[~df_all["status"].isin(["נוצל", "sold"])].shape[0]
    else:
        active_coupons = df_all.shape[0]
    avg_discount = (
        round(df_all["discount_percentage"].mean(), 2)
        if df_all["discount_percentage"].notnull().any()
        else 0
    )

    users_df = fetch_users()
    registered_users = users_df.shape[0] if not users_df.empty else 0

    active_users_count = fetch_active_users_count()
    print(active_users_count)

    coupons_for_sale = df_all[
        (df_all.get("is_for_sale") == True) & (df_all.get("status") == "פעיל")
    ].shape[0]

    # הכנת נתונים לגרף "ערך וקופון ממוצע לכל החברות"
    if "company" in df_all.columns:
        agg = (
            df_all.groupby("company")
            .agg({"value": "mean", "cost": "mean"})
            .reset_index()
        )
        agg = agg.sort_values("value", ascending=False)
        companies = agg["company"].tolist()
        avgValue = agg["value"].tolist()
        avgCost = agg["cost"].tolist()
    else:
        companies = []
        avgValue = []
        avgCost = []

    # בניית גרף (Scatter) עבור ערך ועלות ממוצעים
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=avgValue,
            y=companies,
            mode="markers",
            marker=dict(color="rgb(55,83,109)", size=12),
            name="ערך ממוצע",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=avgCost,
            y=companies,
            mode="markers",
            marker=dict(color="rgb(26,118,255)", size=12),
            name="עלות ממוצע",
        )
    )
    fig.update_layout(
        title="ערך וקופון ממוצע לכל החברות",
        xaxis_title='ערך (בש"ח)',
        yaxis=dict(autorange="reversed"),
        margin=dict(l=100, r=50, t=50, b=50),
        height=350,
    )
    div_company_chart = plotly_plot(
        fig, include_plotlyjs=False, output_type="div", config={"responsive": True}
    )

    # בניית ה-HTML של הדשבורד החדש
    new_dashboard_section = f"""
    <div id="new_dashboard">
      <!-- שורת KPI עם 5 קארדים -->
      <div class="kpi-container">
         <div class="kpi">
           <div class="kpi-value" id="kpiCoupons">{active_coupons}</div>
           <div class="kpi-label">קופונים פעילים במערכת</div>
         </div>
         <div class="kpi">
           <div class="kpi-value" id="kpiDiscount">{avg_discount}%</div>
           <div class="kpi-label">אחוז הנחה ממוצע</div>
         </div>
         <div class="kpi">
           <div class="kpi-value" id="kpiRegistered">{registered_users}</div>
           <div class="kpi-label">משתמשים רשומים</div>
         </div>
         <div class="kpi">
           <div class="kpi-value" id="kpiActiveUsers">{active_users_count}</div>
           <div class="kpi-label">משתמשים פעילים</div>
         </div>
         <div class="kpi">
           <div class="kpi-value" id="kpiCouponsForSale">{coupons_for_sale}</div>
           <div class="kpi-label">קופונים למכירה</div>
         </div>
      </div>

      <!-- אזור לגרף והסינון – מוצגים בשורה אחת -->
      <div class="chart-filter-container" style="display: flex; justify-content: center; align-items: flex-start; gap: 20px; margin-bottom: 20px;">
         <div id="companyFilter" style="text-align:center;">
            <label for="companySelect">בחר חברות:</label><br>
            <select id="companySelect" multiple size="15" style="width:300px; padding:5px; font-size:1em;">
    """
    for comp in companies:
        new_dashboard_section += (
            f'              <option value="{comp}" selected>{comp}</option>\n'
        )
    new_dashboard_section += f"""            </select>
                        <br><br>
                        <button id="selectAllBtn" style="padding:5px; font-size:0.9em; margin-right:5px;">סימון הכל</button>
                        <button id="deselectAllBtn" style="padding:5px; font-size:0.9em; margin-right:5px;">ביטול סימון הכל</button>
                        <button id="updateChartBtn" style="padding:5px; font-size:0.9em;">עדכן גרף</button>
                    </div>

                    <div id="companyChartContainer" style="width:100%; max-width:600px; height:350px; background:#fff; border-radius:8px; box-shadow:0 2px 4px rgba(0,0,0,0.1); position:relative;">
                        {div_company_chart}
                    </div>
                </div>

                <script>
                    // מערכים שמגיעים מ־Python לצורך הצגה התחלתית (לא בהכרח בשימוש בקריאה לשרת)
                    var companies = [{",".join([f'"{c}"' for c in companies])}];
                    var avgValue = [{",".join([str(v) for v in avgValue])}];
                    var avgCost = [{",".join([str(c) for c in avgCost])}];

                    // שומר את ה־csrfToken מתוך ה־meta 
                    var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

                    // פונקציה: סימון הכל
                    document.getElementById('selectAllBtn').addEventListener('click', function() {{
                        var selectElement = document.getElementById('companySelect');
                        for (var i = 0; i < selectElement.options.length; i++) {{
                            selectElement.options[i].selected = true;
                        }}
                    }});

                    // פונקציה: ביטול סימון הכל
                    document.getElementById('deselectAllBtn').addEventListener('click', function() {{
                        var selectElement = document.getElementById('companySelect');
                        for (var i = 0; i < selectElement.options.length; i++) {{
                            selectElement.options[i].selected = false;
                        }}
                    }});

                    // הפונקציה המרכזית: שולחת POST לשרת עם רשימת החברות הנבחרות
                    function updateGraph() {{
                        var selectElement = document.getElementById('companySelect');
                        var selectedOptions = Array.from(selectElement.selectedOptions).map(function(opt) {{
                            return opt.value;
                        }});

                        // שמירת ה-CSRF Token מתוך ה-meta
                        var csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');
                        var csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute('content') : null;
                        
                        // בדיקה אם ה-CSRF Token קיים
                        if (!csrfToken) {{
                            console.error("🚨 CSRF Token is missing from the page!");
                        }}

                        fetch('/admin/update_company_chart', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                                'X-CSRF-Token': csrfToken  // עם מקף במקום קו תחתון
                            }},
                            body: JSON.stringify({{ companies: selectedOptions }})
                        }})
                        .then(response => {{
                            if (!response.ok) {{
                                throw new Error('Network response was not ok');
                            }}
                            return response.json();
                        }})
                        .then(data => {{
                            if (data.chart_div) {{
                                // מחליפים את ה־HTML הקיים בתוכן שחזר מהשרת
                                document.getElementById('companyChartContainer').innerHTML = data.chart_div;
                            }} else if (data.error) {{
                                console.error("Error:", data.error);
                            }}
                        }})
                        .catch(error => console.error('Error:', error));
                    }}

                    // מאזינים לאירוע "קליק" בכפתור 'עדכן גרף'
                    document.getElementById('updateChartBtn').addEventListener('click', updateGraph);
                </script>
                </div>
                """

    return new_dashboard_section


#########################################
# פונקציות לגרפים הישנים (old dashboard)
#########################################


def plot_coupon_usage(df: pd.DataFrame):
    usage = df.groupby(["company", "status"])["id"].count().reset_index(name="count")
    total_usage = usage.groupby("company")["count"].sum().reset_index(name="total")
    companies_order = total_usage.sort_values("total", ascending=False)[
        "company"
    ].tolist()
    fig = px.bar(
        usage,
        x="company",
        y="count",
        color="status",
        title="שימוש בקופונים לפי חברה",
        labels={"company": "חברה", "count": "מספר קופונים", "status": "סטטוס"},
        category_orders={"company": companies_order},
        template="plotly_white",
    )
    fig.update_layout(
        xaxis_title_standoff=50,  # מרחק הכותרת מתוויות הציר
        margin=dict(b=150),  # הגדלת מרווח תחתון
        xaxis_tickangle=45,
    )
    set_layout(fig)
    return fig


def plot_discount_distribution(df: pd.DataFrame):
    discount_avg = df.groupby("company")["discount_percentage"].mean().reset_index()
    discount_avg = discount_avg.sort_values("discount_percentage", ascending=False)
    fig = px.bar(
        discount_avg,
        x="company",
        y="discount_percentage",
        title="אחוז הנחה ממוצע לפי חברה",
        labels={"company": "חברה", "discount_percentage": "אחוז הנחה ממוצע"},
        template="plotly_white",
        color="discount_percentage",
        color_continuous_scale="Oranges",
    )
    fig.update_layout(
        xaxis_title_standoff=50,  # מרחק הכותרת מתוויות הציר
        margin=dict(b=150),  # הגדלת מרווח תחתון
        xaxis_tickangle=45,
    )
    fig.update_traces(hovertemplate="אחוז הנחה ממוצע: %{y:.2f}%<extra></extra>")
    set_layout(fig)
    return fig


def plot_active_users(df: pd.DataFrame):
    if "user_id" not in df.columns:
        return None
    df = df.dropna(subset=["user_id"])
    df["user_id"] = df["user_id"].astype(str).str.strip()
    df = df[df["user_id"] != ""]
    user_usage = df.groupby("user_id")["id"].count().reset_index(name="coupon_count")
    user_usage = user_usage.sort_values("coupon_count", ascending=False)
    fig = px.bar(
        user_usage,
        x="user_id",
        y="coupon_count",
        title="המשתמשים הכי פעילים - מספר קופונים",
        labels={"user_id": "משתמש", "coupon_count": "מספר קופונים"},
        template="plotly_white",
        color="coupon_count",
        color_continuous_scale="Viridis",
        category_orders={"user_id": user_usage["user_id"].tolist()},
    )
    fig.update_layout(
        xaxis_title_standoff=50,  # מרחק הכותרת מתוויות הציר
        margin=dict(b=150),  # הגדלת מרווח תחתון
        xaxis_tickangle=45,
    )
    set_layout(fig)
    return fig


def plot_cost_details(df: pd.DataFrame):
    q1 = df["cost"].quantile(0.25)
    q3 = df["cost"].quantile(0.75)
    iqr = q3 - q1
    upper_bound = q3 + 2 * iqr
    df_filtered = df[df["cost"] <= upper_bound].copy()

    trace_with = go.Box(
        y=df["cost"],
        name="כולל outliers",
        boxpoints="all",
        marker=dict(color="rgba(222,45,38,0.8)"),
    )
    trace_without = go.Box(
        y=df_filtered["cost"],
        name="ללא outliers",
        boxpoints=False,
        marker=dict(color="rgba(55,128,191,0.8)"),
    )
    fig = go.Figure(data=[trace_without, trace_with])
    fig.data[0].visible = True
    fig.data[1].visible = False
    fig.update_layout(
        title="תשלום עבור קופונים - התפלגות המחירים (ללא outliers)",
        title_x=0.5,
        updatemenus=[
            dict(
                type="buttons",
                direction="left",
                buttons=[
                    dict(
                        label="ללא outliers",
                        method="update",
                        args=[
                            {"visible": [True, False]},
                            {
                                "title": "תשלום עבור קופונים - התפלגות המחירים (ללא outliers)"
                            },
                        ],
                    ),
                    dict(
                        label="כולל outliers",
                        method="update",
                        args=[
                            {"visible": [False, True]},
                            {
                                "title": "תשלום עבור קופונים - התפלגות המחירים (כולל outliers)"
                            },
                        ],
                    ),
                ],
                pad={"r": 10, "t": 10},
                showactive=True,
                x=1.0,
                xanchor="right",
                y=1.15,
                yanchor="top",
            )
        ],
    )
    set_layout(fig)
    return fig


def plot_coupons_by_month(df: pd.DataFrame):
    if "date_added" not in df.columns:
        return None
    df = df.copy()
    df["year_month"] = df["date_added"].dt.to_period("M").astype(str)
    month_counts = (
        df.groupby("year_month")["id"].count().reset_index(name="coupon_count")
    )
    month_counts["year_month_dt"] = pd.to_datetime(
        month_counts["year_month"], format="%Y-%m"
    )
    month_counts = month_counts.sort_values("year_month_dt")
    fig = px.bar(
        month_counts,
        x="year_month",
        y="coupon_count",
        title="כמות קופונים שנקנו לפי חודש",
        labels={"year_month": "חודש", "coupon_count": "כמות קופונים"},
        template="plotly_white",
        color="coupon_count",
        color_continuous_scale="Blues",
    )
    fig.update_layout(
        xaxis_title_standoff=50,  # מרחק הכותרת מתוויות הציר
        margin=dict(b=150),  # הגדלת מרווח תחתון
        xaxis_tickangle=45,
    )
    set_layout(fig)
    return fig


def plot_discount_by_month(df: pd.DataFrame):
    if "date_added" not in df.columns:
        return None
    df = df.copy()
    df["year_month"] = df["date_added"].dt.to_period("M").astype(str)
    discount_by_month = (
        df.groupby("year_month")["discount_percentage"].mean().reset_index()
    )
    discount_by_month = discount_by_month.sort_values("year_month")
    fig = px.bar(
        discount_by_month,
        x="year_month",
        y="discount_percentage",
        title="אחוז הנחה ממוצע לפי חודש רכישת הקופון",
        labels={"year_month": "חודש", "discount_percentage": "אחוז הנחה ממוצע"},
        template="plotly_white",
        color="discount_percentage",
        color_continuous_scale="Blues",
    )
    fig.update_traces(hovertemplate="אחוז הנחה ממוצע: %{y:.2f}%<extra></extra>")
    fig.update_layout(
        xaxis_title_standoff=50,  # מרחק הכותרת מתוויות הציר
        margin=dict(b=150),  # הגדלת מרווח תחתון
        xaxis_tickangle=45,
    )
    set_layout(fig)
    return fig


def plot_avg_value_cost_by_company(df: pd.DataFrame):
    if "company" not in df.columns:
        return None
    agg = df.groupby("company").agg({"value": "mean", "cost": "mean"}).reset_index()
    agg = agg.sort_values("value", ascending=False)
    fig = go.Figure(
        data=[
            go.Bar(
                name="ערך ממוצע",
                x=agg["company"],
                y=agg["value"],
                marker_color="rgb(55,83,109)",
            ),
            go.Bar(
                name="עלות ממוצע",
                x=agg["company"],
                y=agg["cost"],
                marker_color="rgb(26,118,255)",
            ),
        ]
    )
    companies = agg["company"].tolist()
    buttons = [
        dict(
            label="כל החברות",
            method="update",
            args=[
                {
                    "x": [agg["company"], agg["company"]],
                    "y": [agg["value"], agg["cost"]],
                },
                {"title": "ערך וקופון ממוצע לכל החברות"},
            ],
        )
    ]
    for comp in companies:
        filtered = agg[agg["company"] == comp]
        buttons.append(
            dict(
                label=comp,
                method="update",
                args=[
                    {"visible": [False, False]},
                    {"title": f"ערך וקופון ממוצע עבור {comp}"},
                ],
            )
        )
    fig.update_layout(
        barmode="group",
        title="ערך וקופון ממוצע לפי חברה",
        xaxis_title="חברה",
        yaxis_title='בש"ח',
        updatemenus=[
            dict(
                type="dropdown",
                direction="down",
                showactive=True,
                x=1.0,
                xanchor="right",
                y=1.15,
                yanchor="top",
                buttons=buttons,
            )
        ],
    )
    set_layout(fig)
    return fig


def plot_usage_vs_discount(df: pd.DataFrame):
    if "value" not in df.columns:
        return None
    df = df.copy()
    df["usage_percentage"] = df.apply(
        lambda row: (row["used_value"] / row["value"] * 100)
        if row["value"] != 0
        else 0,
        axis=1,
    )
    fig = px.scatter(
        df,
        x="discount_percentage",
        y="usage_percentage",
        color="company",
        title="שיעור שימוש בקופונים לעומת אחוז הנחה",
        labels={"discount_percentage": "אחוז הנחה", "usage_percentage": "אחוז שימוש"},
        template="plotly_white",
        hover_data=["code"],
    )
    fig.update_layout(
        xaxis_title_standoff=50,  # מרחק הכותרת מתוויות הציר
        margin=dict(b=150),  # הגדלת מרווח תחתון
        xaxis_tickangle=45,
    )
    set_layout(fig)
    return fig


def plot_discount_distribution_hist(df: pd.DataFrame):
    if "discount_percentage" not in df.columns:
        return None
    fig = px.histogram(
        df,
        x="discount_percentage",
        nbins=20,
        title="התפלגות אחוזי הנחה בקופונים",
        labels={"discount_percentage": "אחוז הנחה", "count": "מספר קופונים"},
        template="plotly_white",
        color_discrete_sequence=["indianred"],
    )
    fig.update_layout(
        xaxis_title_standoff=50,  # מרחק הכותרת מתוויות הציר
        margin=dict(b=150),  # הגדלת מרווח תחתון
        xaxis_tickangle=45,
    )
    set_layout(fig)
    return fig


def plot_drill_down_analysis(df: pd.DataFrame):
    companies = sorted(df["company"].unique())
    if not companies:
        return None
    traces = []
    for company in companies:
        df_company = df[df["company"] == company].copy()
        trace = go.Scatter(
            x=df_company["cost"],
            y=df_company["discount_percentage"],
            mode="markers",
            marker=dict(size=8),
            name=company,
            text=df_company["id"],
            hovertemplate=(
                "קופון: %{text}<br>"
                "תשלום: %{x}<br>"
                "אחוז הנחה: %{y:.2f}%<extra></extra>"
            ),
        )
        traces.append(trace)
    fig = go.Figure(data=traces)
    for i, trace in enumerate(fig.data):
        trace.visible = i == 0
    buttons = []
    for i, company in enumerate(companies):
        visibility = [False] * len(companies)
        visibility[i] = True
        button = dict(
            label=company,
            method="update",
            args=[
                {"visible": visibility},
                {"title": f"Drill Down Analysis: {company}"},
            ],
        )
        buttons.append(button)
    fig.update_layout(
        title=f"Drill Down Analysis: {companies[0]}",
        xaxis_title="תשלום (מחיר הקופון)",
        yaxis_title="אחוז הנחה",
        updatemenus=[
            {
                "buttons": buttons,
                "direction": "down",
                "showactive": True,
                "x": 1,
                "xanchor": "right",
                "y": 1,
                "yanchor": "top",
            }
        ],
    )
    set_layout(fig)
    return fig


def plot_user_max_discount(df: pd.DataFrame):
    if "user_id" not in df.columns:
        return None
    user_max = df.groupby("user_id")["discount_percentage"].max().reset_index()
    user_max = user_max.sort_values("discount_percentage", ascending=False)
    fig = px.bar(
        user_max,
        x="user_id",
        y="discount_percentage",
        title="אחוז ההנחה הגבוה ביותר לפי משתמש",
        labels={"user_id": "משתמש", "discount_percentage": "אחוז הנחה"},
        template="plotly_white",
        color="discount_percentage",
        color_continuous_scale="Oranges",
    )
    fig.update_layout(
        xaxis_title_standoff=50,  # מרחק הכותרת מתוויות הציר
        margin=dict(b=150),  # הגדלת מרווח תחתון
        xaxis_tickangle=45,
    )
    set_layout(fig)
    return fig


def plot_user_sold_coupons(df: pd.DataFrame):
    if "status" not in df.columns or "user_id" not in df.columns:
        return None
    sold = df[df["status"] == "נוצל"]
    user_sold = sold.groupby("user_id")["id"].count().reset_index(name="sold_count")
    user_sold = user_sold.sort_values("sold_count", ascending=False)
    fig = px.bar(
        user_sold,
        x="user_id",
        y="sold_count",
        title="כמות הקופונים שמכרו המשתמשים",
        labels={"user_id": "משתמש", "sold_count": "קופונים שנמכרו"},
        template="plotly_white",
        color="sold_count",
        color_continuous_scale="Greens",
    )
    fig.update_layout(title={"x": 0.5})
    set_layout(fig)
    return fig


#########################################
# פונקציות לבניית תוכן הדשבורד
#########################################


def generate_dashboard_content(fig_divs):
    """
    בונה את תוכן הדשבורד: כולל את הגרפים במבנה grid
    """
    content = '<div class="grid-container">\n'
    for div in fig_divs:
        content += f'<div class="chart-container">{div}</div>\n'
    content += "</div>\n"
    return content


def generate_full_dashboard_html(dashboards: dict, unique_users: list) -> str:
    """
    בונה מחרוזת HTML מלאה עם תפריט לבחירת משתמש והגרפים במבנה grid.
    """
    plotly_js = '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>'
    options = '<option value="all">כל המשתמשים</option>\n'
    for user in unique_users:
        options += f'<option value="{user}">{user}</option>\n'
    header_html = f"""
    <div class="header-container">
        <label for="userSelect"><strong>בחר משתמש: </strong></label>
        <select id="userSelect" onchange="changeDashboard()">
            {options}
        </select>
    </div>
    """
    dashboards_html = (
        '<div class="dashboard-container">\n<div id="dashboardContainer">\n'
    )
    for key, content in dashboards.items():
        dashboards_html += f'<div id="dashboard_{key}" class="dashboard" style="display:none;">\n{content}</div>\n'
    dashboards_html += "</div>\n</div>\n"
    full_content = (
        header_html
        + dashboards_html
        + """
    <script>
        function changeDashboard() {
            var sel = document.getElementById("userSelect");
            var value = sel.value;
            var dashboards = document.getElementsByClassName("dashboard");
            for (var i = 0; i < dashboards.length; i++) {
                dashboards[i].style.display = "none";
            }
            document.getElementById("dashboard_" + value).style.display = "block";
            setTimeout(function() { window.dispatchEvent(new Event('resize')); }, 500);
        }
        window.onload = function() {
            document.getElementById("userSelect").value = "all";
            changeDashboard();
        };
    </script>
    """
    )
    return plotly_js + full_content


@admin_dashboard_bp.route("/update_company_chart", methods=["POST"])
@login_required
def update_company_chart():
    print("Received request at /update_company_chart")  # בדיקה אם זה נקרא
    # ודא שהמשתמש הוא מנהל
    if not is_admin(current_user):
        abort(403)

    # קבלת רשימת החברות שנבחרו מהבקשה (מצופה לקבל JSON עם מפתח "companies")
    try:
        req_data = request.get_json()
        selected_companies = req_data.get("companies", [])
        csrf_token = request.headers.get("X-CSRF-Token")  # בדיקה אם נשלח מהלקוח
        print(f"🔹 CSRF Token שהתקבל: {csrf_token}")  # הדפסה ל-Log

        if not csrf_token:
            return jsonify({"error": "CSRF Token is missing"}), 400

    except Exception as e:
        return jsonify({"error": "נתוני בקשה לא תקינים"}), 400

    # שליפת הנתונים ועיבודם
    df_all = fetch_data()
    if df_all.empty:
        return jsonify({"error": "אין נתונים זמינים"}), 404

    df_all = calculate_discount(df_all)

    # סינון הנתונים לפי החברות שנבחרו (אם נבחרו)
    if selected_companies:
        df_all = df_all[df_all["company"].isin(selected_companies)]

    # הכנת הנתונים לגרף
    if "company" in df_all.columns:
        agg = (
            df_all.groupby("company")
            .agg({"value": "mean", "cost": "mean"})
            .reset_index()
        )
        agg = agg.sort_values("value", ascending=False)
        companies = agg["company"].tolist()
        avgValue = agg["value"].tolist()
        avgCost = agg["cost"].tolist()
    else:
        companies = []
        avgValue = []
        avgCost = []

    # בניית התרשים בעזרת Plotly
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=avgValue,
            y=companies,
            mode="markers",
            marker=dict(color="rgb(55,83,109)", size=12),
            name="ערך ממוצע",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=avgCost,
            y=companies,
            mode="markers",
            marker=dict(color="rgb(26,118,255)", size=12),
            name="עלות ממוצע",
        )
    )
    fig.update_layout(
        title="ערך וקופון ממוצע לכל החברות",
        xaxis_title='ערך (בש"ח)',
        yaxis=dict(autorange="reversed"),
        margin=dict(l=100, r=50, t=50, b=50),
        height=350,
    )

    # יצירת HTML לתרשים
    updated_chart_div = plotly_plot(
        fig, include_plotlyjs=False, output_type="div", config={"responsive": True}
    )

    return jsonify({"chart_div": updated_chart_div})


def build_dashboard() -> str:
    df_all = fetch_data()
    if df_all.empty:
        return "❌ לא נמצאו נתונים להמשך עיבוד."
    df_all = calculate_discount(df_all)

    # חלק חדש – KPI וגרף "ערך וקופון ממוצע לכל החברות" עם סינון חברות
    new_dashboard_section = build_new_dashboard()

    # חלק ישן – הגרפים השונים לפי משתמש (כולל תפריט לבחירת משתמש)
    unique_users = []
    if "user_id" in df_all.columns:
        unique_users = sorted({str(u) for u in df_all["user_id"].unique()})
    dashboards = {}
    keys = ["all"] + unique_users

    for key in keys:
        if key == "all":
            df = df_all.copy()
        else:
            try:
                user_numeric = int(key)
                df = df_all[df_all["user_id"] == user_numeric].copy()
            except ValueError:
                df = df_all[df_all["user_id"] == key].copy()

        fig_divs = []
        fig1 = plot_coupon_usage(df)
        if fig1:
            fig_divs.append(
                plotly_plot(
                    fig1,
                    include_plotlyjs=False,
                    output_type="div",
                    config={"responsive": True},
                )
            )
        fig2 = plot_discount_distribution(df)
        if fig2:
            fig_divs.append(
                plotly_plot(
                    fig2,
                    include_plotlyjs=False,
                    output_type="div",
                    config={"responsive": True},
                )
            )
        fig3 = plot_active_users(df)
        if fig3:
            fig_divs.append(
                plotly_plot(
                    fig3,
                    include_plotlyjs=False,
                    output_type="div",
                    config={"responsive": True},
                )
            )
        fig4 = plot_cost_details(df)
        if fig4:
            fig_divs.append(
                plotly_plot(
                    fig4,
                    include_plotlyjs=False,
                    output_type="div",
                    config={"responsive": True},
                )
            )
        fig5 = plot_coupons_by_month(df)
        if fig5:
            fig_divs.append(
                plotly_plot(
                    fig5,
                    include_plotlyjs=False,
                    output_type="div",
                    config={"responsive": True},
                )
            )
        fig6 = plot_discount_by_month(df)
        if fig6:
            fig_divs.append(
                plotly_plot(
                    fig6,
                    include_plotlyjs=False,
                    output_type="div",
                    config={"responsive": True},
                )
            )
        fig7 = plot_avg_value_cost_by_company(df)
        if fig7:
            fig_divs.append(
                plotly_plot(
                    fig7,
                    include_plotlyjs=False,
                    output_type="div",
                    config={"responsive": True},
                )
            )
        # fig8 = plot_usage_vs_discount(df)
        # if fig8:
        #    fig_divs.append(plotly_plot(fig8, include_plotlyjs=False, output_type='div', config={'responsive': True}))
        # fig9 = plot_discount_distribution_hist(df)
        # if fig9:
        #    fig_divs.append(plotly_plot(fig9, include_plotlyjs=False, output_type='div', config={'responsive': True}))
        # fig10 = plot_drill_down_analysis(df)
        # if fig10:
        #    fig_divs.append(plotly_plot(fig10, include_plotlyjs=False, output_type='div', config={'responsive': True}))

        # גרפים כלליים - רק בלשונית "all"
        if key == "all":
            fig12 = plot_user_max_discount(df_all)
            if fig12:
                fig_divs.append(
                    plotly_plot(
                        fig12,
                        include_plotlyjs=False,
                        output_type="div",
                        config={"responsive": True},
                    )
                )
            fig13 = plot_user_sold_coupons(df_all)
            if fig13:
                fig_divs.append(
                    plotly_plot(
                        fig13,
                        include_plotlyjs=False,
                        output_type="div",
                        config={"responsive": True},
                    )
                )

        dashboards[key] = generate_dashboard_content(fig_divs)

    old_dashboard_section = f"""<div id="old_dashboard">{generate_full_dashboard_html(dashboards, unique_users)}</div>"""

    # HTML מלא כולל סגנונות מעודכנים
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="csrf-token" content="{{ csrf_token() }}">
    <title>Dashboard - כל הגרפים</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            direction: rtl;
        }}
        /* New Dashboard Styles */
        .kpi-container {{
            display: flex;
            justify-content: space-around;
            margin-bottom: 30px;
            gap: 20px;
        }}
        .kpi {{
            background: #ffffff;
            border-radius: 8px;
            padding: 20px;
            width: 18%;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .kpi-value {{
            font-size: 2.5em;
            font-weight: bold;
            color: #2a3f5f;
        }}
        .kpi-label {{
            font-size: 1em;
            color: #555;
            margin-top: 10px;
        }}
        .chart-filter-container {{
            margin-bottom: 20px;
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
        }}
        /* Old Dashboard Styles */
        .header-container {{
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 20px;
            font-size: 16px;
        }}
        .header-container select {{
            margin-left: 10px;
        }}
        .dashboard-container {{
            max-width: 1400px; 
            margin: 0 auto;
            padding: 0 10px;
        }}
        .grid-container {{
            display: grid;
            gap: 20px; 
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
        }}
        @media (max-width: 800px) {{
            .grid-container {{
                grid-template-columns: 1fr; 
            }}
            .kpi-container {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 10px;
            }}
            .kpi:nth-child(n+4) {{
                grid-column: span 1;
            }}
            .kpi {{
                width: 100%;
                min-width: 90px;
                max-width: 130px;
                padding: 12px;
                text-align: center;
            }}
            .kpi-value {{
                font-size: 1.6em;
            }}
            .kpi-label {{
                font-size: 0.9em;
            }}
        }}
        .chart-container {{
            background-color: #fff;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            position: relative;
            width: 90%;
            margin: 0 auto;
            min-height: 400px;
            max-width: 800px;
            padding: 10px; /* ריווח פנימי כדי שהתרשים לא ייחתך */
            box-sizing: border-box; /* לוודא שה-padding נספר כחלק מהרוחב הכולל */
            overflow: hidden;
        }}
        .chart-container .js-plotly-plot {{
            position: absolute;
            top: 0;
            left: 0;
            height: 100% !important;
            width: 100% !important;
        }}
        hr {{
            margin: 40px 0;
            border: none;
            border-top: 2px solid #ddd;
        }}
    </style>
</head>
<body>
    <!-- New Dashboard Section -->
    {new_dashboard_section}
    <hr>
    <!-- Old Dashboard Section -->
    {old_dashboard_section}
</body>
</html>
"""
    return full_html


#########################################
# הגדרת ה־route הראשי של הדשבורד
#########################################


@admin_dashboard_bp.route("/dashboard_coupons")
@login_required
def dashboard():
    if not is_admin(current_user):
        abort(403)
    html = build_dashboard()
    return render_template_string(html)
