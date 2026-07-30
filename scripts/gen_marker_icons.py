"""生成小程序地图 marker 图标（纯标准库，无需 PIL）。

输出 48x48 带白边圆点 PNG 到 miniprogram/assets/：
    python scripts/gen_marker_icons.py
"""

import math
import struct
import zlib
from pathlib import Path

SIZE = 48
OUT_DIR = Path(__file__).resolve().parent.parent / "miniprogram" / "assets"

# 与 pages/map/map.wxss 图例颜色保持一致
ICONS = {
    "evacuee.png": (249, 115, 22),  # 待撤离（橙）
    "evacuee-alert.png": (239, 68, 68),  # 未匹配（红）
    "helper.png": (59, 130, 246),  # 帮扶者（蓝）
    "helper-off.png": (148, 163, 184),  # 帮扶者不可用（灰）
    "shelter.png": (16, 185, 129),  # 避难所（绿）
}


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def make_icon(path: Path, rgb: tuple[int, int, int]) -> None:
    cx = cy = (SIZE - 1) / 2
    r_outer = SIZE / 2 - 1
    r_inner = r_outer - 5  # 白色描边宽度

    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)  # filter: None
        for x in range(SIZE):
            d = math.hypot(x - cx, y - cy)
            if d <= r_inner:
                px = (*rgb, 255)
            elif d <= r_outer:
                # 白色描边，最外 1px 渐隐抗锯齿
                alpha = 255 if d <= r_outer - 1 else max(0, int(255 * (r_outer - d)))
                px = (255, 255, 255, alpha)
            else:
                px = (0, 0, 0, 0)
            raw.extend(px)

    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)  # RGBA8
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rgb in ICONS.items():
        make_icon(OUT_DIR / name, rgb)
        print(f"wrote {OUT_DIR / name}")
