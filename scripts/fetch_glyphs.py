# -*- coding: utf-8 -*-
"""下载 MapLibre 字形 pbf 到 frontend/public/fonts/ 实现自托管。

背景：fonts.openmaptiles.org 在国内不可达，带 text-field 的 symbol 图层
必须等字形加载成功才渲染，导致人物/避难所图标整层消失。
源：jsDelivr 镜像 openmaptiles/fonts@gh-pages（已验证可达）。
字体：Klokantech Noto Sans CJK Regular（含中文字形，共 256 个 range）。
"""
from __future__ import annotations

import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

FONT = "Klokantech Noto Sans CJK Regular"
BASE = "https://cdn.jsdelivr.net/gh/openmaptiles/fonts@gh-pages"
OUT_DIR = Path(__file__).resolve().parents[1] / "frontend" / "public" / "fonts" / FONT

RANGES = [f"{i * 256}-{i * 256 + 255}" for i in range(256)]  # 0-255 … 65280-65535


def fetch(rng: str) -> tuple[str, int]:
    dest = OUT_DIR / f"{rng}.pbf"
    if dest.exists() and dest.stat().st_size > 0:
        return rng, dest.stat().st_size  # 断点续跑：已存在则跳过
    url = f"{BASE}/{urllib.parse.quote(FONT)}/{rng}.pbf"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return rng, len(data)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch, r): r for r in RANGES}
        for i, fut in enumerate(as_completed(futures), 1):
            rng = futures[fut]
            try:
                _, size = fut.result()
                total += size
                if i % 32 == 0 or i == len(RANGES):
                    print(f"[{i}/{len(RANGES)}] cumulative {total / 1e6:.1f} MB")
            except Exception as exc:  # noqa: BLE001
                failed.append(rng)
                print(f"FAIL {rng}: {exc}")
    if failed:
        print(f"failed ranges ({len(failed)}): {failed}")
        return 1
    print(f"done: {len(RANGES)} files, {total / 1e6:.1f} MB -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
