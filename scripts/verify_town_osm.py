# -*- coding: utf-8 -*-
"""PROJECT_CONTEXT 第十节：候选演示城镇 OSM 无障碍标签覆盖验证。

用 Overpass API 统计三个候选区域的：
- highway=footway/path 数量（步行路网密度）
- wheelchair=* 标签数量（way + node，ORS 轮椅模式的关键依据）
- 建筑轮廓数量（DEM 条件化的原料）
- 辅助指标：highway 总 way 数、steps（台阶，轮椅硬伤）、tactile_paving（盲道）

只用标准库，避免依赖问题。结果输出到控制台 + scripts/town_verify_result.json。
"""
import json
import os
import time
import urllib.parse
import urllib.request

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# bbox = (south, west, north, east)，覆盖县城/片区核心建成区
CANDIDATES = {
    "贵州榕江县城": (25.90, 108.48, 25.97, 108.56),
    "重庆磁器口/沙坪坝片区": (29.54, 106.40, 29.62, 106.50),
    "广西阳朔县城": (24.74, 110.45, 24.81, 110.53),
}

# 每项 = (指标名, Overpass 语句模板)
METRICS = [
    ("highway 总 way 数", 'way["highway"]({bbox});'),
    ("footway/path", 'way["highway"~"^(footway|path)$"]({bbox});'),
    ("steps 台阶", 'way["highway"="steps"]({bbox});'),
    ("wheelchair=* (way)", 'way["wheelchair"]({bbox});'),
    ("wheelchair=* (node)", 'node["wheelchair"]({bbox});'),
    ("tactile_paving", '(way["tactile_paving"]({bbox});node["tactile_paving"]({bbox});); '),
    ("建筑轮廓", 'way["building"]({bbox});'),
]


def run_query(query: str) -> dict:
    data = ("data=" + urllib.parse.quote(query)).encode()
    last_err = None
    for round_no in range(3):  # 多轮重试，公共端点限流常见
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                req = urllib.request.Request(endpoint, data=data, headers={
                    "User-Agent": "waitan-evac-demo-town-verify/1.0",
                })
                with urllib.request.urlopen(req, timeout=200) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:  # noqa: BLE001 网络抖动换备用端点
                last_err = e
                print(f"    [warn] {endpoint} 失败: {e}，换备用端点…")
                time.sleep(5 + round_no * 10)
    raise RuntimeError(f"所有 Overpass 端点均失败: {last_err}")


def count_town(bbox: tuple) -> dict:
    """一次请求拿齐一个城镇的全部指标（多个 out count 按顺序返回）。"""
    bbox_str = ",".join(str(v) for v in bbox)
    stmts = "".join(
        tpl.format(bbox=bbox_str) + "out count;" for _, tpl in METRICS
    )
    query = f"[out:json][timeout:180];{stmts}"
    result = run_query(query)
    counts = [
        int(el["tags"]["total"])
        for el in result.get("elements", [])
        if el.get("type") == "count"
    ]
    return {name: (counts[i] if i < len(counts) else -1)
            for i, (name, _) in enumerate(METRICS)}


def main():
    all_results = {}
    for town, bbox in CANDIDATES.items():
        print(f"\n=== {town}  bbox={bbox} ===")
        town_result = count_town(bbox)
        for name, n in town_result.items():
            print(f"  {name}: {n}")
        all_results[town] = town_result
        time.sleep(5)  # 对公共端点限速友好

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "town_verify_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入 {out_path}")


if __name__ == "__main__":
    main()
