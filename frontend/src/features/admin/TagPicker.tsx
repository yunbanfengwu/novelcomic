import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { TagGroup } from '../../api'
import { Icon } from '../../components/Icon'

/** 知识库条目打标选择器：按分组展示可点选标签 chip，多选，选中集合=条目 tags（存 code）。 */
export function TagPicker({ value, onChange }: {
  value: string[]
  onChange: (codes: string[]) => void
}) {
  const [groups, setGroups] = useState<TagGroup[]>([])
  useEffect(() => { api.listTagGroups().then(setGroups).catch(() => {}) }, [])

  const sel = new Set(value)
  const toggle = (code: string) => {
    const next = new Set(sel)
    if (next.has(code)) next.delete(code); else next.add(code)
    onChange([...next])
  }
  if (!groups.length) return null

  return (
    <div className="tag-picker">
      <div className="dim tag-picker-label"><Icon name="tag" /> 标签（可多选，选中项将随本条目引用时自带）</div>
      {groups.map(g => (
        <div key={g.id} className="tag-picker-group">
          <span className="tag-picker-gtitle dim">{g.title}</span>
          <div className="tag-picker-chips">
            {g.tags.map(t => (
              <button key={t.id} type="button"
                className={`tag-chip${sel.has(t.code) ? ' active' : ''}`}
                onClick={() => toggle(t.code)}>
                {sel.has(t.code) && <Icon name="check" />} {t.name}
              </button>
            ))}
            {!g.tags.length && <span className="dim tag-picker-none">（无标签）</span>}
          </div>
        </div>
      ))}
    </div>
  )
}
