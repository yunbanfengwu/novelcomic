import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import './Tooltip.css'

// ═══════════ 全局 Tooltip：接管所有原生 title，禁用系统气泡，改渲染统一样式浮层 ═══════════
// 组件照常写 title="..."（同时作为无障碍回退）；本层在悬浮/聚焦期间摘除该元素的 title 以
// 抑制浏览器原生 tooltip，改在元素上/下方渲染统一样式浮层，移开/失焦/滚动即还原 title 并收起。

type Placement = 'top' | 'bottom'

export function TooltipHost() {
  const [text, setText] = useState('')
  // cx=锚点元素中心 x（未夹取）；渲染后按浮层实测宽度夹取，避免贴边 tooltip 全挤到同一处
  const [pos, setPos] = useState<{ cx: number; y: number; placement: Placement } | null>(null)
  // 当前接管的元素及其原始 title（收起时还原，避免永久改变 DOM 语义）
  const cur = useRef<{ el: Element; title: string } | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  // 用实测宽度夹取水平位置：短 tooltip 正对按钮下方，仅贴边的长 tooltip 才内收（不再全部堆到右边同一处）
  // 注意：定位量必须写进 --tx（transform），不能写进 left ——
  // position:fixed + width:auto + right:auto 时，浏览器按「视口宽度 − left」做收缩排版计算可用宽度，
  // 越靠边（left 越接近视口宽度）可用宽度越窄，导致文字被迫挤成多行；left 恒为 0 就不受锚点位置影响。
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !pos) return
    const half = el.offsetWidth / 2 + 6
    const cx = Math.min(Math.max(pos.cx, half), window.innerWidth - half)
    el.style.setProperty('--tx', cx + 'px')
  }, [pos, text])

  useEffect(() => {
    const restore = () => {
      if (cur.current) { cur.current.el.setAttribute('title', cur.current.title); cur.current = null }
    }
    const hide = () => { restore(); setPos(null); setText('') }

    const onOver = (e: Event) => {
      const t = e.target as Element | null
      const el = t?.closest?.('[title]') as Element | null
      if (!el) return
      const title = el.getAttribute('title')
      if (!title) return              // 空 title 不弹
      if (cur.current?.el === el) return
      restore()
      cur.current = { el, title }
      el.removeAttribute('title')     // 抑制系统原生 tooltip
      const r = el.getBoundingClientRect()
      const placement: Placement = r.top > 44 ? 'top' : 'bottom'
      setText(title)
      setPos({ cx: r.left + r.width / 2, y: placement === 'top' ? r.top : r.bottom, placement })
    }
    const onOut = (e: MouseEvent) => {
      if (!cur.current) return
      const to = e.relatedTarget as Node | null
      if (to && cur.current.el.contains(to)) return   // 仍在同一元素内部移动
      hide()
    }

    document.addEventListener('mouseover', onOver, true)
    document.addEventListener('mouseout', onOut, true)
    document.addEventListener('mousedown', hide, true)
    window.addEventListener('scroll', hide, true)
    window.addEventListener('wheel', hide, true)
    window.addEventListener('keydown', hide, true)
    window.addEventListener('blur', hide)
    return () => {
      hide()
      document.removeEventListener('mouseover', onOver, true)
      document.removeEventListener('mouseout', onOut, true)
      document.removeEventListener('mousedown', hide, true)
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('wheel', hide, true)
      window.removeEventListener('keydown', hide, true)
      window.removeEventListener('blur', hide)
    }
  }, [])

  if (!pos || !text) return null
  return (
    <div ref={ref} className={`tooltip-pop ${pos.placement}`}
      style={{ left: 0, top: pos.y, ['--tx' as string]: pos.cx + 'px' }} role="tooltip">
      {text}
    </div>
  )
}
