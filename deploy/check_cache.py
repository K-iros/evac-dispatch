# -*- coding: utf-8 -*-
"""容器内诊断:落盘缓存指纹是否与镜像内输入文件匹配(决策 1 发布验证)。"""
import hashlib
import json
from pathlib import Path

d = Path("data")
for sc in ("s30", "s2024", "extreme"):
    p = d / f"schedule_{sc}.json"
    if not p.exists():
        print(f"{sc}: CACHE_FILE_MISSING")
        continue
    payload = json.loads(p.read_text(encoding="utf-8"))
    expect = {
        n: hashlib.sha256((d / n).read_bytes()).hexdigest()
        for n in ("yangshuo_schedule.json", f"flood_frames_{sc}.json")
    }
    match = payload.get("inputs") == expect
    print(f"{sc}: match={match}")
    if not match:
        for k, v in expect.items():
            got = (payload.get("inputs") or {}).get(k)
            print(f"  {k}: cache={str(got)[:12]} actual={v[:12]} same={got == v}")
