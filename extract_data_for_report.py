"""
Extract Real Data for Report BAB 2
Analisis Deskriptif & Insight
"""

import psycopg2
import json
import requests
from collections import Counter
from datetime import datetime

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "airdb",
    "user": "air",
    "password": "airpass"
}

BACKEND_URL = "http://localhost:8000"

def get_geographic_distribution():
    """Get station distribution by city"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    cur.execute("""
        SELECT city, COUNT(*) as count
        FROM stations
        WHERE city IS NOT NULL
        GROUP BY city
        ORDER BY count DESC
        LIMIT 15
    """)
    
    results = cur.fetchall()
    cur.close()
    conn.close()
    
    return {city: count for city, count in results}

def get_aqi_distribution():
    """Get AQI distribution from latest data"""
    try:
        response = requests.get(f"{BACKEND_URL}/stations.geojson", timeout=10)
        if response.status_code == 200:
            geojson = response.json()
            features = geojson.get("features", [])
            
            aqi_values = []
            categories = []
            
            for f in features:
                props = f.get("properties", {})
                aqi = props.get("aqi", 0)
                category = props.get("category", "Unknown")
                
                if aqi > 0:
                    aqi_values.append(aqi)
                    categories.append(category)
            
            if aqi_values:
                return {
                    "total_stations": len(aqi_values),
                    "mean": round(sum(aqi_values) / len(aqi_values), 1),
                    "median": sorted(aqi_values)[len(aqi_values)//2],
                    "min": min(aqi_values),
                    "max": max(aqi_values),
                    "category_breakdown": dict(Counter(categories)),
                    "good_count": categories.count("Good"),
                    "moderate_count": categories.count("Moderate"),
                    "unhealthy_count": categories.count("Unhealthy"),
                    "hazardous_count": categories.count("Hazardous")
                }
    except Exception as e:
        print(f"Error fetching AQI distribution: {e}")
    
    return {}

def get_top_worst_stations():
    """Get top 5 worst air quality stations"""
    try:
        response = requests.get(f"{BACKEND_URL}/stations.geojson", timeout=10)
        if response.status_code == 200:
            geojson = response.json()
            features = geojson.get("features", [])
            
            # Sort by AQI descending
            sorted_features = sorted(
                features,
                key=lambda x: x.get("properties", {}).get("aqi", 0),
                reverse=True
            )[:5]
            
            top5 = []
            for f in sorted_features:
                props = f.get("properties", {})
                top5.append({
                    "name": props.get("name", "Unknown"),
                    "city": props.get("city", "Unknown"),
                    "aqi": props.get("aqi", 0),
                    "pm25": props.get("pm25", 0),
                    "category": props.get("category", "Unknown")
                })
            
            return top5
    except Exception as e:
        print(f"Error fetching top worst stations: {e}")
    
    return []

def get_pm25_statistics():
    """Get PM2.5 statistics from observations"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Get PM2.5 statistics from last 7 days
    cur.execute("""
        SELECT 
            AVG(value) as avg_pm25,
            MIN(value) as min_pm25,
            MAX(value) as max_pm25,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY value) as median_pm25
        FROM observations
        WHERE param = 'pm25'
        AND ts > NOW() - INTERVAL '7 days'
        AND value IS NOT NULL
    """)
    
    result = cur.fetchone()
    
    # Get hourly pattern
    cur.execute("""
        SELECT 
            EXTRACT(HOUR FROM ts) as hour,
            AVG(value) as avg_value
        FROM observations
        WHERE param = 'pm25'
        AND ts > NOW() - INTERVAL '7 days'
        AND value IS NOT NULL
        GROUP BY EXTRACT(HOUR FROM ts)
        ORDER BY hour
    """)
    
    hourly_pattern = {int(row[0]): round(row[1], 1) for row in cur.fetchall()}
    
    cur.close()
    conn.close()
    
    if result:
        return {
            "average": round(result[0], 1) if result[0] else 0,
            "min": round(result[1], 1) if result[1] else 0,
            "max": round(result[2], 1) if result[2] else 0,
            "median": round(result[3], 1) if result[3] else 0,
            "hourly_pattern": hourly_pattern,
            "peak_hours": max(hourly_pattern, key=hourly_pattern.get) if hourly_pattern else None
        }
    
    return {}

def get_parameter_statistics():
    """Get statistics for all pollutant parameters"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    params = ['pm25', 'pm10', 'no2', 'so2', 'o3', 'co']
    
    stats = {}
    for param in params:
        cur.execute("""
            SELECT 
                COUNT(*) as count,
                AVG(value) as avg,
                MAX(value) as max
            FROM observations
            WHERE param = %s
            AND ts > NOW() - INTERVAL '7 days'
            AND value IS NOT NULL
        """, (param,))
        
        result = cur.fetchone()
        if result and result[0] > 0:
            stats[param] = {
                "count": result[0],
                "average": round(result[1], 2) if result[1] else 0,
                "max": round(result[2], 2) if result[2] else 0
            }
    
    cur.close()
    conn.close()
    
    return stats

def get_data_completeness():
    """Get data completeness statistics"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Expected readings per station (24 hours * 7 days)
    expected_per_station = 24 * 7
    
    cur.execute("""
        SELECT 
            COUNT(DISTINCT station_id) as active_stations,
            COUNT(*) as total_readings,
            COUNT(*) / COUNT(DISTINCT station_id) as avg_readings_per_station
        FROM observations
        WHERE ts > NOW() - INTERVAL '7 days'
    """)
    
    result = cur.fetchone()
    
    cur.close()
    conn.close()
    
    if result:
        avg_readings = int(result[2]) if result[2] else 0
        completeness_pct = round((avg_readings / expected_per_station) * 100, 1) if expected_per_station > 0 else 0
        
        return {
            "active_stations": result[0],
            "total_readings": result[1],
            "avg_readings_per_station": avg_readings,
            "expected_per_station": expected_per_station,
            "completeness_percentage": completeness_pct
        }
    
    return {}

def main():
    print("="*70)
    print("  EXTRACTING REAL DATA FOR REPORT - BAB 2")
    print("="*70)
    print(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 1. Geographic Distribution
    print("1. Geographic Distribution of Stations...")
    geo_dist = get_geographic_distribution()
    print(f"   Top cities: {list(geo_dist.keys())[:5]}")
    
    # 2. AQI Distribution
    print("\n2. AQI Distribution...")
    aqi_dist = get_aqi_distribution()
    if aqi_dist:
        print(f"   Mean AQI: {aqi_dist.get('mean')}")
        print(f"   Median AQI: {aqi_dist.get('median')}")
        print(f"   Range: {aqi_dist.get('min')} - {aqi_dist.get('max')}")
        print(f"   Categories: {aqi_dist.get('category_breakdown')}")
    
    # 3. Top Worst Stations
    print("\n3. Top 5 Worst Air Quality Stations...")
    top5 = get_top_worst_stations()
    for i, station in enumerate(top5, 1):
        print(f"   #{i} {station['name']} ({station['city']}): AQI {station['aqi']}")
    
    # 4. PM2.5 Statistics
    print("\n4. PM2.5 Statistics (Last 7 Days)...")
    pm25_stats = get_pm25_statistics()
    if pm25_stats:
        print(f"   Average: {pm25_stats.get('average')} µg/m³")
        print(f"   Median: {pm25_stats.get('median')} µg/m³")
        print(f"   Range: {pm25_stats.get('min')} - {pm25_stats.get('max')} µg/m³")
        if pm25_stats.get('peak_hours'):
            print(f"   Peak Hour: {pm25_stats.get('peak_hours')}:00")
    
    # 5. Multi-Parameter Statistics
    print("\n5. Multi-Parameter Statistics...")
    param_stats = get_parameter_statistics()
    for param, stats in param_stats.items():
        print(f"   {param.upper()}: avg={stats['average']}, max={stats['max']}, readings={stats['count']}")
    
    # 6. Data Completeness
    print("\n6. Data Completeness...")
    completeness = get_data_completeness()
    if completeness:
        print(f"   Active Stations: {completeness['active_stations']}")
        print(f"   Avg Readings/Station: {completeness['avg_readings_per_station']}/{completeness['expected_per_station']}")
        print(f"   Completeness: {completeness['completeness_percentage']}%")
    
    # Save to JSON
    print("\n" + "="*70)
    print("  SAVING RESULTS")
    print("="*70)
    
    all_data = {
        "timestamp": datetime.now().isoformat(),
        "geographic_distribution": geo_dist,
        "aqi_distribution": aqi_dist,
        "top_worst_stations": top5,
        "pm25_statistics": pm25_stats,
        "parameter_statistics": param_stats,
        "data_completeness": completeness
    }
    
    output_file = "report_data_extraction.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nResults saved to: {output_file}")
    print("\nData extraction completed!")

if __name__ == "__main__":
    main()
