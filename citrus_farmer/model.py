"""農民版逐日水分收支。

每次計算的初始耗水量只由這一次的「土摸起來」和當天 RAM 決定，
不讀取、也不寫入上一次的灌後耗水量。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

SOIL_FC_PER_CM = {
    "sand": 0.47,
    "sandyLoam": 1.28,
    "loam": 1.92,
    "siltLoam": 2.23,
    "clayLoam": 2.33,
    "siltClay": 2.30,
    "clay": 2.30,
}

SOIL_NAMES = {
    "sand": "砂土",
    "sandyLoam": "砂壤土",
    "loam": "壤土",
    "siltLoam": "坋壤土",
    "clayLoam": "黏壤土",
    "siltClay": "坋黏土",
    "clay": "黏土",
}

ROOT_DEPTH_CM = {
    "shallow": 40,
    "normal": 60,
    "deep": 90,
}

MANAGEMENT = {
    "general": (0.35, 0.45),
    "shallow": (0.35, 0.40),
    "hillside": (0.40, 0.57),
}

KC_DAYS = [0, 67, 87, 97, 111, 170, 200, 340, 366]
KC_VALUES = [0.3, 0.3, 0.5, 0.5, 1.35, 1.35, 1.0, 1.0, 0.3]
KC_BASE_MIN = 0.3
KC_BASE_MAX = 1.35

KC_STAGES = [
    (0, 67, "萌芽前"),
    (67, 97, "春梢萌發"),
    (97, 170, "枝梢旺盛"),
    (170, 340, "果實膨大至轉色"),
    (340, 366, "成熟"),
]

RAM_DAYS = [0, 60, 97, 280, 310, 366]
RAM_SYMBOLS = ["d", "d", "c", "c", "d", "d"]

STAGE_PRESETS = {
    "prebud": {"name": "萌芽前", "base_kc": 0.3, "cd": "d"},
    "spring": {"name": "春梢萌發", "base_kc": 0.4, "cd": "mix"},
    "shoot": {"name": "枝梢旺盛", "base_kc": 0.9, "cd": "c"},
    "fruit": {"name": "果實膨大至轉色", "base_kc": 1.35, "cd": "c"},
    "mature": {"name": "成熟", "base_kc": 0.65, "cd": "d"},
}

STAGE_SENTENCE = {
    "萌芽前": "還沒萌芽，需水少。",
    "春梢萌發": "春梢正在長，不要讓土乾太久。",
    "枝梢旺盛": "枝梢長得快，注意土不要乾透。",
    "果實膨大至轉色": "果實正在長大，這段比較不能缺水。",
    "成熟": "果實接近採收，可以稍為控水，但不要乾到缺水。",
}

SYSTEMS = {
    "drip": {"name": "滴灌", "efficiency": 0.925, "interception": 0.75},
    "microSprinkler": {"name": "微噴", "efficiency": 0.875, "interception": 0.75},
    "sprinkler": {"name": "噴灌", "efficiency": 0.825, "interception": 2.0},
}

ETO_A = 0.0133
ETO_B = -2.56
ETO_H = 1600
KS_FRACTION = 0.67
RAIN_INTERCEPTION_MM = 3.0
SOIL_GAIN_MM = 10.0
IRRIGATE_MARGIN_MM = 2.0
FEN_SQUARE_METERS = 293.4 / 0.3025
MAX_LOOKAHEAD_DAYS = 120


@dataclass(frozen=True)
class IrrigationInput:
    on_date: date
    plant_age: int
    plant_density: float
    density_level: str
    soil_type: str
    root: str
    situation: str
    moisture: str
    rainfall_mm: float
    system: str
    stage_mode: str = "auto"


@dataclass(frozen=True)
class IrrigationResult:
    on_date: date
    day_index: int
    stage_name: str
    stage_fixed: bool
    fc: float
    ram: float
    kc: float
    eto: float
    ks: float
    etc: float
    rainfall_mm: float
    effective_rain: float
    initial_deficit: float
    deficit_before: float
    margin: float
    irrigate: bool
    soil_gain_mm: float
    applied_mm: float
    liters_per_plant: float
    trees_per_fen: float
    tons_per_fen: float
    deficit_after: float
    shortfall_mm: float
    days_until: int | None
    headline: str
    close_call: bool
    system_name: str


def day_index(on_date: date) -> int:
    start = date(on_date.year, 1, 1)
    return max(0, min(366, (on_date - start).days))


def _interpolate(x: float, days: list[int], values: list[float]) -> float:
    if x <= days[0]:
        return values[0]
    if x >= days[-1]:
        return values[-1]
    for index in range(len(days) - 1):
        left, right = days[index], days[index + 1]
        if left <= x <= right:
            span = right - left
            if span == 0:
                return values[index + 1]
            ratio = (x - left) / span
            return values[index] + ratio * (values[index + 1] - values[index])
    return values[-1]


def _stage_name(x: int) -> str:
    name = KC_STAGES[0][2]
    for start, end, label in KC_STAGES:
        if start <= x <= end:
            name = label
    return name


def _kc_limits(age: int, density_level: str) -> tuple[float, float]:
    if age < 10:
        if density_level == "high":
            return 0.4, 0.75
        return 0.6, 0.8
    if age >= 20:
        return 0.3, 1.35
    peak = 1 + ((age - 10) / 10) * 0.35
    return 0.3, peak


def _scale_kc(base_kc: float, low: float, high: float) -> float:
    ratio = (base_kc - KC_BASE_MIN) / (KC_BASE_MAX - KC_BASE_MIN)
    return low + ratio * (high - low)


def _reference_eto(x: int) -> float:
    import math

    exponential = math.exp(ETO_A * x + ETO_B)
    ux = exponential * ETO_A * ETO_H
    vx = exponential + 1
    return ux / (vx * vx)


def _coefficient(x: int, c_value: float, d_value: float) -> float:
    values = [c_value if symbol == "c" else d_value for symbol in RAM_SYMBOLS]
    return _interpolate(x, RAM_DAYS, values)


def _preset_cd(kind: str, c_value: float, d_value: float) -> float:
    if kind == "c":
        return c_value
    if kind == "d":
        return d_value
    return (c_value + d_value) / 2


def field_capacity(soil_type: str, depth_cm: float) -> float:
    return SOIL_FC_PER_CM[soil_type] * depth_cm


def initial_deficit(ram: float, moisture: str) -> float:
    if moisture == "wet":
        return 0.50 * ram
    if moisture == "normal":
        return 0.90 * ram
    if moisture == "dry":
        return ram + 5
    if moisture == "very_dry":
        return ram + 20
    raise ValueError(f"未知的土濕：{moisture}")


def effective_rain(rainfall_mm: float, capacity_mm: float) -> float:
    if rainfall_mm <= RAIN_INTERCEPTION_MM:
        return 0.0
    pe = rainfall_mm - RAIN_INTERCEPTION_MM
    if capacity_mm <= 0:
        return 0.0
    return min(pe, capacity_mm)


def _applied_mm(system: str) -> float:
    spec = SYSTEMS[system]
    return (SOIL_GAIN_MM + spec["interception"]) / spec["efficiency"]


def _liters_and_tons(applied_mm: float, plant_density: float) -> tuple[float, float, float]:
    liters = applied_mm * (10000 / plant_density)
    trees = plant_density * (FEN_SQUARE_METERS / 10000)
    tons = liters * trees / 1000
    return liters, trees, tons


def _day_state(on_date: date, previous_deficit: float, rainfall_mm: float, inputs: IrrigationInput) -> dict:
    x = day_index(on_date)
    c_value, d_value = MANAGEMENT[inputs.situation]
    preset = STAGE_PRESETS.get(inputs.stage_mode) if inputs.stage_mode != "auto" else None
    if preset:
        base_kc = preset["base_kc"]
        stage = preset["name"]
        cd = _preset_cd(preset["cd"], c_value, d_value)
    else:
        base_kc = _interpolate(x, KC_DAYS, KC_VALUES)
        stage = _stage_name(x)
        cd = _coefficient(x, c_value, d_value)
    low, high = _kc_limits(inputs.plant_age, inputs.density_level)
    kc = _scale_kc(base_kc, low, high)
    depth = ROOT_DEPTH_CM[inputs.root]
    fc = field_capacity(inputs.soil_type, depth)
    ram = fc * cd
    eto = _reference_eto(x)
    ks = (fc - previous_deficit) / (fc * KS_FRACTION)
    ks = min(1.0, max(0.0, ks))
    etc = eto * kc * ks
    pe = effective_rain(rainfall_mm, previous_deficit + etc)
    deficit_before = previous_deficit + etc - pe
    return {
        "day_index": x,
        "stage": stage,
        "stage_fixed": preset is not None,
        "fc": fc,
        "ram": ram,
        "kc": kc,
        "eto": eto,
        "ks": ks,
        "etc": etc,
        "effective_rain": pe,
        "deficit_before": deficit_before,
    }


def _project_days(inputs: IrrigationInput, ending_deficit: float) -> int | None:
    deficit = ending_deficit
    for ahead in range(1, MAX_LOOKAHEAD_DAYS + 1):
        future = inputs.on_date + timedelta(days=ahead)
        state = _day_state(future, deficit, 0.0, inputs)
        if state["deficit_before"] - state["ram"] > IRRIGATE_MARGIN_MM:
            return ahead
        deficit = state["deficit_before"]
    return None


def calculate(inputs: IrrigationInput) -> IrrigationResult:
    state = _day_state(inputs.on_date, 0.0, inputs.rainfall_mm, inputs)
    # D0 depends only on today's RAM and the moisture choice, never on a previous result.
    d0 = initial_deficit(state["ram"], inputs.moisture)
    state = _day_state(inputs.on_date, d0, inputs.rainfall_mm, inputs)
    deficit_before = state["deficit_before"]
    margin = deficit_before - state["ram"]
    irrigate = margin > IRRIGATE_MARGIN_MM
    soil_gain = SOIL_GAIN_MM if irrigate else 0.0
    applied = _applied_mm(inputs.system) if irrigate else 0.0
    liters, trees, tons = _liters_and_tons(applied, inputs.plant_density)
    deficit_after = deficit_before - soil_gain
    shortfall = max(0.0, deficit_after - state["ram"]) if irrigate else 0.0
    days_until = _project_days(inputs, deficit_after)
    close_call = (not irrigate) and (days_until == 1 or 0 < margin <= IRRIGATE_MARGIN_MM)
    if irrigate:
        headline = "今天要灌"
    elif close_call:
        headline = "快到了，明天再看"
    else:
        headline = "今天先不用灌"
    return IrrigationResult(
        on_date=inputs.on_date,
        day_index=state["day_index"],
        stage_name=state["stage"],
        stage_fixed=state["stage_fixed"],
        fc=state["fc"],
        ram=state["ram"],
        kc=state["kc"],
        eto=state["eto"],
        ks=state["ks"],
        etc=state["etc"],
        rainfall_mm=inputs.rainfall_mm,
        effective_rain=state["effective_rain"],
        initial_deficit=d0,
        deficit_before=deficit_before,
        margin=margin,
        irrigate=irrigate,
        soil_gain_mm=soil_gain,
        applied_mm=applied,
        liters_per_plant=liters,
        trees_per_fen=trees,
        tons_per_fen=tons,
        deficit_after=deficit_after,
        shortfall_mm=shortfall,
        days_until=days_until,
        headline=headline,
        close_call=close_call,
        system_name=SYSTEMS[inputs.system]["name"],
    )
