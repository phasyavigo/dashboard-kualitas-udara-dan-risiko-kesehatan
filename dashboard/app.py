import os
import json
import random
import requests
import pandas as pd
import dash
from dash import dcc, html, dash_table, Output, Input, State, ctx
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dotenv import load_dotenv
import numpy as np

# Load environment variables
load_dotenv()

# --- Configuration & Constants ---
AQICN_TOKEN = os.environ.get("AQICN_TOKEN", "")
MAPBOX_ACCESS_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")

# API URLs (Preserved for future integration)
# Currently using Mock Data to ensure visual fidelity until backend supports full AQI data
API_INTERNAL_URL = os.environ.get("API_INTERNAL_URL", "http://backend:8000")
API_PUBLIC_URL = os.environ.get("API_PUBLIC_URL", "http://localhost:8000")

# Default center (Indonesia)
DEFAULT_CENTER_LAT = -2.5489
DEFAULT_CENTER_LON = 118.0149
DEFAULT_ZOOM = 4

# Updated Color Palette - Design System
COLORS = {
    "Good": "#50B19E",                         # teal
    "Moderate": "#E49A4E",                     # orange
    "Unhealthy for Sensitive Groups": "#E49A4E", # orange
    "Unhealthy": "#DF6E53",                    # coral red
    "Very Unhealthy": "#DF6E53",               # coral red
    "Hazardous": "#C0392B",                    # dark red
    "Unknown": "#7F8C8D"                       # grey
}

# WHO Thresholds (24h mean guidelines approx)
THRESHOLDS = {
    "pm25": 15,
    "pm10": 45,
    "no2": 25,
    "so2": 40,
    "co": 4,
    "o3": 100 # 8h mean
}

# --- App Initialization ---
app = dash.Dash(__name__, title="Air Quality Dashboard")
server = app.server

# --- MOCK Data Generators ---
# NOTE: These are used to populate the dashboard with realistic looking data
# because the current backend endpoints do not yet return live AQI/PM2.5 values
# for all stations in the GeoJSON response.

def get_aqi_category(pm25_value):
    if pm25_value <= 12.0:
        return "Good"
    elif pm25_value <= 35.4:
        return "Moderate"
    elif pm25_value <= 55.4:
        return "Unhealthy for Sensitive Groups"
    elif pm25_value <= 150.4:
        return "Unhealthy"
    elif pm25_value <= 250.4:
        return "Very Unhealthy"
    else:
        return "Hazardous"

def generate_mock_stations(n=30):
    stations = []
    cities = ["Jakarta", "Surabaya", "Bandung", "Medan", "Semarang", "Makassar", "Palembang", "Denpasar", "Yogyakarta", "Balikpapan"]
    now_iso = datetime.now().isoformat()
    for i in range(n):
        city = random.choice(cities)
        # Random lat/lon around Indonesia
        lat = random.uniform(-10, 5)
        lon = random.uniform(95, 140)
        pm25 = random.uniform(5, 180)
        category = get_aqi_category(pm25)
        stations.append({
            "type": "Feature",
            "id": f"station-{i}",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "station_id": f"station-{i}",
                "name": f"{city} Station {i+1}",
                "city": city,
                "aqi": int(pm25 * 2), # Rough AQI approx
                "pm25": round(pm25, 1),
                "category": category,
                "color": COLORS.get(category, COLORS["Unknown"]),
                "last_update": now_iso,
                "dominant": "pm25",
                "attribution": [{"name": "Mock EPA", "url": "http://example.com"}]
            }
        })
    return {"type": "FeatureCollection", "features": stations}

# Generate static mock data once for consistency
MOCK_GEOJSON = generate_mock_stations(50)

def get_timeseries(station_id, param="pm25", days=7):
    """Fetch Timeseries Data (Real with Mock Fallback)"""
    # Try fetching real data
    try:
        url = f"{API_INTERNAL_URL}/timeseries/{station_id}/{param}"
        # Request slightly more data to ensure coverage
        params = {"limit": days * 24} 
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            series = data.get("series", [])
            if series:
                df = pd.DataFrame(series)
                df['ts'] = pd.to_datetime(df['ts'])
                return df.sort_values('ts')
    except Exception as e:
        print(f"Error fetching timeseries for {station_id}: {e}")

    # Fallback to Mock Data
    now = datetime.now()
    data = []
    hours = days * 24
    base_val = random.uniform(20, 80)
    for i in range(hours):
        ts = now - timedelta(hours=i)
        # Add some random noise and daily cycle
        val = base_val + 10 * np.sin(i / 12 * np.pi) + random.uniform(-5, 5)
        val = max(0, val) # Ensure no negative
        data.append({"ts": ts.isoformat(), "value": round(val, 2)})
    df = pd.DataFrame(data)
    df['ts'] = pd.to_datetime(df['ts'])
    return df.sort_values('ts')

def get_forecast(station_id):
    """Fetch 5-day Forecast (Real with Mock Fallback)"""
    # Try fetching real data
    try:
        url = f"{API_INTERNAL_URL}/forecast/{station_id}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data:
                return data
    except Exception as e:
        print(f"Error fetching forecast for {station_id}: {e}")

    # Fallback to Mock Data
    today = datetime.now().date()
    forecast = []
    for i in range(5):
        day = today + timedelta(days=i)
        forecast.append({
            "day": day.strftime("%a"),
            "min": random.randint(10, 30),
            "max": random.randint(40, 100),
            "avg": random.randint(30, 70)
        })
    return forecast

# --- Layout Helper Components ---

def build_kpi_card(title, value, subtext=None, id_val=None, accent="#ECF0F1"):
    return html.Div([
        html.Div(title, style={
            'fontWeight': '600',
            'color': '#BDC3C7',
            'fontSize': '0.78rem',
            'marginBottom': '6px',
            'textTransform': 'uppercase',
            'letterSpacing': '0.6px'
        }),
        html.Div(value, id=id_val if id_val else None, style={
            'fontWeight': '800',
            'color': accent,
            'fontSize': '1.9rem',
            'margin': '0',
            'lineHeight': '1'
        }),
        html.Div(subtext or "", style={
            'color': '#95A5A6',
            'fontSize': '0.75rem',
            'marginTop': '8px'
        })
    ], className="kpi-card", style={
        'background': '#282F3C',
        'padding': '16px',
        'borderRadius': '10px',
        'flex': '1',
        'minWidth': '200px',
        'border': '1px solid rgba(255,255,255,0.05)',
        'boxShadow': '0 4px 8px rgba(0,0,0,0.3)'
    })

def build_map():
    return dcc.Graph(
        id="map",
        style={'height': '600px', 'width': '100%', 'borderRadius': '8px', 'overflow': 'hidden'},
        config={'displayModeBar': False}
    )

def build_side_panel():
    return html.Div([
        html.Div(id="side-panel-content", children=[
            html.Div([
                html.H3("Select a station", style={'color': '#7F8C8D', 'textAlign': 'center', 'marginTop': '40%'}),
                html.P("Click a marker for details", style={'color': '#616A6B', 'textAlign': 'center'})
            ])
        ])
    ], style={
        'backgroundColor': '#282F3C',
        'padding': '16px',
        'borderRadius': '8px',
        'height': '600px',
        'overflowY': 'auto',
        'boxShadow': '0 4px 8px rgba(0,0,0,0.3)'
    })

# --- Main Layout ---

app.layout = html.Div([
    # Header
    html.Div([
        html.Div([
            html.H1("Air Quality Dashboard", style={
                'margin': '0',
                'fontSize': '2rem',
                'fontWeight': '800',
                'color': '#ECF0F1',
                'letterSpacing': '-0.4px'
            }),
            html.P("Real-time Air Quality Monitoring & Health Risk Assessment", style={
                'margin': '6px 0 0 0',
                'color': '#95A5A6',
                'fontSize': '0.9rem'
            })
        ], style={'flex': '1'}),
        html.Div([
            html.Div(id="last-update-time", style={
                'color': '#F39C12',
                'fontWeight': '600',
                'fontSize': '0.9rem',
                'textAlign': 'right'
            }),
            html.Div("Data Source: Mock API", style={
                'fontSize': '0.75rem',
                'color': '#7F8C8D',
                'textAlign': 'right',
                'marginTop': '6px'
            })
        ], style={'width': '240px', 'display': 'flex', 'flexDirection': 'column', 'justifyContent': 'center', 'alignItems': 'flex-end'})
    ], style={
        'display': 'flex',
        'alignItems': 'center',
        'gap': '16px',
        'padding': '18px',
        'borderRadius': '10px',
        'background': '#282F3C',
        'border': '1px solid rgba(255,255,255,0.05)',
        'marginBottom': '18px'
    }),

    # KPI Cards
    html.Div([
        build_kpi_card("Total Stations", "0", "Online Monitoring", "kpi-total-stations"),
        build_kpi_card("High Risk Areas", "0", "AQI > 100", "kpi-high-risk", "#E74C3C"),
        build_kpi_card("Avg PM2.5", "0", "Nationwide µg/m³", "kpi-avg-pm25"),
        build_kpi_card("Worst Station", "-", "Highest recorded AQI", "kpi-worst-station", "#E74C3C"),
    ], style={'display': 'flex', 'gap': '16px', 'flexWrap': 'wrap', 'marginBottom': '18px'}),

    # Map + Side Panel
    html.Div([
        html.Div(build_map(), style={'flex': '3', 'minWidth': '560px'}),
        html.Div(build_side_panel(), style={'flex': '1.6', 'minWidth': '360px'})
    ], style={'display': 'flex', 'gap': '16px', 'flexWrap': 'wrap', 'marginBottom': '18px'}),

    # Tabs
    html.Div([
        dcc.Tabs(id="analysis-tabs", value='tab-overview', children=[
            dcc.Tab(label='📊 Nationwide Overview', value='tab-overview'),
            dcc.Tab(label='📋 Station List', value='tab-table'),
        ], style={'marginBottom': '0'}),
        html.Div(id="tabs-content", style={'padding': '16px'})
    ], style={
        'background': '#282F3C',
        'padding': '8px',
        'borderRadius': '10px',
        'boxShadow': '0 4px 8px rgba(0,0,0,0.3)'
    }),

    # Interval for updates
    dcc.Interval(id="interval-component", interval=300*1000, n_intervals=0), # 5 min

    # Store for selected station
    dcc.Store(id="selected-station-store")
], style={'backgroundColor': '#1E2631', 'minHeight': '100vh', 'fontFamily': 'Inter, sans-serif', 'color': '#ECF0F1', 'padding': '20px'})

# --- Callbacks ---

@app.callback(      
    [Output("map", "figure"),
     Output("kpi-total-stations", "children"),
     Output("kpi-high-risk", "children"),
     Output("kpi-avg-pm25", "children"),
     Output("kpi-worst-station", "children"),
     Output("last-update-time", "children")],
    [Input("interval-component", "n_intervals")]
)
def update_dashboard_data(n):
    # Fetch real data from API
    try:
        response = requests.get(f"{API_INTERNAL_URL}/stations.geojson", timeout=10)
        if response.status_code == 200:
            geojson = response.json()
            print(f"✅ Using REAL data from backend - {len(geojson.get('features', []))} stations")
        else:
            print(f"⚠️  Backend returned {response.status_code} - Using MOCK data")
            geojson = MOCK_GEOJSON
    except Exception as e:
        print(f"❌ Error fetching from backend: {e} - Using MOCK data")
        geojson = MOCK_GEOJSON

    features = geojson["features"]
    
    total = len(features)
    # Use .get() with default 0 to handle missing properties safely
    high_risk = sum(1 for f in features if f["properties"].get("pm25", 0) > 35.4)
    high_risk_strict = sum(1 for f in features if f["properties"].get("aqi", 0) > 100)
    
    pm25_vals = [f["properties"].get("pm25", 0) for f in features]
    # Filter out 0s if appropriate, or keep them. Here keeping them but handling empty list.
    if total > 0:
        avg_pm25 = round(sum(pm25_vals) / total, 1)
    else:
        avg_pm25 = 0

    sorted_by_aqi = sorted(features, key=lambda x: x["properties"].get("aqi", 0), reverse=True)
    worst_station = sorted_by_aqi[0]["properties"]["name"] if sorted_by_aqi else "-"

    # Prepare marker lists
    lats, lons, texts, colors, sizes, customdata = [], [], [], [], [], []
    for f in features:
        p = f["properties"]
        # Ensure geometry exists
        if not f.get("geometry") or not f["geometry"].get("coordinates"):
            continue
            
        lats.append(f["geometry"]["coordinates"][1])
        lons.append(f["geometry"]["coordinates"][0])
        
        # Handle missing keys gracefully
        name = p.get("name", "Unknown")
        city = p.get("city", "Unknown")
        aqi = p.get("aqi", 0)
        pm25 = p.get("pm25", 0)
        cat = p.get("category", "Unknown")
        color = COLORS.get(cat, COLORS["Unknown"])
        
        texts.append(f"{name}<br>City: {city}<br>AQI: {aqi}<br>PM2.5: {pm25} µg/m³")
        colors.append(color)
        sizes.append(12 if aqi <= 50 else (16 if aqi <= 150 else 20))
        customdata.append([p.get('station_id'), name, city, aqi, cat])

    hovertemplate = "%{text}<extra></extra>"

    scatter = go.Scattermapbox(
        lat=lats,
        lon=lons,
        mode='markers',
        marker=go.scattermapbox.Marker(
            size=sizes,
            color=colors,
            opacity=0.9
        ),
        text=texts,
        hovertemplate=hovertemplate,
        customdata=customdata,
        name="Stations",
        showlegend=False
    )

    # Create legend traces (plotted at center but small, to act as legend)
    legend_traces = []
    # Only show categories present in dataset
    present_categories = sorted(set([f["properties"]["category"] for f in features]),
                                key=lambda c: list(COLORS.keys()).index(c) if c in COLORS else 999)
    for i, cat in enumerate(present_categories):
        legend_traces.append(go.Scattermapbox(
            lat=[DEFAULT_CENTER_LAT + 0.01 * (i+1)],
            lon=[DEFAULT_CENTER_LON + 0.01 * (i+1)],
            mode='markers',
            marker=go.scattermapbox.Marker(size=8, color=COLORS.get(cat, COLORS["Unknown"])),
            text=[cat],
            hoverinfo='none',
            name=cat,
            showlegend=True
        ))

    all_traces = [scatter] + legend_traces

    fig = go.Figure(data=all_traces)

    # Use dark map style
    map_style = "carto-darkmatter"

    fig.update_layout(
        mapbox=dict(
            accesstoken=MAPBOX_ACCESS_TOKEN if MAPBOX_ACCESS_TOKEN else None,
            style=map_style,
            center=dict(lat=DEFAULT_CENTER_LAT, lon=DEFAULT_CENTER_LON),
            zoom=DEFAULT_ZOOM
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(bgcolor='rgba(0,0,0,0.4)', orientation='v', x=0.02, y=0.98, bordercolor='rgba(255,255,255,0.06)'),
        hovermode='closest'
    )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return fig, str(total), str(high_risk_strict), f"{avg_pm25}", worst_station, f"Last Update: {timestamp}"

@app.callback(
    Output("selected-station-store", "data"),
    [Input("map", "clickData")]
)
def update_selected_station(clickData):
    if not clickData:
        return None
    point = clickData['points'][0]
    # customdata: [station_id, name, city, aqi, category]
    return {
        "station_id": point['customdata'][0],
        "name": point['customdata'][1],
        "city": point['customdata'][2],
        "aqi": point['customdata'][3],
        "category": point['customdata'][4]
    }

@app.callback(
    Output("side-panel-content", "children"),
    [Input("selected-station-store", "data"),
     Input("interval-component", "n_intervals")] # Refresh if needed
)
def update_side_panel(data, n):
    if not data:
        return html.Div([
            html.H3("Select a station on the map", style={'color': '#7F8C8D', 'textAlign': 'center', 'marginTop': '40%'}),
            html.P("Click any marker to view detailed analytics", style={'color': '#616A6B', 'textAlign': 'center'})
        ], style={'height': '100%'})

    station_id = data["station_id"]
    # Mock Data Fetch
    df_trend = get_timeseries(station_id)
    forecast = get_forecast(station_id)

    # Trend Chart
    fig_trend = px.area(df_trend, x="ts", y="value", title="PM2.5 Trend (Last 7 Days)")
    fig_trend.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=20, t=40, b=40),
        height=250,
        xaxis_title=None,
        yaxis_title="µg/m³"
    )
    fig_trend.add_hline(y=THRESHOLDS["pm25"], line_dash="dash", line_color="#FFEB3B", annotation_text="WHO Limit", annotation_position="top left")

    # Forecast Cards
    forecast_html = []
    for day in forecast:
        forecast_html.append(html.Div([
            html.Div(day["day"], style={'fontWeight': '700', 'marginBottom': '6px', 'color': '#ECF0F1'}),
            html.Div(f"{day['avg']}", style={'fontSize': '1.1rem', 'fontWeight': '800', 'color': '#FFD54F'}),
            html.Div("PM2.5 (avg)", style={'fontSize': '0.7rem', 'color': '#95A5A6'})
        ], style={'backgroundColor': '#122021', 'padding': '10px', 'borderRadius': '6px', 'textAlign': 'center', 'flex': '1'}))

    return html.Div([
        # Header
        html.Div([
            html.H2(data["name"], style={'margin': '0', 'color': '#ECF0F1'}),
            html.P(f"{data['city']} • {data['category']}", style={'margin': '0', 'color': COLORS.get(data['category'], '#fff')})
        ], style={'marginBottom': '12px', 'borderBottom': '1px solid #223033', 'paddingBottom': '10px'}),

        # Current Status
        html.Div([
            html.Div([
                html.Div("Current AQI", style={'display': 'block', 'fontSize': '0.8rem', 'color': '#95A5A6'}),
                html.Div(f"{data['aqi']}", style={'fontSize': '2.2rem', 'fontWeight': '800', 'color': COLORS.get(data['category'], '#fff')})
            ], style={'flex': '1'}),
            html.Div([
                html.Div("Dominant Pollutant", style={'display': 'block', 'fontSize': '0.8rem', 'color': '#95A5A6'}),
                html.Div("PM2.5", style={'fontSize': '1.1rem', 'fontWeight': '700', 'color': '#ECF0F1'})
            ], style={'flex': '1', 'textAlign': 'right'})
        ], style={'display': 'flex', 'marginBottom': '14px'}),

        # Trend Graph
        dcc.Graph(figure=fig_trend, config={'displayModeBar': False}),

        # Forecast
        html.H4("5-Day Forecast", style={'marginTop': '12px', 'marginBottom': '8px', 'color': '#BDC3C7'}),
        html.Div(forecast_html, style={'display': 'flex', 'gap': '8px'}),

        # Attribution
        html.Div([
            html.P("Source: Mock EPA Data", style={'fontSize': '0.8rem', 'color': '#7F8C8D', 'marginTop': '16px'})
        ])
    ])

@app.callback(
    Output("tabs-content", "children"),
    [Input("analysis-tabs", "value")]
)
def update_tabs(tab):
    # Fetch real data from API
    try:
        response = requests.get(f"{API_INTERNAL_URL}/stations.geojson")
        if response.status_code == 200:
            geojson = response.json()
        else:
            geojson = MOCK_GEOJSON # Fallback
    except Exception:
        geojson = MOCK_GEOJSON # Fallback

    features = geojson["features"]

    if tab == 'tab-overview':
        # Prepare data
        aqi_vals = [f["properties"].get("aqi", 0) for f in features]
        pm25_vals = [f["properties"].get("pm25", 0) for f in features]
        categories = [f["properties"].get("category", "Unknown") for f in features]
        
        # Category distribution (pie/bar)
        from collections import Counter
        cat_counts = Counter(categories)
        
        # Histogram with better styling
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Histogram(
            x=aqi_vals,
            nbinsx=25,
            marker=dict(
                color=aqi_vals,
                colorscale=[[0, '#43A047'], [0.3, '#FFC107'], [0.6, '#FF8A65'], [1, '#E53935']],
                line=dict(color='rgba(255,255,255,0.2)', width=1)
            ),
            name='AQI Distribution'
        ))
        fig_hist.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=280,
            title=dict(text="Nationwide AQI Distribution", font=dict(size=16, color='#ECF0F1')),
            xaxis=dict(title="AQI", gridcolor='rgba(255,255,255,0.05)'),
            yaxis=dict(title="Station Count", gridcolor='rgba(255,255,255,0.05)'),
            margin=dict(l=40, r=20, t=40, b=40)
        )
        
        # Category breakdown pie chart
        fig_pie = go.Figure(data=[go.Pie(
            labels=list(cat_counts.keys()),
            values=list(cat_counts.values()),
            marker=dict(colors=[COLORS.get(cat, COLORS["Unknown"]) for cat in cat_counts.keys()]),
            hole=0.4,
            textposition='inside',
            textinfo='percent+label'
        )])
        fig_pie.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=280,
            title=dict(text="Category Breakdown", font=dict(size=16, color='#ECF0F1')),
            showlegend=False,
            margin=dict(l=20, r=20, t=40, b=20)
        )
        
        # Statistics cards
        avg_aqi = round(sum(aqi_vals)/len(aqi_vals), 1) if aqi_vals else 0
        median_aqi = sorted(aqi_vals)[len(aqi_vals)//2] if aqi_vals else 0
        max_aqi = max(aqi_vals) if aqi_vals else 0

        stats_cards = html.Div([
            html.Div([
                html.Div("Average AQI", style={'fontSize': '0.75rem', 'color': '#95A5A6', 'textTransform': 'uppercase'}),
                html.Div(f"{avg_aqi}", style={'fontSize': '1.8rem', 'fontWeight': '800', 'color': '#3498DB'})
            ], style={'background': 'rgba(52,152,219,0.1)', 'padding': '12px', 'borderRadius': '8px', 'flex': '1', 'border': '1px solid rgba(52,152,219,0.3)'}),
            html.Div([
                html.Div("Median AQI", style={'fontSize': '0.75rem', 'color': '#95A5A6', 'textTransform': 'uppercase'}),
                html.Div(f"{median_aqi}", style={'fontSize': '1.8rem', 'fontWeight': '800', 'color': '#2ECC71'})
            ], style={'background': 'rgba(46,204,113,0.1)', 'padding': '12px', 'borderRadius': '8px', 'flex': '1', 'border': '1px solid rgba(46,204,113,0.3)'}),
            html.Div([
                html.Div("Max AQI", style={'fontSize': '0.75rem', 'color': '#95A5A6', 'textTransform': 'uppercase'}),
                html.Div(f"{max_aqi}", style={'fontSize': '1.8rem', 'fontWeight': '800', 'color': '#E74C3C'})
            ], style={'background': 'rgba(231,76,60,0.1)', 'padding': '12px', 'borderRadius': '8px', 'flex': '1', 'border': '1px solid rgba(231,76,60,0.3)'})
        ], style={'display': 'flex', 'gap': '12px', 'marginBottom': '16px'})
        
        # Top 5 with cards
        sorted_aqi = sorted(features, key=lambda x: x["properties"].get("aqi", 0), reverse=True)[:5]
        top5_cards = []
        for i, f in enumerate(sorted_aqi):
            p = f["properties"]
            cat = p.get("category", "Unknown")
            badge_color = COLORS.get(cat, COLORS["Unknown"])
            top5_cards.append(html.Div([
                html.Div([
                    html.Div(f"#{i+1}", style={
                        'width': '32px',
                        'height': '32px',
                        'borderRadius': '50%',
                        'background': badge_color,
                        'display': 'flex',
                        'alignItems': 'center',
                        'justifyContent': 'center',
                        'fontWeight': '800',
                        'fontSize': '0.9rem',
                        'color': '#fff'
                    }),
                    html.Div([
                        html.Div(p.get("name", "Unknown"), style={'fontWeight': '700', 'fontSize': '0.95rem', 'color': '#ECF0F1'}),
                        html.Div(p.get("city", "Unknown"), style={'fontSize': '0.75rem', 'color': '#95A5A6'})
                    ], style={'flex': '1', 'marginLeft': '12px'})
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '8px'}),
                html.Div([
                    html.Span(f"AQI: {p.get('aqi', 0)}", style={'fontWeight': '800', 'fontSize': '1.1rem', 'color': badge_color}),
                    html.Span(f" • PM2.5: {p.get('pm25', 0)} µg/m³", style={'fontSize': '0.85rem', 'color': '#BDC3C7', 'marginLeft': '8px'})
                ])
            ], style={
                'background': 'linear-gradient(135deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01))',
                'padding': '14px',
                'borderRadius': '8px',
                'marginBottom': '10px',
                'border': f'1px solid {badge_color}33',
                'boxShadow': f'0 4px 8px {badge_color}22'
            }))
        
        return html.Div([
            stats_cards,
            html.Div([
                html.Div([dcc.Graph(figure=fig_hist, config={'displayModeBar': False})], style={'flex': '1.5', 'minWidth': '300px'}),
                html.Div([dcc.Graph(figure=fig_pie, config={'displayModeBar': False})], style={'flex': '1', 'minWidth': '250px'})
            ], style={'display': 'flex', 'gap': '16px', 'flexWrap': 'wrap', 'marginBottom': '16px'}),
            html.Div([
                html.H4("🏆 Top 5 Worst Air Quality Stations", style={'color': '#ECF0F1', 'marginBottom': '12px', 'fontSize': '1.1rem'}),
                html.Div(top5_cards)
            ])
        ])

    elif tab == 'tab-table':
        # Prepare DataFrame for Table
        data = []
        for f in features:
            p = f["properties"]
            data.append({
                "Station": p.get("name", "Unknown"),
                "City": p.get("city", "Unknown"),
                "AQI": p.get("aqi", 0),
                "PM2.5": p.get("pm25", 0),
                "Category": p.get("category", "Unknown"),
                "Status": "🟢 Online"
            })
        df = pd.DataFrame(data)

        return html.Div([
            html.Div([
                html.H4("📍 All Monitoring Stations", style={'color': '#ECF0F1', 'marginBottom': '12px'}),
                html.P(f"Total: {len(df)} stations • Use filters to narrow down results", style={'color': '#95A5A6', 'fontSize': '0.85rem', 'marginBottom': '16px'})
            ]),
            dash_table.DataTable(
                data=df.to_dict('records'),
                columns=[{'name': i, 'id': i} for i in df.columns],
                sort_action="native",
                filter_action="native",
                page_size=15,
                style_header={
                    'backgroundColor': '#223033',
                    'fontWeight': '700',
                    'color': '#ECF0F1',
                    'textAlign': 'left',
                    'padding': '12px',
                    'border': '1px solid #2C3E50',
                    'fontSize': '0.9rem'
                },
                style_cell={
                    'backgroundColor': '#172021',
                    'color': '#BDC3C7',
                    'border': '1px solid #223033',
                    'textAlign': 'left',
                    'padding': '10px',
                    'fontSize': '0.9rem'
                },
                style_data={
                    'border': '1px solid #223033'
                },
                style_data_conditional=[
                    # Alternating row colors
                    {
                        'if': {'row_index': 'odd'},
                        'backgroundColor': '#1A2425'
                    },
                    # AQI highlighting
                    {
                        'if': {'filter_query': '{AQI} > 150', 'column_id': 'AQI'},
                        'color': '#E53935',
                        'fontWeight': 'bold'
                    },
                    {
                        'if': {'filter_query': '{AQI} > 100 && {AQI} <= 150', 'column_id': 'AQI'},
                        'color': '#FF8A65',
                        'fontWeight': 'bold'
                    },
                    {
                        'if': {'filter_query': '{AQI} > 50 && {AQI} <= 100', 'column_id': 'AQI'},
                        'color': '#FFC107',
                        'fontWeight': 'bold'
                    },
                    {
                        'if': {'filter_query': '{AQI} <= 50', 'column_id': 'AQI'},
                        'color': '#43A047',
                        'fontWeight': 'bold'
                    },
                    # Category coloring
                    {
                        'if': {'filter_query': '{Category} = "Good"', 'column_id': 'Category'},
                        'color': '#43A047',
                        'fontWeight': '600'
                    },
                    {
                        'if': {'filter_query': '{Category} = "Moderate"', 'column_id': 'Category'},
                        'color': '#FFC107',
                        'fontWeight': '600'
                    },
                    {
                        'if': {'filter_query': '{Category} contains "Unhealthy"', 'column_id': 'Category'},
                        'color': '#FF8A65',
                        'fontWeight': '600'
                    },
                    {
                        'if': {'filter_query': '{Category} = "Very Unhealthy"', 'column_id': 'Category'},
                        'color': '#8E24AA',
                        'fontWeight': '600'
                    },
                    {
                        'if': {'filter_query': '{Category} = "Hazardous"', 'column_id': 'Category'},
                        'color': '#E53935',
                        'fontWeight': '600'
                    }
                ],
                style_filter={
                    'backgroundColor': '#2C3E50',
                    'color': '#ECF0F1'
                }
            )
        ])

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
