import requests
import json


with open('secrets.json', 'r') as file:
    secrets = json.load(file)
    file.close()

TOKEN = secrets["aqicn-api-key"]   # ganti dengan token kamu

# Bounding box umum untuk seluruh Indonesia
BOUNDING_BOX = "-11,95,6,141"

def fetch_stations():
    url = "https://api.waqi.info/v2/map/bounds/"
    params = {
        "latlng": BOUNDING_BOX,
        "token": TOKEN
    }

    print("Fetching stations from AQICN API ...")
    resp = requests.get(url, params=params)
    resp.raise_for_status()

    data = resp.json()

    if data.get("status") != "ok":
        raise RuntimeError(f"API Error: {data}")

    return data["data"]


def extract_city(station_name):
    """
    Contoh nama:
    'Kelapa Gading, Jakarta, Indonesia'
    """
    parts = [p.strip() for p in station_name.split(",")]
    if len(parts) >= 2:
        return parts[-2]   # kota ada sebelum 'Indonesia'
    return parts[-1]


def main():
    stations_raw = fetch_stations()

    stations_list = []
    cities = {}

    print(f"Found {len(stations_raw)} stations")

    for s in stations_raw:
        name = s["station"]["name"]
        city = extract_city(name)

        station_obj = {
            "uid": s["uid"],
            "name": name,
            "city": city,
            "lat": s["lat"],
            "lon": s["lon"]
        }
        stations_list.append(station_obj)

        if city not in cities:
            cities[city] = []
        cities[city].append(s["uid"])

    # Save station list
    with open("stations_indonesia.json", "w", encoding="utf-8") as f:
        json.dump(stations_list, f, ensure_ascii=False, indent=2)

    # Save city list
    with open("cities_indonesia.json", "w", encoding="utf-8") as f:
        json.dump(cities, f, ensure_ascii=False, indent=2)

    print("Files saved:")
    print("- stations_indonesia.json")
    print("- cities_indonesia.json")


if __name__ == "__main__":
    main()
