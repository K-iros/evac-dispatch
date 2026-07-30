"""演示调度数据 —— 加载扩容数据集并按情景反推最迟出发时间。

演示城镇：广西阳朔县城（第十节城镇验证选定）。第十二节 P0
「扩充数据规模」后，实体与路线不再硬编码于此，而是由
scripts/gen_scale_dataset.py 生成 backend/data/yangshuo_schedule.json
（24 户 / 10 帮扶者 / 4 避难所，坐标均为 OSM 真实地物，路线由
Valhalla pedestrian(wheelchair/blind/foot) 实算 + RDP 简化；匹配为
距离贪心 + 容量上限的预匹配，真实时间窗匹配算法属 P1 项）。

第十一节"最迟出发时间真实化"：latestDeparture / arriveBy 不是
mock 常量，而是由该情景的 landlab 水深场沿路径反推（departure 模块，
路段失效 = 画像水深阈值 或 v·d 失稳超限），与时间轴同一模拟时钟。
"""

import json
import math
from functools import lru_cache
from pathlib import Path

from app.core.departure import latest_departure_steps, point_flooded_minute
from app.core.flood import DEFAULT_SCENARIO, SCENARIOS, compute_flood_frames, sim_clock
from app.models.schemas import (
    AccessCase,
    Assignment,
    Evacuee,
    Helper,
    LngLat,
    ScheduleState,
    Shelter,
    ShelterTransfer,
)

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "yangshuo_schedule.json"

# 与前端 routeUtils 一致的步速（m/s）：接人段帮扶者独行 / 护送段按画像折减
PICKUP_SPEED = 1.4
ESCORT_SPEED = {"wheelchair": 0.9, "blind": 0.9, "elderly": 0.7}
#: 未匹配户（无路线）按住址被淹时刻倒扣的撤离缓冲（分钟）
NO_ROUTE_BUFFER_MIN = 30.0


@lru_cache(maxsize=1)
def _load_dataset() -> dict:
    """扩容数据集（gen_scale_dataset.py 产出，camelCase 字段）。"""
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """球面距离（米），与前端 routeUtils.haversine 一致。"""
    rad = math.pi / 180
    d_lat = (b[1] - a[1]) * rad
    d_lng = (b[0] - a[0]) * rad
    s = (
        math.sin(d_lat / 2) ** 2
        + math.cos(a[1] * rad) * math.cos(b[1] * rad) * math.sin(d_lng / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(s))


def _split_index(route: list[tuple[float, float]], home: tuple[float, float]) -> int:
    """以离住址最近的路径顶点为界，拆分接人段/护送段（与前端一致）。"""
    return min(range(len(route)), key=lambda i: _haversine_m(route[i], home))


def _segment_durations_min(
    route: list[tuple[float, float]], split_idx: int, profile: str
) -> list[float]:
    """各小段通行耗时（分钟）：接人段帮扶者独行，护送段按画像折减。"""
    durations = []
    for i in range(len(route) - 1):
        speed = PICKUP_SPEED if i < split_idx else ESCORT_SPEED[profile]
        durations.append(_haversine_m(route[i], route[i + 1]) / speed / 60)
    return durations


@lru_cache(maxsize=4)
def build_mock_schedule(scenario: str = DEFAULT_SCENARIO) -> ScheduleState:
    """构建该情景的调度态势：最迟出发时间由水深场沿路径反推。"""
    if scenario not in SCENARIOS:
        scenario = DEFAULT_SCENARIO
    data = _load_dataset()
    frames = compute_flood_frames(scenario)
    horizon = float(frames[-1].minute) if frames else 1440.0
    ev_by_id = {e["id"]: e for e in data["evacuees"]}

    assignments: list[Assignment] = []
    #: evacuee id → 主路线的（帮扶者出发分钟, 接人段耗时）
    primary_dep: dict[str, tuple[float, float]] = {}
    #: 串行链时间口径一致性（第十三节第 6 项 (a)）：帮扶者 →
    #: 前序主派任务从 T0 即刻执行的累计完成时刻（= 本单最早可行开始）
    chain_earliest: dict[str, float] = {}
    for a in sorted(
        data["assignments"],
        key=lambda x: (x["isBackup"], x.get("isFallback", False), x.get("sequence", 1)),
    ):
        ev = ev_by_id[a["evacueeId"]]
        home = (ev["location"]["lng"], ev["location"]["lat"])
        route = [tuple(c) for c in a["route"]]
        split_idx = _split_index(route, home)
        durations = _segment_durations_min(route, split_idx, ev["profile"])
        dep_min, derive_steps = latest_departure_steps(
            route, durations, frames, ev["profile"], horizon_min=horizon,
            scenario_key=scenario, pickup_end_index=split_idx,
        )
        pickup_min = sum(durations[:split_idx])
        # arrive_by = 帮扶者最迟到场时刻 = 最迟出发 + 接人段耗时；
        # 无可行时间窗时以住址被淹时刻兜底（前端 P1 清单会另行标记）
        if dep_min is None:
            flooded = point_flooded_minute(
                home, frames, ev["profile"], scenario_key=scenario
            )
            arrive_min = max((flooded or horizon) - NO_ROUTE_BUFFER_MIN, 0.0)
        else:
            arrive_min = dep_min + pickup_min
        # 串行链一致性：主派任务按 sequence 递进累计最早可行开始时刻，
        # 路线反推最迟出发 < 最早可行开始 → 不可行排班（红色冲突告警）
        is_primary = not a["isBackup"] and not a.get("isFallback", False)
        earliest: float | None = None
        conflict = False
        if is_primary:
            earliest = chain_earliest.get(a["helperId"], 0.0)
            conflict = dep_min is None or dep_min < earliest
            # 链上下一单的最早开始 = 本单最早开始 + 本单全程耗时
            chain_earliest[a["helperId"]] = earliest + sum(durations)
        assignments.append(
            Assignment(
                helper_id=a["helperId"],
                evacuee_id=a["evacueeId"],
                shelter_id=a["shelterId"],
                arrive_by=sim_clock(round(arrive_min)),
                is_backup=a["isBackup"],
                is_fallback=a.get("isFallback", False),
                sequence=a.get("sequence", 1),
                route=route,
                foot_route=a.get("footRoute"),
                depart_by=sim_clock(round(dep_min)) if dep_min is not None else None,
                earliest_start=(
                    sim_clock(round(earliest)) if earliest is not None else None
                ),
                conflict=conflict,
                derive_steps=derive_steps,
            )
        )
        if (
            not a["isBackup"]
            and not a.get("isFallback", False)
            and a["evacueeId"] not in primary_dep
        ):
            primary_dep[a["evacueeId"]] = (
                dep_min if dep_min is not None else -1.0,
                pickup_min,
            )

    evacuees: list[Evacuee] = []
    for ev in data["evacuees"]:
        home = (ev["location"]["lng"], ev["location"]["lat"])
        dep = primary_dep.get(ev["id"])
        if dep is not None and dep[0] >= 0:
            # 户的最迟出发 = 帮扶者最迟出发 + 接人段（即离家护送开始时刻）
            latest_min = dep[0] + dep[1]
        else:
            # 无路线/无可行时间窗：住址达到危险阈值时刻 - 撤离缓冲
            flooded = point_flooded_minute(
                home, frames, ev["profile"], scenario_key=scenario
            )
            latest_min = max((flooded or horizon) - NO_ROUTE_BUFFER_MIN, 0.0)
        evacuees.append(
            Evacuee(
                id=ev["id"],
                name=ev["name"],
                profile=ev["profile"],
                address=ev["address"],
                location=LngLat(**ev["location"]),
                latest_departure=sim_clock(round(latest_min)),
                match_status=ev["matchStatus"],
                helper_ids=ev["helperIds"],
                shelter_id=ev["shelterId"],
            )
        )

    helpers = [
        Helper(
            id=h["id"],
            name=h["name"],
            location=LngLat(**h["location"]),
            assigned_evacuee_ids=h["assignedEvacueeIds"],
            available=h["available"],
        )
        for h in data["helpers"]
    ]
    shelters = [
        Shelter(
            id=s["id"],
            name=s["name"],
            location=LngLat(**s["location"]),
            wheelchair_accessible=s["wheelchairAccessible"],
            capacity=s.get("capacity"),
            occupancy=s.get("occupancy"),
            vertical_refuge=s.get("verticalRefuge", False),
        )
        for s in data["shelters"]
    ]

    return ScheduleState(
        alert_level="ready",
        evacuees=evacuees,
        helpers=helpers,
        shelters=shelters,
        assignments=assignments,
        access_cases=[
            AccessCase.model_validate(c) for c in data.get("accessCases", [])
        ],
        shelter_transfers=[
            ShelterTransfer.model_validate(t)
            for t in data.get("shelterTransfers", [])
        ],
    )
