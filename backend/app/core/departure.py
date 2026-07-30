"""最迟出发时间计算（核心逻辑，创新②）。

路径 × 时变水深场求交 → 每小段的"失效时刻" → 沿路径反向递推
"最迟出发时间"。第十一节实装：失效判定 = 画像水深阈值 或
v·d 失稳超限（功能 B），淹没帧来自 landlab OverlandFlow 离线推演。

反向递推：设第 i 小段耗时 dur_i、失效时刻 fail_i（该时刻起不可
通行），则从末段向前
    latest = min(latest, fail_i) - dur_i
最终 latest 即整条路径的最迟出发时刻（模拟分钟）；latest < 0
说明任何时刻出发都无法在各段失效前通过 → 无可行时间窗（P1）。
"""

from shapely.geometry import Point, shape
from shapely.prepared import prep

from app.core.routing import DEPTH_THRESHOLD_M, VD_THRESHOLD_M2_S
from app.models.schemas import DeriveStep, FloodFrame

#: (情景键, 水深阈值, vd 阈值) → 逐帧危险面缓存（FloodFrame 含 dict
#: 字段不可哈希，不能直接 lru_cache，按情景键手动缓存）
_HAZARD_CACHE: dict[tuple[str, float, float], list] = {}


def _hazard_polygons(
    scenario_key: str,
    frames: list[FloodFrame],
    depth_thr: float,
    vd_thr: float,
):
    """每帧的危险面（prepared shapely 多边形）：水深超阈 或 v·d 超限。"""
    cache_key = (scenario_key, depth_thr, vd_thr)
    if cache_key in _HAZARD_CACHE:
        return _HAZARD_CACHE[cache_key]
    per_frame = []
    for frame in frames:
        polys = []
        for feat in frame.geojson.get("features", []):
            props = feat.get("properties") or {}
            min_depth = props.get("minDepth")
            min_vd = props.get("minVd")
            if min_depth is not None and min_depth < depth_thr:
                continue
            if min_vd is not None and min_vd < vd_thr:
                continue
            if min_depth is None and min_vd is None:
                continue
            polys.append(prep(shape(feat["geometry"])))
        per_frame.append((frame.minute, polys))
    _HAZARD_CACHE[cache_key] = per_frame
    return per_frame


def _hit(polys, pt: tuple[float, float]) -> bool:
    p = Point(pt)
    return any(g.contains(p) for g in polys)


def segment_failure_minute(
    segment_coords: list[tuple[float, float]],
    frames: list[FloodFrame],
    profile: str,
    scenario_key: str = "default",
) -> float | None:
    """路段首次不可通行的分钟数（端点或中点命中危险面）；始终可通行返回 None。"""
    a, b = segment_coords[0], segment_coords[-1]
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    per_frame = _hazard_polygons(
        scenario_key, frames, DEPTH_THRESHOLD_M[profile], VD_THRESHOLD_M2_S[profile]
    )
    for minute, polys in per_frame:
        if _hit(polys, a) or _hit(polys, mid) or _hit(polys, b):
            return float(minute)
    return None


def latest_departure_steps(
    route_coords: list[tuple[float, float]],
    segment_durations_min: list[float],
    frames: list[FloodFrame],
    profile: str,
    horizon_min: float = 1440.0,
    scenario_key: str = "default",
    pickup_end_index: int = 0,
) -> tuple[float | None, list[DeriveStep]]:
    """倒推最迟出发时刻并保留每步中间量（第十五节：倒推链可解释）。

    Args:
        route_coords: 路径顶点序列 [(lng, lat), ...]
        segment_durations_min: 各小段通行耗时（分钟），len = 顶点数 - 1
        frames: 该情景的推演帧序列
        profile: 画像（决定水深阈值与 v·d 阈值）
        horizon_min: 预报窗口末端——全程不失效时也须在窗口内完成撤离
        pickup_end_index: 接人段/护送段分界顶点序号（小段 i <
            该值为接人段），仅用于标注 DeriveStep.phase

    Returns:
        (最迟出发分钟 | None, 倒推序逐段中间量)：无可行时间窗
        （负值）时首元素为 None，但 steps 仍完整保留以解释原因。
    """
    latest = horizon_min
    steps: list[DeriveStep] = []
    for i in range(len(route_coords) - 2, -1, -1):
        seg = [route_coords[i], route_coords[i + 1]]
        fail = segment_failure_minute(seg, frames, profile, scenario_key)
        clamped = fail is not None and fail < latest
        if fail is not None:
            latest = min(latest, fail)
        latest -= segment_durations_min[i]
        steps.append(
            DeriveStep(
                seg_index=i,
                phase="pickup" if i < pickup_end_index else "escort",
                fail_minute=fail,
                duration_min=round(segment_durations_min[i], 1),
                latest_after=round(latest, 1),
                clamped=clamped,
            )
        )
    return (latest if latest >= 0 else None, steps)


def latest_departure_minutes(
    route_coords: list[tuple[float, float]],
    segment_durations_min: list[float],
    frames: list[FloodFrame],
    profile: str,
    horizon_min: float = 1440.0,
    scenario_key: str = "default",
) -> float | None:
    """倒推整条路径的最迟出发时刻（模拟分钟）。

    无可行时间窗（负值）返回 None；需要逐段中间量时用
    latest_departure_steps。
    """
    latest, _ = latest_departure_steps(
        route_coords,
        segment_durations_min,
        frames,
        profile,
        horizon_min=horizon_min,
        scenario_key=scenario_key,
    )
    return latest


def point_flooded_minute(
    pt: tuple[float, float],
    frames: list[FloodFrame],
    profile: str,
    scenario_key: str = "default",
) -> float | None:
    """某点位（住址/避难所）首次达到该画像危险阈值的分钟数。"""
    per_frame = _hazard_polygons(
        scenario_key, frames, DEPTH_THRESHOLD_M[profile], VD_THRESHOLD_M2_S[profile]
    )
    for minute, polys in per_frame:
        if _hit(polys, pt):
            return float(minute)
    return None
