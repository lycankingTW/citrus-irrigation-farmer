"""農業部自動雨量站。座標由畫面提供，雨量在伺服器讀取。"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

MIAOLI_LAT = 24.5593
MIAOLI_LON = 120.8214
MIAOLI_NAME = "苗栗區農業改良場"
API_URL = "https://data.moa.gov.tw/api/v1/AutoRainfallStationType/"
API_KEY = "IKXAGW0DJ1G90FL4SJ5N364EM567QX"

# 未帶篩選時，這個端點會忽略 $top / $skip，固定回傳不穩定的 1000 筆（Next 仍為 true）。
# CITY=縣市才是穩定結果：該縣市測站會被重複補到 1000 列，去重後就是完整集合。
# 方框是概略範圍，左右上下各外擴 _COUNTY_PAD，讓縣界附近的果園會一併查相鄰縣市。
_COUNTY_BOXES: dict[str, tuple[float, float, float, float]] = {
    # south, north, west, east
    "基隆市": (25.10, 25.18, 121.65, 121.80),
    "臺北市": (24.96, 25.22, 121.45, 121.67),
    "新北市": (24.67, 25.30, 121.28, 122.01),
    "桃園市": (24.78, 25.13, 120.98, 121.48),
    "新竹縣": (24.45, 24.95, 120.98, 121.30),
    "新竹市": (24.73, 24.86, 120.89, 121.04),
    "苗栗縣": (24.28, 24.75, 120.62, 121.16),
    "臺中市": (24.00, 24.45, 120.45, 121.45),
    "彰化縣": (23.80, 24.20, 120.25, 120.72),
    "南投縣": (23.45, 24.25, 120.60, 121.35),
    "雲林縣": (23.48, 23.85, 120.10, 120.75),
    "嘉義縣": (23.20, 23.65, 120.08, 120.95),
    "嘉義市": (23.45, 23.52, 120.40, 120.52),
    "臺南市": (22.88, 23.42, 120.03, 120.65),
    "高雄市": (22.48, 23.28, 120.17, 121.05),
    "屏東縣": (21.90, 22.88, 120.40, 120.95),
    "宜蘭縣": (24.30, 24.95, 121.45, 121.98),
    "花蓮縣": (23.10, 24.37, 121.15, 121.80),
    "臺東縣": (22.00, 23.45, 120.85, 121.55),
    "澎湖縣": (23.15, 23.80, 119.30, 119.75),
    "金門縣": (24.38, 24.53, 118.20, 118.50),
    "連江縣": (25.94, 26.40, 119.90, 120.55),
}
_COUNTY_PAD = 0.08


@dataclass(frozen=True)
class StationReading:
    name: str
    rain_mm: float
    distance_km: float
    observed_at: str
    place_name: str = "你的位置"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_station(
    records: list[dict],
    latitude: float,
    longitude: float,
    place_name: str = "你的位置",
) -> StationReading:
    best = None
    best_distance = None
    for record in records:
        lat = _float(_field(record, "LAT", "Station_Latitude", "lat", "latitude"))
        lon = _float(_field(record, "LON", "Station_Longitude", "lon", "longitude"))
        if lat is None or lon is None:
            continue
        distance = haversine_km(latitude, longitude, lat, lon)
        if distance >= 500:
            continue
        if best_distance is None or distance < best_distance:
            best = record
            best_distance = distance
    if best is None or best_distance is None:
        raise LookupError("附近沒有測站")
    # HOUR_24 是 24 小時累積雨量。RAIN 是 60 分鐘，NOW 是本日累積，都不能拿來當這欄。
    rain = _float(_field(best, "HOUR_24", "H_24R"))
    return StationReading(
        name=str(_field(best, "Station_name", "name") or "農業氣象站"),
        rain_mm=0.0 if rain is None else rain,
        distance_km=best_distance,
        observed_at=str(_field(best, "TIME") or ""),
        place_name=place_name,
    )


def fetch_records(timeout: float = 12, *, cities: list[str] | None = None) -> list:
    if cities:
        records = _fetch_cities(cities, timeout)
    else:
        records = _dedupe_records(_fetch_data({}, timeout))
    if not records:
        raise LookupError("氣象站沒有回傳資料")
    return records


def fetch_nearest_station(latitude: float, longitude: float, place_name: str, timeout: float = 12) -> StationReading:
    cities = _counties_for(latitude, longitude)
    return nearest_station(fetch_records(timeout, cities=cities or None), latitude, longitude, place_name)


def fetch_miaoli_station(timeout: float = 12) -> StationReading:
    return fetch_nearest_station(MIAOLI_LAT, MIAOLI_LON, MIAOLI_NAME, timeout)


def _counties_for(latitude: float, longitude: float) -> list[str]:
    matches = []
    for name, (south, north, west, east) in _COUNTY_BOXES.items():
        if (
            south - _COUNTY_PAD <= latitude <= north + _COUNTY_PAD
            and west - _COUNTY_PAD <= longitude <= east + _COUNTY_PAD
        ):
            matches.append(name)
    return matches


def _fetch_data(params: dict, timeout: float) -> list[dict]:
    query = urllib.parse.urlencode({"api_key": API_KEY, **params})
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={"User-Agent": "citrus-irrigation-system"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    records = payload.get("Data") or payload.get("data") or []
    if not isinstance(records, list):
        raise LookupError("氣象站沒有回傳資料")
    return [record for record in records if isinstance(record, dict)]


def _fetch_cities(cities: list[str], timeout: float) -> list[dict]:
    ordered = list(dict.fromkeys(cities))
    if len(ordered) == 1:
        batches = [_fetch_data({"CITY": ordered[0]}, timeout)]
    else:
        batches = []
        errors: list[Exception] = []
        with ThreadPoolExecutor(max_workers=min(4, len(ordered))) as pool:
            futures = [pool.submit(_fetch_data, {"CITY": city}, timeout) for city in ordered]
            for future in futures:
                try:
                    batches.append(future.result())
                except Exception as exc:
                    errors.append(exc)
        if not batches:
            if errors:
                raise errors[0]
            raise LookupError("氣象站沒有回傳資料")
    merged: list[dict] = []
    for batch in batches:
        merged.extend(batch)
    return _dedupe_records(merged)


def _dedupe_records(records: list[dict]) -> list[dict]:
    chosen: dict[str, dict] = {}
    extras: list[dict] = []
    for record in records:
        station_id = record.get("Station_ID")
        if station_id is None or station_id == "":
            extras.append(record)
            continue
        chosen.setdefault(str(station_id), record)
    return [*chosen.values(), *extras]


def _field(record: dict, *keys: str):
    for key in keys:
        if key not in record:
            continue
        value = record[key]
        if value is None or value == "":
            continue
        return value
    return None


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number
