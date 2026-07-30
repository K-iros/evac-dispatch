/** 态势图：地图点位 + 匹配路线 + 时变淹没图层 + 推演时间轴 */
const { fetchSchedule, fetchFloodFrames } = require('../../utils/api')
const { ALERT_META, PROFILE_META, STATUS_META, clockLabel } = require('../../utils/format')

/** marker id 分段，便于 markertap 时反查实体类型 */
const ID_EVACUEE = 1000
const ID_HELPER = 2000
const ID_SHELTER = 3000

function toPoints(coords) {
  return coords.map((c) => ({ longitude: c[0], latitude: c[1] }))
}

Page({
  data: {
    longitude: 110.489,
    latitude: 24.779,
    scale: 15,
    markers: [],
    polylines: [],
    polygons: [],
    frameIndex: 0,
    frameMax: 0,
    minuteLabel: '06-19 00:00',
    waterLabel: '105.5',
    warnLabel: '',
    alert: ALERT_META.standby,
    satellite: false,
  },

  frames: [],
  evacuees: [],

  onShow() {
    this.load()
  },

  onPullDownRefresh() {
    this.load(true).then(() => wx.stopPullDownRefresh())
  },

  load(force) {
    return Promise.all([fetchSchedule(force), fetchFloodFrames(force)]).then(
      ([schedule, frames]) => {
        this.frames = frames
        this.evacuees = schedule.evacuees
        this.setData({
          alert: ALERT_META[schedule.alertLevel] || ALERT_META.standby,
          markers: this.buildMarkers(schedule),
          polylines: this.buildPolylines(schedule),
          frameMax: Math.max(frames.length - 1, 0),
        })
        this.setFrame(this.data.frameIndex)
      },
    )
  },

  buildMarkers(schedule) {
    const markers = []
    schedule.evacuees.forEach((e, i) => {
      const meta = PROFILE_META[e.profile]
      markers.push({
        id: ID_EVACUEE + i,
        longitude: e.location.lng,
        latitude: e.location.lat,
        iconPath:
          e.matchStatus === 'unmatched'
            ? '/assets/evacuee-alert.png'
            : '/assets/evacuee.png',
        width: 26,
        height: 26,
        callout: {
          content: meta.icon + ' ' + e.name + ' · ' + STATUS_META[e.matchStatus].label,
          padding: 6,
          borderRadius: 6,
          display: 'BYCLICK',
        },
      })
    })
    schedule.helpers.forEach((h, i) => {
      markers.push({
        id: ID_HELPER + i,
        longitude: h.location.lng,
        latitude: h.location.lat,
        iconPath: h.available ? '/assets/helper.png' : '/assets/helper-off.png',
        width: 22,
        height: 22,
        callout: {
          content: '🤝 ' + h.name + (h.available ? '' : '（不可用）'),
          padding: 6,
          borderRadius: 6,
          display: 'BYCLICK',
        },
      })
    })
    schedule.shelters.forEach((s, i) => {
      markers.push({
        id: ID_SHELTER + i,
        longitude: s.location.lng,
        latitude: s.location.lat,
        iconPath: '/assets/shelter.png',
        width: 28,
        height: 28,
        callout: {
          content: '🏠 ' + s.name + (s.wheelchairAccessible ? '（无障碍）' : ''),
          padding: 6,
          borderRadius: 6,
          display: 'BYCLICK',
        },
      })
    })
    return markers
  },

  buildPolylines(schedule) {
    return schedule.assignments
      .filter((a) => !a.isFallback) // 改派候选不预先绘制（功能 D 由后端/大屏端升级）
      .map((a) => ({
        points: toPoints(a.route),
        color: a.isBackup ? '#94a3b8cc' : '#0284c7cc',
        width: 4,
        arrowLine: true,
      }))
  },

  /** 切换推演时刻，更新淹没多边形（与大屏端同口径：
   * 水深 minDepth 六档浅蓝→深蓝渐变 + 急流 minVd 橙红危险面） */
  setFrame(index) {
    const frame = this.frames[index]
    if (!frame) return
    // 水深分档填色（0.05/0.15/0.30/0.60/1.20/2.00m）
    const DEPTH_FILL = [
      [2.0, '#1e3a8a6b'],
      [1.2, '#1d4ed86b'],
      [0.6, '#3b82f66b'],
      [0.3, '#60a5fa6b'],
      [0.15, '#93c5fd6b'],
      [0, '#bfdbfe6b'],
    ]
    // v·d 急流分档填色（0.25/0.40/0.50 m²/s）
    const VD_FILL = [
      [0.5, '#dc262680'],
      [0.4, '#f9731680'],
      [0, '#fb923c80'],
    ]
    const pick = (table, v) => {
      for (const [min, color] of table) if (v >= min) return color
      return table[table.length - 1][1]
    }
    const polygons = frame.geojson.features.map((f) => {
      const p = f.properties || {}
      const isVd = p.minVd !== undefined
      return {
        points: toPoints(f.geometry.coordinates[0]),
        fillColor: isVd ? pick(VD_FILL, p.minVd) : pick(DEPTH_FILL, p.minDepth || 0),
        strokeColor: isVd ? '#dc2626aa' : '#2563eb66',
        strokeWidth: 1,
      }
    })
    // 顶栏：模拟时钟 + 阳朔站绝对水位（超警幅度）
    const stage = frame.stageM !== undefined ? frame.stageM : frame.waterLevel
    const warn = frame.warnM
    this.setData({
      frameIndex: index,
      polygons,
      minuteLabel: frame.clock ? clockLabel(frame.clock) : '+' + frame.minute + ' 分钟',
      waterLabel: stage.toFixed(1),
      warnLabel:
        warn === undefined ? '' : warn >= 0 ? '超警 +' + warn.toFixed(1) + 'm' : '低于警戒',
    })
  },

  onSliderChange(e) {
    this.setFrame(e.detail.value)
  },

  /** 切换卫星影像底图（查看撤离路径沿线实地环境） */
  toggleSatellite() {
    this.setData({ satellite: !this.data.satellite })
  },

  /** 点击残障者点位 → 跳详情页 */
  onMarkerTap(e) {
    const id = e.detail.markerId
    if (id >= ID_EVACUEE && id < ID_HELPER) {
      const evacuee = this.evacuees[id - ID_EVACUEE]
      if (evacuee) {
        wx.navigateTo({ url: '/pages/detail/detail?id=' + evacuee.id })
      }
    }
  },
})
