import { useCallback, useState } from 'react'

/** 框选矩形（**屏幕坐标**，相对画布宿主左上角） */
export interface MarqueeBox { x: number; y: number; w: number; h: number }

/** 小于这个位移算「点了一下空白」，不算框选（手抖不该把选中清空成 0 个又立刻框选 0 个） */
const THRESHOLD = 4

/**
 * 画布空白处按下拖出的框选矩形。
 * 拖出框 → onSelect(框, 是否加选)；没拖动 → onClick()（点空白 = 取消选中）。
 * 框选期间画布不平移（平移只走滚轮 / 空格拖拽），所以视图变换在整个拖拽过程里是常量。
 */
export function useTapflowMarquee({ hostRef, onSelect, onClick }: {
  hostRef: React.RefObject<HTMLDivElement | null>
  onSelect: (box: MarqueeBox, additive: boolean) => void
  onClick: () => void
}) {
  const [box, setBox] = useState<MarqueeBox | null>(null)

  const start = useCallback((e: React.PointerEvent) => {
    const host = hostRef.current?.getBoundingClientRect()
    if (!host) return
    const additive = e.shiftKey
    const sx = e.clientX - host.left, sy = e.clientY - host.top
    let cur: MarqueeBox | null = null
    const move = (ev: PointerEvent) => {
      const x = ev.clientX - host.left, y = ev.clientY - host.top
      if (!cur && Math.abs(x - sx) < THRESHOLD && Math.abs(y - sy) < THRESHOLD) return
      cur = { x: Math.min(sx, x), y: Math.min(sy, y), w: Math.abs(x - sx), h: Math.abs(y - sy) }
      setBox(cur)
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setBox(null)
      if (cur) onSelect(cur, additive)
      else onClick()
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }, [hostRef, onSelect, onClick])

  return { box, start }
}
