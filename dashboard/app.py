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
from collections import Counter

# Load environment variables
load_dotenv()

# --- Configuration & Constants ---
AQICN_TOKEN = os.environ.get("AQICN_TOKEN", "")
MAPBOX_ACCESS_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")

API_INTERNAL_URL = os.environ.get("API_INTERNAL_URL", "http://backend:8000")
API_PUBLIC_URL = os.environ.get("API_PUBLIC_URL", "http://localhost:8000")

# Default center (Indonesia)
DEFAULT_CENTER_LAT = -2.5489
DEFAULT_CENTER_LON = 118.0149
DEFAULT_ZOOM = 4

# Updated Color Palette - Design System
COLORS = {
    "Good": "#76F0A9",                         # teal
    "Moderate": "#F59964",                     # orange
    "Unhealthy": "#F87064",                    
    "Hazardous": "#7E9FF0",                  
}

def simplify_category(cat):
    """Map backend categories to the 4-color design system"""
    if cat in ["Unhealthy for Sensitive Groups", "Unhealthy"]:
        return "Unhealthy"
    elif cat in ["Very Unhealthy", "Hazardous"]:
        return "Hazardous"
    return cat

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




def get_timeseries(station_id, param="pm25", days=7):
    """Fetch Timeseries Data"""
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

    # Return empty DataFrame on failure
    return pd.DataFrame(columns=['ts', 'value'])

def get_forecast(station_id):
    """Fetch 5-day Forecast"""
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

    return []

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
        style={
            'height': '600px',
            'width': '100%',
            'borderRadius': '8px',
            'overflow': 'hidden'
        },
        config={
            'displayModeBar': False,
            'scrollZoom': True
        }
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
                'fontSize': '3rem',
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
            html.Div("Data Source: Real-time API", style={
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

    html.Div([
    dcc.Tabs(
        id="analysis-tabs", 
        value='tab-overview', 
        parent_style={'backgroundColor': 'transparent'}, 
        
        children=[
            dcc.Tab(
                label='📊 Nationwide Overview', 
                value='tab-overview', 
                style={
                    'color': '#888888', 
                    'backgroundColor': '#242a3b', 
                    'border': 'none',
                    'fontWeight': 'bold',
                    'borderRadius': '10px 0 0 0', 
                    'padding': '12px',
                    'borderRight': '1px solid #1E2631',
                    'fontSize': '1.5rem'
                },
                selected_style={
                    'color': '#ECF0F1', 
                    'backgroundColor': '#21c7ef', 
                    'border': 'none',
                    'fontWeight': 'bold',
                    'borderRadius': '10px 0 0 0',
                    'padding': '12px',
                    'fontSize': '1.5rem',
                }
            ),
            dcc.Tab(
                label='📋 Station List', 
                value='tab-table', 
                style={
                    'color': '#888888', 
                    'backgroundColor': '#242a3b',
                    'border': 'none',
                    'fontWeight': 'bold',
                    'borderRadius': '0 10px 0 0', 
                    'padding': '12px',
                    'fontSize': '1.5rem'
                },
                selected_style={
                    'color': '#ECF0F1', 
                    'backgroundColor': '#ff6969', 
                    'border': 'none',
                    'fontWeight': 'bold',
                    'borderRadius': '0 10px 0 0',
                    'padding': '12px',
                    'fontSize': '1.5rem'
                }
            ),
        ], 
        style={'marginBottom': '0px', 'borderBottom': '2px solid #242a3b'}
    ),
    
    html.Div(id="tabs-content", style={'padding': '16px'})

], style={
    'background': '#282F3C',
    'padding': '8px',
    'borderRadius': '10px',
    'boxShadow': '0 4px 8px rgba(0,0,0,0.3)'
})

], style={
    'padding': '20px',
    'backgroundColor': '#1E2631',
    'minHeight': '100vh',
    'fontFamily': '"Montserrat", sans-serif'
})

# Interval Component for Auto-Refresh
app.layout.children.append(dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0))

# Store for selected station
app.layout.children.append(dcc.Store(id='selected-station-store'))

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
            print(f"⚠️  Backend returned {response.status_code}")
            geojson = {"type": "FeatureCollection", "features": []}
    except Exception as e:
        print(f"❌ Error fetching from backend: {e}")
        geojson = {"type": "FeatureCollection", "features": []}

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
        cat = simplify_category(p.get("category", "Unknown"))
        # Update property so downstream (customdata, sidepanel) sees simplified category
        p["category"] = cat
        
        color = COLORS.get(cat, COLORS["Moderate"])
        
        texts.append(f"{name}<br>City: {city}<br>AQI: {aqi}<br>PM2.5: {pm25} µg/m³")
        colors.append(color)
        customdata.append([p.get('station_id'), name, city, aqi, cat])

    hovertemplate = "%{text}<extra></extra>"

    scatter = go.Scattermapbox(
        lat=lats,
        lon=lons,
        mode='markers',
        marker=go.scattermapbox.Marker(
            size=10,
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
            marker=go.scattermapbox.Marker(size=8, color=COLORS.get(cat, COLORS["Moderate"])),
            text=[cat],
            hoverinfo='none',
            name=cat,
            showlegend=True
        ))

    all_traces = [scatter] + legend_traces

    fig = go.Figure(data=all_traces)
    # map_style = "white-bg"
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
    # Fetch Data
    df_trend = get_timeseries(station_id)
    forecast = get_forecast(station_id)

    # Fetch Latest Pollutants
    pm25_val, pm10_val, o3_val, no2_val = 0, 0, 0, 0
    try:
        resp = requests.get(f"{API_INTERNAL_URL}/latest/{station_id}", timeout=5)
        if resp.status_code == 200:
            latest = resp.json().get("latest", {})
            pm25_val = latest.get("pm25", {}).get("value", 0)
            pm10_val = latest.get("pm10", {}).get("value", 0)
            o3_val = latest.get("o3", {}).get("value", 0)
            no2_val = latest.get("no2", {}).get("value", 0)
    except Exception as e:
        print(f"Error fetching latest for {station_id}: {e}")
        # Fallback
        pm25_val = data.get("pm25", 0)

    # Trend Chart
    fig_trend = px.area(df_trend, x="ts", y="value", title="PM 2.5 Trend (Last 7 Days)")
    fig_trend.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=24, r=20, t=40, b=40),
        height=250,
        title=dict(font=dict(size=14, color='#ECF0F1', family='"Montserrat", sans-serif'), x=0),
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

    # --- Header: name (left) and current AQI (right, aligned horizontally) ---
    header = html.Div([
        # Left: station name + city (lebih besar)
        html.Div([
            html.Div(
                data.get("name", "Unknown Station"),
                style={
                    'margin': '0',
                    'color': '#ECF0F1',
                    'fontSize': '1.6rem',
                    'fontWeight': '800',
                    'lineHeight': '1',
                    'paddingTop': '10px'
                }
            ),
            html.Div(
                data.get('city', ''),
                style={
                    'margin': '4px 0 0 0',
                    'color': '#95A5A6',
                    'fontSize': '0.95rem',
                    'paddingTop': '2px'
                }
            ),
            html.Div(
                datetime.now().strftime("%A, %d %B %Y"),
                style={
                    'margin': '8px 0 0 0',
                    'color': '#FFFFFF',
                    'fontSize': '1.2rem',
                    'fontWeight': 'bold'
                }
            ),
            html.Div(
                f"Last updated : {datetime.now().strftime('%H:%M')} WIB",
                style={
                    'margin': '2px 0 0 0',
                    'color': '#BDC3C7',
                    'fontSize': '0.9rem',
                    'fontWeight': '500'
                }
            )
        ], style={'flex': '1', 'paddingLeft': '8px'}),

        # Right: AQI card with label inside, centered
        html.Div([
            html.Div([
                html.Div("AQI", style={
                    'fontSize': '0.8rem',
                    'color': '#F7F7F7',
                    'opacity': 0.95,
                    'marginBottom': '6px',
                    'textAlign': 'center'
                }),
                html.Div(str(data.get('aqi', '-')), style={
                    'fontSize': '2.2rem',
                    'fontWeight': '900',
                    'lineHeight': '1',
                })
            ], style={
                'display': 'flex',
                'flexDirection': 'column',
                'alignItems': 'center',
                'justifyContent': 'center',
                'padding': '10px 14px',
                'minWidth': '86px',
                'minHeight': '64px',
                'borderRadius': '10px',
                'background': COLORS.get(data.get('category'), '#E74C3C'),
                'color': '#ffffff',
                'boxShadow': '0 4px 10px rgba(0,0,0,0.25)'
            })
        ], style={'display': 'flex', 'alignItems': 'flex-start', 'justifyContent': 'flex-end'})

    ], style={
        'display': 'flex',
        'alignItems': 'flex-start',
        'gap': '16px',
        'marginBottom': '8px',
        'borderBottom': '1px solid #223033',
        'paddingBottom': '12px'
    })

    # Pollutant small cards (arranged horizontally)
    pollutant_cards = html.Div([
        # PM 2.5
        html.Div([
            html.Div("PM 2.5", style={'fontSize': '0.75rem', 'color': '#95A5A6'}),
            html.Div(f"{pm25_val}", style={'fontSize': '1.3rem', 'fontWeight': '800', 'color': '#ECF0F1'})
        ], style={'backgroundColor': '#122021', 'padding': '12px', 'borderRadius': '8px', 'textAlign': 'center', 'flex': '1', 'border': '1px solid rgba(255,255,255,0.03)'}),

        # PM10
        html.Div([
            html.Div("PM10", style={'fontSize': '0.75rem', 'color': '#95A5A6'}),
            html.Div(f"{pm10_val}", style={'fontSize': '1.3rem', 'fontWeight': '800', 'color': '#ECF0F1'})
        ], style={'backgroundColor': '#122021', 'padding': '12px', 'borderRadius': '8px', 'textAlign': 'center', 'flex': '1', 'border': '1px solid rgba(255,255,255,0.03)'}),

        # O3
        html.Div([
            html.Div("O3", style={'fontSize': '0.75rem', 'color': '#95A5A6'}),
            html.Div(f"{o3_val}", style={'fontSize': '1.3rem', 'fontWeight': '800', 'color': '#ECF0F1'})
        ], style={'backgroundColor': '#122021', 'padding': '12px', 'borderRadius': '8px', 'textAlign': 'center', 'flex': '1', 'border': '1px solid rgba(255,255,255,0.03)'}),

        # NO2
        html.Div([
            html.Div("NO2", style={'fontSize': '0.75rem', 'color': '#95A5A6'}),
            html.Div(f"{no2_val}", style={'fontSize': '1.3rem', 'fontWeight': '800', 'color': '#ECF0F1'})
        ], style={'backgroundColor': '#122021', 'padding': '12px', 'borderRadius': '8px', 'textAlign': 'center', 'flex': '1', 'border': '1px solid rgba(255,255,255,0.03)'})
    ], style={'display': 'flex', 'gap': '8px', 'marginTop': '10px', 'marginBottom': '12px'})

    # Trend Chart
    fig_trend = px.area(df_trend, x="ts", y="value", title="<span style='font-size: 1.2rem; color: #FFFFFF; font-weight: bold'>PM 2.5 Trend (Last 7 Days)</span>")
    fig_trend.update_traces(
        line_shape='spline',
        line_width=3,
        line_color='#FFC107',
        fillcolor='rgba(255, 193, 7, 0.1)'
    )
    fig_trend.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=24, r=20, t=40, b=40),
        height=250,
        title=dict(font=dict(size=14, color='#ECF0F1', family='"Montserrat", sans-serif'), x=0),
        xaxis_title=f"--- WHO Limit ({THRESHOLDS['pm25']} µg/m³)",
        yaxis_title="µg/m³",
        yaxis=dict(
            showgrid=True,
            gridcolor='rgba(255,255,255,0.1)',
            zeroline=False
        ),
        xaxis=dict(
            showgrid=False
        )
    )
    fig_trend.add_hline(y=THRESHOLDS["pm25"], line_dash="5px,3px", line_color="#FFEB3B", annotation_text="WHO Limit", annotation_position="top left")

    # Forecast Cards
    forecast_html = []
    if forecast:
        for day in forecast:
            forecast_html.append(html.Div([
                html.Div(day.get("day", ""), style={'fontWeight': '700', 'marginBottom': '6px', 'color': '#ECF0F1'}),
                html.Div(f"{day.get('avg', '-')}", style={'fontSize': '1.1rem', 'fontWeight': '800', 'color': '#FFD54F'}),
                html.Div("PM2.5 (avg)", style={'fontSize': '0.7rem', 'color': '#95A5A6'})
            ], style={'backgroundColor': '#122021', 'padding': '10px', 'borderRadius': '6px', 'textAlign': 'center', 'flex': '1'}))
    else:
        forecast_html.append(html.Div("No forecast data available", style={'color': '#95A5A6', 'textAlign': 'center', 'width': '100%'}))

    return html.Div([
        header,
        # pollutant cards under header
        pollutant_cards,
        # Trend graph (left-aligned because fig margin l matches header paddingLeft)
        dcc.Graph(figure=fig_trend, config={'displayModeBar': False}),
        # Forecast
        html.H4("5-Day Forecast", style={'marginTop': '12px', 'marginBottom': '8px', 'fontSize': '1.2rem', 'color': '#FFFFFF', 'fontWeight': 'bold'}),
        html.Div(forecast_html, style={'display': 'flex', 'gap': '8px'}),
        html.Div([
            html.P("Source: Real-time API", style={'fontSize': '0.8rem', 'color': '#7F8C8D', 'marginTop': '16px'})
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
            geojson = {"type": "FeatureCollection", "features": []}
    except Exception:
        geojson = {"type": "FeatureCollection", "features": []}

    features = geojson["features"]

    if tab == 'tab-overview':
        # Precompute
        aqi_vals = [f["properties"].get("aqi", 0) for f in features]
        categories = [simplify_category(f["properties"].get("category", "Unknown")) for f in features]

        cat_counts = Counter(categories)

        # KPI / stats cards (top)
        avg_aqi = round(sum(aqi_vals)/len(aqi_vals), 1) if aqi_vals else 0
        median_aqi = sorted(aqi_vals)[len(aqi_vals)//2] if aqi_vals else 0
        max_aqi = max(aqi_vals) if aqi_vals else 0

        stats_cards = html.Div([
            html.Div([
                html.Div("AVERAGE AQI", style={'fontSize': '0.75rem', 'color': '#95A5A6', 'textTransform': 'uppercase'}),
                html.Div(f"{avg_aqi}", style={'fontSize': '1.6rem', 'fontWeight': '800', 'color': '#53B0F0'})
            ], style={'background': 'rgba(83,176,240,0.06)', 'padding': '12px', 'borderRadius': '8px', 'flex': '1', 'border': '1px solid rgba(83,176,240,0.12)'}),
            html.Div([
                html.Div("MEDIAN AQI", style={'fontSize': '0.75rem', 'color': '#95A5A6', 'textTransform': 'uppercase'}),
                html.Div(f"{median_aqi}", style={'fontSize': '1.6rem', 'fontWeight': '800', 'color': '#49C46E'})
            ], style={'background': 'rgba(73,196,110,0.05)', 'padding': '12px', 'borderRadius': '8px', 'flex': '1', 'border': '1px solid rgba(73,196,110,0.08)'}),
            html.Div([
                html.Div("MAX AQI", style={'fontSize': '0.75rem', 'color': '#95A5A6', 'textTransform': 'uppercase'}),
                html.Div(f"{max_aqi}", style={'fontSize': '1.6rem', 'fontWeight': '800', 'color': '#F06B6B'})
            ], style={'background': 'rgba(240,107,107,0.04)', 'padding': '12px', 'borderRadius': '8px', 'flex': '1', 'border': '1px solid rgba(240,107,107,0.10)'})
        ], style={'display': 'flex', 'gap': '12px', 'marginBottom': '18px'})

        # Scatter Plot (left) - AQI vs PM2.5
        pm25_vals = [f["properties"].get("pm25", 0) for f in features]
        station_names = [f["properties"].get("name", "Unknown") for f in features]

        fig_scatter = go.Figure()

        fig_scatter.add_trace(go.Scatter(
            x=aqi_vals,
            y=pm25_vals,
            mode='markers',
            text=station_names,
            marker=dict(
                size=10,
                color='rgba(70, 120, 180, 0.55)',    # soft blue transparent
                line=dict(width=1, color='rgba(70,120,180,0.9)'),
            ),
            hovertemplate="<b>%{text}</b><br>AQI: %{x}<br>PM2.5: %{y} µg/m³<extra></extra>"
        ))

        fig_scatter.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=330,
            margin=dict(l=10, r=10, t=10, b=10), # Reduced top margin since title is moved out
            xaxis=dict(
                title="AQI",
                gridcolor='rgba(255,255,255,0.05)',
                zeroline=False
            ),
            yaxis=dict(
                title="PM2.5 (µg/m³)",
                gridcolor='rgba(255,255,255,0.05)',
                zeroline=False
            )
        )

        # Donut pie (right)
        labels = list(cat_counts.keys())
        values = [cat_counts[k] for k in labels]
        pie_colors = [COLORS.get(k, COLORS["Moderate"]) for k in labels]

        fig_pie = go.Figure(data=[go.Pie(
            labels=labels,
            values=values,
            hole=0.45,
            marker=dict(colors=pie_colors, line=dict(color='rgba(0,0,0,0.12)', width=1)),
            textinfo='percent',
            textposition='inside',
            textfont=dict(color='#FFFFFF', size=14, family='Arial'),
            hoverinfo='label+value+percent',
            sort=False
        )])
        fig_pie.update_layout(
            showlegend=False,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=320
        )

        # Custom legend beside pie
        legend_items = []
        preferred_order = ["Good", "Moderate", "Unhealthy", "Hazardous"]
        ordered_labels = [l for l in preferred_order if l in labels] + [l for l in labels if l not in preferred_order]
        for lab in ordered_labels:
            color = COLORS.get(lab, COLORS["Moderate"])
            count = cat_counts.get(lab, 0)
            pct = f"{(count / sum(values) * 100):.1f}%" if sum(values) > 0 else "0%"
            legend_items.append(
                html.Div([
                    html.Div(style={
                        'width': '12px', 'height': '12px', 'borderRadius': '50%',
                        'background': color, 'marginRight': '10px', 'flex': '0 0 auto'
                    }),
                    html.Div([
                        html.Div(lab, style={'color': '#ECF0F1', 'fontSize': '0.95rem', 'marginBottom': '2px'}),
                        html.Div(pct, style={'color': '#95A5A6', 'fontSize': '0.82rem'})
                    ])
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '8px', 'marginBottom': '12px'})
            )

        legend_column = html.Div(legend_items, style={'display': 'flex', 'flexDirection': 'column', 'paddingLeft': '10px'})

        # Compose left + right sections
        left_section = html.Div([
            html.Div("AQI vs PM2.5 Correlation", style={
                'color': '#ECF0F1',
                'fontSize': '1.5rem',
                'fontWeight': '800',
                'marginBottom': '12px'
            }),
            html.Div(dcc.Graph(figure=fig_scatter, config={'displayModeBar': False}), style={'width': '100%'})
        ], style={'flex': '2', 'minWidth': '560px'})

        right_section = html.Div([
            html.Div("Category Breakdown", style={
                'color': '#ECF0F1',
                'fontSize': '1.5rem',
                'fontWeight': '800',
                'marginBottom': '12px'
            }),
            html.Div([
                html.Div(
                    dcc.Graph(figure=fig_pie, config={'displayModeBar': False}),
                    style={'width': '55%', 'minWidth': '200px'}
                ),
                html.Div(
                    legend_column,
                    style={'width': '45%', 'paddingLeft': '14px'}
                )
            ], style={
                'display': 'flex',
                'flexDirection': 'row',
                'alignItems': 'center',
                'justifyContent': 'flex-start',
                'width': '100%'
            })
        ], style={
            'flex': '1',
            'minWidth': '300px',
            'display': 'flex',
            'flexDirection': 'column',
            'alignItems': 'flex-start'
        })

        middle_row = html.Div([left_section, right_section], style={'display': 'flex', 'gap': '24px', 'alignItems': 'flex-start', 'marginBottom': '18px'})

        # Top 5 with cards
        sorted_aqi = sorted(features, key=lambda x: x["properties"].get("aqi", 0), reverse=True)[:5]
        top5_cards = []
        for i, f in enumerate(sorted_aqi):
            p = f["properties"]
            cat = simplify_category(p.get("category", "Unknown"))
            badge_color = COLORS.get(cat, COLORS["Moderate"])
            top5_cards.append(html.Div([
                html.Div([
                    html.Div(f"#{i+1}", style={
                        'width': '42px',
                        'height': '42px',
                        'borderRadius': '50%',
                        'background': badge_color,
                        'display': 'flex',
                        'alignItems': 'center',
                        'justifyContent': 'center',
                        'fontWeight': '800',
                        'fontSize': '1.1rem',
                        'color': '#fff',
                        'flex': '0 0 auto'
                    }),
                    html.Div([
                        html.Div(p.get("name", "Unknown"), style={'fontWeight': '700', 'fontSize': '1.1rem', 'color': '#ECF0F1'}),
                        html.Div(p.get("city", "Unknown"), style={'fontSize': '0.9rem', 'color': '#95A5A6', 'marginTop': '2px'})
                    ], style={'flex': '1', 'marginLeft': '12px'})
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '8px'}),
                html.Div([
                    html.Span(f"AQI: {p.get('aqi', 0)}", style={'fontWeight': '800', 'fontSize': '1.1rem', 'color': badge_color}),
                    html.Span(f" • PM2.5: {p.get('pm25', 0)} µg/m³", style={'fontSize': '0.95rem', 'color': '#ECF0F1', 'marginLeft': '8px', 'fontWeight': '500'})
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
            middle_row,
            html.Div([
                html.Div("🏆 Top 5 Worst Air Quality Stations", style={
                    'color': '#ECF0F1',
                    'fontSize': '1.5rem',
                    'fontWeight': '800',
                    'marginBottom': '12px'
                }),
                html.Div(top5_cards)
            ], style={'marginTop': '6px'})
        ], style={
            'backgroundColor': '#1E2631',
            'padding': '20px',
            'borderRadius': '12px',
            'boxShadow': '0 6px 18px rgba(0,0,0,0.35)'
        })

    elif tab == 'tab-table':
        # Prepare DataFrame for Table
        data = []
        for f in features:
            p = f["properties"]
            
            # Badge HTML generation for Markdown
            cat = simplify_category(p.get("category", "Unknown"))
            cat_color = COLORS.get(cat, COLORS["Moderate"])
            cat_badge = f'<span style="background-color: {cat_color}22; color: {cat_color}; padding: 4px 12px; border-radius: 12px; font-weight: 600; font-size: 0.85rem; border: 1px solid {cat_color}44;">{cat}</span>'
            
            aqi = p.get("aqi", 0)
            aqi_color = COLORS["Good"]
            if aqi > 200: aqi_color = COLORS["Hazardous"]
            elif aqi > 100: aqi_color = COLORS["Unhealthy"]
            elif aqi > 50: aqi_color = COLORS["Moderate"]
            
            aqi_badge = f'<span style="background-color: {aqi_color}22; color: {aqi_color}; padding: 4px 12px; border-radius: 12px; font-weight: 600; font-size: 0.85rem; border: 1px solid {aqi_color}44;">{aqi}</span>'

            data.append({
                "City": f"{p.get('city', 'Unknown')}, {p.get('name', 'Unknown')}",
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Category": cat_badge,
                "AQI": aqi_badge,
                "PM 2.5": p.get("pm25", 0)
            })
        df = pd.DataFrame(data)

        return html.Div([
            html.Div([
                html.Div([
                    html.H2("All Monitoring Stations", style={'color': '#ECF0F1', 'fontSize': '1.5rem', 'fontWeight': '800', 'margin': '0'}),
                    html.H3(f"Total: {len(df)} stations • Real-time Data", style={'color': '#95A5A6', 'fontSize': '0.9rem', 'fontWeight': '400', 'margin': '4px 0 0 0'})
                ], style={'flex': '1'}),
                html.Div([
                    dcc.Input(id='search-city', placeholder='Search city...', type='text', style={
                        'padding': '8px 12px', 'borderRadius': '6px', 'border': '1px solid #34495E',
                        'backgroundColor': '#2C3E50', 'color': '#ECF0F1', 'marginRight': '10px'
                    }),
                    dcc.Dropdown(
                        id='filter-category',
                        options=[{'label': c, 'value': c} for c in ["Good", "Moderate", "Unhealthy", "Hazardous"]],
                        placeholder="Filter Category",
                        style={'width': '160px', 'color': '#333'}
                    )
                ], style={'display': 'flex', 'alignItems': 'center'})
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '16px', 'paddingBottom': '12px', 'borderBottom': '1px solid #2C3E50'}),

            dash_table.DataTable(
                data=df.to_dict('records'),
                columns=[
                    {'name': 'City', 'id': 'City'},
                    {'name': 'Timestamp', 'id': 'ts'},
                    {'name': 'Category', 'id': 'Category', 'presentation': 'markdown'},
                    {'name': 'AQI', 'id': 'AQI', 'presentation': 'markdown'},
                    {'name': 'PM 2.5', 'id': 'PM 2.5'}
                ],
                sort_action="native",
                filter_action="native",
                page_size=10,
                style_header={
                    'backgroundColor': '#223033',
                    'fontWeight': '700',
                    'color': '#ECF0F1',
                    'textAlign': 'left',
                    'padding': '12px',
                    'border': '1px solid #2C3E50',
                    'fontSize': '0.95rem'
                },
                style_cell={
                    'backgroundColor': '#172021',
                    'color': '#BDC3C7',
                    'border': '1px solid #223033',
                    'textAlign': 'left',
                    'padding': '12px',
                    'fontSize': '0.95rem',
                    'fontFamily': '"Montserrat", sans-serif'
                },
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': '#1A2425'}
                ],
                style_filter={
                    'backgroundColor': '#2C3E50',
                    'color': '#ECF0F1'
                },
                markdown_options={"html": True}
            )
        ])

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
