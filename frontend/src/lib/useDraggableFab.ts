import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'

const MARGIN = 12      // 贴边最小留白：钳制后不会半个身子露在视口外
const DRAG_SLOP = 4    // 位移小于此像素仍算点击——不然手抖一下就点不开了

export type FabPos = { x: number; y: number }

const readPos = (key: string): FabPos | null => {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const p = JSON.parse(raw) as Partial<FabPos>
    return typeof p?.x === 'number' && typeof p?.y === 'number' ? { x: p.x, y: p.y } : null
  } catch { return null }
}

/** 可拖动浮标的定位逻辑：拖过之后落点持久化到 localStorage。
 *
 * 缺省位置**不测视口**、交给 CSS 的 right/bottom 贴角——窗口最小化/标签页隐藏时
 * innerWidth 会是 0，此时若用 JS 算默认落点，会把浮标钉死在左上角且再也回不来。
 * 只有存在拖过的落点时才用内联 left/top 接管（此时顺带把 right/bottom 置 auto）。
 * moved ref 给调用方在 onClick 里分辨「拖完松手」还是「真点击」——拖动不应触发点击。 */
export function useDraggableFab(key: string, w: number, h: number) {
  const [pos, setPos] = useState<FabPos | null>(() => readPos(key))
  const [dragging, setDragging] = useState(false)
  const drag = useRef<{ dx: number; dy: number; sx: number; sy: number } | null>(null)
  const moved = useRef(false)

  const clamp = useCallback((p: FabPos): FabPos => {
    const W = window.innerWidth, H = window.innerHeight
    if (!W || !H) return p   // 视口尚未成形：原样保留，等拿到真实尺寸再钳
    return {
      x: Math.min(Math.max(p.x, MARGIN), Math.max(MARGIN, W - w - MARGIN)),
      y: Math.min(Math.max(p.y, MARGIN), Math.max(MARGIN, H - h - MARGIN)),
    }
  }, [w, h])

  // 缩窗/换屏后把已有落点收回视口内（没拖过则无事发生，贴角由 CSS 管）
  useEffect(() => {
    const onResize = () => setPos(p => (p ? clamp(p) : p))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [clamp])

  const onPointerDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return
    // 起拖点按实际盒子算，不依赖 pos——贴角缺省态（pos 为 null）也能直接拖走
    const r = e.currentTarget.getBoundingClientRect()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { dx: e.clientX - r.left, dy: e.clientY - r.top, sx: e.clientX, sy: e.clientY }
    moved.current = false
    setDragging(true)
  }
  const onPointerMove = (e: React.PointerEvent<HTMLElement>) => {
    const d = drag.current
    if (!d) return
    if (Math.hypot(e.clientX - d.sx, e.clientY - d.sy) > DRAG_SLOP) moved.current = true
    setPos(clamp({ x: e.clientX - d.dx, y: e.clientY - d.dy }))
  }
  const onPointerUp = (e: React.PointerEvent<HTMLElement>) => {
    if (!drag.current) return
    e.currentTarget.releasePointerCapture(e.pointerId)
    drag.current = null
    setDragging(false)
    if (moved.current && pos) localStorage.setItem(key, JSON.stringify(pos))
  }

  const style: CSSProperties = pos
    ? { left: pos.x, top: pos.y, right: 'auto', bottom: 'auto' }
    : {}
  return {
    style, dragging, moved,
    handlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp },
  }
}
