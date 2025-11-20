import os
import json
import requests
import pandas as pd
import dash
import dash_leaflet as dl
from dash import dcc, html, Output, Input, State
import plotly.express as px
import plotly.graph_objects as go
from dash_extensions.javascript import assign, Namespace

# --- Configuration ---
API_INTERNAL_URL = os.environ.get("API_INTERNAL_URL", "http://backend:8000")
API_PUBLIC_URL = os.environ.get("API_PUBLIC_URL", "http://localhost:8000")
AQICN_TOKEN = os.environ.get("AQICN_TOKEN", "")

# Default center (Indonesia)
DEFAULT_CENTER = [-2.5489, 118.0149]
DEFAULT_ZOOM = 5

# --- App Initialization ---
app = dash.Dash(__name__, title="Air Quality Dashboard")
server = app.server

# ...

# --- Client-Side Javascript for Map Markers ---
# Use the user's custom JS from assets/dashExtensions_default.js
# Use the user's custom JS from assets/dashExtensions_default.js
# We use assign to reference the function attached to window.dashExtensions.default.function0
point_to_layer = assign("dashExtensions.default.function0")

# ...

# --- Helper Functions ---
def get_stations_geojson():
    try:
        resp = requests.get(f"{API_INTERNAL_URL}/stations.geojson")
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error fetching stations: {e}")
    return None

def get_timeseries(station_id, param="pm25"):
    try:
        resp = requests.get(f"{API_INTERNAL_URL}/timeseries/{station_id}/{param}?limit=100")
        if resp.status_code == 200:
            data = resp.json()
            return pd.DataFrame(data["series"])
    except Exception as e:
        print(f"Error fetching timeseries: {e}")
    return pd.DataFrame()

# --- Layout ---
app.layout = html.Div([
    # Header
    html.Div([
        html.H1("Air Quality & Health Risk Dashboard", style={'textAlign': 'center', 'color': 'white'}),
        html.P("Monitoring PM2.5, PM10, and other pollutants across Indonesia.", style={'textAlign': 'center', 'color': '#ddd'}),
    ], style={'backgroundColor': '#2c3e50', 'padding': '20px'}),

    # Main Content
    html.Div([
        # Summary Cards
        html.Div([
            html.Div([
                html.H4("Total Stations"),
                html.H2(id="total-stations", children="0")
            ], style={'width': '30%', 'display': 'inline-block', 'textAlign': 'center', 'backgroundColor': '#34495e', 'color': 'white', 'padding': '10px', 'borderRadius': '5px', 'margin': '1%'}),
            html.Div([
                html.H4("High Risk Areas (>50 PM2.5)"),
                html.H2(id="high-risk-count", children="0")
            ], style={'width': '30%', 'display': 'inline-block', 'textAlign': 'center', 'backgroundColor': '#c0392b', 'color': 'white', 'padding': '10px', 'borderRadius': '5px', 'margin': '1%'}),
            html.Div([
                html.H4("Average PM2.5 (Nationwide)"),
                html.H2(id="avg-pm25", children="0")
            ], style={'width': '30%', 'display': 'inline-block', 'textAlign': 'center', 'backgroundColor': '#f39c12', 'color': 'white', 'padding': '10px', 'borderRadius': '5px', 'margin': '1%'}),
        ], style={'marginBottom': '20px'}),

        # Left Column: Map
        html.Div([
            html.H3("Station Map"),
            dl.Map([
                dl.TileLayer(), # Default OpenStreetMap
                # AQICN Overlay
                dl.TileLayer(
                    url=f"https://tiles.aqicn.org/tiles/usepa-aqi/{{z}}/{{x}}/{{y}}.png?token={AQICN_TOKEN}",
                    opacity=0.5,
                    attribution="Air Quality Tiles &copy; <a href='http://waqi.info'>waqi.info</a>"
                ) if AQICN_TOKEN else None,
                dl.GeoJSON(
                    id="stations-layer",
                    url=f"{API_PUBLIC_URL}/stations.geojson",
                    options=dict(
                        pointToLayer=point_to_layer
                    ),
                    zoomToBounds=True
                )
            ], center=DEFAULT_CENTER, zoom=DEFAULT_ZOOM, style={'height': '600px'}, id="map"),
        ], style={'width': '60%', 'display': 'inline-block', 'verticalAlign': 'top', 'padding': '10px'}),

        # Right Column: Charts & Details
        html.Div([
            html.H3("Station Details"),
            html.Div(id="station-info", children="Click a station on the map to see details."),
            
            html.Hr(),
            
            html.H4("Pollutant Trends"),
            dcc.Dropdown(
                id="param-dropdown",
                options=[
                    {'label': 'PM2.5', 'value': 'pm25'},
                    {'label': 'PM10', 'value': 'pm10'},
                    {'label': 'Ozone (O3)', 'value': 'o3'},
                    {'label': 'NO2', 'value': 'no2'},
                    {'label': 'SO2', 'value': 'so2'},
                    {'label': 'CO', 'value': 'co'},
                ],
                value='pm25',
                clearable=False
            ),
            dcc.Graph(id="trend-graph", style={'height': '400px'}),
        ], style={'width': '38%', 'display': 'inline-block', 'verticalAlign': 'top', 'padding': '10px', 'boxSizing': 'border-box'})
    ], style={'display': 'flex', 'flexWrap': 'wrap'})
])

# --- Client-Side Javascript for Map Markers ---
# We need to inject some JS to handle the coloring of markers based on value.
# Since we can't easily write a separate .js file here without more setup, 
# we'll use a simplified approach or rely on the GeoJSON style property if the backend provides it.
# For now, let's assume the backend *could* provide style, or we use a simple circle marker.
# A better approach for Dash Leaflet is using the `hideout` prop for dynamic styling, 
# but for simplicity in this first pass, let's just render standard markers or circles.

# To make it "Green to Red", we really need that logic. 
# Let's add a dummy JS namespace for the `pointToLayer` if we were to use it.
# For this MVP, I will remove the custom `pointToLayer` and just use default markers 
# OR use `dl.CircleMarker` in a callback if I were constructing children dynamically.
# BUT `dl.GeoJSON` is best for performance.
# Let's stick to `dl.GeoJSON` but maybe without the custom JS for now to ensure it runs, 
# or add a simple functional prop.

# Actually, let's use a callback to generate the GeoJSON data with `style` properties 
# if we want to color them server-side, OR just let the frontend handle it.
# For now, I will remove `options` to avoid JS errors until we set up the assets folder.

# --- Callbacks ---

@app.callback(
    [Output("station-info", "children"),
     Output("trend-graph", "figure")],
    [Input("stations-layer", "click_feature"),
     Input("param-dropdown", "value")]
)
def update_details(feature, param):
    if not feature:
        return "Click a station to see details.", go.Figure()
    
    props = feature["properties"]
    station_id = props.get("station_id")
    name = props.get("name")
    city = props.get("city")
    
    # Info Text
    info = html.Div([
        html.H5(f"{name} ({city})"),
        html.P(f"Station ID: {station_id}"),
        html.P(f"Last Update: {props.get('last_update')}")
    ])
    
    # Fetch Data
    df = get_timeseries(station_id, param)
    
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No data available for this station/param",
            xaxis={"visible": False},
            yaxis={"visible": False},
            annotations=[{
                "text": "No Data Available",
                "xref": "paper",
                "yref": "paper",
                "showarrow": False,
                "font": {"size": 20}
            }],
            height=400,
            margin={'l': 40, 'b': 40, 't': 40, 'r': 40}
        )
    else:
        fig = px.line(df, x="ts", y="value", title=f"{param.upper()} Trend")
        fig.update_layout(height=400, margin={'l': 40, 'b': 40, 't': 40, 'r': 40})
        # Add threshold lines (WHO)
        thresholds = {
            "pm25": 15, # 24-hour
            "pm10": 45,
            "no2": 25,
            "so2": 40,
            "co": 4
        }
        if param in thresholds:
            fig.add_hline(y=thresholds[param], line_dash="dash", line_color="red", annotation_text="WHO Limit")
            
    return info, fig

@app.callback(
    [Output("total-stations", "children"),
     Output("high-risk-count", "children"),
     Output("avg-pm25", "children")],
    [Input("stations-layer", "data")] # Trigger when map data loads
)
def update_summary(geojson_data):
    if not geojson_data or "features" not in geojson_data:
        return "0", "0", "0"
    
    features = geojson_data["features"]
    total = len(features)
    
    high_risk = 0
    pm25_sum = 0
    pm25_count = 0
    
    for f in features:
        params = f["properties"].get("params")
        if params and "pm25" in params:
            # Handle different structures if needed, assuming simplified or raw
            try:
                val = params["pm25"]["v"] if isinstance(params["pm25"], dict) else params["pm25"]
                if val > 50:
                    high_risk += 1
                pm25_sum += val
                pm25_count += 1
            except:
                pass
                
    avg = f"{pm25_sum / pm25_count:.1f}" if pm25_count > 0 else "N/A"
    
    return str(total), str(high_risk), avg

if __name__ == "__main__":
    app.run_server(debug=True, host="0.0.0.0", port=8050)
