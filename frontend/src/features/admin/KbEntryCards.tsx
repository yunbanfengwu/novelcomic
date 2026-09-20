import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api'
import type { KbEntry, KbFolder } from '../../api'
import { KbEntryEditor } from './KbEntryEditor'
import { KbStyleCard } from './KbStyleCard'
import { KbStyleDetail } from './KbStyleDetail'

/** 缩略图大卡布局（画风库）：卡片点开放大详情（右侧改提示词/重新出图）；右上角三竖点菜单编辑/删除。
 * actionsEl：文件夹 header 挂载点——「新增条目」提升到标题同一行。 */
export function KbEntryCards({ folder, onCountChanged, actionsEl }: {
  folder: KbFolder
  onCountChanged: () => void
  actionsEl?: HTMLElement | null
}) {
  const [entries, setEntries] = useState<KbEntry[]>([])
  const [editing, setEditing] = useState<Partial<KbEntry> | null>(null)
  const [detail, setDetail] = useState<KbEntry | null>(null)

  const reload = useCallback(() => {
    api.listKb({ folder_id: folder.id }).then(setEntries)
  }, [folder.id])
  useEffect(() => { reload() }, [reload])

  // 详情打开时用列表最新数据同步（重新出图/保存后缩略图与提示词及时反映）
  const detailLive = detail ? entries.find(e => e.id === detail.id) ?? detail : null

  const save = async (e: Partial<KbEntry>) => {
    if (!e.name?.trim()) { alert('名称必填'); return }
    try {
      if (e.id) await api.updateKb(e.id, e)
      else await api.createKb(e)
      setEditing(null); reload(); onCountChanged()
    } catch (err) { alert(String(err)) }
  }
  const remove = async (e: KbEntry) => {
    if (!confirm(`确认删除「${e.title || e.name}」？`)) return
    await api.deleteKb(e.id); reload(); onCountChanged()
  }

  const toolbar = (
    <div className="btns kbv-toolbar">
      <button onClick={() => setEditing({
        scope: 'global', kind: folder.kind || 'prompt_block', category: folder.category,
        name: '', title: '', description: '', content: '', tags: [], meta: {}, weight: 0, enabled: true,
      })}>＋新增条目</button>
    </div>
  )

  return (
    <div>
      {actionsEl ? createPortal(toolbar, actionsEl) : toolbar}
      {editing && <KbEntryEditor key={editing.id ?? 'new'} entry={editing}
        onSave={save} onCancel={() => setEditing(null)} />}
      <div className="kb-cards">
        {entries.map(e => (
          <KbStyleCard key={e.id} entry={e}
            onOpen={setDetail} onEdit={setEditing} onDelete={remove} />
        ))}
      </div>
      {!entries.length && <div className="card dim">暂无条目，点击"＋新增条目"添加。</div>}
      {detailLive && <KbStyleDetail entry={detailLive}
        onClose={() => setDetail(null)} onSaved={() => { reload(); onCountChanged() }} />}
    </div>
  )
}
