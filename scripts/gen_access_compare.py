# -*- coding: utf-8 -*-
"""第十二节 P0「无障碍路径对比开关」：生成轮椅/步行分化案例。

背景（第十节关键发现）：阳朔 wheelchair=* 标签趋近于零，Valhalla
的 wheelchair 与 foot costing 返回路径几乎相同，引擎无法自发分化。
本脚本人工构造 3 个分化案例——在既有轮椅户主路线的护送段上选定
障碍点（叙事：CV 街景识别出台阶/陡坎，即创新①「识别→注入→路径
改变」闭环的注入端），用 Valhalla exclude_locations 实算轮椅绕行
路线，替换该户主路线；同航点 type=foot 实算普通步行对照路线存入
footRoute。前端对比开关同屏渲染双线 + ⚠️ 障碍标记 + 绕行倍率。

案例户：e-8 卢阿姨（西街）/ e-14 秦阿婆（桂花路）/ e-19 欧奶奶
（画山路），均为无备份路线的轮椅户，双线视觉不受备份线干扰。

第十三节第 6 项(b) 配套约束：绕行路线不得穿过 +720min 前失效的
路段（s2024 水深场、轮椅画像口径）——避免「无障碍绕行版」反而
把户推入更早被淹的低洼巷道，制造新的时间口径矛盾。

产出（在扩容数据集上原位更新）：
  backend/data/yangshuo_schedule.json      主路线替换 + footRoute + accessCases
  frontend/src/mock/scheduleDataset.json   经 build_mock_schedule 重新序列化
  scripts/yangshuo_access_routes.json      Valhalla 原始结果存档

运行：backend\\.venv\\Scripts\\python.exe scripts/gen_access_compare.py
"""
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
VALHALLA = "https://valhalla1.openstreetmap.de/route"
RDP_EPS = 0.00008  # ≈9m，与 gen_scale_dataset.py 一致
COS_LAT = math.cos(24.78 * math.pi / 180)
SCENARIO = "s2024"  # 绕行安全约束的判定情景（演示默认情景）

#: 对比案例户（轮椅、无备份路线）
CASE_IDS = ["e-8", "e-14", "e-19"]
BARRIER_LABEL = "台阶/陡坎 · 轮椅不可通行（街景识别）"
#: 绕行判定：轮椅绕行里程须比步行长出该比例才算分化成功
MIN_DETOUR = 1.06
#: 第 6 项(b)：绕行路线各段失效时刻不得早于该分钟数
MIN_SAFE_MIN = 720.0
#: 障碍点候选位置（护送段行程占比），逐个尝试直至分化
BARRIER_FRACTIONS = [0.55, 0.4, 0.7, 0.25, 0.85]


def dist_m(a, b):
    dx = (a[0] - b[0]) * COS_LAT
    dy = a[1] - b[1]
    return math.hypot(dx, dy) * 111_320


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


def valhalla_route(waypoints, ped_type, exclude=None, retries=3):
    body = {
        "locations": [{"lon": p[0], "lat": p[1]} for p in waypoints],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"type": ped_type}},
        "units": "kilometers",
    }
    if exclude:
        body["exclude_locations"] = [{"lon": p[0], "lat": p[1]} for p in exclude]
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
                "coordinates": coords,
                "distance_km": round(trip["summary"]["length"], 3),
                "duration_min": round(trip["summary"]["time"] / 60, 1),
            }
        except Exception as exc:  # noqa: BLE001 —— 公共实例偶发 5xx/超时
            last_err = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Valhalla 路线失败: {last_err}")


def escort_vertex_at(route, home, frac):
    """护送段（离住址最近顶点 → 终点）按行程占比 frac 取顶点。"""
    split = min(range(len(route)), key=lambda i: dist_m(route[i], home))
    escort = route[split:]
    if len(escort) < 3:
        return None
    total = sum(dist_m(escort[i], escort[i + 1]) for i in range(len(escort) - 1))
    acc = 0.0
    for i in range(len(escort) - 1):
        acc += dist_m(escort[i], escort[i + 1])
        if acc >= total * frac:
            return escort[i + 1]
    return escort[-2]


def route_fail_minute(coords, frames, profile):
    """整条路线最早失效时刻（分钟；全程可通行返回 None）。"""
    from app.core.departure import segment_failure_minute

    simplified = rdp(coords, RDP_EPS)
    fails = [
        segment_failure_minute(
            [simplified[i], simplified[i + 1]], frames, profile,
            scenario_key=SCENARIO)
        for i in range(len(simplified) - 1)
    ]
    fails = [f for f in fails if f is not None]
    return min(fails) if fails else None


def main():
    from app.core.flood import compute_flood_frames

    frames = compute_flood_frames(SCENARIO)
    ds_path = BACKEND / "data" / "yangshuo_schedule.json"
    ds = json.loads(ds_path.read_text(encoding="utf-8"))
    ev_by_id = {e["id"]: e for e in ds["evacuees"]}
    pt = {x["id"]: (x["location"]["lng"], x["location"]["lat"])
          for x in ds["evacuees"] + ds["helpers"] + ds["shelters"]}

    cases, archive = [], []
    for ev_id in CASE_IDS:
        ev = ev_by_id[ev_id]
        primary = next(
            a for a in ds["assignments"]
            if a["evacueeId"] == ev_id and not a["isBackup"]
            and not a.get("isFallback", False)
        )
        # 串行第 2+ 单起点 = 前一单避难所（真实匹配算法的串行链口径）
        seq = primary.get("sequence", 1)
        if seq > 1:
            prev = next(
                a for a in ds["assignments"]
                if a["helperId"] == primary["helperId"] and not a["isBackup"]
                and not a.get("isFallback", False)
                and a.get("sequence", 1) == seq - 1
            )
            start = pt[prev["shelterId"]]
        else:
            start = pt[primary["helperId"]]
        wp = [start, pt[ev_id], pt[primary["shelterId"]]]
        home = pt[ev_id]
        print(f"== {ev_id} {ev['name']} ({primary['helperId']} seq{seq} -> "
              f"{primary['shelterId']}) ==", flush=True)

        foot = valhalla_route(wp, "foot")
        print(f"  foot: {foot['distance_km']:.3f} km", flush=True)
        time.sleep(1.5)

        # 迭代堵路构造分化：单障碍不奏效时，逐轮把当前轮椅路线
        # 护送段中点追加为障碍（叙事：街景识别出多处台阶/陡坎），
        # 直至轮椅路线被迫绕行
        detour, barrier = None, None
        for frac in BARRIER_FRACTIONS:
            cand = escort_vertex_at(foot["coordinates"], home, frac)
            if cand is None:
                continue
            excludes = [cand]
            for _round in range(4):
                try:
                    r = valhalla_route(wp, "wheelchair", exclude=excludes)
                except RuntimeError as exc:
                    print(f"  frac={frac} x{len(excludes)}点: 失败 {exc}",
                          flush=True)
                    time.sleep(1.5)
                    break
                ratio = r["distance_km"] / foot["distance_km"]
                # 第 6 项(b)：绕行版不得穿过 +720min 前失效路段
                fail_min = route_fail_minute(
                    r["coordinates"], frames, ev["profile"])
                safe = fail_min is None or fail_min >= MIN_SAFE_MIN
                fail_tag = "全程可通行" if fail_min is None else f"+{fail_min:.0f}min"
                print(f"  frac={frac} x{len(excludes)}点: wheelchair "
                      f"{r['distance_km']:.3f} km (x{ratio:.2f}) "
                      f"失效={fail_tag}{'' if safe else ' ✗过早'}", flush=True)
                time.sleep(1.5)
                if ratio >= MIN_DETOUR and safe:
                    detour, barrier = r, cand
                    break
                nxt = escort_vertex_at(r["coordinates"], home, 0.5)
                if nxt is None or any(dist_m(nxt, p) < 15 for p in excludes):
                    break
                excludes.append(nxt)
            if detour is not None:
                break
        if detour is None:
            print(f"  !! {ev_id} 未能构造分化案例，跳过", flush=True)
            continue

        # 主路线替换为轮椅绕行版；同 assignment 记录步行对照线
        primary["route"] = [list(c) for c in rdp(detour["coordinates"], RDP_EPS)]
        primary["footRoute"] = [list(c) for c in rdp(foot["coordinates"], RDP_EPS)]
        ratio = round(detour["distance_km"] / foot["distance_km"], 2)
        cases.append({
            "evacueeId": ev_id,
            "barrier": {"location": {"lng": barrier[0], "lat": barrier[1]},
                        "label": BARRIER_LABEL},
            "wheelchairKm": detour["distance_km"],
            "footKm": foot["distance_km"],
            "detourRatio": ratio,
        })
        archive.append({"evacuee": ev_id, "barrier": list(barrier),
                        "foot": foot, "wheelchair": detour})
        print(f"  ✓ 分化成功：绕行倍率 x{ratio}", flush=True)

    if not cases:
        raise SystemExit("全部案例构造失败，数据集未改动")

    ds["accessCases"] = cases
    ds_path.write_text(json.dumps(ds, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"已更新 {ds_path}（{len(cases)} 个对比案例）")

    (ROOT / "scripts" / "yangshuo_access_routes.json").write_text(
        json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")

    # 前端离线回退重新序列化（含替换后的路线与 accessCases）
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
    print(f"已写入 {frontend_path}")


if __name__ == "__main__":
    main()
