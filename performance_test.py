"""
Performance Testing Script for Air Quality Dashboard
Generates real metrics for Chapter 6 of the report
"""

import requests
import time
import statistics
import psycopg2
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
BACKEND_URL = "http://localhost:8000"
DASHBOARD_URL = "http://localhost:8050"
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "airdb",
    "user": "air",
    "password": "airpass"
}

def print_section(title):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def test_api_response_time(endpoint, num_requests=100):
    """Test API endpoint response time"""
    print(f"\nTesting {endpoint}...")
    url = f"{BACKEND_URL}{endpoint}"
    
    response_times = []
    failures = 0
    
    for i in range(num_requests):
        try:
            start = time.time()
            response = requests.get(url, timeout=10)
            end = time.time()
            
            if response.status_code == 200:
                response_times.append((end - start) * 1000)  # Convert to ms
            else:
                failures += 1
        except Exception as e:
            failures += 1
    
    if response_times:
        return {
            "endpoint": endpoint,
            "requests": num_requests,
            "mean_ms": round(statistics.mean(response_times), 2),
            "median_ms": round(statistics.median(response_times), 2),
            "min_ms": round(min(response_times), 2),
            "max_ms": round(max(response_times), 2),
            "p95_ms": round(statistics.quantiles(response_times, n=20)[18], 2) if len(response_times) > 20 else round(max(response_times), 2),
            "failures": failures,
            "success_rate": round((num_requests - failures) / num_requests * 100, 2)
        }
    else:
        return {"endpoint": endpoint, "error": "All requests failed"}

def test_concurrent_load(endpoint, concurrency=10, total_requests=100):
    """Test API under concurrent load"""
    print(f"\nTesting concurrent load (concurrency={concurrency})...")
    url = f"{BACKEND_URL}{endpoint}"
    
    def make_request():
        try:
            start = time.time()
            response = requests.get(url, timeout=10)
            end = time.time()
            return {
                "success": response.status_code == 200,
                "time_ms": (end - start) * 1000
            }
        except:
            return {"success": False, "time_ms": 0}
    
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(make_request) for _ in range(total_requests)]
        for future in as_completed(futures):
            results.append(future.result())
    
    successful = [r for r in results if r["success"]]
    times = [r["time_ms"] for r in successful]
    
    if times:
        return {
            "concurrency": concurrency,
            "total_requests": total_requests,
            "successful": len(successful),
            "failed": total_requests - len(successful),
            "mean_ms": round(statistics.mean(times), 2),
            "p95_ms": round(statistics.quantiles(times, n=20)[18], 2) if len(times) > 20 else round(max(times), 2),
            "failure_rate": round((total_requests - len(successful)) / total_requests * 100, 2)
        }
    else:
        return {"error": "All requests failed"}

def test_database_queries():
    """Test database query performance"""
    print("\nTesting database queries...")
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        queries = {
            "count_stations": "SELECT COUNT(*) FROM stations",
            "count_observations": "SELECT COUNT(*) FROM observations",
            "latest_observations": "SELECT DISTINCT ON (station_id, param) station_id, param, value, ts FROM observations ORDER BY station_id, param, ts DESC LIMIT 100",
            "stations_with_geom": "SELECT station_id, name, city, ST_AsGeoJSON(geom) FROM stations WHERE geom IS NOT NULL",
            "timeseries_query": "SELECT ts, value FROM observations WHERE station_id = (SELECT station_id FROM stations LIMIT 1) AND param = 'pm25' ORDER BY ts DESC LIMIT 1000"
        }
        
        results = {}
        for query_name, query in queries.items():
            start = time.time()
            cur.execute(query)
            rows = cur.fetchall()
            end = time.time()
            
            results[query_name] = {
                "query": query[:80] + "..." if len(query) > 80 else query,
                "execution_time_ms": round((end - start) * 1000, 2),
                "rows_returned": len(rows)
            }
        
        cur.close()
        conn.close()
        
        return results
    except Exception as e:
        return {"error": str(e)}

def test_data_statistics():
    """Get actual data statistics from database"""
    print("\nGathering data statistics...")
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        stats = {}
        
        # Total stations
        cur.execute("SELECT COUNT(*) FROM stations")
        stats["total_stations"] = cur.fetchone()[0]
        
        # Total observations
        cur.execute("SELECT COUNT(*) FROM observations")
        stats["total_observations"] = cur.fetchone()[0]
        
        # Date range
        cur.execute("SELECT MIN(ts), MAX(ts) FROM observations")
        min_date, max_date = cur.fetchone()
        stats["date_range"] = {
            "earliest": str(min_date) if min_date else "N/A",
            "latest": str(max_date) if max_date else "N/A"
        }
        
        # Parameters collected
        cur.execute("SELECT DISTINCT param FROM observations")
        stats["parameters"] = [row[0] for row in cur.fetchall()]
        
        # Data completeness (last 24 hours)
        cur.execute("""
            SELECT 
                COUNT(DISTINCT station_id) as stations_reporting,
                COUNT(*) as total_readings
            FROM observations
            WHERE ts > NOW() - INTERVAL '24 hours'
        """)
        row = cur.fetchone()
        stats["last_24h"] = {
            "stations_reporting": row[0],
            "total_readings": row[1]
        }
        
        cur.close()
        conn.close()
        
        return stats
    except Exception as e:
        return {"error": str(e)}

def main():
    print_section("AIR QUALITY DASHBOARD - PERFORMANCE TEST REPORT")
    print(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Test 1: API Response Time (Sequential)
    print_section("TEST 1: API RESPONSE TIME (100 sequential requests)")
    
    endpoints = [
        "/stations.geojson",
        "/summary",
    ]
    
    api_results = {}
    for endpoint in endpoints:
        result = test_api_response_time(endpoint, num_requests=100)
        api_results [endpoint] = result
        if "error" not in result:
            print(f"\n{endpoint}:")
            print(f"  Mean: {result['mean_ms']}ms")
            print(f"  Median: {result['median_ms']}ms")
            print(f"  P95: {result['p95_ms']}ms")
            print(f"  Min/Max: {result['min_ms']}ms / {result['max_ms']}ms")
            print(f"  Success Rate: {result['success_rate']}%")
    
    # Test 2: Concurrent Load
    print_section("TEST 2: CONCURRENT LOAD TESTING")
    
    concurrency_levels = [10, 25, 50]
    load_results = {}
    
    for concurrency in concurrency_levels:
        result = test_concurrent_load("/stations.geojson", concurrency=concurrency, total_requests=100)
        load_results[f"concurrency_{concurrency}"] = result
        if "error" not in result:
            print(f"\nConcurrency {concurrency}:")
            print(f"  Successful: {result['successful']}/{result['total_requests']}")
            print(f"  Mean Response: {result['mean_ms']}ms")
            print(f"  P95: {result['p95_ms']}ms")
            print(f"  Failure Rate: {result['failure_rate']}%")
    
    # Test 3: Database Queries
    print_section("TEST 3: DATABASE QUERY PERFORMANCE")
    
    db_results = test_database_queries()
    if "error" not in db_results:
        for query_name, result in db_results.items():
            print(f"\n{query_name}:")
            print(f"  Execution Time: {result['execution_time_ms']}ms")
            print(f"  Rows Returned: {result['rows_returned']}")
    else:
        print(f"Error: {db_results['error']}")
    
    # Test 4: Data Statistics
    print_section("TEST 4: ACTUAL DATA STATISTICS")
    
    data_stats = test_data_statistics()
    if "error" not in data_stats:
        print(f"\nTotal Stations: {data_stats['total_stations']}")
        print(f"Total Observations: {data_stats['total_observations']:,}")
        print(f"Date Range: {data_stats['date_range']['earliest']} to {data_stats['date_range']['latest']}")
        print(f"Parameters Collected: {', '.join(data_stats['parameters'])}")
        print(f"\nLast 24 Hours:")
        print(f"  Stations Reporting: {data_stats['last_24h']['stations_reporting']}")
        print(f"  Total Readings: {data_stats['last_24h']['total_readings']}")
    else:
        print(f"Error: {data_stats['error']}")
    
    # Save results to JSON
    print_section("SAVING RESULTS")
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "api_response_time": api_results,
        "concurrent_load": load_results,
        "database_queries": db_results,
        "data_statistics": data_stats
    }
    
    output_file = "performance_test_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to: {output_file}")
    print("\nPerformance testing completed!")

if __name__ == "__main__":
    main()
