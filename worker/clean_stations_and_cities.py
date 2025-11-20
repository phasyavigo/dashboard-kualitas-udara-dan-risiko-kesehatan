import json
from pathlib import Path

# Ubah kalau nama file kamu beda
STATIONS_FILE = Path("stations_indonesia.json")
CITIES_FILE = Path("cities_indonesia.json")


def is_non_indonesian_station(station):
    """
    Menentukan apakah stasiun ini JELAS bukan Indonesia
    berdasar field 'name'.

    Aturan:
    - Split 'name' dengan koma.
    - Ambil token terakhir sebagai 'country'.
    - Jika country ada dan bukan 'Indonesia' (case-insensitive),
      maka stasiun dianggap bukan Indonesia -> akan dihapus.
    - Jika tidak ada country (tidak ada koma atau cuma satu bagian),
      TIDAK dihapus (sesuai instruksi: fokus ke yang ada negaranya).
    """
    name = station.get("name", "")
    parts = [p.strip() for p in name.split(",") if p.strip()]

    if len(parts) >= 2:
        country = parts[-1].lower()
        if country != "indonesia":
            return True  # contoh: 'Malaysia', 'Brunei', 'Singapore', dll
    return False


def clean_stations_file(stations_path: Path):
    print(f"[INFO] Loading stations from {stations_path}")
    with stations_path.open("r", encoding="utf-8") as f:
        stations = json.load(f)

    print(f"[INFO] Total stations before cleaning: {len(stations)}")

    cleaned_stations = []
    removed_uids = []

    for st in stations:
        if is_non_indonesian_station(st):
            uid = st.get("uid")
            removed_uids.append(uid)
        else:
            cleaned_stations.append(st)

    print(f"[INFO] Non-Indonesian stations removed: {len(removed_uids)}")
    print(f"[INFO] Stations after cleaning: {len(cleaned_stations)}")

    # Rewrite file yang sama (tidak bikin file baru)
    with stations_path.open("w", encoding="utf-8") as f:
        json.dump(cleaned_stations, f, ensure_ascii=False, indent=2)

    return removed_uids


def clean_cities_file(cities_path: Path, removed_uids):
    removed_set = set(removed_uids)

    print(f"[INFO] Loading cities from {cities_path}")
    with cities_path.open("r", encoding="utf-8") as f:
        cities = json.load(f)

    print(f"[INFO] Total cities before cleaning: {len(cities)}")

    cleaned_cities = {}
    removed_cities_count = 0

    for city_name, uid_list in cities.items():
        # Filter uid yang masih valid (tidak termasuk removed_uids)
        new_uids = [uid for uid in uid_list if uid not in removed_set]

        if new_uids:
            cleaned_cities[city_name] = new_uids
        else:
            # Kota ini cuma berisi stasiun yang dibuang, jadi ikut dihapus
            removed_cities_count += 1

    print(f"[INFO] Cities removed (all uids invalid): {removed_cities_count}")
    print(f"[INFO] Cities after cleaning: {len(cleaned_cities)}")

    # Rewrite file yang sama
    with cities_path.open("w", encoding="utf-8") as f:
        json.dump(cleaned_cities, f, ensure_ascii=False, indent=2)


def main():
    if not STATIONS_FILE.exists():
        raise FileNotFoundError(f"{STATIONS_FILE} not found")
    if not CITIES_FILE.exists():
        raise FileNotFoundError(f"{CITIES_FILE} not found")

    # 1. Bersihkan stations_indonesia.json
    removed_uids = clean_stations_file(STATIONS_FILE)

    # 2. Pakai removed_uids untuk membersihkan cities_indonesia.json
    if removed_uids:
        clean_cities_file(CITIES_FILE, removed_uids)
    else:
        print("[INFO] No stations removed, cities file left unchanged.")


if __name__ == "__main__":
    main()
