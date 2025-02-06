import os
import pandas as pd
import requests
import plotly.graph_objects as go
from dash import Dash, dcc, html
from dash.dependencies import Input, Output

# פונקציה לשליפת נתונים מ-Supabase
def fetch_data() -> pd.DataFrame:
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", "")
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ חסרים משתני סביבה: SUPABASE_URL ו/או SUPABASE_ANON_KEY")
        return pd.DataFrame()
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    url = f"{SUPABASE_URL}/rest/v1/coupon"
    response = requests.get(url, headers=headers, params={"select": "*"})
    if response.status_code != 200:
        print("שגיאה בשליפת הנתונים:", response.text)
        return pd.DataFrame()
    data = response.json()
    df = pd.DataFrame(data)
    if "exclude_saving" in df.columns:
        df = df[df["exclude_saving"] != True]
    if "value" not in df.columns:
        df["value"] = 0
    if "cost" not in df.columns:
        df["cost"] = 0
    return df

# אתחול אפליקציית Dash
app = Dash(__name__)
app.title = "דשבורד - ערך, עלות ואחוזי הנחה ממוצעים"

df = fetch_data()
all_companies = sorted(df["company"].unique()) if "company" in df.columns else []

def compute_average_discount(selected_companies):
    if not selected_companies:
        return "אין נתונים"
    filtered = df[df["company"].isin(selected_companies)]
    if filtered.empty or (filtered["value"]==0).all():
        return "אין נתונים"
    discount_series = filtered.apply(lambda r: ((r["value"] - r["cost"]) / r["value"] * 100)
                                       if r["value"] != 0 else 0, axis=1)
    avg_discount = discount_series.mean()
    return f"{avg_discount:.2f}%"

def build_figure(selected_companies):
    if not selected_companies:
        return go.Figure()
    filtered_df = df[df["company"].isin(selected_companies)]
    if filtered_df.empty:
        return go.Figure()
    agg = filtered_df.groupby("company").agg({"value": "mean", "cost": "mean"}).reset_index()
    agg["discount"] = ((agg["value"] - agg["cost"]) / agg["value"] * 100).round(2)  # חישוב אחוז הנחה ממוצע
    agg = agg.sort_values("value", ascending=False)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=agg['value'],
        y=agg['company'],
        orientation='h',
        name='ערך ממוצע',
        marker=dict(color='rgba(55,83,109,0.8)'),
        text=[f"{d}%" for d in agg["discount"]],  # הצגת אחוז הנחה ממוצע על העמודות
        textposition='outside'
    ))
    fig.add_trace(go.Bar(
        x=agg['cost'],
        y=agg['company'],
        orientation='h',
        name='עלות ממוצעת',
        marker=dict(color='rgba(26,118,255,0.8)')
    ))
    fig.update_layout(
        xaxis=dict(title='בש"ח'),
        yaxis=dict(title='חברה', autorange='reversed'),
        barmode='group',
        paper_bgcolor='#f9f9f9',
        plot_bgcolor='#ffffff',
        font=dict(family="Arial, sans-serif", size=14, color="#333"),
        hovermode="closest"
    )
    return fig

app.layout = html.Div(style={'direction': 'rtl', 'textAlign': 'center', 'padding': '20px', 'backgroundColor': '#f9f9f9'}, children=[
    html.H1("דשבורד - ערך, עלות ואחוזי הנחה ממוצעים לפי חברה",
            style={'textAlign': 'center', 'marginBottom': '20px'}),
    html.Div(style={'textAlign': 'center', 'marginBottom': '10px','display': 'flex',  'alignItems': 'center', 'gap': '10px'},
             children=[
                 html.Div(style={'width': '20%', 'backgroundColor': '#ffffff', 'padding': '10px',
                                 'borderRadius': '8px', 'boxShadow': '0 3px 6px rgba(0,0,0,0.1)',
                                 'maxHeight': '400px', 'overflowY': 'auto'}, children=[
                     dcc.Dropdown(
                         id='company-dropdown',
                         options=[{'label': comp, 'value': comp} for comp in all_companies],
                         multi=True,
                         value=all_companies,
                         placeholder="בחר חברות",
                         style={'width': '100%', 'fontSize': '14px'}
                     ),
                     html.Br(),
                     html.Div(id='discount-indicator',
                              style={'fontSize': '16px', 'fontWeight': 'bold', 'color': '#2a3f5f'})
                 ]),
                 html.Div(style={'width': '70%'}, children=[
                     dcc.Graph(
                         id='value-cost-graph',
                         style={'height': '500px'},
                         config={'displayModeBar': 'hover'}
                     )
                 ])
             ])
])

@app.callback(
    [Output('value-cost-graph', 'figure'),
     Output('discount-indicator', 'children')],
    [Input('company-dropdown', 'value')]
)
def update_graph(selected_companies):
    fig = build_figure(selected_companies)
    avg_discount = compute_average_discount(selected_companies)
    return fig, f"אחוז הנחה ממוצע: {avg_discount}"

if __name__ == '__main__':
    app.run_server(debug=True)
