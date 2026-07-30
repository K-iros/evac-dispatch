"""时变淹没图层：按情景加载 landlab OverlandFlow 离线推演帧。

第十一节：scripts/run_flood_sim.py 基于条件化 DEM（Copernicus GLO-30 +
OSM 建筑 +5m / 道路 -0.3m）与漓江分段水位过程线（24h、缓涨→急涨→
临峰趋缓）+ 降雨/排水源项（pluvial 内涝水路）离线推演，导出
backend/data/flood_frames_{scenario}.json。

每帧 geojson 含两类分档面：
- minDepth ∈ {0.05, 0.15, 0.30, 0.60, 1.20, 2.00}：水深渐变着色 +
  画像水深阈值失效判定（轮椅 ≥0.15m、盲人/老人 ≥0.30m）
- minVd ∈ {0.25, 0.40, 0.50}：v·d 行人失稳危险度（功能 B）

每帧另带 clock（模拟时钟）、stage_m/warn_m（阳朔站绝对水位/超警幅度）。
预计算文件缺失时回退演示帧（同构字段，保证接口一致）。
"""

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from app.models.schemas import FloodFrame

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

#: 情景预设（功能 C）：与 scripts/run_flood_sim.py 的 SCENARIOS 对齐。
#: 措辞用"情景"不用"复现"——阳朔断面无完整流量过程线，按洪峰水位反推
SCENARIOS: dict[str, str] = {
    "s30": "30年一遇",
    "s2024": "2024-06 漓江洪水情景",
    "extreme": "极端情景",
}
DEFAULT_SCENARIO = "s2024"

# 与 run_flood_sim.py 一致的显示口径 / 过程线（回退帧与出发时间计算共用）
SIM_T0 = datetime(2024, 6, 19, 0, 0)
BASE_STAGE = 105.5
WARN_STAGE = 109.5
TOTAL_MIN = 1440
FRAME_STEP_MIN = 60
_HYDROGRAPHS: dict[str, list[tuple[int, float]]] = {
    "s30": [(0, 0.0), (720, 0.8), (1200, 3.8), (1440, 4.2)],
    "s2024": [(0, 0.0), (720, 1.0), (1200, 5.0), (1440, 5.5)],
    "extreme": [(0, 0.0), (600, 1.5), (1140, 6.4), (1440, 7.0)],
}


def water_level_at(minute: int, scenario: str = DEFAULT_SCENARIO) -> float:
    """分段过程线水位涨幅（米）：缓涨→急涨→临峰趋缓（线性插值）。"""
    points = _HYDROGRAPHS.get(scenario, _HYDROGRAPHS[DEFAULT_SCENARIO])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if minute <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (max(minute, x0) - x0) / (x1 - x0)
    return points[-1][1]


def sim_clock(minute: int) -> str:
    """模拟分钟 → 模拟时钟 ISO 时刻（T0 = 2024-06-19 00:00）。"""
    return (SIM_T0 + timedelta(minutes=minute)).isoformat()


@lru_cache(maxsize=4)
def _load_precomputed(scenario: str) -> tuple[FloodFrame, ...] | None:
    """加载该情景的 landlab 离线推演帧；文件缺失或损坏返回 None。"""
    path = DATA_DIR / f"flood_frames_{scenario}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return tuple(FloodFrame(**f) for f in raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def compute_flood_frames(scenario: str = DEFAULT_SCENARIO) -> list[FloodFrame]:
    """返回该情景的时变淹没图层序列（预计算帧缺失时回退演示帧）。"""
    if scenario not in SCENARIOS:
        scenario = DEFAULT_SCENARIO
    precomputed = _load_precomputed(scenario)
    if precomputed:
        return list(precomputed)
    return _demo_frames(scenario)


def _demo_frames(scenario: str) -> list[FloodFrame]:
    """演示回退帧：进水点漓江河道，嵌套矩形模拟深度/流速分档。"""
    frames: list[FloodFrame] = []
    cx, cy = 110.4962, 24.7802  # 占位进水点：漓江河道，漫溢后侵入西岸老城区
    peak = _HYDROGRAPHS.get(scenario, _HYDROGRAPHS[DEFAULT_SCENARIO])[-1][1]
    for minute in range(0, TOTAL_MIN + 1, FRAME_STEP_MIN):
        rise = water_level_at(minute, scenario)
        r = 0.001 + (rise / peak) * 0.008
        features = []
        # 浅→深嵌套：深度分档 + 中心 v·d 急流危险面
        for prop, value, scale in (
            ("minDepth", 0.05, 1.0),
            ("minDepth", 0.15, 0.7),
            ("minDepth", 0.30, 0.45),
            ("minVd", 0.25, 0.3),
            ("minVd", 0.50, 0.18),
        ):
            rr = r * scale
            features.append(
                {
                    "type": "Feature",
                    "properties": {prop: value},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [cx - rr, cy - rr],
                                [cx + rr, cy - rr],
                                [cx + rr, cy + rr],
                                [cx - rr, cy + rr],
                                [cx - rr, cy - rr],
                            ]
                        ],
                    },
                }
            )
        stage = BASE_STAGE + rise
        frames.append(
            FloodFrame(
                minute=minute,
                water_level=round(rise, 2),
                stage_m=round(stage, 2),
                warn_m=round(stage - WARN_STAGE, 2),
                clock=sim_clock(minute),
                geojson={"type": "FeatureCollection", "features": features},
            )
        )
    return frames
