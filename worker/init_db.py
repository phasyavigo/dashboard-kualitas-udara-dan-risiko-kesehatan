import os
import json
import psycopg2
import requests
from psycopg2.extras import Json

# Database Configuration
DB_HOST = os.environ.get("PGHOST", "localhost")
DB_PORT = os.environ.get("PGPORT", "5432")
DB_NAME = os.environ.get("PGDATABASE", "airdb")
DB_USER = os.environ.get("PGUSER", "air")
DB_PASS = os.environ.get("PGPASSWORD", "airpass")

def get_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )
    return conn

def create_tables():
    conn = get_connection()
    cur = conn.cursor()
    
    print("Creating tables if not exist...")
    
    # Enable PostGIS
    cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    
    # Table: stations
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stations (
            station_id VARCHAR(255) PRIMARY KEY,
            uid INT,
            name TEXT,
            city TEXT,
            params JSONB,
            last_update TIMESTAMP,
            geom GEOMETRY(Point, 4326),
            geomjson TEXT
        );
    """)
    
    # Table: observations
    cur.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id SERIAL PRIMARY KEY,
            station_id VARCHAR(255) REFERENCES stations(station_id),
            ts TIMESTAMP,
            param VARCHAR(50),
            value FLOAT,
            unit VARCHAR(50),
            raw_json JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(station_id, ts, param)
        );
    """)
    
    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stations_geom ON stations USING GIST (geom);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_obs_station_ts ON observations (station_id, ts);")
    
    conn.commit()
    cur.close()
    conn.close()
    print("Tables created.")

def populate_stations():
    # Load stations from JSON file
    # If file doesn't exist, maybe fetch it? For now assume it exists or we run fetch script.
    # We will try to read 'stations_indonesia.json' which is created by fetch_stations_and_city.py
    
    
    with open('stations_indonesia.json', 'r', encoding='utf-8') as f:
        stations = json.load(f)
        
    conn = get_connection()
    cur = conn.cursor()
    
    print(f"Inserting {len(stations)} stations...")
    
    for s in stations:
        uid = s.get("uid")
        name = s.get("name")
        city = s.get("city")
        lat = s.get("lat")
        lon = s.get("lon")
        station_id = str(uid) # Use UID as station_id for simplicity
        
        # Insert or Update
        cur.execute("""
            INSERT INTO stations (station_id, uid, name, city, geom, geomjson)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)
            ON CONFLICT (station_id) DO UPDATE SET
                name = EXCLUDED.name,
                city = EXCLUDED.city,
                geom = EXCLUDED.geom,
                geomjson = EXCLUDED.geomjson;
        """, (
            station_id, uid, name, city, lon, lat,
            json.dumps({"type": "Point", "coordinates": [lon, lat]})
        ))
        
    conn.commit()
    cur.close()
    conn.close()
    print("Stations populated.")

if __name__ == "__main__":
    try:
        create_tables()
        populate_stations()
    except Exception as e:
        print(f"Error initializing DB: {e}")
