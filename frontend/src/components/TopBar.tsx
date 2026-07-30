import type { AlertLevel, FloodFrame, Scenario } from '../types'

const ALERT_META: Record<AlertLevel, { label: string; activeCls: string }> = {
  standby: { label: '预备', activeCls: 'bg-gray-600 text-white' },
  ready: { label: '待命', activeCls: 'bg-amber-500 text-white' },
  dispatch: { label: '出动', activeCls: 'bg-red-600 text-white' },
}

const ALERT_ORDER: AlertLevel[] = ['standby', 'ready', 'dispatch']

export interface BoardStats {
  evacuated: number
  enRoute: number
  unmatched: number
  lost: number
}

/** 模拟时钟 ISO → "06-19 14:00" 展示 */
function clockLabel(iso: string): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

interface Props {
  alertLevel: AlertLevel
  onAlertChange: (level: AlertLevel) => void
  stats: BoardStats
  drillActive: boolean
  onResetDrill: () => void
  frames: FloodFrame[]
  frameIndex: number
  onFrameChange: (index: number) => void
  /** 情景预设（功能 C） */
  scenarios: Scenario[]
  scenario: string
  onScenarioChange: (key: string) => void
  /** 播放模式（功能 A）：▶暂停/播放 + 1x/4x 倍速 */
  playing: boolean
  playSpeed: 1 | 4
  onTogglePlay: () => void
  onSpeedChange: (speed: 1 | 4) => void
  /** AI 派单简报抽屉开关 */
  briefingsOpen: boolean
  onToggleBriefings: () => void
  /** 第十四节第 5 项：非出动档推进时间轴 →「出动」按钮脉冲引导 */
  dispatchHint: boolean
}

/** 顶部：标题栏 + 分级响应三档切换 + 数据看板 + 情景预设 + 淹没推演时间轴 */
export default function TopBar({
  alertLevel,
  onAlertChange,
  stats,
  drillActive,
  onResetDrill,
  frames,
  frameIndex,
  onFrameChange,
  scenarios,
  scenario,
  onScenarioChange,
  playing,
  playSpeed,
  onTogglePlay,
  onSpeedChange,
  briefingsOpen,
  onToggleBriefings,
  dispatchHint,
}: Props) {
  const current = frames[frameIndex]

  return (
    <header className="flex items-center gap-4 border-b border-gray-200 bg-white px-4 py-2">
      <div className="flex items-center gap-3">
        <h1 className="shrink-0 text-base font-bold text-gray-900">灾前疏散调度作战板</h1>

        {/* 分级响应三档切换（防"狼来了"：预备→待命→出动） */}
        <div className="flex items-center gap-1 rounded-full bg-gray-100 p-0.5">
          {ALERT_ORDER.map((level) => (
            <button
              key={level}
              type="button"
              onClick={() => onAlertChange(level)}
              className={`rounded-full px-3 py-0.5 text-sm font-semibold transition-colors ${
                alertLevel === level
                  ? ALERT_META[level].activeCls
                  : 'text-gray-500 hover:bg-gray-200'
              } ${
                // 第十四节第 5 项：非出动档推演时「出动」脉冲提示
                level === 'dispatch' && dispatchHint
                  ? 'animate-pulse ring-2 ring-red-400 ring-offset-1'
                  : ''
              }`}
            >
              {ALERT_META[level].label}
            </button>
          ))}
        </div>
        {dispatchHint && (
          <span className="shrink-0 animate-pulse text-[11px] font-semibold text-red-600">
            ← 切「出动」档查看撤离推演
          </span>
        )}
      </div>

      {/* 数据看板：已撤离 / 在途 / 未匹配 / 失联 */}
      <div className="flex shrink-0 items-center gap-1.5 text-xs">
        <StatChip label="已撤离" value={stats.evacuated} cls="bg-gray-100 text-gray-600" />
        <StatChip label="在途" value={stats.enRoute} cls="bg-amber-50 text-amber-700" />
        <StatChip
          label="未匹配"
          value={stats.unmatched}
          cls={stats.unmatched > 0 ? 'bg-red-50 text-red-700' : 'bg-gray-100 text-gray-600'}
        />
        <StatChip
          label="失联"
          value={stats.lost}
          cls={stats.lost > 0 ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'}
        />
        {drillActive && (
          <button
            type="button"
            onClick={onResetDrill}
            className="ml-1 rounded-full border border-red-200 bg-white px-2.5 py-0.5 font-semibold text-red-600 hover:bg-red-50"
          >
            ↺ 重置演练
          </button>
        )}
      </div>

      {/* 情景预设（功能 C）：切换后重新加载该情景的推演帧与调度态势 */}
      <select
        value={scenario}
        onChange={(e) => onScenarioChange(e.target.value)}
        className="shrink-0 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs font-semibold text-gray-700 outline-none hover:border-sky-400"
        title="情景预设"
      >
        {scenarios.map((s) => (
          <option key={s.key} value={s.key}>
            {s.name}
          </option>
        ))}
      </select>

      {/* AI 派单简报（第十二节 P0）：每位帮扶者一句话任务卡 */}
      <button
        type="button"
        onClick={onToggleBriefings}
        className={`shrink-0 rounded-lg px-2.5 py-1 text-xs font-semibold transition-colors ${
          briefingsOpen
            ? 'bg-violet-600 text-white'
            : 'border border-gray-200 bg-white text-gray-700 hover:border-violet-400'
        }`}
      >
        🤖 AI 简报
      </button>

      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        {/* 播放模式（功能 A）：▶/⏸ + 倍速；拖动时间轴即暂停 */}
        <button
          type="button"
          onClick={onTogglePlay}
          className={`shrink-0 rounded-full px-2.5 py-0.5 text-sm font-bold transition-colors ${
            playing ? 'bg-sky-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
          title={playing ? '暂停' : '播放 24h 推演'}
        >
          {playing ? '⏸' : '▶'}
        </button>
        <div className="flex shrink-0 items-center overflow-hidden rounded-full bg-gray-100 text-[11px] font-semibold">
          {([1, 4] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onSpeedChange(s)}
              className={`px-2 py-0.5 ${
                playSpeed === s ? 'bg-sky-600 text-white' : 'text-gray-500 hover:bg-gray-200'
              }`}
            >
              {s}x
            </button>
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={Math.max(frames.length - 1, 0)}
          step={1}
          value={frameIndex}
          onChange={(e) => onFrameChange(Number(e.target.value))}
          className="w-full max-w-md accent-sky-600"
        />
        {current && (
          <span className="shrink-0 text-sm text-gray-700">
            {/* 模拟时钟标签 + 阳朔站绝对水位（模型修正一的口径） */}
            <span className="font-semibold text-gray-900">
              {current.clock ? clockLabel(current.clock) : `+${current.minute} 分钟`}
            </span>
            {current.stageM !== undefined && (
              <>
                {' · '}
                <span className="font-semibold text-sky-700">
                  阳朔站 {current.stageM.toFixed(1)}m
                </span>
                {current.warnM !== undefined && (
                  <span
                    className={`ml-1 rounded px-1 py-0.5 text-[11px] font-bold ${
                      current.warnM >= 0 ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-500'
                    }`}
                  >
                    {current.warnM >= 0
                      ? `超警 +${current.warnM.toFixed(1)}m`
                      : `低于警戒 ${Math.abs(current.warnM).toFixed(1)}m`}
                  </span>
                )}
              </>
            )}
          </span>
        )}
      </div>
    </header>
  )
}

function StatChip({ label, value, cls }: { label: string; value: number; cls: string }) {
  return (
    <span className={`rounded-full px-2.5 py-0.5 font-semibold ${cls}`}>
      {label} {value}
    </span>
  )
}
