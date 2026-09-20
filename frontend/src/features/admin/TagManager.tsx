import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Tag, TagGroup } from '../../api'
import { TagGroupRail } from './TagGroupRail'
import { TagGrid } from './TagGrid'
import { TagEditor } from './TagEditor'

/** 标签库容器：左栏分组（视频类型/风格类型内置受保护 + 自定义）/ 右栏该组标签卡片。
 * 标签含 名称/code/缩略图；条目打标复用 kb_entries.tags（存 code）。 */
export function TagManager() {
  const [groups, setGroups] = useState<TagGroup[]>([])
  const [selId, setSelId] = useState<number | null>(null)
  const [editing, setEditing] = useState<Partial<Tag> | null>(null)
  const [err, setErr] = useState('')

  const load = async () => {
    const gs = await api.listTagGroups()
    setGroups(gs)
    setSelId(s => (s && gs.some(g => g.id === s)) ? s : (gs[0]?.id ?? null))
  }
  useEffect(() => { load().catch(e => setErr(String(e))) }, [])

  const sel = groups.find(g => g.id === selId) || null
  const guard = (fn: () => Promise<unknown>) => fn().then(load).catch(e => setErr(String(e)))

  const addGroup = (code: string, title: string) => guard(() => api.createTagGroup({ code, title }))
  const renameGroup = (id: number, title: string) => guard(() => api.updateTagGroup(id, { title }))
  const delGroup = (id: number) => guard(() => api.deleteTagGroup(id))
  const delTag = (id: number) => guard(() => api.deleteTag(id))
  const saveTag = async (t: Partial<Tag>) => {
    if (t.id) await api.updateTag(t.id, { name: t.name!, thumbnail_url: t.thumbnail_url || undefined })
    else await api.createTag({ group_id: selId!, code: t.code!, name: t.name!, thumbnail_url: t.thumbnail_url || undefined })
    setEditing(null)
    await load()
  }

  return (
    <div className="tag-mgr">
      {err && <div className="tag-err" onClick={() => setErr('')}>{err}</div>}
      <TagGroupRail groups={groups} selId={selId} onSelect={setSelId}
        onAdd={addGroup} onRename={renameGroup} onDelete={delGroup} />
      <TagGrid group={sel}
        onNew={() => setEditing({ name: '', code: '', thumbnail_url: '' })}
        onEdit={t => setEditing(t)} onDelete={delTag} />
      {editing && (
        <TagEditor tag={editing} onSave={saveTag} onCancel={() => setEditing(null)} />
      )}
    </div>
  )
}
