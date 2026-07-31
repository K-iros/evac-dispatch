#!/usr/bin/env bash
# 从容器取回已算好的 LF 缓存到宿主仓库(EOL 修复:避免本地 27min 重算)
set -eu
cd /root/evac-dispatch
for sc in s30 s2024 extreme; do
  docker cp "evac-backend:/app/data/schedule_${sc}.json" "backend/data/schedule_${sc}.json"
done
echo "== 容器内指纹校验 =="
docker exec evac-backend python /app/check_cache.py
echo "== 宿主 schedule 缓存 sha256 =="
for sc in s30 s2024 extreme; do sha256sum "backend/data/schedule_${sc}.json"; done
echo "== 宿主 yangshuo_schedule.json sha256 =="
sha256sum backend/data/yangshuo_schedule.json
