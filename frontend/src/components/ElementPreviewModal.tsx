import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { registerElementPreview } from '../lib/elementPreview'
import { Icon } from './Icon'

/** 预览/生成弹窗宿主（**多层栈**）：全屏遮罩 + 居中大卡片，卡片内渲染调用方传入的组件。
 * 每层独立遮罩按栈序叠放；点遮罩/✕/Esc 只关栈顶一层。父层始终挂载（状态不丢）。
 * App 根挂载一次，任意组件用 openElementPreview()/pushElementPreview() 打开。 */
export function ElementPreviewModal() {
  const [stack, setStack] = useState<ReactNode[]>([])
  /** 处于全屏的层序号（同时只允许一层）。全屏走浏览器 Fullscreen API（等价 F11），
   * 卡片再靠 .epm-full 铺满这块全屏视口。状态以 fullscreenchange 为准——用户按 F11/Esc
   * 或从浏览器 UI 退出时也能同步回来。
   * 全屏键默认不显示，由内容自己的 CSS 打开。 */
  const [full, setFull] = useState<number | null>(null)

  useEffect(() => {
    registerElementPreview(
      n => { setStack([n]); setFull(null) },     // open：重置为单层
      n => setStack(s => [...s, n]),             // push：叠一层
      () => setStack(s => {                      // close：出栈一层
        setFull(f => (f !== null && f >= s.length - 1 ? null : f))
        return s.slice(0, -1)
      }),
    )
    return () => registerElementPreview(null, null, null)
  }, [])

  // 浏览器侧退出全屏（Esc / F11 / 地址栏提示条）时把状态收回来
  useEffect(() => {
    const onChange = () => { if (!document.fullscreenElement) setFull(null) }
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const toggleFull = (i: number) => {
    if (full === i) {
      if (document.fullscreenElement) void document.exitFullscreen()
      else setFull(null)
      return
    }
    // 真·浏览器全屏；被权限策略禁用时（内嵌 iframe 等）退化成铺满视口，按钮不至于点了没反应
    document.documentElement.requestFullscreen().catch(() => {})
    setFull(i)
  }

  // 关到第 i 层之前（点遮罩/✕）：被关掉的层若正全屏，连浏览器全屏一起退掉
  const closeTo = (i: number) => {
    setStack(s => s.slice(0, i))
    setFull(f => {
      if (f === null || f < i) return f
      if (document.fullscreenElement) void document.exitFullscreen()
      return null
    })
  }

  // Esc：全屏态交给浏览器（它自己会退出全屏），不顺手把弹窗也关了
  useEffect(() => {
    if (!stack.length) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (document.fullscreenElement) return   // 浏览器自己会退全屏
      if (full !== null) { setFull(null); return }  // 退化态：先退铺满，再按才关窗
      closeTo(stack.length - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stack.length, full])

  useEffect(() => {
    if (!stack.length) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [stack.length])

  if (!stack.length) return null
  return createPortal(
    <>
      {stack.map((node, i) => (
        <div key={i} className="modal-backdrop" style={{ zIndex: 1000 + i * 10 }}
          onClick={() => closeTo(i)}>
          <div className={'modal-card element-preview-card' + (full === i ? ' epm-full' : '')}
            onClick={e => e.stopPropagation()}>
            <button className="modal-x epm-full-btn" title={full === i ? '退出全屏' : '全屏'}
              onClick={() => toggleFull(i)}>
              <Icon name={full === i ? 'collapse' : 'fullscreen'} />
            </button>
            <button className="modal-x epm-close" title="关闭 (Esc)"
              onClick={() => closeTo(i)}>✕</button>
            {node}
          </div>
        </div>
      ))}
    </>, document.body)
}
