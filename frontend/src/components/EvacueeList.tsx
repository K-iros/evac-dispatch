import { useState } from 'react'
import type { Assignment, Evacuee, FloodFrame, MatchStatus, Profile, Shelter } from '../types'
import DeriveChain from './DeriveChain'
import { exportPriorityCsv, type PriorityEntry } from './routeUtils'

const PROFILE_LABEL: Record<Profile, string> = {
  wheelchair: '♿ 轮椅',
  blind: '🦯 盲人',
  elderly: '🧓 老人',
}

const STATUS_META: Record<MatchStatus, { label: string; cls: string }> = {
  unmatched: { label: '未匹配', cls: 'bg-red-100 text-red-700' },
  matched: { label: '已匹配', cls: 'bg-blue-100 text-blue-700' },
  en_route: { label: '在途', cls: 'bg-amber-100 text-amber-700' },
  escorting: { label: '护送中', cls: 'bg-orange-100 text-orange-700' },
  arrived: { label: '已到场', cls: 'bg-emerald-100 text-emerald-700' },
  evacuated: { label: '已撤离', cls: 'bg-gray-200 text-gray-500' },
}

/** 倒计时文案：相对当前推演时刻（模拟时钟）距最迟出发时间；
 * 剩余不足 1 小时或已超时视为紧迫。simNow 为当前帧 clock，
 * 与时间轴/最迟出发时间同一坐标系（避免“时间轴已变红、
 * 倒计时仍充裕”的自相矛盾） */
function countdown(iso: string, simNow: string | null): { text: string; urgent: boolean } {
  const now = simNow ? new Date(simNow).getTime() : Date.now()
  const diffMs = new Date(iso).getTime() - now
  const abs = Math.abs(diffMs)
  const h = Math.floor(abs / 3_600_000)
  const m = Math.floor((abs % 3_600_000) / 60_000)
  const text = diffMs >= 0 ? `剩 ${h} 时 ${m} 分` : `已超 ${h} 时 ${m} 分`
  return { text, urgent: diffMs < 3_600_000 }
}

/** 第十四节第 4 项：倒计时按状态收敛——已撤离不再对最迟出发时间
 * 倒计时（人已安置，「已超 X 时」语义荒谬）；所失效时提示待转移
 * （与第 8-2 项整所转移联动）；护送/接人途中显示行进状态 */
function statusText(
  e: Evacuee,
  shelters: Shelter[],
  failedShelterIds: string[],
  simNow: string | null,
): { text: string; cls: string } {
  if (e.matchStatus === 'evacuated') {
    const sh = shelters.find((s) => s.id === e.shelterId)
    if (sh && failedShelterIds.includes(sh.id)) {
      // 垂直避险所原地上楼，非垂直所等待整所转移（第 8-2 项）
      return sh.verticalRefuge
        ? { text: '⚠ 场地进水 · 垂直避险', cls: 'font-bold text-amber-600' }
        : { text: '⚠ 避难点失效 · 待转移', cls: 'font-bold text-red-600' }
    }
    return { text: `已安置 · ${sh?.name ?? '避难点'}`, cls: 'text-emerald-600' }
  }
  if (e.matchStatus === 'escorting') return { text: '护送中', cls: 'text-orange-600' }
  const cd = countdown(e.latestDeparture, simNow)
  return { text: cd.text, cls: cd.urgent ? 'font-bold text-red-600' : 'text-gray-600' }
}

interface Props {
  evacuees: Evacuee[]
  selectedId: string | null
  onSelect: (id: string) => void
  /** 无路可走 · 救助优先级清单（P0/P1） */
  priorityList: PriorityEntry[]
  /** 当前推演帧的模拟时钟（倒计时基准） */
  simNow: string | null
  /** 避难所列表 + 当前失效所（第十四节第 4 项：已安置/待转移文案） */
  shelters: Shelter[]
  failedShelterIds: string[]
  /** 倒推链数据源（第十五节）：主派任务 deriveSteps + 帧序兜底扫描 */
  assignments: Assignment[]
  frames: FloodFrame[]
}

/** 左侧：按最迟出发时间倒计时排序的待撤离名单 + 无路可走清单 */
export default function EvacueeList({
  evacuees,
  selectedId,
  onSelect,
  priorityList,
  simNow,
  shelters,
  failedShelterIds,
  assignments,
  frames,
}: Props) {
  // 倒推链展开户（点击最迟出发时间切换，一次只展开一户）
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const sorted = [...evacuees].sort(
    (a, b) => new Date(a.latestDeparture).getTime() - new Date(b.latestDeparture).getTime(),
  )

  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <h2 className="text-sm font-bold text-gray-900">待撤离名单</h2>
        <span className="text-xs text-gray-500">共 {evacuees.length} 人</span>
      </div>

      <ul className="flex-1 overflow-y-auto">
        {sorted.map((e) => {
          const status = STATUS_META[e.matchStatus]
          const st = statusText(e, shelters, failedShelterIds, simNow)
          const selected = e.id === selectedId
          return (
            <li key={e.id}>
              <button
                type="button"
                onClick={() => onSelect(e.id)}
                className={`w-full border-b border-gray-100 px-4 py-3 text-left transition-colors ${
                  selected ? 'bg-sky-50' : 'hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-gray-900">{e.name}</span>
                  <span className="text-xs text-gray-500">{PROFILE_LABEL[e.profile]}</span>
                  <span className={`ml-auto rounded-full px-2 py-0.5 text-xs ${status.cls}`}>
                    {status.label}
                  </span>
                </div>
                <div className="mt-1 truncate text-xs text-gray-500">{e.address}</div>
                <div className="mt-1 flex items-center justify-between text-xs">
                  <span className="text-gray-400">帮扶 {e.helperIds.length} 人</span>
                  {/* 点击展开倒推链（第十五节）：行本身是 button，
                      用 span+stopPropagation 避免嵌套交互元素 */}
                  <span
                    role="button"
                    tabIndex={0}
                    title="点击查看最迟出发时间怎么算的"
                    onClick={(ev) => {
                      ev.stopPropagation()
                      setExpandedId((id) => (id === e.id ? null : e.id))
                    }}
                    onKeyDown={(ev) => {
                      if (ev.key === 'Enter' || ev.key === ' ') {
                        ev.stopPropagation()
                        setExpandedId((id) => (id === e.id ? null : e.id))
                      }
                    }}
                    className={`truncate pl-2 text-right underline decoration-dotted underline-offset-2 hover:decoration-solid ${st.cls}`}
                  >
                    {st.text} {expandedId === e.id ? '▴' : '▾'}
                  </span>
                </div>
              </button>
              {expandedId === e.id && (
                <DeriveChain
                  evacuee={e}
                  assignment={
                    assignments.find(
                      (a) => a.evacueeId === e.id && !a.isBackup && !a.isFallback,
                    ) ?? null
                  }
                  frames={frames}
                />
              )}
            </li>
          )
        })}
      </ul>

      {/* 无路可走清单：任何情景下都无可行路线的人员，可导出救助优先级清单 */}
      <section className="shrink-0 border-t-2 border-red-100 bg-red-50/40">
        <div className="flex items-center justify-between px-4 py-2">
          <h3 className="text-xs font-bold text-red-700">
            ⚠ 无路可走 · 救助优先级（{priorityList.length}）
          </h3>
          <button
            type="button"
            disabled={priorityList.length === 0}
            onClick={() => exportPriorityCsv(priorityList)}
            className="rounded border border-red-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            ⤓ 导出清单
          </button>
        </div>
        {priorityList.length === 0 ? (
          <p className="px-4 pb-3 text-[11px] text-gray-400">当前推演情景下所有人员均有可行路线</p>
        ) : (
          <ul className="max-h-40 overflow-y-auto pb-2">
            {priorityList.map((p) => (
              <li key={p.evacueeId}>
                <button
                  type="button"
                  onClick={() => onSelect(p.evacueeId)}
                  className="w-full px-4 py-1.5 text-left hover:bg-red-50"
                >
                  <div className="flex items-center gap-2 text-xs">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                        p.tier === 'P0' ? 'bg-red-600 text-white' : 'bg-amber-500 text-white'
                      }`}
                    >
                      {p.tier}
                    </span>
                    <span className="font-semibold text-gray-900">{p.name}</span>
                    <span className="text-gray-500">{PROFILE_LABEL[p.profile]}</span>
                  </div>
                  <p className="mt-0.5 text-[11px] text-red-700">{p.reason}</p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  )
}
