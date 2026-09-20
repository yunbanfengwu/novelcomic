import { useEffect, useState } from 'react'

/** 全屏切换：整页 Fullscreen API。isFull 随 fullscreenchange 同步（Esc/系统退出也会更新）。 */
export function useFullscreen() {
  const [isFull, setIsFull] = useState(false)
  useEffect(() => {
    const sync = () => setIsFull(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])
  const toggle = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
    else document.documentElement.requestFullscreen().catch(() => {})
  }
  return { isFull, toggle }
}
