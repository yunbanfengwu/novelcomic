import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Tag } from '../../api'
import { Icon } from '../../components/Icon'

/** 标签编辑小弹层：名称 / code（新建可填、编辑锁定）/ 缩略图 URL。仿 KbEntryEditor 的 portal+Esc。 */
export function TagEditor({ tag, onSave, onCancel }: {
  tag: Partial<Tag>
  onSave: (t: Partial<Tag>) => Promise<void>
  onCancel: () => void
}) {
  const [t, setT] = useState<Partial<Tag>>(tag)
  const [saving, setSaving] = useState(false)
  const patch = (p: Partial<Tag>) => setT(v => ({ ...v, ...p }))

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  const save = async () => {
    if (!t.name?.trim() || (!t.id && !t.code?.trim())) return
    setSaving(true)
    try { await onSave({ ...t, name: t.name.trim(), code: t.code?.trim() }) }
    finally { setSaving(false) }
  }

  return createPortal(
    <div className="kbe-overlay" onClick={() => { if (!saving) onCancel() }}>
      <div className="kbe-modal tag-editor" onClick={e => e.stopPropagation()}>
        <div className="kbe-head">
          <b>{t.id ? `编辑标签 #${t.id}` : '新建标签'}</b>
          <button className="kbe-close" title="关闭 (Esc)" onClick={onCancel}>✕</button>
        </div>
        <div className="kbe-body">
          <input placeholder="名称（如 迪士尼）" value={t.name || ''} autoFocus
            onChange={e => patch({ name: e.target.value })} />
          <input placeholder="code（英文唯一，如 disney；建后不可改）" value={t.code || ''}
            disabled={!!t.id} onChange={e => patch({ code: e.target.value })} />
          <div className="tag-thumb-edit">
            {t.thumbnail_url && <img className="tag-card-thumb" src={t.thumbnail_url} alt="缩略图" />}
            <input placeholder="缩略图 URL（可选）" value={t.thumbnail_url || ''}
              onChange={e => patch({ thumbnail_url: e.target.value })} />
          </div>
        </div>
        <div className="btns kbe-foot">
          <button disabled={saving} onClick={save}>
            {saving ? <Icon name="spinner" spin /> : <Icon name="save" />} 保存
          </button>
          <button className="ghost" disabled={saving} onClick={onCancel}>取消</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
