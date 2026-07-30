# 前端多阶段构建:node 产出 dist → nginx 托管静态文件 + /api 反代
# 构建上下文 = frontend/ 目录

# ---- 阶段 1:构建 ----
FROM node:22-alpine AS build

WORKDIR /build

# 依赖层独立缓存;国内服务器走 npmmirror 加速
COPY package.json package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com \
    && npm ci

COPY . .
RUN npm run build

# ---- 阶段 2:运行 ----
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 80
