import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Map as MLMap,
  NavigationControl,
  Popup,
  setWorkerUrl,
  type GeoJSONSource,
  type StyleSpecification,
} from 'maplibre-gl'
// rolldown-vite 不会把 maplibre 通过 import.meta.url 相对定位的 worker 拷进产物
// （dev 预构建与生产构建同病），worker 404 会导致 load 事件永不触发、
// 所有 GeoJSON 图层（人物/路线/淹没区）整体不渲染；这里用 ?worker&url
// 让 Vite 显式打包 worker（含其 shared 依赖）并注入真实产物地址
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { FeatureCollection } from 'geojson'
import type { AccessScanResponse, ActiveTransfer, Evacuee, FloodFrame, Profile, ScheduleState } from '../types'
import { fetchAccessScan } from '../api/client'
import { mockAccessScan } from '../mock/data'
import { loadAvatarIcons, loadMapIcons } from './mapIcons'
import RoadbookPanel from './RoadbookPanel'
import { buildRoutePlan, haversine, hazardOf, movingDotAt, ROUTE_STRATEGY, statusSegments, type HazardThreshold, type RoutePlan } from './routeUtils'

/** 演示城镇：广西阳朔县城（见 mock/data.ts，老城区—阳朔公园一带） */
const INITIAL_CENTER: [number, number] = [110.489, 24.779]
const INITIAL_ZOOM = 15.2

setWorkerUrl(maplibreWorkerUrl)

/**
 * 双底图：OSM 街道 + Esri 卫星影像（免费瓦片，非实时影像；
 * "实时情况"由叠加其上的淹没推演图层与路径受淹检测承担）
 */
const MAP_STYLE: StyleSpecification = {
  version: 8,
  // 文字标注字形（含中文）：自托管于 public/fonts/，避免外部字形源不可达
  // 导致带 text-field 的 symbol 图层（人物/避难所图标+姓名）整层不渲染
  glyphs: '/fonts/{fontstack}/{range}.pbf',
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
    },
    satellite: {
      type: 'raster',
      tiles: [
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      ],
      tileSize: 256,
      attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
    },
  },
  layers: [
    { id: 'osm', type: 'raster', source: 'osm' },
    { id: 'satellite', type: 'raster', source: 'satellite', layout: { visibility: 'none' } },
  ],
}

const EMPTY_FC: FeatureCollection = { type: 'FeatureCollection', features: [] }
const TEXT_FONT = ['Klokantech Noto Sans CJK Regular']

const PROFILE_LABEL: Record<Profile, string> = {
  wheelchair: '♿ 轮椅',
  blind: '🦯 盲人',
  elderly: '🧓 老人',
}

type Basemap = 'streets' | 'satellite'

/* ---------- 第 2 项：重合标记地理偏移 ---------- */

const OVERLAP_M = 15 // 重合判定距离（米）
const OFFSET_M = 22 // 偏移半径（米）

/** 米 → 经纬度增量 */
function metersToDelta(lat: number, dxM: number, dyM: number): [number, number] {
  return [dxM / (111_320 * Math.cos((lat * Math.PI) / 180)), dyM / 111_320]
}

/** 待撤离者展示位置：<15m 聚簇成员绕簇心均匀散开；与帮扶者
 * 单点重合则向东北偏移；返回偏移后位置（未偏移者不入表） */
function displayPositions(
  evs: Evacuee[],
  helperPts: [number, number][],
): Map<string, [number, number]> {
  const out = new Map<string, [number, number]>()
  const pts = evs.map((e) => [e.location.lng, e.location.lat] as [number, number])
  // 并查集聚簇：两两距离 <15m 归为一簇
  const parent = evs.map((_, i) => i)
  const find = (i: number): number => (parent[i] === i ? i : (parent[i] = find(parent[i])))
  for (let i = 0; i < evs.length; i++) {
    for (let j = i + 1; j < evs.length; j++) {
      if (haversine(pts[i], pts[j]) < OVERLAP_M) parent[find(i)] = find(j)
    }
  }
  const groups = new Map<number, number[]>()
  evs.forEach((_, i) => {
    const r = find(i)
    groups.set(r, [...(groups.get(r) ?? []), i])
  })
  for (const members of groups.values()) {
    if (members.length > 1) {
      // 簇心周围均匀散开
      const cx = members.reduce((s, i) => s + pts[i][0], 0) / members.length
      const cy = members.reduce((s, i) => s + pts[i][1], 0) / members.length
      members.forEach((i, k) => {
        const ang = (2 * Math.PI * k) / members.length
        const [dx, dy] = metersToDelta(cy, Math.cos(ang) * OFFSET_M, Math.sin(ang) * OFFSET_M)
        out.set(evs[i].id, [cx + dx, cy + dy])
      })
    } else {
      // 单点：与帮扶者重合时向东北偏移
      const i = members[0]
      if (helperPts.some((h) => haversine(h, pts[i]) < OVERLAP_M)) {
        const [dx, dy] = metersToDelta(pts[i][1], OFFSET_M * 0.7, OFFSET_M * 0.7)
        out.set(evs[i].id, [pts[i][0] + dx, pts[i][1] + dy])
      }
    }
  }
  return out
}

interface Props {
  schedule: ScheduleState | null
  frame: FloodFrame | null
  /** 下一推演帧（+60 分钟），驱动“即将失效”黄色预警着色 */
  nextFrame: FloodFrame | null
  /** 当前推演时刻已失效的避难所 id（功能 D，App 派生） */
  failedShelterIds: string[]
  selectedEvacueeId: string | null
  onSelectEvacuee: (id: string) => void
  /** 补位演练：标记某帮扶者超时失联 */
  onSimulateLost: (helperId: string) => void
  /** 演练触发时间戳，驱动连线切换动画 */
  drillStamp: number
  /** 当前情景键（语音路书按情景生成，P1） */
  scenario: string
  /** 第 8-2 项：当前时刻需执行的整所转移（App 派生） */
  activeTransfers: ActiveTransfer[]
}

/** 右侧地图：人物/避难所图标 + 高亮路径规划 + 时变淹没图层 + 卫星底图 */
export default function MapView({
  schedule,
  frame,
  nextFrame,
  failedShelterIds,
  selectedEvacueeId,
  onSelectEvacuee,
  onSimulateLost,
  drillStamp,
  scenario,
  activeTransfers,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MLMap | null>(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [basemap, setBasemap] = useState<Basemap>('streets')
  // 无障碍对比开关：同屏双线（轮椅绕行 × 普通步行）+ 障碍标记
  const [accessCompare, setAccessCompare] = useState(false)
  // 街景 AI 识别演示（第十五节 CV 半真闭环）：照片 → 多模态判定 → 绕行已生效
  const [scanState, setScanState] = useState<'idle' | 'scanning' | 'done'>('idle')
  const [scanResult, setScanResult] = useState<AccessScanResponse | null>(null)
  // 语音路书面板（P1，盲人户入口）
  const [roadbookOpen, setRoadbookOpen] = useState(false)
  // 避免 map click 闭包引用过期的回调
  const onSelectRef = useRef(onSelectEvacuee)
  onSelectRef.current = onSelectEvacuee

  // 换户后收起路书面板（避免播报对象错位）
  useEffect(() => {
    setRoadbookOpen(false)
  }, [selectedEvacueeId])

  const selectedEvacuee = useMemo(
    () => schedule?.evacuees.find((e) => e.id === selectedEvacueeId) ?? null,
    [schedule, selectedEvacueeId],
  )
  /** 无障碍对比案例（后端预置，轮椅户双路线分化） */
  const accessCases = schedule?.accessCases ?? []

  /** 街景 AI 识别：后端 Qwen-VL/模板优先，离线时本地模板兜底；
   * 最短 1.2s 识别动画让“照片 → AI 判定”的叙事节奏可感知 */
  const runScan = () => {
    setScanState('scanning')
    const started = Date.now()
    fetchAccessScan(scenario).then((res) => {
      const result = res ?? mockAccessScan(accessCases.map((c) => c.evacueeId))
      window.setTimeout(
        () => {
          setScanResult(result)
          setScanState('done')
        },
        Math.max(0, 1200 - (Date.now() - started)),
      )
    })
  }

  /** 选中人员的主路线规划（接人段/护送段/失效检测），随推演时刻实时更新；
   * 未升级的改派候选（isFallback）不参与 */
  const routePlan: RoutePlan | null = useMemo(() => {
    if (!schedule || !selectedEvacuee) return null
    const primary = schedule.assignments.find(
      (a) => a.evacueeId === selectedEvacuee.id && !a.isBackup && !a.isFallback,
    )
    if (!primary) return null
    return buildRoutePlan(primary, selectedEvacuee, frame, nextFrame)
  }, [schedule, selectedEvacuee, frame, nextFrame])

  // 初始化地图与图层（一次性）
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new MLMap({
      container: containerRef.current,
      style: MAP_STYLE,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
    })
    map.addControl(new NavigationControl(), 'top-right')

    map.on('load', () => {
      void (async () => {
        await loadMapIcons(map)
        // 第 1 项：剧情户虚拟头像（缺文件时静默回退画像 pin）
        await loadAvatarIcons(map)

        // 淹没图层：landlab 推演帧按水深六档渐变着色（功能 A）
        // 0.05m 浅蓝 → 2.00m+ 深蓝，仅渲染 minDepth 分档面
        map.addSource('flood', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'flood-fill',
          type: 'fill',
          source: 'flood',
          filter: ['has', 'minDepth'],
          paint: {
            'fill-color': [
              'step',
              ['get', 'minDepth'],
              '#bfdbfe',
              0.15,
              '#93c5fd',
              0.3,
              '#60a5fa',
              0.6,
              '#3b82f6',
              1.2,
              '#1d4ed8',
              2.0,
              '#1e3a8a',
            ],
            'fill-opacity': 0.42,
          },
        })
        map.addLayer({
          id: 'flood-line',
          type: 'line',
          source: 'flood',
          filter: ['has', 'minDepth'],
          paint: { 'line-color': '#2563eb', 'line-width': 0.8, 'line-opacity': 0.6 },
        })
        // v·d 急流危险区（功能 B）：水深×流速超限的行人失稳面，
        // 橙→红叠加在水深图层之上（浅水急流同样致命）
        map.addLayer({
          id: 'flood-vd',
          type: 'fill',
          source: 'flood',
          filter: ['has', 'minVd'],
          paint: {
            'fill-color': [
              'step',
              ['get', 'minVd'],
              '#fb923c',
              0.4,
              '#f97316',
              0.5,
              '#dc2626',
            ],
            'fill-opacity': 0.5,
          },
        })
        map.addLayer({
          id: 'flood-vd-line',
          type: 'line',
          source: 'flood',
          filter: ['has', 'minVd'],
          paint: { 'line-color': '#b91c1c', 'line-width': 1, 'line-dasharray': [2, 1.5] },
        })

        // 全部匹配路线：逐小段按失效状态着色（绿=畅通 / 黄=下一帧将失效 / 红=已淹没），
        // 随时间轴联动；备份路线畅通态为灰色；有选中时其余暗化
        map.addSource('routes', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'routes-line',
          type: 'line',
          source: 'routes',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            'line-color': [
              'match',
              ['get', 'status'],
              'flooded',
              '#ef4444',
              'warning',
              '#eab308',
              ['case', ['get', 'isBackup'], '#94a3b8', '#16a34a'],
            ],
            'line-width': 3,
            'line-opacity': ['case', ['get', 'dimmed'], 0.25, 0.9],
          },
        })

        // 无障碍对比：普通步行对照线（灰色长虚线，仅对比开关开启时可见）
        map.addSource('foot-routes', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'foot-routes-line',
          type: 'line',
          source: 'foot-routes',
          layout: { 'line-cap': 'round', 'line-join': 'round', visibility: 'none' },
          paint: {
            'line-color': '#475569',
            'line-width': 3.5,
            'line-dasharray': [2.2, 1.8],
            'line-opacity': 0.85,
          },
        })

        // 第 8-2 项：失效所 → 高地兜底所整所转移路线（紫色粗虚线，不可行变红）
        map.addSource('transfer-routes', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'transfer-routes-line',
          type: 'line',
          source: 'transfer-routes',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            'line-color': ['case', ['get', 'feasible'], '#7c3aed', '#dc2626'],
            'line-width': 5,
            'line-dasharray': [2, 1.2],
          },
        })
        map.addLayer({
          id: 'transfer-routes-arrows',
          type: 'symbol',
          source: 'transfer-routes',
          layout: {
            'symbol-placement': 'line',
            'symbol-spacing': 80,
            'icon-image': 'route-arrow',
            'icon-size': 0.8,
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
          },
        })

        // 选中人员的醒目路径：白色描边 + 接人段（琥珀虚线）+ 护送段（绿实线），受淹段变红
        map.addSource('active-route', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'active-route-casing',
          type: 'line',
          source: 'active-route',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#ffffff', 'line-width': 10, 'line-opacity': 0.9 },
        })
        map.addLayer({
          id: 'active-escort-line',
          type: 'line',
          source: 'active-route',
          filter: ['==', ['get', 'kind'], 'escort'],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            'line-color': [
              'match',
              ['get', 'status'],
              'flooded',
              '#ef4444',
              'warning',
              '#eab308',
              '#10b981',
            ],
            'line-width': 6,
          },
        })
        map.addLayer({
          id: 'active-pickup-line',
          type: 'line',
          source: 'active-route',
          filter: ['==', ['get', 'kind'], 'pickup'],
          layout: { 'line-join': 'round' },
          paint: {
            'line-color': [
              'match',
              ['get', 'status'],
              'flooded',
              '#ef4444',
              'warning',
              '#eab308',
              '#f59e0b',
            ],
            'line-width': 5,
            'line-dasharray': [1.8, 1.4],
          },
        })
        map.addLayer({
          id: 'active-route-arrows',
          type: 'symbol',
          source: 'active-route',
          layout: {
            'symbol-placement': 'line',
            'symbol-spacing': 70,
            'icon-image': 'route-arrow',
            'icon-size': 0.9,
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
          },
        })

        // 避难所（大号绿色徽章 + 常显名称）
        map.addSource('shelters', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'shelters-symbol',
          type: 'symbol',
          source: 'shelters',
          layout: {
            'icon-image': ['get', 'icon'],
            'icon-size': 1,
            'icon-allow-overlap': true,
            'text-field': ['get', 'label'],
            'text-font': TEXT_FONT,
            'text-size': 12,
            'text-anchor': 'top',
            'text-offset': [0, 1.6],
            'text-optional': true,
          },
          paint: {
            'text-color': '#065f46',
            'text-halo-color': '#ffffff',
            'text-halo-width': 1.6,
          },
        })

        // 第 2 项：重合标记偏移引导线（细灰虚线连回真实位置）
        map.addSource('offset-leaders', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'offset-leaders-line',
          type: 'line',
          source: 'offset-leaders',
          paint: {
            'line-color': '#64748b',
            'line-width': 1.2,
            'line-dasharray': [1.5, 1.5],
            'line-opacity': 0.8,
          },
        })

        // 帮扶者（蓝色人形圆点，不可用灰色）
        map.addSource('helpers', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'helpers-symbol',
          type: 'symbol',
          source: 'helpers',
          layout: {
            'icon-image': ['get', 'icon'],
            'icon-size': 1,
            'icon-allow-overlap': true,
            'text-field': ['get', 'name'],
            'text-font': TEXT_FONT,
            'text-size': 11,
            'text-anchor': 'top',
            'text-offset': [0, 1.3],
            'text-optional': true,
          },
          paint: {
            'text-color': '#1d4ed8',
            'text-halo-color': '#ffffff',
            'text-halo-width': 1.4,
          },
        })

        // 待撤离人员（人物水滴 pin，按画像区分，未匹配红色告警），选中放大；
        // 第 3 项：标签 text-variable-anchor 防碰撞 + symbol-sort-key 紧迫户必显；
        // 第十四节：已撤离 pin 迁至避难所旁（icon-offset 像素聚簇散开），
        // 护送/接人途中住址 pin 半透明压暗（icon-opacity 数据驱动）
        map.addSource('evacuees', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'evacuees-symbol',
          type: 'symbol',
          source: 'evacuees',
          layout: {
            'icon-image': ['get', 'icon'],
            'icon-size': ['case', ['get', 'selected'], 1.2, 0.95],
            'icon-anchor': ['get', 'anchor'],
            'icon-offset': ['get', 'offset'],
            'icon-allow-overlap': true,
            'symbol-sort-key': ['get', 'sortKey'],
            'text-field': ['get', 'label'],
            'text-font': TEXT_FONT,
            'text-size': 12,
            'text-variable-anchor': ['top', 'bottom', 'left', 'right'],
            'text-radial-offset': 0.5,
            'text-justify': 'auto',
            'text-optional': true,
          },
          paint: {
            'icon-opacity': ['case', ['get', 'dimmed'], 0.35, 1],
            'text-opacity': ['case', ['get', 'dimmed'], 0.45, 1],
            'text-color': '#9a3412',
            'text-halo-color': '#ffffff',
            'text-halo-width': 1.6,
          },
        })

        // 第 4 项：护送移动小点（出动档沿路线插值，接人段琥珀/护送段绿）；
        // 第十四节第 2 项：小点放大并带该户姓名标签（消除"人在路上
        // 但 pin 还在家"的割裂感）
        map.addSource('escort-dots', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'escort-dots-symbol',
          type: 'symbol',
          source: 'escort-dots',
          layout: {
            'icon-image': ['get', 'icon'],
            'icon-size': 1.2,
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
            'text-field': ['get', 'name'],
            'text-font': TEXT_FONT,
            'text-size': 11,
            'text-anchor': 'top',
            'text-offset': [0, 1.1],
            'text-allow-overlap': true,
            'text-ignore-placement': true,
          },
          paint: {
            'text-color': '#0f172a',
            'text-halo-color': '#ffffff',
            'text-halo-width': 1.5,
          },
        })

        // 无障碍对比：障碍点 ⚠️ 标记（叙事：CV 街景识别台阶→注入→路径改变）
        map.addSource('access-barriers', { type: 'geojson', data: EMPTY_FC })
        map.addLayer({
          id: 'access-barriers-symbol',
          type: 'symbol',
          source: 'access-barriers',
          layout: {
            visibility: 'none',
            'icon-image': 'access-barrier',
            'icon-size': 1,
            'icon-allow-overlap': true,
            'text-field': ['get', 'shortLabel'],
            'text-font': TEXT_FONT,
            'text-size': 11,
            'text-anchor': 'top',
            'text-offset': [0, 1.4],
            'text-optional': true,
          },
          paint: {
            'text-color': '#a16207',
            'text-halo-color': '#ffffff',
            'text-halo-width': 1.4,
          },
        })

        // 交互：点击待撤离者 → 选中并出路径；点击避难所/帮扶者 → 信息气泡
        map.on('click', 'evacuees-symbol', (e) => {
          const id = e.features?.[0]?.properties?.id
          if (id) onSelectRef.current(String(id))
        })
        map.on('click', 'shelters-symbol', (e) => {
          const p = e.features?.[0]?.properties
          if (!p) return
          // 第 5 项：容量透出（sh-3 满员叙事）；第 7 项：垂直避险降级文案
          const cap =
            p.capacity != null
              ? `<br/>容量 ${p.occupancy ?? 0}/${p.capacity}${
                  p.full ? ' · <b style="color:#b45309">已满员，后续人员自动改派</b>' : ''
                }`
              : ''
          new Popup({ offset: 20, closeButton: false })
            .setLngLat(e.lngLat)
            .setHTML(
              `<div style="font-size:13px"><b>🏠 ${p.name}</b><br/>${
                p.failed
                  ? p.vertical
                    ? '⚠️ 场地进水，转为垂直避险 —— 已入住人员上二楼以上，不再接收新增'
                    : '⛔ 已被淹/急流超限，不可用 —— 派往人员已自动改派'
                  : p.accessible
                    ? '♿ 无障碍避难所'
                    : '⚠️ 无坡道，轮椅不适用'
              }${cap}</div>`,
            )
            .addTo(map)
        })
        map.on('click', 'helpers-symbol', (e) => {
          const p = e.features?.[0]?.properties
          if (!p) return
          new Popup({ offset: 14, closeButton: false })
            .setLngLat(e.lngLat)
            .setHTML(
              `<div style="font-size:13px"><b>🤝 ${p.name}</b><br/>${
                p.lost
                  ? '⚠️ 超时失联，任务已由备份接替'
                  : p.available
                    ? `负责 ${p.assignedCount} 位帮扶对象`
                    : '当前不可用'
              }</div>`,
            )
            .addTo(map)
        })
        map.on('click', 'access-barriers-symbol', (e) => {
          const p = e.features?.[0]?.properties
          if (!p) return
          new Popup({ offset: 18, closeButton: false })
            .setLngLat(e.lngLat)
            .setHTML(
              `<div style="font-size:13px"><b>⚠️ ${p.label}</b><br/>轮椅不可通行，已重新规划绕行路线（x${p.ratio} 倍里程）</div>`,
            )
            .addTo(map)
        })
        for (const layer of ['evacuees-symbol', 'shelters-symbol', 'helpers-symbol', 'access-barriers-symbol']) {
          map.on('mouseenter', layer, () => {
            map.getCanvas().style.cursor = 'pointer'
          })
          map.on('mouseleave', layer, () => {
            map.getCanvas().style.cursor = ''
          })
        }

        setMapLoaded(true)
      })()
    })

    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      setMapLoaded(false)
    }
  }, [])

  // 底图切换（街道 / 卫星影像）
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    map.setLayoutProperty('satellite', 'visibility', basemap === 'satellite' ? 'visible' : 'none')
    map.setLayoutProperty('osm', 'visibility', basemap === 'streets' ? 'visible' : 'none')
  }, [mapLoaded, basemap])

  // 调度态势 / 选中变化 → 更新点位与路线
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded || !schedule) return

    // 第 2 项：重合标记地理偏移（<15m 聚簇散开 / 与帮扶者重合偏移）；
    // 已撤离者不参与住址聚簇（pin 已迁往避难所，第十四节第 1 项）
    const atHome = schedule.evacuees.filter((e) => e.matchStatus !== 'evacuated')
    const evPos = displayPositions(
      atHome,
      schedule.helpers.map((h) => [h.location.lng, h.location.lat]),
    )

    // 第十四节第 1 项：已撤离者 pin 迁至目标避难所，同所人员绕徽章
    // 按像素 icon-offset 环形散开（像素单位缩放不聚拢，每环 8 人）
    const shelterById = new Map(schedule.shelters.map((s) => [s.id, s]))
    const evacuatedOffset = new Map<string, [number, number]>()
    const evacuatedBySh = new Map<string, string[]>()
    for (const ev of schedule.evacuees) {
      if (ev.matchStatus === 'evacuated' && ev.shelterId && shelterById.has(ev.shelterId)) {
        const list = evacuatedBySh.get(ev.shelterId) ?? []
        list.push(ev.id)
        evacuatedBySh.set(ev.shelterId, list)
      }
    }
    for (const ids of evacuatedBySh.values()) {
      ids.forEach((id, k) => {
        const ring = Math.floor(k / 8)
        const inRing = Math.min(ids.length - ring * 8, 8)
        const ang = ((k % 8) / inRing) * 2 * Math.PI + Math.PI / 2
        const r = 34 + ring * 26
        evacuatedOffset.set(id, [Math.cos(ang) * r, Math.sin(ang) * r])
      })
    }

    ;(map.getSource('evacuees') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: schedule.evacuees.map((ev) => {
        const evacuated = ev.matchStatus === 'evacuated'
        // 第十四节第 2 项：接人/护送途中住址 pin 半透明压暗
        const traveling = ev.matchStatus === 'en_route' || ev.matchStatus === 'escorting'
        // 第 1 项：剧情户虚拟头像（已注册才用；未匹配仍用红色告警 pin；
        // 已撤离统一用灰 ✓ pin，状态语义优先于头像辨识）
        const avatar =
          !evacuated && ev.matchStatus !== 'unmatched' && map.hasImage(`avatar-${ev.id}`)
        // 第 3 项：紧迫户必显（sort-key 小者优先占位）：选中 > 未匹配 >
        // 距最迟出发 <60 分钟 > 其余 > 已撤离
        const urgent =
          !evacuated &&
          frame !== null &&
          new Date(ev.latestDeparture).getTime() - new Date(frame.clock ?? 0).getTime() <
            3_600_000
        const sortKey =
          ev.id === selectedEvacueeId
            ? 0
            : ev.matchStatus === 'unmatched'
              ? 1
              : urgent
                ? 2
                : evacuated
                  ? 30
                  : 10
        const shelter = evacuated && ev.shelterId ? shelterById.get(ev.shelterId) : undefined
        return {
          type: 'Feature' as const,
          properties: {
            id: ev.id,
            name: ev.name,
            // 已撤离聚簇不显姓名（避免所旁标签堆叠）
            label: evacuated ? '' : ev.name,
            icon: evacuated
              ? `evacuee-${ev.profile}-done`
              : avatar
                ? `avatar-${ev.id}`
                : `evacuee-${ev.profile}${ev.matchStatus === 'unmatched' ? '-alert' : ''}`,
            anchor: avatar ? 'center' : 'bottom',
            offset: evacuatedOffset.get(ev.id) ?? [0, 0],
            dimmed: traveling,
            selected: ev.id === selectedEvacueeId,
            sortKey,
          },
          geometry: {
            type: 'Point' as const,
            coordinates: shelter
              ? [shelter.location.lng, shelter.location.lat]
              : evPos.get(ev.id) ?? [ev.location.lng, ev.location.lat],
          },
        }
      }),
    })
    // 第 2 项：偏移者画引导线连回真实位置
    ;(map.getSource('offset-leaders') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: [...evPos.entries()].map(([id, pos]) => {
        const ev = schedule.evacuees.find((e) => e.id === id)!
        return {
          type: 'Feature' as const,
          properties: {},
          geometry: {
            type: 'LineString' as const,
            coordinates: [pos, [ev.location.lng, ev.location.lat]],
          },
        }
      }),
    })
    ;(map.getSource('helpers') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: schedule.helpers.map((h) => ({
        type: 'Feature',
        properties: {
          name: h.lost ? `${h.name}（失联）` : h.name,
          icon: h.available ? 'helper' : 'helper-off',
          available: h.available,
          lost: Boolean(h.lost),
          assignedCount: h.assignedEvacueeIds.length,
        },
        geometry: { type: 'Point', coordinates: [h.location.lng, h.location.lat] },
      })),
    })
    ;(map.getSource('shelters') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: schedule.shelters.map((s) => {
        const failed = failedShelterIds.includes(s.id)
        // 第 7 项：垂直避险所失效 → 黄色降级（仍触发在途改派）而非红叉
        const vertical = Boolean(s.verticalRefuge)
        const full = s.capacity != null && (s.occupancy ?? 0) >= s.capacity
        return {
          type: 'Feature' as const,
          properties: {
            name: s.name,
            label: failed
              ? vertical
                ? `⚠️ ${s.name}（垂直避险）`
                : `⛔ ${s.name}（失效）`
              : `🏠 ${s.name}`,
            icon: failed
              ? vertical
                ? 'shelter-vertical'
                : 'shelter-failed'
              : s.wheelchairAccessible
                ? 'shelter'
                : 'shelter-limited',
            accessible: s.wheelchairAccessible,
            failed,
            vertical,
            capacity: s.capacity ?? null,
            occupancy: s.occupancy ?? null,
            full,
          },
          geometry: { type: 'Point' as const, coordinates: [s.location.lng, s.location.lat] },
        }
      }),
    })
    // 选中者的主路线交给 active-route 醒目渲染；未升级的改派候选不显示；
    // 其余路线逐小段按失效状态着色（绿/黄/红，按各自画像水深+v·d
    // 阈值），随推演时刻联动
    const profileOf = new Map(schedule.evacuees.map((e) => [e.id, e.profile]))
    ;(map.getSource('routes') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: schedule.assignments
        .filter((a) => !a.isFallback && !(a.evacueeId === selectedEvacueeId && !a.isBackup))
        .flatMap((a) => {
          const profile = profileOf.get(a.evacueeId)
          const thr: HazardThreshold = profile
            ? hazardOf(profile)
            : { depth: 0, vd: Infinity }
          return statusSegments(a.route, frame, nextFrame, thr).map((seg) => ({
            type: 'Feature' as const,
            properties: {
              isBackup: a.isBackup,
              status: seg.status,
              dimmed: selectedEvacueeId !== null && a.evacueeId !== selectedEvacueeId,
            },
            geometry: { type: 'LineString' as const, coordinates: seg.coords },
          }))
        }),
    })
  }, [mapLoaded, schedule, selectedEvacueeId, frame, nextFrame, failedShelterIds])

  // 第 4 项：护送移动小点（出动档，沿主派路线按任务时间轴插值）；
  // 第十四节第 3 项：传入下一帧时刻，任务窗口落在两帧之间时夹取补显
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded || !schedule) return
    const nowMin = frame?.minute
    const evById = new Map(schedule.evacuees.map((e) => [e.id, e]))
    const features =
      nowMin === undefined || schedule.alertLevel !== 'dispatch'
        ? []
        : schedule.assignments
            .filter((a) => !a.isBackup && !a.isFallback && a.timeline)
            .flatMap((a) => {
              const ev = evById.get(a.evacueeId)
              if (!ev) return []
              const dot = movingDotAt(a, ev, nowMin, nextFrame?.minute ?? null)
              if (!dot) return []
              return [
                {
                  type: 'Feature' as const,
                  properties: { icon: `escort-dot-${dot.phase}`, name: ev.name },
                  geometry: { type: 'Point' as const, coordinates: dot.pos },
                },
              ]
            })
    ;(map.getSource('escort-dots') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features,
    })
  }, [mapLoaded, schedule, frame, nextFrame])

  // 第 8-2 项：整所转移路线（失效非垂直避险所 → 高地兜底所）
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    ;(map.getSource('transfer-routes') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: activeTransfers.map((t) => ({
        type: 'Feature' as const,
        properties: { feasible: t.feasible },
        geometry: { type: 'LineString' as const, coordinates: t.route },
      })),
    })
  }, [mapLoaded, activeTransfers])

  // 无障碍对比数据：案例户的步行对照线 + 障碍点（随态势加载一次）
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded || !schedule) return
    const cases = schedule.accessCases ?? []
    ;(map.getSource('foot-routes') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: schedule.assignments
        .filter((a) => a.footRoute && !a.isBackup && !a.isFallback)
        .map((a) => ({
          type: 'Feature',
          properties: { evacueeId: a.evacueeId },
          geometry: { type: 'LineString', coordinates: a.footRoute! },
        })),
    })
    ;(map.getSource('access-barriers') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: cases.map((c) => ({
        type: 'Feature',
        properties: { label: c.barrier.label, shortLabel: '台阶障碍', ratio: c.detourRatio },
        geometry: { type: 'Point', coordinates: [c.barrier.location.lng, c.barrier.location.lat] },
      })),
    })
  }, [mapLoaded, schedule])

  // 对比开关 → 切换双线/障碍图层可见性
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    const vis = accessCompare ? 'visible' : 'none'
    map.setLayoutProperty('foot-routes-line', 'visibility', vis)
    map.setLayoutProperty('access-barriers-symbol', 'visibility', vis)
  }, [mapLoaded, accessCompare])

  // 路径规划 / 推演时刻变化 → 更新高亮路径（受淹段红 / 即将失效段黄）
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    ;(map.getSource('active-route') as GeoJSONSource).setData(
      routePlan
        ? {
            type: 'FeatureCollection',
            features: routePlan.segments.map((s) => ({
              type: 'Feature',
              properties: { kind: s.kind, flooded: s.flooded, status: s.status },
              geometry: { type: 'LineString', coordinates: s.coords },
            })),
          }
        : EMPTY_FC,
    )
  }, [mapLoaded, routePlan])

  // 补位演练触发 → 新主路线闪烁脉冲（连线切换动画）
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded || drillStamp === 0) return
    let tick = 0
    const timer = window.setInterval(() => {
      tick += 1
      const on = tick % 2 === 1
      if (map.getLayer('active-route-casing')) {
        map.setPaintProperty('active-route-casing', 'line-color', on ? '#fbbf24' : '#ffffff')
        map.setPaintProperty('active-route-casing', 'line-width', on ? 14 : 10)
      }
      if (tick >= 6) {
        window.clearInterval(timer)
      }
    }, 250)
    return () => window.clearInterval(timer)
  }, [mapLoaded, drillStamp])

  // 时间轴变化 → 更新淹没图层
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    ;(map.getSource('flood') as GeoJSONSource).setData(frame ? frame.geojson : EMPTY_FC)
  }, [mapLoaded, frame])

  // 选中人员 → 视野覆盖整条路线；无路线则飞到住址
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded || !selectedEvacuee) return
    if (routePlan) {
      const coords = routePlan.assignment.route
      const lngs = coords.map((c) => c[0])
      const lats = coords.map((c) => c[1])
      map.fitBounds(
        [
          [Math.min(...lngs), Math.min(...lats)],
          [Math.max(...lngs), Math.max(...lats)],
        ],
        { padding: { top: 90, bottom: 90, left: 90, right: 90 }, maxZoom: 16.5, duration: 800 },
      )
    } else {
      map.flyTo({ center: [selectedEvacuee.location.lng, selectedEvacuee.location.lat], zoom: 15.5 })
    }
    // 仅在选中对象变化时调整视野（推演时刻变化不重置视野）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapLoaded, selectedEvacuee])

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />

      {/* 底图切换（街道/卫星）+ 无障碍对比开关 */}
      <div className="absolute left-3 top-3 z-10 flex items-start gap-2">
        <div className="flex overflow-hidden rounded-lg bg-white shadow-md">
          {(
            [
              ['streets', '街道'],
              ['satellite', '卫星'],
            ] as [Basemap, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setBasemap(key)}
              className={`px-3 py-1.5 text-xs font-semibold transition-colors ${
                basemap === key ? 'bg-sky-600 text-white' : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {accessCases.length > 0 && (
          <button
            type="button"
            onClick={() => setAccessCompare((v) => !v)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold shadow-md transition-colors ${
              accessCompare
                ? 'bg-violet-600 text-white'
                : 'bg-white text-gray-600 hover:bg-gray-100'
            }`}
          >
            ♿ 无障碍对比
          </button>
        )}
      </div>

      {/* 无障碍对比卡片：3 个分化案例的绕行倍率，点击定位；
          卡尾为街景 AI 识别演示（第十五节：照片 → 判定 → 绕行已生效） */}
      {accessCompare && accessCases.length > 0 && schedule && (
        <div className="absolute left-3 top-14 z-10 max-h-[calc(100%-5rem)] w-72 overflow-y-auto rounded-xl bg-white/95 p-3 shadow-lg backdrop-blur">
          <div className="text-xs font-bold text-gray-900">♿ 轮椅 × 步行路径对比</div>
          <p className="mt-1 text-[11px] leading-4 text-gray-500">
            街景识别出台阶/陡坎（⚠️）→ 注入路网 → 轮椅路线自动绕行。
            灰虚线＝普通步行，彩线＝轮椅实际路线。
          </p>
          <div className="mt-2 space-y-1">
            {accessCases.map((c) => {
              const ev = schedule.evacuees.find((e) => e.id === c.evacueeId)
              return (
                <button
                  key={c.evacueeId}
                  type="button"
                  onClick={() => onSelectEvacuee(c.evacueeId)}
                  className={`flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-xs transition-colors ${
                    selectedEvacueeId === c.evacueeId
                      ? 'bg-violet-50 text-violet-800'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  <span className="font-semibold">{ev?.name ?? c.evacueeId}</span>
                  <span className="text-[11px] text-gray-500">
                    {c.footKm}km → {c.wheelchairKm}km
                    <span className="ml-1 font-bold text-violet-600">x{c.detourRatio}</span>
                  </span>
                </button>
              )
            })}
          </div>

          {/* 街景 AI 识别：预选巷口照片 → 多模态判定台阶/陡坎（坐标已预绑定） */}
          <div className="mt-2 border-t border-gray-100 pt-2">
            {scanState === 'idle' && (
              <button
                type="button"
                onClick={runScan}
                className="w-full rounded-lg bg-violet-600 px-2 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-violet-700"
              >
                📷 街景 AI 识别：这些障碍怎么发现的？
              </button>
            )}
            {scanState === 'scanning' && (
              <p className="animate-pulse rounded-lg bg-violet-50 px-2 py-2 text-center text-xs font-semibold text-violet-700">
                🔍 AI 识别中…多模态判定台阶/陡坎
              </p>
            )}
            {scanState === 'done' && scanResult && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                      scanResult.source === 'llm'
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-gray-200 text-gray-600'
                    }`}
                  >
                    {scanResult.source === 'llm' ? 'Qwen-VL 实时识别' : '模板判定'}
                  </span>
                  <button
                    type="button"
                    onClick={runScan}
                    className="text-[11px] font-semibold text-violet-600 hover:underline"
                  >
                    ↻ 重新识别
                  </button>
                </div>
                {scanResult.items.map((item) => {
                  const c = accessCases.find((x) => x.evacueeId === item.evacueeId)
                  const ev = schedule.evacuees.find((e) => e.id === item.evacueeId)
                  return (
                    <button
                      key={item.evacueeId}
                      type="button"
                      onClick={() => onSelectEvacuee(item.evacueeId)}
                      className="block w-full rounded-lg border border-gray-100 p-1.5 text-left transition-colors hover:border-violet-200 hover:bg-violet-50/50"
                    >
                      <img
                        src={item.image}
                        alt={`${ev?.name ?? item.evacueeId} 附近街景`}
                        className="h-20 w-full rounded object-cover"
                      />
                      <p className="mt-1 text-[11px] leading-4 text-gray-800">
                        <span className="font-bold">{ev?.name ?? item.evacueeId}附近</span>
                        {item.barrierDetected ? ' ⚠️ ' : ' ✅ '}
                        {item.verdict}
                      </p>
                      {item.barrierDetected && c && (
                        <p className="mt-0.5 text-[10px] font-semibold text-violet-600">
                          已注入路网 → 轮椅路线绕行 x{c.detourRatio}（点击定位）
                        </p>
                      )}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 第 8-2 项：整所转移告警横幅（失效所已入住人员 → 高地兜底所） */}
      {activeTransfers.length > 0 && schedule && (
        <div className="absolute left-1/2 top-3 z-10 w-[26rem] -translate-x-1/2 space-y-1.5">
          {activeTransfers.map((t) => {
            const from = schedule.shelters.find((s) => s.id === t.fromShelterId)
            const to = schedule.shelters.find((s) => s.id === t.toShelterId)
            return (
              <div
                key={t.fromShelterId}
                className={`rounded-xl px-3 py-2 text-xs font-semibold shadow-lg backdrop-blur ${
                  t.feasible
                    ? 'bg-violet-50/95 text-violet-800'
                    : 'bg-red-50/95 text-red-700'
                }`}
              >
                {t.feasible
                  ? `🚨 ${from?.name ?? t.fromShelterId} 失效，已入住 ${t.count} 人沿紫色路线整所转移至 ${to?.name ?? t.toShelterId}`
                  : `⛔ ${from?.name ?? t.fromShelterId} 失效且转移路线已不可行 —— ${t.count} 人就地垂直避险，请求舰艇/直升机救援`}
              </div>
            )
          })}
        </div>
      )}

      {/* 图例 */}
      <div className="absolute bottom-3 right-3 z-10 rounded-lg bg-white/95 px-3 py-2 text-[11px] leading-5 text-gray-600 shadow-md">
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-orange-500" /> 待撤离
          <span className="ml-2 inline-block h-2.5 w-2.5 rounded-full bg-red-500" /> 未匹配
          <span className="ml-2 inline-block h-2.5 w-2.5 rounded-full bg-gray-400 text-center text-[8px] font-bold leading-[10px] text-white">✓</span>{' '}
          已安置
          <span className="ml-2 inline-block h-2.5 w-2.5 rounded-full bg-blue-500" /> 帮扶者
          <span className="ml-2 inline-block h-2.5 w-2.5 rounded-full bg-emerald-600" /> 避难所
          <span className="ml-2 inline-block h-2.5 w-2.5 rounded-full bg-red-600 text-center text-[8px] font-bold leading-[10px] text-white">✕</span>{' '}
          失效
        </div>
        <div className="mt-1 flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 border-t-2 border-dashed border-amber-500" /> 接人段
          <span className="ml-2 inline-block h-0.5 w-4 bg-emerald-500" /> 护送段
          {/* 水深六档渐变（功能 A）+ v·d 急流危险区（功能 B） */}
          <span className="ml-2 inline-block h-2.5 w-10 rounded-sm" style={{ background: 'linear-gradient(90deg,#bfdbfe,#60a5fa,#1d4ed8,#1e3a8a)' }} />{' '}
          水深 0.05→2m+
          <span className="ml-2 inline-block h-2.5 w-2.5 rounded-sm border border-red-700 bg-orange-500/60" /> 急流 v·d
        </div>
        <div className="mt-1 flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-green-600" /> 畅通
          <span className="ml-2 inline-block h-0.5 w-4 bg-yellow-500" /> 下一小时将失效
          <span className="ml-2 inline-block h-0.5 w-4 bg-red-500" /> 已失效
          <span className="ml-2 inline-block h-2.5 w-2.5 rounded-full bg-amber-600" /> 垂直避险
          <span className="ml-2 inline-block h-0.5 w-4 border-t-2 border-dashed border-violet-600" /> 整所转移
        </div>
      </div>

      {/* 路径规划卡片 */}
      {selectedEvacuee && (
        <RouteCard
          evacuee={selectedEvacuee}
          plan={routePlan}
          schedule={schedule}
          frame={frame}
          onSimulateLost={onSimulateLost}
          roadbookOpen={roadbookOpen}
          onToggleRoadbook={() => setRoadbookOpen((v) => !v)}
        />
      )}
      {/* 语音路书面板（P1）：盲人户入口，TTS 播报陪同导引路书 */}
      {selectedEvacuee && roadbookOpen && (
        <RoadbookPanel
          evacuee={selectedEvacuee}
          scenario={scenario}
          schedule={schedule}
          onClose={() => setRoadbookOpen(false)}
        />
      )}
    </div>
  )
}

/** 左下角路径规划卡：画像策略 + 分段距离/耗时 + 受淹/预警告警 + 补位演练 */
function RouteCard({
  evacuee,
  plan,
  schedule,
  frame,
  onSimulateLost,
  roadbookOpen,
  onToggleRoadbook,
}: {
  evacuee: Evacuee
  plan: RoutePlan | null
  schedule: ScheduleState | null
  frame: FloodFrame | null
  onSimulateLost: (helperId: string) => void
  roadbookOpen: boolean
  onToggleRoadbook: () => void
}) {
  const helperNames = evacuee.helperIds
    .map((id) => schedule?.helpers.find((h) => h.id === id)?.name)
    .filter(Boolean)
  const shelterName = schedule?.shelters.find((s) => s.id === evacuee.shelterId)?.name
  const backupCount = (schedule?.assignments ?? []).filter(
    (a) => a.evacueeId === evacuee.id && a.isBackup,
  ).length
  const promoted = Boolean(plan?.assignment.promoted)
  const rerouted = Boolean(plan?.assignment.rerouted)
  /** 第 6 项(a)：串行链时间口径冲突（最迟出发 < 最早可行开始）红色告警 */
  const conflict = Boolean(plan?.assignment.conflict)
  const departBy = plan?.assignment.departBy ?? null
  /** 第 5 项：改派目标满员提示（rerouted 时检查新目标所容量） */
  const targetShelter = schedule?.shelters.find((s) => s.id === plan?.assignment.shelterId)
  const targetFull =
    targetShelter?.capacity != null &&
    (targetShelter.occupancy ?? 0) >= targetShelter.capacity
  const primaryHelper = plan
    ? schedule?.helpers.find((h) => h.id === plan.assignment.helperId)
    : undefined
  /** 串行链信息（P1 真实匹配算法）：该主帮扶者的主派单数与本单次序 */
  const seq = plan?.assignment.sequence ?? 1
  const chainLen = plan
    ? (schedule?.assignments ?? []).filter(
        (a) => a.helperId === plan.assignment.helperId && !a.isBackup && !a.isFallback,
      ).length
    : 0

  return (
    <div className="absolute bottom-3 left-3 z-10 w-80 rounded-xl bg-white/95 p-4 shadow-lg backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold text-gray-900">{evacuee.name}</span>
        <span className="text-xs text-gray-500">{PROFILE_LABEL[evacuee.profile]}</span>
        {frame && (
          <span className="ml-auto rounded-full bg-sky-100 px-2 py-0.5 text-[11px] text-sky-700">
            推演 +{frame.minute} 分
          </span>
        )}
      </div>

      {plan ? (
        <>
          {/* 第 6 项(a)：不可行排班红色冲突告警（两套时间口径自洽校验） */}
          {conflict && (
            <div className="mt-2 rounded-lg border border-red-300 bg-red-50 px-2.5 py-1.5 text-xs font-bold text-red-700">
              🚨 排班冲突：最迟出发早于串行链最早可行开始，需人工增派/拆链
            </div>
          )}
          {promoted && (
            <div className="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-700">
              🔁 主帮扶失联，备份 {primaryHelper?.name ?? ''} 已自动升级接替任务
            </div>
          )}
          {/* 功能 D：避难所失效自动改派提示；第 5 项：改派目标容量透出 */}
          {rerouted && (
            <div className="mt-2 rounded-lg bg-red-50 px-2.5 py-1.5 text-xs font-semibold text-red-700">
              ⛔ 原避难所已被淹/急流超限，已自动改派至 {shelterName ?? '次近可达避难所'}
              {targetShelter?.capacity != null &&
                `（容量 ${targetShelter.occupancy ?? 0}/${targetShelter.capacity}）`}
            </div>
          )}
          {/* 第 5 项：目标所满员提示（未改派但目标已满，后续新增需求将改派） */}
          {!rerouted && targetFull && (
            <div className="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-700">
              ⚠️ {targetShelter?.name} 容量 {targetShelter?.occupancy}/
              {targetShelter?.capacity} 已满 —— 本户已占位，后续新增人员将自动改派
            </div>
          )}
          {/* P1 真实匹配：串行链角标（一人串行接多户，时间窗校验通过） */}
          {chainLen > 1 && (
            <div className="mt-2 rounded-lg bg-violet-50 px-2.5 py-1.5 text-xs font-semibold text-violet-700">
              ⛓ {primaryHelper?.name ?? '帮扶者'}串行任务 第 {seq}/{chainLen} 单
              {seq > 1 && ' · 送达上一户后从避难所出发'}
            </div>
          )}
          <p className="mt-2 text-xs leading-5 text-gray-600">{ROUTE_STRATEGY[evacuee.profile]}</p>
          <div className="mt-2 space-y-1.5 text-xs">
            <div className="flex items-center gap-2">
              <span className="inline-block h-0.5 w-5 border-t-2 border-dashed border-amber-500" />
              <span className="text-gray-700">
                接人段（帮扶者→住址）约 {Math.round(plan.pickupM)} 米 · {plan.pickupMin} 分钟
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-block h-1 w-5 rounded bg-emerald-500" />
              <span className="text-gray-700">
                护送段（住址→{shelterName ?? '避难所'}）约 {Math.round(plan.escortM)} 米 ·{' '}
                {plan.escortMin} 分钟
              </span>
            </div>
          </div>
          <div
            className={`mt-2 rounded-lg px-2.5 py-1.5 text-xs font-semibold ${
              plan.floodedCount > 0
                ? 'bg-red-50 text-red-700'
                : plan.warningCount > 0
                  ? 'bg-yellow-50 text-yellow-700'
                  : 'bg-emerald-50 text-emerald-700'
            }`}
          >
            {plan.floodedCount > 0
              ? `⚠️ 当前推演时刻有 ${plan.floodedCount} 段路径失效（水深/急流超限），需提前出发或改道`
              : plan.warningCount > 0
                ? `⏳ ${plan.warningCount} 段路径将于下一小时内失效，建议立即出发`
                : '✓ 当前推演时刻路径全程可通行'}
          </div>
          {/* 第 6 项(a)：路线反推的帮扶者最迟出发时刻（与户 latestDeparture 同源自洽） */}
          {departBy && (
            <div className="mt-1.5 text-[11px] text-gray-500">
              ⏰ 帮扶者最迟出发：
              {new Date(departBy).toLocaleTimeString('zh-CN', {
                hour: '2-digit',
                minute: '2-digit',
              })}
              （含接人段耗时反推）
            </div>
          )}
          <div className="mt-2 flex items-center justify-between text-[11px] text-gray-400">
            <span>
              帮扶：{helperNames.join('、') || '—'}
              {backupCount > 0 && `（含 ${backupCount} 名备份）`}
            </span>
            <span>阳朔真实路网 · Valhalla 无障碍路径</span>
          </div>
          {/* 补位演练：模拟主帮扶超时失联 → 备份自动升级（核心差异化卖点） */}
          {!promoted && backupCount > 0 && (
            <button
              type="button"
              onClick={() => onSimulateLost(plan.assignment.helperId)}
              className="mt-2 w-full rounded-lg border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-700 transition-colors hover:bg-amber-100"
            >
              ⚡ 演练：模拟主帮扶 {primaryHelper?.name ?? ''} 失联（备份自动补位）
            </button>
          )}
          {/* P1 语音路书：盲人户入口（叙事最强），TTS 陪同导引播报 */}
          {evacuee.profile === 'blind' && (
            <button
              type="button"
              onClick={onToggleRoadbook}
              className={`mt-2 w-full rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                roadbookOpen
                  ? 'bg-violet-600 text-white hover:bg-violet-700'
                  : 'border border-violet-300 bg-violet-50 text-violet-700 hover:bg-violet-100'
              }`}
            >
              🦯 语音路书：视障陪同导引{roadbookOpen ? '（收起）' : '（TTS 播报）'}
            </button>
          )}
        </>
      ) : (
        <div className="mt-2 rounded-lg bg-red-50 px-2.5 py-2 text-xs font-semibold text-red-700">
          ⚠️ 尚未匹配帮扶者，无可派路线 —— 请优先为该户调度人力
        </div>
      )}
    </div>
  )
}
