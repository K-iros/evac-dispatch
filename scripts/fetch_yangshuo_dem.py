# -*- coding: utf-8 -*-
"""下载并裁剪阳朔演示区 DEM，输出 UTM 49N / 20m 栅格。

主选 Copernicus GLO-30（AWS 公共 COG，/vsicurl/ 窗口读取，免注册；
FABDEM 需注册下载，当前网络不可行，垂直精度差异对演示可接受）。
备选 AWS Terrarium 高程瓦片（elevation-tiles-prod，z14 约 9m/px）。

输出 backend/data/yangshuo_dem_utm.tif（EPSG:32649，20m）。
"""
import io
import math
import os
import urllib.request

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import from_bounds as window_from_bounds

# 演示区 bbox（WGS84，w/s/e/n）：漓江河湾 + 老城区 + 阳朔公园
BBOX = (110.455, 24.750, 110.525, 24.810)
DST_CRS = "EPSG:32649"  # UTM 49N（110.5°E）
DST_RES = 20.0  # m

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "backend", "data", "yangshuo_dem_utm.tif")

COPERNICUS = ("/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/"
              "Copernicus_DSM_COG_10_N24_00_E110_00_DEM/"
              "Copernicus_DSM_COG_10_N24_00_E110_00_DEM.tif")

TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TERRARIUM_Z = 14


def warp_to_utm(src_arr, src_transform, src_crs):
    """把源栅格重投影为 UTM 49N / 20m，裁剪到 BBOX。"""
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:4326", DST_CRS, always_xy=True)
    xs, ys = tf.transform([BBOX[0], BBOX[2]], [BBOX[1], BBOX[3]])
    w, e = min(xs), max(xs)
    s, n = min(ys), max(ys)
    width = int(round((e - w) / DST_RES))
    height = int(round((n - s) / DST_RES))
    dst_transform = from_bounds(w, s, e, n, width, height)
    dst = np.full((height, width), np.nan, dtype="float32")
    reproject(
        source=src_arr.astype("float32"),
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=DST_CRS,
        resampling=Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with rasterio.open(
        OUT, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=DST_CRS, transform=dst_transform, nodata=np.nan,
        compress="deflate",
    ) as ds:
        ds.write(dst, 1)
    valid = dst[np.isfinite(dst)]
    print("已写入 %s  %dx%d  高程 %.1f ~ %.1f m（均值 %.1f）" % (
        OUT, width, height, valid.min(), valid.max(), valid.mean()))


def fetch_copernicus():
    print("尝试 Copernicus GLO-30 (/vsicurl/ AWS COG) ...")
    env = rasterio.Env(GDAL_HTTP_TIMEOUT=40, GDAL_HTTP_MAX_RETRY=2,
                       GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR")
    with env, rasterio.open(COPERNICUS) as src:
        win = window_from_bounds(*BBOX, transform=src.transform)
        arr = src.read(1, window=win)
        transform = src.window_transform(win)
        warp_to_utm(arr, transform, src.crs)


def _tile_xy(lng, lat, z):
    n = 2 ** z
    x = (lng + 180) / 360 * n
    lat_r = math.radians(lat)
    y = (1 - math.asinh(math.tan(lat_r)) / math.pi) / 2 * n
    return x, y


def fetch_terrarium():
    from PIL import Image

    print("回退 AWS Terrarium 瓦片 (z=%d) ..." % TERRARIUM_Z)
    z = TERRARIUM_Z
    x0f, y1f = _tile_xy(BBOX[0], BBOX[1], z)  # 左下
    x1f, y0f = _tile_xy(BBOX[2], BBOX[3], z)  # 右上
    x0, x1 = int(x0f), int(x1f)
    y0, y1 = int(y0f), int(y1f)
    cols, rows = x1 - x0 + 1, y1 - y0 + 1
    mosaic = np.zeros((rows * 256, cols * 256), dtype="float32")
    for yi in range(y0, y1 + 1):
        for xi in range(x0, x1 + 1):
            url = TERRARIUM.format(z=z, x=xi, y=yi)
            req = urllib.request.Request(url, headers={"User-Agent": "waitan-evac-demo/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                img = Image.open(io.BytesIO(r.read())).convert("RGB")
            px = np.asarray(img, dtype="float32")
            elev = px[:, :, 0] * 256 + px[:, :, 1] + px[:, :, 2] / 256 - 32768
            mosaic[(yi - y0) * 256:(yi - y0 + 1) * 256,
                   (xi - x0) * 256:(xi - x0 + 1) * 256] = elev
            print("  tile %d/%d/%d ok" % (z, xi, yi))
    # 瓦片镶嵌为 Web Mercator 栅格
    R = 6378137.0
    n = 2 ** z
    tile_m = 2 * math.pi * R / n

    def merc_x(xi):
        return -math.pi * R + xi * tile_m

    def merc_y(yi):
        return math.pi * R - yi * tile_m

    transform = rasterio.transform.from_origin(
        merc_x(x0), merc_y(y0), tile_m / 256, tile_m / 256)
    warp_to_utm(mosaic, transform, "EPSG:3857")


def main():
    try:
        fetch_copernicus()
        print("DEM 来源：Copernicus GLO-30")
    except Exception as e:  # noqa: BLE001
        print("  [warn] Copernicus 失败: %s" % e)
        fetch_terrarium()
        print("DEM 来源：AWS Terrarium z%d" % TERRARIUM_Z)


if __name__ == "__main__":
    main()
