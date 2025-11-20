# Air Quality Dashboard - Walkthrough

## Overview
This dashboard visualizes air quality data (PM2.5, PM10, etc.) from stations across Indonesia using the AQICN API. It includes a FastAPI backend, a PostgreSQL/PostGIS database, and a Dash Plotly frontend.

## Prerequisites
- Docker & Docker Compose
- AQICN API Token (Get one at [aqicn.org](https://aqicn.org/data-platform/token/))

## Setup & Run

1.  **Configure API Token**:
    - Ensure you have a `secrets.json` file in the root directory with your token:
      ```json
      {
          "aqicn-api-key": "YOUR_TOKEN_HERE"
      }
      ```
    - OR set it in `docker-compose.yml` under the `worker` service (uncomment the line).

2.  **Build and Run**:
    ```bash
    docker-compose up --build
    ```

3.  **Access the Dashboard**:
    - Open your browser to [http://localhost:8050](http://localhost:8050).
    - The backend API is available at [http://localhost:8000/docs](http://localhost:8000/docs).

## Features
- **Interactive Map**: View air quality stations on a map of Indonesia.
- **Real-time Data**: Click on a station to see the latest pollutant levels.
- **Historical Trends**: View time-series graphs for PM2.5, PM10, and other pollutants.
- **WHO Thresholds**: Graphs include WHO recommended limits for easy comparison.

## Architecture
- **Backend**: FastAPI (Python)
- **Frontend**: Dash (Python)
- **Database**: PostgreSQL + PostGIS
- **Cache**: Redis
- **Worker**: Scheduled Python script for data ingestion
