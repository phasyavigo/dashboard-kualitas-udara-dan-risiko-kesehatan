import os
import json
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

import asyncpg
from fastapi import FastAPI, HTTPException, Query
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as redis_lib  # Menggunakan library redis modern

# --- 1. KONFIGURASI SETTINGS (Perbaikan Pydantic V2) ---
class Settings(BaseSettings):
    # Mendefinisikan field agar cocok dengan variabel di .env
    # Pydantic bersifat case-insensitive (PGHOST di .env -> pghost di sini)
    pghost: str = "localhost"
    pgport: int = 5432
    pgdatabase: str = "airdb"
    pguser: str = "air"
    pgpassword: str = "airpass"
    redis_url: Optional[str] = "redis://localhost:6379"
    cache_ttl: int = 30

    # Konfigurasi untuk membaca file .env dan mengabaikan variabel extra yang tidak dikenal
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

# --- 2. INISIALISASI APP ---
app = FastAPI(title="Air Quality Dashboard API")

# Variabel Global untuk Koneksi Database & Redis
DB_POOL: Optional[asyncpg.pool.Pool] = None
REDIS_CLIENT = None

# --- 3. EVENTS (STARTUP & SHUTDOWN) ---
@app.on_event("startup")
async def startup():
    """Dijalankan saat server mulai: Buka koneksi DB & Redis"""
    global DB_POOL, REDIS_CLIENT
    
    # Koneksi ke PostgreSQL
    try:
        print(f"Connecting to DB at {settings.pghost}:{settings.pgport}...")
        DB_POOL = await asyncpg.create_pool(
            host=settings.pghost,
            port=settings.pgport,
            user=settings.pguser,
            password=settings.pgpassword,
            database=settings.pgdatabase,
            min_size=1,
            max_size=10
        )
        print("✅ Database connected.")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")

    # Koneksi ke Redis
    if settings.redis_url:
        try:
            print(f"Connecting to Redis at {settings.redis_url}...")
            # decode_responses=True agar outputnya string, bukan bytes
            REDIS_CLIENT = redis_lib.from_url(settings.redis_url, decode_responses=True)
            await REDIS_CLIENT.ping()
            print("✅ Redis connected.")
        except Exception as e:
            print(f"⚠️ Redis connection warning: {e}")
            REDIS_CLIENT = None

@app.on_event("shutdown")
async def shutdown():
    """Dijalankan saat server mati: Tutup koneksi"""
    global DB_POOL, REDIS_CLIENT
    if DB_POOL:
        await DB_POOL.close()
        print("Database connection closed.")
    if REDIS_CLIENT:
        await REDIS_CLIENT.close()
        print("Redis connection closed.")

# --- 4. UTILITY FUNCTIONS ---
def station_row_to_feature(row: asyncpg.Record) -> Dict[str, Any]:
    """Konversi baris database menjadi format GeoJSON Feature"""
    props = {
        "station_id": row["station_id"],
        "name": row["name"],
        "city": row["city"],
        "params": row["params"],
        "last_update": row["last_update"].isoformat() if row["last_update"] else None
    }
    # Parse geomjson string ke JSON object
    geom = json.loads(row["geomjson"]) if row["geomjson"] else None
    return {"type": "Feature", "properties": props, "geometry": geom}

# --- 5. ENDPOINTS ---

@app.get("/health")
async def health():
    """Cek kesehatan aplikasi & database"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        async with DB_POOL.acquire() as con:
            await con.execute('SELECT 1')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")
    
    return {"status": "ok", "database": "connected", "redis": "connected" if REDIS_CLIENT else "disabled"}

@app.get("/stations.geojson")
async def stations_geojson(
    lat_min: Optional[float] = None, lon_min: Optional[float] = None,
    lat_max: Optional[float] = None, lon_max: Optional[float] = None,
    force_refresh: bool = False
):
    """Mengambil data stasiun dalam format GeoJSON"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Cek Cache Redis
    cache_key = f"stations:{lat_min}:{lon_min}:{lat_max}:{lon_max}"
    if REDIS_CLIENT and not force_refresh:
        cached_data = await REDIS_CLIENT.get(cache_key)
        if cached_data:
            return json.loads(cached_data)

    # Buat Query SQL
    query = "SELECT station_id, name, city, params, last_update, ST_AsGeoJSON(geom) AS geomjson FROM stations"
    args = []
    
    # Filter berdasarkan koordinat (Bounding Box) jika parameter ada
    if None not in (lat_min, lon_min, lat_max, lon_max):
        query += " WHERE ST_X(geom) BETWEEN $1 AND $2 AND ST_Y(geom) BETWEEN $3 AND $4"
        args = [lon_min, lon_max, lat_min, lat_max] # Urutan postgis: X (lon), Y (lat)

    # Eksekusi Query
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch(query, *args)

    # Format ke GeoJSON
    features = [station_row_to_feature(r) for r in rows]
    geojson_data = {"type": "FeatureCollection", "features": features}

    # Simpan ke Redis Cache
    if REDIS_CLIENT:
        await REDIS_CLIENT.set(cache_key, json.dumps(geojson_data), ex=settings.cache_ttl)

    return geojson_data

@app.get("/latest/{station_id}")
async def latest_for_station(station_id: str):
    """Mengambil data observasi terbaru untuk stasiun tertentu"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with DB_POOL.acquire() as conn:
        # Ambil satu nilai terbaru untuk setiap parameter (DISTINCT ON param)
        sql = """
        SELECT DISTINCT ON (param) param, value, ts
        FROM observations
        WHERE station_id = $1
        ORDER BY param, ts DESC
        """
        rows = await conn.fetch(sql, station_id)

    if not rows:
        raise HTTPException(status_code=404, detail="No observations found for station")

    result = {r["param"]: {"value": r["value"], "ts": r["ts"].isoformat()} for r in rows}
    return {"station_id": station_id, "latest": result}

@app.get("/timeseries/{station_id}/{param}")
async def timeseries(
    station_id: str, 
    param: str, 
    start: Optional[str] = Query(None), 
    end: Optional[str] = Query(None), 
    limit: int = 1000
):
    """Mengambil data historis (timeseries)"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Validasi format tanggal
    start_ts = None
    end_ts = None
    try:
        if start: start_ts = datetime.fromisoformat(start)
        if end: end_ts = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Start/End must be ISO datetime strings")

    # Susun Query Dinamis
    query = "SELECT ts, value FROM observations WHERE station_id=$1 AND param=$2"
    args = [station_id, param]
    arg_counter = 3

    if start_ts:
        query += f" AND ts >= ${arg_counter}"
        args.append(start_ts)
        arg_counter += 1
    
    if end_ts:
        query += f" AND ts <= ${arg_counter}"
        args.append(end_ts)
        arg_counter += 1
    
    query += f" ORDER BY ts ASC LIMIT ${arg_counter}"
    args.append(limit)

    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch(query, *args)

    series = [{"ts": r["ts"].isoformat(), "value": r["value"]} for r in rows]
    return {"station_id": station_id, "param": param, "series": series}