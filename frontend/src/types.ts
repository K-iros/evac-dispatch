import type { FeatureCollection } from 'geojson'

/** 领域类型定义 —— 与后端 schemas 保持字段对齐 */

/** 残障画像：轮椅 / 盲人 / 老人（画像可插拔） */
export type Profile = 'wheelchair' | 'blind' | 'elderly'

/** 匹配状态 */
export type MatchStatus =
  | 'unmatched' // 无帮扶者
  | 'matched' // 已匹配（含备份）
  | 'en_route' // 帮扶者在途（接人）
  | 'escorting' // 护送中（第十三节第 4 项：时间驱动四态）
  | 'arrived' // 已到场
  | 'evacuated' // 已撤离

/** 响应级别：分级响应，防"狼来了" */
export type AlertLevel = 'standby' | 'ready' | 'dispatch'

export interface LngLat {
  lng: number
  lat: number
}

/** 待撤离人员（残障/弱势人群） */
export interface Evacuee {
  id: string
  name: string
  profile: Profile
  address: string
  location: LngLat
  /** 最迟出发时间（ISO 8601），核心计算产物 */
  latestDeparture: string
  matchStatus: MatchStatus
  /** 匹配的帮扶者 id（首选 + 备份，冗余匹配） */
  helperIds: string[]
  /** 目标避难所 id */
  shelterId: string | null
}

/** 帮扶者（志愿者/网格员） */
export interface Helper {
  id: string
  name: string
  location: LngLat
  assignedEvacueeIds: string[]
  available: boolean
  /** 超时失联（补位模拟中被标记，前端演练态） */
  lost?: boolean
}

/** 避难所 */
export interface Shelter {
  id: string
  name: string
  location: LngLat
  wheelchairAccessible: boolean
  /** 容量上限（第十三节第 5 项：容量透出，sh-3 满员叙事） */
  capacity?: number | null
  /** 已分配主派人数（离线管线回写） */
  occupancy?: number | null
  /** 失效后仍可垂直避险（校舍类上楼，第 7 项）：黄色降级而非红叉 */
  verticalRefuge?: boolean
}

/** 避难所整所转移路线（第 8-2 项：失效所 → 高地兜底所） */
export interface ShelterTransfer {
  fromShelterId: string
  toShelterId: string
  route: [number, number][]
}

/** 第 8-2 项派生：当前时刻需执行的整所转移（App 派生，MapView 渲染） */
export interface ActiveTransfer extends ShelterTransfer {
  /** 已入住待转移人数 */
  count: number
  /** 转移路线当前是否仍可行（按所内最弱画像阈值判危险面） */
  feasible: boolean
}

/** 一条调度任务：帮扶者 → 残障者家 → 避难所 */
export interface Assignment {
  helperId: string
  evacueeId: string
  shelterId: string
  arriveBy: string
  isBackup: boolean
  /** 串行链次序（P1 真实匹配算法）：≥2 即"一人串行接多户"，
   * 路线起点为前一单的避难所（送达后再出发接下一户） */
  sequence?: number
  /** 避难所失效时的改派候选路线（功能 D，平时不显示） */
  isFallback?: boolean
  /** 由备份升级而来（补位模拟产物，驱动切换动画与标注） */
  promoted?: boolean
  /** 由避难所失效自动改派而来（功能 D 派生产物） */
  rerouted?: boolean
  /** 路线坐标（GeoJSON LineString coordinates） */
  route: [number, number][]
  /** 普通步行对照路线（无障碍对比开关，仅对比案例户有值） */
  footRoute?: [number, number][] | null
  /** 路线反推的帮扶者最迟出发时刻（ISO，第 6 项 a） */
  departBy?: string | null
  /** 串行链最早可行开始时刻（ISO，前序任务 T0 即刻执行的最早完成） */
  earliestStart?: string | null
  /** 最迟出发 < 最早可行开始 → 不可行排班（红色冲突告警） */
  conflict?: boolean
  /** 最迟出发时间倒推链（第十五节）：后端逐段中间量透出，
   * 点击名单最迟出发时间展开白箱推导 */
  deriveSteps?: DeriveStep[]
  /** 前端派生：出动档时间驱动状态机的任务时间轴（第 4 项） */
  timeline?: AssignmentTimeline
}

/** 最迟出发时间倒推链的单步中间量（第十五节：可解释性透出）。
 * 倒推序（[0] 为路径末段）：latest = min(latest, failMinute) − durationMin */
export interface DeriveStep {
  segIndex: number
  phase: 'pickup' | 'escort'
  /** 该段失效时刻（模拟分钟）；null = 全程可通行 */
  failMinute: number | null
  durationMin: number
  /** 递推后 latest（可为负，负值即无可行时间窗） */
  latestAfter: number
  /** 该段失效时刻是否实际收紧了 latest */
  clamped: boolean
}

/** 任务时间轴（模拟分钟）：待命→在途(接人)→护送中→已撤离的阶段边界 */
export interface AssignmentTimeline {
  /** 帮扶者出发时刻 */
  startMin: number
  /** 接到人（接人段结束）时刻 */
  pickupEndMin: number
  /** 送达避难所时刻 */
  arriveMin: number
}

/** 无障碍对比案例（第十二节 P0）：轮椅绕行 vs 普通步行同屏双线。
 * 障碍点叙事：CV 街景识别台阶→注入标签→路径改变（创新①闭环的注入端） */
export interface AccessCase {
  evacueeId: string
  barrier: {
    location: LngLat
    label: string
  }
  wheelchairKm: number
  footKm: number
  /** 绕行倍率 = wheelchairKm / footKm */
  detourRatio: number
}

/** 某一时刻的淹没图层（landlab OverlandFlow 离线推演帧）
 * geojson feature 属性：minDepth（水深分档，A 渐变着色 + 失效判定）
 * 或 minVd（v·d 失稳分档，B 危险度判据），两类面共存 */
export interface FloodFrame {
  minute: number
  waterLevel: number
  /** 阳朔站绝对水位（米，模型修正一的口径） */
  stageM?: number
  /** 超警幅度（米，警戒水位 109.5m） */
  warnM?: number
  /** 模拟时钟 ISO 时刻（T0 = 2024-06-19 00:00） */
  clock?: string
  geojson: FeatureCollection
}

/** 情景预设（功能 C）：后端 /api/scenarios */
export interface Scenario {
  key: string
  name: string
  isDefault: boolean
}

/** 整体调度态势 */
export interface ScheduleState {
  alertLevel: AlertLevel
  evacuees: Evacuee[]
  helpers: Helper[]
  shelters: Shelter[]
  assignments: Assignment[]
  /** 无障碍对比案例（对比开关数据源，无案例时为空/缺省） */
  accessCases?: AccessCase[]
  /** 避难所整所转移路线（第 8-2 项，离线预算） */
  shelterTransfers?: ShelterTransfer[]
}

/** LLM 派单简报（第十二节 P0）：每位帮扶者一张任务卡 */
export interface Briefing {
  helperId: string
  helperName: string
  text: string
}

/** /api/briefings 响应：source 区分 LLM 实时生成 / 规则模板兜底 */
export interface BriefingsResponse {
  source: 'llm' | 'template'
  items: Briefing[]
}

/** LLM 语音路书（第十二节 P1）：盲人画像路径 → 自然语言 → TTS 播报 */
export interface RoadbookResponse {
  evacueeId: string
  evacueeName: string
  helperName: string | null
  shelterName: string | null
  source: 'llm' | 'template'
  /** 可直接朗读的整段路书（约 30 秒） */
  text: string
  /** 结构化转向步骤（面板逐条展示） */
  steps: string[]
  distanceKm: number
  durationMin: number
}

/** 单张街景的 CV 障碍识别结果（第十五节：CV 补标签半真闭环）。
 * 预选街景图 + 多模态判定，障碍点坐标人工预绑定于 accessCases */
export interface AccessScanItem {
  evacueeId: string
  /** 街景图 URL（/streetview/{id}.png，Vite 静态服务） */
  image: string
  /** AI 判定文本 */
  verdict: string
  barrierDetected: boolean
}

/** /api/access-scan 响应：Qwen-VL 实时识别 / 模板兜底 */
export interface AccessScanResponse {
  source: 'llm' | 'template'
  items: AccessScanItem[]
}
