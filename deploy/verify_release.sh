#!/usr/bin/env bash
# 发布后验证:三情景响应耗时 + LLM source + 落地页 /intro/
set -u
echo "== /api/schedule 三情景耗时 =="
for sc in s30 s2024 extreme; do
  curl -so /dev/null -w "$sc %{time_total}s code=%{http_code}\n" "http://localhost/api/schedule?scenario=$sc"
done
echo "== LLM source (briefings / roadbook / access-scan) =="
curl -s --max-time 90 "http://localhost/api/briefings?scenario=s2024" | head -c 120; echo
curl -s --max-time 90 "http://localhost/api/access-scan?scenario=s2024" | head -c 120; echo
echo "== 落地页 =="
curl -so /dev/null -w "/intro/ code=%{http_code} cache=%{header_json}\n" "http://localhost/intro/" 2>/dev/null \
  || curl -sI "http://localhost/intro/" | head -5
curl -so /dev/null -w "shot-flood.png code=%{http_code}\n" "http://localhost/intro/assets/shot-flood.png"
echo "== 作战板 =="
curl -so /dev/null -w "/ code=%{http_code}\n" "http://localhost/"
