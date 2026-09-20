import { useEffect, useRef, useState } from 'react'
import { parsePrompt, serializePrompt, tokenLabel } from '../../lib/tapflowPrompt'
import type { TapCtxRef, TapUpstreamVar } from '../../lib/tapflowData'
import { refGroups, unpackRef } from '../../lib/tapflowRefs'
import { useTapflowCatalog } from '../../lib/useTapflowCatalog'
import { TapPickMenu } from './TapPickMenu'

/**
 * 系统提示词编辑器：文本 + **行内标签**混排（「请参考【图片小明】生成」）。
 *
 * 用 contenteditable 而不是 textarea——textarea 只能存纯文本，做不出行内标签。
 * 存的仍是一个字符串，标签就是 {{...}} 占位符，运行时的解析口径与后端一致。
 *
 * 行内标签只有一个入口：**在正文里打 @**。上方那排方块的「+」只管那排，不动正文。
 *
 * 受控但不重渲染：contenteditable 每次 React 重画都会把光标弹回开头，所以 DOM 由
 * 本组件自己建，只有**外部值变了且不是自己刚发出去的**才重建。
 */
export function TapPromptEditor({ value, refs, upstream, placeholder, onChange, onAddRef }: {
  value: string
  /** 引用清单：占位符 → 展示名与类型（决定标签文字与配色） */
  refs: TapCtxRef[]
  /** @ 菜单的候选：沿连线回溯到的上游输出变量 */
  upstream: TapUpstreamVar[]
  placeholder?: string
  onChange: (next: string) => void
  /** @ 选中的引用要登记进引用清单，标签才解析得出名字与类型 */
  onAddRef?: (ref: TapCtxRef) => void
}) {
  const catalog = useTapflowCatalog()
  const el = useRef<HTMLDivElement>(null)
  const last = useRef(value)
  const metaRef = useRef(refs)
  metaRef.current = refs
  // @ 菜单：坐标是相对本组件外框的，锚点是一个 0 尺寸的定位元素
  const [at, setAt] = useState<{ left: number; top: number } | null>(null)
  const picked = useRef(false)

  /** 一个标签节点：【名字】，整块不可编辑（退格能整体删掉，不会拆成半截占位符） */
  const chip = (token: string) => {
    const r = metaRef.current.find(x => x.token === token)
    const span = document.createElement('span')
    span.className = 'tap-ptag ' + (r?.type ?? 'text')
    span.contentEditable = 'false'
    span.dataset.token = token
    span.textContent = `【${tokenLabel(token, Object.fromEntries(
      metaRef.current.map(x => [x.token, x.label])))}】`
    return span
  }

  const build = (v: string) => {
    const host = el.current
    if (!host) return
    host.textContent = ''
    for (const p of parsePrompt(v)) {
      if (p.token) host.appendChild(chip(p.token))
      else for (const [i, line] of (p.text ?? '').split('\n').entries()) {
        if (i) host.appendChild(document.createElement('br'))
        if (line) host.appendChild(document.createTextNode(line))
      }
    }
  }

  useEffect(() => {
    if (value === last.current && el.current?.childNodes.length) return
    last.current = value
    build(value)
  }, [value])   // eslint-disable-line react-hooks/exhaustive-deps

  const emit = () => {
    if (!el.current) return
    const s = serializePrompt(el.current)
    last.current = s
    onChange(s)
  }

  /** 光标处在哪：折叠光标在部分浏览器下 rect 全 0，插个零宽标记量一下再撤掉 */
  const caretPoint = (): { left: number; top: number } | null => {
    const box = el.current?.parentElement
    const sel = window.getSelection()
    if (!box || !sel?.rangeCount) return null
    const range = sel.getRangeAt(0)
    let rect = range.getBoundingClientRect()
    if (!rect.width && !rect.height) {
      const mark = document.createElement('span')
      mark.textContent = '​'
      range.insertNode(mark)
      rect = mark.getBoundingClientRect()
      mark.remove()
      sel.collapseToEnd()
    }
    const b = box.getBoundingClientRect()
    return { left: rect.left - b.left, top: rect.bottom - b.top }
  }

  /** 在光标处插入一个行内标签 */
  const insert = (r: TapCtxRef) => {
    const host = el.current
    if (!host) return
    const node = chip(r.token)
    const sel = window.getSelection()
    const range = sel?.rangeCount ? sel.getRangeAt(0) : null
    if (range && host.contains(range.commonAncestorContainer)) {
      range.deleteContents()
      range.insertNode(node)
      range.setStartAfter(node)
      range.collapse(true)
      sel!.removeAllRanges()
      sel!.addRange(range)
    } else {
      host.appendChild(node)
    }
    host.focus()
    emit()
  }

  /** 光标处插入一段纯文本（@ 菜单没选就把 @ 本身补回去） */
  const insertText = (t: string) => {
    el.current?.focus()
    document.execCommand('insertText', false, t)
  }

  return (
    <div className="tap-charter-wrap">
      <div
        ref={el} className="tap-charter-area" contentEditable suppressContentEditableWarning
        role="textbox" tabIndex={0} aria-multiline data-placeholder={placeholder}
        onInput={emit}
        onBlur={emit}
        // 粘贴一律取纯文本：带样式的 HTML 进来会把标签结构搅乱
        onPaste={e => {
          e.preventDefault()
          insertText(e.clipboardData.getData('text/plain'))
        }}
        onKeyDown={e => {
          // 画布在外层监听空格平移、滚轮缩放——编辑时别让它们冒泡出去
          e.stopPropagation()
          if (e.key !== '@' || at) return
          // @ 不真的打进正文：拦下来开菜单，没选中再把 @ 补回去
          e.preventDefault()
          picked.current = false
          setAt(caretPoint())
        }}
        onWheel={e => e.stopPropagation()} />
      {at && (
        <span className="tap-at-anchor" style={{ left: at.left, top: at.top }}>
          <TapPickMenu
            groups={refGroups(upstream, t => refs.some(r => r.token === t), catalog.queryTools)}
            onPick={raw => {
              const r = unpackRef(raw)
              picked.current = true
              onAddRef?.(r)
              setAt(null)
              // 等引用登记进清单再插标签，否则标签解析不出名字
              setTimeout(() => insert(r), 0)
            }}
            onClose={() => {
              setAt(null)
              if (!picked.current) insertText('@')
            }} />
        </span>
      )}
    </div>
  )
}
