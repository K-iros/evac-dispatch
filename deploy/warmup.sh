#!/usr/bin/env bash
# 三情景串行预热(严禁并发,GIL 争抢会恶化求解耗时)
set -u
for sc in s30 s2024 extreme; do
  echo "warmup $sc start $(date +%T)"
  curl -s -o /dev/null -w "$sc: %{http_code} ${sc}_time=%{time_total}s\n" \
    --max-time 600 "http://localhost/api/schedule?scenario=$sc"
done
echo "warmup done $(date +%T)"
