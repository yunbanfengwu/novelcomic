import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { CaseEntry, CaseGroup } from '../../api'
import { Icon } from '../../components/Icon'
import { CaseEntryCard } from './CaseEntryCard'
import { CaseEntryEditor } from './CaseEntryEditor'

/** 案例库容器：分组过滤 + 案例列表 + 新建/编辑（浏览型资料，与知识库分离，不参与召回） */
export function CaseLibrary() {
  const [groups, setGroups] = useState<CaseGroup[]>([])
  const [entries, setEntries] = useState<CaseEntry[]>([])
  const [groupId, setGroupId] = useState<number | 'all'>('all')
  const [editing, setEditing] = useState<Partial<CaseEntry> | null>(null)

  const reload = useCallback(() => {
    api.listCaseGroups().then(setGroups)
    api.listCaseEntries().then(setEntries)
  }, [])
  useEffect(() => { reload() }, [reload])

  const shown = groupId === 'all' ? entries : entries.filter(e => e.group_id === groupId)

  const addGroup = async () => {
    const title = prompt('分组名（如：游戏制作 · 场景设计）')?.trim()
    if (!title) return
    try { await api.createCaseGroup(title); reload() } catch (e) { alert((e as Error).message) }
  }
  const renameGroup = async (g: CaseGroup) => {
    const title = prompt('新分组名', g.title)?.trim()
    if (!title || title === g.title) return
    try { await api.updateCaseGroup(g.id, { title, seq: g.seq }); reload() } catch (e) { alert((e as Error).message) }
  }
  const delGroup = async (g: CaseGroup) => {
    if (!confirm(`删除分组「${g.title}」？\n组内 ${g.count} 个案例将变为未分组（不删除案例）`)) return
    try { await api.deleteCaseGroup(g.id); if (groupId === g.id) setGroupId('all'); reload() }
    catch (e) { alert((e as Error).message) }
  }
  const delEntry = async (e: CaseEntry) => {
    if (!confirm(`删除案例「${e.title || `#${e.id}`}」？`)) return
    try { await api.deleteCaseEntry(e.id); reload() } catch (err) { alert((err as Error).message) }
  }
  const save = async (e: Partial<CaseEntry>) => {
    if (e.id) await api.updateCaseEntry(e.id, e)
    else await api.createCaseEntry({ ...e, group_id: e.group_id ?? (groupId === 'all' ? null : groupId) })
    setEditing(null); reload()
  }

  return (
    <div className="adm-panel">
      <div className="adm-head">
        <h2><Icon name="clapper" /> 案例库</h2>
        <div className="adm-actions">
          <span className="dim">{shown.length} 个案例 · 仅供浏览参考，不参与知识召回</span>
          <button className="small" onClick={() => setEditing({ group_id: groupId === 'all' ? null : groupId })}>
            <Icon name="folderplus" /> 新建案例
          </button>
        </div>
      </div>
      <div className="cl-groups">
        <button className={`seg-btn${groupId === 'all' ? ' active' : ''}`} onClick={() => setGroupId('all')}>
          全部（{entries.length}）
        </button>
        {groups.map(g => (
          <button key={g.id} className={`seg-btn${groupId === g.id ? ' active' : ''}`}
            onClick={() => setGroupId(g.id)}
            onDoubleClick={() => renameGroup(g)}
            onContextMenu={ev => { ev.preventDefault(); delGroup(g) }}
            title="双击改名 · 右键删除">
            {g.title}（{g.count}）
          </button>
        ))}
        <button className="seg-btn" onClick={addGroup} title="新建分组"><Icon name="folderplus" /></button>
      </div>
      {editing && (
        <CaseEntryEditor entry={editing} groups={groups}
          onSave={save} onCancel={() => setEditing(null)} />
      )}
      <div className="cl-list">
        {shown.map(e => (
          <CaseEntryCard key={e.id} entry={e}
            onEdit={() => setEditing(e)} onDelete={() => delEntry(e)} />
        ))}
        {shown.length === 0 && !editing && <div className="dim cl-empty">暂无案例，点右上「新建案例」开始</div>}
      </div>
    </div>
  )
}
