import { useCallback, useRef, useState } from 'react'

/**
 * 横向拖动改变「右侧面板」宽度的通用 hook。
 * 返回 width（px）、resizing（拖动中）、onResizeDown（绑到分割线的 onMouseDown）。
 * 宽度持久化到 localStorage[key]；向右拖动缩小右面板（width = 起始 - Δx），并做上下限夹取。
 */
export function useHorizontalResize(key: string, def = 400, min = 280, max = 900) {
  const [width, setWidth] = useState(() => {
    const v = Number(localStorage.getItem(key))
    return v >= min && v <= max ? v : def
  })
  const [resizing, setResizing] = useState(false)
  const wRef = useRef(width)

  const onResizeDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = wRef.current
    setResizing(true)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    const onMove = (ev: MouseEvent) => {
      const w = Math.min(max, Math.max(min, startW - (ev.clientX - startX)))
      wRef.current = w
      setWidth(w)
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      setResizing(false)
      localStorage.setItem(key, String(wRef.current))
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [key, min, max])

  return { width, resizing, onResizeDown }
}
