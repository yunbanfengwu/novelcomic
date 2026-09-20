import { useCallback, useEffect, useState } from 'react'

/** 观测元素**父容器**的宽度（ResizeObserver 实时更新），用于按可用宽度折算可容纳的子项数 */
export function useParentWidth() {
  const [el, setEl] = useState<HTMLElement | null>(null)
  const [width, setWidth] = useState(0)
  const ref = useCallback((node: HTMLElement | null) => setEl(node), [])
  useEffect(() => {
    const parent = el?.parentElement
    if (!parent) return
    const apply = () => setWidth(parent.clientWidth)
    apply() // 挂载即同步量一次，不依赖 RO 首调（帧节流环境下可能延迟）
    const ro = new ResizeObserver(apply)
    ro.observe(parent)
    return () => ro.disconnect()
  }, [el])
  return { ref, width }
}
