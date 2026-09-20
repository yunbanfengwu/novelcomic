import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { TrashProject } from '../../api'
import { Icon } from '../Icon'
import { fmtDateTime } from '../../lib/fmtTime'

/**
 * 项目回收站：列出已软删除的项目，可「恢复」（重回首页）或「彻底删除」（物理级联，不可恢复）。
 * onChanged：恢复/彻底删除后回调，供首页刷新项目图标。
 */
export function ProjectTrash({ onChanged }: { onChanged?: () => void }) {
  const [items, setItems] = useState<TrashProject[] | null>(null)
  const [busy, setBusy] = useState<number | null>(null)

  const load = () =>
    api.listTrash().then(setItems).catch(e => { alert((e as Error).message); setItems([]) })
  useEffect(() => { load() }, [])

  const restore = async (p: TrashProject) => {
    setBusy(p.id)
    try { await api.restoreProject(p.id); await load(); onChanged?.() }
    catch (e) { alert((e as Error).message) }
    finally { setBusy(null) }
  }
  const purge = async (p: TrashProject) => {
    if (!confirm(`彻底删除「${p.title}」？\n将永久清除该项目的目录 / 正文 / 要素 / 分镜 / 任务等全部数据，不可恢复。`)) return
    setBusy(p.id)
    try { await api.purgeProject(p.id); await load(); onChanged?.() }
    catch (e) { alert((e as Error).message) }
    finally { setBusy(null) }
  }

  if (items === null) return <div className="console-loading"><Icon name="spinner" spin /> 加载中…</div>
  if (!items.length) return (
    <div className="console-empty">
      <Icon name="trash" /><b>没有已删除的项目</b>
      <span className="dim">删除的项目会移到这里，可恢复或彻底删除</span>
    </div>
  )

  return (
    <div className="trash-list">
      {items.map(p => (
        <div key={p.id} className="trash-item">
          <div className="trash-cover">
            {p.config?.cover_url
              ? <img src={p.config.cover_url} alt="" />
              : <span>{p.title.slice(0, 1)}</span>}
          </div>
          <div className="trash-meta">
            <b title={p.title}>{p.title}</b>
            <span className="dim">删除于 {fmtDateTime(p.deleted_at)}</span>
          </div>
          <div className="trash-acts">
            <button className="ghost small" disabled={busy === p.id} onClick={() => restore(p)}>
              <Icon name="undo" /> 恢复
            </button>
            <button className="ghost small trash-purge" disabled={busy === p.id} onClick={() => purge(p)}>
              <Icon name="trash" /> 彻底删除
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
