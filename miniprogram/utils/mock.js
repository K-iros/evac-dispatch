/**
 * 骨架阶段演示数据 —— 与 backend/app/services/mock_data.py 保持一致。
 * 演示城镇：广西阳朔县城（第十节城镇验证选定）。坐标均为 OSM
 * 真实地物：住址在漓江边低洼老城区（县前街/滨江路/桂花路），
 * 避难所在西侧远离江岸（另有临江低洼的山水园避难点，供功能 D
 * 避难所失效演示）；路线由 Valhalla 实算生成。
 * 时间口径与模拟时钟一致（T0 = 2024-06-19 00:00，见 core/flood.py）。
 */

var SIM_T0_MS = Date.UTC(2024, 5, 19, 0, 0)

/** 模拟时钟：T0 + minute 分钟的 ISO 时刻（无时区后缀） */
function simClock(minute) {
  return new Date(SIM_T0_MS + minute * 60000).toISOString().replace('Z', '')
}

function mockSchedule() {
  return {
    alertLevel: 'ready',
    shelters: [
      {
        id: 'sh-1',
        name: '阳朔公园应急避难点',
        location: { lng: 110.48455, lat: 24.77903 },
        wheelchairAccessible: true,
      },
      {
        id: 'sh-2',
        name: '县实验小学体育馆',
        location: { lng: 110.47673, lat: 24.7752 },
        wheelchairAccessible: false,
      },
      // 临江低洼避难点：急涨段会被淹没/急流超限 → 触发功能 D 自动改派
      // （s2024 情景 +1020min 首次失效，早于 sh-1 的 +1260min）
      {
        id: 'sh-3',
        name: '山水园临江避难点',
        location: { lng: 110.4923, lat: 24.7791 },
        wheelchairAccessible: true,
      },
    ],
    helpers: [
      {
        id: 'h-1',
        name: '王志愿',
        location: { lng: 110.48864, lat: 24.78027 },
        assignedEvacueeIds: ['e-1'],
        available: true,
      },
      {
        id: 'h-2',
        name: '李网格',
        location: { lng: 110.48954, lat: 24.77977 },
        assignedEvacueeIds: ['e-1', 'e-2'],
        available: true,
      },
      {
        id: 'h-3',
        name: '赵帮扶',
        location: { lng: 110.48169, lat: 24.77894 },
        assignedEvacueeIds: [],
        available: false,
      },
    ],
    // latestDeparture：模拟时钟口径的近似值（后端在线时由该情景
    // 水深场沿路径反推，此处为 s2024 急涨段前的合理回退值）
    evacuees: [
      {
        id: 'e-1',
        name: '张奶奶',
        profile: 'wheelchair',
        address: '县前街 12 号 101',
        location: { lng: 110.4918, lat: 24.7795 },
        latestDeparture: simClock(700), // ≈06-19 11:40，急涨段前
        matchStatus: 'matched',
        helperIds: ['h-1', 'h-2'],
        shelterId: 'sh-1',
      },
      {
        id: 'e-2',
        name: '陈先生',
        profile: 'blind',
        address: '滨江路 88 号 502',
        location: { lng: 110.49275, lat: 24.78125 },
        latestDeparture: simClock(730), // ≈06-19 12:10
        matchStatus: 'matched',
        helperIds: ['h-2'],
        shelterId: 'sh-3', // 默认派往临江避难点（功能 D 演示）
      },
      {
        id: 'e-3',
        name: '刘爷爷',
        profile: 'elderly',
        address: '桂花路 5 号 301',
        location: { lng: 110.49046, lat: 24.7784 },
        latestDeparture: simClock(750), // ≈06-19 12:30，无路线按住址被淹倒扣
        matchStatus: 'unmatched',
        helperIds: [],
        shelterId: null,
      },
    ],
    // 路线由 Valhalla 实算（帮扶者→住址→避难所三点航线，RDP 简化），
    // 顶点包含帮扶者位置与残障者住址，据此拆分接人段/护送段
    assignments: [
      {
        helperId: 'h-1',
        evacueeId: 'e-1',
        shelterId: 'sh-1',
        arriveBy: simClock(690),
        isBackup: false,
        route: [
          [110.48864, 24.78027],
          [110.4892, 24.77935],
          [110.48998, 24.77933],
          [110.4904, 24.779],
          [110.49094, 24.77953],
          [110.4918, 24.7795],
          [110.49094, 24.77953],
          [110.49019, 24.77884],
          [110.48894, 24.77846],
          [110.48838, 24.77888],
          [110.48684, 24.77752],
          [110.48677, 24.7779],
          [110.48656, 24.77793],
          [110.48636, 24.7783],
          [110.48488, 24.77881],
          [110.48462, 24.77906],
        ],
      },
      {
        helperId: 'h-2',
        evacueeId: 'e-1',
        shelterId: 'sh-1',
        arriveBy: simClock(695),
        isBackup: true,
        route: [
          [110.48954, 24.77977],
          [110.49022, 24.78021],
          [110.4919, 24.78016],
          [110.4918, 24.7795],
          [110.49094, 24.77953],
          [110.49019, 24.77884],
          [110.48894, 24.77846],
          [110.48838, 24.77888],
          [110.48684, 24.77752],
          [110.48677, 24.7779],
          [110.48656, 24.77793],
          [110.48636, 24.7783],
          [110.48488, 24.77881],
          [110.48462, 24.77906],
        ],
      },
      {
        helperId: 'h-2',
        evacueeId: 'e-2',
        shelterId: 'sh-3',
        arriveBy: simClock(720),
        isBackup: false,
        route: [
          [110.48954, 24.77977],
          [110.49022, 24.78021],
          [110.49251, 24.78015],
          [110.49275, 24.78125],
          [110.49289, 24.7811],
          [110.49276, 24.78023],
          [110.49295, 24.77955],
          [110.4923, 24.7791],
        ],
      },
      // 功能 D：sh-3 被淹/急流超限时自动升级此改派候选为主路线
      {
        helperId: 'h-2',
        evacueeId: 'e-2',
        shelterId: 'sh-1',
        arriveBy: simClock(715),
        isBackup: false,
        isFallback: true,
        route: [
          [110.48954, 24.77977],
          [110.49022, 24.78021],
          [110.49251, 24.78015],
          [110.49275, 24.78125],
          [110.49251, 24.78015],
          [110.49007, 24.78015],
          [110.48912, 24.77949],
          [110.48684, 24.77752],
          [110.48677, 24.7779],
          [110.48656, 24.77793],
          [110.48636, 24.7783],
          [110.48488, 24.77881],
          [110.48462, 24.77906],
        ],
      },
    ],
  }
}

/* ---------- 淹没推演回退帧 ---------- */

// 与 backend/app/core/flood.py 一致的口径：s2024 分段过程线 + 水位换算
var HYDROGRAPH = [
  [0, 0],
  [720, 1.0],
  [1200, 5.0],
  [1440, 5.5],
]
var BASE_STAGE = 105.5
var WARN_STAGE = 109.5
var TOTAL_MIN = 1440
var FRAME_STEP_MIN = 60

function waterLevelAt(minute) {
  for (var i = 0; i < HYDROGRAPH.length - 1; i++) {
    var x0 = HYDROGRAPH[i][0]
    var y0 = HYDROGRAPH[i][1]
    var x1 = HYDROGRAPH[i + 1][0]
    var y1 = HYDROGRAPH[i + 1][1]
    if (minute <= x1) return y0 + ((y1 - y0) * (Math.max(minute, x0) - x0)) / (x1 - x0)
  }
  return HYDROGRAPH[HYDROGRAPH.length - 1][1]
}

/** 淹没推演回退帧 —— 与 backend/app/core/flood.py 回退帧同构
 * （后端在线时返回 landlab OverlandFlow 预计算帧，每帧含水深分档面
 * minDepth ∈ {0.05..2.00} 与 v·d 分档面 minVd ∈ {0.25..0.50}，
 * 另带 stageM/warnM/clock，此处 mock 同格式） */
function mockFloodFrames() {
  var frames = []
  // 占位进水点：漓江河道，漫溢后逐步侵入西岸老城区（先淹滨江路一带）
  var cx = 110.4962
  var cy = 24.7802
  var peak = HYDROGRAPH[HYDROGRAPH.length - 1][1]
  // 浅→深嵌套：深度分档 + 中心 v·d 急流危险面
  var levels = [
    ['minDepth', 0.05, 1],
    ['minDepth', 0.15, 0.7],
    ['minDepth', 0.3, 0.45],
    ['minVd', 0.25, 0.3],
    ['minVd', 0.5, 0.18],
  ]
  for (var minute = 0; minute <= TOTAL_MIN; minute += FRAME_STEP_MIN) {
    var rise = waterLevelAt(minute)
    var r = 0.001 + (rise / peak) * 0.008
    var stage = BASE_STAGE + rise
    frames.push({
      minute: minute,
      waterLevel: Math.round(rise * 100) / 100,
      stageM: Math.round(stage * 100) / 100,
      warnM: Math.round((stage - WARN_STAGE) * 100) / 100,
      clock: simClock(minute),
      geojson: {
        type: 'FeatureCollection',
        features: levels.map(function (lv) {
          var props = {}
          props[lv[0]] = lv[1]
          var rr = r * lv[2]
          return {
            type: 'Feature',
            properties: props,
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

module.exports = { mockSchedule, mockFloodFrames, simClock, SIM_T0_MS: SIM_T0_MS }
