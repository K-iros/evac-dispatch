# -*- coding: utf-8 -*-
"""整理落地页素材：从 scripts/raw_shots/ 的实机截图裁剪出各槽位适配图。

每个裁剪框按落地页对应卡片的显示比例反推，保证 object-fit:cover 下
关键信息（倒推链、改派弹窗、救助清单等）不被裁掉。
cmp-schedule 原图为竖版名单栏，拼为双列横幅以适配对比卡。
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "scripts" / "raw_shots"
OUT = ROOT / "landing" / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def box(src: str, dst: str, region: tuple[int, int, int, int]) -> None:
    """按绝对坐标 (left, top, right, bottom) 裁剪。"""
    img = Image.open(RAW / src).convert("RGB").crop(region)
    img.save(OUT / dst, "PNG")
    w, h = img.size
    print(f"{dst}: {w}x{h}  ratio {w / h:.2f}")


def schedule_montage(src: str, dst: str) -> None:
    """竖版名单栏切成上下两段并排，拼成横幅（对比右卡 ~2.2:1）。"""
    img = Image.open(RAW / src).convert("RGB")
    left = img.crop((0, 65, 456, 470))    # 黄阿婆 / 陈先生 / 蒙先生
    right = img.crop((0, 465, 456, 870))  # 蒋阿婆 / 欧奶奶 / 罗奶奶
    gap = 2
    canvas = Image.new("RGB", (left.width * 2 + gap, left.height), "#e5e7eb")
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width + gap, 0))
    canvas.save(OUT / dst, "PNG")
    w, h = canvas.size
    print(f"{dst}: {w}x{h}  ratio {w / h:.2f}")


if __name__ == "__main__":
    # Hero 竖幅（~0.69）：卢阿姨轮椅路线 + 接人段 + 陈社工，通向避难所方向
    box("shot-route.png", "shot-route.png", (1283, 77, 2204, 1409))
    # Bento 淹没推演（~1.85）：水深图层 + 红色失效带 + 三态路段，去掉右上缩放控件
    box("shot-flood.png", "shot-flood.png", (962, 167, 2695, 1104))
    # Bento 倒推链（顶左展示）：张奶奶行 + 「最迟出发怎么算的」逐段收紧面板
    box("shot-card.png", "shot-card.png", (0, 140, 860, 900))
    # Bento 无障碍对比（~1.44）：轮椅×步行绕行倍率面板
    box("shot-access.png", "shot-access.png", (489, 147, 1006, 506))
    # Bento 自动改派（~3.11）：山水园临江避难点失效弹窗 + 红色失效路线带
    box("shot-reassign.png", "shot-reassign.png", (1046, 530, 2672, 1053))
    # Bento 分级响应（~2.60）：无路可走·救助优先级红色清单 + 导出按钮
    box("shot-board.png", "shot-board.png", (0, 1230, 888, 1552))
    # Bento 语音路书（~1.70）：横幅取标题 + 护送里程 + 播报按钮 + 首句叙述，适配宽扁槽位
    box("shot-roadbook.png", "shot-roadbook.png", (505, 20, 1075, 355))
    # 对比左卡（~2.18）：卫星底图纯淹没视图，避开顶部告警横幅与底部图例
    box("cmp-flood.png", "cmp-flood.png", (0, 220, 2314, 1282))
    # 对比右卡：名单栏双列横幅
    schedule_montage("cmp-schedule.png", "cmp-schedule.png")
