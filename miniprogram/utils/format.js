/** 展示格式化：画像/状态/响应级别文案与倒计时 */

const PROFILE_META = {
  wheelchair: { icon: '♿', label: '轮椅' },
  blind: { icon: '🦯', label: '盲人' },
  elderly: { icon: '🧓', label: '老人' },
}

const STATUS_META = {
  unmatched: { label: '未匹配', cls: 'tag-red' },
  matched: { label: '已匹配', cls: 'tag-blue' },
  en_route: { label: '在途', cls: 'tag-amber' },
  arrived: { label: '已到场', cls: 'tag-green' },
  evacuated: { label: '已撤离', cls: 'tag-gray' },
}

const ALERT_META = {
  standby: { label: '预备', cls: 'alert-standby' },
  ready: { label: '待命', cls: 'alert-ready' },
  dispatch: { label: '出动', cls: 'alert-dispatch' },
}

const { SIM_T0_MS } = require('./mock')

/** 倒计时文案：距最迟出发时间；剩余不足 1 小时或已超时视为紧迫。
 * 时间口径为模拟时钟（latestDeparture 是 2024-06-19 推演时刻），
 * simNowIso 传当前推演帧时刻，缺省取推演起点 T0。 */
function countdown(iso, simNowIso) {
  const now = simNowIso ? new Date(simNowIso).getTime() : SIM_T0_MS
  const diffMs = new Date(iso + (iso.indexOf('Z') < 0 ? 'Z' : '')).getTime() - now
  const abs = Math.abs(diffMs)
  const h = Math.floor(abs / 3600000)
  const m = Math.floor((abs % 3600000) / 60000)
  const text = diffMs >= 0 ? '剩 ' + h + ' 时 ' + m + ' 分' : '已超 ' + h + ' 时 ' + m + ' 分'
  return { text, urgent: diffMs < 3600000 }
}

const pad = (n) => (n < 10 ? '0' + n : '' + n)

/** ISO 时刻 → HH:mm（模拟时钟按 UTC 字段读取，避免时区偏移） */
function timeHM(iso) {
  const d = new Date(iso + (iso.indexOf('Z') < 0 ? 'Z' : ''))
  return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes())
}

/** ISO 时刻 → MM-DD HH:mm 模拟时钟标签 */
function clockLabel(iso) {
  const d = new Date(iso + (iso.indexOf('Z') < 0 ? 'Z' : ''))
  return (
    pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) + ' ' +
    pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes())
  )
}

module.exports = { PROFILE_META, STATUS_META, ALERT_META, countdown, timeHM, clockLabel }
