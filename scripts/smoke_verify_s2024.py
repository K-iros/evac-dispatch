# -*- coding: utf-8 -*-
"""冒烟验证：s2024 帧数据 + sh-3 失效时序 + latestDeparture 反推。"""
import sys
sys.path.insert(0, r"d:\File\waitan\backend")

from app.core.flood import compute_flood_frames
from app.core.departure import point_flooded_minute, _hazard_polygons
from app.services.mock_data import build_mock_schedule

frames = compute_flood_frames("s2024")
print("帧数:", len(frames))
f0, fm = frames[0], frames[-1]
print("首帧:", f0.minute, f0.stage_m, f0.warn_m, f0.clock)
print("末帧:", fm.minute, fm.stage_m, fm.warn_m, fm.clock)

# 分档面统计（末帧）
from collections import Counter
c = Counter()
for feat in fm.geojson["features"]:
    p = feat["properties"]
    if "minDepth" in p:
        c["depth_%.2f" % p["minDepth"]] += 1
    if "minVd" in p:
        c["vd_%.2f" % p["minVd"]] += 1
print("末帧分档面:", dict(c))

# sh-3 山水园临江避难点 失效时序（避难所判据：深0.3 / vd0.5 → elderly 画像近似）
SH3 = (110.49230, 24.77910)
SH1 = (110.48455, 24.77903)
per = _hazard_polygons("shelter", frames, 0.30, 0.50)
from shapely.geometry import Point
def first_hit(pt):
    p = Point(pt)
    for minute, polys in per:
        if any(g.contains(p) for g in polys):
            return minute
    return None
print("sh-3 失效时刻(min):", first_hit(SH3))
print("sh-1 失效时刻(min):", first_hit(SH1))

# 三户住址被淹时刻
for name, pt, prof in [("e-1 县前街", (110.49180, 24.77950), "wheelchair"),
                       ("e-2 滨江路", (110.49275, 24.78125), "blind"),
                       ("e-3 桂花路", (110.49046, 24.77840), "elderly")]:
    print(name, "→ 首次达危险阈值:", point_flooded_minute(pt, frames, prof, "s2024"))

# 调度态势反推
s = build_mock_schedule("s2024")
for ev in s.evacuees:
    print(ev.id, ev.name, "latestDeparture =", ev.latest_departure)
for a in s.assignments:
    print(a.helper_id, "->", a.evacuee_id, "->", a.shelter_id,
          "backup=", a.is_backup, "fallback=", a.is_fallback, "arriveBy=", a.arrive_by)
