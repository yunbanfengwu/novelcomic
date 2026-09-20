import type { ReactNode } from 'react'
import './SubNav.css'

export type SubItem = { key: string; icon: ReactNode; label: string }

/** 页面可选用的二级菜单（属于页面内容，非框架强制）。放在看板内作为第一列。 */
export function SubNav({ title, items, active, onSelect }: {
  title?: ReactNode; items: SubItem[]; active?: string; onSelect?: (key: string) => void
}) {
  return (
    <aside className="subnav">
      {title && <div className="subnav-head">{title}</div>}
      <div className="subnav-menu">
        {items.map(it => (
          <button key={it.key} className={`subnav-item${active === it.key ? ' active' : ''}`}
            onClick={() => onSelect?.(it.key)}>
            <span className="subnav-ico">{it.icon}</span><span>{it.label}</span>
          </button>
        ))}
      </div>
    </aside>
  )
}
