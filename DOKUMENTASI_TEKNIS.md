# PERANCANGAN ARSITEKTUR & IMPLEMENTASI PIPELINE
## Dashboard Kualitas Udara dan Risiko Kesehatan Indonesia

**FAKULTAS ILMU KOMPUTER**  
**UNIVERSITAS BRAWIJAYA**

---

## BAB 1 Diagram Arsitektur Pipeline Lengkap

### 1.1 Arsitektur Microservices

Sistem dashboard kualitas udara ini dibangun menggunakan arsitektur microservices yang terdiri dari 5 komponen utama yang saling berinteraksi. Pendekatan microservices dipilih untuk memastikan *scalability*, *maintainability*, dan kemudahan dalam pengembangan secara modular.

```
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│                  │         │                  │         │                  │
│    Dashboard     │────────▶│     Backend      │────────▶│   PostgreSQL     │
│   (Dash/Plotly)  │  HTTP   │    (FastAPI)     │   SQL   │   + PostGIS      │
│                  │         │                  │         │                  │
└──────────────────┘         └──────────────────┘         └──────────────────┘
                                      │                            ▲
                                      │                            │
                                      ▼                            │
                             ┌──────────────────┐         ┌────────────────┐
                             │                  │         │                │
                             │      Redis       │         │     Worker     │
                             │   (Caching)      │         │  (Scheduler)   │
                             │                  │         │                │
                             └──────────────────┘         └────────────────┘
                                                                   │
                                                                   ▼
                                                          ┌─────────────────┐
                                                          │   AQICN API     │
                                                          │ (Data Source)   │
                                                          └─────────────────┘
```

### 1.2 Komponen Sistem dan Peran

#### 1.2.1 PostgreSQL + PostGIS (Port 5432)

PostgreSQL berfungsi sebagai database utama sistem dengan ekstensi PostGIS untuk menangani data geospasial. Database ini menyimpan dua tabel utama:

- **stations**: Menyimpan metadata stasiun monitoring (lokasi geografis, nama, kota)
- **observations**: Menyimpan time-series data pengukuran kualitas udara (PM2.5, PM10, NO2, SO2, CO, O3, AQI)

PostGIS memungkinkan query spatial seperti:
- Pencarian stasiun berdasarkan radius geografis
- Interpolasi spatial untuk heatmap
- Indexing geografis menggunakan GIST untuk performa optimal

#### 1.2.2 Redis (Port 6379)

Redis berfungsi sebagai in-memory cache untuk:
- Caching response API dari backend (TTL: 30 detik default)
- Mengurangi load ke database untuk query yang sering diakses
- Mempercepat response time dashboard dengan caching GeoJSON

Penggunaan Redis sangat penting karena query agregasi spasial ke database cukup intensif, terutama untuk fitur heatmap interpolasi.

#### 1.2.3 Backend API (FastAPI - Port 8000)

Backend API dibangun menggunakan FastAPI dengan fitur:
- **Async/Await**: Menggunakan asyncpg untuk non-blocking database operations
- **Auto-documentation**: Swagger UI tersedia di `/docs`
- **CORS enabled**: Memungkinkan akses dari dashboard frontend

Endpoints utama yang disediakan:
- `GET /stations.geojson`: GeoJSON semua stasiun dengan data terkini
- `GET /timeseries/{station_id}/{param}`: Historical data time-series
- `GET /heatmap`: Spatial interpolation untuk visualisasi heatmap
- `GET /health_risk`: Health risk assessment berdasarkan PM2.5
- `GET /summary`: KPI aggregation untuk dashboard metrics

#### 1.2.4 Dashboard (Dash - Port 8050)

Dashboard frontend dibangun menggunakan Plotly Dash, menyediakan:
- **Interactive Map**: Scattermapbox dengan marker stations
- **Real-time KPIs**: Total stations, high risk areas, average PM2.5
- **Time Series Graphs**: Tren PM2.5 7 hari terakhir
- **Forecast Visualization**: Prediksi 5 hari ke depan
- **Data Tables**: Sortable dan filterable station list
- **Analytics Tab**: Histogram AQI distribution, pie chart categories

UI menggunakan dark theme dengan glassmorphism design untuk modern aesthetics.

#### 1.2.5 Worker Scheduler

Worker bertugas melakukan periodic data ingestion dari AQICN API dengan schedule:
- **Hourly**: Fetch observations dari semua stasiun (via `fetch_observations_and_insert.py`)
- **On Startup**: Database initialization dan initial population (`init_db.py`)

Worker menggunakan library `schedule` untuk cron-like scheduling.

### 1.3 Container Orchestration

Semua komponen di-orkestrasi menggunakan Docker Compose dengan definisi sebagai berikut:

```yaml
services:
  postgres:
    image: postgis/postgis:15-3.3
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]
  
  redis:
    image: redis:7
    ports: ["6379:6379"]
  
  backend:
    build: ./backend
    depends_on: [postgres, redis]
    ports: ["8000:8000"]
  
  dashboard:
    build: ./dashboard
    depends_on: [backend]
    ports: ["8050:8050"]
  
  worker:
    build: ./worker
    command: python scheduler.py
    depends_on: [postgres, redis]
```

Dependency graph memastikan services start dalam urutan yang benar:
1. PostgreSQL dan Redis (foundational layer)
2. Backend API (bergantung pada database dan cache)
3. Dashboard dan Worker (bergantung pada backend/database)

---

## BAB 2 Flow Data (Ingest → Transform → Store → Analyze)

### 2.1 Data Ingestion Layer

#### 2.1.1 Source: AQICN API

Data kualitas udara bersumber dari AQICN (Air Quality Index China Network) melalui REST API publik. AQICN menyediakan data real-time dari ribuan stasiun monitoring di seluruh dunia, termasuk Indonesia.

API endpoint yang digunakan:
```
https://api.waqi.info/feed/@{uid}/?token={TOKEN}
```

Parameter yang diambil:
- **IAQI** (Individual Air Quality Index): pm25, pm10, o3, no2, so2, co
- **AQI**: Overall Air Quality Index
- **Forecast**: Prediksi 5 hari ke depan
- **Metadata**: Station name, city, coordinates, timestamp

#### 2.1.2 Fetch Process

Worker menjalankan script `fetch_observations_and_insert.py` yang melakukan:

1. **Load Station List**: Query database untuk mendapatkan semua stasiun terdaftar
2. **Iterate Stations**: Untuk setiap stasiun, fetch data dari AQICN API
3. **Rate Limiting**: Sleep 0.5 detik antar request untuk menghindari rate limit
4. **Retry Logic**: HTTP retry dengan exponential backoff (max 3 attempts)
5. **Fallback Strategy**: 
   - Coba fetch by UID terlebih dahulu
   - Jika gagal, fallback ke geo-coordinates

Kode snippet untuk fetch detail:

```python
def fetch_detail(uid, lat, lon):
    url_uid = f"https://api.waqi.info/feed/@{uid}/?token={TOKEN}"
    try:
        r = http.get(url_uid, timeout=20)
        if r.status_code == 200 and r.json().get("status") == "ok":
            return r.json()["data"]
    except Exception as e:
        print(f"Error fetching UID {uid}: {e}")
    
    # Fallback geo
    url_geo = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={TOKEN}"
    r = http.get(url_geo, timeout=20)
    return r.json()["data"] if r.json().get("status") == "ok" else None
```

### 2.2 Data Transformation Layer

#### 2.2.1 Sanitization

Data mentah dari API mengalami proses sanitasi untuk menangani edge cases:

**NaN/Inf Handling**: Nilai float yang invalid (NaN, Infinity) di-set menjadi `None`

```python
def sanitize_data(data):
    if isinstance(data, dict):
        return {k: sanitize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_data(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
    return data
```

#### 2.2.2 Enrichment from Forecast

Jika IAQI untuk polutan tertentu (pm25, pm10) tidak tersedia di response real-time, sistem melakukan enrichment dari data forecast:

```python
def enrich_with_forecast(data, iaqi):
    forecast = data.get("forecast", {}).get("daily", {})
    if not forecast:
        return iaqi
    
    date_str = data.get("time", {}).get("iso", "").split("T")[0]
    
    for pollutant in ["pm25", "pm10", "o3", "uvi"]:
        if pollutant not in iaqi and pollutant in forecast:
            daily_data = forecast[pollutant]
            today_entry = next((item for item in daily_data 
                               if item.get("day") == date_str), None)
            if today_entry:
                iaqi[pollutant] = {"v": today_entry["avg"], 
                                  "from_forecast": True}
    return iaqi
```

Strategi enrichment ini memastikan coverage data yang lebih baik, terutama untuk stasiun yang memiliki incomplete real-time measurements.

#### 2.2.3 AQI Category Mapping

Backend API menerapkan kategori AQI berdasarkan PM2.5 dan AQI value sesuai standar WHO dan US EPA:

```python
def get_category(aqi_val, pm25_val):
    if pm25_val <= 15.4:
        return "Good"
    elif pm25_val <= 55.4:
        return "Moderate"
    elif pm25_val <= 150.4:
        return "Unhealthy"
    else:
        return "Hazardous"
```

Categories:
- **Good** (0-50 AQI / 0-15.4 µg/m³ PM2.5): Hijau
- **Moderate** (51-100 AQI / 15.5-55.4 µg/m³): Kuning
- **Unhealthy** (101-150 AQI / 55.5-150.4 µg/m³): Merah
- **Hazardous** (>150 AQI / >150.4 µg/m³): Ungu

### 2.3 Data Storage Layer

#### 2.3.1 Database Schema

**Table: stations**

```sql
CREATE TABLE stations (
    station_id VARCHAR(255) PRIMARY KEY,
    uid INT,
    name TEXT,
    city TEXT,
    params JSONB,                          -- Latest IAQI parameters
    last_update TIMESTAMP,
    geom GEOMETRY(Point, 4326),            -- PostGIS geometry
    geomjson TEXT
);

CREATE INDEX idx_stations_geom ON stations USING GIST (geom);
```

**Table: observations**

```sql
CREATE TABLE observations (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(255) REFERENCES stations(station_id),
    ts TIMESTAMP,
    param VARCHAR(50),                      -- pm25, pm10, no2, etc.
    value FLOAT,
    unit VARCHAR(50),
    raw_json JSONB,                         -- Full API response
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(station_id, ts, param)
);

CREATE INDEX idx_obs_station_ts ON observations (station_id, ts);
```

#### 2.3.2 Insert Logic

Observations di-insert dengan konfliks handling untuk menghindari duplikasi:

```python
cur.execute("""
    INSERT INTO observations (station_id, ts, param, value, unit, raw_json)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (station_id, ts, param) DO NOTHING
""", (station_id, ts, param, value, unit, Json(raw)))
```

Constraint `UNIQUE(station_id, ts, param)` memastikan tidak ada duplikasi data untuk kombinasi stasiun-waktu-parameter yang sama.

#### 2.3.3 Station Metadata Update

Setiap kali observations di-insert, metadata stasiun di-update dengan latest parameters:

```python
cur.execute("""
    UPDATE stations 
    SET params = %s::jsonb, last_update = %s 
    WHERE station_id = %s
""", (json.dumps(iaqi), ts, station_id))
```

Ini memungkinkan dashboard untuk langsung query latest values tanpa perlu join ke tabel observations.

### 2.4 Data Analysis & Serving Layer

#### 2.4.1 GeoJSON Aggregation

Endpoint `/stations.geojson` melakukan agregasi data untuk semua stasiun:

1. Query stasiun dari database dengan latest params dari field `params` (JSONB)
2. Extract PM2.5 dan AQI dari params
3. Calculate category berdasarkan nilai
4. Build GeoJSON FeatureCollection dengan properties enriched

```python
async def stations_geojson():
    cache_key = "stations:geojson"
    
    # Try cache first
    if not force_refresh and REDIS_CLIENT:
        cached = await REDIS_CLIENT.get(cache_key)
        if cached:
            return json.loads(cached)
    
    # Query database
    rows = await DB_POOL.fetch("""
        SELECT station_id, uid, name, city, params, 
               ST_AsGeoJSON(geom) as geojson
        FROM stations
        WHERE geom IS NOT NULL
    """)
    
    # Build GeoJSON features
    features = []
    for row in rows:
        params = row["params"] or {}
        pm25 = params.get("pm25", {}).get("v", 0)
        aqi = params.get("aqi", {}).get("v", 0) if "aqi" in params else 0
        
        category = get_category(aqi, pm25)
        
        features.append({
            "type": "Feature",
            "geometry": json.loads(row["geojson"]),
            "properties": {
                "station_id": row["station_id"],
                "name": row["name"],
                "city": row["city"],
                "pm25": pm25,
                "aqi": aqi,
                "category": category
            }
        })
    
    geojson = {"type": "FeatureCollection", "features": features}
    
    # Cache result
    if REDIS_CLIENT:
        await REDIS_CLIENT.setex(cache_key, settings.cache_ttl, 
                                 json.dumps(geojson))
    
    return geojson
```

Response di-cache di Redis dengan TTL 30 detik untuk mengurangi database load.

#### 2.4.2 Time Series Query

Endpoint `/timeseries/{station_id}/{param}` menyediakan historical data:

```python
async def timeseries(station_id: str, param: str, limit: int = 1000):
    rows = await DB_POOL.fetch("""
        SELECT ts, value, unit 
        FROM observations
        WHERE station_id = $1 AND param = $2
        ORDER BY ts DESC
        LIMIT $3
    """, station_id, param, limit)
    
    series = [{"ts": r["ts"].isoformat(), 
               "value": r["value"], 
               "unit": r["unit"]} for r in rows]
    
    return {"station_id": station_id, "param": param, "series": series}
```

#### 2.4.3 Spatial Interpolation (Heatmap)

Endpoint `/heatmap` melakukan Inverse Distance Weighting (IDW) interpolation untuk membuat heatmap continuous:

```python
async def heatmap(param: str = "pm25", grid_size: int = 50):
    # Fetch all stations with latest value
    rows = await DB_POOL.fetch("""
        SELECT ST_Y(geom) as lat, ST_X(geom) as lon, params
        FROM stations WHERE params IS NOT NULL
    """)
    
    # Extract coordinates and values
    points = []
    values = []
    for r in rows:
        params = r["params"]
        if param in params:
            points.append([r["lon"], r["lat"]])
            values.append(params[param]["v"])
    
    # Create grid
    lon_min, lon_max = min(p[0] for p in points), max(p[0] for p in points)
    lat_min, lat_max = min(p[1] for p in points), max(p[1] for p in points)
    
    grid_lon = np.linspace(lon_min, lon_max, grid_size)
    grid_lat = np.linspace(lat_min, lat_max, grid_size)
    grid_x, grid_y = np.meshgrid(grid_lon, grid_lat)
    
    # Interpolate using scipy griddata (IDW-like)
    grid_z = griddata(points, values, (grid_x, grid_y), method='linear')
    
    return {
        "grid_lon": grid_lon.tolist(),
        "grid_lat": grid_lat.tolist(),
        "grid_values": grid_z.tolist(),
        "param": param
    }
```

Interpolasi spatial ini memungkinkan visualisasi kontinu kualitas udara di area tanpa stasiun monitoring.

---

## BAB 3 Pemilihan Tools + Justifikasi

### 3.1 Database: PostgreSQL + PostGIS

**Alasan Pemilihan:**

1. **Relational Integrity**: PostgreSQL menyediakan ACID compliance untuk konsistensi data
2. **JSON Support**: Native JSONB type untuk menyimpan flexible schema (params field)
3. **Spatial Extensions**: PostGIS memungkinkan query geografis kompleks
4. **Performance**: Indexing capabilities (B-tree, GIST) untuk query optimization
5. **Open Source**: Free dan community-driven dengan dokumentasi lengkap

**Alternatif yang Dipertimbangkan:**
- **MongoDB**: Ditolak karena kurangnya dukungan spatial query yang mature
- **MySQL**: Ditolak karena spatial support tidak se-robust PostGIS
- **TimescaleDB**: Overengineered untuk skala data saat ini (cocok untuk IoT scale)

### 3.2 Cache: Redis

**Alasan Pemilihan:**

1. **In-Memory Performance**: Sub-millisecond latency untuk cache hits
2. **TTL Support**: Built-in expiration untuk cache invalidation
3. **Simplicity**: Simple key-value store tanpa overhead schema
4. **Async Support**: Kompatibel dengan asyncio Python ecosystem

**Alternatif yang Dipertimbangkan:**
- **Memcached**: Ditolak karena kurang fitur (no persistence, no TTL per-key)
- **Application-level cache (LRU)**: Ditolak karena tidak shared antar containers

### 3.3 Backend Framework: FastAPI

**Alasan Pemilihan:**

1. **Performance**: ASGI-based, async/await native support
2. **Type Safety**: Pydantic models untuk request/response validation
3. **Auto Documentation**: OpenAPI (Swagger) UI out-of-the-box
4. **Modern Python**: Menggunakan Python 3.11+ features (type hints)
5. **Developer Experience**: Fast development dengan minimal boilerplate

**Alternatif yang Dipertimbangkan:**
- **Flask**: Ditolak karena tidak async-native (WSGI-based)
- **Django REST Framework**: Overengineered, ORM overhead tidak diperlukan
- **Node.js/Express**: Ditolak untuk konsistensi stack (full Python)

### 3.4 Dashboard Framework: Plotly Dash

**Alasan Pemilihan:**

1. **Declarative UI**: React.js-based tanpa perlu menulis JavaScript
2. **Plotly Integration**: Built-in support untuk interactive charts
3. **Callback System**: Reactive programming model untuk interactivity
4. **Python-Native**: Full Python stack untuk frontend dan backend
5. **Rapid Prototyping**: Cocok untuk data science visualization

**Alternatif yang Dipertimbangkan:**
- **Streamlit**: Ditolak karena kurang kontrol atas layout dan state management
- **React + Plotly.js**: Ditolak karena memerlukan JavaScript expertise
- **Tableau/Power BI**: Ditolak karena proprietary dan kurang customizable

### 3.5 Task Scheduling: Python Schedule

**Alasan Pemilihan:**

1. **Simplicity**: Human-readable syntax (`schedule.every(1).hours.do()`)
2. **Lightweight**: Minimal dependencies
3. **Sufficient for Use Case**: Hourly schedule tidak memerlukan cron complexity

**Alternatif yang Dipertimbangkan:**
- **Celery**: Overengineered untuk task sederhana, memerlukan message broker
- **APScheduler**: Lebih kompleks tanpa benefit signifikan untuk use case ini
- **Cron**: Ditolak karena kurang portable dan harder untuk containerization

### 3.6 Containerization: Docker + Docker Compose

**Alasan Pemilihan:**

1. **Environment Consistency**: Consistent environments across dev/prod
2. **Dependency Isolation**: Setiap service memiliki dependencies terisolasi
3. **Easy Deployment**: Single command deployment (`docker-compose up`)
4. **Service Orchestration**: Built-in service dependencies dan networking

**Alternatif yang Dipertimbangkan:**
- **Kubernetes**: Overkill untuk deployment single-server
- **Virtual Machines**: Resource overhead terlalu besar
- **Bare Metal**: Dependency hell dan environment inconsistency

---

## BAB 4 Implementasi ETL/Stream Processor Awal

### 4.1 Extract: Data Acquisition

#### 4.1.1 Station Bootstrap

Proses awal dimulai dengan populasi tabel `stations` dari file `stations_indonesia.json`:

```python
def populate_stations():
    with open('stations_indonesia.json', 'r', encoding='utf-8') as f:
        stations = json.load(f)
    
    conn = get_connection()
    cur = conn.cursor()
    
    for s in stations:
        uid = s.get("uid")
        name = s.get("name")
        city = s.get("city")
        lat = s.get("lat")
        lon = s.get("lon")
        station_id = str(uid)
        
        cur.execute("""
            INSERT INTO stations (station_id, uid, name, city, geom, geomjson)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)
            ON CONFLICT (station_id) DO UPDATE SET
                name = EXCLUDED.name,
                city = EXCLUDED.city,
                geom = EXCLUDED.geom
        """, (station_id, uid, name, city, lon, lat,
              json.dumps({"type": "Point", "coordinates": [lon, lat]})))
    
    conn.commit()
```

File JSON ini dihasilkan dari API search AQICN:
```
GET https://api.waqi.info/search/?keyword=indonesia&token={TOKEN}
```

#### 4.1.2 Observation Fetching

Worker scheduler menjalankan `fetch_observations_and_insert.py` setiap jam:

**Workflow:**
1. Query semua stasiun dari database
2. Untuk setiap stasiun:
   - Fetch data dari AQICN API (dengan retry logic)
   - Extract IAQI parameters (pm25, pm10, o3, no2, so2, co)
   - Extract AQI dan dominant pollutant
   - Enrich dengan forecast jika data incomplete
3. Insert observations ke database (dengan conflict handling)
4. Update station metadata dengan latest params

**Error Handling:**
- HTTP timeout: 20 detik
- Retry strategy: 3 attempts dengan backoff factor 1s
- Fallback ke geo-coordinate jika UID fetch gagal
- Skip station jika tidak ada data tersedia

### 4.2 Transform: Data Processing

#### 4.2.1 Schema Normalization

Data API dalam bentuk nested JSON di-flatten menjadi relational rows:

**Input (API Response):**
```json
{
  "aqi": 85,
  "time": {"iso": "2025-11-22T12:00:00+07:00"},
  "iaqi": {
    "pm25": {"v": 45.2},
    "pm10": {"v": 78.0},
    "no2": {"v": 12.5}
  }
}
```

**Output (Database Rows):**
```sql
INSERT INTO observations VALUES
  ('station_123', '2025-11-22 12:00:00', 'pm25', 45.2, 'µg/m³', {...}),
  ('station_123', '2025-11-22 12:00:00', 'pm10', 78.0, 'µg/m³', {...}),
  ('station_123', '2025-11-22 12:00:00', 'no2', 12.5, 'µg/m³', {...}),
  ('station_123', '2025-11-22 12:00:00', 'aqi', 85, NULL, {...});
```

#### 4.2.2 Value Validation

Sebelum insert, values divalidasi:

```python
# Remove NaN/Inf values
iaqi = sanitize_data(iaqi)

# Validate AQI is numeric
try:
    aqi_float = float(aqi_value)
except ValueError:
    print(f"Skipping invalid AQI: {aqi_value}")
```

### 4.3 Load: Database Insertion

#### 4.3.1 Batch Processing

Meskipun saat ini insert dilakukan per-station secara sequential, struktur PostgreSQL connection pooling memungkinkan future optimization dengan batch inserts menggunakan `psycopg2.extras.execute_batch()`.

#### 4.3.2 Upsert Strategy

Menggunakan PostgreSQL `ON CONFLICT` clause:

```python
cur.execute("""
    INSERT INTO observations (station_id, ts, param, value, unit, raw_json)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (station_id, ts, param) DO NOTHING
""", (station_id, ts, param, value, unit, Json(raw)))
```

Strategi `DO NOTHING` dipilih karena:
- Data dari API bersifat immutable (historical records)
- Tidak ada update pattern, hanya insert new observations
- Menghindari duplicate constraint violations saat re-run

### 4.4 Scheduling & Automation

#### 4.4.1 Scheduler Implementation

```python
import schedule
import subprocess

def run_ingestion():
    print(f"[{datetime.now()}] Starting data ingestion...")
    subprocess.run(["python", "fetch_observations_and_insert.py"], check=True)
    print(f"[{datetime.now()}] Ingestion completed.")

# Schedule hourly
schedule.every(1).hours.do(run_ingestion)

# Run immediately on startup
subprocess.run(["python", "init_db.py"], check=True)
run_ingestion()

# Main loop
while True:
    schedule.run_pending()
    time.sleep(60)
```

#### 4.4.2 Containerized Scheduling

Worker container menggunakan command override di docker-compose:

```yaml
worker:
  build: ./worker
  command: python scheduler.py
  restart: unless-stopped
```

Dengan `restart: unless-stopped`, scheduler akan auto-restart jika crash, memastikan data ingestion tetap berjalan.

### 4.5 Data Flow Summary Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         ETL Pipeline                         │
└─────────────────────────────────────────────────────────────┘

EXTRACT                 TRANSFORM                LOAD
─────────               ─────────                ────

[AQICN API]             [Sanitize]              [PostgreSQL]
     │                       │                        │
     │ HTTP GET              │ Remove NaN/Inf         │ INSERT
     │                       │                        │
     ▼                       ▼                        ▼
[JSON Response] ───────▶ [Enrich] ──────────▶ [observations]
     │                       │                        │
     │                       │ Forecast Fill          │ UPDATE
     │                       │                        │
     │                       ▼                        ▼
     │                  [Normalize]             [stations.params]
     │                       │
     │                       │ Flatten JSON
     │                       │
     └───────────────────────┴────────────────────────┘

Schedule: Every 1 hour (via Python schedule)
Retry: 3 attempts with backoff
Rate Limit: 0.5s delay between stations
```

---

## BAB 5 Struktur Database/Data Warehouse

### 5.1 Database Schema Design

#### 5.1.1 Entity Relationship

```
┌─────────────────────────────────────┐
│            stations                 │
├─────────────────────────────────────┤
│ PK  station_id   VARCHAR(255)       │
│     uid          INT                │
│     name         TEXT               │
│     city         TEXT               │
│     params       JSONB              │
│     last_update  TIMESTAMP          │
│     geom         GEOMETRY(Point)    │  ◄─── PostGIS type
│     geomjson     TEXT               │
└─────────────────────────────────────┘
              │
              │ 1
              │
              │ *
              ▼
┌─────────────────────────────────────┐
│          observations               │
├─────────────────────────────────────┤
│ PK  id           SERIAL             │
│ FK  station_id   VARCHAR(255)       │
│     ts           TIMESTAMP          │
│     param        VARCHAR(50)        │
│     value        FLOAT              │
│     unit         VARCHAR(50)        │
│     raw_json     JSONB              │
│     created_at   TIMESTAMP          │
├─────────────────────────────────────┤
│ UNIQUE (station_id, ts, param)      │
└─────────────────────────────────────┘
```

**Relationship**: One-to-Many (1 station → N observations)

#### 5.1.2 Table: stations

**Purpose**: Master data untuk stasiun monitoring geografis

**Fields:**
- `station_id` (PK): Unique identifier (biasanya sama dengan UID)
- `uid`: AQICN station UID untuk API reference
- `name`: Nama stasiun (e.g., "Jakarta Central")
- `city`: Kota lokasi stasiun
- `params` (JSONB): Latest parameters dalam format `{"pm25": {"v": 45.2}, ...}`
- `last_update`: Timestamp update terakhir
- `geom` (GEOMETRY): Koordinat geografis dalam format PostGIS Point
- `geomjson`: GeoJSON representation untuk backward compatibility

**Indexes:**
```sql
CREATE INDEX idx_stations_geom ON stations USING GIST (geom);
```

GIST index memungkinkan spatial queries seperti:
```sql
-- Find stations within bounding box
SELECT * FROM stations 
WHERE geom && ST_MakeEnvelope(lon_min, lat_min, lon_max, lat_max, 4326);

-- Find nearest stations
SELECT * FROM stations 
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(lon, lat), 4326) 
LIMIT 10;
```

#### 5.1.3 Table: observations

**Purpose**: Time-series data pengukuran kualitas udara

**Fields:**
- `id` (PK): Auto-increment primary key
- `station_id` (FK): Reference ke stations table
- `ts`: Timestamp pengukuran (dari API)
- `param`: Nama parameter (pm25, pm10, no2, so2, co, o3, aqi)
- `value`: Nilai numerik pengukuran
- `unit`: Unit pengukuran (µg/m³, ppb, etc.)
- `raw_json` (JSONB): Complete API response untuk auditability
- `created_at`: Timestamp insert ke database (for ETL tracking)

**Constraints:**
```sql
UNIQUE (station_id, ts, param)
```

Constraint ini mencegah duplikasi data untuk kombinasi station-time-parameter yang sama.

**Indexes:**
```sql
CREATE INDEX idx_obs_station_ts ON observations (station_id, ts);
```

Composite index untuk optimasi time-series queries:
```sql
SELECT * FROM observations 
WHERE station_id = 'station_123' 
  AND ts BETWEEN '2025-11-01' AND '2025-11-22'
ORDER BY ts DESC;
```

### 5.2 Data Types Rationale

#### 5.2.1 JSONB vs JSON

**Pilihan: JSONB**

JSONB (Binary JSON) dipilih untuk field `params` dan `raw_json` karena:
- **Performance**: Binary format lebih cepat untuk query dan indexing
- **Indexing**: Support GIN index untuk query nested fields
- **Compression**: Lebih efisien storage dibanding text JSON

**Trade-off:**
- Insert slightly slower (karena binary conversion)
- Lebih cocok untuk read-heavy workloads (sesuai use case dashboard)

#### 5.2.2 GEOMETRY vs GEOGRAPHY

**Pilihan: GEOMETRY(Point, 4326)**

- SRID 4326 = WGS 84 (standard GPS coordinates)
- GEOMETRY lebih performa untuk planar calculations
- GEOGRAPHY cocok untuk spherical earth calculations (tidak diperlukan untuk scale Indonesia)

#### 5.2.3 TIMESTAMP vs TIMESTAMPTZ

**Pilihan: TIMESTAMP (without timezone)**

Data dari API sudah dalam ISO format dengan timezone info, disimpan sebagai UTC:
```python
ts = data["time"]["iso"]  # "2025-11-22T12:00:00+07:00"
```

PostgreSQL akan convert ke UTC saat insert jika menggunakan TIMESTAMPTZ.

### 5.3 Query Patterns & Optimization

#### 5.3.1 Latest Values Query

**Challenge**: Mendapatkan latest value untuk setiap parameter per stasiun

**Solution 1: Denormalization** (Current approach)
Simpan latest values di `stations.params` (JSONB field):

```sql
SELECT station_id, params->>'pm25' as pm25
FROM stations;
```

**Advantages:**
- Single table scan
- No JOIN required
- Fast for dashboard queries

**Disadvantages:**
- Data redundancy
- Requires UPDATE on every observation insert

**Solution 2: Window Functions** (Alternative)
```sql
SELECT DISTINCT ON (station_id, param) 
    station_id, param, value, ts
FROM observations
ORDER BY station_id, param, ts DESC;
```

**Trade-off**: Slower query but no denormalization overhead.

#### 5.3.2 Aggregation Queries

**Use Case**: Dashboard KPIs (avg PM2.5, max AQI, etc.)

```sql
-- Average PM2.5 nationwide
SELECT AVG((params->'pm25'->>'v')::float) as avg_pm25
FROM stations
WHERE params->'pm25' IS NOT NULL;

-- Count high-risk stations
SELECT COUNT(*) 
FROM stations
WHERE (params->'aqi'->>'v')::float > 100;

-- Top 5 worst stations
SELECT name, city, (params->'aqi'->>'v')::float as aqi
FROM stations
WHERE params->'aqi' IS NOT NULL
ORDER BY (params->'aqi'->>'v')::float DESC
LIMIT 5;
```

**Optimization**: Create functional index on JSONB fields:
```sql
CREATE INDEX idx_stations_pm25 
ON stations (((params->'pm25'->>'v')::float));
```

#### 5.3.3 Time-Series Queries

**Use Case**: Chart time-series PM2.5 untuk 7 hari terakhir

```sql
SELECT ts, value
FROM observations
WHERE station_id = $1 
  AND param = 'pm25'
  AND ts >= NOW() - INTERVAL '7 days'
ORDER BY ts ASC;
```

**Optimization**: Composite index `idx_obs_station_ts` memungkinkan index-only scan.

### 5.4 Data Retention & Archival Strategy

#### 5.4.1 Current State

Saat ini tidak ada retention policy (unlimited storage).

#### 5.4.2 Future Recommendations

**Short-term (Hot Data):** 30 hari terakhir di main table
**Long-term (Warm Data):** 1 tahun terakhir di partitioned table
**Archive (Cold Data):** >1 tahun di compressed archive (parquet/s3)

**Implementation dengan Partitioning:**
```sql
CREATE TABLE observations_2025_11 PARTITION OF observations
FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');

CREATE TABLE observations_2025_12 PARTITION OF observations
FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
```

**Benefits:**
- Faster queries (partition pruning)
- Easy archival (detach old partitions)
- Better maintenance (vacuum per partition)

### 5.5 Backup & Recovery Strategy

#### 5.5.1 Database Backup

**Current:** Docker volume persistence (`postgres_data`)

**Recommended:**
```bash
# Daily backup with pg_dump
docker exec postgres pg_dump -U air airdb > backup_$(date +%Y%m%d).sql

# Point-in-time recovery with WAL archiving
# postgresql.conf:
wal_level = replica
archive_mode = on
archive_command = 'cp %p /archive/%f'
```

#### 5.5.2 Disaster Recovery

**RTO** (Recovery Time Objective): < 1 hour
**RPO** (Recovery Point Objective): < 1 hour (data loss acceptable karena hourly refresh)

**Recovery Steps:**
1. Stop all services (`docker-compose down`)
2. Restore PostgreSQL volume dari backup
3. Restart services (`docker-compose up -d`)
4. Worker akan auto-populate missing data dari AQICN API

---

## BAB 6 Dokumentasi Teknis

### 6.1 Deployment Guide

#### 6.1.1 Prerequisites

- **Docker**: Version 20.10 or higher
- **Docker Compose**: Version 2.0 or higher
- **AQICN API Token**: Register di [https://aqicn.org/data-platform/token/](https://aqicn.org/data-platform/token/)
- **Minimum Hardware**:
  - CPU: 2 cores
  - RAM: 4 GB
  - Storage: 20 GB (untuk database growth)

#### 6.1.2 Installation Steps

**1. Clone Repository**
```bash
git clone https://github.com/yourusername/dashboard-kualitas-udara.git
cd dashboard-kualitas-udara
```

**2. Configure Environment**
```bash
# Create .env file
cat > .env << EOF
AQICN_TOKEN=your_api_token_here
PGHOST=postgres
PGPORT=5432
PGDATABASE=airdb
PGUSER=air
PGPASSWORD=airpass
REDIS_URL=redis://redis:6379
EOF
```

**3. Build and Start Services**
```bash
# Build images
docker-compose build

# Start in detached mode
docker-compose up -d

# Verify all services are running
docker-compose ps
```

**4. Verify Deployment**
```bash
# Check backend health
curl http://localhost:8000/health

# Access dashboard
open http://localhost:8050
```

#### 6.1.3 Service Startup Order

Docker Compose menggunakan `depends_on` untuk ordering:
```
1. postgres, redis (parallel)
2. backend, worker (wait for postgres/redis)
3. dashboard (wait for backend)
```

**Healthcheck untuk dependencies:**
```yaml
backend:
  depends_on:
    postgres:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "pg_isready", "-h", "postgres"]
```

### 6.2 Configuration Reference

#### 6.2.1 Backend Configuration

File: `backend/main.py`

**Environment Variables:**
- `PGHOST`: PostgreSQL hostname (default: `localhost`)
- `PGPORT`: PostgreSQL port (default: `5432`)
- `PGDATABASE`: Database name (default: `airdb`)
- `PGUSER`: Database user (default: `air`)
- `PGPASSWORD`: Database password (default: `airpass`)
- `REDIS_URL`: Redis connection string (default: `None`)
- `CACHE_TTL`: Cache expiration in seconds (default: `30`)

**Application Settings:**
```python
class Settings(BaseSettings):
    pghost: str = "localhost"
    pgport: int = 5432
    redis_url: Optional[str] = None
    cache_ttl: int = 30
    
    model_config = SettingsConfigDict(env_file=".env")
```

#### 6.2.2 Worker Configuration

File: `worker/scheduler.py`

**Schedule Configuration:**
```python
# Modify hourly interval
schedule.every(1).hours.do(run_ingestion)

# Alternative schedules:
schedule.every(30).minutes.do(run_ingestion)  # Every 30 min
schedule.every().hour.at(":15").do(run_ingestion)  # At :15 of every hour
```

**Rate Limiting:**
```python
# worker/fetch_observations_and_insert.py
BATCH = 0.5  # Seconds between API calls
```

Increase `BATCH` value jika mengalami rate limiting dari AQICN API.

#### 6.2.3 Dashboard Configuration

File: `dashboard/app.py`

**API Endpoint Configuration:**
```python
API_INTERNAL_URL = os.environ.get("API_INTERNAL_URL", "http://backend:8000")
API_PUBLIC_URL = os.environ.get("API_PUBLIC_URL", "http://localhost:8000")
```

- `API_INTERNAL_URL`: Untuk komunikasi container-to-container
- `API_PUBLIC_URL`: Untuk client-side fetch (jika diperlukan)

**Refresh Interval:**
```python
dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0)
```
Interval dalam milliseconds (default: 60 detik).

### 6.3 API Documentation

#### 6.3.1 Interactive Documentation

FastAPI menyediakan auto-generated API docs:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

#### 6.3.2 Core Endpoints

**GET /health**
```json
{
  "status": "healthy",
  "db": "connected",
  "redis": "connected"
}
```

**GET /stations.geojson**

Query Parameters:
- `lat_min`, `lon_min`, `lat_max`, `lon_max` (optional): Bounding box filtering
- `force_refresh` (boolean): Bypass cache

Response:
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [106.8456, -6.2088]
      },
      "properties": {
        "station_id": "123",
        "name": "Jakarta Central",
        "city": "Jakarta",
        "pm25": 45.2,
        "aqi": 85,
        "category": "Moderate"
      }
    }
  ]
}
```

**GET /timeseries/{station_id}/{param}**

Path Parameters:
- `station_id`: Station identifier
- `param`: Parameter name (pm25, pm10, no2, so2, co, o3, aqi)

Query Parameters:
- `start` (ISO datetime): Start date filter
- `end` (ISO datetime): End date filter
- `limit` (int): Max records (default: 1000)

Response:
```json
{
  "station_id": "123",
  "param": "pm25",
  "series": [
    {
      "ts": "2025-11-22T12:00:00",
      "value": 45.2,
      "unit": "µg/m³"
    }
  ]
}
```

**GET /heatmap**

Query Parameters:
- `param` (string): Parameter for interpolation (default: `pm25`)
- `grid_size` (int): Grid resolution (default: `50`)

Response:
```json
{
  "grid_lon": [95.0, 95.5, ..., 141.0],
  "grid_lat": [-10.0, -9.5, ..., 6.0],
  "grid_values": [[23.5, 24.1, ...], ...],
  "param": "pm25"
}
```

**GET /health_risk**

Query Parameters:
- `pm25_value` (float): PM2.5 concentration in µg/m³

Response:
```json
{
  "pm25": 45.2,
  "category": "Moderate",
  "color": "#FFBB02",
  "health_implications": "Acceptable for most, sensitive groups may experience minor effects",
  "recommendations": [
    "Sensitive individuals should limit prolonged outdoor activity",
    "Keep windows closed if you have respiratory conditions"
  ]
}
```

### 6.4 Monitoring & Logging

#### 6.4.1 Container Logs

**View real-time logs:**
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f worker
```

**Log rotation configuration:**
```yaml
# docker-compose.yml
services:
  backend:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

#### 6.4.2 Application Logging

**Backend Logging:**
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)
logger.info("Database connected")
logger.error(f"Error fetching data: {e}")
```

**Worker Logging:**
```python
print(f"[{datetime.now()}] Starting data ingestion...")
print(f"✅ Using REAL data from backend - {len(features)} stations")
```

Logs dapat di-aggregate menggunakan external tools seperti:
- **ELK Stack**: Elasticsearch, Logstash, Kibana
- **Loki**: Lightweight log aggregation dari Grafana
- **CloudWatch**: Jika deploy di AWS

### 6.5 Troubleshooting Guide

#### 6.5.1 Common Issues

**Issue: `ModuleNotFoundError: No module named 'dash'`**

Solution:
```bash
# Rebuild dashboard container
docker-compose build dashboard
docker-compose up -d dashboard
```

**Issue: Database connection refused**

Solution:
```bash
# Check if PostgreSQL is running
docker-compose ps postgres

# Verify environment variables
docker-compose exec backend env | grep PG

# Manual connection test
docker-compose exec postgres psql -U air -d airdb -c "SELECT 1;"
```

**Issue: Worker not fetching data**

Solution:
```bash
# Check worker logs
docker-compose logs worker

# Verify AQICN token is set
docker-compose exec worker env | grep AQICN

# Manually run fetch script
docker-compose exec worker python fetch_observations_and_insert.py
```

**Issue: Dashboard shows no data**

Solution:
```bash
# Verify backend is accessible
curl http://localhost:8000/stations.geojson

# Check if stations table is populated
docker-compose exec postgres psql -U air -d airdb -c "SELECT COUNT(*) FROM stations;"

# Force cache refresh
curl "http://localhost:8000/stations.geojson?force_refresh=true"
```

#### 6.5.2 Performance Tuning

**Database Connection Pooling:**
```python
# backend/main.py
DB_POOL = await asyncpg.create_pool(
    min_size=5,
    max_size=20,
    command_timeout=60
)
```

**Redis Cache TTL:**
```python
# Increase cache duration for less frequent updates
settings.cache_ttl = 300  # 5 minutes
```

**Worker Concurrency:**

Convert sequential fetching ke concurrent dengan `asyncio`:
```python
import asyncio

async def fetch_all_stations():
    tasks = [fetch_detail_async(uid, lat, lon) for uid, lat, lon in stations]
    results = await asyncio.gather(*tasks)
```

### 6.6 Security Considerations

#### 6.6.1 Database Security

**Change default credentials:**
```yaml
# docker-compose.yml
postgres:
  environment:
    POSTGRES_USER: ${DB_USER}
    POSTGRES_PASSWORD: ${DB_PASS}
```

**Network isolation:**
```yaml
services:
  postgres:
    ports:
      - "127.0.0.1:5432:5432"  # Bind to localhost only
```

**SSL/TLS for production:**
```python
# backend/main.py
DB_POOL = await asyncpg.create_pool(
    ...,
    ssl='require'
)
```

#### 6.6.2 API Security

**Rate Limiting:**
```python
from fastapi import FastAPI
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.get("/stations.geojson")
@limiter.limit("10/minute")
async def stations_geojson():
    ...
```

**API Key Authentication (Future):**
```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.api_key:
        raise HTTPException(status_code=403)
```

#### 6.6.3 Secret Management

**Never commit secrets to Git:**
```gitignore
.env
secrets.json
*.key
*.pem
```

**Use Docker secrets for production:**
```yaml
services:
  backend:
    secrets:
      - db_password
      - api_token
secrets:
  db_password:
    file: ./secrets/db_password.txt
  api_token:
    file: ./secrets/api_token.txt
```

### 6.7 Future Enhancements

#### 6.7.1 Scalability Improvements

**Horizontal Scaling:**
- Deploy multiple backend instances behind load balancer (Nginx/HAProxy)
- Use Redis for shared session state
- Database read replicas untuk read-heavy queries

**Vertical Scaling:**
- Increase PostgreSQL `shared_buffers` untuk caching
- Add more worker processes untuk paralel data ingestion
- Upgrade to larger Docker host

#### 6.7.2 Feature Additions

**Real-time Streaming:**
- Implement WebSocket endpoint untuk live updates
- Use Server-Sent Events (SSE) untuk push notifications
- Integrate with Kafka untuk event streaming

**Machine Learning:**
- Forecast model untuk prediksi AQI 24-48 jam ke depan
- Anomaly detection untuk sensor malfunctions
- Correlation analysis (weather vs air quality)

**Alerting System:**
- Email/SMS notifications untuk threshold breaches
- Webhook integration (Slack, Discord)
- Subscription management untuk users

---

**DOKUMENTASI BERAKHIR**

---

**Referensi:**

1. FastAPI Documentation: [https://fastapi.tiangolo.com](https://fastapi.tiangolo.com)
2. PostgreSQL Documentation: [https://www.postgresql.org/docs/](https://www.postgresql.org/docs/)
3. PostGIS Documentation: [https://postgis.net/documentation/](https://postgis.net/documentation/)
4. Plotly Dash Documentation: [https://dash.plotly.com](https://dash.plotly.com)
5. AQICN API Reference: [https://aqicn.org/json-api/doc/](https://aqicn.org/json-api/doc/)
6. Docker Compose Specification: [https://docs.docker.com/compose/compose-file/](https://docs.docker.com/compose/compose-file/)
7. Redis Documentation: [https://redis.io/documentation](https://redis.io/documentation)

**Dibuat oleh:**
- Phasya Vigo Khalil Nugroho (235150300111004)
- Daffa Fawwaz Garibaldi (235150307111011)
- Gilang Shido Faizalhaq (235150300111011)
- Peter Abednego Wijaya (235150300111013)
- Rafie Habibi Fauzi (235150301111009)
- Dos Hansel Sihombing (235150301111001)

**Universitas Brawijaya - Fakultas Ilmu Komputer**  
**Program Studi**: Informatika  
**Mata Kuliah**: Pengelolaan & Integrasi Data  
**Tahun Ajaran**: 2025/2026
