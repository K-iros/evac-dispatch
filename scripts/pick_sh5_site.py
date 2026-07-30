# -*- coding: utf-8 -*-
"""第十三节第 7 项：sh-5 高地兜底避难点选址（水深场扫描，方法同 sh-3 重选）。

对候选 OSM 真实地物逐一扫描三情景全部推演帧：
- 全程安全判据：任意情景任意帧，点位均不落入任何 minDepth ≥ 0.05m
  水深面或任何 v·d 面（比避难所失效判据 0.3m/0.5 更严——兜底点要求
  完全不进水，才能承接二次转移的"终极兜底"角色）；
- 同时打印现有 4 个避难所在三情景下的失效时刻（SHELTER_HAZARD 口径
  depth≥0.3 / vd≥0.5），供改派链级联与文档回填。

运行：backend\\.venv\\Scripts\\python.exe scripts/pick_sh5_site.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from shapely.geometry import Point, shape  # noqa: E402
from shapely.prepared import prep  # noqa: E402

from app.core.flood import SCENARIOS, compute_flood_frames  # noqa: E402

#: 候选点（OSM 真实地物，西侧/南侧高地，见 scripts/yangshuo_places.json）
CANDIDATES = [
    ("欧美达英文书院", 110.4763445, 24.7733866),
    ("富康医院", 110.4788227, 24.7755786),
    ("阳朔县实验小学", 110.4767262, 24.7751975),
    ("阳朔中学", 110.4926195, 24.7709394),
    ("阳朔县妇幼保健院", 110.4802938, 24.7767296),
]

#: 现有避难所（失效时刻参考）
EXISTING = [
    ("sh-1 阳朔公园", 110.48455, 24.77903),
    ("sh-2 县实验小学体育馆", 110.47673, 24.7752),
    ("sh-3 山水园临江避难点", 110.4923, 24.7791),
    ("sh-4 县外语实验中学", 110.48942, 24.7918),
]


def frame_polys(frame, depth_thr, vd_thr):
    polys = []
    for feat in frame.geojson.get("features", []):
        props = feat.get("properties") or {}
        d, vd = props.get("minDepth"), props.get("minVd")
        if d is not None and d >= depth_thr:
            polys.append(prep(shape(feat["geometry"])))
        elif vd is not None and vd >= vd_thr:
            polys.append(prep(shape(feat["geometry"])))
    return polys


def first_hit_minute(pt, frames, depth_thr, vd_thr):
    p = Point(pt)
    for frame in frames:
        if any(g.contains(p) for g in frame_polys(frame, depth_thr, vd_thr)):
            return frame.minute
    return None


def main():
    all_frames = {key: compute_flood_frames(key) for key in SCENARIOS}

    print("== 现有避难所失效时刻（depth≥0.3 或 vd≥0.5） ==")
    for name, lng, lat in EXISTING:
        hits = {
            key: first_hit_minute((lng, lat), frames, 0.3, 0.5)
            for key, frames in all_frames.items()
        }
        print(f"  {name}: " + "  ".join(
            f"{k}={'+'+str(v)+'min' if v is not None else '安全'}"
            for k, v in hits.items()))

    print("== sh-5 候选点（全程安全判据 depth≥0.05 或任何 v·d） ==")
    for name, lng, lat in CANDIDATES:
        hits = {
            key: first_hit_minute((lng, lat), frames, 0.05, 0.0)
            for key, frames in all_frames.items()
        }
        safe = all(v is None for v in hits.values())
        print(f"  {'✓' if safe else '✗'} {name} ({lng}, {lat}): " + "  ".join(
            f"{k}={'+'+str(v)+'min' if v is not None else '安全'}"
            for k, v in hits.items()))


if __name__ == "__main__":
    main()
