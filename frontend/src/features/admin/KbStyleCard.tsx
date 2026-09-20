import { useEffect, useRef, useState } from 'react'
import type { KbEntry } from '../../api'
import { Icon } from '../../components/Icon'

/** 画风卡片：缩略图大卡，点卡放大查看；右上角三竖点菜单浮出编辑/删除。纯展示，操作回调上抛。 */
export function KbStyleCard({ entry, onOpen, onEdit, onDelete }: {
  entry: KbEntry
  onOpen: (e: KbEntry) => void
  onEdit: (e: KbEntry) => void
  onDelete: (e: KbEntry) => void
}) {
  const [menu, setMenu] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menu) return
    const close = (ev: MouseEvent) => { if (!ref.current?.contains(ev.target as Node)) setMenu(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menu])

  return (
    <div className={'kb-card kb-style-card' + (menu ? ' menu-open' : '')} ref={ref}>
      <button className="kb-kebab" title="更多" onClick={() => setMenu(m => !m)}><Icon name="more" /></button>
      {!!entry.weight && <span className="kb-weight-badge" title="展示/搜索排序权重">{entry.weight}</span>}
      {menu && (
        <div className="kb-menu">
          <button onClick={() => { setMenu(false); onEdit(entry) }}><Icon name="pen" /> 编辑</button>
          <button className="danger" onClick={() => { setMenu(false); onDelete(entry) }}>
            <Icon name="cross" /> 删除
          </button>
        </div>
      )}
      <button className="kb-card-open" title="点击放大查看" onClick={() => onOpen(entry)}>
        {entry.thumbnail_url
          ? <img className="kb-card-thumb" src={entry.thumbnail_url} alt={entry.name} />
          : <div className="kb-card-thumb kb-card-thumb-empty"><Icon name="palette" /></div>}
        <div className="kb-card-body">
          <b>{entry.title || entry.name}</b>
          <span className="dim">{entry.content || entry.description}</span>
        </div>
      </button>
    </div>
  )
}
