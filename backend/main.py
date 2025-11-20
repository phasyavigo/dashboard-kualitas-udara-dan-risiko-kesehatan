import os
import json
import asyncio
from datetime import datetime
    pgpassword: str = "airpass"
    redis_url: Optional[str] = "redis://localhost:6379"
    cache_ttl: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

# --- 2. APP INITIALIZATION ---
app = FastAPI(title="Air Quality Dashboard API")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Connection Pools
DB_POOL: Optional[asyncpg.pool.Pool] = None
REDIS_CLIENT = None

# --- 3. EVENTS (STARTUP & SHUTDOWN) ---
@app.on_event("startup")
async def startup():
    """Run on startup: Connect to DB & Redis"""
    global DB_POOL, REDIS_CLIENT
    
    # PostgreSQL Connection
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

    # Redis Connection
    if settings.redis_url:
        try:
            print(f"Connecting to Redis at {settings.redis_url}...")
            REDIS_CLIENT = redis_lib.from_url(settings.redis_url, decode_responses=True)
            await REDIS_CLIENT.ping()
            print("✅ Redis connected.")
        except Exception as e:
            print(f"⚠️ Redis connection warning: {e}")
            REDIS_CLIENT = None

@app.on_event("shutdown")
async def shutdown():
    """Run on shutdown: Close connections"""
    global DB_POOL, REDIS_CLIENT
    if DB_POOL:
        await DB_POOL.close()
        print("Database connection closed.")
    if REDIS_CLIENT:
        await REDIS_CLIENT.close()
        print("Redis connection closed.")

# --- 4. UTILITY FUNCTIONS ---
def station_row_to_feature(row: asyncpg.Record) -> Dict[str, Any]:
    """Convert DB row to GeoJSON Feature"""
    props = {
        "station_id": row["station_id"],
        "name": row["name"],
        "city": row["city"],
        "params": row["params"],
        "last_update": row["last_update"].isoformat() if row["last_update"] else None
    }
    geom = json.loads(row["geomjson"]) if row["geomjson"] else None
    return {"type": "Feature", "properties": props, "geometry": geom}

# --- 5. ENDPOINTS ---

@app.get("/health")
async def health():
    """Health check"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database not initialized")
    try:
        async with DB_POOL.acquire() as con:
            await con.execute('SELECT 1')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")
    
    redis_status = "disabled"
    if REDIS_CLIENT:
        try:
            await REDIS_CLIENT.ping()
            redis_status = "connected"
        except Exception:
            redis_status = "unreachable"
            
    return {"status": "ok", "database": "connected", "redis": redis_status}

@app.get("/stations.geojson")
async def stations_geojson(
    lat_min: Optional[float] = None, lon_min: Optional[float] = None,
    lat_max: Optional[float] = None, lon_max: Optional[float] = None,
    force_refresh: bool = False
):
    """Get stations as GeoJSON"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Check Redis Cache
    cache_key = f"stations:{lat_min}:{lon_min}:{lat_max}:{lon_max}"
    if REDIS_CLIENT and not force_refresh:
        cached_data = await REDIS_CLIENT.get(cache_key)
        if cached_data:
            return json.loads(cached_data)

    # Build Query
    query = "SELECT station_id, name, city, params, last_update, ST_AsGeoJSON(geom) AS geomjson FROM stations"
    args = []
    
    if None not in (lat_min, lon_min, lat_max, lon_max):
        query += " WHERE ST_X(geom) BETWEEN $1 AND $2 AND ST_Y(geom) BETWEEN $3 AND $4"
        args = [lon_min, lon_max, lat_min, lat_max]

    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch(query, *args)

    features = [station_row_to_feature(r) for r in rows]
    geojson_data = {"type": "FeatureCollection", "features": features}

    # Save to Cache
    if REDIS_CLIENT:
        await REDIS_CLIENT.set(cache_key, json.dumps(geojson_data), ex=settings.cache_ttl)

    return Response(content=json.dumps(geojson_data), media_type="application/geo+json")

@app.get("/latest/{station_id}")
async def latest_for_station(station_id: str):
    """Get latest observations for a station"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with DB_POOL.acquire() as conn:
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
    limit: int = Query(1000, gt=0, le=10000)
):
    """Get historical data"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    start_ts = None
    end_ts = None
    try:
        if start: start_ts = datetime.fromisoformat(start)
        if end: end_ts = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Start/End must be ISO datetime strings")

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
import json
from typing import Any, Dict, Optional
from datetime import datetime

import asyncpg
import redis.asyncio as redis_lib
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings, SettingsConfigDict

import numpy as np
from scipy.interpolate import griddata


# --- 1. CONFIGURATION ---
class Settings(BaseSettings):
    pghost: str = "localhost"
    pgport: int = 5432
    pguser: str = "user"
    pgpassword: str = "password"
    pgdatabase: str = "airquality"

    redis_url: Optional[str] = None
    cache_ttl: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

# --- 2. APP INITIALIZATION ---
app = FastAPI(title="Air Quality Dashboard API")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Connection Pools
DB_POOL: Optional[asyncpg.pool.Pool] = None
REDIS_CLIENT = None

# --- 3. EVENTS (STARTUP & SHUTDOWN) ---
@app.on_event("startup")
async def startup():
    """Run on startup: Connect to DB & Redis"""
    global DB_POOL, REDIS_CLIENT
    
    # PostgreSQL Connection
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

    # Redis Connection
    if settings.redis_url:
        try:
            print(f"Connecting to Redis at {settings.redis_url}...")
            REDIS_CLIENT = redis_lib.from_url(settings.redis_url, decode_responses=True)
            await REDIS_CLIENT.ping()
            print("✅ Redis connected.")
        except Exception as e:
            print(f"⚠️ Redis connection warning: {e}")
            REDIS_CLIENT = None

@app.on_event("shutdown")
async def shutdown():
    """Run on shutdown: Close connections"""
    global DB_POOL, REDIS_CLIENT
    if DB_POOL:
        await DB_POOL.close()
        print("Database connection closed.")
    if REDIS_CLIENT:
        await REDIS_CLIENT.close()
        print("Redis connection closed.")

# --- 4. UTILITY FUNCTIONS ---
def station_row_to_feature(row: asyncpg.Record) -> Dict[str, Any]:
    """Convert DB row to GeoJSON Feature"""
    props = {
        "station_id": row["station_id"],
        "name": row["name"],
        "city": row["city"],
        "params": row["params"],
        "last_update": row["last_update"].isoformat() if row["last_update"] else None
    }
    geom = json.loads(row["geomjson"]) if row["geomjson"] else None
    return {"type": "Feature", "properties": props, "geometry": geom}

# --- 5. ENDPOINTS ---

@app.get("/health")
async def health():
    """Health check"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database not initialized")
    try:
        async with DB_POOL.acquire() as con:
            await con.execute('SELECT 1')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")
    
    redis_status = "disabled"
    if REDIS_CLIENT:
        try:
            await REDIS_CLIENT.ping()
            redis_status = "connected"
        except Exception:
            redis_status = "unreachable"
            
    return {"status": "ok", "database": "connected", "redis": redis_status}

@app.get("/stations.geojson")
async def stations_geojson(
    lat_min: Optional[float] = None, lon_min: Optional[float] = None,
    lat_max: Optional[float] = None, lon_max: Optional[float] = None,
    force_refresh: bool = False
):
    """Get stations as GeoJSON"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Check Redis Cache
    cache_key = f"stations:{lat_min}:{lon_min}:{lat_max}:{lon_max}"
    if REDIS_CLIENT and not force_refresh:
        cached_data = await REDIS_CLIENT.get(cache_key)
        if cached_data:
            return json.loads(cached_data)

    # Build Query
    query = "SELECT station_id, name, city, params, last_update, ST_AsGeoJSON(geom) AS geomjson FROM stations"
    args = []
    
    if None not in (lat_min, lon_min, lat_max, lon_max):
        query += " WHERE ST_X(geom) BETWEEN $1 AND $2 AND ST_Y(geom) BETWEEN $3 AND $4"
        args = [lon_min, lon_max, lat_min, lat_max]

    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch(query, *args)

    features = [station_row_to_feature(r) for r in rows]
    geojson_data = {"type": "FeatureCollection", "features": features}

    # Save to Cache
    if REDIS_CLIENT:
        await REDIS_CLIENT.set(cache_key, json.dumps(geojson_data), ex=settings.cache_ttl)

    return Response(content=json.dumps(geojson_data), media_type="application/geo+json")

@app.get("/latest/{station_id}")
async def latest_for_station(station_id: str):
    """Get latest observations for a station"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with DB_POOL.acquire() as conn:
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
    limit: int = Query(1000, gt=0, le=10000)
):
    """Get historical data"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    start_ts = None
    end_ts = None
    try:
        if start: start_ts = datetime.fromisoformat(start)
        if end: end_ts = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Start/End must be ISO datetime strings")

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

@app.get("/heatmap")
async def heatmap(
    param: str = "pm25",
    grid_size: int = 50  # Resolution of the grid (50x50)
):
    """Generate interpolated heatmap data (IDW)"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # 1. Fetch latest data for all stations
    query = """
        SELECT DISTINCT ON (s.station_id) 
            s.station_id, ST_X(s.geom) as lon, ST_Y(s.geom) as lat, o.value
        FROM stations s
        JOIN observations o ON s.station_id = o.station_id
        WHERE o.param = $1
        ORDER BY s.station_id, o.ts DESC
    """
    
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch(query, param)
    
    if len(rows) < 3:
        raise HTTPException(status_code=400, detail="Not enough data points for interpolation")

    # 2. Prepare data for interpolation
    points = np.array([(r["lon"], r["lat"]) for r in rows])
    values = np.array([r["value"] for r in rows])

    # 3. Create a grid
    # Indonesia approximate bounds (can be dynamic based on data)
    min_lon, min_lat = points.min(axis=0)
    max_lon, max_lat = points.max(axis=0)
    
    # Add some padding
    pad = 0.5
    grid_lon = np.linspace(min_lon - pad, max_lon + pad, grid_size)
    grid_lat = np.linspace(min_lat - pad, max_lat + pad, grid_size)
    grid_lon_mesh, grid_lat_mesh = np.meshgrid(grid_lon, grid_lat)

    # 4. Interpolate (using linear or cubic, or nearest)
    # 'linear' is good for triangulation, 'nearest' fills gaps but looks blocky
    # We use 'linear' and fill nans with nearest to cover the whole rect
    grid_z = griddata(points, values, (grid_lon_mesh, grid_lat_mesh), method='linear')
    
    # Fill NaN values (outside convex hull) with nearest neighbor to make it look fuller
    # or just leave them as None to only show data where we have coverage
    # For a nice heatmap, we often want to fill, but for accuracy, we shouldn't extrapolate too much.
    # Let's stick to linear for now.
    
    # 5. Convert to GeoJSON Points (or Polygons)
    # For Dash Leaflet, a heatmap layer usually takes points with intensity.
    # But if we want a "contour" map, we might need polygons.
    # Simplest for now: Return a list of weighted points for L.heatLayer
    
    heatmap_points = []
    for i in range(grid_size):
```python

# --- 4. UTILITY FUNCTIONS ---
def station_row_to_feature(row: asyncpg.Record) -> Dict[str, Any]:
    """Convert DB row to GeoJSON Feature"""
    props = {
        "station_id": row["station_id"],
        "name": row["name"],
        "city": row["city"],
        "params": row["params"],
        "last_update": row["last_update"].isoformat() if row["last_update"] else None
    }
    geom = json.loads(row["geomjson"]) if row["geomjson"] else None
    return {"type": "Feature", "properties": props, "geometry": geom}

# --- 5. ENDPOINTS ---

@app.get("/health")
async def health():
    """Health check"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database not initialized")
    try:
        async with DB_POOL.acquire() as con:
            await con.execute('SELECT 1')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")
    
    redis_status = "disabled"
    if REDIS_CLIENT:
        try:
            await REDIS_CLIENT.ping()
            redis_status = "connected"
        except Exception:
            redis_status = "unreachable"
            
    return {"status": "ok", "database": "connected", "redis": redis_status}

@app.get("/stations.geojson")
async def stations_geojson(
    lat_min: Optional[float] = None, lon_min: Optional[float] = None,
    lat_max: Optional[float] = None, lon_max: Optional[float] = None,
    force_refresh: bool = False
):
    """Get stations as GeoJSON"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Check Redis Cache
    cache_key = f"stations:{lat_min}:{lon_min}:{lat_max}:{lon_max}"
    if REDIS_CLIENT and not force_refresh:
        cached_data = await REDIS_CLIENT.get(cache_key)
        if cached_data:
            return json.loads(cached_data)

    # Build Query
    query = "SELECT station_id, name, city, params, last_update, ST_AsGeoJSON(geom) AS geomjson FROM stations"
    args = []
    
    if None not in (lat_min, lon_min, lat_max, lon_max):
        query += " WHERE ST_X(geom) BETWEEN $1 AND $2 AND ST_Y(geom) BETWEEN $3 AND $4"
        args = [lon_min, lon_max, lat_min, lat_max]

    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch(query, *args)

    features = [station_row_to_feature(r) for r in rows]
    geojson_data = {"type": "FeatureCollection", "features": features}

    # Save to Cache
    if REDIS_CLIENT:
        await REDIS_CLIENT.set(cache_key, json.dumps(geojson_data), ex=settings.cache_ttl)

    return Response(content=json.dumps(geojson_data), media_type="application/geo+json")

@app.get("/latest/{station_id}")
async def latest_for_station(station_id: str):
    """Get latest observations for a station"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with DB_POOL.acquire() as conn:
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
    limit: int = Query(1000, gt=0, le=10000)
):
    """Get historical data"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    start_ts = None
    end_ts = None
    try:
        if start: start_ts = datetime.fromisoformat(start)
        if end: end_ts = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Start/End must be ISO datetime strings")

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

@app.get("/heatmap")
async def heatmap(
    param: str = "pm25",
    grid_size: int = 50  # Resolution of the grid (50x50)
):
    """Generate interpolated heatmap data (IDW)"""
    if not DB_POOL:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # 1. Fetch latest data for all stations
    query = """
        SELECT DISTINCT ON (s.station_id) 
            s.station_id, ST_X(s.geom) as lon, ST_Y(s.geom) as lat, o.value
        FROM stations s
        JOIN observations o ON s.station_id = o.station_id
        WHERE o.param = $1
        ORDER BY s.station_id, o.ts DESC
    """
    
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch(query, param)
    
    if len(rows) < 3:
        raise HTTPException(status_code=400, detail="Not enough data points for interpolation")

    # 2. Prepare data for interpolation
    points = np.array([(r["lon"], r["lat"]) for r in rows])
    values = np.array([r["value"] for r in rows])

    # 3. Create a grid
    # Indonesia approximate bounds (can be dynamic based on data)
    min_lon, min_lat = points.min(axis=0)
    max_lon, max_lat = points.max(axis=0)
    
    # Add some padding
    pad = 0.5
    grid_lon = np.linspace(min_lon - pad, max_lon + pad, grid_size)
    grid_lat = np.linspace(min_lat - pad, max_lat + pad, grid_size)
    grid_lon_mesh, grid_lat_mesh = np.meshgrid(grid_lon, grid_lat)

    # 4. Interpolate (using linear or cubic, or nearest)
    # 'linear' is good for triangulation, 'nearest' fills gaps but looks blocky
    # We use 'linear' and fill nans with nearest to cover the whole rect
    grid_z = griddata(points, values, (grid_lon_mesh, grid_lat_mesh), method='linear')
    
    # Fill NaN values (outside convex hull) with nearest neighbor to make it look fuller
    # or just leave them as None to only show data where we have coverage
    # For a nice heatmap, we often want to fill, but for accuracy, we shouldn't extrapolate too much.
    # Let's stick to linear for now.
    
    # 5. Convert to GeoJSON Points (or Polygons)
    # For Dash Leaflet, a heatmap layer usually takes points with intensity.
    # But if we want a "contour" map, we might need polygons.
    # Simplest for now: Return a list of weighted points for L.heatLayer
    
    heatmap_points = []
    for i in range(grid_size):
        for j in range(grid_size):
            val = grid_z[i, j]
            if not np.isnan(val):
                heatmap_points.append([grid_lat[i], grid_lon[j], float(val)])
                
    return {"type": "heatmap", "data": heatmap_points}

@app.get("/health-risk/{pm25_value}")
async def health_risk(pm25_value: float):
    """Get health risk assessment based on PM2.5 value (WHO/US EPA standards)"""
    
    risk_level = ""
    color = ""
    advice = ""
    
    if pm25_value <= 12.0:
        risk_level = "Good"
        color = "#00e400" # Green
        advice = "Air quality is satisfactory, and air pollution poses little or no risk."
    elif pm25_value <= 35.4:
        risk_level = "Moderate"
        color = "#ffff00" # Yellow
        advice = "Air quality is acceptable. However, there may be a risk for some people, particularly those who are unusually sensitive to air pollution."
    elif pm25_value <= 55.4:
        risk_level = "Unhealthy for Sensitive Groups"
        color = "#ff7e00" # Orange
        advice = "Members of sensitive groups (children, elderly, people with heart/lung disease) may experience health effects. The general public is less likely to be affected."
    elif pm25_value <= 150.4:
        risk_level = "Unhealthy"
        color = "#ff0000" # Red
        advice = "Some members of the general public may experience health effects; members of sensitive groups may experience more serious health effects."
    elif pm25_value <= 250.4:
        risk_level = "Very Unhealthy"
        color = "#8f3f97" # Purple
        advice = "Health alert: The risk of health effects is increased for everyone."
    else:
        risk_level = "Hazardous"
        color = "#7e0023" # Maroon
        advice = "Health warning of emergency conditions: everyone is more likely to be affected."

    return {
        "pm25": pm25_value,
        "level": risk_level,
        "color": color,
        "advice": advice
    }
```