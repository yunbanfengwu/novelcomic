// 画布通用几何：视图变换与贝塞尔连线。素材画布与 SOP 编排画布共用。
export interface CanvasView { x: number; y: number; scale: number }

export const CANVAS_SCALE_MIN = 0.35
export const CANVAS_SCALE_MAX = 1.8

export const clampScale = (value: number, min = CANVAS_SCALE_MIN, max = CANVAS_SCALE_MAX) =>
  Math.min(max, Math.max(min, value))

/** 以指针位置 (px,py) 为锚点缩放视图。 */
export function zoomViewAt(
  view: CanvasView, px: number, py: number, factor: number,
  min = CANVAS_SCALE_MIN, max = CANVAS_SCALE_MAX,
): CanvasView {
  const scale = clampScale(view.scale * factor, min, max)
  return {
    scale,
    x: px - ((px - view.x) / view.scale) * scale,
    y: py - ((py - view.y) / view.scale) * scale,
  }
}

/** 屏幕坐标 → 画布世界坐标。 */
export const toWorld = (view: CanvasView, clientX: number, clientY: number, rect: DOMRect) => ({
  x: (clientX - rect.left - view.x) / view.scale,
  y: (clientY - rect.top - view.y) / view.scale,
})

/** 水平方向三次贝塞尔连线路径。 */
export function bezierPath(x1: number, y1: number, x2: number, y2: number, minBend = 80): string {
  const bend = Math.max(minBend, Math.abs(x2 - x1) * 0.45)
  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`
}
