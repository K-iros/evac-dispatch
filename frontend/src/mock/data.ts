import type { AccessScanResponse, FloodFrame, Scenario, ScheduleState } from '../types'
import scheduleDataset from './scheduleDataset.json'

/**
 * 后端离线时的回退演示数据 —— 与 backend/data/yangshuo_schedule.json 同源。
 * 演示城镇：广西阳朔县城（第十节城镇验证选定）。第十二节 P0
 * 「扩充数据规模」：24 户 / 10 帮扶者 / 4 避难所，坐标均为 OSM
 * 真实地物（低洼老城区滨江路/县前街/桂花路/西街 + 西侧高地对照组），
 * 路线由 Valhalla 实算。数据集由 scripts/gen_scale_dataset.py 生成：
 * scheduleDataset.json 即后端 build_mock_schedule('s2024') 的完整序列化
 * （latestDeparture/arriveBy 已按 s2024 水深场反推），离线回退与
 * 在线返回逐字段一致。
 * 时间口径与模拟时钟一致（T0 = 2024-06-19 00:00，见 core/flood.py）。
 */

/** 模拟时钟：T0 + minute 分钟的 ISO 时刻 */
function simClock(minute: number): string {
  return new Date(Date.UTC(2024, 5, 19, 0, 0) + minute * 60_000)
    .toISOString()
    .replace('Z', '')
}

/** 情景预设回退清单（与 backend/app/core/flood.py SCENARIOS 一致） */
export function mockScenarios(): Scenario[] {
  return [
    { key: 's30', name: '30年一遇', isDefault: false },
    { key: 's2024', name: '2024-06 漓江洪水情景', isDefault: true },
    { key: 'extreme', name: '极端情景', isDefault: false },
  ]
}

export function mockSchedule(): ScheduleState {
  // JSON 导入的字面量类型宽化为 string/number[][]，此处收窄为领域类型
  return scheduleDataset as unknown as ScheduleState
}

/** 街景 AI 识别本地兜底（第十五节）：与后端 cv_access.TEMPLATE_VERDICTS
 * 同一文案口径，后端离线时演示不会空白 */
const SCAN_VERDICTS: Record<string, string> = {
  'e-8': '存在障碍：巷口连续石阶约 5 级，无坡道，轮椅不可通行',
  'e-14': '存在障碍：路缘陡坎高约 20cm 且路面破损，轮椅不可通行',
  'e-19': '存在障碍：临街台阶带残缺护栏，无缘石坡道，轮椅不可通行',
}

export function mockAccessScan(caseIds: string[]): AccessScanResponse {
  return {
    source: 'template',
    items: caseIds.map((id) => ({
      evacueeId: id,
      image: `/streetview/${id}.png`,
      verdict: SCAN_VERDICTS[id] ?? '存在障碍：识别到台阶/陡坎，轮椅不可通行',
      barrierDetected: true,
    })),
  }
}

/* ---------- 淹没推演回退帧 ---------- */

// 与 backend/app/core/flood.py 一致的口径：s2024 分段过程线 + 水位换算
const HYDROGRAPH: [number, number][] = [
  [0, 0],
  [720, 1.0],
  [1200, 5.0],
  [1440, 5.5],
]
const BASE_STAGE = 105.5
const WARN_STAGE = 109.5
const TOTAL_MIN = 1440
const FRAME_STEP_MIN = 60

function waterLevelAt(minute: number): number {
  for (let i = 0; i < HYDROGRAPH.length - 1; i++) {
    const [x0, y0] = HYDROGRAPH[i]
    const [x1, y1] = HYDROGRAPH[i + 1]
    if (minute <= x1) return y0 + ((y1 - y0) * (Math.max(minute, x0) - x0)) / (x1 - x0)
  }
  return HYDROGRAPH[HYDROGRAPH.length - 1][1]
}

/** 淹没推演回退帧 —— 与 backend/app/core/flood.py 回退帧同构
 * （后端在线时返回 landlab OverlandFlow 预计算帧，每帧含水深分档面
 * minDepth ∈ {0.05..2.00} 与 v·d 分档面 minVd ∈ {0.25..0.50}，
 * 另带 stageM/warnM/clock，此处 mock 同格式） */
export function mockFloodFrames(): FloodFrame[] {
  const frames: FloodFrame[] = []
  // 占位进水点：漓江河道，漫溢后逐步侵入西岸老城区（先淹滨江路一带）
  const cx = 110.4962
  const cy = 24.7802
  const peak = HYDROGRAPH[HYDROGRAPH.length - 1][1]
  // 浅→深嵌套：深度分档 + 中心 v·d 急流危险面
  const levels: ['minDepth' | 'minVd', number, number][] = [
    ['minDepth', 0.05, 1],
    ['minDepth', 0.15, 0.7],
    ['minDepth', 0.3, 0.45],
    ['minVd', 0.25, 0.3],
    ['minVd', 0.5, 0.18],
  ]
  for (let minute = 0; minute <= TOTAL_MIN; minute += FRAME_STEP_MIN) {
    const rise = waterLevelAt(minute)
    const r = 0.001 + (rise / peak) * 0.008
    const stage = BASE_STAGE + rise
    frames.push({
      minute,
      waterLevel: Math.round(rise * 100) / 100,
      stageM: Math.round(stage * 100) / 100,
      warnM: Math.round((stage - WARN_STAGE) * 100) / 100,
      clock: simClock(minute),
      geojson: {
        type: 'FeatureCollection',
        features: levels.map(([prop, value, scale]) => {
          const rr = r * scale
          return {
            type: 'Feature',
            properties: { [prop]: value },
            geometry: {
              type: 'Polygon',
              coordinates: [
                [
                  [cx - rr, cy - rr],
                  [cx + rr, cy - rr],
                  [cx + rr, cy + rr],
                  [cx - rr, cy + rr],
                  [cx - rr, cy - rr],
                ],
              ],
            },
          }
        }),
      },
    })
  }
  return frames
}
