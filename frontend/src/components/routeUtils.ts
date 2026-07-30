import type { FeatureCollection, Polygon, Position } from 'geojson'
import type {
  Assignment,
  AssignmentTimeline,
  Evacuee,
  FloodFrame,
  Profile,
  ScheduleState,
} from '../types'

/**
 * 路径工具：接人段/护送段拆分、测距、与当前时刻淹没图层求交。
 * 淹没帧由 landlab OverlandFlow 离线推演导出（24h，帧间隔 60 分钟），
 * 每帧含两类分档面：
 * - minDepth ∈ {0.05, 0.15, 0.30, 0.60, 1.20, 2.00}：水深渐变着色 +
 *   画像水深阈值失效（轮椅 ≥0.15m、盲人/老人 ≥0.30m）
 * - minVd ∈ {0.25, 0.40, 0.50}：v·d 行人失稳危险度（功能 B，
 *   轮椅 ≥0.25、老人 ≥0.40、健康成人/盲人引导 ≥0.50 m²/s 失稳）
 * 路段失效 = 水深超阈 或 v·d 超限，与 backend/app/core/routing.py 的
 * DEPTH_THRESHOLD_M / VD_THRESHOLD_M2_S 对齐。
 */

const EARTH_R = 6_371_000

/** 画像化水深失效阈值（米）：与后端 routing.DEPTH_THRESHOLD_M 一致 */
export const DEPTH_THRESHOLD: Record<Profile, number> = {
  wheelchair: 0.15, // 轮椅：浅水即失效（轮毂浸水/驱动打滑）
  blind: 0.3, // 盲人：步行淤水上限
  elderly: 0.3, // 老人：步行淤水上限
}

/** 画像化 v·d 失稳阈值（m²/s）：与后端 routing.VD_THRESHOLD_M2_S 一致。
 * 行人失稳经验判据 v×d ≈ 0.5 m²/s，轮椅/老人更严 */
export const VD_THRESHOLD: Record<Profile, number> = {
  wheelchair: 0.25, // 轮椅：浅流即可推偻/漂移
  blind: 0.5, // 盲人：成人悺臂引导，按成人失稳限
  elderly: 0.4, // 老人：站立稳定性差
}

/** 危险阈值对：水深 + v·d（避难所失效校验等非画像场景用成人口径） */
export interface HazardThreshold {
  depth: number
  vd: number
}

/** 画像 → 危险阈值对 */
export function hazardOf(profile: Profile): HazardThreshold {
  return { depth: DEPTH_THRESHOLD[profile], vd: VD_THRESHOLD[profile] }
}

/** 避难所失效判据（功能 D）：场地被淹 ≥0.3m 或急流 v·d ≥0.5 */
export const SHELTER_HAZARD: HazardThreshold = { depth: 0.3, vd: 0.5 }

/** 球面距离（米） */
export function haversine(a: [number, number], b: [number, number]): number {
  const rad = Math.PI / 180
  const dLat = (b[1] - a[1]) * rad
  const dLng = (b[0] - a[0]) * rad
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_R * Math.asin(Math.sqrt(s))
}

/** 射线法：点是否在环内 */
function pointInRing(pt: [number, number], ring: Position[]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if (yi > pt[1] !== yj > pt[1] && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

/** 外环 bbox 缓存（扩容后的热路径预筛：推演帧多边形顶点数大，
 * 先用 4 次比较排除再做射线法；帧 feature 对象跨渲染稳定，WeakMap 免手动失效） */
const bboxCache = new WeakMap<object, [number, number, number, number]>()

function outerRingBbox(feature: object, ring: Position[]): [number, number, number, number] {
  let bb = bboxCache.get(feature)
  if (!bb) {
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    for (const [x, y] of ring) {
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
    bb = [minX, minY, maxX, maxY]
    bboxCache.set(feature, bb)
  }
  return bb
}

/** 点是否落在当前帧任一危险面内（外环命中且不在孔洞中）。
 * 危险面 = 水深面 minDepth ≥ 阈值 或 v·d 面 minVd ≥ 阈值；
 * 无两类属性的面（旧格式）对所有画像都视为阻断 */
export function pointInFlood(
  pt: [number, number],
  flood: FeatureCollection | null,
  thr: HazardThreshold,
): boolean {
  if (!flood) return false
  for (const f of flood.features) {
    if (f.geometry.type !== 'Polygon') continue
    const props = f.properties as { minDepth?: number; minVd?: number } | null
    const depth = props?.minDepth
    const vd = props?.minVd
    const hazardous =
      depth !== undefined || vd !== undefined
        ? (depth !== undefined && depth >= thr.depth) || (vd !== undefined && vd >= thr.vd)
        : true // 旧格式兼容：无分档属性视为阻断
    if (!hazardous) continue
    const rings = (f.geometry as Polygon).coordinates
    if (rings.length === 0) continue
    const [minX, minY, maxX, maxY] = outerRingBbox(f, rings[0])
    if (pt[0] < minX || pt[0] > maxX || pt[1] < minY || pt[1] > maxY) continue
    if (!pointInRing(pt, rings[0])) continue
    if (rings.slice(1).some((hole) => pointInRing(pt, hole))) continue
    return true
  }
  return false
}

export type SegmentKind = 'pickup' | 'escort'

/** 路段状态：畅通 / 下一推演帧（+60 分钟）将失效 / 已淹没 */
export type SegmentStatus = 'ok' | 'warning' | 'flooded'

export interface RouteSegment {
  kind: SegmentKind
  coords: [[number, number], [number, number]]
  /** 当前推演时刻该小段是否受淹（中点或端点落入危险面） */
  flooded: boolean
  status: SegmentStatus
  lengthM: number
}

/** 小段是否失效：端点或中点落入危险面（水深超阈 或 v·d 超限） */
function segFlooded(
  a: [number, number],
  b: [number, number],
  flood: FeatureCollection | null,
  thr: HazardThreshold,
): boolean {
  if (!flood) return false
  const mid: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
  return (
    pointInFlood(a, flood, thr) ||
    pointInFlood(mid, flood, thr) ||
    pointInFlood(b, flood, thr)
  )
}

/** 小段三态状态：当前帧失效=红；下一帧（+60 分钟）失效=黄；否则绿 */
export function segmentStatus(
  a: [number, number],
  b: [number, number],
  frame: FloodFrame | null,
  nextFrame: FloodFrame | null,
  thr: HazardThreshold,
): SegmentStatus {
  if (segFlooded(a, b, frame?.geojson ?? null, thr)) return 'flooded'
  if (segFlooded(a, b, nextFrame?.geojson ?? null, thr)) return 'warning'
  return 'ok'
}

/** 整条路线 → 带状态小段（全局路段失效着色用，不区分接人/护送） */
export function statusSegments(
  route: [number, number][],
  frame: FloodFrame | null,
  nextFrame: FloodFrame | null,
  thr: HazardThreshold,
): { coords: [[number, number], [number, number]]; status: SegmentStatus }[] {
  const out: { coords: [[number, number], [number, number]]; status: SegmentStatus }[] = []
  for (let i = 0; i < route.length - 1; i++) {
    out.push({
      coords: [route[i], route[i + 1]],
      status: segmentStatus(route[i], route[i + 1], frame, nextFrame, thr),
    })
  }
  return out
}

/** 以离残障者家最近的路径顶点为界，拆分接人段 / 护送段 */
export function splitIndexAt(route: [number, number][], home: [number, number]): number {
  let best = 0
  let bestD = Infinity
  route.forEach((p, i) => {
    const d = haversine(p, home)
    if (d < bestD) {
      bestD = d
      best = i
    }
  })
  return best
}

/** 路线 → 逐小段（含失效/预警标记），供分色渲染与统计 */
export function buildSegments(
  route: [number, number][],
  splitIdx: number,
  frame: FloodFrame | null,
  nextFrame: FloodFrame | null,
  thr: HazardThreshold,
): RouteSegment[] {
  const segments: RouteSegment[] = []
  for (let i = 0; i < route.length - 1; i++) {
    const a = route[i]
    const b = route[i + 1]
    const status = segmentStatus(a, b, frame, nextFrame, thr)
    segments.push({
      kind: i < splitIdx ? 'pickup' : 'escort',
      coords: [a, b],
      flooded: status === 'flooded',
      status,
      lengthM: haversine(a, b),
    })
  }
  return segments
}

/** 护送段步速（米/秒）：帮扶者带着残障者行进，按画像折减 */
export const ESCORT_SPEED: Record<Profile, number> = {
  wheelchair: 0.9, // 推轮椅
  blind: 0.9, // 挽臂引导（0.8-1.0，取中值）
  elderly: 0.7, // 搀扶慢行
}
/** 接人段步速：帮扶者独行 */
const PICKUP_SPEED = 1.4

/* ---------- 时间驱动四态状态机（第十三节第 4 项） ---------- */

/** 模拟时钟 T0（landlab 推演起点，与后端 flood.SIM_T0 一致） */
const SIM_T0_MS = new Date('2024-06-19T00:00:00').getTime()

/** ISO 模拟时刻 → 推演分钟 */
export function simMinute(iso: string): number {
  return (new Date(iso).getTime() - SIM_T0_MS) / 60_000
}

/** 推演分钟 → 模拟时钟标签（HH:MM，跨日加“次日”前缀；
 * 倒推链气泡等展示用，与时间轴 clock 同一坐标系） */
export function simLabel(minute: number): string {
  const d = new Date(SIM_T0_MS + minute * 60_000)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const day = Math.floor(minute / 1440)
  const prefix = day === 0 ? '' : day === 1 ? '次日' : `${day > 0 ? '+' : ''}${day}日`
  return `${prefix}${hh}:${mm}`
}

/** 出动档发令口径：帮扶者比最迟出发时刻提前出发的安全余量（分钟） */
export const SAFETY_MARGIN_MIN = 120

/** 主派任务时间轴：出发 = max(串行链前单实际送达, 最迟出发 − 安全余量)，
 * 接人/护送耗时按步速折算；无 departBy（无可行时间窗）时退化为
 * 最早可行开始即刻出发（尽早抢时间） */
export function buildTimeline(
  assignment: Assignment,
  evacuee: Evacuee,
  prevArriveMin: number,
): AssignmentTimeline {
  const splitIdx = splitIndexAt(assignment.route, [evacuee.location.lng, evacuee.location.lat])
  let pickupM = 0
  let escortM = 0
  for (let i = 0; i < assignment.route.length - 1; i++) {
    const d = haversine(assignment.route[i], assignment.route[i + 1])
    if (i < splitIdx) pickupM += d
    else escortM += d
  }
  const pickupDur = pickupM / PICKUP_SPEED / 60
  const escortDur = escortM / ESCORT_SPEED[evacuee.profile] / 60
  const departBy = assignment.departBy ? simMinute(assignment.departBy) : null
  const earliest = assignment.earliestStart ? simMinute(assignment.earliestStart) : 0
  const startMin = Math.max(
    prevArriveMin,
    earliest,
    departBy !== null ? departBy - SAFETY_MARGIN_MIN : 0,
  )
  return {
    startMin,
    pickupEndMin: startMin + pickupDur,
    arriveMin: startMin + pickupDur + escortDur,
  }
}

/** 沿坐标串按里程占比取插值点（frac ∈ [0,1]） */
function pointAlong(coords: [number, number][], frac: number): [number, number] {
  if (coords.length === 0) return [0, 0]
  if (coords.length === 1 || frac <= 0) return coords[0]
  if (frac >= 1) return coords[coords.length - 1]
  const lens: number[] = []
  let total = 0
  for (let i = 0; i < coords.length - 1; i++) {
    const d = haversine(coords[i], coords[i + 1])
    lens.push(d)
    total += d
  }
  let target = total * frac
  for (let i = 0; i < lens.length; i++) {
    if (target <= lens[i]) {
      const t = lens[i] > 0 ? target / lens[i] : 0
      return [
        coords[i][0] + (coords[i + 1][0] - coords[i][0]) * t,
        coords[i][1] + (coords[i + 1][1] - coords[i][1]) * t,
      ]
    }
    target -= lens[i]
  }
  return coords[coords.length - 1]
}

/** 护送移动小点：当前推演时刻在路线上的插值位置；未出发/已送达返回 null。
 * 第十四节第 3 项：60 分钟帧粒度下多数任务全程 30-70 分钟，任务窗口
 * 可能整体落在本帧与下一帧之间而一帧都不显示 → 此时在本帧就近
 * 夹取到窗口中点，保证小点至少可见一次（与 deriveSchedule 的
 * escorting 夹取口径一致） */
export function movingDotAt(
  assignment: Assignment,
  evacuee: Evacuee,
  nowMin: number,
  nextFrameMin?: number | null,
): { pos: [number, number]; phase: 'pickup' | 'escort' } | null {
  const t = assignment.timeline
  if (!t) return null
  let effNow = nowMin
  if (nowMin >= t.arriveMin) return null
  if (nowMin < t.startMin) {
    if (!clampVisible(t, nowMin, nextFrameMin ?? null)) return null
    effNow = (t.startMin + t.arriveMin) / 2 // 夹取到窗口中点（行进中观感）
  }
  const splitIdx = splitIndexAt(assignment.route, [evacuee.location.lng, evacuee.location.lat])
  if (effNow < t.pickupEndMin) {
    const frac = (effNow - t.startMin) / Math.max(t.pickupEndMin - t.startMin, 1e-6)
    return { pos: pointAlong(assignment.route.slice(0, splitIdx + 1), frac), phase: 'pickup' }
  }
  const frac = (effNow - t.pickupEndMin) / Math.max(t.arriveMin - t.pickupEndMin, 1e-6)
  return { pos: pointAlong(assignment.route.slice(splitIdx), frac), phase: 'escort' }
}

/** 第十四节第 3 项夹取判定：任务窗口 [startMin, arriveMin) 整体落在
 * 本帧与下一帧之间（窗口内无任何帧）时，在本帧补显一次 */
export function clampVisible(
  t: AssignmentTimeline,
  nowMin: number,
  nextFrameMin: number | null,
): boolean {
  return nowMin < t.startMin && nextFrameMin !== null && nextFrameMin >= t.arriveMin
}

/** 画像化路线策略文案（对应 Valhalla costing 映射，见 backend/app/core/routing.py） */
export const ROUTE_STRATEGY: Record<Profile, string> = {
  wheelchair: '轮椅无障碍路线：避开台阶与陡坡，全程坡道可通行',
  blind: '视障引导路线：优先盲道与声控信号灯，避开复杂路口',
  elderly: '慢行路线：优先平缓大路，预留充足搀扶时间',
}

export interface RoutePlan {
  assignment: Assignment
  segments: RouteSegment[]
  pickupM: number
  escortM: number
  pickupMin: number
  escortMin: number
  floodedCount: number
  /** 下一推演帧（+60 分钟）内将失效的段数 */
  warningCount: number
}

/** 汇总选中人员的主路线规划（距离/耗时/失效段数），按其画像阈值判失效 */
export function buildRoutePlan(
  assignment: Assignment,
  evacuee: Evacuee,
  frame: FloodFrame | null,
  nextFrame: FloodFrame | null,
): RoutePlan {
  const splitIdx = splitIndexAt(assignment.route, [evacuee.location.lng, evacuee.location.lat])
  const segments = buildSegments(
    assignment.route,
    splitIdx,
    frame,
    nextFrame,
    hazardOf(evacuee.profile),
  )
  const pickupM = segments.filter((s) => s.kind === 'pickup').reduce((s, x) => s + x.lengthM, 0)
  const escortM = segments.filter((s) => s.kind === 'escort').reduce((s, x) => s + x.lengthM, 0)
  return {
    assignment,
    segments,
    pickupM,
    escortM,
    pickupMin: Math.ceil(pickupM / PICKUP_SPEED / 60),
    escortMin: Math.ceil(escortM / ESCORT_SPEED[evacuee.profile] / 60),
    floodedCount: segments.filter((s) => s.status === 'flooded').length,
    warningCount: segments.filter((s) => s.status === 'warning').length,
  }
}

/* ---------- 无路可走清单（救助优先级） ---------- */

/** 路线失效时刻缓存：帧序列 → 路线坐标数组 → 阈值键 → 分钟。
 * 失效时刻与当前推演帧无关（扫全帧序列），而 buildPriorityList
 * 随派生态每次重建；扩容到 28 条路线 × 25 帧后必须缓存。
 * deriveSchedule 浅拷贝 assignment 时保留 route 数组引用，
 * frames 数组每情景加载一次，两级 WeakMap 均可命中 */
const failMinuteCache = new WeakMap<
  FloodFrame[],
  WeakMap<[number, number][], Map<string, number | null>>
>()

/** 路线在推演序列中的最早失效时刻（分钟，按画像水深+v·d 阈值）；全程可行返回 null */
export function routeFailureMinute(
  route: [number, number][],
  frames: FloodFrame[],
  thr: HazardThreshold,
): number | null {
  let byRoute = failMinuteCache.get(frames)
  if (!byRoute) {
    byRoute = new WeakMap()
    failMinuteCache.set(frames, byRoute)
  }
  let byThr = byRoute.get(route)
  if (!byThr) {
    byThr = new Map()
    byRoute.set(route, byThr)
  }
  const key = `${thr.depth}|${thr.vd}`
  const cached = byThr.get(key)
  if (cached !== undefined) return cached

  let result: number | null = null
  outer: for (const f of frames) {
    for (let i = 0; i < route.length - 1; i++) {
      if (segFlooded(route[i], route[i + 1], f.geojson, thr)) {
        result = f.minute
        break outer
      }
    }
  }
  byThr.set(key, result)
  return result
}

export type PriorityTier = 'P0' | 'P1'

export interface PriorityEntry {
  evacueeId: string
  name: string
  profile: Profile
  address: string
  latestDeparture: string
  tier: PriorityTier
  reason: string
  /** 最优路线的失效时刻（分钟）；P0 无路线时为 null */
  failMinute: number | null
}

/**
 * 筛出“无路可走”人员 → 救助优先级清单（To G 叙事落点）：
 * P0 = 未匹配帮扶者、无任何可派路线；P1 = 所有候选路线（含备份）
 * 在推演窗口内都会被淹没失效。有任一全程可行路线则不入清单。
 */
export function buildPriorityList(
  schedule: ScheduleState,
  frames: FloodFrame[],
): PriorityEntry[] {
  const entries: PriorityEntry[] = []
  for (const ev of schedule.evacuees) {
    const routes = schedule.assignments.filter((a) => a.evacueeId === ev.id)
    const base = {
      evacueeId: ev.id,
      name: ev.name,
      profile: ev.profile,
      address: ev.address,
      latestDeparture: ev.latestDeparture,
    }
    if (routes.length === 0) {
      entries.push({ ...base, tier: 'P0', reason: '未匹配帮扶者，无可派路线', failMinute: null })
      continue
    }
    const failMinutes = routes.map((a) =>
      routeFailureMinute(a.route, frames, hazardOf(ev.profile)),
    )
    if (failMinutes.some((m) => m === null)) continue // 存在全程可行路线
    const best = Math.max(...(failMinutes as number[]))
    entries.push({
      ...base,
      tier: 'P1',
      reason: `全部 ${routes.length} 条候选路线将于推演 +${best} 分钟内失效`,
      failMinute: best,
    })
  }
  // P0 最优先；同级按失效时刻早→晚，再按最迟出发时间
  return entries.sort((a, b) => {
    if (a.tier !== b.tier) return a.tier === 'P0' ? -1 : 1
    if (a.failMinute !== b.failMinute) return (a.failMinute ?? -1) - (b.failMinute ?? -1)
    return new Date(a.latestDeparture).getTime() - new Date(b.latestDeparture).getTime()
  })
}

/** 导出 CSV（带 BOM，Excel 可直接打开中文） */
export function exportPriorityCsv(entries: PriorityEntry[]): void {
  const PROFILE_TEXT: Record<Profile, string> = {
    wheelchair: '轮椅',
    blind: '盲人',
    elderly: '老人',
  }
  const rows = [
    ['优先级', '姓名', '画像', '地址', '最迟出发时间', '原因'],
    ...entries.map((e) => [
      e.tier,
      e.name,
      PROFILE_TEXT[e.profile],
      e.address,
      new Date(e.latestDeparture).toLocaleString('zh-CN'),
      e.reason,
    ]),
  ]
  const csv = '\uFEFF' + rows.map((r) => r.map((c) => `"${c.replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `救助优先级清单_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
