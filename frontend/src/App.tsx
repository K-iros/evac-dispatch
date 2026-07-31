import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  ActiveTransfer,
  AlertLevel,
  Assignment,
  FloodFrame,
  Profile,
  Scenario,
  ScheduleState,
} from './types'
import { fetchFloodFrames, fetchScenarios, fetchSchedule } from './api/client'
import {
  buildPriorityList,
  buildTimeline,
  clampVisible,
  hazardOf,
  pointInFlood,
  routeFailureMinute,
  SHELTER_HAZARD,
} from './components/routeUtils'
import TopBar from './components/TopBar'
import EvacueeList from './components/EvacueeList'
import MapView from './components/MapView'
import BriefingPanel from './components/BriefingPanel'

const DEFAULT_SCENARIO = 's2024'
const NO_FAILED_SHELTERS: string[] = []

/**
 * 态势派生（纯前端、不改原始数据，"重置演练"即恢复）：
 * 1. 第 4 项时间驱动四态：出动档按任务时间轴（最迟出发−安全余量、
 *    串行链前单送达递推）推进 待命→在途(接人)→护送中→已撤离；
 * 2. 功能 D：主路线目标避难所在当前推演时刻失效 → 自动升级首个
 *    未失效的改派候选（isFallback 数组序即级联序，第 8-1 项）；
 *    已送达户不再改派（交由第 8-2 项整所转移）；
 * 3. 补位模拟：失联帮扶者剔除，其主派任务由备份自动升级。
 */
function deriveSchedule(
  base: ScheduleState,
  lostIds: string[],
  alertLevel: AlertLevel,
  failedShelterIds: string[],
  nowMin: number | null,
  nextMin: number | null,
): ScheduleState {
  const lost = new Set(lostIds)
  const failed = new Set(failedShelterIds)
  const evById = new Map(base.evacuees.map((e) => [e.id, e]))
  /** 功能 D 改派后的目标避难所：evacuee id → shelter id */
  const rerouted = new Map<string, string>()
  const dispatch = alertLevel === 'dispatch'

  // 串行链前单送达时刻递推（第 4 项）：按原始主派链预算，
  // 改派/补位后的新路线仍沿用链上同一最早开始时刻（演示口径）
  const prevArriveByEv = new Map<string, number>()
  const origTimeline = new Map<string, ReturnType<typeof buildTimeline>>()
  if (dispatch) {
    const byHelper = new Map<string, Assignment[]>()
    for (const a of base.assignments) {
      if (a.isBackup || a.isFallback) continue
      const list = byHelper.get(a.helperId) ?? []
      list.push(a)
      byHelper.set(a.helperId, list)
    }
    for (const chain of byHelper.values()) {
      chain.sort((x, y) => (x.sequence ?? 1) - (y.sequence ?? 1))
      let prev = 0
      for (const a of chain) {
        const ev = evById.get(a.evacueeId)
        if (!ev) continue
        prevArriveByEv.set(a.evacueeId, prev)
        const t = buildTimeline(a, ev, prev)
        origTimeline.set(a.evacueeId, t)
        prev = t.arriveMin
      }
    }
  }

  const assignments = base.evacuees.flatMap((ev) => {
    let own = base.assignments.filter((a) => a.evacueeId === ev.id)
    // 出动档已送达：不再改派（人已在所内，第 8-2 项接管）
    const t0 = origTimeline.get(ev.id)
    const settled = dispatch && t0 !== undefined && nowMin !== null && nowMin >= t0.arriveMin
    // 功能 D：主路线的避难所失效 → 升级首个未失效的改派候选（级联序）
    const primary0 = own.find((a) => !a.isBackup && !a.isFallback)
    if (primary0 && failed.has(primary0.shelterId) && !settled) {
      const fallback = own.find((a) => a.isFallback && !failed.has(a.shelterId))
      if (fallback) {
        rerouted.set(ev.id, fallback.shelterId)
        own = own
          .filter((a) => a !== primary0)
          .map((a) => (a === fallback ? { ...a, isFallback: false, rerouted: true } : a))
      }
    }
    own = own.filter((a) => !a.isFallback) // 未升级的改派候选平时不参与
    // 补位模拟：主帮扶未失联则原样保留（剔除失联的备份）
    const primary = own.find((a) => !a.isBackup)
    if (!primary || !lost.has(primary.helperId)) {
      return own.filter((a) => !lost.has(a.helperId))
    }
    // 主帮扶失联：首个可用备份升级为主
    const backups = own.filter((a) => a.isBackup && !lost.has(a.helperId))
    if (backups.length === 0) return []
    const [next, ...rest] = backups
    return [{ ...next, isBackup: false, promoted: true }, ...rest]
  })

  // 第 4 项：为最终主派任务（含改派/补位升级后）挂任务时间轴
  const finalAssignments = dispatch
    ? assignments.map((a) => {
        if (a.isBackup || a.isFallback) return a
        const ev = evById.get(a.evacueeId)
        if (!ev) return a
        const timeline = buildTimeline(a, ev, prevArriveByEv.get(a.evacueeId) ?? 0)
        return { ...a, timeline }
      })
    : assignments

  const timelineByEv = new Map(
    finalAssignments
      .filter((a) => !a.isBackup && !a.isFallback && a.timeline)
      .map((a) => [a.evacueeId, a.timeline!]),
  )

  const evacuees = base.evacuees.map((ev) => {
    const helperIds = ev.helperIds.filter((id) => !lost.has(id))
    const shelterId = rerouted.get(ev.id) ?? ev.shelterId
    const hasRoute = finalAssignments.some((a) => a.evacueeId === ev.id && !a.isBackup)
    let matchStatus = ev.matchStatus
    if (ev.matchStatus !== 'unmatched' && !hasRoute) matchStatus = 'unmatched'
    else if (dispatch && matchStatus === 'matched') {
      // 时间驱动四态：待命→在途(接人)→护送中→已撤离；
      // 第十四节第 3 项：任务窗口整体落在两帧之间时本帧夹取为
      // 护送中（与 movingDotAt 小点补显同口径，名单/地图一致）
      const t = timelineByEv.get(ev.id)
      if (t && nowMin !== null) {
        matchStatus =
          nowMin < t.startMin
            ? clampVisible(t, nowMin, nextMin)
              ? 'escorting'
              : 'matched'
            : nowMin < t.pickupEndMin
              ? 'en_route'
              : nowMin < t.arriveMin
                ? 'escorting'
                : 'evacuated'
      } else {
        matchStatus = 'en_route'
      }
    }
    return { ...ev, helperIds, matchStatus, shelterId }
  })

  const helpers = base.helpers.map((h) =>
    lost.has(h.id) ? { ...h, available: false, lost: true } : h,
  )

  return { ...base, alertLevel, evacuees, helpers, assignments: finalAssignments }
}

/** 调度作战板主布局：顶部时间轴+看板 / 左侧名单+优先级清单 / 右侧地图 */
export default function App() {
  const [baseSchedule, setBaseSchedule] = useState<ScheduleState | null>(null)
  const [frames, setFrames] = useState<FloodFrame[]>([])
  const [frameIndex, setFrameIndex] = useState(0)
  const [selectedEvacueeId, setSelectedEvacueeId] = useState<string | null>(null)
  const [alertLevel, setAlertLevel] = useState<AlertLevel>('standby')
  // 补位演练：失联帮扶者 id 列表；drillStamp 触发地图切换动画
  const [lostHelperIds, setLostHelperIds] = useState<string[]>([])
  const [drillStamp, setDrillStamp] = useState(0)
  // 情景预设（功能 C）与播放模式（功能 A）
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO)
  const [playing, setPlaying] = useState(false)
  const [playSpeed, setPlaySpeed] = useState<1 | 4>(1)
  // AI 派单简报抽屉（第十二节 P0）
  const [briefingsOpen, setBriefingsOpen] = useState(false)
  // 二期决策 2 窄屏止血：<768px 常驻提示横幅（可关闭，桌面端 md:hidden 零影响）
  const [mobileNoticeClosed, setMobileNoticeClosed] = useState(false)

  useEffect(() => {
    fetchScenarios().then(setScenarios)
  }, [])

  // 情景切换 → 重新加载该情景的调度态势与推演帧，回到 T0 并复位演练
  useEffect(() => {
    let stale = false
    setPlaying(false)
    setFrameIndex(0)
    setLostHelperIds([])
    fetchSchedule(scenario).then((s) => {
      if (stale) return
      setBaseSchedule(s)
      setAlertLevel(s.alertLevel)
    })
    fetchFloodFrames(scenario).then((f) => {
      if (!stale) setFrames(f)
    })
    return () => {
      stale = true
    }
  }, [scenario])

  // 播放模式：1x 每 1.5s 一帧（推演 1 小时），4x 四倍速；到末帧自动停
  useEffect(() => {
    if (!playing || frames.length === 0) return
    const timer = window.setInterval(() => {
      setFrameIndex((i) => Math.min(i + 1, frames.length - 1))
    }, 1500 / playSpeed)
    return () => window.clearInterval(timer)
  }, [playing, playSpeed, frames.length])
  useEffect(() => {
    if (playing && frames.length > 0 && frameIndex >= frames.length - 1) setPlaying(false)
  }, [playing, frames.length, frameIndex])

  const currentFrame = useMemo(() => frames[frameIndex] ?? null, [frames, frameIndex])
  const nextFrame = useMemo(() => frames[frameIndex + 1] ?? null, [frames, frameIndex])

  /** 功能 D：当前推演时刻失效的避难所（场地被淹 ≥0.3m 或急流 v·d ≥0.5）。
   * 内容不变时复用上一次数组引用，避免每帧都触发整个派生态/
   * 优先级清单/地图数据源重建（扩容到 24 户后的播放流畅度关键） */
  const failedIdsRef = useRef<string[]>([])
  const failedShelterIds = useMemo(() => {
    if (!baseSchedule || !currentFrame) return NO_FAILED_SHELTERS
    const ids = baseSchedule.shelters
      .filter((s) =>
        pointInFlood([s.location.lng, s.location.lat], currentFrame.geojson, SHELTER_HAZARD),
      )
      .map((s) => s.id)
    if (ids.join(',') !== failedIdsRef.current.join(',')) failedIdsRef.current = ids
    return failedIdsRef.current
  }, [baseSchedule, currentFrame])

  const schedule = useMemo(
    () =>
      baseSchedule
        ? deriveSchedule(
            baseSchedule,
            lostHelperIds,
            alertLevel,
            failedShelterIds,
            currentFrame?.minute ?? null,
            nextFrame?.minute ?? null,
          )
        : null,
    [baseSchedule, lostHelperIds, alertLevel, failedShelterIds, currentFrame, nextFrame],
  )

  /** 第 8-2 项：失效非垂直避险所的整所转移（已入住人员 → 高地兜底所）。
   * 可行性按所内最弱画像阈值扫全帧序判转移路线失效时刻 */
  const activeTransfers = useMemo<ActiveTransfer[]>(() => {
    if (!schedule || !currentFrame || alertLevel !== 'dispatch') return []
    const out: ActiveTransfer[] = []
    for (const t of schedule.shelterTransfers ?? []) {
      if (!failedShelterIds.includes(t.fromShelterId)) continue
      const from = schedule.shelters.find((s) => s.id === t.fromShelterId)
      if (!from || from.verticalRefuge) continue // 垂直避险所原地上楼，不转移
      const occupants = schedule.evacuees.filter(
        (e) => e.shelterId === t.fromShelterId && e.matchStatus === 'evacuated',
      )
      if (occupants.length === 0) continue
      const weakest: Profile = occupants.some((e) => e.profile === 'wheelchair')
        ? 'wheelchair'
        : occupants.some((e) => e.profile === 'elderly')
          ? 'elderly'
          : 'blind'
      const failMin = routeFailureMinute(t.route, frames, hazardOf(weakest))
      out.push({
        ...t,
        count: occupants.length,
        feasible: failMin === null || failMin > currentFrame.minute,
      })
    }
    return out
  }, [schedule, frames, currentFrame, failedShelterIds, alertLevel])

  /** 无路可走清单（P0/P1 救助优先级），基于原始态势与全部推演帧 */
  const priorityList = useMemo(
    () => (schedule && frames.length > 0 ? buildPriorityList(schedule, frames) : []),
    [schedule, frames],
  )

  /** 数据看板统计 */
  const stats = useMemo(() => {
    const evs = schedule?.evacuees ?? []
    return {
      evacuated: evs.filter((e) => e.matchStatus === 'evacuated').length,
      enRoute: evs.filter(
        (e) =>
          e.matchStatus === 'en_route' ||
          e.matchStatus === 'escorting' ||
          e.matchStatus === 'arrived',
      ).length,
      unmatched: evs.filter((e) => e.matchStatus === 'unmatched').length,
      lost: lostHelperIds.length,
    }
  }, [schedule, lostHelperIds])

  /** 补位演练：标记选中人员的主帮扶失联 → 备份自动升级 */
  const simulateLost = (helperId: string) => {
    setLostHelperIds((ids) => (ids.includes(helperId) ? ids : [...ids, helperId]))
    setDrillStamp(Date.now())
  }
  const resetDrill = () => setLostHelperIds([])

  /** 拖动时间轴即暂停播放（功能 A 交互约定） */
  const handleFrameChange = (index: number) => {
    setPlaying(false)
    setFrameIndex(index)
  }

  /** 第十四节第 5 项：非出动档推进时间轴时，「出动」按钮脉冲引导
   * （撤离推演/移动小点仅出动档生效，可发现性修复） */
  const dispatchHint = alertLevel !== 'dispatch' && frameIndex > 0

  return (
    <div className="flex h-full flex-col bg-gray-100">
      {/* 窄屏止血横幅（二期决策 2）：仅 <768px 可见，作战板为指挥端设计 */}
      {!mobileNoticeClosed && (
        <div className="flex items-center gap-2 bg-amber-100 px-3 py-1.5 text-xs text-amber-800 md:hidden">
          <span className="min-w-0 flex-1">
            💻 本作战板为指挥端设计，建议桌面端访问获得完整体验
          </span>
          <button
            type="button"
            onClick={() => setMobileNoticeClosed(true)}
            className="flex-none rounded px-1.5 py-0.5 font-semibold text-amber-700 hover:bg-amber-200"
            aria-label="关闭提示"
          >
            ✕
          </button>
        </div>
      )}
      <TopBar
        alertLevel={alertLevel}
        onAlertChange={setAlertLevel}
        stats={stats}
        drillActive={lostHelperIds.length > 0}
        onResetDrill={resetDrill}
        frames={frames}
        frameIndex={frameIndex}
        onFrameChange={handleFrameChange}
        scenarios={scenarios}
        scenario={scenario}
        onScenarioChange={setScenario}
        playing={playing}
        playSpeed={playSpeed}
        onTogglePlay={() => {
          // 已到末帧再按播放 → 从头开始
          if (!playing && frameIndex >= frames.length - 1) setFrameIndex(0)
          setPlaying((p) => !p)
        }}
        onSpeedChange={setPlaySpeed}
        briefingsOpen={briefingsOpen}
        onToggleBriefings={() => setBriefingsOpen((v) => !v)}
        dispatchHint={dispatchHint}
      />
      <div className="flex min-h-0 flex-1">
        <EvacueeList
          evacuees={schedule?.evacuees ?? []}
          selectedId={selectedEvacueeId}
          onSelect={setSelectedEvacueeId}
          priorityList={priorityList}
          simNow={currentFrame?.clock ?? null}
          shelters={schedule?.shelters ?? []}
          failedShelterIds={failedShelterIds}
          assignments={schedule?.assignments ?? []}
          frames={frames}
        />
        <main className="relative min-w-0 flex-1">
          <MapView
            schedule={schedule}
            frame={currentFrame}
            nextFrame={nextFrame}
            failedShelterIds={failedShelterIds}
            selectedEvacueeId={selectedEvacueeId}
            onSelectEvacuee={setSelectedEvacueeId}
            onSimulateLost={simulateLost}
            drillStamp={drillStamp}
            scenario={scenario}
            activeTransfers={activeTransfers}
          />
          {/* AI 派单简报抽屉：覆盖地图右侧，按当前情景生成 */}
          <BriefingPanel
            open={briefingsOpen}
            onClose={() => setBriefingsOpen(false)}
            scenario={scenario}
            schedule={schedule}
          />
        </main>
      </div>
    </div>
  )
}
