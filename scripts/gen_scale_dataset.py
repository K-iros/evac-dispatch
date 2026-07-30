# -*- coding: utf-8 -*-
"""第十二节 P0「扩充数据规模」：生成阳朔演示扩容数据集。

规模：24 户 / 10 帮扶者 / 4 避难所（20 户已匹配 + 4 户未匹配，
供 P0 清单与红色角标展示）。选点均为 OSM 真实街道/地物
（scripts/yangshuo_places.json 探查结果）：14 户在漓江边低洼老城区
（滨江路/县前街/桂花路/西街/芙蓉路/城北路），10 户在西侧高地
（宝泉巷/碧莲巷/兰花路/画山路/将军路/福源路/蟠桃路等）。

匹配为距离贪心 + 容量上限的**预匹配**（真实匹配算法带时间窗校验
属 P1 项，见第十二节），e-1/e-2 沿用原演示叙事种子（补位演练、
功能 D 避难所改派）。路线由 Valhalla 公共实例实算
（帮扶者→住址→避难所三点航线，RDP 简化）。

产出：
  backend/data/yangshuo_schedule.json      后端运行时数据（无时刻，
                                           latestDeparture 由水深场反推）
  frontend/src/mock/scheduleDataset.json   前端离线回退（含 s2024 反推时刻，
                                           经 build_mock_schedule 序列化）
  scripts/yangshuo_scale_routes.json       Valhalla 原始结果存档

运行：backend\\.venv\\Scripts\\python.exe scripts/gen_scale_dataset.py
"""
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VALHALLA = "https://valhalla1.openstreetmap.de/route"
RDP_EPS = 0.00008  # ≈9m，与既有演示路线的简化粒度一致
COS_LAT = math.cos(24.78 * math.pi / 180)

# ---------------- 实体表（坐标均取自 OSM 真实街道锚点） ----------------

SHELTERS = [
    # (id, name, lng, lat, accessible, capacity)  sh-3 容量 2 = 功能 D 演示保留
    ("sh-1", "阳朔公园应急避难点", 110.48455, 24.77903, True, 8),
    ("sh-2", "县实验小学体育馆", 110.47673, 24.77520, False, 8),
    ("sh-3", "山水园临江避难点", 110.49230, 24.77910, True, 2),
    ("sh-4", "县外语实验中学安置点", 110.48942, 24.79180, True, 8),
]

HELPERS = [
    # (id, name, lng, lat, available)
    ("h-1", "王志愿", 110.48864, 24.78027, True),   # 城中路
    ("h-2", "李网格", 110.48954, 24.77977, True),   # 叠翠路
    ("h-3", "赵帮扶", 110.48169, 24.77894, False),  # 宝泉巷（不可用）
    ("h-4", "陈社工", 110.48888, 24.77636, True),   # 西街
    ("h-5", "韦志强", 110.48966, 24.77868, True),   # 桂花路
    ("h-6", "蒙丽华", 110.49034, 24.78116, True),   # 芙蓉路
    ("h-7", "覃建国", 110.48595, 24.77688, True),   # 蟠桃路
    ("h-8", "卢桂香", 110.49103, 24.78298, True),   # 城北路
    ("h-9", "廖安民", 110.47393, 24.77432, True),   # 画山路
    ("h-10", "苏晓梅", 110.49190, 24.78016, True),  # 县前街
]

EVACUEES = [
    # (id, name, profile, address, lng, lat)
    # —— 漓江边低洼老城区（急涨段先失效，撑起 P1/改派叙事）——
    ("e-1", "张奶奶", "wheelchair", "县前街 12 号 101", 110.49180, 24.77950),
    ("e-2", "陈先生", "blind", "滨江路 88 号 502", 110.49275, 24.78125),
    ("e-3", "刘爷爷", "elderly", "桂花路 5 号 301", 110.49046, 24.77840),
    ("e-4", "黄阿婆", "elderly", "滨江路 32 号", 110.49266, 24.77973),
    ("e-5", "莫大爷", "wheelchair", "滨江路 56 号", 110.49254, 24.77935),
    ("e-6", "韦奶奶", "elderly", "县前街 3 号", 110.49190, 24.78000),
    ("e-7", "覃伯", "blind", "西街 71 号", 110.49063, 24.77830),
    ("e-8", "卢阿姨", "wheelchair", "西街 105 号", 110.48930, 24.77680),
    ("e-9", "廖老太", "elderly", "桂花路 18 号", 110.49100, 24.77983),
    ("e-10", "苏爷爷", "elderly", "芙蓉路 9 号", 110.49034, 24.78100),
    ("e-11", "蒙先生", "blind", "滨江路 120 号", 110.49258, 24.78060),
    ("e-12", "罗奶奶", "wheelchair", "县前街 27 号", 110.49190, 24.78016),
    ("e-13", "唐阿公", "elderly", "城北路 44 号", 110.49103, 24.78250),
    ("e-14", "秦阿婆", "wheelchair", "桂花路 33 号", 110.49080, 24.77855),
    # —— 西侧高地（全程安全，对照组）——
    ("e-15", "何大爷", "elderly", "宝泉巷 6 号", 110.48514, 24.78131),
    ("e-16", "梁奶奶", "wheelchair", "宝泉巷 21 号", 110.48661, 24.78022),
    ("e-17", "陆先生", "blind", "碧莲巷 8 号", 110.48213, 24.77749),
    ("e-18", "蒋阿婆", "elderly", "兰花路 15 号", 110.47698, 24.77670),
    ("e-19", "欧奶奶", "wheelchair", "画山路 22 号", 110.47561, 24.77642),
    ("e-20", "邓爷爷", "elderly", "将军路 9 号", 110.47521, 24.77623),
    ("e-21", "曾阿姨", "blind", "福源路 12 号", 110.47460, 24.77890),
    ("e-22", "冯老伯", "elderly", "蟠桃路 47 号", 110.47817, 24.77789),
    ("e-23", "彭阿公", "elderly", "进士路 5 号", 110.49045, 24.77236),
    ("e-24", "邱阿婆", "wheelchair", "神山路 18 号", 110.48713, 24.78706),
]

#: 未匹配户（P0 清单 + 红色角标）：老城深水区 2 户 + 城郊无人手 2 户
UNMATCHED = {"e-3", "e-11", "e-23", "e-24"}
#: 冗余匹配（含备份帮扶者）的户
WITH_BACKUP = {"e-1", "e-5", "e-7", "e-9", "e-12", "e-16"}
#: 叙事种子：主帮扶 / 目标避难所固定（沿用既有演示动线）
SEED_HELPER = {"e-1": "h-1", "e-2": "h-2"}
SEED_BACKUP = {"e-1": "h-2"}
SEED_SHELTER = {"e-2": "sh-3", "e-4": "sh-3"}  # sh-3 两户 → 功能 D 双改派
HELPER_CAP = 3


def dist_m(a, b):
    dx = (a[0] - b[0]) * COS_LAT
    dy = a[1] - b[1]
    return math.hypot(dx, dy) * 111_320


# ---------------- 贪心预匹配（距离 + 容量） ----------------

def greedy_match():
    """按低洼→高地顺序为已匹配户挑最近的可用帮扶者与最近兼容避难所。"""
    load = {h[0]: 0 for h in HELPERS}
    sh_load = {s[0]: 0 for s in SHELTERS}
    # 种子避难所先占容量
    for sid in SEED_SHELTER.values():
        sh_load[sid] += 1
    plans = {}  # ev_id -> {"helpers": [primary, backup?], "shelter": sid}
    for ev in EVACUEES:
        ev_id, _, profile, _, lng, lat = ev
        if ev_id in UNMATCHED:
            continue
        home = (lng, lat)
        # 主帮扶：种子优先，否则最近的可用且未满员者
        cands = sorted(
            (h for h in HELPERS if h[4] and load[h[0]] < HELPER_CAP),
            key=lambda h: dist_m(home, (h[2], h[3])),
        )
        primary = SEED_HELPER.get(ev_id) or cands[0][0]
        load[primary] += 1
        helpers = [primary]
        if ev_id in WITH_BACKUP:
            backup = SEED_BACKUP.get(ev_id) or next(
                h[0] for h in cands if h[0] != primary and load[h[0]] < HELPER_CAP
            )
            load[backup] += 1
            helpers.append(backup)
        # 避难所：种子优先；轮椅只去无障碍避难所；容量满则次近
        if ev_id in SEED_SHELTER:
            shelter = SEED_SHELTER[ev_id]
        else:
            options = sorted(
                (
                    s for s in SHELTERS
                    if sh_load[s[0]] < s[5] and (profile != "wheelchair" or s[4])
                ),
                key=lambda s: dist_m(home, (s[2], s[3])),
            )
            shelter = options[0][0]
            sh_load[shelter] += 1
        plans[ev_id] = {"helpers": helpers, "shelter": shelter}
    return plans


# ---------------- Valhalla 路线（RDP 简化） ----------------

def rdp(points, eps):
    if len(points) < 3:
        return points
    ax, ay = points[0]
    bx, by = points[-1]
    dx, dy = (bx - ax) * COS_LAT, by - ay
    norm = math.hypot(dx, dy)
    best_i, best_d = 0, 0.0
    for i in range(1, len(points) - 1):
        px, py = (points[i][0] - ax) * COS_LAT, points[i][1] - ay
        d = abs(px * dy - py * dx) / norm if norm else math.hypot(px, py)
        if d > best_d:
            best_i, best_d = i, d
    if best_d <= eps:
        return [points[0], points[-1]]
    left = rdp(points[: best_i + 1], eps)
    return left[:-1] + rdp(points[best_i:], eps)


def decode_polyline6(encoded):
    coords, lat, lng, i = [], 0, 0, 0
    while i < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lng += delta
        coords.append((round(lng / 1e6, 6), round(lat / 1e6, 6)))
    return coords


PROFILE_TO_TYPE = {"wheelchair": "wheelchair", "blind": "blind", "elderly": "foot"}


def valhalla_route(waypoints, ped_type, retries=3):
    body = {
        "locations": [{"lon": p[0], "lat": p[1]} for p in waypoints],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"type": ped_type}},
        "units": "kilometers",
    }
    req = urllib.request.Request(
        VALHALLA, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "waitan-evac-demo/1.0"})
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                trip = json.loads(r.read().decode())["trip"]
            coords = []
            for leg in trip["legs"]:
                part = decode_polyline6(leg["shape"])
                if coords and part and coords[-1] == part[0]:
                    part = part[1:]
                coords.extend(part)
            return {
                "coordinates": rdp(coords, RDP_EPS),
                "raw_points": len(coords),
                "distance_km": round(trip["summary"]["length"], 3),
                "duration_min": round(trip["summary"]["time"] / 60, 1),
            }
        except Exception as exc:  # noqa: BLE001 —— 公共实例偶发 5xx/超时
            last_err = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Valhalla 路线失败: {last_err}")


def fetch_routes(plans):
    """(helper, evacuee, shelter, isBackup, isFallback) → 路线折线。"""
    pt = {h[0]: (h[2], h[3]) for h in HELPERS}
    pt.update({s[0]: (s[2], s[3]) for s in SHELTERS})
    pt.update({e[0]: (e[4], e[5]) for e in EVACUEES})
    profile_of = {e[0]: e[2] for e in EVACUEES}
    accessible = {s[0]: s[4] for s in SHELTERS}

    tasks = []  # (helper, evacuee, shelter, is_backup, is_fallback)
    for ev_id, plan in plans.items():
        primary, *backup = plan["helpers"]
        tasks.append((primary, ev_id, plan["shelter"], False, False))
        for b in backup:
            tasks.append((b, ev_id, plan["shelter"], True, False))
        # 功能 D：派往 sh-3 的户预生成改派候选（次近的其他无障碍避难所）
        if plan["shelter"] == "sh-3":
            fallback_sh = min(
                (s for s in SHELTERS if s[0] != "sh-3" and accessible[s[0]]),
                key=lambda s: dist_m(pt[ev_id], (s[2], s[3])),
            )[0]
            tasks.append((primary, ev_id, fallback_sh, False, True))

    results, archive = [], []
    for i, (h, e, s, is_backup, is_fallback) in enumerate(tasks, 1):
        profile = profile_of[e]
        ped_type = PROFILE_TO_TYPE[profile]
        wp = [pt[h], pt[e], pt[s]]
        kind = "fallback" if is_fallback else ("backup" if is_backup else "primary")
        print(f"[{i}/{len(tasks)}] {h} -> {e} -> {s} ({ped_type}, {kind}) ...",
              flush=True)
        try:
            r = valhalla_route(wp, ped_type)
        except RuntimeError:
            # 轮椅在标签稀疏区可能无解（第五节已知坑）→ 回退步行 costing
            print("  轮椅/画像 costing 无解，回退 type=foot", flush=True)
            r = valhalla_route(wp, "foot")
        print(f"  {r['distance_km']:.3f} km / {r['duration_min']:.1f} min / "
              f"{r['raw_points']} -> {len(r['coordinates'])} 点", flush=True)
        results.append({
            "helperId": h, "evacueeId": e, "shelterId": s,
            "isBackup": is_backup, "isFallback": is_fallback,
            "route": [[c[0], c[1]] for c in r["coordinates"]],
        })
        archive.append({"helper": h, "evacuee": e, "shelter": s,
                        "type": ped_type, "kind": kind, **r})
        time.sleep(1.5)
    return results, archive


# ---------------- 数据集组装与落盘 ----------------

def main():
    plans = greedy_match()
    assignments, archive = fetch_routes(plans)

    dataset = {
        "shelters": [
            {"id": s[0], "name": s[1],
             "location": {"lng": s[2], "lat": s[3]},
             "wheelchairAccessible": s[4]}
            for s in SHELTERS
        ],
        "helpers": [
            {"id": h[0], "name": h[1],
             "location": {"lng": h[2], "lat": h[3]},
             "assignedEvacueeIds": sorted(
                 ev_id for ev_id, p in plans.items() if h[0] in p["helpers"]),
             "available": h[4]}
            for h in HELPERS
        ],
        "evacuees": [
            {"id": e[0], "name": e[1], "profile": e[2], "address": e[3],
             "location": {"lng": e[4], "lat": e[5]},
             "matchStatus": "unmatched" if e[0] in UNMATCHED else "matched",
             "helperIds": plans.get(e[0], {}).get("helpers", []),
             "shelterId": plans.get(e[0], {}).get("shelter")}
            for e in EVACUEES
        ],
        "assignments": assignments,
    }

    backend_path = BACKEND / "data" / "yangshuo_schedule.json"
    backend_path.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入 {backend_path}")

    (ROOT / "scripts" / "yangshuo_scale_routes.json").write_text(
        json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")

    # 前端离线回退：经 build_mock_schedule 计算 s2024 反推时刻后整体序列化，
    # 保证与后端在线返回完全一致
    sys.path.insert(0, str(BACKEND))
    from app.services.mock_data import build_mock_schedule  # noqa: E402

    state = build_mock_schedule("s2024")
    frontend_path = ROOT / "frontend" / "src" / "mock" / "scheduleDataset.json"
    frontend_path.write_text(
        json.dumps(state.model_dump(mode="json", by_alias=True),
                   ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"已写入 {frontend_path}")

    n_matched = sum(1 for e in EVACUEES if e[0] not in UNMATCHED)
    print(f"规模：{len(EVACUEES)} 户（{n_matched} 匹配 / {len(UNMATCHED)} 未匹配）"
          f" / {len(HELPERS)} 帮扶者 / {len(SHELTERS)} 避难所"
          f" / {len(assignments)} 条路线")


if __name__ == "__main__":
    main()
