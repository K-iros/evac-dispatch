# -*- coding: utf-8 -*-
"""用 Valhalla 公共实例为阳朔演示场景生成真实路线折线。

场景选点来自 explore_yangshuo_places.py 的真实地物：
  避难所 sh-1 阳朔公园应急避难点（西侧高地，远离漓江）
         sh-2 县实验小学体育馆
         sh-3 山水园临江避难点（滨江低洼——供避难所失效演示，功能 D）
  待撤离住址均在漓江边低洼老城区（县前街/滨江路/桂花路）
路线为三点航线：帮扶者 → 住址 → 避难所（与 mock assignments 同构）。
输出 scripts/yangshuo_demo_routes.json，供人工回填三份 mock。
"""
import json
import os
import time
import urllib.request

VALHALLA = "https://valhalla1.openstreetmap.de/route"

POINTS = {
    "sh-1": (110.48455, 24.77903),  # 阳朔公园
    "sh-2": (110.47673, 24.77520),  # 县实验小学
    "sh-3": (110.49302, 24.77818),  # 文化古迹山水园（临江低洼）
    "h-1": (110.48864, 24.78027),   # 城中路
    "h-2": (110.48954, 24.77977),   # 叠翠路
    "h-3": (110.48169, 24.77894),   # 宝泉巷
    "e-1": (110.49180, 24.77950),   # 县前街（轮椅）
    "e-2": (110.49275, 24.78125),   # 滨江路（视障，最贴江）
    "e-3": (110.49046, 24.77840),   # 桂花路（老人，未匹配）
}

# (helper, evacuee, shelter, costing type)
ASSIGNMENTS = [
    ("h-1", "e-1", "sh-1", "wheelchair"),
    ("h-2", "e-1", "sh-1", "wheelchair"),
    ("h-2", "e-2", "sh-1", "blind"),
    # 功能 D：e-2 默认派往临江 sh-3，被淹后自动改派 sh-1（上一条路线）
    ("h-2", "e-2", "sh-3", "blind"),
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


def route(waypoints, ped_type):
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


def main():
    out = {"points": {k: {"lng": v[0], "lat": v[1]} for k, v in POINTS.items()},
           "assignments": []}
    for h, e, s, ped_type in ASSIGNMENTS:
        wp = [POINTS[h], POINTS[e], POINTS[s]]
        print("%s -> %s -> %s (%s) ..." % (h, e, s, ped_type))
        r = route(wp, ped_type)
        print("  %.3f km / %.1f min / %d 点" % (
            r["distance_km"], r["duration_min"], len(r["coordinates"])))
        out["assignments"].append({
            "helper": h, "evacuee": e, "shelter": s, "type": ped_type, **r})
        time.sleep(2)

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "yangshuo_demo_routes.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("已写入 %s" % path)


if __name__ == "__main__":
    main()
