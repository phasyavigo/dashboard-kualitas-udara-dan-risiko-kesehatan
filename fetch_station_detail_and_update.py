#!/usr/bin/env python3
"""
fetch_station_details_and_update.py

Fetch details for stations in DB (or from normalized json) and update 'params' (list of pollutant keys)
and 'last_update' timestamp in stations table.

Set AQICN_TOKEN in env or put secrets.json {"aqicn_token":"..."} in project root.
"""

import os
import json
import time
from pathlib import Path
import requests
import psycopg2
from psycopg2.extras import Json

# config
TOKEN = os.getenv("AQICN_TOKEN")
if not TOKEN:
    sec = Path("secrets.json")
    if sec.exists():
        TOKEN = json.loads(sec.read_text()).get("aqicn-api-key")

if not TOKEN:
    raise SystemExit("AQICN_TOKEN not set in env or secrets.json")

DB = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", 5432)),
    "dbname": os.getenv("PGDATABASE", "airdb"),
    "user": os.getenv("PGUSER", "air"),
    "password": os.getenv("PGPASSWORD", "airpass")
}

BATCH_SLEEP = 0.5  # seconds between requests to be polite; tune for rate limits

def connect():
    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    return conn

def get_stations_from_db():
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT station_id, uid, ST_X(geom) as lon, ST_Y(geom) as lat FROM stations;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    stations = []
    for station_id, uid, lon, lat in rows:
        stations.append({"station_id": station_id, "uid": uid, "lon": lon, "lat": lat})
    return stations

def fetch_detail_by_uid(uid):
    # prefer feed/@{uid} endpoint (the WAQI docs show feed/@uid pattern)
    url = f"https://api.waqi.info/feed/@{uid}/?token={TOKEN}"
    r = requests.get(url, timeout=20)
    if r.status_code != 200:
        return None
    js = r.json()
    if js.get("status") != "ok":
        return None
    return js["data"]

def update_station_in_db(station_id, params_list, last_update_iso, meta):
    conn = connect()
    cur = conn.cursor()
    sql = """
    UPDATE stations
    SET params = %s,
        last_update = %s,
        meta_json = meta_json || %s::jsonb,
        updated_at = now()
    WHERE station_id = %s;
    """
    cur.execute(sql, (params_list, last_update_iso, json.dumps(meta), station_id))
    cur.close()
    conn.close()

def main(limit=None):
    stations = get_stations_from_db()
    if limit:
        stations = stations[:limit]
    for s in stations:
        uid = s["uid"]
        station_id = s["station_id"]
        if uid is None:
            print(f"skip {station_id} no uid")
            continue
        detail = fetch_detail_by_uid(uid)
        time.sleep(BATCH_SLEEP)
        if not detail:
            print(f"no detail for uid {uid}")
            continue
        # parse iaqi keys
        iaqi = detail.get("iaqi", {})
        params = sorted(list(iaqi.keys()))
        # parse time
        t_iso = None
        t_field = detail.get("time")
        if isinstance(t_field, dict):
            t_iso = t_field.get("iso")
        # update
        update_station_in_db(station_id, params, t_iso, detail)
        print(f"updated {station_id} params={params} last_update={t_iso}")

if __name__ == "__main__":
    main(limit=10)  # set limit for testing, e.g., main(limit=50)
