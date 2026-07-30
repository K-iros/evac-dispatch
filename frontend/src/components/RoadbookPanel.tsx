import { useEffect, useRef, useState } from 'react'
import type { Evacuee, RoadbookResponse, ScheduleState } from '../types'
import { fetchRoadbook } from '../api/client'
import { ESCORT_SPEED, haversine, splitIndexAt } from './routeUtils'

/**
 * 语音路书面板（第十二节 P1）：盲人画像路径 → 自然语言路书 → TTS 播报。
 * demo「评委闭眼听 30 秒」：选中盲人户 → 🔊 播报整段陪同导引口语路书。
 * 后端 /api/roadbook 生成（DeepSeek 润色 source='llm' / 规则模板
 * source='template'）；后端离线时前端按同口径本地模板兜底，演示永不空白。
 */

/** 转向判定阈值（度），与 backend/app/services/roadbook.py 同口径 */
const SLIGHT_TURN_DEG = 30
const SHARP_TURN_DEG = 60
const COMPASS = ['北', '东北', '东', '东南', '南', '西南', '西', '西北']
const COS_LAT = Math.cos((24.78 * Math.PI) / 180)

/** 方位角（度，0=正北顺时针） */
function bearingDeg(a: [number, number], b: [number, number]): number {
  const dx = (b[0] - a[0]) * COS_LAT
  const dy = b[1] - a[1]
  return ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360
}

/** 两段间的转向词；直行返回 null */
function turnWord(prev: number, cur: number): string | null {
  const delta = ((cur - prev + 540) % 360) - 180 // (-180, 180]，正=右转
  if (Math.abs(delta) <= SLIGHT_TURN_DEG) return null
  const side = delta > 0 ? '右' : '左'
  return Math.abs(delta) > SHARP_TURN_DEG ? `${side}转` : `稍向${side}`
}

const roundM = (m: number) => Math.max(Math.round(m / 10) * 10, 10)

/** 护送段折线 → 转向步骤清单（合并连续直行段，与后端同口径） */
function buildSteps(escort: [number, number][]): string[] {
  if (escort.length < 2) return []
  const steps: string[] = []
  let acc = haversine(escort[0], escort[1])
  let prevBearing = bearingDeg(escort[0], escort[1])
  let lead = `沿${COMPASS[Math.round(prevBearing / 45) % 8]}方向出发，直行约`
  for (let i = 1; i < escort.length - 1; i++) {
    const bearing = bearingDeg(escort[i], escort[i + 1])
    const seg = haversine(escort[i], escort[i + 1])
    const turn = turnWord(prevBearing, bearing)
    if (turn === null) {
      acc += seg
    } else {
      steps.push(`${lead} ${roundM(acc)} 米`)
      lead = `${turn}，继续直行约`
      acc = seg
    }
    prevBearing = bearing
  }
  steps.push(`${lead} ${roundM(acc)} 米`)
  return steps
}

/** 本地模板兜底：与 backend/app/services/roadbook.py _template_text 同口径 */
function buildLocalRoadbook(
  evacuee: Evacuee,
  schedule: ScheduleState,
): RoadbookResponse | null {
  const primary = schedule.assignments.find(
    (a) => a.evacueeId === evacuee.id && !a.isBackup && !a.isFallback,
  )
  if (!primary || primary.route.length < 2) return null
  const helperName = schedule.helpers.find((h) => h.id === primary.helperId)?.name ?? null
  const shelterName = schedule.shelters.find((s) => s.id === primary.shelterId)?.name ?? null

  const home: [number, number] = [evacuee.location.lng, evacuee.location.lat]
  const escort = primary.route.slice(splitIndexAt(primary.route, home))
  let distM = 0
  for (let i = 0; i < escort.length - 1; i++) distM += haversine(escort[i], escort[i + 1])
  const steps = buildSteps(escort)
  const distanceKm = Math.round((distM / 1000) * 100) / 100
  const durationMin = Math.max(Math.round(distM / ESCORT_SPEED[evacuee.profile] / 60), 1)

  const text =
    `${evacuee.name}您好，我是${helperName ?? '帮扶者'}。我们现在从家出发，` +
    `前往${shelterName ?? '避难所'}，全程约${distanceKm}公里，` +
    `步行大约${durationMin}分钟，请抓稳我的手臂，跟着我的口令走。` +
    steps.map((s, i) => `${i + 1}. ${s}。`).join('') +
    `到达${shelterName ?? '避难所'}后请在登记处稍作休息，全程有我陪同，请放心。`
  return {
    evacueeId: evacuee.id,
    evacueeName: evacuee.name,
    helperName,
    shelterName,
    source: 'template',
    text,
    steps,
    distanceKm,
    durationMin,
  }
}

interface Props {
  evacuee: Evacuee
  scenario: string
  schedule: ScheduleState | null
  onClose: () => void
}

/** 路径卡上方的路书卡片：文字路书 + 🔊 TTS 播报/停止 */
export default function RoadbookPanel({ evacuee, scenario, schedule, onClose }: Props) {
  const [data, setData] = useState<RoadbookResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [speaking, setSpeaking] = useState(false)
  const utterRef = useRef<SpeechSynthesisUtterance | null>(null)

  useEffect(() => {
    let stale = false
    setLoading(true)
    setData(null)
    fetchRoadbook(scenario, evacuee.id).then((res) => {
      if (stale) return
      // 后端离线/404 → 本地模板兜底（与后端模板同口径）
      setData(res ?? (schedule ? buildLocalRoadbook(evacuee, schedule) : null))
      setLoading(false)
    })
    return () => {
      stale = true
    }
    // 换户/换情景重新加载；schedule 引用变化不重复请求
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, evacuee.id])

  // 卸载/关闭时停止播报
  useEffect(() => {
    return () => {
      window.speechSynthesis?.cancel()
    }
  }, [])

  const toggleSpeak = () => {
    const synth = window.speechSynthesis
    if (!synth || !data) return
    if (speaking) {
      synth.cancel()
      setSpeaking(false)
      return
    }
    const utter = new SpeechSynthesisUtterance(data.text)
    utter.lang = 'zh-CN'
    utter.rate = 0.95
    utter.onend = () => setSpeaking(false)
    utter.onerror = () => setSpeaking(false)
    utterRef.current = utter // 防止 GC 提前回收导致 onend 不触发
    synth.cancel()
    synth.speak(utter)
    setSpeaking(true)
  }

  return (
    <div className="absolute bottom-3 left-[21.5rem] z-10 flex max-h-[70%] w-96 flex-col rounded-xl bg-white/95 shadow-lg backdrop-blur">
      <div className="flex items-center gap-2 border-b border-gray-100 px-4 py-3">
        <span className="text-sm font-bold text-gray-900">🦯 语音路书</span>
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
          <div className="py-8 text-center text-xs text-gray-400">正在生成语音路书…</div>
        )}
        {!loading && !data && (
          <div className="py-8 text-center text-xs text-gray-400">
            该户暂无主路线，无法生成路书
          </div>
        )}
        {!loading && data && (
          <>
            <div className="text-[11px] text-gray-400">
              {data.evacueeName} → {data.shelterName ?? '避难所'} · 约 {data.distanceKm} 公里
              · 护送约 {data.durationMin} 分钟
            </div>
            <button
              type="button"
              onClick={toggleSpeak}
              className={`mt-2 w-full rounded-lg px-3 py-2 text-xs font-bold transition-colors ${
                speaking
                  ? 'bg-red-50 text-red-600 hover:bg-red-100'
                  : 'bg-violet-600 text-white hover:bg-violet-700'
              }`}
            >
              {speaking ? '⏹ 停止播报' : '🔊 播报路书（约 30 秒，请闭眼聆听）'}
            </button>
            <p className="mt-3 rounded-lg bg-gray-50 p-3 text-xs leading-5 text-gray-700">
              {data.text}
            </p>
            {data.steps.length > 0 && (
              <ol className="mt-3 space-y-1 text-[11px] leading-4 text-gray-500">
                {data.steps.map((s, i) => (
                  <li key={i}>
                    {i + 1}. {s}
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div>

      <div className="border-t border-gray-100 px-4 py-2 text-[11px] leading-4 text-gray-400">
        盲人画像路径 → 自然语言路书 → TTS 播报 · 水情提醒来自水动力推演
      </div>
    </div>
  )
}
