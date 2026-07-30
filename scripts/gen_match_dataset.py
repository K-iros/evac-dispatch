# -*- coding: utf-8 -*-
"""第十二节 P1「真实匹配算法」+ 第十三节第 5/6(b)/7/8-1/8-2 项数据管线。

流程（两阶段时间窗 + 不动点迭代，路线仍离线实算）：
1. Phase A 时间窗：每户 deadline = 住址达画像危险阈值时刻（s2024
   水深场，point_flooded_minute）− 30 分钟撤离缓冲；全程不淹 →
   预报窗口末端；
2. 耗时矩阵：Valhalla sources_to_targets 实算——接人段/串行转移段
   按帮扶者独行（foot），护送段按画像 costing（轮椅 3.0 km/h 等，
   复用后端 PROFILE_TO_COSTING）；矩阵含 sh-5，但初始匹配不含
   sh-5（第 7 项：高地兜底保留所，仅作 fallback/二次转移目标）；
3. Phase A 求解：app.core.matching.match_helpers（贪心按紧迫度 +
   到场校验 + 串行链最坏情况校验 + 容量/无障碍兼容 + 备份冗余）；
4. Phase B（第 6 项 b，两套时间口径统一）：按 Phase A 实算路线用
   latest_departure_minutes 反推每户"最迟离家时刻"（帮扶者最迟
   出发 + 接人段耗时，与 mock_data 口径一致），回灌
   new_deadline = min(住址淹没版, 路线反推版)，重跑 match_helpers
   一轮（不动点迭代一轮），组合变更的路线重算；
5. 路线：主派（sequence=1 复用既有 Valhalla 路线，串行第 2+ 单
   起点为前一单避难所、必须重算）+ 有序 fallback（第 8-1 项：
   全部匹配户预生成「次近可用兼容所」+ sh-5 终极兜底两级改派
   路线，数组序即级联序，前端取首个未失效者）+ 备份路线；
6. shelterTransfers（第 8-2 项）：sh-1~sh-4 → sh-5 的整所转移
   路线（wheelchair costing，按所内最弱画像的最严口径）；
7. occupancy 回写（第 5 项：各所主派人数，前端容量透出）；
8. 回写 backend/data/yangshuo_schedule.json（assignments 带
   sequence，清除 footRoute/accessCases）并重新序列化前端回退 JSON。

叙事锁单（人工锁单在现实调度同样存在，算法仅校验并告警）：
  e-1 张奶奶 ← h-1 王志愿 → sh-1（补位演练种子，备份强制 h-2）
  e-2 陈先生 ← h-2 李网格 → sh-3（功能 D 改派主案例）
  e-4 黄阿婆 ← h-10 苏晓梅 → sh-3（功能 D 双改派）

跑完后须重跑 gen_access_compare.py 重建无障碍绕行案例
（e-8/e-14/e-19 的主路线会按新匹配结果重新构造绕行版）。

运行：backend\\.venv\\Scripts\\python.exe scripts/gen_match_dataset.py
"""
import json
import math
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.departure import (  # noqa: E402
    latest_departure_minutes,
    point_flooded_minute,
)
from app.core.flood import compute_flood_frames  # noqa: E402
from app.core.matching import match_helpers  # noqa: E402
from app.core.routing import PROFILE_TO_COSTING  # noqa: E402
from app.services.mock_data import (  # noqa: E402
    _segment_durations_min,
    _split_index,
)

VALHALLA = "https://valhalla1.openstreetmap.de"
RDP_EPS = 0.00008  # ≈9m，与 gen_scale_dataset.py 一致
COS_LAT = math.cos(24.78 * math.pi / 180)
SCENARIO = "s2024"  # 匹配决策情景（演示默认情景）
BUFFER_MIN = 30.0   # 撤离缓冲，与 mock_data.NO_ROUTE_BUFFER_MIN 一致
HORIZON_MIN = 1440.0

#: 剧情固定的未匹配户（帮扶资源缺口，撑 P0 清单）
EXCLUDE = {"e-3", "e-11", "e-23", "e-24"}
#: 叙事锁单：户 → (帮扶者, 避难所)
LOCKED = {
    "e-1": ("h-1", "sh-1"),
    "e-2": ("h-2", "sh-3"),
    "e-4": ("h-10", "sh-3"),
}
#: 冗余匹配户（e-1 备份强制 h-2，补位演练种子）
WITH_BACKUP = {"e-1", "e-5", "e-7", "e-9", "e-12", "e-16"}
SEED_BACKUP = {"e-1": "h-2"}
#: 第 7 项：高地兜底保留所——不参与初始匹配，仅作 fallback/转移目标
ULTIMATE = "sh-5"

PROFILE_TO_TYPE = {"wheelchair": "wheelchair", "blind": "blind", "elderly": "foot"}


# ---------------- Valhalla 客户端（同步 urllib，脚本惯例） ----------------

def _post(path, body, retries=3):
    req = urllib.request.Request(
        f"{VALHALLA}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "waitan-evac-demo/1.0"})
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode())
        except Exception as exc:  # noqa: BLE001 —— 公共实例偶发 5xx/超时
            last_err = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Valhalla {path} 失败: {last_err}")


def matrix_min(sources, targets, costing_opts):
    """sources_to_targets 耗时矩阵（分钟；不可达 None）。"""
    payload = _post("/sources_to_targets", {
        "sources": [{"lon": p[0], "lat": p[1]} for p in sources],
        "targets": [{"lon": p[0], "lat": p[1]} for p in targets],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": costing_opts},
        "units": "kilometers",
    })
    return [
        [cell.get("time") / 60 if cell.get("time") is not None else None
         for cell in row]
        for row in payload["sources_to_targets"]
    ]


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


def valhalla_route(waypoints, ped_type):
    payload = _post("/route", {
        "locations": [{"lon": p[0], "lat": p[1]} for p in waypoints],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"type": ped_type}},
        "units": "kilometers",
    })
    coords = []
    for leg in payload["trip"]["legs"]:
        part = decode_polyline6(leg["shape"])
        if coords and part and coords[-1] == part[0]:
            part = part[1:]
        coords.extend(part)
    return [list(c) for c in rdp(coords, RDP_EPS)]


# ---------------- 主流程 ----------------

def main():
    ds_path = BACKEND / "data" / "yangshuo_schedule.json"
    ds = json.loads(ds_path.read_text(encoding="utf-8"))
    evs = [e for e in ds["evacuees"] if e["id"] not in EXCLUDE]
    helpers = [h for h in ds["helpers"] if h["available"]]
    shelters = ds["shelters"]
    pt = {x["id"]: (x["location"]["lng"], x["location"]["lat"])
          for x in ds["evacuees"] + ds["helpers"] + ds["shelters"]}
    profile = {e["id"]: e["profile"] for e in evs}
    # 第 5 项：容量/无障碍从数据集读取（sh-3 小容量 = 功能 D 演示）
    capacity = {s["id"]: s["capacity"] for s in shelters}
    accessible = {s["id"]: s["wheelchairAccessible"] for s in shelters}

    ev_ids = [e["id"] for e in evs]
    h_ids = [h["id"] for h in helpers]
    sh_ids = [s["id"] for s in shelters]
    # 第 7 项：sh-5 保留所不进初始匹配（RESERVE），矩阵仍算全所
    match_sh_ids = [s for s in sh_ids if s != ULTIMATE]
    foot_opts = {"type": "foot"}

    # 1. Phase A 时间窗：住址达画像危险阈值时刻 − 缓冲（s2024 水深场）
    print(f"== Phase A 时间窗（{SCENARIO} 水深场） ==", flush=True)
    frames = compute_flood_frames(SCENARIO)
    deadline = {}
    for e in evs:
        flooded = point_flooded_minute(
            pt[e["id"]], frames, e["profile"], scenario_key=SCENARIO)
        deadline[e["id"]] = (
            max(flooded - BUFFER_MIN, 0.0) if flooded is not None else HORIZON_MIN
        )
        tag = f"+{deadline[e['id']]:.0f}min" if flooded else "全程安全"
        print(f"  {e['id']} {e['name']}: {tag}", flush=True)

    # 2. Valhalla 耗时矩阵（接人/转移=foot 独行，护送=画像 costing）
    print("== Valhalla 耗时矩阵 ==", flush=True)
    m = matrix_min([pt[h] for h in h_ids], [pt[e] for e in ev_ids], foot_opts)
    pickup = {h: dict(zip(ev_ids, row)) for h, row in zip(h_ids, m)}
    print(f"  接人段 {len(h_ids)}x{len(ev_ids)} 完成", flush=True)
    time.sleep(1.5)

    escort = {e: {} for e in ev_ids}
    for prof in ("wheelchair", "blind", "elderly"):
        group = [e for e in ev_ids if profile[e] == prof]
        if not group:
            continue
        m = matrix_min([pt[e] for e in group], [pt[s] for s in sh_ids],
                       PROFILE_TO_COSTING[prof])
        for e, row in zip(group, m):
            escort[e] = dict(zip(sh_ids, row))
        print(f"  护送段 {prof} {len(group)}x{len(sh_ids)} 完成", flush=True)
        time.sleep(1.5)

    m = matrix_min([pt[s] for s in sh_ids], [pt[e] for e in ev_ids], foot_opts)
    transfer = {s: dict(zip(ev_ids, row)) for s, row in zip(sh_ids, m)}
    print(f"  转移段 {len(sh_ids)}x{len(ev_ids)} 完成", flush=True)

    # 3. 求解（Phase A / Phase B 共用）
    def solve(dl):
        result = match_helpers(
            ev_ids, h_ids, match_sh_ids,
            profile=profile, deadline_min=dl,
            pickup_min=pickup, escort_min=escort, transfer_min=transfer,
            shelter_capacity=capacity, shelter_accessible=accessible,
            locked=LOCKED, with_backup=WITH_BACKUP,
        )
        # e-1 备份强制 h-2（补位演练种子）
        for plan in result.plans:
            seed = SEED_BACKUP.get(plan.evacuee_id)
            if seed and plan.backup_ids != [seed]:
                plan.backup_ids = [seed]
        chains = {}
        for p in sorted(result.plans, key=lambda p: (p.helper_id, p.sequence)):
            chains.setdefault(p.helper_id, []).append(p)
        return result, chains

    result, chains = solve(deadline)
    print("== Phase A 匹配结果 ==", flush=True)
    for h_id, chain in sorted(chains.items()):
        seq = " → ".join(f"{p.evacuee_id}({p.shelter_id})" for p in chain)
        star = "  ★串行" if len(chain) > 1 else ""
        print(f"  {h_id}: {seq}{star}", flush=True)

    # 4. 路线缓存：key = (起点 id, 户, 避难所, costing)，跨阶段复用
    old_routes = {
        (a["helperId"], a["evacueeId"], a["shelterId"],
         a["isBackup"], a.get("isFallback", False)): a["route"]
        for a in ds["assignments"]
    }
    route_cache = {}

    def get_route(start_id, ev_id, sh_id, ped_type, old_key=None):
        ck = (start_id, ev_id, sh_id, ped_type)
        if ck in route_cache:
            return route_cache[ck]
        if old_key and old_key in old_routes:
            print(f"  复用 {start_id}->{ev_id}->{sh_id}", flush=True)
            route_cache[ck] = old_routes[old_key]
            return route_cache[ck]
        print(f"  实算 {start_id}->{ev_id}->{sh_id} ({ped_type})", flush=True)
        route = valhalla_route([pt[start_id], pt[ev_id], pt[sh_id]], ped_type)
        time.sleep(1.5)
        route_cache[ck] = route
        return route

    def build_primary_routes(chains_):
        """主派路线（串行第 2+ 单起点=前一单避难所）；返回 户→路线。"""
        routes = {}
        for h_id, chain in sorted(chains_.items()):
            prev = None
            for p in chain:
                start_id = prev if prev else h_id
                key = (h_id, p.evacuee_id, p.shelter_id, False, False)
                routes[p.evacuee_id] = get_route(
                    start_id, p.evacuee_id, p.shelter_id,
                    PROFILE_TO_TYPE[profile[p.evacuee_id]],
                    old_key=key if p.sequence == 1 else None)
                prev = p.shelter_id
        return routes

    print("== Phase A 主派路线 ==", flush=True)
    primary_routes = build_primary_routes(chains)

    # 5. Phase B（第 6 项 b）：路线反推最迟离家时刻回灌 deadline，重跑一轮
    print("== Phase B 路线反推回灌 ==", flush=True)
    deadline_b = dict(deadline)
    for p in result.plans:
        route = [tuple(c) for c in primary_routes[p.evacuee_id]]
        split = _split_index(route, pt[p.evacuee_id])
        durs = _segment_durations_min(route, split, profile[p.evacuee_id])
        dep = latest_departure_minutes(
            route, durs, frames, profile[p.evacuee_id],
            horizon_min=HORIZON_MIN, scenario_key=SCENARIO)
        if dep is None:
            print(f"  ⚠ {p.evacuee_id} 路线无可行时间窗，deadline 保持不变",
                  flush=True)
            continue
        # 户最迟离家 = 帮扶者最迟出发 + 接人段耗时（mock_data 口径）
        route_ddl = dep + sum(durs[:split])
        if route_ddl < deadline_b[p.evacuee_id]:
            print(f"  {p.evacuee_id}: +{deadline[p.evacuee_id]:.0f}"
                  f" → +{route_ddl:.0f}min（路线反推更紧）", flush=True)
            deadline_b[p.evacuee_id] = route_ddl

    if deadline_b != deadline:
        old_combo = {p.evacuee_id: (p.helper_id, p.shelter_id, p.sequence)
                     for p in result.plans}
        result, chains = solve(deadline_b)
        changed = [
            p.evacuee_id for p in result.plans
            if old_combo.get(p.evacuee_id)
            != (p.helper_id, p.shelter_id, p.sequence)
        ]
        print(f"== Phase B 匹配结果（{len(changed)} 户组合变更："
              f"{changed or '无'}） ==", flush=True)
        for h_id, chain in sorted(chains.items()):
            seq = " → ".join(f"{p.evacuee_id}({p.shelter_id})" for p in chain)
            star = "  ★串行" if len(chain) > 1 else ""
            print(f"  {h_id}: {seq}{star}", flush=True)
        print("== Phase B 变更路线 ==", flush=True)
        primary_routes = build_primary_routes(chains)
    for ev_id, why in result.unmatched.items():
        print(f"  !! {ev_id} 未匹配：{why}", flush=True)
    for w in result.warnings:
        print(f"  ⚠ {w}", flush=True)

    # 6. 组装 assignments：主派 + 有序 fallback（第 8-1 项）+ 备份
    def fallback_targets(ev_id, primary_sh):
        """有序改派候选：次近可用兼容所 + sh-5 终极兜底（数组序=级联序）。"""
        compat = [
            s for s in sh_ids
            if s != primary_sh and s != ULTIMATE
            and (profile[ev_id] != "wheelchair" or accessible[s])
            and escort[ev_id].get(s) is not None
        ]
        targets = sorted(compat, key=lambda s: escort[ev_id][s])[:1]
        if primary_sh != ULTIMATE:
            targets.append(ULTIMATE)
        return targets

    assignments = []
    print("== 路线构建（fallback/备份） ==", flush=True)
    for h_id, chain in sorted(chains.items()):
        prev = None
        for p in chain:
            ped_type = PROFILE_TO_TYPE[profile[p.evacuee_id]]
            start_id = prev if prev else h_id
            assignments.append({
                "helperId": h_id, "evacueeId": p.evacuee_id,
                "shelterId": p.shelter_id, "isBackup": False,
                "isFallback": False, "sequence": p.sequence,
                "route": primary_routes[p.evacuee_id],
            })
            # 第 8-1 项：全量有序 fallback（前端取首个未失效者）
            for fb in fallback_targets(p.evacuee_id, p.shelter_id):
                fb_key = (h_id, p.evacuee_id, fb, False, True)
                assignments.append({
                    "helperId": h_id, "evacueeId": p.evacuee_id,
                    "shelterId": fb, "isBackup": False, "isFallback": True,
                    "sequence": p.sequence,
                    "route": get_route(
                        start_id, p.evacuee_id, fb, ped_type,
                        old_key=fb_key if p.sequence == 1 else None),
                })
            # 备份：从备份帮扶者家出发（冗余待命，不入串行链）
            for b_id in p.backup_ids:
                b_key = (b_id, p.evacuee_id, p.shelter_id, True, False)
                assignments.append({
                    "helperId": b_id, "evacueeId": p.evacuee_id,
                    "shelterId": p.shelter_id, "isBackup": True,
                    "isFallback": False, "sequence": 1,
                    "route": get_route(
                        b_id, p.evacuee_id, p.shelter_id, ped_type,
                        old_key=b_key),
                })
            prev = p.shelter_id

    # 7. shelterTransfers（第 8-2 项）：各所 → sh-5 整所转移路线
    #    wheelchair costing（按所内可能存在的最弱画像取最严口径）
    print("== 避难所转移路线（→ sh-5） ==", flush=True)
    old_transfers = {
        (t["fromShelterId"], t["toShelterId"]): t["route"]
        for t in ds.get("shelterTransfers", [])
    }
    shelter_transfers = []
    for s in shelters:
        if s["id"] == ULTIMATE:
            continue
        tk = (s["id"], ULTIMATE)
        if tk in old_transfers:
            print(f"  复用 {s['id']} -> {ULTIMATE}", flush=True)
            route = old_transfers[tk]
        else:
            print(f"  实算 {s['id']} -> {ULTIMATE} (wheelchair)", flush=True)
            route = valhalla_route([pt[s["id"]], pt[ULTIMATE]], "wheelchair")
            time.sleep(1.5)
        shelter_transfers.append({
            "fromShelterId": s["id"], "toShelterId": ULTIMATE, "route": route,
        })
    ds["shelterTransfers"] = shelter_transfers

    # 8. 回写数据集（footRoute/accessCases 由 gen_access_compare.py 重建）
    plan_by_ev = {p.evacuee_id: p for p in result.plans}
    for e in ds["evacuees"]:
        plan = plan_by_ev.get(e["id"])
        if e["id"] in EXCLUDE or plan is None:
            e["matchStatus"] = "unmatched"
            e["helperIds"] = []
            e["shelterId"] = None
        else:
            e["matchStatus"] = "matched"
            e["helperIds"] = [plan.helper_id, *plan.backup_ids]
            e["shelterId"] = plan.shelter_id
    for h in ds["helpers"]:
        chain = [p.evacuee_id for p in chains.get(h["id"], [])]
        backup_for = sorted(
            p.evacuee_id for p in result.plans if h["id"] in p.backup_ids)
        h["assignedEvacueeIds"] = chain + backup_for
    # 第 5 项：occupancy = 各所主派人数（前端"容量 2/2 已满"透出）
    occ = Counter(p.shelter_id for p in result.plans)
    for s in ds["shelters"]:
        s["occupancy"] = occ.get(s["id"], 0)
    ds["assignments"] = assignments
    ds["accessCases"] = []

    ds_path.write_text(json.dumps(ds, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"已写入 {ds_path}（{len(assignments)} 条路线）", flush=True)

    # 9. 前端离线回退重新序列化
    from app.services.mock_data import build_mock_schedule  # noqa: E402
    build_mock_schedule.cache_clear()
    from app.services import mock_data
    mock_data._load_dataset.cache_clear()

    state = build_mock_schedule(SCENARIO)
    frontend_path = ROOT / "frontend" / "src" / "mock" / "scheduleDataset.json"
    frontend_path.write_text(
        json.dumps(state.model_dump(mode="json", by_alias=True),
                   ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"已写入 {frontend_path}", flush=True)
    n_serial = sum(1 for c in chains.values() if len(c) > 1)
    n_fb = sum(1 for a in assignments if a["isFallback"])
    n_conflict = sum(1 for a in state.assignments if a.conflict)
    print(f"匹配完成：{len(result.plans)} 户主派 / {n_serial} 条串行链 / "
          f"{n_fb} 条 fallback / {len(result.unmatched)} 户未匹配 / "
          f"{n_conflict} 条冲突告警", flush=True)


if __name__ == "__main__":
    main()
