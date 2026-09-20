import { useState } from 'react'
import { api } from '../../../../api'
import { Icon } from '../../../../components/Icon'
import type { GuideInfo } from '../GuidedCreate'

/**
 * 基本信息步（全暂存）：草稿（首页输入自动带入）+ 书名/梗概/主线可预填。
 * 留空字段由 AI 在最后一步创建时按草稿初拟；填了的覆盖 AI 初拟。
 * 草稿框右下角星标：按草稿一键智能生成书名/梗概/主线（草稿态，回填后仍可再改）。
 */
export function BasicInfoStep({ draft, setDraft, info, onPatch, noDraft = false }: {
  draft: string
  setDraft: (v: string) => void
  info: GuideInfo
  onPatch: (patch: Partial<GuideInfo>) => void
  noDraft?: boolean  // 编辑已有项目：无草稿概念，只改书名/梗概/主线
}) {
  const [busy, setBusy] = useState(false)
  const draftOk = draft.trim().length >= 10

  const gen = async () => {
    if (!draftOk) { alert('草稿至少 10 字'); return }
    setBusy(true)
    try {
      const r = await api.draftInfo(draft.trim())
      onPatch({ title: r.title, synopsis: r.synopsis, storyline: r.storyline })
    } catch (e) { alert(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="guide-form">
      {!noDraft && <>
      <label className="modal-label" htmlFor="g-draft">小说草稿 / 构思（必填，至少 10 字）</label>
      <div className="guide-draft-wrap">
        <textarea id="g-draft" className="modal-textarea guide-draft" value={draft} autoFocus={!draft}
          onChange={e => setDraft(e.target.value)}
          placeholder="粘贴你的小说草稿或一句话构思，AI 会据此拟定书名、梗概、文风与画风…" />
        <button type="button" className="guide-draft-gen" disabled={busy || !draftOk}
          title={draftOk ? '一键智能生成下方书名、梗概、主线（回填后仍可再改）' : '草稿至少 10 字'}
          onClick={gen}>
          {busy ? <Icon name="spinner" spin /> : <Icon name="sparkles" />}
        </button>
      </div>
      <div className="modal-sep"><span>以下可留空，创建时由 AI 按草稿初拟</span></div>
      </>}
      {noDraft && <>
      <label className="modal-label">项目角色类型（必选）</label>
      <div className="btns">
        <button type="button"
          className={info.character_mode === 'real' ? 'primary' : 'small'}
          onClick={() => onPatch({ character_mode: 'real' })}>
          <Icon name="user" /> 真人
        </button>
        <button type="button"
          className={info.character_mode !== 'real' ? 'primary' : 'small'}
          onClick={() => onPatch({ character_mode: 'virtual' })}>
          <Icon name="wand" /> 虚拟形象
        </button>
      </div>
      <p className="dim">
        {info.character_mode === 'real'
          ? '真人：五官绑定系统管理中的备案角色；项目角色卡只生成服饰、发饰、动作和道具造型。'
          : '虚拟形象：角色卡生成完整外貌、五官与服化道。'}
      </p>
      <label className="modal-label" htmlFor="g-title">书名</label>
      <input id="g-title" className="modal-input" value={info.title}
        onChange={e => onPatch({ title: e.target.value })}
        placeholder="留空 = AI 拟定" />
      <label className="modal-label" htmlFor="g-syn">故事梗概</label>
      <textarea id="g-syn" className="modal-textarea" value={info.synopsis}
        onChange={e => onPatch({ synopsis: e.target.value })}
        placeholder="主角、核心冲突、世界观钩子（留空 = AI 拟定）" />
      <label className="modal-label" htmlFor="g-story">主线故事线</label>
      <textarea id="g-story" className="modal-textarea" value={info.storyline}
        onChange={e => onPatch({ storyline: e.target.value })}
        placeholder="起点→关键转折→终局的一句话主线 + 卷级走向（留空 = AI 拟定）" />
      </>}
    </div>
  )
}
