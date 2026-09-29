"""農業部自動氣象站。座標由畫面提供，雨量在伺服器讀取。"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass

MIAOLI_LAT = 24.5593
MIAOLI_LON = 120.8214
MIAOLI_NAME = "苗栗區農業改良場"
API_URL = "https://data.moa.gov.tw/api/v1/AutoWeatherStationType/"
API_KEY = "IKXAGW0DJ1G90FL4SJ5N364EM567QX"


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
        lat = _float(record.get("Station_Latitude") or record.get("lat") or record.get("latitude"))
        lon = _float(record.get("Station_Longitude") or record.get("lon") or record.get("longitude"))
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
    rain = _float(best.get("H_24R"))
    return StationReading(
        name=str(best.get("Station_name") or best.get("name") or "農業氣象站"),
        rain_mm=0.0 if rain is None else rain,
        distance_km=best_distance,
        observed_at=str(best.get("TIME") or ""),
        place_name=place_name,
    )


def fetch_records(timeout: float = 12) -> list:
    query = urllib.parse.urlencode({"api_key": API_KEY})
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={"User-Agent": "citrus-irrigation-system"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    records = payload.get("Data") or payload.get("data") or []
    if not isinstance(records, list) or not records:
        raise LookupError("氣象站沒有回傳資料")
    return records


def fetch_nearest_station(latitude: float, longitude: float, place_name: str, timeout: float = 12) -> StationReading:
    return nearest_station(fetch_records(timeout), latitude, longitude, place_name)


def fetch_miaoli_station(timeout: float = 12) -> StationReading:
    return fetch_nearest_station(MIAOLI_LAT, MIAOLI_LON, MIAOLI_NAME, timeout)


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number
