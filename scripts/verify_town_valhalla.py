# -*- coding: utf-8 -*-
"""PROJECT_CONTEXT 第十节：候选城镇轮椅可达性验证（Valhalla 公共服务）。

背景：ORS 公共 API 在当前网络下被阻断（DNS 污染 + TLS SNI 重置，无代理可用），
      改用 Valhalla 公共实例 valhalla1.openstreetmap.de 完成同等验证。
      Valhalla 的 pedestrian costing 支持 type=wheelchair，会排除 steps
      并读取 wheelchair=* / surface / incline 标签，与 ORS wheelchair profile 目的等价。

用法：
    python scripts/verify_town_valhalla.py

每镇自动从 Overpass 拉真实道路节点，构造 5 对 800-2500m 起终点，
分别用 wheelchair / foot 两种行人类型请求路径，统计成功率与绕行倍率。
结果输出到控制台 + scripts/town_valhalla_result.json。
"""
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

VALHALLA_URL = "https://valhalla1.openstreetmap.de/route"
PED_TYPES = ["wheelchair", "foot"]
PAIRS_PER_TOWN = 5

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# bbox = (south, west, north, east)，与 verify_town_osm.py 一致
CANDIDATES = {
    "贵州榕江县城": (25.90, 108.48, 25.97, 108.56),
    "重庆磁器口/沙坪坝片区": (29.54, 106.40, 29.62, 106.50),
    "广西阳朔县城": (24.74, 110.45, 24.81, 110.53),
}


def fetch_road_nodes(bbox):
    """拉取 bbox 内可步行道路的几何点。"""
    bbox_str = ",".join(str(v) for v in bbox)
    query = (
        "[out:json][timeout:120];"
        'way["highway"~"^(residential|tertiary|secondary|primary|unclassified|'
        'living_street|footway)$"](' + bbox_str + ");"
        "out geom 300;"
    )
    data = ("data=" + urllib.parse.quote(query)).encode()
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(
                endpoint, data=data,
                headers={"User-Agent": "waitan-evac-demo-town-verify/1.0"})
            with urllib.request.urlopen(req, timeout=150) as resp:
                result = json.loads(resp.read().decode())
            pts = []
            for el in result.get("elements", []):
                for g in el.get("geometry", [])[:2]:
                    pts.append((g["lon"], g["lat"]))
            if pts:
                return pts
        except Exception as e:  # noqa: BLE001
            last_err = e
            print("    [warn] %s 失败: %s" % (endpoint, e))
            time.sleep(3)
    raise RuntimeError("拉取道路节点失败: %s" % last_err)


def dist_m(a, b):
    dx = (a[0] - b[0]) * 111320 * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * 110540
    return math.hypot(dx, dy)


def pick_pairs(pts, n=PAIRS_PER_TOWN):
    """从道路点中选 n 对相距 800-2500m 的起终点，尽量分散。"""
    pairs = []
    used = set()
    step = max(1, len(pts) // (n * 6))
    for i in range(0, len(pts), step):
        if len(pairs) >= n:
            break
        if i in used:
            continue
        for j in range(i + 1, len(pts)):
            if j in used:
                continue
            d = dist_m(pts[i], pts[j])
            if 800 <= d <= 2500:
                pairs.append({
                    "name": "试跑%d" % (len(pairs) + 1),
                    "start": list(pts[i]),
                    "end": list(pts[j]),
                    "straight_m": int(d),
                })
                used.add(i)
                used.add(j)
                break
    return pairs


def route(start, end, ped_type):
    """start/end = [lon, lat]。返回 {ok, distance_m, duration_min} 或 {ok:False, error}。"""
    body = {
        "locations": [
            {"lat": start[1], "lon": start[0]},
            {"lat": end[1], "lon": end[0]},
        ],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"type": ped_type}},
        "directions_options": {"units": "kilometers"},
    }
    req = urllib.request.Request(
        VALHALLA_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "waitan-evac-demo-town-verify/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode())
        summary = payload["trip"]["summary"]
        return {
            "ok": True,
            "distance_m": round(summary["length"] * 1000, 1),
            "duration_min": round(summary["time"] / 60, 1),
        }
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode())
            msg = detail.get("error", str(detail))
        except Exception:  # noqa: BLE001
            msg = str(e)
        return {"ok": False, "error": "HTTP %s: %s" % (e.code, msg)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def main():
    all_results = {}
    for town, bbox in CANDIDATES.items():
        print("\n=== %s ===" % town)
        print("  拉取道路节点…")
        pts = fetch_road_nodes(bbox)
        pairs = pick_pairs(pts)
        if not pairs:
            print("  ❌ 路网点不足，无法构造起终点对")
            all_results[town] = {"error": "路网极稀疏，无法构造试跑点对"}
            continue

        records = []
        for p in pairs:
            entry = dict(p)
            for ped_type in PED_TYPES:
                r = route(p["start"], p["end"], ped_type)
                entry[ped_type] = r
                if r["ok"]:
                    detour = round(r["distance_m"] / p["straight_m"], 2)
                    r["detour_ratio"] = detour
                    status = "✅ %sm / %smin (绕行 %sx)" % (
                        r["distance_m"], r["duration_min"], detour)
                else:
                    status = "❌ %s" % r["error"]
                print("  [%-10s] %s 直线%sm: %s" % (
                    ped_type, p["name"], p["straight_m"], status))
                time.sleep(1.2)
            records.append(entry)

        wc_ok = sum(1 for e in records if e["wheelchair"]["ok"])
        ft_ok = sum(1 for e in records if e["foot"]["ok"])
        wc_detours = [e["wheelchair"].get("detour_ratio") for e in records
                      if e["wheelchair"]["ok"]]
        summary = {
            "试跑对数": len(records),
            "wheelchair 成功": wc_ok,
            "foot 成功": ft_ok,
            "wheelchair 平均绕行倍率": (
                round(sum(wc_detours) / len(wc_detours), 2) if wc_detours else None),
        }
        print("  --- 小结: 轮椅 %d/%d 成功, 步行 %d/%d 成功, 轮椅平均绕行 %s ---" % (
            wc_ok, len(records), ft_ok, len(records),
            summary["wheelchair 平均绕行倍率"]))
        all_results[town] = {"summary": summary, "records": records}
        time.sleep(3)

    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "town_valhalla_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print("\n结果已写入 %s" % out_path)


if __name__ == "__main__":
    main()
