import pytest

from citrus_farmer.weather import (
    MIAOLI_LAT,
    MIAOLI_LON,
    _counties_for,
    _dedupe_records,
    fetch_miaoli_station,
    nearest_station,
)


def test_rainfall_station_uses_lat_lon_and_hour_24():
    records = [
        {
            "Station_name": "大潭",
            "Station_ID": "01E390",
            "TIME": "2026/09/29 17:00",
            "LAT": "24.63506600000000",
            "LON": "120.82085000000000",
            "HOUR_24": "1.5",
        },
        {
            "Station_name": "頭汴坑",
            "Station_ID": "01F680",
            "TIME": "2026/09/29 17:00",
            "LAT": "24.11509200000000",
            "LON": "120.81112500000000",
            "HOUR_24": "9",
        },
    ]

    reading = nearest_station(records, MIAOLI_LAT, MIAOLI_LON, "苗栗區農業改良場")

    assert reading.name == "大潭"
    assert reading.rain_mm == 1.5
    assert reading.observed_at == "2026/09/29 17:00"
    assert reading.distance_km < 15


def test_zero_hour_24_is_kept():
    records = [
        {
            "Station_name": "大潭",
            "LAT": "24.635066",
            "LON": "120.820850",
            "HOUR_24": "0",
            "TIME": "2026/09/29 17:00",
        }
    ]

    reading = nearest_station(records, MIAOLI_LAT, MIAOLI_LON)

    assert reading.rain_mm == 0.0


def test_hour_24_wins_over_legacy_rain():
    records = [
        {
            "Station_name": "苗栗",
            "Station_ID": "C0E750",
            "LAT": "24.565",
            "LON": "120.821",
            "HOUR_24": "0",
            "H_24R": "8",
            "TIME": "2026/09/29 17:00",
        }
    ]

    reading = nearest_station(records, MIAOLI_LAT, MIAOLI_LON)

    assert reading.rain_mm == 0.0


def test_legacy_weather_station_fields_still_work():
    records = [
        {
            "Station_name": "公館",
            "Station_Latitude": "24.500000",
            "Station_Longitude": "120.820000",
            "H_24R": "4",
            "TIME": "2026/09/29 16:00",
        }
    ]

    reading = nearest_station(records, MIAOLI_LAT, MIAOLI_LON)

    assert reading.name == "公館"
    assert reading.rain_mm == 4.0


def test_records_without_coordinates_are_skipped():
    records = [
        {"Station_name": "缺座標", "HOUR_24": "5", "Station_ID": "x"},
    ]

    with pytest.raises(LookupError, match="附近沒有測站"):
        nearest_station(records, MIAOLI_LAT, MIAOLI_LON)


def test_city_padding_is_deduped_by_station_id():
    row = {
        "Station_ID": "C0E750",
        "Station_name": "苗栗",
        "LAT": "24.565",
        "LON": "120.821",
        "HOUR_24": "0",
    }
    other = {"Station_ID": "01F680", "Station_name": "頭汴坑", "HOUR_24": "0"}

    merged = _dedupe_records([row, other, dict(row), dict(row)])

    assert [record["Station_ID"] for record in merged] == ["C0E750", "01F680"]
    assert merged[0]["HOUR_24"] == "0"


def test_miaoli_farm_uses_only_miaoli_county():
    assert _counties_for(MIAOLI_LAT, MIAOLI_LON) == ["苗栗縣"]


def test_miaoli_fetch_queries_miaoli_and_reads_hour_24(monkeypatch):
    captured = {}

    def fake_fetch(params, timeout):
        captured["params"] = params
        captured["timeout"] = timeout
        row = {
            "Station_name": "苗栗",
            "Station_ID": "C0E750",
            "LAT": "24.565",
            "LON": "120.821",
            "HOUR_24": "2",
            "TIME": "2026/09/29 17:00",
            "CITY": "苗栗縣",
        }
        return [row, dict(row), dict(row)]

    monkeypatch.setattr("citrus_farmer.weather._fetch_data", fake_fetch)

    reading = fetch_miaoli_station(timeout=7)

    assert captured["params"] == {"CITY": "苗栗縣"}
    assert captured["timeout"] == 7
    assert reading.name == "苗栗"
    assert reading.rain_mm == 2.0
    assert reading.distance_km < 5
    assert reading.place_name == "苗栗區農業改良場"
