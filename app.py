from __future__ import annotations

import base64
import html
from contextlib import contextmanager
from datetime import date
from functools import lru_cache
from pathlib import Path

import streamlit as st

from citrus_farmer.model import (
    SOIL_NAMES,
    STAGE_PRESETS,
    STAGE_SENTENCE,
    IrrigationInput,
    IrrigationResult,
    calculate,
)
from citrus_farmer.weather import fetch_miaoli_station, fetch_nearest_station

st.set_page_config(
    page_title="今天要不要灌水",
    page_icon=str(Path(__file__).resolve().parent / "images" / "logo.png"),
    layout="centered",
    initial_sidebar_state="collapsed",
)

SOIL_OPTIONS = [
    ("砂土", "sand"),
    ("砂壤土", "sandyLoam"),
    ("壤土", "loam"),
    ("坋壤土", "siltLoam"),
    ("黏壤土", "clayLoam"),
    ("坋黏土", "siltClay"),
    ("黏土", "clay"),
]
ROOT_OPTIONS = [("淺，約 40 公分", "shallow"), ("一般，約 60 公分", "normal"), ("深，約 90 公分", "deep")]
SITUATION_OPTIONS = [
    ("平地一般果園", "general"),
    ("土層比較淺", "shallow"),
    ("山坡地，水不夠", "hillside"),
]
MOISTURE_OPTIONS = [
    ("還濕", "wet"),
    ("普通", "normal"),
    ("有點乾", "dry"),
    ("很乾、葉子軟", "very_dry"),
]
SYSTEM_OPTIONS = [
    ("滴灌，最省水", "drip"),
    ("微噴，用水量中等", "microSprinkler"),
    ("噴灌，最耗水", "sprinkler"),
]
STAGE_OPTIONS = [("照今天自動判斷", "auto")] + [
    (preset["name"], key) for key, preset in STAGE_PRESETS.items()
]
DENSITY_OPTIONS = [("約 300 株，種得比較開", 300), ("約 400 株，常見距離", 400), ("約 600 株，種得比較密", 600), ("自己填", 0)]

_THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800&display=swap');

:root {
    --green: #1b5e20;
    --green-dark: #0d3d14;
    --leaf: #e8f5e9;
    --line: #d7e3d8;
    --ink: #1c241c;
    --muted: #5c6b5e;
    --warn: #e65100;
    --warn-bg: #fff3e0;
    --ok: #2e7d32;
    --ok-bg: #e8f5e9;
    --shadow: 0 8px 24px rgba(27, 94, 32, 0.08);
}

html, body, .stApp, .stAppViewContainer,
[data-testid="stMarkdown"],
[data-testid="stWidgetLabel"],
[data-testid="stCaptionContainer"],
[data-testid="stRadio"] label,
button,
input,
textarea {
    font-family: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif;
    color: var(--ink);
}

.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background: #f3f6f1;
}

#MainMenu,
header[data-testid="stHeader"],
footer,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stHeader"],
[data-testid="stAppDeployButton"],
[data-testid="stMainMenu"],
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"] {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
}

[data-testid="stStatusWidget"] {
    visibility: hidden;
}

.stApp {
    overflow-x: hidden;
}

.block-container,
[data-testid="stMainBlockContainer"] {
    max-width: 736px !important;
    padding-top: 0 !important;
    padding-left: 16px !important;
    padding-right: 16px !important;
    padding-bottom: 48px !important;
}

.farmer-top {
    background: var(--green);
    color: white;
    width: 100vw;
    margin-left: calc(50% - 50vw);
    margin-right: calc(50% - 50vw);
    margin-bottom: 20px;
    padding: 28px 16px 24px;
}

.farmer-top-inner {
    max-width: 704px;
    margin: 0 auto;
}

.site-logo {
    width: 96px;
    height: 96px;
    display: block;
    margin-bottom: 12px;
    background: #fff;
    border-radius: 50%;
    object-fit: cover;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
}

.farmer-top .org {
    margin: 0;
    opacity: 0.85;
    font-size: 0.95rem;
    font-weight: 500;
}

.farmer-top h1 {
    margin: 6px 0 8px;
    font-size: 2rem;
    line-height: 1.25;
    font-weight: 800;
    color: white;
    letter-spacing: 0;
}

.farmer-top .lead {
    margin: 0;
    font-size: 1.05rem;
    line-height: 1.5;
    opacity: 0.95;
}

[data-testid="stMarkdown"]:has(.farmer-top) {
    margin-bottom: 0;
}

[data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] {
    background: #ffffff;
    border: 1px solid var(--line) !important;
    border-radius: 18px !important;
    box-shadow: var(--shadow);
    padding: 18px 16px 12px !important;
    margin-bottom: 4px;
}

.section-title {
    margin: 0 0 12px;
    font-size: 1.25rem;
    font-weight: 800;
    line-height: 1.3;
    color: var(--ink);
}

[data-testid="stMarkdown"]:has(.section-title) {
    margin-bottom: 0.15rem;
}

[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label {
    font-weight: 700 !important;
    color: var(--ink) !important;
    font-size: 1.02rem !important;
}

[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p {
    color: var(--muted) !important;
    font-size: 0.95rem !important;
}

/* Streamlit 深色主題的淺字配上淺底會看不見，這裡一律改成深字。 */
.stApp [data-testid="stMarkdownContainer"] p,
.stApp [data-testid="stMarkdownContainer"] li,
.stApp [data-testid="stMarkdownContainer"] span,
.stApp [data-testid="stWidgetLabel"] p,
.stApp [data-testid="stWidgetLabel"] label,
.stApp [data-testid="stRadio"] p,
.stApp [data-testid="stRadio"] span,
.stApp [data-testid="stRadio"] label,
.stApp [data-testid="stCheckbox"] p,
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] div,
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] span,
.stApp [data-testid="stNumberInput"] input {
    color: #1c241c !important;
}

.farmer-top,
.farmer-top p,
.farmer-top h1,
.farmer-top .org,
.farmer-top .lead {
    color: #ffffff !important;
}

[data-baseweb="select"] > div {
    background-color: #ffffff !important;
    color: #1c241c !important;
}

[data-testid="stRadioGroup"] {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

[data-testid="stRadioGroup"][aria-orientation="vertical"] {
    flex-direction: column;
    align-items: stretch;
}

[data-testid="stRadioOption"] {
    background: #fff;
    border: 2px solid var(--line);
    border-radius: 12px;
    padding: 10px 12px !important;
    margin: 0 !important;
    min-height: 48px;
    align-items: center;
    transition: background 0.15s ease, border-color 0.15s ease;
}

[data-testid="stRadioGroup"][aria-orientation="vertical"] > div,
[data-testid="stRadioGroup"][aria-orientation="vertical"] [data-testid="stRadioOption"] {
    width: 100%;
}

[data-testid="stRadioOption"][data-selected="true"] {
    border-color: var(--green);
    background: var(--leaf);
    box-shadow: inset 0 0 0 1px var(--green);
}

[data-testid="stRadioOption"] p {
    font-size: 1rem;
    font-weight: 700;
    color: var(--ink);
}

[data-baseweb="select"] > div,
[data-testid="stNumberInput"] input,
[data-testid="stTextInput"] input {
    border-radius: 12px !important;
    border-color: var(--line) !important;
    min-height: 48px;
    background: #fff;
}

[data-testid="stNumberInput"] button {
    border-color: var(--line) !important;
    color: var(--green) !important;
}

[data-testid="stCheckbox"] label p {
    font-weight: 700;
}

.stApp button[kind="primary"] {
    background: var(--green) !important;
    border: 0 !important;
    color: #fff !important;
    border-radius: 12px !important;
    min-height: 64px !important;
    font-size: 1.3rem !important;
    font-weight: 800 !important;
    box-shadow: 0 8px 18px rgba(27, 94, 32, 0.18);
}

.stApp button[kind="primary"] p,
.stApp button[kind="primary"] span,
.stApp button[kind="primary"] [data-testid="stMarkdownContainer"] p,
.stApp button[kind="primary"] [data-testid="stMarkdownContainer"] span,
.stApp button[kind="primary"]:hover p,
.stApp button[kind="primary"]:hover span {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}

.stApp button[kind="primary"]:hover {
    background: var(--green-dark) !important;
    border: 0 !important;
}

.stApp button[kind="secondary"] {
    background: #fff !important;
    color: var(--green) !important;
    border: 2px solid var(--green) !important;
    border-radius: 12px !important;
    min-height: 52px !important;
    font-weight: 800 !important;
}

.stApp button[kind="secondary"] p,
.stApp button[kind="secondary"] span,
.stApp button[kind="secondary"] [data-testid="stMarkdownContainer"] p,
.stApp button[kind="secondary"] [data-testid="stMarkdownContainer"] span,
.stApp button[kind="secondary"]:hover p,
.stApp button[kind="secondary"]:hover span {
    color: #1b5e20 !important;
    -webkit-text-fill-color: #1b5e20 !important;
}

.stApp button[kind="secondary"]:hover {
    background: var(--leaf) !important;
    border: 2px solid var(--green) !important;
}

/* 下拉選單改用 React Aria，選項文字要壓成深色，底色保持白。 */
.stApp [data-testid="stSelectbox"] [role="group"],
.stApp [data-testid="stSelectbox"] input[role="combobox"] {
    background-color: #ffffff !important;
    color: #1c241c !important;
    -webkit-text-fill-color: #1c241c !important;
}

.stApp button:focus-visible {
    outline: 3px solid #e8a317;
    outline-offset: 2px;
}

.station-card {
    margin-top: 4px;
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--leaf);
    border: 2px solid var(--green);
    color: var(--ink);
    line-height: 1.5;
}

.station-card strong {
    display: block;
    margin-bottom: 4px;
}

[data-testid="stAlert"] {
    border-radius: 12px;
}

.result {
    border-radius: 18px;
    padding: 22px 18px;
    margin: 8px 0 16px;
}

.result.need {
    background: var(--warn-bg);
    border: 3px solid var(--warn);
}

.result.ok {
    background: var(--ok-bg);
    border: 3px solid var(--ok);
}

.result h2 {
    margin: 0 0 8px;
    font-size: 2rem;
    line-height: 1.25;
    font-weight: 800;
    color: var(--ink);
}

.metric-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin: 8px 0 4px;
}

.metric-kicker {
    margin: 0;
    color: var(--muted);
    font-weight: 700;
    font-size: 0.95rem;
}

.stMarkdown p.liters,
p.liters {
    font-size: 2.75rem !important;
    font-weight: 800 !important;
    line-height: 1.1 !important;
    margin: 2px 0 0 !important;
    color: var(--ink) !important;
}

.stMarkdown p.liters span,
p.liters span {
    font-size: 1.2rem !important;
    font-weight: 700 !important;
}

.stMarkdown p.metric-kicker,
p.metric-kicker {
    margin: 0 !important;
    color: var(--muted) !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
}

.say {
    font-size: 1.08rem;
    line-height: 1.55;
    margin: 10px 0 0;
    color: var(--ink);
}

.say.shortfall {
    background: #fff;
    border-radius: 12px;
    padding: 10px 12px;
    font-weight: 700;
}

[data-testid="stMarkdown"]:has(.result) {
    margin-bottom: 0;
}

[data-testid="stExpander"] {
    background: #fff;
    border: 1px solid var(--line) !important;
    border-radius: 18px !important;
    box-shadow: var(--shadow);
    overflow: hidden;
}

[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span {
    font-weight: 700;
}

@media (max-width: 520px) {
    .farmer-top h1 {
        font-size: 1.7rem;
    }
    .metric-row {
        grid-template-columns: 1fr;
    }
    .liters {
        font-size: 2.3rem;
    }
}
"""


@lru_cache(maxsize=1)
def _logo_uri() -> str:
    logo_path = Path(__file__).resolve().parent / "images" / "logo.png"
    encoded = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _render_header() -> None:
    """隱藏 Streamlit 預設介面，並畫出綠色頁首。樣式和頁首放在同一塊，避免上方多出空白。"""
    logo = _logo_uri()
    st.html(
        f"<style>{_THEME_CSS}</style>"
        '<header class="farmer-top">'
        '<div class="farmer-top-inner">'
        f'<img class="site-logo" src="{logo}" alt="苗栗區農業改良場">'
        '<p class="org">苗栗區農業改良場</p>'
        "<h1>今天要不要灌水</h1>"
        "<p class=\"lead\">可讀附近農業氣象站的雨量，再按一下就知道每株幾公升、一分地幾噸。</p>"
        "</div></header>"
    )


@contextmanager
def _section(title: str):
    with st.container(border=True):
        st.markdown(f'<p class="section-title">{html.escape(title)}</p>', unsafe_allow_html=True)
        yield


_LOCATE = st.components.v2.component(
    "farmer_geolocation",
    html='<button type="button" class="locate">用我的位置讀測站</button>',
    css="""
    button.locate {
        width: 100%;
        min-height: 52px;
        border: 0;
        border-radius: 12px;
        background: #1b5e20;
        color: white;
        font-family: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif;
        font-size: 1rem;
        font-weight: 800;
        cursor: pointer;
    }
    button.locate:disabled { opacity: 0.7; }
    """,
    js="""
    export default function(component) {
        const { setTriggerValue, parentElement } = component;
        const button = parentElement.querySelector("button.locate");
        if (!button || button.dataset.bound) {
            return;
        }
        button.dataset.bound = "1";
        button.onclick = () => {
            const label = "用我的位置讀測站";
            const finish = (payload) => {
                setTriggerValue("location", payload);
                button.disabled = false;
                button.textContent = label;
            };
            button.disabled = true;
            button.textContent = "正在取得位置…";
            if (!navigator.geolocation) {
                finish({ error: "這個瀏覽器不能定位。可以改用苗栗農改場附近的測站。" });
                return;
            }
            navigator.geolocation.getCurrentPosition(
                (pos) => finish({
                    lat: pos.coords.latitude,
                    lon: pos.coords.longitude,
                    error: null
                }),
                () => finish({ error: "沒有拿到位置。請允許定位，或改用苗栗農改場附近的測站。" }),
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
            );
        };
    }
    """,
)


def _label(options, value):
    for label, item in options:
        if item == value:
            return label
    return options[0][0]


def _value(options, label):
    for text, item in options:
        if text == label:
            return item
    return options[0][1]


def _load_station(loader) -> None:
    try:
        st.session_state["station_reading"] = loader()
        st.session_state.pop("station_error", None)
    except Exception:
        st.session_state.pop("station_reading", None)
        st.session_state["station_error"] = "測站暫時讀不到，請改選雨量。"


def _rain_mm(choice: str, custom_mm: float, use_station: bool) -> float:
    station = st.session_state.get("station_reading")
    if use_station and station is not None:
        return station.rain_mm
    if choice == "只有一點":
        return 2
    if choice == "小雨":
        return 10
    if choice == "自己填毫米":
        return max(0.0, float(custom_mm))
    return 0


def _show_result(result: IrrigationResult) -> None:
    kind = "need" if result.irrigate else "ok"
    liters = round(result.liters_per_plant)
    tons = f"{result.tons_per_fen:.1f}"
    trees = round(result.trees_per_fen)
    parts = [f"<h2>{html.escape(result.headline)}</h2>"]
    if result.irrigate:
        parts.append(
            '<div class="metric-row">'
            f'<div><p class="metric-kicker">每株</p><p class="liters">{liters} <span>公升</span></p></div>'
            f'<div><p class="metric-kicker">一分地</p><p class="liters">{tons} <span>噸</span></p></div>'
            "</div>"
        )
        parts.append(
            f'<p class="say">{html.escape(result.system_name)}每株大約灌 {liters} 公升。'
            f"一分地大約 {trees} 株，共 {tons} 噸。</p>"
        )
        if result.shortfall_mm > 0:
            parts.append(
                f'<p class="say shortfall">灌完土還是偏乾，還差 {result.shortfall_mm:.1f} 毫米。明天再算一次。</p>'
            )
        parts.append('<p class="say">同樣把 10 毫米的水送進土裡：滴灌最省，微噴居中，噴灌最耗水。</p>')
    else:
        parts.append(
            '<div class="metric-row">'
            f'<div><p class="metric-kicker">一分地</p><p class="liters">{tons} <span>噸</span></p></div>'
            "</div>"
        )
        if result.headline == "今天先不用灌" and result.days_until:
            extra = ""
            if result.stage_fixed:
                extra = f"這幾天先假設還是「{html.escape(result.stage_name)}」。"
            parts.append(f'<p class="say">如果後面沒下雨，大約 {result.days_until} 天後再來看。{extra}</p>')

    sentence = STAGE_SENTENCE.get(result.stage_name, "")
    parts.append(f'<p class="say">現在是{html.escape(result.stage_name)}。{html.escape(sentence)}</p>')
    st.markdown(f'<div class="result {kind}">{"".join(parts)}</div>', unsafe_allow_html=True)

    with st.expander("為什麼是這個結果"):
        rows = [
            f"今天雨量 {result.rainfall_mm:.1f} 毫米，有效雨量 {result.effective_rain:.1f} 毫米。",
            f"灌溉前耗水量 {result.deficit_before:.1f} 毫米，耗水限值 RAM {result.ram:.1f} 毫米。",
            f"進土 {result.soil_gain_mm:.0f} 毫米。",
        ]
        if result.irrigate:
            rows.append(f"灌完還差 {result.shortfall_mm:.1f} 毫米。")
        if result.stage_fixed and result.days_until and not result.irrigate:
            rows.append(f"往後天數假設時期維持在{result.stage_name}。")
        for row in rows:
            st.write("・ " + row)


def main() -> None:
    _render_header()
    today = date.today()

    with _section("1. 今天"):
        st.write(f"今天是 {today.year}年{today.month}月{today.day}日")
        here, miaoli = st.columns(2)
        with here:
            located = _LOCATE(on_location_change=lambda: None)
        with miaoli:
            use_miaoli = st.button("改用苗栗農改場附近測站", use_container_width=True)
        if use_miaoli:
            _load_station(lambda: fetch_miaoli_station())
        location = getattr(located, "location", None) if located is not None else None
        if isinstance(location, dict):
            token = (location.get("lat"), location.get("lon"), location.get("error"))
            if st.session_state.get("location_token") != token:
                st.session_state["location_token"] = token
                if location.get("error"):
                    st.session_state["station_error"] = location["error"]
                elif location.get("lat") is not None:
                    key = (round(float(location["lat"]), 4), round(float(location["lon"]), 4))
                    st.session_state["located_key"] = key
                    _load_station(lambda: fetch_nearest_station(key[0], key[1], "你的位置"))
        station = st.session_state.get("station_reading")
        if st.session_state.get("station_error"):
            st.error(st.session_state["station_error"])
        if station is not None:
            observed = station.observed_at or "測站未提供"
            st.markdown(
                '<div class="station-card">'
                f"<strong>{html.escape(station.name)}測站</strong>"
                f"距離{html.escape(station.place_name)} {station.distance_km:.1f} 公里。"
                f"24 小時雨量 {station.rain_mm:.1f} 毫米。更新時間 {html.escape(observed)}。"
                "</div>",
                unsafe_allow_html=True,
            )

        use_station = False
        if station is not None:
            use_station = st.checkbox("這次用測站的 24 小時雨量", value=True)

        rain_choice = st.radio("今天下雨了嗎？", ["沒下雨", "只有一點", "小雨", "自己填毫米"], horizontal=True)
        custom_mm = 0.0
        if rain_choice == "自己填毫米":
            custom_mm = st.number_input("今天雨量（毫米）", min_value=0.0, max_value=500.0, value=0.0, step=0.1)
        st.caption("只有一點不到 3 毫米，幾乎不算。小雨大約 10 毫米。")

    with _section("2. 果樹"):
        stage_label = st.selectbox("現在果樹在哪個時期？", [item[0] for item in STAGE_OPTIONS])
        stage_mode = _value(STAGE_OPTIONS, stage_label)
        if stage_mode == "auto":
            preview = calculate(
                IrrigationInput(
                    on_date=today,
                    plant_age=8,
                    plant_density=400,
                    density_level="low",
                    soil_type="loam",
                    root="normal",
                    situation="general",
                    moisture="normal",
                    rainfall_mm=0,
                    system="drip",
                    stage_mode="auto",
                )
            )
            st.caption(f"依今天判斷，現在是{preview.stage_name}。如果園裡不是這個時期，請自己選。")
        else:
            st.caption(STAGE_SENTENCE.get(STAGE_PRESETS[stage_mode]["name"], ""))

        age = int(st.number_input("樹大約幾年", min_value=1, max_value=50, value=8, step=1))
        density_label = st.radio("一公頃大概幾株", [item[0] for item in DENSITY_OPTIONS])
        density = _value(DENSITY_OPTIONS, density_label)
        if density == 0:
            density = int(st.number_input("一公頃幾株", min_value=100, max_value=2000, value=400, step=10))
        density_level = "low"
        if age < 10:
            spacing = st.radio("未滿 10 年的樹，種得密還是疏？", ["比較疏", "比較密"], horizontal=True)
            density_level = "high" if spacing == "比較密" else "low"
            st.caption("這只會稍微改變幼樹每天耗水，通常不會改這一劑要灌幾公升。")

    with _section("3. 土和果園"):
        soil = _value(SOIL_OPTIONS, st.selectbox("土是哪一種", [item[0] for item in SOIL_OPTIONS], index=2))
        root = _value(ROOT_OPTIONS, st.radio("根大概多深", [item[0] for item in ROOT_OPTIONS], index=1))
        situation = _value(SITUATION_OPTIONS, st.radio("果園情況", [item[0] for item in SITUATION_OPTIONS]))
        if situation == "hillside":
            st.caption("山坡地的耗水限值設高一點，土可以再乾一些才建議灌，不是每次少灌幾公升。")
        elif situation == "shallow":
            st.caption("土層淺，耗水限值設低一點，不要讓土乾太久。")
        moisture = _value(MOISTURE_OPTIONS, st.radio("現在土摸起來", [item[0] for item in MOISTURE_OPTIONS], index=1, horizontal=True))
        st.caption("這只看你現在摸到的土。下次打開要重選，不會沿用上次算完的耗水量。不確定就選「普通」。")

    with _section("4. 怎麼灌"):
        system = _value(SYSTEM_OPTIONS, st.radio("園裡用哪一種", [item[0] for item in SYSTEM_OPTIONS]))
        st.caption("同樣把 10 毫米的水送進土裡：滴灌最省，微噴居中，噴灌最耗水。")

    if st.button("看今天要不要灌", type="primary", use_container_width=True):
        rainfall = _rain_mm(rain_choice, custom_mm, use_station and station is not None)
        result = calculate(
            IrrigationInput(
                on_date=today,
                plant_age=age,
                plant_density=float(density),
                density_level=density_level,
                soil_type=soil,
                root=root,
                situation=situation,
                moisture=moisture,
                rainfall_mm=rainfall,
                system=system,
                stage_mode=stage_mode,
            )
        )
        _show_result(result)
        st.caption(f"土壤是{SOIL_NAMES[soil]}。")


if __name__ == "__main__":
    main()
