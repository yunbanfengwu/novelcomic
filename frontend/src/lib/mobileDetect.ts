// ═══════════ 移动端判定：视口 <400px 或移动 UA 时给 body 挂 is-mobile ═══════════

/** 视口宽度低于该值判定为移动端 */
export const MOBILE_MAX_WIDTH = 400

const MOBILE_UA = /Android|iPhone|iPad|iPod|HarmonyOS|Mobile/i

/** 移动 UA 与窄视口等同处理 */
function isMobile(): boolean {
  return MOBILE_UA.test(navigator.userAgent) || window.innerWidth < MOBILE_MAX_WIDTH
}

/** 应用启动时调用一次：在 body 上维护 is-mobile class，尺寸变化时实时更新 */
export function initMobileBodyClass() {
  const apply = () => document.body.classList.toggle('is-mobile', isMobile())
  apply()
  window.addEventListener('resize', apply)
  // 部分环境（设备仿真/旋转）不派发 resize，用媒体查询变化兜底
  window.matchMedia(`(max-width: ${MOBILE_MAX_WIDTH - 1}px)`).addEventListener('change', apply)
}
