import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Element } from '../../api'
import { Icon } from '../../components/Icon'

/** 场景轻量特征：人群密度/时段/氛围。手填后织入场景设定图出图（体现人流密度 + 大远景/中景两级取景）。 */
const FIELDS: { key: keyof Draft; label: string; ph: string }[] = [
  { key: '人群密度', label: '人群密度', ph: '如 空旷 / 三两行人 / 熙攘 / 人山人海' },
  { key: '时段', label: '时段', ph: '如 清晨 / 正午 / 黄昏 / 深夜' },
  { key: '氛围', label: '氛围', ph: '如 宁静祥和 / 肃杀压抑 / 喧闹市井' },
]
type Draft = { 人群密度: string; 时段: string; 氛围: string }
const emptyDraft = (): Draft => ({ 人群密度: '', 时段: '', 氛围: '' })

export function SceneProfileCard({ pid, el, onReload }: {
  pid: number; el: Element; onReload: () => void
}) {
  const profile = el.meta.profile
  const [draft, setDraft] = useState<Draft>(() => ({ ...emptyDraft(), ...(profile ?? {}) }))
  const [busy, setBusy] = useState(false)
  useEffect(() => { setDraft({ ...emptyDraft(), ...(profile ?? {}) }) }, [el.id, profile])

  const dirty = FIELDS.some(f => (draft[f.key] || '') !== ((profile?.[f.key] as string) || ''))
  const save = async () => {
    setBusy(true)
    try { await api.saveElementProfile(pid, el.id, draft); onReload() }
    catch (e) { alert(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="char-profile">
      <div className="cp-head">
        <span className="cp-title"><Icon name="scene" /> 场景特征</span>
        {dirty && (
          <button className="small" disabled={busy} onClick={save} title="保存场景特征（下次出设定图时织入）">
            {busy ? <Icon name="spinner" spin /> : <Icon name="save" />} 保存
          </button>
        )}
      </div>
      <div className="cp-fields">
        {FIELDS.map(f => (
          <label className="cp-row" key={f.key}>
            <span className="cp-label">{f.label}</span>
            <input className="cp-input" value={draft[f.key]} placeholder={f.ph}
              onChange={e => setDraft(d => ({ ...d, [f.key]: e.target.value }))} />
          </label>
        ))}
      </div>
    </div>
  )
}
