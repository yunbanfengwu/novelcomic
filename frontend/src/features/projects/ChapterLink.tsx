import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import type { Chapter } from '../../api'
import { Icon } from '../../components/Icon'

/** A chapter link with a hover action menu. */
export function ChapterLink({ pid, c, onDelete }: {
  pid: number
  c: Chapter
  onDelete?: (chapter: Chapter) => Promise<void> | void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const remove = async (event: React.MouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    if (!onDelete || busy) return
    setBusy(true)
    try {
      await onDelete(c)
      setMenuOpen(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={'cat-item-wrap' + (menuOpen ? ' menu-open' : '')}>
      <NavLink to={`/project/${pid}/body/${c.seq}`}
        className={({ isActive }) => 'cat-item' + (isActive ? ' active' : '')}
        title={`第${c.seq}集 ${c.title}`}>
        <span className="cat-num">{c.seq}</span>
        <span className="cat-title">{c.title}</span>
      </NavLink>
      {onDelete && <>
        <button className="cat-more" type="button" aria-label={`第${c.seq}集更多操作`}
          aria-expanded={menuOpen} title="更多操作"
          onClick={event => {
            event.preventDefault()
            event.stopPropagation()
            setMenuOpen(open => !open)
          }}>
          <Icon name="more" />
        </button>
        {menuOpen && <div className="cat-menu" role="menu">
          <button className="cat-menu-delete" type="button" role="menuitem" disabled={busy}
            onClick={remove}>
            <Icon name={busy ? 'spinner' : 'trash'} spin={busy} /> 删除本集
          </button>
        </div>}
      </>}
    </div>
  )
}
