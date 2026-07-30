"""FastAPI 入口。

开发运行：
    cd backend
    python -m venv .venv && .venv\\Scripts\\activate
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.flood import SCENARIOS
from app.services.mock_data import build_mock_schedule


@asynccontextmanager
async def lifespan(_: FastAPI):
    """后台预热三情景的水深场反推缓存：扩容到 28 条路线后
    单情景冷启动反推需 15-30s，预热后演示现场切情景秒回。"""
    tasks = [
        asyncio.create_task(asyncio.to_thread(build_mock_schedule, key))
        for key in SCENARIOS
    ]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="灾前疏散调度大脑", version="0.1.0", lifespan=lifespan)

# 开发期允许 Vite dev server 直连（生产走同源反代）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5200"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
