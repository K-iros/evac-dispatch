# -*- coding: utf-8 -*-
"""阳朔洪水离线推演（第十一节：模型修正 + 多情景 + 流速场）。

模型修正一（水位基准与时间尺度）：
  - 时间尺度 3h → 24h（1440 分钟），帧间隔 60 分钟，与"洪水预警窗口
    1-3 天"的产品前提一致
  - 涨幅改为分段过程线（缓涨→急涨→临峰趋缓），参照桂林站 2024-06
    首峰→急涨→主峰的节奏；总涨幅按情景 4.2 / 5.5 / 7.0 m
  - 水位显示口径：阳朔站绝对水位 = 常水位基准 105.5m + 涨幅，
    警戒水位 109.5m（2024-06 阳朔站洪峰 110.77m 超警 1.27m 反推）
  - 每帧带 clock 模拟时钟标签（T0 = 2024-06-19 00:00）

模型修正二（补齐内涝水路 pluvial）：
  - 降雨源项：24h 累计约 290mm（2024-06 量级），峰值时段 45mm/h，
    全域落雨、低洼处自然汇积（OverlandFlow.rainfall_intensity）
  - 排水能力负源项：县城管网 20mm/h，暴雨超出部分才积水；
    外江涨幅超过 2.5m（管口顶托）后排水置零——复现顶托失效

功能 B 数据（v×d 危险度）：
  - OverlandFlow 的 surface_water__discharge（链路单宽流量 q，m²/s）
    即 v·d；取节点邻接链路最大 |q|，按 0.25 / 0.40 / 0.50 m²/s
    三档阈值矢量化为 minVd 面（轮椅 0.25、老人 0.40、行人 0.50 失稳）

输出 backend/data/flood_frames_{scenario}.json（FloodFrame 序列，
backend/app/core/flood.py 按情景加载）。
"""
import json
import os
import time
from datetime import datetime, timedelta

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio import features as rio_features
from shapely.geometry import LineString, Polygon, shape
from shapely.ops import transform as shp_transform

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEM_PATH = os.path.join(ROOT, "backend", "data", "yangshuo_dem_utm.tif")
OSM_PATH = os.path.join(ROOT, "backend", "data", "yangshuo_osm.json")
OUT_TPL = os.path.join(ROOT, "backend", "data", "flood_frames_%s.json")

TOTAL_MIN = 1440          # 24h 推演窗口
FRAME_STEP_MIN = 60       # 每小时一帧
SIM_T0 = datetime(2024, 6, 19, 0, 0)  # 模拟时钟起点（2024-06 漓江洪水节奏）
BASE_STAGE = 105.5        # 阳朔站常水位基准（m，洪峰 110.77 - 涨幅 5.5 反推）
WARN_STAGE = 109.5        # 阳朔站警戒水位（2024-06 洪峰超警 1.27m 反推）

# 深度分档（m）：0.05 视觉层 / 0.15 轮椅失效 / 0.30 步行失效 / 深水渐变档
DEPTH_LEVELS = (0.05, 0.15, 0.30, 0.60, 1.20, 2.00)
# v·d 失稳分档（m²/s）：0.25 轮椅 / 0.40 老人 / 0.50 成人行人
VD_LEVELS = (0.25, 0.40, 0.50)
MIN_POLY_AREA_M2 = 1200.0  # 丢弃 <3 个栅格的碎多边形
BUILDING_RAISE = 5.0
ROAD_LOWER = 0.3

DRAIN_MM_H = 20.0         # 县城管网排水能力
DRAIN_CUTOFF_RISE = 2.5   # 外江涨幅超此值后管口顶托，排水置零

# 基准雨型（分钟, mm/h）分段常数：缓雨→峰值段（12-16h 45mm/h）→退雨
RAIN_BASE = [(0, 3.0), (360, 8.0), (720, 45.0), (960, 8.0), (1200, 3.0)]

#: 情景 → 水位过程线断点 [(分钟, 累计涨幅 m)]（线性插值）+ 雨型缩放
SCENARIOS = {
    "s30": {
        "label": "30年一遇",
        "hydrograph": [(0, 0.0), (720, 0.8), (1200, 3.8), (1440, 4.2)],
        "rain_scale": 0.6,
    },
    "s2024": {
        "label": "2024-06 漓江洪水情景",
        "hydrograph": [(0, 0.0), (720, 1.0), (1200, 5.0), (1440, 5.5)],
        "rain_scale": 1.0,
    },
    "extreme": {
        "label": "极端情景",
        "hydrograph": [(0, 0.0), (600, 1.5), (1140, 6.4), (1440, 7.0)],
        "rain_scale": 1.4,
    },
}


def rise_at(minute, hydrograph):
    """分段过程线：t 分钟时相对常水位的累计涨幅（米）。"""
    xs = [p[0] for p in hydrograph]
    ys = [p[1] for p in hydrograph]
    return float(np.interp(minute, xs, ys))


def rain_at(minute, scale):
    """分段常数雨型：t 分钟时降雨强度（mm/h）。"""
    rate = RAIN_BASE[0][1]
    for start, mm_h in RAIN_BASE:
        if minute >= start:
            rate = mm_h
    return rate * scale


def net_rain_m_s(minute, scale, rise):
    """净雨强度（m/s）：降雨 - 排水；外江顶托后排水失效。"""
    drain = 0.0 if rise > DRAIN_CUTOFF_RISE else DRAIN_MM_H
    return max(rain_at(minute, scale) - drain, 0.0) / 1000.0 / 3600.0


def condition_dem():
    """DEM 条件化：建筑 +5m、道路 -0.3m；返回 (dem, transform, water_mask)。"""
    with rasterio.open(DEM_PATH) as src:
        dem = src.read(1)
        transform = src.transform
        crs = src.crs
    # 填补零星 nodata（取有效均值，域内基本无缺失）
    if np.isnan(dem).any():
        dem = np.where(np.isnan(dem), np.nanmean(dem), dem)

    with open(OSM_PATH, encoding="utf-8") as f:
        osm = json.load(f)
    to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform

    def utm_polys(rings):
        out = []
        for ring in rings:
            if len(ring) < 4:
                continue
            try:
                p = shp_transform(to_utm, Polygon(ring))
                if p.is_valid and p.area > 0:
                    out.append(p)
            except Exception:  # noqa: BLE001
                continue
        return out

    shape_hw = dem.shape

    # 建筑 +5m：不可淹没的阻水体
    blds = utm_polys(osm["buildings"])
    bld_mask = rio_features.rasterize(
        [(g, 1) for g in blds], out_shape=shape_hw, transform=transform,
        fill=0, dtype="uint8")
    # 道路 -0.3m：低洼导水通道（中心线栅格化，all_touched 保证 20m 网格连通）
    roads = []
    for r in osm["roads"]:
        if len(r["coords"]) >= 2:
            roads.append(shp_transform(to_utm, LineString(r["coords"])))
    road_mask = rio_features.rasterize(
        [(g, 1) for g in roads], out_shape=shape_hw, transform=transform,
        fill=0, dtype="uint8", all_touched=True)
    # 水面：只取宏观水体（漓江主河道 riverbank）作水位边界，
    # 排除山间小水塘，避免高处孤立水体被当作洪源
    water = [p for p in utm_polys(osm["water"]) if p.area >= 1e5]
    water_mask = rio_features.rasterize(
        [(g, 1) for g in water], out_shape=shape_hw, transform=transform,
        fill=0, dtype="uint8", all_touched=True)

    dem = dem.astype("float64")
    dem[(road_mask == 1) & (bld_mask == 0)] -= ROAD_LOWER
    dem[(bld_mask == 1)] += BUILDING_RAISE
    print("条件化：建筑 %d 栅格 +%.1fm，道路 %d 栅格 -%.1fm，水面 %d 栅格" % (
        int(bld_mask.sum()), BUILDING_RAISE, int(road_mask.sum()), ROAD_LOWER,
        int(water_mask.sum())))
    return dem, transform, water_mask == 1


def field_to_features(field, levels, prop_name, transform, to_wgs):
    """标量场 → 按阈值分档矢量化（浅档在前，深档后画覆盖在上）。"""
    feats = []
    for lvl in levels:
        mask = (field >= lvl).astype("uint8")
        if mask.sum() == 0:
            continue
        for geom, val in rio_features.shapes(mask, mask=mask == 1, transform=transform):
            if val != 1:
                continue
            poly = shape(geom)
            if poly.area < MIN_POLY_AREA_M2:
                continue
            poly = shp_transform(to_wgs, poly.simplify(10.0))
            coords = [
                [[round(x, 5), round(y, 5)] for x, y in ring.coords]
                for ring in [poly.exterior, *poly.interiors]
            ]
            feats.append({
                "type": "Feature",
                "properties": {prop_name: lvl},
                "geometry": {"type": "Polygon", "coordinates": coords},
            })
    return feats


def run_scenario(key, cfg, dem, transform, water_mask):
    """跑一个情景的 24h 推演，输出 FloodFrame 序列 JSON。"""
    from landlab import RasterModelGrid
    from landlab.components.overland_flow import OverlandFlow

    nrows, ncols = dem.shape
    dx = transform.a
    to_wgs = Transformer.from_crs("EPSG:32649", "EPSG:4326", always_xy=True).transform
    hydrograph = cfg["hydrograph"]
    rain_scale = cfg["rain_scale"]

    # landlab 节点序自左下角起 → DEM（行 0 = 北）需上下翻转
    grid = RasterModelGrid((nrows, ncols), xy_spacing=dx)
    grid.add_field("topographic__elevation", np.flipud(dem).ravel(), at="node")
    grid.add_zeros("surface_water__depth", at="node")
    grid.at_node["surface_water__depth"] += 1e-8
    grid.set_closed_boundaries_at_grid_edges(True, True, True, True)

    river_nodes = np.flatnonzero(np.flipud(water_mask).ravel())
    z = grid.at_node["topographic__elevation"]
    h = grid.at_node["surface_water__depth"]
    print("[%s] 河道节点 %d 个，水面高程 %.1f ~ %.1f m" % (
        key, len(river_nodes), z[river_nodes].min(), z[river_nodes].max()))

    of = OverlandFlow(grid, steep_slopes=True, mannings_n=0.04, alpha=0.7, h_init=1e-8)
    q_link = grid.at_link["surface_water__discharge"]

    frames = []
    next_frame_min = 0
    elapsed = 0.0
    t0 = time.time()

    def export_frame(minute):
        depth = np.flipud(h.reshape(nrows, ncols)).copy()
        depth[water_mask] = 0.0  # 河道常水面不算淹没区
        # v·d 危险度场：节点邻接链路最大单宽流量 |q|（m²/s），只统计有水处
        vd_node = grid.map_max_of_node_links_to_node(np.abs(q_link))
        vd = np.flipud(vd_node.reshape(nrows, ncols)).copy()
        vd[water_mask] = 0.0
        vd[depth < DEPTH_LEVELS[0]] = 0.0
        feats = field_to_features(depth, DEPTH_LEVELS, "minDepth", transform, to_wgs)
        feats += field_to_features(vd, VD_LEVELS, "minVd", transform, to_wgs)
        rise = rise_at(minute, hydrograph)
        stage = BASE_STAGE + rise
        frames.append({
            "minute": minute,
            "water_level": round(rise, 2),
            "stage_m": round(stage, 2),
            "warn_m": round(stage - WARN_STAGE, 2),
            "clock": (SIM_T0 + timedelta(minutes=minute)).isoformat(),
            "geojson": {"type": "FeatureCollection", "features": feats},
        })
        wet = int((depth >= DEPTH_LEVELS[0]).sum())
        print("[%s] 帧 +%4d min | 涨幅 %.2fm | 淹没 %5d 栅格 (%.2f km²) | %d 面 | 用时 %.0fs" % (
            key, minute, rise, wet, wet * dx * dx / 1e6, len(feats), time.time() - t0))

    while elapsed <= TOTAL_MIN * 60:
        minute = elapsed / 60.0
        # 水位边界：漓江水面按分段过程线抬升——每个河道单元以自身
        # 水面高程（DSM 记录即水面）为基准抬升 rise(t)，满溢后由
        # OverlandFlow 向两岸低处漫流
        rise = rise_at(minute, hydrograph)
        h[river_nodes] = np.maximum(h[river_nodes], max(rise, 1e-8))
        # 降雨/排水源项（pluvial 内涝水路）：净雨全域落地
        of.rainfall_intensity = net_rain_m_s(minute, rain_scale, rise)

        if elapsed >= next_frame_min * 60:
            export_frame(next_frame_min)
            next_frame_min += FRAME_STEP_MIN

        of.dt = min(of.calc_time_step(), 30.0)
        of.overland_flow()
        elapsed += of.dt

    if next_frame_min <= TOTAL_MIN:  # 末帧（+1440）兼顾步长跨过循环边界
        export_frame(next_frame_min)

    out_path = OUT_TPL % key
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(frames, f, ensure_ascii=False)
    print("[%s] 已写入 %s（%d 帧，%.1f MB，总耗时 %.0fs）" % (
        key, out_path, len(frames), os.path.getsize(out_path) / 1e6, time.time() - t0))


def main():
    import sys

    dem, transform, water_mask = condition_dem()
    keys = sys.argv[1:] or list(SCENARIOS)
    for key in keys:
        run_scenario(key, SCENARIOS[key], dem, transform, water_mask)


if __name__ == "__main__":
    main()
