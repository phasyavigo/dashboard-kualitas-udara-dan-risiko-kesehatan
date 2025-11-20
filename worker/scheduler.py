import time
import schedule
import subprocess
import os
from datetime import datetime

def run_ingestion():
    print(f"[{datetime.now()}] Starting data ingestion...")
    try:
        # Run the existing scripts
        # 1. Fetch stations (optional, maybe run less frequently)
        # subprocess.run(["python", "fetch_stations_and_city.py"], check=True)
        
        # 2. Fetch observations
        subprocess.run(["python", "fetch_observations_and_insert.py"], check=True)
        
        print(f"[{datetime.now()}] Ingestion completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[{datetime.now()}] Error during ingestion: {e}")

# Schedule every hour
schedule.every(1).hours.do(run_ingestion)

# Also run initialization and ingestion immediately on startup
print("Running DB Initialization...")
subprocess.run(["python", "init_db.py"], check=True)
run_ingestion()

if __name__ == "__main__":
    print("Scheduler started...")
    while True:
        schedule.run_pending()
        time.sleep(60)
