import { useCallback, useEffect, useRef, useState } from 'react'
import { clampScale, zoomViewAt, type CanvasView } from './canvasGeometry'

// tapflow 画布专用缩放区间（共享库默认 0.35~1.8 对大节点画布太窄）
export const TAP_SCALE_MIN = 0.1
export const TAP_SCALE_MAX = 3

/** 指针底下有没有「自己能滚的东西」（正文卡、提示词输入框、超长浮层…）。
 *
 * 画布的滚轮是**原生监听挂在宿主元素上**的，而 React 的 stopPropagation 要等冒泡到
 * 根容器才执行——原生监听早就先跑完了，子组件里写 onWheel 拦不住。所以放行判断
 * 只能做在这个原生监听里。
 *
 * 按**能力**判断而不是按 class 白名单：谁真的能滚就让给谁，以后新加浮层不用回来登记。 */
function scrollableAt(target: Element | null, host: Element): boolean {
  for (let el: Element | null = target; el && el !== host; el = el.parentElement) {
    const s = getComputedStyle(el)
    const scrolls = s.overflowY === 'auto' || s.overflowY === 'scroll' || el.tagName === 'TEXTAREA'
    if (scrolls && el.scrollHeight > el.clientHeight + 1) return true
  }
  return false
}

/** 正在输入的地方：空格是打字，不是「切平移模式」 */
const typing = (t: EventTarget | null) => {
  const el = t as HTMLElement | null
  return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
}

/**
 * tapflow 画布视图 hook：滚轮平移 + 滚轮指针缩放 + 缩放条。
 * **左键拖拽不平移画布**（那是框选，见 useTapflowMarquee）：要拖着看就按住空格，或用中键。
 * 视图变换公式复用 canvasGeometry（单一实现）。
 */
export function useTapflowView(initial?: Partial<CanvasView>) {
  const [view, setView] = useState<CanvasView>({ x: 60, y: 40, scale: 0.9, ...initial })
  // 按住 Ctrl/⌘ = 缩放模式：光标从抓手切成放大镜，提示此时滚轮是缩放而非平移
  const [zoomMode, setZoomMode] = useState(false)
  // 按住空格 = 平移模式：光标切抓手，此时左键拖拽是平移而非框选
  const [panMode, setPanMode] = useState(false)
  const hostRef = useRef<HTMLDivElement>(null)
  // 平移模式要在 memo 过的 tryPan 里读到最新值，故同时留一份 ref
  const panModeRef = useRef(false)

  useEffect(() => {
    const setPan = (on: boolean) => { panModeRef.current = on; setPanMode(on) }
    const down = (e: KeyboardEvent) => {
      setZoomMode(e.ctrlKey || e.metaKey)
      if (e.code !== 'Space' || typing(e.target)) return
      e.preventDefault()   // 否则空格会滚动外层页面
      setPan(true)
    }
    const up = (e: KeyboardEvent) => {
      setZoomMode(e.ctrlKey || e.metaKey)
      if (e.code === 'Space') setPan(false)
    }
    // 切走窗口时收不到 keyup，回来会卡在缩放/抓手光标
    const reset = () => { setZoomMode(false); setPan(false) }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', reset)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', reset)
    }
  }, [])

  // wheel 需要 passive:false 才能 preventDefault（阻止页面滚动）
  useEffect(() => {
    const el = hostRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      // 指针下面有能滚的东西（正文卡 / 提示词输入框 / 长浮层）就把滚轮让给它；
      // 否则 Ctrl(⌘)+滚轮 = 以指针为锚缩放，普通滚轮 = 平移画布。
      // 原来这里是写死的选择器（只放行选中文本节点的正文），提示词输入框滚不动就是漏在外面
      if (scrollableAt(e.target as Element | null, el)) return
      e.preventDefault()
      if (e.ctrlKey || e.metaKey) {
        const rect = el.getBoundingClientRect()
        const factor = e.deltaY < 0 ? 1.08 : 1 / 1.08
        setView(v => zoomViewAt(v, e.clientX - rect.left, e.clientY - rect.top, factor, TAP_SCALE_MIN, TAP_SCALE_MAX))
      } else {
        setView(v => ({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY }))
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  /** 背景按下：**只有**按住空格的左键、或中键才平移画布，其余交给调用方去框选。
   * 返回是否已接管本次按下。（节点内部会 stopPropagation，不会触发） */
  const tryPan = useCallback((e: React.PointerEvent) => {
    const mid = e.button === 1
    if (!mid && !(e.button === 0 && panModeRef.current)) return false
    if (mid) e.preventDefault()   // 挡掉中键的「自动滚动」默认行为
    const start = { sx: e.clientX, sy: e.clientY }
    const base = { x: 0, y: 0 }
    setView(v => { base.x = v.x; base.y = v.y; return v })
    const move = (ev: PointerEvent) => {
      setView(v => ({ ...v, x: base.x + ev.clientX - start.sx, y: base.y + ev.clientY - start.sy }))
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return true
  }, [])

  /** 缩放条：围绕视口中心缩放 */
  const setScaleCentered = useCallback((scale: number) => {
    const el = hostRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    setView(v => zoomViewAt(v, rect.width / 2, rect.height / 2,
      clampScale(scale, TAP_SCALE_MIN, TAP_SCALE_MAX) / v.scale, TAP_SCALE_MIN, TAP_SCALE_MAX))
  }, [])

  return { view, zoomMode, panMode, hostRef, tryPan, setScaleCentered }
}
