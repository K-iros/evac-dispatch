#!/usr/bin/env bash
# 发布/更新脚本:拉代码 → 构建 → 启动 → 预热三情景
# 用法:bash deploy/deploy.sh   (在仓库根目录执行)
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> 拉取最新代码"
git pull --ff-only

echo "==> 构建并启动容器"
docker compose up -d --build

echo "==> 等待后端健康(最多 120s)"
for i in $(seq 1 24); do
  if docker exec evac-backend python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/scenarios', timeout=5)" \
    2>/dev/null; then
    echo "后端已就绪"
    break
  fi
  [ "$i" -eq 24 ] && { echo "后端 120s 未就绪,查看日志: docker logs evac-backend"; exit 1; }
  sleep 5
done

# 预热:冷启动 /api/schedule 求解 90-486s/情景,lifespan 已后台预热,
# 这里串行单发长超时请求确认三情景全部缓存完成(严禁并发/超时重试)
echo "==> 预热三情景(每情景最长 10 分钟,请耐心等待)"
for sc in s30 s2024 extreme; do
  echo "  预热情景: $sc ..."
  t0=$(date +%s)
  docker exec evac-backend python -c "
import urllib.request
urllib.request.urlopen('http://localhost:8000/api/schedule?scenario=$sc', timeout=600).read()
"
  echo "  $sc 完成,耗时 $(( $(date +%s) - t0 ))s"
done

echo "==> 部署完成: http://$(curl -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')"
