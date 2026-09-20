import { useState } from 'react'
import { api } from '../../api'
import type { KbEntry } from '../../api'
import { Icon } from '../../components/Icon'

/** 库内排序权重小控件（音色库/角色库卡片用）：失焦或回车即存，成功后回调重排。越大越靠前。 */
export function KbWeightControl({ entry, onSaved }: { entry: KbEntry; onSaved: () => void }) {
  const base = entry.weight ?? 0
  const [w, setW] = useState(base)
  const [busy, setBusy] = useState(false)

  const commit = async () => {
    if (w === base) return
    setBusy(true)
    try { await api.setKbWeight(entry.id, w); onSaved() }
    catch (e) { alert(String(e)); setW(base) } finally { setBusy(false) }
  }

  return (
    <label className="kb-weight-ctl" title="权重：库内排序，越大越靠前">
      <span className="dim">权重</span>
      <input type="number" value={w} disabled={busy}
        onChange={e => setW(Number(e.target.value) || 0)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
      {busy && <Icon name="spinner" spin />}
    </label>
  )
}
