#!/usr/bin/env bash
# 服务器一次性初始化:Ubuntu 22.04 安装 Docker + Compose 插件(阿里云镜像源)
# 用法:bash deploy/setup-server.sh
set -euo pipefail

echo "==> 安装 Docker(阿里云 apt 源)"
apt-get update
apt-get install -y ca-certificates curl gnupg git

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

echo "==> 配置 Docker Hub 国内镜像加速"
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.net"
  ]
}
EOF
systemctl restart docker
systemctl enable docker

docker --version
docker compose version
echo "==> Docker 环境就绪"
