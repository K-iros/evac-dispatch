/** 小程序入口 —— 全局配置 */
App({
  globalData: {
    // 后端 FastAPI 地址。开发者工具需在「详情-本地设置」勾选
    // 「不校验合法域名」（project.config.json 已默认 urlCheck: false）。
    // 真机联调时改为局域网 IP，上线时改为已备案的 HTTPS 域名。
    apiBase: 'http://localhost:8000',
  },
})
