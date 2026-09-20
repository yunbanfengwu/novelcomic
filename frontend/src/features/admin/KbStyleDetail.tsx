import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api'
import type { KbEntry } from '../../api'
import { Icon } from '../../components/Icon'
import { openLightbox } from '../../lib/lightbox'

/** 画风放大详情：左侧大图（点击看原图），右侧提示词可改 + 保存 / 重新出图（按当前提示词重出并回写）。 */
export function KbStyleDetail({ entry, onClose, onSaved }: {
  entry: KbEntry
  onClose: () => void
  onSaved: () => void
}) {
  const [pos, setPos] = useState(entry.meta?.positive || '')
  const [neg, setNeg] = useState(entry.meta?.negative || '')
  const [img, setImg] = useState(entry.thumbnail_url || '')
  const [saving, setSaving] = useState(false)
  const [regen, setRegen] = useState(false)
  const dirty = pos !== (entry.meta?.positive || '') || neg !== (entry.meta?.negative || '')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !saving && !regen) onClose() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [onClose, saving, regen])

  const persist = () => api.updateKb(entry.id!, {
    ...entry, meta: { ...entry.meta, positive: pos, negative: neg },
  })

  const save = async () => {
    setSaving(true)
    try { await persist(); onSaved() }
    catch (e) { alert(String(e)) } finally { setSaving(false) }
  }
  const reimage = async () => {
    setRegen(true)
    try {
      if (dirty) await persist()                                  // 先存改后的提示词，再据此出图
      const { thumbnail_url } = await api.genKbThumbnail(entry.id!, pos.trim() || undefined)
      setImg(thumbnail_url); onSaved()
    } catch (e) { alert(String(e)) } finally { setRegen(false) }
  }

  return createPortal(
    <div className="kbd-overlay" onClick={() => { if (!saving && !regen) onClose() }}>
      <button className="kbd-close" title="关闭 (Esc)" onClick={onClose}>✕</button>
      <div className="kbd-body" onClick={e => e.stopPropagation()}>
        <div className="kbd-main">
          {img
            ? <img className="kbd-img" src={img} alt={entry.name} title="点击查看原图"
                onClick={() => openLightbox(img, entry.title || entry.name)} />
            : <div className="kbd-img kbd-empty"><Icon name="palette" /></div>}
          {regen && <div className="kbd-regen"><Icon name="spinner" spin /> 重新出图中…</div>}
        </div>
        <aside className="kbd-side">
          <div className="kbd-title">{entry.title || entry.name}</div>
          {entry.category && <span className="tag">{entry.category}</span>}
          <label className="lb-label">正向提示词</label>
          <textarea rows={8} value={pos} onChange={e => setPos(e.target.value)}
            placeholder="描述该画风的正向提示词（重新出图即用它）" />
          <label className="lb-label">负面提示词</label>
          <textarea rows={3} value={neg} onChange={e => setNeg(e.target.value)}
            placeholder="不希望出现的元素（可空）" />
          <div className="btns kbd-foot">
            <button className="small ghost" disabled={saving || regen || !dirty} onClick={save}>
              {saving ? <Icon name="spinner" spin /> : <Icon name="save" />} 保存
            </button>
            <button className="small" disabled={saving || regen} onClick={reimage} title="按当前提示词重新生成缩略图并回写">
              {regen ? <Icon name="spinner" spin /> : <Icon name="image" />} 重新出图
            </button>
          </div>
        </aside>
      </div>
    </div>,
    document.body,
  )
}
