# -*- coding: utf-8 -*-
"""生成落地页「扫码现场体验」二维码素材。

用法：部署拿到公网 demo 地址后，把下面的 DEMO_URL 改成公网地址并重跑本脚本，
同时把 landing/index.html 中的 DEMO_URL 常量改成同一地址（两处保持一致）。
输出黑白高对比二维码（最稳的扫码方案），置于白色圆角卡中展示。
"""
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M

# ▼▼▼ 部署后改这一处 ▼▼▼
DEMO_URL = "http://localhost:5200"
# ▲▲▲ 并同步 landing/index.html 里的 DEMO_URL ▲▲▲

OUT = Path(__file__).resolve().parents[1] / "landing" / "assets" / "qr-demo.png"

qr = qrcode.QRCode(
    version=None,
    error_correction=ERROR_CORRECT_M,  # 容错，现场投影/反光更稳
    box_size=12,
    border=2,
)
qr.add_data(DEMO_URL)
qr.make(fit=True)
img = qr.make_image(fill_color="#14100a", back_color="#ffffff").convert("RGB")
img.save(OUT, "PNG")
print(f"qr-demo.png: {img.size[0]}x{img.size[1]}  ->  {DEMO_URL}")
