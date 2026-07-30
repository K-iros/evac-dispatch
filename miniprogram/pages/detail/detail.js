/** 人员详情：画像信息 + 帮扶者 + 避难所 + 任务路线小地图 */
const { fetchSchedule } = require('../../utils/api')
const { PROFILE_META, STATUS_META, countdown, timeHM } = require('../../utils/format')

Page({
  data: {
    evacuee: null,
    profile: null,
    status: null,
    countdownText: '',
    urgent: false,
    departure: '',
    helpers: [],
    shelter: null,
    markers: [],
    polylines: [],
    mapCenter: { lng: 110.489, lat: 24.779 },
  },

  onLoad(options) {
    this.evacueeId = options.id
    this.load()
  },

  load() {
    fetchSchedule().then((schedule) => {
      const evacuee = schedule.evacuees.find((e) => e.id === this.evacueeId)
      if (!evacuee) {
        wx.showToast({ title: '人员不存在', icon: 'error' })
        return
      }
      const helpers = evacuee.helperIds
        .map((id) => schedule.helpers.find((h) => h.id === id))
        .filter(Boolean)
        .map((h, i) => ({
          id: h.id,
          name: h.name,
          available: h.available,
          role: i === 0 ? '主帮扶' : '备份 ' + i,
        }))
      const shelter = schedule.shelters.find((s) => s.id === evacuee.shelterId) || null
      const assignment = schedule.assignments.find(
        (a) => a.evacueeId === evacuee.id && !a.isBackup && !a.isFallback,
      )
      const cd = countdown(evacuee.latestDeparture)

      this.setData({
        evacuee,
        profile: PROFILE_META[evacuee.profile],
        status: STATUS_META[evacuee.matchStatus],
        countdownText: cd.text,
        urgent: cd.urgent,
        departure: timeHM(evacuee.latestDeparture),
        helpers,
        shelter,
        mapCenter: evacuee.location,
        markers: this.buildMarkers(evacuee, schedule, shelter),
        polylines: assignment
          ? [
              {
                points: assignment.route.map((c) => ({ longitude: c[0], latitude: c[1] })),
                color: '#0284c7cc',
                width: 4,
                arrowLine: true,
              },
            ]
          : [],
      })
    })
  },

  buildMarkers(evacuee, schedule, shelter) {
    const markers = [
      {
        id: 1,
        longitude: evacuee.location.lng,
        latitude: evacuee.location.lat,
        iconPath:
          evacuee.matchStatus === 'unmatched'
            ? '/assets/evacuee-alert.png'
            : '/assets/evacuee.png',
        width: 28,
        height: 28,
      },
    ]
    evacuee.helperIds.forEach((id, i) => {
      const h = schedule.helpers.find((x) => x.id === id)
      if (h) {
        markers.push({
          id: 10 + i,
          longitude: h.location.lng,
          latitude: h.location.lat,
          iconPath: h.available ? '/assets/helper.png' : '/assets/helper-off.png',
          width: 22,
          height: 22,
        })
      }
    })
    if (shelter) {
      markers.push({
        id: 99,
        longitude: shelter.location.lng,
        latitude: shelter.location.lat,
        iconPath: '/assets/shelter.png',
        width: 28,
        height: 28,
      })
    }
    return markers
  },

  /** 用微信内置地图导航到该户 */
  onNavigate() {
    const e = this.data.evacuee
    if (!e) return
    wx.openLocation({
      longitude: e.location.lng,
      latitude: e.location.lat,
      name: e.name + '（' + this.data.profile.label + '）',
      address: e.address,
      scale: 17,
    })
  },
})
