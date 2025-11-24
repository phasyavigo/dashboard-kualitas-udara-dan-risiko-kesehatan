import os, json, time, requests, psycopg2
from psycopg2.extras import Json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ... (secrets loading code remains same, handled by context)

# Setup Requests Session with Retry
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http = requests.Session()
http.mount("https://", adapter)
http.mount("http://", adapter)

try:
    with open('secrets.json', 'r') as file:
        secrets = json.load(file)
        file.close()
    TOKEN = secrets.get("aqicn-api-key")
except FileNotFoundError:
    TOKEN = os.environ.get("AQICN_TOKEN", "")

if not TOKEN:
    print("Error: No AQICN Token found in secrets.json or environment variables.")
    exit(1)

DB = {
  "host": os.environ.get("PGHOST", "localhost"),
  "port": int(os.environ.get("PGPORT", 5432)),
  "dbname": os.environ.get("PGDATABASE", "airdb"),
  "user": os.environ.get("PGUSER", "air"),
  "password": os.environ.get("PGPASSWORD", "airpass")
}

BATCH = 0.5

def connect():
    return psycopg2.connect(**DB)

def get_stations():
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT station_id, uid, ST_Y(geom) as lat, ST_X(geom) as lon FROM stations;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

def fetch_detail(uid, lat, lon):
    # try uid first
    url_uid = f"https://api.waqi.info/feed/@{uid}/?token={TOKEN}"
    try:
        r = http.get(url_uid, timeout=20)
        if r.status_code == 200 and r.json().get("status") == "ok":
            return r.json()["data"]
    except Exception as e:
        print(f"Error fetching UID {uid}: {e}")

    # fallback geo
    url_geo = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={TOKEN}"
    try:
        r = http.get(url_geo, timeout=20)
        js = r.json()
        if js.get("status") == "ok":
            return js["data"]
    except Exception as e:
        print(f"Error fetching GEO {lat},{lon}: {e}")
        
    return None

import math

def sanitize_data(data):
    if isinstance(data, dict):
        return {k: sanitize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_data(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
    return data

def enrich_with_forecast(data, iaqi):
    """
    If 'iaqi' is missing key pollutants (pm25, pm10), try to fill them
    from 'forecast' data for the current day.
    """
    forecast = data.get("forecast", {}).get("daily", {})
    if not forecast:
        return iaqi

    # Determine the date to look for. 
    time_data = data.get("time", {})
    date_str = None
    
    # Try ISO first
    if "iso" in time_data:
        # "2025-11-20T19:00:00+08:00" -> "2025-11-20"
        date_str = time_data["iso"].split("T")[0]
    elif "s" in time_data:
        # "2025-11-20 19:00:00" -> "2025-11-20"
        date_str = time_data["s"].split(" ")[0]
    
    if not date_str:
        return iaqi

    # Pollutants to check
    for pollutant in ["pm25", "pm10", "o3", "uvi"]:
        if pollutant not in iaqi and pollutant in forecast:
            # Find entry for today
            daily_data = forecast[pollutant]
            today_entry = next((item for item in daily_data if item.get("day") == date_str), None)
            
            if today_entry:
                # Use 'avg' as the value
                iaqi[pollutant] = {"v": today_entry["avg"], "from_forecast": True}
    
    return iaqi

def insert_observations(station_id, ts, iaqi, raw):
    conn = connect()
    cur = conn.cursor()
    
    # Sanitize iaqi to remove NaNs
    iaqi = sanitize_data(iaqi)
    
    json_str = json.dumps(iaqi)
    # print(f"DEBUG: station_id={station_id}, type={type(iaqi)}, json_len={len(json_str)}")

    # Extract AQI and dominant pollutant from raw data
    aqi_value = raw.get("aqi")
    dominentpol = raw.get("dominentpol")

    # Insert observations for each pollutant
    for param, obj in iaqi.items():
        value = obj.get("v")
        unit = obj.get("u") if isinstance(obj, dict) else None
        
        # If from_forecast, we might want to note it, but schema doesn't support it yet.
        # We just insert the value.
        
        cur.execute("""
            INSERT INTO observations (station_id, ts, param, value, unit, raw_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (station_id, ts, param) DO NOTHING
        """, (station_id, ts, param, value, unit, Json(raw)))
    
    # Insert AQI as a special parameter
    if aqi_value is not None:
        try:
            aqi_float = float(aqi_value)
            cur.execute("""
                INSERT INTO observations (station_id, ts, param, value, raw_json)
                VALUES (%s, %s, 'aqi', %s, %s)
                ON CONFLICT (station_id, ts, param) DO NOTHING
            """, (station_id, ts, aqi_float, Json(raw)))
        except ValueError:
            print(f"Skipping invalid AQI value: {aqi_value} for station {station_id}")
    
    # Insert dominant pollutant as a text parameter (store as numeric 1.0 for compatibility)
    # We'll store the actual pollutant name in unit field
    if dominentpol:
        cur.execute("""
            INSERT INTO observations (station_id, ts, param, value, unit, raw_json)
            VALUES (%s, %s, 'dominentpol', 1.0, %s, %s)
            ON CONFLICT (station_id, ts, param) DO NOTHING
        """, (station_id, ts, dominentpol, Json(raw)))
    
    # Update station with latest params and time
    cur.execute("""
        UPDATE stations 
        SET params = %s::jsonb, last_update = %s 
        WHERE station_id = %s
    """, (json.dumps(iaqi), ts, station_id))
    
    conn.commit()
    cur.close(); conn.close()

def main(limit=None):
    stations = get_stations()
    if limit:
        stations = stations[:limit]

    for station_id, uid, lat, lon in stations:
        if uid is None:
            print("skip", station_id, "no uid")
            continue
        data = fetch_detail(uid, lat, lon)
        time.sleep(BATCH)
        if not data:
            print("no data for", station_id)
            continue
        
        ts = None
        if "time" in data and isinstance(data["time"], dict):
            ts = data["time"].get("iso")
        
        iaqi = data.get("iaqi")
        if iaqi:
            # Enrich with forecast if needed
            iaqi = enrich_with_forecast(data, iaqi)
            
            insert_observations(station_id, ts, iaqi, data)
            print("inserted:", station_id, list(iaqi.keys()))

if __name__ == "__main__":
    # main(limit=10)   # try for 10 first
    main() # Run for all stations
