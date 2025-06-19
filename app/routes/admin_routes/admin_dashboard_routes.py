from flask import Blueprint, abort, current_app, render_template_string, request
from flask_login import login_required, current_user
import os
import pandas as pd
import requests
from dotenv import load_dotenv
import plotly.express as px
import plotly.graph_objects as go
from plotly.offline import plot as plotly_plot
from app.extensions import db
from sqlalchemy.sql import text
import datetime

# טוען משתני סביבה
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "❌ Error: SUPABASE_URL and SUPABASE_ANON_KEY must be set in the .env file"
    )

admin_dashboard_bp = Blueprint("admin_dashboard_bp", __name__)


def is_admin(user):
    """בודק אם המשתמש הוא אדמין – עדכן בהתאם למערכת שלך."""
    return getattr(user, "is_admin", False)


#########################################
# פונקציות לקבלת ועיבוד נתונים
#########################################


def fetch_data() -> pd.DataFrame:
    """
    מקבל נתונים מטבלת הקופונים ב-Supabase ומבצע עיבוד ראשוני.
    במקרה של שגיאה מוחזר DataFrame ריק.
    """
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
        # מסנן קופונים עם exclude_saving=True
        if "exclude_saving" in df.columns:
            df = df[df["exclude_saving"] != True]
        if "date_added" in df.columns:
            df["date_added"] = pd.to_datetime(df["date_added"], errors="coerce")
        if "expiration" in df.columns:
            df["expiration"] = pd.to_datetime(df["expiration"], errors="coerce")
        return df
    else:
        current_app.logger.error(f"⚠️ Error fetching data: {response.text}")
        return pd.DataFrame()


def calculate_discount(df: pd.DataFrame) -> pd.DataFrame:
    """
    מחשב את עמודת discount_percentage אם אינה קיימת או ריקה.
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
    df["discount_percentage"] = df["discount_percentage"].round(2)
    return df


def set_layout(fig):
    """מגדיר עיצוב בסיסי לגרפים."""
    fig.update_layout(
        autosize=True,
        margin=dict(l=20, r=20, t=50, b=80),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )


#########################################
# פונקציות לקבלת נתוני משתמשים
#########################################


def fetch_users() -> pd.DataFrame:
    """
    שליפת נתוני משתמשים מ-Supabase.
    מוגבל ל־10 רשומות. במקרה שאין נתונים מה-API, מוחזר DataFrame סטטי לדוגמה.
    """
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{SUPABASE_URL}/rest/v1/users?limit=10"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        df = pd.DataFrame(data)
        if not df.empty:
            return df
    # במקרה ואין נתונים – ללא דאטה סטטי עם מידע אישי:
    sample_data = [
        {
            "id": 1,
            "email": "demo@example.com",
            "first_name": "דמו",
            "last_name": "משתמש",
        }
    ]
    return pd.DataFrame(sample_data)


#########################################
# פונקציות ליצירת גרפים
#########################################


def plot_status_distribution(df: pd.DataFrame):
    today = pd.Timestamp.now()

    def get_status_category(row):
        if pd.notnull(row.get("expiration")) and row["expiration"] < today:
            return "Expired"
        elif row.get("status") == "פעיל":
            return "Active"
        else:
            return "Remaining"

    df = df.copy()
    df["status_category"] = df.apply(get_status_category, axis=1)
    status_counts = df["status_category"].value_counts().reset_index()
    status_counts.columns = ["status_category", "count"]
    total = status_counts["count"].sum()
    status_counts["percentage"] = (status_counts["count"] / total * 100).round(2)
    fig = px.pie(
        status_counts,
        names="status_category",
        values="percentage",
        title="Status Distribution",
        hole=0.4,
    )
    set_layout(fig)
    return fig


def plot_coupons_by_company(df: pd.DataFrame):
    if "company" not in df.columns:
        return None
    company_counts = df["company"].value_counts().reset_index()
    company_counts.columns = ["company", "count"]
    fig = px.bar(
        company_counts,
        x="company",
        y="count",
        title="Coupons Count by Company",
        labels={"company": "Company", "count": "Number of Coupons"},
        template="plotly_white",
    )
    fig.update_layout(xaxis_tickangle=45)
    set_layout(fig)
    return fig


def plot_discount_percentage_by_company(df: pd.DataFrame, top_n=5):
    if "company" not in df.columns:
        return None
    discount_avg = df.groupby("company")["discount_percentage"].mean().reset_index()
    discount_avg.columns = ["company", "avg_discount"]
    discount_avg = discount_avg.sort_values("avg_discount", ascending=False).head(top_n)
    fig = px.bar(
        discount_avg,
        x="company",
        y="avg_discount",
        title=f"Average Discount Percentage by Company (Top {top_n})",
        labels={"company": "Company", "avg_discount": "Avg Discount (%)"},
        template="plotly_white",
        color="avg_discount",
        color_continuous_scale="Oranges",
    )
    fig.update_layout(xaxis_tickangle=45)
    set_layout(fig)
    return fig


def plot_value_vs_cost(df: pd.DataFrame, company_filter: list = None):
    df_plot = df.copy()
    if company_filter and "company" in df_plot.columns:
        df_plot = df_plot[df_plot["company"].isin(company_filter)]
    if df_plot.empty:
        return None
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_plot["value"],
            y=df_plot["cost"],
            mode="markers",
            marker=dict(size=10, opacity=0.7),
            text=df_plot["company"],
            hovertemplate="Company: %{text}<br>Value: %{x}<br>Cost: %{y}",
            name="Coupons",
        )
    )
    max_val = max(df_plot["value"].max(), df_plot["cost"].max())
    fig.add_trace(
        go.Scatter(
            x=[0, max_val],
            y=[0, max_val],
            mode="lines",
            line=dict(dash="dash"),
            name="y=x",
        )
    )
    fig.update_layout(
        title="Comparison of Coupon Value vs. Cost",
        xaxis_title="Value",
        yaxis_title="Cost",
    )
    set_layout(fig)
    return fig


def plot_monthly_purchase_volume(df: pd.DataFrame):
    if "date_added" not in df.columns:
        return None
    df = df.copy()
    df["month"] = df["date_added"].dt.to_period("M").astype(str)
    monthly_counts = df.groupby("month").size().reset_index(name="count")
    fig = px.line(
        monthly_counts,
        x="month",
        y="count",
        title="Coupons Added Over Time",
        labels={"month": "Month", "count": "Number of Coupons"},
        template="plotly_white",
    )
    fig.update_layout(xaxis_tickangle=45)
    set_layout(fig)
    return fig


def plot_usage_type_segmentation(df: pd.DataFrame):
    if "is_one_time" not in df.columns:
        return None
    usage_counts = df["is_one_time"].value_counts().reset_index()
    usage_counts.columns = ["is_one_time", "count"]
    usage_counts["Usage Type"] = usage_counts["is_one_time"].apply(
        lambda x: "One-time" if x else "Multi-use"
    )
    fig = px.bar(
        usage_counts,
        x="Usage Type",
        y="count",
        title="Usage Type Segmentation",
        labels={"count": "Number of Coupons"},
        template="plotly_white",
    )
    set_layout(fig)
    return fig


def plot_top_discounts(df: pd.DataFrame):
    if "discount_percentage" not in df.columns or "company" not in df.columns:
        return None
    top_discount = df.groupby("company")["discount_percentage"].max().reset_index()
    top_discount = top_discount.sort_values(
        "discount_percentage", ascending=False
    ).head(10)
    fig = px.bar(
        top_discount,
        x="company",
        y="discount_percentage",
        title="Top 10 Companies by Highest Coupon Discount",
        labels={"company": "Company", "discount_percentage": "Max Discount (%)"},
        template="plotly_white",
        color="discount_percentage",
        color_continuous_scale="Viridis",
    )
    fig.update_layout(xaxis_tickangle=45)
    set_layout(fig)
    return fig


def plot_usage_analysis(df: pd.DataFrame):
    if "value" not in df.columns or "used_value" not in df.columns:
        return None
    total_value = df["value"].sum()
    total_used = df["used_value"].sum() if "used_value" in df.columns else 0
    remaining = total_value - total_used
    fig = px.pie(
        names=["Used Value", "Remaining Value"],
        values=[total_used, remaining],
        title="Usage Analysis: Used vs Remaining Value",
        hole=0.4,
    )
    set_layout(fig)
    return fig


def plot_availability_and_sale(df: pd.DataFrame):
    """
    בונה תרשים עמודות מקובצות המפריד בין 'For Sale' ו-'Not For Sale'.
    במידה ויש רק ערך אחד (למשל רק True או רק False) – יעביר רק את העמודה הקיימת.
    """
    if "is_available" not in df.columns or "is_for_sale" not in df.columns:
        return None
    availability = pd.crosstab(df["is_available"], df["is_for_sale"]).reset_index()
    # בדיקה אם קיימים ערכים של True/False בעמודת is_for_sale
    if True in availability.columns:
        availability = availability.rename(columns={True: "For Sale"})
    if False in availability.columns:
        availability = availability.rename(columns={False: "Not For Sale"})
    # בונים רשימת עמודות y הקיימות
    y_cols = [
        col for col in ["For Sale", "Not For Sale"] if col in availability.columns
    ]
    if not y_cols:
        return None
    fig = px.bar(
        availability,
        x="is_available",
        y=y_cols,
        title="Segmentation by Availability and Sale",
        labels={"is_available": "Available (True/False)"},
        barmode="group",
        template="plotly_white",
    )
    set_layout(fig)
    return fig


def plot_discount_histogram(df: pd.DataFrame):
    if "discount_percentage" not in df.columns:
        return None
    fig = px.histogram(
        df,
        x="discount_percentage",
        nbins=20,
        title="Distribution of Discount Percentages",
        labels={"discount_percentage": "Discount (%)", "count": "Number of Coupons"},
        template="plotly_white",
        color_discrete_sequence=["indianred"],
    )
    fig.update_layout(xaxis_tickangle=45)
    set_layout(fig)
    return fig


def plot_expiration_segmentation(df: pd.DataFrame):
    if "expiration" not in df.columns:
        return None
    today = pd.Timestamp.now()
    df = df.copy()
    df["expiration_status"] = df["expiration"].apply(
        lambda x: "Expired"
        if pd.notnull(x) and x < today
        else (
            "About to Expire"
            if pd.notnull(x) and x <= today + pd.Timedelta(days=7)
            else "Valid"
        )
    )
    status_counts = df["expiration_status"].value_counts().reset_index()
    status_counts.columns = ["expiration_status", "count"]
    fig = px.bar(
        status_counts,
        x="expiration_status",
        y="count",
        title="Coupons Expiration Segmentation",
        labels={"expiration_status": "Expiration Status", "count": "Number of Coupons"},
        template="plotly_white",
    )
    set_layout(fig)
    return fig


def plot_monthly_highest_discount(df: pd.DataFrame):
    if "date_added" not in df.columns or "discount_percentage" not in df.columns:
        return None
    df = df.copy()
    df["month"] = df["date_added"].dt.to_period("M").astype(str)
    monthly_max = df.groupby("month")["discount_percentage"].max().reset_index()
    fig = px.line(
        monthly_max,
        x="month",
        y="discount_percentage",
        title="Monthly Highest Discount Achievement",
        labels={"month": "Month", "discount_percentage": "Highest Discount (%)"},
        template="plotly_white",
    )
    fig.update_layout(xaxis_tickangle=45)
    set_layout(fig)
    return fig


#########################################
# פונקציות ליצירת KPI – נתוני בינה עסקית
#########################################


def generate_profitability_kpis(df: pd.DataFrame):
    total_value = df["value"].sum() if "value" in df.columns else 0
    total_cost = df["cost"].sum() if "cost" in df.columns else 0
    total_used = df["used_value"].sum() if "used_value" in df.columns else 0
    html = f"""
    <div class="row text-center my-3">
        <div class="col-md-4 mb-3">
            <div class="card p-3 bg-white shadow-sm border-0">
                <h4 class="text-success">Total Coupon Value</h4>
                <p class="fs-4 fw-bold">{total_value:,.2f}</p>
            </div>
        </div>
        <div class="col-md-4 mb-3">
            <div class="card p-3 bg-white shadow-sm border-0">
                <h4 class="text-success">Total Coupon Cost</h4>
                <p class="fs-4 fw-bold">{total_cost:,.2f}</p>
            </div>
        </div>
        <div class="col-md-4 mb-3">
            <div class="card p-3 bg-white shadow-sm border-0">
                <h4 class="text-success">Total Used Value</h4>
                <p class="fs-4 fw-bold">{total_used:,.2f}</p>
            </div>
        </div>
    </div>
    """
    return html


def generate_overall_kpis(df: pd.DataFrame):
    utilized = df[df.get("status") == "נוצל"].shape[0] if "status" in df.columns else 0
    avg_discount = (
        df["discount_percentage"].mean() if "discount_percentage" in df.columns else 0
    )
    ratio = (
        (df["value"] / df["cost"]).mean()
        if "value" in df.columns and "cost" in df.columns and (df["cost"] != 0).all()
        else 0
    )
    if "company" in df.columns:
        seg = df["company"].value_counts().head(5)
        seg_html = (
            "<ul class='list-unstyled mb-0'>"
            + "".join(
                [
                    f"<li><strong>{comp}</strong>: {cnt}</li>"
                    for comp, cnt in seg.items()
                ]
            )
            + "</ul>"
        )
    else:
        seg_html = "N/A"
    html = f"""
    <div class="row text-center my-3">
        <div class="col-md-3 mb-3">
            <div class="card p-3 bg-white shadow-sm border-0">
                <h4 class="text-primary">Total Utilized Coupons</h4>
                <p class="fs-4 fw-bold">{utilized}</p>
            </div>
        </div>
        <div class="col-md-3 mb-3">
            <div class="card p-3 bg-white shadow-sm border-0">
                <h4 class="text-primary">Average Discount (%)</h4>
                <p class="fs-4 fw-bold">{avg_discount:.2f}</p>
            </div>
        </div>
        <div class="col-md-3 mb-3">
            <div class="card p-3 bg-white shadow-sm border-0">
                <h4 class="text-primary">Avg Value-to-Cost Ratio</h4>
                <p class="fs-4 fw-bold">{ratio:.2f}</p>
            </div>
        </div>
        <div class="col-md-3 mb-3">
            <div class="card p-3 bg-white shadow-sm border-0">
                <h4 class="text-primary">Coupons by Company</h4>
                {seg_html}
            </div>
        </div>
    </div>
    """
    return html


#########################################
# בניית לוח הנתונים – בחירת משתמש/ים והצגת נתוניהם בלבד
#########################################


def build_detailed_dashboard() -> str:
    # שליפת רשימת המשתמשים (מוגבלת ל־10) לטופס הבחירה
    users_df = fetch_users()
    if users_df.empty:
        user_select_form = "<p>No users available.</p>"
    else:
        options_html = "<option value=''>-- בחר משתמש --</option>"
        for _, row in users_df.iterrows():
            selected = (
                "selected" if str(row["id"]) in request.args.getlist("user_id") else ""
            )
            options_html += f"<option value='{row['id']}' {selected}>{row['first_name']} {row['last_name']} ({row['email']})</option>"
        user_select_form = f"""
         <div class="mb-3">
             <form method="get" action="">
                <label for="user_id" class="form-label">בחר משתמש/ים:</label>
                <select id="user_id" name="user_id" class="form-select" multiple style="width: auto; display: inline-block; margin-right: 10px;">
                    {options_html}
                </select>
                <button type="submit" class="btn btn-primary">Apply</button>
             </form>
         </div>
         """

    # אם לא נבחרו משתמשים – מציגים את הטופס בלבד (ללא נתונים)
    selected_ids = request.args.getlist("user_id")
    if not selected_ids:
        full_html = f"""<!DOCTYPE html>
<html lang="he">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <title>Advanced Dashboard</title>
  <style>
    body {{
      background-color: #f5f5f5;
      direction: rtl;
    }}
  </style>
</head>
<body>
  <div class="container my-4">
    <h2 class="text-center mb-4">Business Intelligence Dashboard</h2>
    {user_select_form}
    <div class="alert alert-info text-center">אנא בחר משתמש/ים כדי לראות את הנתונים.</div>
  </div>
</body>
</html>
"""
        return full_html

    # שליפת נתוני הקופונים
    df_all = fetch_data()
    # במידה ואין נתונים כלל, נותר רק הטופס לבחירת משתמשים
    if df_all.empty:
        full_html = f"""<!DOCTYPE html>
<html lang="he">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <title>Advanced Dashboard</title>
  <style>
    body {{
      background-color: #f5f5f5;
      direction: rtl;
    }}
  </style>
</head>
<body>
  <div class="container my-4">
    <h2 class="text-center mb-4">Business Intelligence Dashboard</h2>
    {user_select_form}
    <div class="alert alert-info text-center">אין נתוני קופונים.</div>
  </div>
</body>
</html>
"""
        return full_html

    # סינון נתוני הקופונים לפי המשתמש/ים הנבחרים
    if "all" in selected_ids:
        filtered_df = df_all
    else:
        try:
            selected_ids_int = [int(x) for x in selected_ids if x.isdigit()]
        except ValueError:
            return "<div class='container my-5 text-center text-danger'>❌ Invalid user selection.</div>"
        filtered_df = df_all[df_all["user_id"].isin(selected_ids_int)]

    # במידה והסינון מחזיר DataFrame ריק – מציגים רק את הטופס לבחירת משתמשים
    if filtered_df.empty:
        full_html = f"""<!DOCTYPE html>
<html lang="he">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <title>Advanced Dashboard</title>
  <style>
    body {{
      background-color: #f5f5f5;
      direction: rtl;
    }}
  </style>
</head>
<body>
  <div class="container my-4">
    <h2 class="text-center mb-4">Business Intelligence Dashboard</h2>
    {user_select_form}
    <div class="alert alert-info text-center">אין נתוני קופונים עבור המשתמש/ים הנבחרים.</div>
  </div>
</body>
</html>
"""
        return full_html

    filtered_df = calculate_discount(filtered_df)

    # יצירת KPI וגרפים
    overall_kpis = generate_overall_kpis(filtered_df)
    profitability_kpis = generate_profitability_kpis(filtered_df)

    graph_functions = [
        (plot_status_distribution, "Status Distribution"),
        (plot_coupons_by_company, "Coupons by Company"),
        (plot_discount_percentage_by_company, "Average Discount by Company"),
        (plot_value_vs_cost, "Value vs Cost Comparison"),
        (plot_monthly_purchase_volume, "Coupons Added Over Time"),
        (plot_usage_type_segmentation, "Usage Type Segmentation"),
        (plot_top_discounts, "Top 10 Discounts"),
        (plot_usage_analysis, "Usage Analysis"),
        (plot_availability_and_sale, "Availability & Sale Segmentation"),
        (plot_discount_histogram, "Discount Distribution Histogram"),
        (plot_expiration_segmentation, "Expiration Segmentation"),
        (plot_monthly_highest_discount, "Monthly Highest Discount"),
    ]

    graph_divs = ""
    for func, title in graph_functions:
        fig = func(filtered_df)
        if fig is not None:
            graph_div = plotly_plot(
                fig,
                include_plotlyjs=False,
                output_type="div",
                config={"responsive": True},
            )
            graph_divs += f"""
            <div class="col-md-6 mb-4">
                <div class="card p-3 bg-white shadow-sm border-0">
                    <h5 class="text-center">{title}</h5>
                    {graph_div}
                </div>
            </div>
            """

    graphs_html = f"<div class='row'>{graph_divs}</div>"

    full_html = f"""<!DOCTYPE html>
<html lang="he">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="csrf-token" content="{{{{ csrf_token() }}}}">
    <title>Advanced Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{
            background-color: #f5f5f5;
            direction: rtl;
        }}
        .card {{
            border: none;
        }}
    </style>
</head>
<body>
    <div class="container my-4">
        <h2 class="text-center mb-4">Business Intelligence Dashboard</h2>
        {user_select_form}
        {overall_kpis}
        {profitability_kpis}
        <hr>
        {graphs_html}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
    return full_html


#########################################
# הגדרת הנתיב הראשי להצגת לוח הנתונים
#########################################


@admin_dashboard_bp.route("/dashboard_coupons")
@login_required
def dashboard():
    if not is_admin(current_user):
        abort(403)
    html = build_detailed_dashboard()
    return render_template_string(html)
