import json
import time
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ================== KONFIGURASI ==================
with open('secrets.json', 'r') as file:
    secrets = json.load(file)
    file.close()

API_TOKEN = secrets["aqicn-api-key"]


BASE_URL = "https://aqicn.org"
MENLHK_URL = f"{BASE_URL}/network/menlhk/"

STATIONS_FILE = Path("stations_indonesia.json")
CITIES_FILE = Path("cities_indonesia.json")
SCRAPED_OUTPUT = Path("scraped_menlhk_stations.json")

# ================== HELPER JSON ==================


def load_json_or_default(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ================== HELPER SCRAPING ==================


def get_html(url):
    print(f"[GET] {url}")
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def find_menlhk_station_links(html):
    """
    Cari link stasiun dari halaman MENLHK network.
    Di halaman itu ada list:
      "Some of the most polluted air quality monitoring stations:"
    Linknya bentuk <a> ke /station/... per stasiun.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Kita mau semua link ke /station/
        if "/station/" in href:
            name = a.get_text(strip=True)
            if not name:
                continue
            # Hindari link generik seperti "Click for more information" dsb kalau ada
            # nama stasiun di list itu selalu punya angka AQI di depan (misal "130 Kabupaten Muaro Jambi Sengeti")
            if not any(ch.isdigit() for ch in name):
                continue

            full_url = urljoin(BASE_URL, href)
            links.append({
                "name": name,
                "url": full_url,
            })

    # Hilangkan duplikat berdasarkan URL
    uniq = {}
    for item in links:
        uniq[item["url"]] = item
    final_links = list(uniq.values())

    print(f"[INFO] Found {len(final_links)} MENLHK station links on network page")
    return final_links


def extract_cloud_api_url(station_html):
    """
    Dari halaman stasiun, cari link Cloud API:
      href yang mengandung '/data-platform/api/Axxxxxx/'
    """
    soup = BeautifulSoup(station_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/data-platform/api/" in href:
            return urljoin(BASE_URL, href)
    return None


def fetch_station_data_from_json_api(uid: int):
    """
    Panggil JSON API feed @uid untuk ambil metadata stasiun.
    """
    api_url = f"https://api.waqi.info/feed/@{uid}/"
    params = {"token": API_TOKEN}
    print(f"[API] GET {api_url}")
    resp = requests.get(api_url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        print(f"[WARN] API status not ok for uid {uid}: {data}")
        return None
    return data["data"]


# ================== MAIN LOGIC ==================


def main():
    # 1. Load existing JSON
    existing_stations = load_json_or_default(STATIONS_FILE, [])
    existing_cities = load_json_or_default(CITIES_FILE, {})

    # station db jadi dict uid -> obj
    stations_by_uid = {}
    for st in existing_stations:
        stations_by_uid[st["uid"]] = st

    # 2. Scrape page MENLHK network
    html = get_html(MENLHK_URL)
    station_links = find_menlhk_station_links(html)

    scraped_summary = []

    # 3. Loop tiap stasiun di MENLHK
    for i, st_link in enumerate(station_links, start=1):
        print(f"\n[INFO] ({i}/{len(station_links)}) Processing: {st_link['name']}")
        station_url = st_link["url"]

        try:
            station_html = get_html(station_url)
        except Exception as e:
            print(f"[WARN] Gagal buka halaman stasiun: {e}")
            continue

        cloud_api_url = extract_cloud_api_url(station_html)
        if not cloud_api_url:
            print("[WARN] Cloud API URL tidak ditemukan, skip")
            continue

        # Extract uid dari cloud_api_url, pola: .../data-platform/api/A519118/
        m = re.search(r"/data-platform/api/A(\d+)/?", cloud_api_url)
        if not m:
            print(f"[WARN] Tidak bisa extract UID dari {cloud_api_url}")
            continue

        uid = int(m.group(1))
        print(f"[INFO] UID from Cloud API: {uid}")

        # 4. Panggil JSON API feed @uid
        api_data = fetch_station_data_from_json_api(uid)
        if not api_data:
            print("[WARN] Tidak dapat data dari JSON API, skip")
            continue

        city_name = api_data["city"]["name"]
        lat, lon = api_data["city"]["geo"]

        # Bangun objek stasiun final
        station_obj = {
            "uid": uid,
            "name": city_name,  # atau bisa pakai st_link["name"], terserah preferensi
            "city": city_name,
            "lat": lat,
            "lon": lon
        }

        # Simpan ke summary hasil scrape
        scraped_summary.append({
            "uid": uid,
            "station_label_from_network": st_link["name"],
            "station_url": station_url,
            "cloud_api_url": cloud_api_url,
            "city": city_name,
            "lat": lat,
            "lon": lon
        })

        # 5. Update stations_indonesia.json
        if uid not in stations_by_uid:
            print(f"[ADD] Tambah station uid {uid} ke stations_indonesia.json")
            stations_by_uid[uid] = station_obj
        else:
            print(f"[SKIP] uid {uid} sudah ada di stations_indonesia.json")

        # 6. Update cities_indonesia.json
        if city_name not in existing_cities:
            existing_cities[city_name] = []

        if uid not in existing_cities[city_name]:
            print(f"[ADD] Tambah uid {uid} ke kota '{city_name}' di cities_indonesia.json")
            existing_cities[city_name].append(uid)
        else:
            print(f"[SKIP] Kota '{city_name}' sudah punya uid {uid}")

        # Jeda sedikit biar tidak terlalu agresif
        time.sleep(1.0)

    # 7. Tulis balik ke file yang sama
    new_stations_list = list(stations_by_uid.values())
    save_json(STATIONS_FILE, new_stations_list)
    save_json(CITIES_FILE, existing_cities)
    save_json(SCRAPED_OUTPUT, scraped_summary)

    print("\n[DONE] Update selesai.")
    print(f"  - stations_indonesia.json: {len(new_stations_list)} record")
    print(f"  - cities_indonesia.json:   {len(existing_cities)} kota")
    print(f"  - scraped_menlhk_stations.json: {len(scraped_summary)} record")


if __name__ == "__main__":
    main()
