# -*- coding: utf-8 -*-
"""LLM 语音路书（第十二节 P1）：盲人画像路径 → 自然语言路书 → TTS。

demo 场景「评委闭眼听 30 秒」：选中盲人户 → 前端 speechSynthesis
朗读整段路书。生成链路：

1. 事实提取（纯几何+水深场，不依赖 LLM）：主路线护送段折线 →
   方位角/转角序列 → 转向步骤清单（"沿东南方向直行约 120 米后左转"）；
   逐小段 segment_failure_minute → 最早失效时刻 → 水情提醒
   （这是水动力推演独有的信息，通用导航给不了）；
2. 有 DEEPSEEK_API_KEY 时一次调用 DeepSeek 把结构化步骤润色成
   给视障者的陪同导引口语路书（约 30 秒朗读量）；
3. 无 Key / 失败时模板拼接兜底（source 标注来源，演示不空白）。

接口对任何有主路线的户可用（路书口径 = 护送段：从家到避难所），
前端入口只在盲人户路径卡展示（叙事最强）。
"""

import json
import logging
import math
import os

import httpx

from app.core.departure import segment_failure_minute
from app.core.flood import compute_flood_frames, sim_clock
from app.models.schemas import RoadbookResponse, ScheduleState
from app.services.mock_data import ESCORT_SPEED, _haversine_m, _split_index

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_TIMEOUT = 45.0
COS_LAT = math.cos(24.78 * math.pi / 180)

#: 转向判定阈值（度）：30-60 稍向，>60 明确转向
SLIGHT_TURN_DEG = 30.0
SHARP_TURN_DEG = 60.0

COMPASS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]

#: (scenario, evacuee_id) → LLM 结果缓存（模板兜底不缓存）
_llm_cache: dict[tuple[str, str], RoadbookResponse] = {}


def _bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """方位角（度，0=正北顺时针）。"""
    dx = (b[0] - a[0]) * COS_LAT
    dy = b[1] - a[1]
    return math.degrees(math.atan2(dx, dy)) % 360


def _compass(bearing: float) -> str:
    return COMPASS[round(bearing / 45) % 8]


def _turn_word(prev_bearing: float, bearing: float) -> str | None:
    """两段间的转向词；直行返回 None。"""
    delta = (bearing - prev_bearing + 540) % 360 - 180  # (-180, 180]，正=右转
    if abs(delta) <= SLIGHT_TURN_DEG:
        return None
    side = "右" if delta > 0 else "左"
    return f"{side}转" if abs(delta) > SHARP_TURN_DEG else f"稍向{side}"


def _round_m(meters: float) -> int:
    """步行距离取整到 10 米（口语量纲）。"""
    return max(int(round(meters / 10) * 10), 10)


def _build_steps(escort: list[tuple[float, float]]) -> list[str]:
    """护送段折线 → 转向步骤清单（合并连续直行段）。"""
    if len(escort) < 2:
        return []
    steps: list[str] = []
    acc = _haversine_m(escort[0], escort[1])
    prev_bearing = _bearing_deg(escort[0], escort[1])
    lead = f"沿{_compass(prev_bearing)}方向出发，直行约"
    for i in range(1, len(escort) - 1):
        bearing = _bearing_deg(escort[i], escort[i + 1])
        seg = _haversine_m(escort[i], escort[i + 1])
        turn = _turn_word(prev_bearing, bearing)
        if turn is None:
            acc += seg
        else:
            steps.append(f"{lead} {_round_m(acc)} 米")
            lead = f"{turn}，继续直行约"
            acc = seg
        prev_bearing = bearing
    steps.append(f"{lead} {_round_m(acc)} 米")
    return steps


def _hazard_note(
    escort: list[tuple[float, float]], profile: str, scenario: str
) -> str | None:
    """护送段最早失效时刻 → 水情提醒（水动力推演独有信息）。"""
    frames = compute_flood_frames(scenario)
    earliest: float | None = None
    for i in range(len(escort) - 1):
        fail = segment_failure_minute(
            [escort[i], escort[i + 1]], frames, profile, scenario_key=scenario
        )
        if fail is not None and (earliest is None or fail < earliest):
            earliest = fail
    if earliest is None:
        return None
    clock = sim_clock(round(earliest))[11:16]
    return f"注意：按洪水推演，路线途中路段 {clock} 起积水将超过安全深度，务必在最迟出发时间前通过"


def _build_facts(
    scenario: str, state: ScheduleState, evacuee_id: str
) -> dict | None:
    """路书事实清单（LLM 输入 = 模板输入，同一数据源）。"""
    ev = next((e for e in state.evacuees if e.id == evacuee_id), None)
    if ev is None:
        return None
    primary = next(
        (a for a in state.assignments
         if a.evacuee_id == evacuee_id and not a.is_backup and not a.is_fallback),
        None,
    )
    if primary is None:
        return None
    helper = next((h for h in state.helpers if h.id == primary.helper_id), None)
    shelter = next((s for s in state.shelters if s.id == primary.shelter_id), None)

    route = [tuple(c) for c in primary.route]
    home = (ev.location.lng, ev.location.lat)
    escort = route[_split_index(route, home):]
    dist_m = sum(
        _haversine_m(escort[i], escort[i + 1]) for i in range(len(escort) - 1)
    )
    speed = ESCORT_SPEED[ev.profile]
    return {
        "evacuee": ev,
        "helper": helper,
        "shelter": shelter,
        "steps": _build_steps(escort),
        "hazard": _hazard_note(escort, ev.profile, scenario),
        "distance_km": round(dist_m / 1000, 2),
        "duration_min": max(round(dist_m / speed / 60), 1),
        "depart_by": ev.latest_departure[11:16],
    }


def _template_text(f: dict) -> str:
    """模板兜底：可直接朗读的整段路书。"""
    ev = f["evacuee"]
    shelter_name = f["shelter"].name if f["shelter"] else "避难所"
    helper_name = f["helper"].name if f["helper"] else "帮扶者"
    parts = [
        f"{ev.name}您好，我是{helper_name}。我们现在从家出发，"
        f"前往{shelter_name}，全程约{f['distance_km']}公里，"
        f"步行大约{f['duration_min']}分钟，请抓稳我的手臂，跟着我的口令走。"
    ]
    parts.extend(f"{i}. {s}。" for i, s in enumerate(f["steps"], 1))
    if f["hazard"]:
        parts.append(f"{f['hazard']}。")
    parts.append(f"到达{shelter_name}后请在登记处稍作休息，全程有我陪同，请放心。")
    return "".join(parts)


_SYSTEM_PROMPT = (
    "你是社区防汛疏散的陪同导引播报员。把给定的转向步骤和水情提示，"
    "改写成给视障者的口语路书：第二人称、安抚而清晰，保留每一步的"
    "方向与距离数字，提到路口和转向时给出触觉/听觉提示（如扶稳手臂、"
    "留意路缘），水情提醒必须保留时刻。全文 150-220 字，适合 30 秒左右"
    "朗读，不要列表符号，输出纯文本段落。"
)


def _call_deepseek(api_key: str, facts: dict) -> str:
    payload = {
        "evacuee": facts["evacuee"].name,
        "profile": facts["evacuee"].profile,
        "helper": facts["helper"].name if facts["helper"] else None,
        "shelter": facts["shelter"].name if facts["shelter"] else None,
        "distanceKm": facts["distance_km"],
        "durationMin": facts["duration_min"],
        "departBy": facts["depart_by"],
        "steps": facts["steps"],
        "hazard": facts["hazard"],
    }
    resp = httpx.post(
        DEEPSEEK_URL,
        timeout=DEEPSEEK_TIMEOUT,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "temperature": 0.6,
        },
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def build_roadbook(
    scenario: str, state: ScheduleState, evacuee_id: str
) -> RoadbookResponse | None:
    """语音路书入口：LLM 优先，任何失败走模板兜底；无路线返回 None。"""
    cache_key = (scenario, evacuee_id)
    cached = _llm_cache.get(cache_key)
    if cached is not None:
        return cached

    facts = _build_facts(scenario, state, evacuee_id)
    if facts is None:
        return None

    def _response(source: str, text: str) -> RoadbookResponse:
        return RoadbookResponse(
            evacuee_id=evacuee_id,
            evacuee_name=facts["evacuee"].name,
            helper_name=facts["helper"].name if facts["helper"] else None,
            shelter_name=facts["shelter"].name if facts["shelter"] else None,
            source=source,  # type: ignore[arg-type]
            text=text,
            steps=facts["steps"],
            distance_km=facts["distance_km"],
            duration_min=facts["duration_min"],
        )

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return _response("template", _template_text(facts))
    try:
        result = _response("llm", _call_deepseek(api_key, facts))
        _llm_cache[cache_key] = result
        return result
    except Exception as exc:  # noqa: BLE001 —— 网络/配额/解析失败均兜底
        logger.warning("DeepSeek 路书生成失败，走模板兜底: %s", exc)
        return _response("template", _template_text(facts))
