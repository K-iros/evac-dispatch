import { useMemo } from 'react'
import type { Assignment, Evacuee, FloodFrame } from '../types'
import { hazardOf, pointInFlood, simLabel, simMinute } from './routeUtils'

/**
 * 最迟出发时间倒推链气泡（第十五节第 1 项：可解释性白箱）。
 * 数据源为后端 departure.latest_departure_steps 透出的逐段中间量
 * （倒推序：从避难所反向递推 latest = min(latest, fail) − dur），
 * 此处聚合为可读时间线：连续可通行段合并为一条"步行 X 分钟"，
 * 被淹没收紧的段单独成条（⚠ 途中路段 HH:MM 起不可通行）。
 */

/** 聚合后的展示条目 */
type ChainItem =
  | { kind: 'clamp'; failMin: number }
  | { kind: 'walk'; phase: 'pickup' | 'escort'; count: number; dur: number; latestAfter: number }

/** 倒推链聚合：steps 为倒推序（[0] = 路径末段，紧邻避难所） */
function aggregate(steps: NonNullable<Assignment['deriveSteps']>): ChainItem[] {
  const items: ChainItem[] = []
  let acc: { phase: 'pickup' | 'escort'; count: number; dur: number; latestAfter: number } | null =
    null
  const flush = () => {
    if (acc) items.push({ kind: 'walk', ...acc })
    acc = null
  }
  for (const s of steps) {
    if (s.clamped && s.failMinute !== null) {
      flush()
      items.push({ kind: 'clamp', failMin: s.failMinute })
    }
    if (acc && acc.phase !== s.phase) flush()
    if (!acc) acc = { phase: s.phase, count: 0, dur: 0, latestAfter: s.latestAfter }
    acc.count += 1
    acc.dur += s.durationMin
    acc.latestAfter = s.latestAfter
  }
  flush()
  return items
}

const PHASE_META: Record<'pickup' | 'escort', { icon: string; label: string }> = {
  escort: { icon: '🚶', label: '护送段' },
  pickup: { icon: '🏃', label: '接人段' },
}

interface Props {
  evacuee: Evacuee
  /** 该户主派任务（未匹配/无路线时为空 → 走住址淹没兜底解释） */
  assignment: Assignment | null
  frames: FloodFrame[]
}

/** 名单行点击"最迟出发时间"展开的倒推时间线 */
export default function DeriveChain({ evacuee, assignment, frames }: Props) {
  const steps = assignment?.deriveSteps
  const horizon = frames.length > 0 ? frames[frames.length - 1].minute : 1440

  const items = useMemo(() => (steps && steps.length > 0 ? aggregate(steps) : []), [steps])

  /** 无路线兜底：扫帧找住址首次达到画像危险阈值的时刻（与后端
   * point_flooded_minute 同口径），最迟离家 = 该时刻 − 30 分钟缓冲 */
  const floodedMin = useMemo(() => {
    if (steps && steps.length > 0) return null
    const thr = hazardOf(evacuee.profile)
    const pt: [number, number] = [evacuee.location.lng, evacuee.location.lat]
    for (const f of frames) {
      if (pointInFlood(pt, f.geojson, thr)) return f.minute
    }
    return null
  }, [steps, evacuee, frames])

  return (
    <div className="border-b border-sky-100 bg-sky-50/60 px-4 py-2.5 text-[11px] leading-relaxed">
      <p className="mb-1 font-bold text-sky-800">🧮 最迟出发怎么算的（从避难所倒推）</p>
      {items.length > 0 ? (
        <ol className="space-y-1 border-l-2 border-sky-200 pl-2.5">
          <li className="text-gray-500">推演期末 {simLabel(horizon)} 为初始上限</li>
          {items.map((it, i) =>
            it.kind === 'clamp' ? (
              <li key={i} className="font-semibold text-amber-700">
                ⚠ 途中路段 {simLabel(it.failMin)} 起不可通行 → 上限收紧
              </li>
            ) : (
              <li key={i} className="text-gray-700">
                {PHASE_META[it.phase].icon} {PHASE_META[it.phase].label}
                {it.count > 1 ? ` ×${it.count}` : ''} · 步行 {Math.max(1, Math.round(it.dur))} 分
                → 最迟 {simLabel(it.latestAfter)}
              </li>
            ),
          )}
          {assignment?.departBy ? (
            <>
              <li className="font-bold text-sky-800">
                ⏱ 帮扶者最迟出发 {simLabel(simMinute(assignment.departBy))}
              </li>
              <li className="font-bold text-sky-800">
                🏠 户最迟离家 {simLabel(simMinute(evacuee.latestDeparture))}（出发 + 接人段）
              </li>
            </>
          ) : (
            <li className="font-bold text-red-600">⛔ 倒推为负：全程无可行时间窗</li>
          )}
          {assignment && (assignment.sequence ?? 1) >= 2 && assignment.earliestStart && (
            <li className={assignment.conflict ? 'font-bold text-red-600' : 'text-violet-700'}>
              {assignment.conflict ? '🔴' : '🔗'} 串行链第 {assignment.sequence} 单：前序送达后最早{' '}
              {simLabel(simMinute(assignment.earliestStart))} 才能开始
              {assignment.conflict ? ' → 晚于最迟出发，排班不可行' : ''}
            </li>
          )}
        </ol>
      ) : (
        <p className="text-gray-700">
          该户当前无可行路线，改按住址淹没时刻兜底：
          {floodedMin !== null
            ? `住址约 ${simLabel(floodedMin)} 达到危险阈值，倒扣 30 分钟撤离缓冲 → 最迟 ${simLabel(
                simMinute(evacuee.latestDeparture),
              )}`
            : `推演期内住址未达危险阈值，取期末兜底 → 最迟 ${simLabel(
                simMinute(evacuee.latestDeparture),
              )}`}
        </p>
      )}
    </div>
  )
}
