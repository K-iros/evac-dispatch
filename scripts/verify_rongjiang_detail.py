# -*- coding: utf-8 -*-
"""榕江县城（古州镇）OSM 覆盖复核：收紧 bbox + 计入 relation 型建筑 + 分类统计。

目的：确认第一轮 8x8km bbox 统计出的"建筑 35 个"是否为误判
（可能建筑被建成 relation、或 bbox 偏离主城区）。
"""
import json
import time
import urllib.parse
import urllib.request

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# 古州镇主城区（都柳江两岸建成区），收紧到约 4x4 km
BBOX_TIGHT = (25.915, 108.505, 25.950, 108.545)
# 原 8x8 km 对照
BBOX_WIDE = (25.90, 108.48, 25.97, 108.56)

METRICS = [
    ("建筑 way", 'way["building"]({bbox});'),
    ("建筑 relation", 'relation["building"]({bbox});'),
    ("residential 道路", 'way["highway"="residential"]({bbox});'),
    ("footway", 'way["highway"="footway"]({bbox});'),
    ("service 道路", 'way["highway"="service"]({bbox});'),
    ("waterway 河道", 'way["waterway"]({bbox});'),
    ("学校/医院(amenity)", 'way["amenity"~"^(school|hospital|clinic)$"]({bbox});'),
    ("POI 节点(name)", 'node["name"]({bbox});'),
]


def run(query):
    data = ("data=" + urllib.parse.quote(query)).encode()
    last = None
    for _ in range(2):
        for ep in OVERPASS_ENDPOINTS:
            try:
                req = urllib.request.Request(
                    ep, data=data,
                    headers={"User-Agent": "waitan-evac-demo-town-verify/1.0"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001
                last = e
                print("    [warn] %s: %s" % (ep, e))
                time.sleep(4)
    raise RuntimeError("Overpass 全部失败: %s" % last)


def count_all(bbox):
    bs = ",".join(str(v) for v in bbox)
    stmts = "".join(tpl.format(bbox=bs) + "out count;" for _, tpl in METRICS)
    res = run("[out:json][timeout:180];" + stmts)
    nums = [int(e["tags"]["total"]) for e in res.get("elements", [])
            if e.get("type") == "count"]
    return {name: (nums[i] if i < len(nums) else -1)
            for i, (name, _) in enumerate(METRICS)}


def main():
    out = {}
    for label, bbox in (("紧凑 bbox (古州镇主城 ~4x4km)", BBOX_TIGHT),
                        ("宽 bbox (~8x8km, 对照)", BBOX_WIDE)):
        print("\n=== 榕江 %s  bbox=%s ===" % (label, bbox))
        r = count_all(bbox)
        for k, v in r.items():
            print("  %s: %s" % (k, v))
        out[label] = {"bbox": list(bbox), **r}
        time.sleep(4)
    print("\n" + json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
