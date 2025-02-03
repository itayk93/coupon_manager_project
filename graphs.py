#!/usr/bin/env python3
# dashboard.py

import os
import sys
import pandas as pd
import requests
import re
from dotenv import load_dotenv
import plotly.express as px
import plotly.graph_objects as go
from plotly.offline import plot as plotly_plot

# טוען משתנים מקובץ .env
load_dotenv()

# שליפת המשתנים
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ שגיאה: יש להגדיר את SUPABASE_URL ואת SUPABASE_ANON_KEY בקובץ .env")


# ------------------ פונקציות לעיבוד הנתונים ------------------

def fetch_data() -> pd.DataFrame:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    url = f"{SUPABASE_URL}/rest/v1/coupon"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        df = pd.DataFrame(data)
        if "date_added" in df.columns:
            df["date_added"] = pd.to_datetime(df["date_added"], errors="coerce")
        if "expiration" in df.columns:
            df["expiration"] = pd.to_datetime(df["expiration"], errors="coerce")
        return df
    else:
        print("⚠️ שגיאה בשליפת הנתונים:", response.text)
        return pd.DataFrame()


def calculate_discount(df: pd.DataFrame) -> pd.DataFrame:
    if "discount_percentage" not in df.columns or df["discount_percentage"].isnull().all():
        df["discount_percentage"] = df.apply(
            lambda row: ((row["value"] - row["cost"]) / row["value"] * 100)
            if row.get("value", 0) != 0 else None,
            axis=1
        )
    return df


# ------------------ פונקציות לגרפים ------------------

def plot_coupon_usage(df: pd.DataFrame):
    usage = df.groupby(["company", "status"])["id"].count().reset_index(name="count")
    total_usage = usage.groupby("company")["count"].sum().reset_index(name="total")
    companies_order = total_usage.sort_values("total", ascending=False)["company"].tolist()
    fig = px.bar(
        usage,
        x="company",
        y="count",
        color="status",
        title="שימוש בקופונים לפי חברה",
        labels={"company": "חברה", "count": "מספר קופונים", "status": "סטטוס"},
        category_orders={"company": companies_order},
        template="plotly_white"
    )
    fig.update_layout(
        title={'x': 0.5},
        xaxis_tickangle=-45
    )
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
        color_continuous_scale="Oranges"
    )
    fig.update_layout(
        title={'x': 0.5},
        xaxis_tickangle=-45
    )
    fig.update_traces(hovertemplate='אחוז הנחה ממוצע: %{y:.2f}%<extra></extra>')
    return fig


def plot_active_users(df: pd.DataFrame):
    if "user_id" not in df.columns:
        print("⚠️ העמודה 'user_id' לא נמצאה בנתונים. דילוג על גרף המשתמשים הפעילים.")
        return None
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
        color_continuous_scale="Viridis"
    )
    fig.update_layout(
        title={'x': 0.5},
        xaxis_tickangle=-45
    )
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
        marker=dict(color="rgba(222,45,38,0.8)")
    )
    trace_without = go.Box(
        y=df_filtered["cost"],
        name="ללא outliers",
        boxpoints=False,
        marker=dict(color="rgba(55,128,191,0.8)")
    )
    fig = go.Figure(data=[trace_without, trace_with])
    fig.data[0].visible = True
    fig.data[1].visible = False
    fig.update_layout(
        title="תשלום עבור קופונים - התפלגות המחירים (ללא outliers)",
        title_x=0.5,
        margin=dict(l=10, r=10, t=40, b=60),
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
                            {"title": "תשלום עבור קופונים - התפלגות המחירים (ללא outliers)",
                             "annotations": [
                                 dict(
                                     x=0.5,
                                     y=1.15,
                                     xref="paper",
                                     yref="paper",
                                     text=f"ערך חריג (outlier) הוא ערך שמתרחק משמעותית מהתפלגות הנתונים. ערכים מעל {upper_bound:.2f} הושמטו.",
                                     showarrow=False,
                                     font=dict(size=10, color="gray"),
                                     xanchor="center",
                                     align="center"
                                 )
                             ]}
                        ]
                    ),
                    dict(
                        label="כולל outliers",
                        method="update",
                        args=[
                            {"visible": [False, True]},
                            {"title": "תשלום עבור קופונים - התפלגות המחירים (כולל outliers)",
                             "annotations": []}
                        ]
                    )
                ],
                pad={"r": 10, "t": 10},
                showactive=True,
                x=1.0,
                xanchor="right",
                y=1.15,
                yanchor="top"
            )
        ]
    )
    return fig


def plot_coupons_by_month(df: pd.DataFrame):
    if "date_added" not in df.columns:
        print("⚠️ העמודה 'date_added' לא נמצאה בנתונים. דילוג על גרף זה.")
        return None
    df = df.copy()
    df["year_month"] = df["date_added"].dt.to_period("M").astype(str)
    month_counts = df.groupby("year_month")["id"].count().reset_index(name="coupon_count")
    month_counts["year_month_dt"] = pd.to_datetime(month_counts["year_month"], format="%Y-%m")
    month_counts = month_counts.sort_values("year_month_dt")
    fig = px.bar(
        month_counts,
        x="year_month",
        y="coupon_count",
        title="כמות קופונים שנקנו לפי חודש",
        labels={"year_month": "חודש", "coupon_count": "כמות קופונים"},
        template="plotly_white",
        color="coupon_count",
        color_continuous_scale="Blues"
    )
    fig.update_layout(
        title={'x': 0.5},
        xaxis_tickangle=-45
    )
    return fig


def plot_discount_by_month(df: pd.DataFrame):
    if "date_added" not in df.columns:
        print("⚠️ העמודה 'date_added' לא נמצאה בנתונים. דילוג על גרף זה.")
        return None
    df = df.copy()
    df["year_month"] = df["date_added"].dt.to_period("M").astype(str)
    discount_by_month = df.groupby("year_month")["discount_percentage"].mean().reset_index()
    discount_by_month = discount_by_month.sort_values("year_month")
    fig = px.bar(
        discount_by_month,
        x="year_month",
        y="discount_percentage",
        title="אחוז הנחה ממוצע לפי חודש רכישת הקופון",
        labels={"year_month": "חודש", "discount_percentage": "אחוז הנחה ממוצע"},
        template="plotly_white",
        color="discount_percentage",
        color_continuous_scale="Blues"
    )
    fig.update_layout(
        title={'x': 0.5},
        xaxis_tickangle=-45
    )
    return fig


def plot_avg_value_cost_by_company(df: pd.DataFrame):
    if "company" not in df.columns:
        print("⚠️ העמודה 'company' לא נמצאה בנתונים. דילוג על גרף זה.")
        return None
    agg = df.groupby("company").agg({'value': 'mean', 'cost': 'mean'}).reset_index()
    agg = agg.sort_values("value", ascending=False)
    fig = go.Figure(data=[
        go.Bar(name='ערך ממוצע', x=agg["company"], y=agg["value"], marker_color='rgb(55, 83, 109)'),
        go.Bar(name='עלות ממוצע', x=agg["company"], y=agg["cost"], marker_color='rgb(26, 118, 255)')
    ])
    companies = agg["company"].tolist()
    buttons = [
        dict(
            label="כל החברות",
            method="update",
            args=[{"x": [agg["company"], agg["company"]],
                   "y": [agg["value"], agg["cost"]]},
                  {"title": "ערך וקופון ממוצע לכל החברות"}]
        )
    ]
    for comp in companies:
        filtered = agg[agg["company"] == comp]
        buttons.append(
            dict(
                label=comp,
                method="update",
                args=[{"x": [[comp], [comp]],
                       "y": [filtered["value"], filtered["cost"]]},
                      {"title": f"ערך וקופון ממוצע עבור {comp}"}]
            )
        )
    fig.update_layout(
        barmode='group',
        title="ערך וקופון ממוצע לפי חברה",
        xaxis_title="חברה",
        yaxis_title="בש\"ח",
        updatemenus=[dict(
            type="dropdown",
            direction="down",
            showactive=True,
            x=1.0,
            xanchor="right",
            y=1.15,
            yanchor="top",
            buttons=buttons
        )]
    )
    return fig


def plot_usage_vs_discount(df: pd.DataFrame):
    if "value" not in df.columns:
        print("⚠️ העמודה 'value' לא נמצאה בנתונים. דילוג על גרף זה.")
        return None
    df = df.copy()
    df["usage_percentage"] = df.apply(lambda row: (row["used_value"] / row["value"] * 100) if row["value"] != 0 else 0, axis=1)
    fig = px.scatter(
        df,
        x="discount_percentage",
        y="usage_percentage",
        color="company",
        title="שיעור שימוש בקופונים לעומת אחוז הנחה",
        labels={"discount_percentage": "אחוז הנחה", "usage_percentage": "אחוז שימוש"},
        template="plotly_white",
        hover_data=["code"]
    )
    fig.update_layout(
        title={'x': 0.5}
    )
    return fig


def plot_discount_distribution_hist(df: pd.DataFrame):
    if "discount_percentage" not in df.columns:
        print("⚠️ העמודה 'discount_percentage' לא נמצאה בנתונים. דילוג על גרף זה.")
        return None
    fig = px.histogram(
        df,
        x="discount_percentage",
        nbins=20,
        title="התפלגות אחוזי הנחה בקופונים",
        labels={"discount_percentage": "אחוז הנחה", "count": "מספר קופונים"},
        template="plotly_white",
        color_discrete_sequence=["indianred"]
    )
    fig.update_layout(
        title={'x': 0.5},
        xaxis_tickangle=-45
    )
    return fig


def plot_drill_down_analysis(df: pd.DataFrame):
    companies = sorted(df["company"].unique())
    traces = []
    for company in companies:
        df_company = df[df["company"] == company].copy()
        trace = go.Scatter(
            x=df_company["cost"],
            y=df_company["discount_percentage"],
            mode="markers",
            marker=dict(size=10),
            name=company,
            text=df_company["id"],
            hovertemplate=("קופון: %{text}<br>" +
                           "תשלום: %{x}<br>" +
                           "אחוז הנחה: %{y:.2f}%<extra></extra>")
        )
        traces.append(trace)
    fig = go.Figure(data=traces)
    for i, trace in enumerate(fig.data):
        trace.visible = (i == 0)
    buttons = []
    for i, company in enumerate(companies):
        visibility = [False] * len(companies)
        visibility[i] = True
        button = dict(
            label=company,
            method="update",
            args=[{"visible": visibility},
                  {"title": f"Drill Down Analysis: {company}",
                   "annotations": []}]
        )
        buttons.append(button)
    fig.update_layout(
        title=f"Drill Down Analysis: {companies[0]}",
        xaxis_title="תשלום (מחיר הקופון)",
        yaxis_title="אחוז הנחה",
        updatemenus=[{
            "buttons": buttons,
            "direction": "down",
            "showactive": True,
            "x": 1,
            "xanchor": "right",
            "y": 1,
            "yanchor": "top"
        }]
    )
    return fig


# ------------------ פונקציות לניתוח לפי משתמשים ------------------

def plot_user_coupon_count(df: pd.DataFrame):
    if "user_id" not in df.columns:
        print("⚠️ העמודה 'user_id' לא נמצאה בנתונים. דילוג על גרף זה.")
        return None
    user_counts = df.groupby("user_id")["id"].count().reset_index(name="coupon_count")
    user_counts = user_counts.sort_values("coupon_count", ascending=False)
    fig = px.bar(
        user_counts,
        x="user_id",
        y="coupon_count",
        title="כמות הקופונים של המשתמשים (מהכי הרבה להכי נמוכה)",
        labels={"user_id": "משתמש", "coupon_count": "כמות קופונים"},
        template="plotly_white",
        color="coupon_count",
        color_continuous_scale="Blues"
    )
    fig.update_layout(title={'x': 0.5})
    return fig


def plot_user_max_discount(df: pd.DataFrame):
    if "user_id" not in df.columns:
        print("⚠️ העמודה 'user_id' לא נמצאה בנתונים. דילוג על גרף זה.")
        return None
    user_max = df.groupby("user_id")["discount_percentage"].max().reset_index()
    user_max = user_max.sort_values("discount_percentage", ascending=False)
    fig = px.bar(
        user_max,
        x="user_id",
        y="discount_percentage",
        title="אחוז ההנחה הגבוה ביותר לפי משתמש (מהגדולים להכי קטנים)",
        labels={"user_id": "משתמש", "discount_percentage": "אחוז הנחה"},
        template="plotly_white",
        color="discount_percentage",
        color_continuous_scale="Oranges"
    )
    fig.update_layout(title={'x': 0.5})
    return fig


def plot_user_sold_coupons(df: pd.DataFrame):
    if "status" not in df.columns or "user_id" not in df.columns:
        print("⚠️ העמודות 'status' או 'user_id' לא נמצאו בנתונים. דילוג על גרף זה.")
        return None
    sold = df[df["status"] == "נוצל"]
    user_sold = sold.groupby("user_id")["id"].count().reset_index(name="sold_count")
    user_sold = user_sold.sort_values("sold_count", ascending=False)
    fig = px.bar(
        user_sold,
        x="user_id",
        y="sold_count",
        title="כמות הקופונים שמכרו המשתמשים (מהכי הרבה להכי מעט)",
        labels={"user_id": "משתמש", "sold_count": "קופונים שנמכרו"},
        template="plotly_white",
        color="sold_count",
        color_continuous_scale="Greens"
    )
    fig.update_layout(title={'x': 0.5})
    return fig


# ------------------ פונקציות לבניית הדשבורד ------------------

def generate_dashboard_content(fig_divs):
    """
    בונה את תוכן הדשבורד: מכולל את הגרפים במבנה grid
    """
    content = '<div class="grid-container">\n'
    for div in fig_divs:
        content += f'<div class="chart-container">{div}</div>\n'
    content += '</div>\n'
    return content


def generate_full_dashboard(dashboards: dict, unique_users: list, output_filename="dashboard.html"):
    """
    בונה את קובץ ה-HTML הסופי, כאשר בכל דשבורד מופיע תחת div נפרד,
    ותפריט נפתח (select) מאפשר לבחור את המשתמש הרצוי.
    """
    plotly_js = '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>'
    # בניית רשימת האפשרויות לתפריט הבחירה – "כל המשתמשים" ואחריו המשתמשים הייחודיים
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

    dashboards_html = '<div class="dashboard-container">\n'
    dashboards_html += '<div id="dashboardContainer">\n'
    for key, content in dashboards.items():
        dashboards_html += f'<div id="dashboard_{key}" class="dashboard" style="display:none;">\n'
        dashboards_html += content
        dashboards_html += '</div>\n'
    dashboards_html += '</div>\n</div>\n'

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <!-- Viewport למכשירים ניידים -->
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Dashboard - גרפים</title>
    {plotly_js}
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
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
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 10px;
        }}
        .grid-container {{
            display: grid;
            gap: 20px;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        }}
        .chart-container {{
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            width: 100%;
        }}
    </style>
</head>
<body>
    {header_html}
    {dashboards_html}
    <script>
        function changeDashboard() {{
            var sel = document.getElementById("userSelect");
            var value = sel.value;
            var dashboards = document.getElementsByClassName("dashboard");
            for (var i = 0; i < dashboards.length; i++) {{
                dashboards[i].style.display = "none";
            }}
            document.getElementById("dashboard_" + value).style.display = "block";
        }}
        window.onload = function() {{
            document.getElementById("userSelect").value = "all";
            changeDashboard();
        }};
    </script>
</body>
</html>
"""
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Dashboard נשמר ב־{output_filename}")


# ------------------ פונקציה ראשית ------------------

def main():
    df_all = fetch_data()
    if df_all.empty:
        print("❌ לא נמצאו נתונים להמשך עיבוד.")
        return
    df_all = calculate_discount(df_all)
    # קבלת רשימת משתמשים (user_id) מהקופונים (בהנחה שהעמודה קיימת)
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
        print(f"✅ נתונים עבור {key}:")
        print(df.head())

        fig_divs = []
        # הגרפים מוצגים עם config המאפשר התאמה רוחבית
        fig1 = plot_coupon_usage(df)
        fig_divs.append(plotly_plot(fig1, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig2 = plot_discount_distribution(df)
        fig_divs.append(plotly_plot(fig2, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig3 = plot_active_users(df)
        if fig3 is not None:
            fig_divs.append(plotly_plot(fig3, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig4 = plot_cost_details(df)
        fig_divs.append(plotly_plot(fig4, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig5 = plot_coupons_by_month(df)
        if fig5 is not None:
            fig_divs.append(plotly_plot(fig5, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig6 = plot_discount_by_month(df)
        if fig6 is not None:
            fig_divs.append(plotly_plot(fig6, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig7 = plot_avg_value_cost_by_company(df)
        if fig7 is not None:
            fig_divs.append(plotly_plot(fig7, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig8 = plot_usage_vs_discount(df)
        if fig8 is not None:
            fig_divs.append(plotly_plot(fig8, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig9 = plot_discount_distribution_hist(df)
        if fig9 is not None:
            fig_divs.append(plotly_plot(fig9, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig10 = plot_drill_down_analysis(df)
        fig_divs.append(plotly_plot(fig10, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        # גרפים לניתוח לפי משתמשים – מוצגים תמיד על הנתונים הכוללים (df_all)
        fig11 = plot_user_coupon_count(df_all)
        if fig11 is not None:
            fig_divs.append(plotly_plot(fig11, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig12 = plot_user_max_discount(df_all)
        if fig12 is not None:
            fig_divs.append(plotly_plot(fig12, include_plotlyjs=False, output_type='div', config={"responsive": True}))
        fig13 = plot_user_sold_coupons(df_all)
        if fig13 is not None:
            fig_divs.append(plotly_plot(fig13, include_plotlyjs=False, output_type='div', config={"responsive": True}))

        dashboard_content = generate_dashboard_content(fig_divs)
        dashboards[key] = dashboard_content

    generate_full_dashboard(dashboards, unique_users, output_filename="dashboard.html")


if __name__ == "__main__":
    main()
