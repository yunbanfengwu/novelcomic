import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { ArkCharacter, Element } from '../../api'
import { Icon } from '../../components/Icon'
import { useGenConfig } from '../../lib/useGenConfig'
import { ArkLibraryButton } from './ArkLibraryButton'

/** 角色结构化档案：年龄/性别/身份/时代服饰/体貌可编辑 + AI 按项目年代背景补全。
 * 批量抽取不再产外貌——外貌由此后置生成（治"古装现代脸"）；派生的英文外貌提示词落 meta.外貌提示词，
 * 展示与再改写走上层 ElementPreview 的公共图片生成弹框。 */
const FIELDS: { key: keyof Draft; label: string; area?: boolean }[] = [
  { key: '年龄段', label: '年龄段' },
  { key: '性别', label: '性别' },
  { key: '身份称谓', label: '身份称谓' },
  { key: '身份', label: '身份' },
  { key: '时代服饰', label: '时代服饰', area: true },
  { key: '体貌', label: '体貌', area: true },
  { key: '招牌动作', label: '招牌动作', area: true },
  { key: '招牌眼神', label: '招牌眼神', area: true },
]
type Draft = {
  年龄段: string; 性别: string; 身份称谓: string; 身份: string; 时代服饰: string; 体貌: string
  招牌动作: string; 招牌眼神: string
}
const emptyDraft = (): Draft => ({
  年龄段: '', 性别: '', 身份称谓: '', 身份: '', 时代服饰: '', 体貌: '',
  招牌动作: '', 招牌眼神: '',
})
const toDraft = (el: Element): Draft => ({ ...emptyDraft(), ...(el.meta.profile ?? {}) })

export function CharacterProfile({ pid, el, onReload }: {
  pid: number; el: Element; onReload: () => void
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(el))
  const [busy, setBusy] = useState<'' | 'gen' | 'save'>('')
  const [hints, setHints] = useState('')
  const [showHints, setShowHints] = useState(false)
  const [identities, setIdentities] = useState<ArkCharacter[]>([])
  // 系统配置关掉「允许项目直传火山」时隐藏入口，统一到角色库管理；加载中(null)先按默认允许，避免闪隐
  const allowArkUpload = useGenConfig()?.allow_project_ark_upload !== false
  const profile = el.meta.profile
  const hasProfile = FIELDS.some(f => (profile?.[f.key] ?? '').trim())

  // 切换角色 / 补档回填后，用库内值重置草稿（避免残留上一个角色的编辑）
  useEffect(() => {
    setDraft({ ...emptyDraft(), ...(profile ?? {}) }); setHints(''); setShowHints(false)
  }, [el.id, profile])
  useEffect(() => {
    api.listArkCharacters().then(rows =>
      setIdentities(rows.filter(c => c.ark_status === 'active' && !!c.ark_asset_id))
    ).catch(console.error)
  }, [])

  const dirty = FIELDS.some(f => (draft[f.key] || '') !== ((el.meta.profile?.[f.key] as string) || ''))

  const gen = async () => {
    setBusy('gen')
    try { await api.genElementProfile(pid, el.id, hints.trim() || undefined); onReload() }
    catch (e) { alert(String(e)) } finally { setBusy('') }
  }
  const save = async () => {
    setBusy('save')
    try { await api.saveElementProfile(pid, el.id, draft); onReload() }
    catch (e) { alert(String(e)) } finally { setBusy('') }
  }
  const bindIdentity = async (raw: string) => {
    setBusy('save')
    try {
      await api.bindCharacterIdentity(pid, el.id, raw ? Number(raw) : null)
      onReload()
    } catch (e) { alert(String(e)) } finally { setBusy('') }
  }

  return (
    <div className="char-profile">
      <div className="cp-head">
        <span className="cp-title"><Icon name="idcard" /> 角色档案</span>
        <div className="btns">
          {allowArkUpload && <ArkLibraryButton pid={pid} el={el} />}
          {dirty && (
            <button className="small" disabled={!!busy} onClick={save} title="保存手改的档案字段">
              {busy === 'save' ? <Icon name="spinner" spin /> : <Icon name="save" />} 保存
            </button>
          )}
          <button className="small ghost" disabled={!!busy}
            onClick={() => setShowHints(s => !s)} title="补全前可填年龄/身份/年代等要点">
            <Icon name="pen" /> 要点
          </button>
          <button className="small" disabled={!!busy} onClick={gen}
            title="按项目年代背景 AI 补全档案与外貌提示词（会覆盖现有外貌）">
            {busy === 'gen' ? <><Icon name="spinner" spin /> 生成中…</>
              : <><Icon name="wand" /> {hasProfile ? '重新补全' : 'AI补全档案'}</>}
          </button>
        </div>
      </div>
      {showHints && (
        <input className="cp-hints" value={hints} placeholder="可选补充要点：如 二十岁上下 / 落魄书生 / 左脸有疤"
          onChange={e => setHints(e.target.value)} />
      )}
      <div className="cp-row">
        <span className="cp-label">备案五官</span>
        <select className="cp-input" value={String(el.meta.identity_character_id || '')}
          disabled={!!busy} onChange={e => bindIdentity(e.target.value)}>
          <option value="">未绑定（真人项目需选择）</option>
          {identities.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        {el.meta.identity_image_url && (
          <img src={el.meta.identity_image_url} alt={el.meta.identity_character_name || '备案角色'}
            title="固定五官身份；当前角色卡只负责服化道、发饰与动作"
            style={{ width: 42, height: 42, objectFit: 'cover', borderRadius: 6 }} />
        )}
      </div>
      {hasProfile || dirty ? (
        <div className="cp-fields">
          {FIELDS.map(f => (
            <label className="cp-row" key={f.key}>
              <span className="cp-label">{f.label}</span>
              {f.area
                ? <textarea className="cp-input" rows={2} value={draft[f.key]}
                    onChange={e => setDraft(d => ({ ...d, [f.key]: e.target.value }))} />
                : <input className="cp-input" value={draft[f.key]}
                    onChange={e => setDraft(d => ({ ...d, [f.key]: e.target.value }))} />}
            </label>
          ))}
        </div>
      ) : (
        <p className="dim cp-empty">尚无档案。点「AI补全档案」按项目年代背景生成年龄/身份/时代服饰与外貌提示词。</p>
      )}
    </div>
  )
}
