import json
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

API_TOKEN = "YOUR_API_TOKEN"  # isi dengan token kamu

BASE_URL = "https://aqicn.org"
COUNTRY_URL = f"{BASE_URL}/station/country/id/indonesia/"
SCRAPED_OUTPUT = "scraped_indonesia_stations.json"

STATIONS_FILE = Path("stations_indonesia.json")
CITIES_FILE = Path("cities_indonesia.json")


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def load_json_or_empty(path: Path):
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_html(url):
    print(f"[GET] {url}")
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def find_indonesia_station_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        full_url = urljoin(BASE_URL, href)

        if "/station/" in href and "indonesia" in href.lower():
            if any(x in href for x in ["validation", "widgets", "data-platform", "map"]):
                continue

            name = a.get_text(strip=True)
            if name:
                links.append({"name": name, "url": full_url})

    uniq = {}
    for s in links:
        uniq[s["url"]] = s
    return list(uniq.values())


def extract_cloud_api_url(station_html):
    soup = BeautifulSoup(station_html, "html.parser")
    for a in soup.find_all("a", href=True):
        if "/data-platform/api/" in a["href"]:
            return urljoin(BASE_URL, a["href"])
    return None


def fetch_station_api(station_url):
    """
    Ambil UID dari halaman stasiun (scraping), lalu cek JSON API feed.
    """
    try:
        html = get_html(station_url)
    except:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Cari link feed @UID dari halaman
    for a in soup.find_all("a", href=True):
        if "/feed/@" in a["href"]:
            api_url = urljoin(BASE_URL, a["href"])
            api_url = api_url + "?token=" + API_TOKEN
            try:
                r = requests.get(api_url, timeout=15)
                data = r.json()
                if data.get("status") == "ok":
                    return data["data"]
            except:
                return None

    return None


# ---------------------------------------------------------
# Main scraper + updater
# ---------------------------------------------------------

def main():
    # Load existing JSON
    stations_db = load_json_or_empty(STATIONS_FILE)
    cities_db = load_json_or_empty(CITIES_FILE)

    if isinstance(stations_db, list):
        # convert to dict by uid
        stations_dict = {s["uid"]: s for s in stations_db}
    else:
        stations_dict = {}

    if not isinstance(cities_db, dict):
        cities_db = {}

    # SCRAPE website Indonesia stations
    html = get_html(COUNTRY_URL)
    scraped = find_indonesia_station_links(html)
    print(f"[INFO] Found {len(scraped)} scraped station links")

    combined_output = []

    for i, st in enumerate(scraped, start=1):
        print(f"\n[INFO] ({i}/{len(scraped)}) Processing: {st['name']}")
        station_url = st["url"]

        api_data = fetch_station_api(station_url)
        if not api_data:
            print("[WARN] Cannot fetch station API, skipping")
            continue

        uid = api_data.get("idx")
        city = api_data["city"]["name"]
        lat, lon = api_data["city"]["geo"]

        # Build station object
        station_obj = {
            "uid": uid,
            "name": st["name"],
            "city": city,
            "lat": lat,
            "lon": lon
        }

        combined_output.append({
            "name": st["name"],
            "station_url": station_url,
            "uid": uid,
            "city": city,
            "lat": lat,
            "lon": lon
        })

        # TAMBAH KE stations_indonesia.json (if not exist)
        if uid not in stations_dict:
            print(f"[ADD] Adding station uid {uid} to stations_indonesia.json")
            stations_dict[uid] = station_obj
        else:
            print(f"[SKIP] uid {uid} already exists")

        # TAMBAH KE cities_indonesia.json (if not exist)
        if city not in cities_db:
            cities_db[city] = []

        if uid not in cities_db[city]:
            print(f"[ADD] Adding uid {uid} to city: {city}")
            cities_db[city].append(uid)
        else:
            print(f"[SKIP] City {city} already has uid {uid}")

        time.sleep(1.0)

    # Save updated station list
    stations_list = list(stations_dict.values())
    save_json(STATIONS_FILE, stations_list)

    # Save updated cities file
    save_json(CITIES_FILE, cities_db)

    # Save scraped reference file
    save_json(Path(SCRAPED_OUTPUT), combined_output)

    print("\n[DONE] All updates applied successfully.")


if __name__ == "__main__":
    main()
