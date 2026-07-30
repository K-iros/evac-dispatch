/**
 * API 层：后端不在线时自动回退 mock，联调零改动。
 * 后端路由见 backend/app/api/routes.py
 */
const { mockSchedule, mockFloodFrames } = require('./mock')

function request(path) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: getApp().globalData.apiBase + path,
      timeout: 5000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          reject(new Error('HTTP ' + res.statusCode))
        }
      },
      fail: reject,
    })
  })
}

let schedulePromise = null
let framesPromise = null

/** 获取整体调度态势（名单 + 帮扶者 + 匹配结果），页面间共享缓存 */
function fetchSchedule(force) {
  if (!schedulePromise || force) {
    schedulePromise = request('/api/schedule').catch(() => mockSchedule())
  }
  return schedulePromise
}

/** 获取淹没推演时间序列 */
function fetchFloodFrames(force) {
  if (!framesPromise || force) {
    framesPromise = request('/api/flood/frames').catch(() => mockFloodFrames())
  }
  return framesPromise
}

module.exports = { fetchSchedule, fetchFloodFrames }
