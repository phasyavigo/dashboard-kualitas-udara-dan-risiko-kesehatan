# 🌍 Dashboard Kualitas Udara & Risiko Kesehatan Indonesia

Real-time air quality monitoring dashboard untuk Indonesia dengan visualisasi interaktif dan analisis risiko kesehatan.

## ✨ Features

- 🗺️ **Interactive Map** - Visualisasi real-time kualitas udara dari stasiun monitoring di seluruh Indonesia
- 📊 **Data Analytics** - Analisis tren polutan (PM2.5, PM10, NO2, SO2, CO, O3)
- 🎯 **Health Risk Assessment** - Kategori AQI dengan rekomendasi kesehatan
- 📈 **Time Series Analysis** - Historical data dan forecast 5 hari
- 🔄 **Auto-refresh** - Data update otomatis setiap jam
- 🎨 **Modern UI** - Dark theme dengan visualisasi yang menarik

## 🏗️ Architecture

Aplikasi ini dibangun dengan **microservices architecture** menggunakan Docker:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Dashboard  │────▶│   Backend   │────▶│  PostgreSQL │
│   (Dash)    │     │  (FastAPI)  │     │  + PostGIS  │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                     ▲
                           ▼                     │
                    ┌─────────────┐     ┌───────┴──────┐
                    │    Redis    │     │    Worker    │
                    │   (Cache)   │     │  (Scheduler) │
                    └─────────────┘     └──────────────┘
```

### Services

| Service | Technology | Port | Description |
|---------|-----------|------|-------------|
| **Backend** | FastAPI + Uvicorn | 8000 | REST API untuk data kualitas udara |
| **Dashboard** | Dash + Plotly | 8050 | Web interface dengan visualisasi interaktif |
| **Worker** | Python + Schedule | - | Background job untuk fetch data dari AQICN API |
| **Database** | PostgreSQL + PostGIS | 5432 | Penyimpanan data dengan spatial support |
| **Cache** | Redis | 6379 | Caching untuk performa optimal |

## 🛠️ Tech Stack

### Backend
- **FastAPI** - Modern Python web framework
- **AsyncPG** - Async PostgreSQL driver
- **Redis** - Caching layer
- **Pydantic** - Data validation

### Dashboard
- **Dash** - Interactive web applications
- **Plotly** - Data visualization
- **Pandas** - Data manipulation
- **Dash Leaflet** - Interactive maps

### Worker
- **Schedule** - Task scheduling
- **Requests** - HTTP client untuk API calls
- **psycopg2** - PostgreSQL adapter

### Database
- **PostgreSQL 15** - Relational database
- **PostGIS** - Geographic data extension

## 📋 Prerequisites

- Docker & Docker Compose
- AQICN API Token ([Get it here](https://aqicn.org/data-platform/token/))

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/dashboard-kualitas-udara-dan-risiko-kesehatan.git
cd dashboard-kualitas-udara-dan-risiko-kesehatan
```

### 2. Setup Environment Variables

Buat file `.env` di root directory:

```env
AQICN_TOKEN=your_api_token_here
PGHOST=postgres
PGPORT=5432
PGDATABASE=airdb
PGUSER=air
PGPASSWORD=airpass
REDIS_URL=redis://redis:6379
```

### 3. Run dengan Docker Compose

```bash
# Start semua services
docker-compose up -d

# Check logs
docker-compose logs -f

# Stop services
docker-compose down
```

### 4. Access Dashboard

- **Dashboard**: http://localhost:8050
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

## 📁 Project Structure

```
.
├── backend/                 # FastAPI backend service
│   ├── main.py             # API endpoints
│   ├── Dockerfile
│   └── requirements.txt
│
├── dashboard/              # Dash frontend service
│   ├── app.py             # Dashboard application
│   ├── assets/            # Static files (CSS, images)
│   ├── Dockerfile
│   └── requirements.txt
│
├── worker/                # Background worker service
│   ├── scheduler.py       # Main scheduler
│   ├── init_db.py        # Database initialization
│   ├── fetch_observations_and_insert.py
│   ├── stations_indonesia.json
│   ├── Dockerfile
│   └── requirements.txt
│
├── tests/                 # Test files
│   └── test_backend.py
│
├── docker-compose.yml     # Docker orchestration
├── .env                   # Environment variables (create this)
├── .gitignore
└── README.md
```

## 🔌 API Endpoints

### Backend API

```http
GET /stations.geojson
# Returns: GeoJSON dengan semua stasiun dan data terkini

GET /timeseries/{station_id}/{param}?limit=100
# Returns: Time series data untuk parameter tertentu

GET /summary/kpi
# Returns: KPI summary (total stasiun, avg PM2.5, dll)
```

## 🌐 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AQICN_TOKEN` | API token dari AQICN | Required |
| `PGHOST` | PostgreSQL host | postgres |
| `PGPORT` | PostgreSQL port | 5432 |
| `PGDATABASE` | Database name | airdb |
| `PGUSER` | Database user | air |
| `PGPASSWORD` | Database password | airpass |
| `REDIS_URL` | Redis connection URL | redis://redis:6379 |

## 🔧 Development

### Local Development (Without Docker)

```bash
# Setup virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies for each service
pip install -r backend/requirements.txt
pip install -r dashboard/requirements.txt
pip install -r worker/requirements.txt

# Run PostgreSQL & Redis locally
# Update .env with localhost connections

# Run services
python backend/main.py
python dashboard/app.py
python worker/scheduler.py
```

### Rebuild Specific Service

```bash
# Rebuild dan restart service tertentu
docker-compose up -d --build backend
docker-compose up -d --build dashboard
docker-compose up -d --build worker
```

## 📊 Data Source

Data kualitas udara berasal dari [AQICN (Air Quality Index China Network)](https://aqicn.org/) yang menyediakan data real-time dari stasiun monitoring di seluruh dunia, termasuk Indonesia.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License.


## 🙏 Acknowledgments

- AQICN for providing air quality data API
- World Air Quality Index project
- OpenStreetMap for map tiles

---

Made with ❤️ for better air quality awareness in Indonesia
