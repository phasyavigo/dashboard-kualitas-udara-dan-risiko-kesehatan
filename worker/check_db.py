import os
import psycopg2

DB_HOST = os.environ.get("PGHOST", "postgres")
DB_PORT = os.environ.get("PGPORT", "5432")
DB_NAME = os.environ.get("PGDATABASE", "airdb")
DB_USER = os.environ.get("PGUSER", "air")
DB_PASS = os.environ.get("PGPASSWORD", "airpass")

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )
    cur = conn.cursor()
    
    cur.execute("SELECT count(*) FROM stations;")
    count = cur.fetchone()[0]
    print(f"Total stations in DB: {count}")
    
    if count > 0:
        cur.execute("SELECT station_id, name, ST_AsText(geom) FROM stations LIMIT 5;")
        rows = cur.fetchall()
        print("Sample stations:")
        for r in rows:
            print(r)
            
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error connecting to DB: {e}")
