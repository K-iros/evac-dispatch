/** 撤离名单：按最迟出发时间倒计时排序 */
const { fetchSchedule } = require('../../utils/api')
const { PROFILE_META, STATUS_META, countdown, timeHM } = require('../../utils/format')

Page({
  data: {
    items: [],
    stats: { total: 0, unmatched: 0, evacuated: 0 },
  },

  onShow() {
    this.load()
    // 每 30 秒刷新一次倒计时文案
    this.timer = setInterval(() => this.load(), 30000)
  },

  onHide() {
    clearInterval(this.timer)
  },

  onUnload() {
    clearInterval(this.timer)
  },

  onPullDownRefresh() {
    this.load(true).then(() => wx.stopPullDownRefresh())
  },

  load(force) {
    return fetchSchedule(force).then((schedule) => {
      const items = schedule.evacuees
        .slice()
        .sort((a, b) => new Date(a.latestDeparture) - new Date(b.latestDeparture))
        .map((e) => {
          const cd = countdown(e.latestDeparture)
          return {
            id: e.id,
            name: e.name,
            address: e.address,
            profileIcon: PROFILE_META[e.profile].icon,
            profileLabel: PROFILE_META[e.profile].label,
            status: STATUS_META[e.matchStatus],
            departure: timeHM(e.latestDeparture),
            countdownText: cd.text,
            urgent: cd.urgent,
            helperCount: e.helperIds.length,
          }
        })
      this.setData({
        items,
        stats: {
          total: schedule.evacuees.length,
          unmatched: schedule.evacuees.filter((e) => e.matchStatus === 'unmatched').length,
          evacuated: schedule.evacuees.filter((e) => e.matchStatus === 'evacuated').length,
        },
      })
    })
  },

  onItemTap(e) {
    wx.navigateTo({ url: '/pages/detail/detail?id=' + e.currentTarget.dataset.id })
  },
})
