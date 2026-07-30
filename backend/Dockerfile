# 后端运行时镜像:FastAPI + 预计算数据
# 构建上下文 = 仓库根目录(需要 COPY frontend/public/streetview 供 CV 识别读原图)
FROM python:3.12-slim

WORKDIR /app

# 国内服务器走阿里云 PyPI 镜像加速;依赖层独立缓存
COPY backend/requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt \
    -i https://mirrors.aliyun.com/pypi/simple/

# 代码与运行时数据
COPY backend/app ./app
COPY backend/data ./data

# cv_access.py 以 parents[3]/frontend/public/streetview 读街景原图,
# 容器内 /app/app/services 的 parents[3] = / ,故放到 /frontend/public/streetview
COPY frontend/public/streetview /frontend/public/streetview

EXPOSE 8000

# 单 worker:进程内 lru_cache 预热三情景,多 worker 会重复预热且内存翻倍
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
