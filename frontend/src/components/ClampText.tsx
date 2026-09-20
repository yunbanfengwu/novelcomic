import { useEffect, useRef, useState } from 'react'
import './ClampText.css'

/** 长文本折叠：默认 4 行截断，超出显示"更多"，点击展开/收起——避免面板内嵌套滚动条 */
export function ClampText({ text, lines = 4 }: { text: string; lines?: number }) {
  const [open, setOpen] = useState(false)
  const [overflow, setOverflow] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (el) setOverflow(el.scrollHeight > el.clientHeight + 2)
  }, [text, open])
  return (
    <div>
      <div ref={ref} className={'prompt-box clamp-box' + (open ? ' open' : '')}
        style={open ? undefined : { WebkitLineClamp: lines }}>{text}</div>
      {(overflow || open) && (
        <span className="linklike" onClick={() => setOpen(o => !o)}>{open ? '收起 ▴' : '更多 ▾'}</span>
      )}
    </div>
  )
}
