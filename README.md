# 灾前疏散调度大脑

面向社区帮扶者/网格员的灾前疏散调度工具。在洪水/台风等有预警窗口的灾种下，为社区内残障与弱势人群计算"最迟帮扶出发时间"，冗余匹配帮扶者，派发无障碍路线任务。

> 背景、定位红线与完整技术决策见 [`PROJECT_CONTEXT.md`](./PROJECT_CONTEXT.md)。

## 目录结构

```
waitan/
├─ frontend/                # React + Vite + MapLibre 调度作战板（主前端）
│  └─ src/
│     ├─ components/        # TopBar 时间轴 / EvacueeList 名单 / MapView 地图
│     ├─ api/client.ts      # API 层（后端未就绪时回退 mock）
│     ├─ mock/data.ts       # 演示数据（与后端 mock 一致）
│     └─ types.ts           # 领域类型
├─ backend/                 # FastAPI + 地理计算
│  └─ app/
│     ├─ core/              # flood 淹没模型 / departure 最迟出发 / matching 匹配 / routing ORS
│     ├─ models/schemas.py  # Pydantic 模型
│     ├─ services/          # mock 数据
│     ├─ api/routes.py      # 路由
│     └─ main.py            # 入口
├─ miniprogram/             # 微信原生小程序（暂缓：审批周期原因，保留代码备用）
└─ scripts/                 # 辅助脚本（小程序 marker 图标生成等）
```

## 快速启动

### 后端
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
接口：`GET /api/health` `GET /api/schedule` `GET /api/flood/frames`

### 前端（网页版）
```powershell
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
```
访问 http://localhost:5200 （端口固定为 5200，`/api` 由 Vite 代理到 8000；后端未启动时自动回退内置 mock 数据）

### 小程序（暂缓）
`miniprogram/` 为微信原生小程序实现，因 demo 阶段审批周期原因暂不推进，代码保留备用。需要时用微信开发者工具导入该目录即可（后端未启动时同样回退 mock）。

## 当前进度

- [x] 项目初始化（后端骨架、演示数据）
- [x] 网页版调度作战板（时间轴 / 名单 / 地图，主前端，端口 5200）
- [x] 微信原生小程序端（已完成但暂缓推进，保留在 `miniprogram/`）
- [ ] 数据准备：选定演示城镇，下载 OSM `.pbf` 与 DEM
- [ ] 核心算法层：浴缸淹没模型 → 路段失效时刻 → 最迟出发时间 → 帮扶者匹配（`core/` 内为占位骨架）
- [ ] 盲人画像与 LLM 语音路书（增量）
