import os, json, time, requests, psycopg2
from psycopg2.extras import Json

with open('secrets.json', 'r') as file:
    secrets = json.load(file)
    file.close()

TOKEN = secrets["aqicn-api-key"]

DB = {
  "host": "localhost",
  "port": 5432,
  "dbname": "airdb",
  "user": "air",
  "password": "airpass"
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
    r = requests.get(url_uid, timeout=20)
    if r.status_code == 200 and r.json().get("status") == "ok":
        return r.json()["data"]

    # fallback geo
    url_geo = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={TOKEN}"
    r = requests.get(url_geo, timeout=20)
    js = r.json()
    if js.get("status") == "ok":
        return js["data"]
    return None

def insert_observations(station_id, ts, iaqi, raw):
    conn = connect()
    cur = conn.cursor()
    for param, obj in iaqi.items():
        value = obj.get("v")
        unit = obj.get("u") if isinstance(obj, dict) else None
        cur.execute("""
            INSERT INTO observations (station_id, ts, param, value, unit, raw_json)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (station_id, ts, param, value, unit, Json(raw)))
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
            insert_observations(station_id, ts, iaqi, data)
            print("inserted:", station_id, list(iaqi.keys()))

if __name__ == "__main__":
    main(limit=10)   # try for 10 first
