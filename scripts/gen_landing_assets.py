# -*- coding: utf-8 -*-
"""整理落地页素材：从项目根目录的真实 e2e 截图裁剪出干净的产品图。

去掉右侧/底部滚动条与截图残留的黑色区域，输出到 landing/assets/。
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "landing" / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def autocrop_dark(img: Image.Image, threshold: int = 24) -> Image.Image:
    """裁掉右侧与底部整列/整行近黑的区域（截图残留的黑边）。"""
    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()

    right = w
    for x in range(w - 1, -1, -1):
        col_max = max(px[x, y] for y in range(0, h, 4))
        if col_max > threshold:
            right = x + 1
            break
    bottom = h
    for y in range(h - 1, -1, -1):
        row_max = max(px[x, y] for x in range(0, right, 4))
        if row_max > threshold:
            bottom = y + 1
            break
    return img.crop((0, 0, right, bottom))


def prep(src: str, dst: str, trim: tuple[int, int, int, int] = (0, 0, 0, 0)) -> None:
    """trim = (left, top, right, bottom) 额外裁剪像素。"""
    img = Image.open(ROOT / src).convert("RGB")
    img = autocrop_dark(img)
    l, t, r, b = trim
    w, h = img.size
    img = img.crop((l, t, w - r, h - b))
    img.save(OUT / dst, "PNG")
    print(f"{dst}: {img.size[0]}x{img.size[1]}")


def box(src: str, dst: str, region: tuple[int, int, int, int]) -> None:
    """按绝对坐标 (left, top, right, bottom) 裁剪。"""
    img = Image.open(ROOT / src).convert("RGB").crop(region)
    img.save(OUT / dst, "PNG")
    print(f"{dst}: {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    # 竖幅路线图：接人段/护送段/障碍标记/避难所，落地页主视觉
    prep("e2e_verify_step5_locate_lu_route_wide.png", "shot-route.png", (0, 0, 14, 16))
    # 淹没推演：水深分级蓝色图层 + 路段三态着色 + 图例
    prep("e2e_step2_frame21_map.png", "shot-flood.png", (0, 0, 14, 16))
    # 作战板全景：名单 + 地图 + 避难所失效弹窗 + 整所转移横幅
    prep("verify_e2e_step5_shelter_popup.png", "shot-board.png", (0, 0, 14, 16))
    # 路径卡：串行任务 + 倒推链 + 补位演练按钮
    prep("verify_e2e_step6_zhangnainai.png", "shot-card.png", (0, 0, 14, 16))
    # 盲人路书卡：视障引导路线 + 失效告警（只取卡片区域，右缘止于卡片边界 x=342）
    box("e2e_step6_playback.png", "shot-roadbook.png", (26, 161, 342, 380))
    # 自动改派：避难所被淹改派横幅 + P0/P1 清单（去除右侧黑区）
    box("reverify_frame18_reassign.png", "shot-reassign.png", (0, 0, 652, 406))
