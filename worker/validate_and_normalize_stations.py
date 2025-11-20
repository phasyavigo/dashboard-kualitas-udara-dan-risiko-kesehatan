#!/usr/bin/env python3
"""
validate_and_normalize_stations.py

Reads: ./stations_indonesia.json
Writes:
 - ./stations_indonesia_normalized.json
 - ./stations_normalized.csv

This script expects items that look like AQICN map/bounds responses where each item may have:
 - uid, lat, lon, station (object with name, maybe city)
It will:
 - filter points within Indonesia bbox,
 - normalize fields to canonical keys,
 - deduplicate by uid or lat/lon+name.
"""

import json
import csv
from pathlib import Path
from typing import Any, Dict

# INPUT: change if your file is elsewhere
INPUT_PATH = Path("stations_indonesia.json")
OUT_JSON = Path("stations_indonesia_normalized.json")
OUT_CSV = Path("stations_normalized.csv")

# loose bounding box for Indonesia
MIN_LAT, MAX_LAT = -11.0, 6.5
MIN_LON, MAX_LON = 95.0, 141.0

def in_indonesia(lat: float, lon: float) -> bool:
    try:
        return (MIN_LAT <= lat <= MAX_LAT) and (MIN_LON <= lon <= MAX_LON)
    except Exception:
        return False

def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    # AQICN responses sometimes put metadata inside 'station' object
    uid = rec.get("uid")
    station_obj = rec.get("station") or {}
    # station_obj may be string in some nonstandard dumps; guard
    if isinstance(station_obj, str):
        station_name = station_obj
        station_city = ""
    else:
        station_name = station_obj.get("name") or rec.get("name") or ""
        # station city can be nested like {'city': {'name': 'City, Country'}}
        station_city = ""
        city_field = station_obj.get("city")
        if isinstance(city_field, dict):
            station_city = city_field.get("name") or ""
        elif isinstance(city_field, str):
            station_city = city_field
        else:
            station_city = rec.get("city") or ""

    lat = rec.get("lat") or rec.get("latitude") or None
    lon = rec.get("lon") or rec.get("longitude") or None

    station_id = f"aqicn-{uid}" if uid is not None else f"aqicn-unknown-{abs(hash(station_name))%100000}"

    normalized = {
        "station_id": station_id,
        "uid": uid,
        "name": station_name.strip(),
        "city": station_city.strip(),
        "country": "ID",
        "provider": "AQICN",
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
        "params": [],            # placeholder, to be filled by detail fetch
        "last_update": None,
        "meta": rec              # store raw object for audit
    }
    return normalized

def main():
    assert INPUT_PATH.exists(), f"{INPUT_PATH} not found. Put your stations file there."
    raw = json.loads(INPUT_PATH.read_text(encoding="utf8"))
    # If file is API response wrapper like {"status":"ok","data":[...]}
    if isinstance(raw, dict) and "data" in raw:
        data = raw["data"]
    else:
        data = raw

    normalized = []
    seen = set()
    dropped = []
    for rec in data:
        n = normalize_record(rec)
        lat, lon = n["lat"], n["lon"]
        if lat is None or lon is None:
            dropped.append((n, "missing coordinates"))
            continue
        if not in_indonesia(lat, lon):
            dropped.append((n, "outside Indonesia bbox"))
            continue
        # dedupe by uid if present, else by (lat,lon,name)
        key = (n["uid"], round(lat,6), round(lon,6), n["name"].lower())
        if key in seen:
            continue
        seen.add(key)
        normalized.append(n)

    # write outputs
    OUT_JSON.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"Wrote {len(normalized)} normalized stations to {OUT_JSON}")

    with OUT_CSV.open("w", encoding="utf8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["station_id","uid","name","city","country","provider","lat","lon","params_json","last_update","meta_json"])
        for n in normalized:
            writer.writerow([
                n["station_id"],
                n["uid"],
                n["name"],
                n["city"],
                n["country"],
                n["provider"],
                n["lat"],
                n["lon"],
                json.dumps(n["params"], ensure_ascii=False),
                n["last_update"],
                json.dumps(n["meta"], ensure_ascii=False)
            ])
    print(f"Wrote CSV to {OUT_CSV}")
    if dropped:
        print(f"Dropped {len(dropped)} records (sample): {dropped[:3]}")

if __name__ == "__main__":
    main()
