import { useEffect, useState } from 'react'
import type { BriefingsResponse, ScheduleState } from '../types'
import { fetchBriefings } from '../api/client'

/**
 * AI 派单简报抽屉（第十二节 P0）：每位帮扶者一句话任务卡。
 * 后端 /api/briefings 一次 DeepSeek 调用生成全部（source='llm'），
 * 无 Key/失败时后端规则模板兜底（source='template'）；后端整体
 * 离线时前端用同口径本地模板兜底，演示永不空白。
 */

const PROFILE_LABEL: Record<string, string> = {
  wheelchair: '轮椅',
  blind: '视障',
  elderly: '高龄',
}
const PROFILE_NOTE: Record<string, string> = {
  wheelchair: '全程走无障碍绕行路线，避开台阶陡坎',
  blind: '全程牵引陪同，提前口述路况',
  elderly: '放慢步速，随身带常用药品',
}

/** ISO 模拟时钟 → HH:MM */
const hhmm = (iso: string) => (iso.length >= 16 ? iso.slice(11, 16) : iso)

/** 本地模板兜底：与 backend/app/services/briefing.py 同口径 */
function buildLocalBriefings(schedule: ScheduleState): BriefingsResponse {
  const evById = new Map(schedule.evacuees.map((e) => [e.id, e]))
  const shelterById = new Map(schedule.shelters.map((s) => [s.id, s]))
  const items = schedule.helpers
    .filter((h) => h.available)
    .map((h) => {
      const own = schedule.assignments.filter((a) => a.helperId === h.id && !a.isFallback)
      const parts = own
        .filter((a) => !a.isBackup)
        .sort((a, b) => (a.sequence ?? 1) - (b.sequence ?? 1))
        .flatMap((a, i) => {
          const ev = evById.get(a.evacueeId)
          if (!ev) return []
          const shelter = shelterById.get(a.shelterId)?.name ?? a.shelterId
          // 串行第 2+ 单不报独立时刻（与后端模板同口径）
          if (i > 0) {
            return [
              `送达后转接${ev.name}（${PROFILE_LABEL[ev.profile]}，${ev.address}），` +
                `护送至${shelter}；${PROFILE_NOTE[ev.profile]}`,
            ]
          }
          return [
            `${hhmm(ev.latestDeparture)}前出发接${ev.name}（${PROFILE_LABEL[ev.profile]}，${ev.address}），` +
              `${hhmm(a.arriveBy)}前送达${shelter}；${PROFILE_NOTE[ev.profile]}`,
          ]
        })
      const backupCount = own.filter((a) => a.isBackup).length
      let text: string
      if (parts.length === 0) {
        text = '机动备份：主帮扶失联时立即接替，保持通讯畅通。'
      } else {
        text = `${parts.join('。')}。`
        if (backupCount > 0) text += `另兼${backupCount}户备份，留意补位通知。`
      }
      return { helperId: h.id, helperName: h.name, text }
    })
  return { source: 'template', items }
}

interface Props {
  open: boolean
  onClose: () => void
  scenario: string
  schedule: ScheduleState | null
}

/** 右侧抽屉：任务卡列表 + 来源徽章（LLM / 模板） */
export default function BriefingPanel({ open, onClose, scenario, schedule }: Props) {
  const [data, setData] = useState<BriefingsResponse | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    let stale = false
    setLoading(true)
    setData(null)
    fetchBriefings(scenario).then((res) => {
      if (stale) return
      // 后端离线 → 本地模板兜底（与后端模板同口径）
      setData(res ?? (schedule ? buildLocalBriefings(schedule) : null))
      setLoading(false)
    })
    return () => {
      stale = true
    }
    // 打开时按当前情景加载一次；schedule 变化不重复请求
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scenario])

  if (!open) return null

  return (
    <div className="absolute inset-y-0 right-0 z-20 flex w-96 flex-col border-l border-gray-200 bg-white shadow-2xl">
      <div className="flex items-center gap-2 border-b border-gray-100 px-4 py-3">
        <span className="text-sm font-bold text-gray-900">🤖 AI 派单简报</span>
        {data && (
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${
              data.source === 'llm'
                ? 'bg-violet-100 text-violet-700'
                : 'bg-gray-100 text-gray-500'
            }`}
          >
            {data.source === 'llm' ? 'DeepSeek 生成' : '规则模板'}
          </span>
        )}
        <button
          type="button"
          onClick={onClose}
          className="ml-auto rounded-full px-2 py-0.5 text-sm text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          ✕
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {loading && (
          <div className="py-10 text-center text-xs text-gray-400">正在生成任务简报…</div>
        )}
        {!loading && !data && (
          <div className="py-10 text-center text-xs text-gray-400">暂无简报数据</div>
        )}
        {!loading &&
          data?.items.map((b) => (
            <div
              key={b.helperId}
              className="mb-2.5 rounded-xl border border-gray-100 bg-gray-50/70 p-3"
            >
              <div className="text-xs font-bold text-gray-900">🤝 {b.helperName}</div>
              <p className="mt-1 text-xs leading-5 text-gray-600">{b.text}</p>
            </div>
          ))}
      </div>

      <div className="border-t border-gray-100 px-4 py-2 text-[11px] leading-4 text-gray-400">
        一句话任务卡：接谁 / 几点前出发·送达 / 去哪 / 注意什么。
        {data?.source === 'template' && ' 配置 DEEPSEEK_API_KEY 后由 LLM 生成。'}
      </div>
    </div>
  )
}
