import { useState } from 'react'
import type { TagGroup } from '../../api'
import { Icon } from '../../components/Icon'

/** 标签分组左栏：分组列表（内置带锁标记、不可删）+ 新建分组内联表单。 */
export function TagGroupRail({ groups, selId, onSelect, onAdd, onRename, onDelete }: {
  groups: TagGroup[]
  selId: number | null
  onSelect: (id: number) => void
  onAdd: (code: string, title: string) => void
  onRename: (id: number, title: string) => void
  onDelete: (id: number) => void
}) {
  const [adding, setAdding] = useState(false)
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')

  const submit = () => {
    if (!code.trim() || !title.trim()) return
    onAdd(code.trim(), title.trim())
    setCode(''); setTitle(''); setAdding(false)
  }

  return (
    <div className="tag-rail">
      <div className="tag-rail-head"><b>标签分组</b></div>
      <div className="tag-rail-list">
        {groups.map(g => (
          <div key={g.id} className={`tag-rail-item${selId === g.id ? ' active' : ''}`}
            onClick={() => onSelect(g.id)}>
            <span className="tag-rail-name">
              {g.system && <Icon name="lock" />} {g.title}
              <span className="dim tag-rail-count"> {g.tags.length}</span>
            </span>
            <span className="tag-rail-acts" onClick={e => e.stopPropagation()}>
              <button className="small ghost" title="重命名"
                onClick={() => { const t = prompt('分组名称', g.title); if (t?.trim()) onRename(g.id, t.trim()) }}>
                <Icon name="pen" />
              </button>
              {!g.system && (
                <button className="small ghost" title="删除分组（含其标签）"
                  onClick={() => { if (confirm(`删除分组「${g.title}」及其全部标签？`)) onDelete(g.id) }}>
                  <Icon name="trash" />
                </button>
              )}
            </span>
          </div>
        ))}
      </div>
      {adding ? (
        <div className="tag-rail-add">
          <input placeholder="code（英文唯一）" value={code} onChange={e => setCode(e.target.value)} autoFocus />
          <input placeholder="分组名称" value={title} onChange={e => setTitle(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submit() }} />
          <div className="btns">
            <button className="small" onClick={submit}><Icon name="check" /> 建组</button>
            <button className="small ghost" onClick={() => setAdding(false)}>取消</button>
          </div>
        </div>
      ) : (
        <button className="small ghost tag-rail-newbtn" onClick={() => setAdding(true)}>
          <Icon name="plus" /> 新建分组
        </button>
      )}
    </div>
  )
}
