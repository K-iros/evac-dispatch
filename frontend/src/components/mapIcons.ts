import type { Map as MLMap } from 'maplibre-gl'

/**
 * 地图 marker 图标：内联 SVG → data URL，运行时注册为 map image。
 * 待撤离者用"人物水滴 pin"（按画像区分轮廓），避难所用大号圆形徽章，
 * 视觉体系与小程序 assets 及图例配色保持一致。
 */

/** 人物水滴 pin：32x38 视口，锚点在底部尖端 */
function pin(fill: string, glyph: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="76" viewBox="0 0 32 38">
  <path d="M16 1C8.8 1 3 6.8 3 14c0 9.6 13 23 13 23s13-13.4 13-23C29 6.8 23.2 1 16 1z"
    fill="${fill}" stroke="#ffffff" stroke-width="2"/>
  ${glyph}
</svg>`
}

/** 小圆点 marker（帮扶者）：24x24 视口 */
function dot(fill: string, glyph: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="52" height="52" viewBox="0 0 26 26">
  <circle cx="13" cy="13" r="11" fill="${fill}" stroke="#ffffff" stroke-width="2"/>
  ${glyph}
</svg>`
}

/** 大号徽章（避难所）：38x38 视口 */
function badge(fill: string, glyph: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 40 40">
  <circle cx="20" cy="20" r="17.5" fill="${fill}" stroke="#ffffff" stroke-width="3"/>
  ${glyph}
</svg>`
}

const W = '#ffffff'

/** 轮椅使用者：头 + 坐姿躯干 + 大轮 */
const GLYPH_WHEELCHAIR = `
  <circle cx="14.2" cy="7.2" r="2.5" fill="${W}"/>
  <path d="M12.9 10.2h2.7v4.8h4.7v2.3h-7.4z" fill="${W}"/>
  <circle cx="14.6" cy="18.6" r="3.8" fill="none" stroke="${W}" stroke-width="1.8"/>
  <path d="M20.5 16.6l1.8 3.5h1.6" fill="none" stroke="${W}" stroke-width="1.7" stroke-linecap="round"/>`

/** 视障者：站立人形 + 斜向盲杖 */
const GLYPH_BLIND = `
  <circle cx="15" cy="7" r="2.6" fill="${W}"/>
  <path d="M11.5 19.8c0-3.4 1.6-5.5 3.5-5.5s3.5 2.1 3.5 5.5v1.4h-7z" fill="${W}"/>
  <path d="M18.6 12.5l4 8" stroke="${W}" stroke-width="1.7" stroke-linecap="round"/>`

/** 老人：微躬人形 + 直拐杖 */
const GLYPH_ELDERLY = `
  <circle cx="14.6" cy="7" r="2.6" fill="${W}"/>
  <path d="M11 19.8c0-3.4 1.7-5.5 3.6-5.5s3.6 2.1 3.6 5.5v1.4H11z" fill="${W}"/>
  <path d="M20.6 12.8v8.2" stroke="${W}" stroke-width="1.7" stroke-linecap="round"/>`

/** 帮扶者：站立人形（26 视口） */
const GLYPH_HELPER = `
  <circle cx="13" cy="9" r="3" fill="${W}"/>
  <path d="M7.8 19.4c0-3.6 2.3-5.8 5.2-5.8s5.2 2.2 5.2 5.8v.4H7.8z" fill="${W}"/>`

/** 避难所：房屋（40 视口） */
const GLYPH_SHELTER = `
  <path d="M11 20l9-7.5 9 7.5" fill="none" stroke="${W}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M13.4 19.4v8.4h13.2v-8.4z" fill="${W}"/>
  <rect x="18.1" y="23.2" width="3.8" height="4.6" fill="CURRENT"/>`

const C_EVACUEE = '#f97316' // 待撤离（橙）
const C_ALERT = '#ef4444' // 未匹配（红）
const C_HELPER = '#3b82f6' // 帮扶者（蓝）
const C_HELPER_OFF = '#94a3b8' // 不可用（灰）
const C_SHELTER = '#059669' // 无障碍避难所（绿）
const C_SHELTER_LIMITED = '#64748b' // 非无障碍避难所（灰蓝）
const C_SHELTER_FAILED = '#dc2626' // 失效避难所（红，功能 D）
const C_SHELTER_VERTICAL = '#d97706' // 垂直避险降级（黄，第十三节第 7 项）
const C_DONE = '#9ca3af' // 已撤离（灰，第十四节第 1 项）

/** 失效避难所：红色徽章 + 右上角红叉角标 */
function failedBadge(): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 40 40">
  <circle cx="20" cy="20" r="17.5" fill="${C_SHELTER_FAILED}" stroke="#ffffff" stroke-width="3" opacity="0.92"/>
  ${GLYPH_SHELTER.replace('CURRENT', C_SHELTER_FAILED)}
  <line x1="9" y1="9" x2="31" y2="31" stroke="#ffffff" stroke-width="3.4" stroke-linecap="round"/>
  <line x1="31" y1="9" x2="9" y2="31" stroke="#ffffff" stroke-width="3.4" stroke-linecap="round"/>
</svg>`
}

/** 垂直避险降级徽章（第 7 项）：黄底房屋 + 上行箭头（场地进水、人员上楼） */
function verticalBadge(): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 40 40">
  <circle cx="20" cy="20" r="17.5" fill="${C_SHELTER_VERTICAL}" stroke="#ffffff" stroke-width="3"/>
  ${GLYPH_SHELTER.replace('CURRENT', C_SHELTER_VERTICAL)}
  <path d="M20 26v-9m0 0l-3.4 3.4M20 17l3.4 3.4" fill="none" stroke="${C_SHELTER_VERTICAL}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`
}

/** 已撤离 pin（第十四节第 1 项）：灰底画像 + 右上角绿色 ✓ 角标，
 * 迁移到目标避难所旁展示"已安排到位" */
function pinDone(glyph: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="76" viewBox="0 0 32 38">
  <path d="M16 1C8.8 1 3 6.8 3 14c0 9.6 13 23 13 23s13-13.4 13-23C29 6.8 23.2 1 16 1z"
    fill="${C_DONE}" stroke="#ffffff" stroke-width="2" opacity="0.92"/>
  ${glyph}
  <circle cx="25.5" cy="6.5" r="5" fill="#16a34a" stroke="#ffffff" stroke-width="1.6"/>
  <path d="M23.2 6.5l1.7 1.7 3-3.4" fill="none" stroke="#ffffff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`
}

/** 护送移动小点（第 4 项）：外圈白描边实心圆，接人段琥珀 / 护送段绿，与路线配色一致 */
function movingDot(fill: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 18 18">
  <circle cx="9" cy="9" r="8" fill="${fill}" opacity="0.25"/>
  <circle cx="9" cy="9" r="5.2" fill="${fill}" stroke="#ffffff" stroke-width="2"/>
</svg>`
}

/** 图标名 → SVG 源码 */
const ICONS: Record<string, string> = {
  'evacuee-wheelchair': pin(C_EVACUEE, GLYPH_WHEELCHAIR),
  'evacuee-blind': pin(C_EVACUEE, GLYPH_BLIND),
  'evacuee-elderly': pin(C_EVACUEE, GLYPH_ELDERLY),
  'evacuee-wheelchair-alert': pin(C_ALERT, GLYPH_WHEELCHAIR),
  'evacuee-blind-alert': pin(C_ALERT, GLYPH_BLIND),
  'evacuee-elderly-alert': pin(C_ALERT, GLYPH_ELDERLY),
  // 已撤离（第十四节第 1 项）：灰 pin + ✓ 角标，pin 迁至避难所旁
  'evacuee-wheelchair-done': pinDone(GLYPH_WHEELCHAIR),
  'evacuee-blind-done': pinDone(GLYPH_BLIND),
  'evacuee-elderly-done': pinDone(GLYPH_ELDERLY),
  helper: dot(C_HELPER, GLYPH_HELPER),
  'helper-off': dot(C_HELPER_OFF, GLYPH_HELPER),
  shelter: badge(C_SHELTER, GLYPH_SHELTER.replace('CURRENT', C_SHELTER)),
  'shelter-limited': badge(C_SHELTER_LIMITED, GLYPH_SHELTER.replace('CURRENT', C_SHELTER_LIMITED)),
  // 避难所失效（被淹/v·d 超限）：红底白叉，功能 D 自动改派时标注
  'shelter-failed': failedBadge(),
  // 垂直避险降级（第 7 项）：场地进水但可上楼，黄色降级而非红叉
  'shelter-vertical': verticalBadge(),
  // 护送移动小点（第 4 项）：接人段琥珀 / 护送段绿
  'escort-dot-pickup': movingDot('#f59e0b'),
  'escort-dot-escort': movingDot('#10b981'),
  // 路径方向箭头（沿线布置，指向 +x）
  'route-arrow': `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">
  <path d="M5 4l12 7-12 7z" fill="#ffffff" stroke="rgba(15,23,42,0.35)" stroke-width="1.2"/>
</svg>`,
  // 无障碍对比：街景识别出的台阶/陡坎障碍点（黄底警告三角 + 台阶纹）
  'access-barrier': `<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" viewBox="0 0 30 30">
  <path d="M15 3L28 26H2z" fill="#facc15" stroke="#ffffff" stroke-width="2.2" stroke-linejoin="round"/>
  <path d="M9.5 21.5h3v-3h3v-3h3" fill="none" stroke="#1f2937" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`,
}

function svgToImage(svg: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  })
}

/** 注册全部图标到地图实例（pixelRatio 2 保证高清屏清晰） */
export async function loadMapIcons(map: MLMap): Promise<void> {
  await Promise.all(
    Object.entries(ICONS).map(async ([name, svg]) => {
      const img = await svgToImage(svg)
      if (!map.hasImage(name)) map.addImage(name, img, { pixelRatio: 2 })
    }),
  )
}

/** 第十三节第 1 项：剧情户虚拟人脸头像（AI 生成，非真实照片）。
 * 头像文件位于 public/avatars/{evacueeId}.png，运行时画到圆形画布
 * （白描边 + 橙色外环，与画像 pin 配色一致）后注册为 avatar-{id}；
 * 缺文件/加载失败静默跳过，MapView 回退画像 pin */
export const AVATAR_EVACUEE_IDS = ['e-1', 'e-2', 'e-8', 'e-16', 'e-19'] as const

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

export async function loadAvatarIcons(map: MLMap): Promise<void> {
  const SIZE = 88 // 导出像素（pixelRatio 2 → 屏幕 44px）
  await Promise.all(
    AVATAR_EVACUEE_IDS.map(async (id) => {
      try {
        const img = await loadImage(`/avatars/${id}.png`)
        const canvas = document.createElement('canvas')
        canvas.width = SIZE
        canvas.height = SIZE
        const ctx = canvas.getContext('2d')
        if (!ctx) return
        const r = SIZE / 2
        // 圆形裁剪 + 橙色外环 + 白描边
        ctx.save()
        ctx.beginPath()
        ctx.arc(r, r, r - 5, 0, Math.PI * 2)
        ctx.clip()
        ctx.drawImage(img, 0, 0, SIZE, SIZE)
        ctx.restore()
        ctx.lineWidth = 4
        ctx.strokeStyle = '#f97316'
        ctx.beginPath()
        ctx.arc(r, r, r - 5, 0, Math.PI * 2)
        ctx.stroke()
        ctx.lineWidth = 3
        ctx.strokeStyle = '#ffffff'
        ctx.beginPath()
        ctx.arc(r, r, r - 2, 0, Math.PI * 2)
        ctx.stroke()
        const data = ctx.getImageData(0, 0, SIZE, SIZE)
        const name = `avatar-${id}`
        if (!map.hasImage(name)) map.addImage(name, data, { pixelRatio: 2 })
      } catch {
        // 缺头像文件：静默回退画像 pin
      }
    }),
  )
}
