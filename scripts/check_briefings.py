# -*- coding: utf-8 -*-
"""验证 /api/briefings：来源、条数、文本内容（写文件避开控制台编码）。"""
import json
import urllib.request
from pathlib import Path

d = json.loads(
    urllib.request.urlopen(
        "http://127.0.0.1:8000/api/briefings?scenario=s2024", timeout=60
    ).read().decode("utf-8")
)
lines = [f"source: {d['source']}  items: {len(d['items'])}"]
for it in d["items"]:
    lines.append(f"[{it['helperId']}] {it['helperName']}: {it['text']}")
out = Path(__file__).with_name("briefings_s2024.txt")
out.write_text("\n".join(lines), encoding="utf-8")
print(f"written {out}")
