# -*- coding: utf-8 -*-
"""探查阳朔县城真实地物，为演示数据挑选坐标。

输出：学校/医院/公园等可作避难所的命名地物、命名住宅街道、河道，
供 gen_yangshuo_demo_data.py 选点与人工核对。
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

BBOX = "24.74,110.45,24.81,110.53"  # south,west,north,east


def run(query):
    data = ("data=" + urllib.parse.quote(query)).encode()
    last = None
    for _ in range(3):
        for ep in ENDPOINTS:
            try:
                req = urllib.request.Request(
                    ep, data=data,
                    headers={"User-Agent": "waitan-evac-demo/1.0"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001
                last = e
                print("  [warn] %s: %s" % (ep, e))
                time.sleep(4)
    raise RuntimeError("Overpass 失败: %s" % last)


def center_of(el):
    if el["type"] == "node":
        return (el["lon"], el["lat"])
    if "center" in el:
        return (el["center"]["lon"], el["center"]["lat"])
    geom = el.get("geometry") or []
    if geom:
        return (
            round(sum(g["lon"] for g in geom) / len(geom), 6),
            round(sum(g["lat"] for g in geom) / len(geom), 6),
        )
    return None


def main():
    out = {}

    print("== 可作避难所的命名地物（学校/医院/体育/政府/公园）==")
    q = (
        "[out:json][timeout:180];("
        'nwr["amenity"~"^(school|college|hospital|community_centre|townhall)$"]["name"](%s);'
        'nwr["leisure"~"^(sports_centre|stadium|park)$"]["name"](%s);'
        ');out center;' % (BBOX, BBOX)
    )
    res = run(q)
    shelters = []
    for el in res.get("elements", []):
        c = center_of(el)
        if not c:
            continue
        tags = el.get("tags", {})
        shelters.append({
            "name": tags.get("name"),
            "kind": tags.get("amenity") or tags.get("leisure"),
            "lng": c[0], "lat": c[1],
            "wheelchair": tags.get("wheelchair"),
        })
    for s in shelters:
        print("  %-28s %-16s %.5f, %.5f" % (s["name"], s["kind"], s["lng"], s["lat"]))
    out["shelters_candidates"] = shelters
    time.sleep(4)

    print("\n== 命名街道（residential/tertiary/secondary，取中点）==")
    q = (
        "[out:json][timeout:180];"
        'way["highway"~"^(residential|tertiary|secondary|living_street|pedestrian)$"]["name"](%s);'
        "out geom;" % BBOX
    )
    res = run(q)
    streets = []
    for el in res.get("elements", []):
        geom = el.get("geometry") or []
        if not geom:
            continue
        mid = geom[len(geom) // 2]
        streets.append({
            "name": el["tags"].get("name"),
            "highway": el["tags"].get("highway"),
            "lng": round(mid["lon"], 6), "lat": round(mid["lat"], 6),
        })
    streets.sort(key=lambda s: s["name"] or "")
    for s in streets[:60]:
        print("  %-24s %-14s %.5f, %.5f" % (s["name"], s["highway"], s["lng"], s["lat"]))
    print("  ... 共 %d 条命名街道" % len(streets))
    out["named_streets"] = streets

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "yangshuo_places.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n已写入 %s" % path)


if __name__ == "__main__":
    main()
