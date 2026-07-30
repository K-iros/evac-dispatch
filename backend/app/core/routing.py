"""Valhalla 路由客户端 —— 画像化无障碍路径计算。

引擎选型（见 PROJECT_CONTEXT 第十节验证结果）：
ORS 公共 API 在国内网络被阻断（DNS 污染 + TLS SNI 阻断），已作废。
改用 Valhalla：公共实例可直连，`pedestrian` costing 原生支持
`type=wheelchair`（自动排除 highway=steps，读取 wheelchair/surface/incline 标签）。

画像策略（见 PROJECT_CONTEXT 第五节）:
- wheelchair: pedestrian + type=wheelchair（注意标签稀疏地区仍可能无解，需回退）
- blind:      pedestrian + type=blind（Valhalla 原生盲人类型：偏好人行道、
              惩罚复杂路口）+ 我方后处理打分（见 score_blind_route）
- elderly:    pedestrian + type=foot + 降速系数

已验证事实（阳朔/重庆/榕江实测）：三地 wheelchair=* 标签趋近于零，
wheelchair 与 foot 返回路径几乎相同 → 引擎无法真正区分无障碍路径，
"无路可走清单"必须由淹没模型 + 后处理打分产出，不能指望引擎。
"""

from typing import Any, Literal

import httpx

Profile = Literal["wheelchair", "blind", "elderly"]

# 公共实例；自部署后改为 http://localhost:8002
VALHALLA_BASE_URL = "https://valhalla1.openstreetmap.de"

#: 画像 → Valhalla pedestrian type + 附加 costing 参数
PROFILE_TO_COSTING: dict[str, dict[str, Any]] = {
    # 轮椅：排除台阶，最大坡度受限，步速慢
    "wheelchair": {"type": "wheelchair", "walking_speed": 3.0, "max_hiking_difficulty": 0},
    # 盲人：可走台阶，但步速打折（0.8-1.0 m/s ≈ 3.1 km/h），路口风险靠后处理打分
    "blind": {"type": "blind", "walking_speed": 3.1},
    # 老人：普通步行降速
    "elderly": {"type": "foot", "walking_speed": 3.6},
}

#: 各画像的路段失效水深阈值（米，见第十节"路段失效判定升级"）
DEPTH_THRESHOLD_M: dict[str, float] = {
    "wheelchair": 0.15,
    "blind": 0.30,
    "elderly": 0.30,
}

#: 各画像的 v·d 失稳阈值（m²/s，功能 B）：行人失稳判据
#: 水深×流速 > 0.5 为成人标准，轮椅/老人更严；路段失效 =
#: 水深超阈 或 v·d 超限（与前端 routeUtils.VD_THRESHOLD 对齐）
VD_THRESHOLD_M2_S: dict[str, float] = {
    "wheelchair": 0.25,
    "blind": 0.50,
    "elderly": 0.40,
}


class NoRouteError(RuntimeError):
    """该画像在当前路网下无可行路径（→ 进入 P0 无路可走清单）。"""


def _costing_options(profile: Profile) -> dict:
    return {"pedestrian": PROFILE_TO_COSTING[profile]}


async def get_route(
    profile: Profile,
    waypoints: list[tuple[float, float]],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """请求 Valhalla route，返回归一化结果。

    Args:
        profile: 画像（wheelchair / blind / elderly）
        waypoints: [(lng, lat), ...]，至少两点；三点即"帮扶者→住址→避难所"
        client: 复用的 HTTP 客户端（批量预计算时传入以复用连接）

    Returns:
        {"coordinates": [(lng, lat), ...], "distance_m": float, "duration_s": float,
         "legs": [{"distance_m": ..., "duration_s": ...}, ...]}

    Raises:
        NoRouteError: Valhalla 返回无路径（该画像走不通）
    """
    if len(waypoints) < 2:
        raise ValueError("waypoints 至少需要两个点")

    body = {
        "locations": [{"lat": lat, "lon": lng} for lng, lat in waypoints],
        "costing": "pedestrian",
        "costing_options": _costing_options(profile),
        "directions_options": {"units": "kilometers"},
    }

    own_client = client is None
    http = client or httpx.AsyncClient(timeout=45)
    try:
        resp = await http.post(f"{VALHALLA_BASE_URL}/route", json=body)
        if resp.status_code != 200:
            # Valhalla 无解时返回 400 + {"error": "No path could be found for input"}
            detail = ""
            try:
                detail = str(resp.json().get("error", ""))
            except Exception:  # noqa: BLE001 响应体非 JSON 时忽略
                detail = resp.text[:200]
            if resp.status_code == 400:
                raise NoRouteError(f"{profile} 无可行路径: {detail}")
            resp.raise_for_status()
        payload = resp.json()
    finally:
        if own_client:
            await http.aclose()

    trip = payload["trip"]
    coordinates: list[tuple[float, float]] = []
    legs: list[dict] = []
    for leg in trip["legs"]:
        pts = decode_polyline6(leg["shape"])
        # 相邻 leg 首尾重合，去重接缝点
        if coordinates and pts and pts[0] == coordinates[-1]:
            pts = pts[1:]
        coordinates.extend(pts)
        legs.append(
            {
                "distance_m": leg["summary"]["length"] * 1000,
                "duration_s": leg["summary"]["time"],
            }
        )

    return {
        "coordinates": coordinates,
        "distance_m": trip["summary"]["length"] * 1000,
        "duration_s": trip["summary"]["time"],
        "legs": legs,
    }


async def get_matrix(
    profile: Profile,
    sources: list[tuple[float, float]],
    targets: list[tuple[float, float]],
    *,
    client: httpx.AsyncClient | None = None,
) -> list[list[float | None]]:
    """画像化耗时矩阵（秒），供 matching 层做帮扶者-残障者匹配。

    不可达单元返回 None（而非 inf），便于上层识别"该帮扶者无法到达该户"。
    """
    body = {
        "sources": [{"lat": lat, "lon": lng} for lng, lat in sources],
        "targets": [{"lat": lat, "lon": lng} for lng, lat in targets],
        "costing": "pedestrian",
        "costing_options": _costing_options(profile),
        "units": "kilometers",
    }
    own_client = client is None
    http = client or httpx.AsyncClient(timeout=60)
    try:
        resp = await http.post(f"{VALHALLA_BASE_URL}/sources_to_targets", json=body)
        resp.raise_for_status()
        payload = resp.json()
    finally:
        if own_client:
            await http.aclose()

    return [
        [cell.get("time") for cell in row]
        for row in payload["sources_to_targets"]
    ]


def decode_polyline6(encoded: str) -> list[tuple[float, float]]:
    """解码 Valhalla 的 polyline6（精度 1e-6，非 Google 的 1e-5）。

    返回 [(lng, lat), ...]，与 GeoJSON 坐标序一致。
    """
    coords: list[tuple[float, float]] = []
    index = 0
    lat = 0
    lng = 0
    length = len(encoded)
    while index < length:
        for axis in range(2):
            shift = 0
            result = 0
            while index < length:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lng += delta
        coords.append((lng / 1e6, lat / 1e6))
    return coords


def score_blind_route(coordinates: list[tuple[float, float]]) -> float:
    """盲人画像后处理打分（越低越好）—— 转折次数惩罚。

    已验证：演示区域 tactile_paving 标签为 0，故打分不依赖盲道，
    以转折次数（每次转向都是迷失风险点）为主要因子。
    路口复杂度与道路等级因子待接入 OSM 标签后补充。
    """
    if len(coordinates) < 3:
        return 0.0

    import math

    turns = 0
    for i in range(1, len(coordinates) - 1):
        (x0, y0), (x1, y1), (x2, y2) = coordinates[i - 1], coordinates[i], coordinates[i + 1]
        a = math.atan2(y1 - y0, x1 - x0)
        b = math.atan2(y2 - y1, x2 - x1)
        deviation = abs(math.degrees(b - a)) % 360
        if deviation > 180:
            deviation = 360 - deviation
        if deviation > 30:  # 30° 以上算一次有效转折
            turns += 1
    return float(turns)
