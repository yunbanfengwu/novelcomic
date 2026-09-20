import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export interface TapPickItem {
  value: string
  label: string
  /** 次要说明（知识库条目数 / 工具描述），跟在名字后面灰字显示 */
  note?: string
  /** 当前生效项，左侧打勾 */
  active?: boolean
  /** 危险操作（如删除），红字 */
  danger?: boolean
}
export interface TapPickGroup { title?: string; items: (string | TapPickItem)[] }

const GAP = 6      // 浮窗与触发点的间距
const EDGE = 8     // 离视口边缘的最小留白

/** 元素是不是 fixed 定位的包含块（有 transform/filter/perspective 就是）。
 * 是的话，里面 position:fixed 的坐标以它的边框盒为原点，不是视口。 */
function isContainingBlock(el: Element): boolean {
  const s = getComputedStyle(el)
  return s.transform !== 'none' || s.filter !== 'none' || s.perspective !== 'none'
    || s.willChange.includes('transform')
}

/** 浮窗该挂到哪：优先挂进 Radix Dialog 的内容节点（.rx-modal）。
 *
 * 不能挂 document.body——Radix 的模态 Dialog 打开时会把 body 设成
 * `pointer-events: none`，只有 Dialog 内容子树可交互，挂 body 上的浮窗**点不动**，
 * 点击直接穿到下面的画布。挂进内容节点还顺带解决了另一个问题：
 * Radix 的 DismissableLayer 会把「内容之外的点击」当作关闭信号，
 * 挂在外面点一下菜单就会把整个画布弹窗关掉。 */
function portalHost(from: Element | null): HTMLElement {
  return (from?.closest('.rx-modal') as HTMLElement | null) ?? document.body
}

/** 通用选择浮窗：分组列出候选，点选即回调；点外部或 ESC 关闭。
 * 「添加变量」「添加取数工具」等共用它，点外关闭这类逻辑只此一份。
 *
 * portal + fixed 定位：浮窗原来是触发点的兄弟节点，属性面板一有 overflow 滚动
 * 就会把它裁掉（右侧面板里只露出半截）。位置按触发点实测算，空间不够则上翻、
 * 贴边收拢，超高就自己滚。调用方无需改动——锚点取的是浮窗原位置的父元素。 */
export function TapPickMenu({ groups, onPick, onClose }: {
  groups: TapPickGroup[]
  onPick: (value: string) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const holder = useRef<HTMLSpanElement>(null)
  const [host, setHost] = useState<HTMLElement | null>(null)
  const [pos, setPos] = useState<{ left: number; top: number; maxH: number } | null>(null)

  // 先定容器（要等锚点进 DOM 才知道自己在不在弹窗里），再定位置
  useLayoutEffect(() => { setHost(portalHost(holder.current)) }, [])

  // 位置要在浏览器绘制前算好，否则会先闪一下再跳到正确位置
  useLayoutEffect(() => {
    if (!host) return
    const place = () => {
      const anchor = holder.current?.parentElement
      const menu = ref.current
      if (!anchor || !menu) return
      const a = anchor.getBoundingClientRect()
      const w = menu.offsetWidth
      const h = menu.scrollHeight
      const below = window.innerHeight - a.bottom - GAP - EDGE
      const above = a.top - GAP - EDGE
      // 下方放不下且上方更宽敞 → 上翻
      const flip = h > below && above > below
      const maxH = Math.max(120, flip ? above : below)
      const top = flip ? Math.max(EDGE, a.top - GAP - Math.min(h, maxH)) : a.bottom + GAP
      // 先按右对齐触发点；会捅出左边界就改成左对齐（宁可往右铺，也别整片盖到画布上）
      let left = a.right - w
      if (left < EDGE) left = a.left
      left = Math.min(Math.max(EDGE, left), Math.max(EDGE, window.innerWidth - w - EDGE))
      // 容器若是 fixed 的包含块（.rx-modal 带 transform），坐标要换算到它的边框盒
      const o = host !== document.body && isContainingBlock(host)
        ? host.getBoundingClientRect() : { left: 0, top: 0 }
      // 必须比对后再 set：每次都塞新对象会「setPos → 重渲染 → 再 place」死循环
      const next = { left: left - o.left, top: top - o.top, maxH }
      setPos(p => (p && p.left === next.left && p.top === next.top && p.maxH === next.maxH)
        ? p : next)
    }
    place()
    window.addEventListener('resize', place)
    // 捕获阶段收全部滚动容器的滚动（面板自身滚动也要跟着走）
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [host])

  useEffect(() => {
    const away = (e: PointerEvent) => {
      const t = e.target as Node
      // 触发点自身也算「内部」：否则点按钮会先被这里关掉，再被 onClick 切回打开，永远关不掉
      if (ref.current?.contains(t) || holder.current?.parentElement?.contains(t)) return
      onClose()
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    // 延后挂载：否则本次点击的冒泡会立刻把刚开的浮窗关掉
    const t = setTimeout(() => window.addEventListener('pointerdown', away), 0)
    window.addEventListener('keydown', esc)
    return () => {
      clearTimeout(t)
      window.removeEventListener('pointerdown', away)
      window.removeEventListener('keydown', esc)
    }
  }, [onClose])

  const empty = groups.every(g => !g.items.length)
  const norm = (it: string | TapPickItem): TapPickItem =>
    typeof it === 'string' ? { value: it, label: it } : it

  const menu = (
    <div
      ref={ref} role="menu" className="tap-param-menu floating"
      style={pos
        ? { left: pos.left, top: pos.top, maxHeight: pos.maxH }
        // 首帧还没量出位置：先画在视口外，避免左上角闪一下
        : { left: -9999, top: -9999 }}
      // 只拦 React 树上的冒泡；**不要**在这里装原生 stopPropagation——
      // React 的事件委托挂在根容器上，在菜单节点截断原生冒泡会让 onClick 根本不触发
      onPointerDown={e => e.stopPropagation()}
      onWheel={e => e.stopPropagation()}>
      {empty && <div className="tap-pm-title">没有可添加的项</div>}
      {groups.map((g, i) => !!g.items.length && (
        <div key={g.title ?? i} className={i ? 'tap-pm-group' : ''}>
          {g.title && <div className="tap-pm-title">{g.title}</div>}
          {g.items.map(raw => {
            const it = norm(raw)
            return (
              // 菜单项用 div 而非 button：button 带全局主题样式（渐变底、居中文字），
              // 在菜单里要一条条覆盖，不如直接不用它
              <div key={it.value} role="menuitem" tabIndex={0}
                className={'tap-pm-item' + (it.active ? ' active' : '') + (it.danger ? ' danger' : '')}
                onClick={() => { onPick(it.value); onClose() }}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') { onPick(it.value); onClose() }
                }}>
                <span>{it.label}{it.note && <i className="tap-pm-note">{it.note}</i>}</span>
                {it.active && <em>✓</em>}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
  // 留一个 0 尺寸的锚点在原位（父元素即触发点），浮窗本体挂到弹窗内容/body 上
  return (
    <>
      <span ref={holder} className="tap-pm-anchor" />
      {host && createPortal(menu, host)}
    </>
  )
}
