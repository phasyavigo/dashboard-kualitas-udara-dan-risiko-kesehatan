import psycopg2
import json
import os

DB_HOST = os.environ.get("PGHOST", "localhost")
DB_PORT = os.environ.get("PGPORT", "5432")
DB_NAME = os.environ.get("PGDATABASE", "airdb")
DB_USER = os.environ.get("PGUSER", "air")
DB_PASS = os.environ.get("PGPASSWORD", "airpass")

def connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

def test_update():
    conn = connect()
    cur = conn.cursor()
    
    print("Testing simple update...")
    try:
        # Try updating with a simple JSON string
        cur.execute("UPDATE stations SET params = '{\"test\": 1}'::jsonb WHERE station_id = 'aqicn-13654'")
        conn.commit()
        print("Update successful!")
    except Exception as e:
        print(f"Update failed: {e}")
        conn.rollback()
        
    cur.close()
    conn.close()

if __name__ == "__main__":
    test_update()
