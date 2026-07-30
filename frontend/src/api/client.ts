import type {
  AccessScanResponse,
  BriefingsResponse,
  FloodFrame,
  RoadbookResponse,
  Scenario,
  ScheduleState,
} from '../types'
import { mockFloodFrames, mockScenarios, mockSchedule } from '../mock/data'

/**
 * API 层：后端不在线时自动回退 mock，联调零改动。
 * 后端路由见 backend/app/api/routes.py；scenario 为情景键（功能 C）。
 */

async function tryFetch<T>(url: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return (await res.json()) as T
  } catch {
    return fallback
  }
}

/** 获取情景预设清单（30年一遇 / 2024-06 漓江洪水情景 / 极端情景） */
export function fetchScenarios(): Promise<Scenario[]> {
  return tryFetch<Scenario[]>('/api/scenarios', mockScenarios())
}

/** 获取整体调度态势（名单 + 帮扶者 + 匹配结果，最迟出发按该情景反推） */
export function fetchSchedule(scenario: string): Promise<ScheduleState> {
  return tryFetch<ScheduleState>(
    `/api/schedule?scenario=${encodeURIComponent(scenario)}`,
    mockSchedule(),
  )
}

/** 获取该情景的淹没推演时间序列（24h，帧间隔 60 分钟） */
export function fetchFloodFrames(scenario: string): Promise<FloodFrame[]> {
  return tryFetch<FloodFrame[]>(
    `/api/flood/frames?scenario=${encodeURIComponent(scenario)}`,
    mockFloodFrames(),
  )
}

/** 获取 AI 派单简报（DeepSeek/模板）；后端离线时返回 null，
 * 由 BriefingPanel 用本地模板兜底生成 */
export function fetchBriefings(scenario: string): Promise<BriefingsResponse | null> {
  return tryFetch<BriefingsResponse | null>(
    `/api/briefings?scenario=${encodeURIComponent(scenario)}`,
    null,
  )
}

/** 获取语音路书（第十二节 P1，盲人户入口）；后端离线/无主路线时
 * 返回 null，由 RoadbookPanel 用本地模板兜底生成 */
export function fetchRoadbook(
  scenario: string,
  evacueeId: string,
): Promise<RoadbookResponse | null> {
  return tryFetch<RoadbookResponse | null>(
    `/api/roadbook?scenario=${encodeURIComponent(scenario)}&evacueeId=${encodeURIComponent(evacueeId)}`,
    null,
  )
}

/** 获取街景 AI 无障碍识别（第十五节 CV 半真闭环，Qwen-VL/模板）；
 * 后端离线时返回 null，由 MapView 用本地模板判定兜底 */
export function fetchAccessScan(scenario: string): Promise<AccessScanResponse | null> {
  return tryFetch<AccessScanResponse | null>(
    `/api/access-scan?scenario=${encodeURIComponent(scenario)}`,
    null,
  )
}
