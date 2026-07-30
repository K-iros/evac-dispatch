# -*- coding: utf-8 -*-
"""LLM 派单简报（第十二节 P0）：每位帮扶者一句话任务卡。

内容口径：接谁 / 几点前出发·送达 / 去哪个避难所 / 走多远 /
画像注意事项（轮椅绕行·视障牵引·高龄慢行）+ 备份职责。

生成策略：
1. 有 DEEPSEEK_API_KEY 时一次调用 DeepSeek（deepseek-chat，
   json_object 输出）生成全部帮扶者简报，结果按情景缓存；
2. 无 Key / 调用失败 / 返回缺人时，用规则模板兜底（source 字段
   标注来源，演示不会空白）。
"""

import json
import logging
import math
import os

import httpx

from app.models.schemas import Briefing, BriefingsResponse, ScheduleState

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_TIMEOUT = 45.0
COS_LAT = math.cos(24.78 * math.pi / 180)

PROFILE_LABEL = {"wheelchair": "轮椅", "blind": "视障", "elderly": "高龄"}
#: 画像注意事项（模板兜底文案，也作为 LLM 输入提示）
PROFILE_NOTE = {
    "wheelchair": "全程走无障碍绕行路线，避开台阶陡坎",
    "blind": "全程牵引陪同，提前口述路况",
    "elderly": "放慢步速，随身带常用药品",
}

#: LLM 结果缓存：scenario → BriefingsResponse（模板兜底不缓存，便于配 Key 后重试）
_llm_cache: dict[str, BriefingsResponse] = {}


def _route_km(route: list) -> float:
    """路线折线长度（km），与数据脚本同一量纲。"""
    total = 0.0
    for a, b in zip(route, route[1:]):
        dx = (a[0] - b[0]) * COS_LAT
        dy = a[1] - b[1]
        total += math.hypot(dx, dy) * 111.32
    return round(total, 1)


def _hhmm(iso: str) -> str:
    """ISO 时刻 → HH:MM（模拟时钟，见 core/flood.py T0）。"""
    return iso[11:16] if len(iso) >= 16 else iso


def _build_helper_tasks(state: ScheduleState) -> list[dict]:
    """按帮扶者汇总任务事实（LLM 输入 = 模板输入，同一数据源）。"""
    ev_by_id = {e.id: e for e in state.evacuees}
    shelter_by_id = {s.id: s for s in state.shelters}
    access_ids = {c.evacuee_id for c in state.access_cases}

    tasks: dict[str, dict] = {}
    for h in state.helpers:
        if h.available:
            tasks[h.id] = {"helperId": h.id, "helperName": h.name,
                           "primary": [], "backupFor": []}
    for a in state.assignments:
        entry = tasks.get(a.helper_id)
        ev = ev_by_id.get(a.evacuee_id)
        if entry is None or ev is None or a.is_fallback:
            continue
        if a.is_backup:
            entry["backupFor"].append(ev.name)
            continue
        shelter = shelter_by_id.get(a.shelter_id)
        note = PROFILE_NOTE[ev.profile]
        if ev.id in access_ids:
            note = "路线已按街景识别的台阶障碍绕行，务必按图走"
        entry["primary"].append({
            "evacuee": ev.name,
            "profile": PROFILE_LABEL[ev.profile],
            "address": ev.address,
            "departBy": _hhmm(ev.latest_departure),
            "arriveBy": _hhmm(a.arrive_by),
            "shelter": shelter.name if shelter else a.shelter_id,
            "distanceKm": _route_km(a.route),
            "note": note,
            "seq": a.sequence,
        })
    # 主派多任务按串行链次序排序（P1 真实匹配算法），简报顺序即执行顺序
    result = list(tasks.values())
    for entry in result:
        entry["primary"].sort(key=lambda t: t["seq"])
    return result


def _template_text(entry: dict) -> str:
    """规则模板：一句话任务卡（与 LLM 同口径的兜底文案）。

    串行第 2+ 单不报独立时刻（各单"最迟时刻"是彼此独立的约束
    上限，逐单报时可能出现倒挂），统一用"送达后转接"表述。
    """
    parts = []
    for i, t in enumerate(entry["primary"]):
        if i == 0:
            parts.append(
                f"{t['departBy']}前出发接{t['evacuee']}（{t['profile']}，{t['address']}），"
                f"{t['arriveBy']}前送达{t['shelter']}（约{t['distanceKm']}公里）；{t['note']}"
            )
        else:
            parts.append(
                f"送达后转接{t['evacuee']}（{t['profile']}，{t['address']}），"
                f"护送至{t['shelter']}（约{t['distanceKm']}公里）；{t['note']}"
            )
    if not parts:
        backups = "、".join(entry["backupFor"]) or "各户"
        return f"机动备份：{backups}的主帮扶失联时立即接替，保持通讯畅通。"
    text = "。".join(parts) + "。"
    if entry["backupFor"]:
        text += f"另兼{len(entry['backupFor'])}户备份，留意补位通知。"
    return text


def _template_briefings(entries: list[dict]) -> BriefingsResponse:
    return BriefingsResponse(
        source="template",
        items=[Briefing(helper_id=e["helperId"], helper_name=e["helperName"],
                        text=_template_text(e)) for e in entries],
    )


_SYSTEM_PROMPT = (
    "你是社区防汛疏散调度助手。给每位帮扶者写一句话中文任务简报："
    "接谁（画像/住址）、几点前出发、几点前送达哪个避难所、大约走多远、"
    "画像注意事项，如兼任备份用一短句带过。primary 列表已按串行执行"
    "顺序排列：第 2 单起是送达上一户后再出发的串行任务，用「送达后转接」"
    "表述且不要报出发时刻。口吻是给一线帮扶者的行动指令，"
    "简洁有力，每人不超过90字，不要开场白。"
    '只输出 JSON：{"briefings":[{"helperId":"...","text":"..."}]}'
)


def _call_deepseek(api_key: str, entries: list[dict]) -> dict[str, str]:
    """一次调用生成全部简报，返回 helperId → text。"""
    resp = httpx.post(
        DEEPSEEK_URL,
        timeout=DEEPSEEK_TIMEOUT,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(entries, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.5,
        },
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    items = json.loads(content)["briefings"]
    return {str(it["helperId"]): str(it["text"]).strip()
            for it in items if it.get("helperId") and it.get("text")}


def build_briefings(scenario: str, state: ScheduleState) -> BriefingsResponse:
    """派单简报入口：LLM 优先，任何失败走模板兜底。"""
    cached = _llm_cache.get(scenario)
    if cached is not None:
        return cached

    entries = _build_helper_tasks(state)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return _template_briefings(entries)

    try:
        texts = _call_deepseek(api_key, entries)
        # LLM 漏答的帮扶者用模板补齐，保证人手一卡
        items = [
            Briefing(helper_id=e["helperId"], helper_name=e["helperName"],
                     text=texts.get(e["helperId"]) or _template_text(e))
            for e in entries
        ]
        result = BriefingsResponse(source="llm", items=items)
        _llm_cache[scenario] = result
        return result
    except Exception as exc:  # noqa: BLE001 —— 网络/配额/解析失败均兜底
        logger.warning("DeepSeek 简报生成失败，走模板兜底: %s", exc)
        return _template_briefings(entries)
