# -*- coding: utf-8 -*-
"""生成「扫码现场体验」二维码素材。

二期决策 2（扫码路径改道）：二维码不直落作战板，改落响应式落地页
/intro/（docker-compose 已把 landing/ 只读挂到 nginx 该路径），手机
扫码体验闭环完整；完整作战板由落地页引导在电脑端打开（DEMO_URL）。
换公网地址后改下方 QR_URL 并重跑本脚本，同时同步 landing/index.html
里的 DEMO_URL（指向作战板）。
输出黑白高对比二维码（最稳的扫码方案），置于白色圆角卡中展示。
"""
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M

# ▼▼▼ 换公网地址后改这一处（扫码落落地页，非作战板） ▼▼▼
QR_URL = "http://121.41.172.35/intro/"
# ▲▲▲ 并同步 landing/index.html 里的 DEMO_URL（指向作战板） ▲▲▲

OUT = Path(__file__).resolve().parents[1] / "landing" / "assets" / "qr-demo.png"

qr = qrcode.QRCode(
    version=None,
    error_correction=ERROR_CORRECT_M,  # 容错，现场投影/反光更稳
    box_size=12,
    border=2,
)
qr.add_data(QR_URL)
qr.make(fit=True)
img = qr.make_image(fill_color="#14100a", back_color="#ffffff").convert("RGB")
img.save(OUT, "PNG")
print(f"qr-demo.png: {img.size[0]}x{img.size[1]}  ->  {QR_URL}")
