# -*- coding: utf-8 -*-
"""下载阳朔演示区 OSM 建筑/道路/水体，供 DEM 条件化使用。

输出 backend/data/yangshuo_osm.json：
  buildings: [[ [lng,lat], ... ], ...]   建筑外轮廓（闭合环）
  roads:     [{"highway": ..., "coords": [[lng,lat], ...]}, ...]
  water:     [[ [lng,lat], ... ], ...]   水体多边形（漓江 riverbank 等）
"""
import json
import os
import time
import urllib.parse
import urllib.request

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# 与 fetch_yangshuo_dem.py 的 BBOX 一致（s,w,n,e）
BBOX = "24.750,110.455,24.810,110.525"

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "backend", "data", "yangshuo_osm.json")


def run(query):
    data = ("data=" + urllib.parse.quote(query)).encode()
    last = None
    for _ in range(3):
        for ep in ENDPOINTS:
            try:
                req = urllib.request.Request(
                    ep, data=data,
                    headers={"User-Agent": "waitan-evac-demo/1.0"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001
                last = e
                print("  [warn] %s: %s" % (ep, e))
                time.sleep(5)
    raise RuntimeError("Overpass 失败: %s" % last)


def ring(el):
    geom = el.get("geometry") or []
    return [[round(g["lon"], 6), round(g["lat"], 6)] for g in geom]


def main():
    out = {}

    print("== 建筑轮廓 ==")
    res = run('[out:json][timeout:300];way["building"](%s);out geom;' % BBOX)
    buildings = [ring(el) for el in res.get("elements", []) if el.get("geometry")]
    print("  %d 栋" % len(buildings))
    out["buildings"] = buildings
    time.sleep(5)

    print("== 道路中心线 ==")
    res = run('[out:json][timeout:300];way["highway"](%s);out geom;' % BBOX)
    roads = []
    for el in res.get("elements", []):
        if not el.get("geometry"):
            continue
        roads.append({"highway": el["tags"].get("highway"), "coords": ring(el)})
    print("  %d 条" % len(roads))
    out["roads"] = roads
    time.sleep(5)

    print("== 水体（riverbank / water 面 + 漓江中心线）==")
    res = run(
        '[out:json][timeout:300];('
        'way["natural"="water"](%s);'
        'way["waterway"="riverbank"](%s);'
        ');out geom;' % (BBOX, BBOX))
    water = [ring(el) for el in res.get("elements", []) if el.get("geometry")]
    print("  %d 个水面" % len(water))
    out["water"] = water
    time.sleep(5)

    res = run('[out:json][timeout:300];way["waterway"="river"](%s);out geom;' % BBOX)
    rivers = [ring(el) for el in res.get("elements", []) if el.get("geometry")]
    print("  %d 段河道中心线" % len(rivers))
    out["river_centerlines"] = rivers

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("已写入 %s (%.1f MB)" % (OUT, os.path.getsize(OUT) / 1e6))


if __name__ == "__main__":
    main()
