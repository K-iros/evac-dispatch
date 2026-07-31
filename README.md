# 灾前疏散调度大脑

面向社区帮扶者/网格员的灾前疏散调度作战板。在洪水/台风等**有预警窗口**的灾种下，为社区内残障与弱势人群计算"最迟帮扶出发时间"，冗余匹配帮扶者，派发无障碍撤离路线——把"提前转移"从口号变成一张可执行、可解释的调度表。

## 在线演示

| 入口 | 地址 | 说明 |
|---|---|---|
| 🖥️ 调度作战板 | http://121.41.172.35/ | 主产品，为桌面指挥端设计（建议电脑端打开） |
| 📖 产品介绍页 | http://121.41.172.35/intro/ | 项目背景、能力速览与上手指南 |

演示场景：**广西阳朔县城**，三套情景可切换（30 年一遇 / 2024-06 漓江洪水情景 / 极端情景）。后端离线时前端自动回退内置演示数据，页面始终可用。

**3 分钟看懂**：打开作战板 → 拖动顶部时间轴，看漓江洪水逐小时淹没县城 → 点名单里的"陈先生（盲人）"，看他的最迟出发时间是如何沿路径逐段倒推出来的（白箱计算链）→ 点"补位演练"模拟帮扶者失联，看系统自动顶上备份 → 推进时间轴至避难所被淹，看整所人员自动改派转移 → 点盲人户的"语音路书"，闭眼听 30 秒陪同导引。

## 核心能力

- **三情景水动力淹没推演**：landlab OverlandFlow（Bates 2010 惯性简化浅水方程）基于条件化 DEM（Copernicus GLO-30 + OSM 建筑/道路修正）离线预计算，水深六档 + v·d 行人失稳双判据；
- **最迟出发时间反推**：路径 × 时变水深场求交 → 各路段失效时刻 → 沿路径反向递推，逐段中间量可解释（倒推链）；
- **帮扶者冗余匹配**：贪心 + 时间窗匹配，含同一帮扶者串行多户的链式时间口径校验（冲突红色告警）；
- **三段式无障碍路径**：Valhalla 按画像实算（wheelchair / blind / foot），接人段 + 护送段分色渲染；
- **动态推演与自愈**：24h 时间轴播放/拖动、补位演练（帮扶者失联→备份顶上）、避难所失效整所转移（不可行则就地垂直避险）、分级响应三档（预备/待命/出动）；
- **兜底与闭环**："无路可走"清单 + CSV 导出；LLM 派单简报（DeepSeek）、LLM 语音路书（TTS 播报）、街景 CV 无障碍识别（Qwen-VL）——LLM/CV 均带本地模板兜底，无 Key 也可完整演示。

## 技术栈

- **前端**：React 19 + TypeScript + Vite + Tailwind 4 + MapLibre GL 6（字形自托管，双底图 OSM/卫星）
- **后端**：FastAPI + shapely / rasterio；淹没模型 landlab（离线预计算）；路径 Valhalla 公共实例
- **部署**：docker-compose（前端 nginx 静态托管 + `/api` 同源反代后端）

## 目录结构

```
waitan/
├─ frontend/                 # 调度作战板（主前端）
│  ├─ src/components/        # TopBar 时间轴 / EvacueeList 名单 / MapView 地图与浮层
│  ├─ src/api/client.ts      # API 层（后端离线自动回退 mock）
│  ├─ src/mock/data.ts       # 内置演示数据
│  ├─ nginx.conf             # 生产配置（静态托管 / 反代 / 字形与缓存策略）
│  └─ Dockerfile
├─ backend/
│  ├─ app/core/              # flood 淹没帧加载 / departure 最迟出发反推 / matching / routing
│  ├─ app/services/          # mock_data 调度构建（含落盘缓存加载）/ briefing / roadbook / cv_access
│  ├─ app/api/routes.py      # 接口路由
│  ├─ data/                  # yangshuo_schedule.json / flood_frames_*.json / schedule_*.json 缓存
│  └─ Dockerfile
├─ landing/                  # 产品介绍页（部署为 /intro/）
├─ miniprogram/              # 微信小程序帮扶者端（已冻结；规划激活为接单/打卡端，见项目状态）
├─ scripts/                  # 数据管线与工具（洪水推演 / 数据集生成 / 调度缓存 / 二维码等）
├─ deploy/deploy.sh          # 发布脚本：拉代码 → 构建 → 健康检查 → 预热自检
├─ docker-compose.yml        # 生产编排
├─ PROJECT_CONTEXT_V1.md     # 第一期完整技术决策存档（十五节）
└─ PROJECT_CONTEXT_V2.md     # 第二期决策记录（进行中）
```

## 本地开发

### 后端
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

接口：`/api/health` `/api/scenarios` `/api/schedule` `/api/flood/frames` `/api/briefings` `/api/access-scan` `/api/roadbook`（均带 `?scenario=` 情景参数）

LLM 增强可选：设置 `DEEPSEEK_API_KEY`（派单简报/路书润色）与 `DASHSCOPE_API_KEY`（街景 CV 识别）环境变量；缺省时自动模板兜底，不阻塞任何功能。

### 前端
```powershell
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
```

访问 http://localhost:5200（端口固定 5200，`/api` 由 Vite 代理到 8000；后端未启动时自动回退内置 mock）。

## 生产部署

```bash
docker compose up -d --build     # 或增量发布：bash deploy/deploy.sh
```

两个关键机制：

- **调度结果落盘缓存**：三情景调度计算（最迟出发反推，CPU 密集）已预计算为 `backend/data/schedule_{s30,s2024,extreme}.json` 随仓库分发，带输入指纹（SHA256）校验——重启秒级恢复，输入数据变更时自动回落实时计算并刷新缓存。**发布纪律**：改动 `yangshuo_schedule.json` 或洪水帧后，须本地重跑 `python scripts/gen_schedule_cache.py` 并将缓存与代码同一提交推送，否则线上重建后预热将回落 20+ 分钟实时计算（功能不坏，发布窗口拖长）。
- **地图稳定性加固**：MapLibre worker 显式打包注入（rolldown-vite 产物修复）、中文字形自托管于 `public/fonts/`（不依赖外部字形源）、`index.html` no-cache（发版后普通刷新即生效）。

## 项目状态

第一期（产品闭环，P0/P1 全部完成）已存档于 `PROJECT_CONTEXT_V1.md`；第二期进行中，已完成后端冷启动落盘缓存、手机端引导与窄屏止血，决策记录见 `PROJECT_CONTEXT_V2.md`。

**规划中**：

- **Web 端调度 → 小程序接收，调度中心与个人联动**：指挥端在作战板派单，帮扶者在微信小程序接单（`accept`）、到场打卡（`checkin`），状态回流作战板形成派单→接单→执行→反馈的完整闭环。小程序端代码已在 `miniprogram/` 保留，后端已留 `accept`/`checkin` 占位接口，属激活而非从零开发。
