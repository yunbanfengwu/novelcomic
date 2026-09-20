import { useState } from 'react'
import { api } from '../../../api'
import type { StagedMaterial } from '../../../api'
import { Icon } from '../../../components/Icon'
import { GUIDE_STEPS } from '../../../lib/guideSteps'
import { GuideRail } from './GuideRail'
import { BasicInfoStep } from './steps/BasicInfoStep'
import { MaterialsStep } from './steps/MaterialsStep'
import { StyleStep } from './steps/StyleStep'
import { PreviewStep } from './steps/PreviewStep'

/** 引导各步暂存的基本信息/风格字段（空=创建时由 AI 按草稿初拟） */
export interface GuideInfo {
  title: string; synopsis: string; storyline: string
  writing_style: string; art_style: string
  character_mode?: 'real' | 'virtual'
  /** 主项目类型（视频类型标签 code），兼容多标签 tags。 */
  project_type?: string
  /** 项目类型标签（来自标签库，如 brand_ad / film_drama）。 */
  tags?: string[]
}

/**
 * 引导式新建项目（独立可复用组件，非仅弹框用）：左列步骤、右列输入/对话区。
 * 像 macOS 开机引导——分步、每步可跳过、后续在项目里补充。
 * 全程暂存：项目只在最后一步点「创建作品」时才真正创建（唯一例外：文件上传即时直传 OSS 拿 URL）。
 * mode='edit'：编辑已有项目——预填现值，去掉材料/预览步，任意步右下角「保存」（onSave 落库）。
 */
export function GuidedCreate({ initialDraft = '', initialInfo, initialAspect = '16:9', mode = 'create', onDone, onSave, onExit }: {
  initialDraft?: string
  initialInfo?: GuideInfo
  initialAspect?: '16:9' | '9:16'
  mode?: 'create' | 'edit'
  onDone?: (projectId: number) => void
  onSave?: (info: GuideInfo, aspect: '16:9' | '9:16') => Promise<void>
  onExit?: () => void
}) {
  const editing = mode === 'edit'
  // 新建时把“基本信息”和“相关材料”合并到同一页。标题、梗概和主线
  // 由草稿解析后在最后的设定预览中确认，创建页只需要先提供草稿和材料。
  const steps = editing
    ? GUIDE_STEPS.filter(s => s.key !== 'materials' && s.key !== 'preview')
    : GUIDE_STEPS
      .filter(s => s.key !== 'materials')
      .map(s => s.key === 'basic'
        ? { ...s, label: '基本信息与材料', hint: '输入小说草稿，也可以补充已有小说或参考资料；标题、梗概和主线将在设定预览中确认。' }
        : s)
  const [draft, setDraft] = useState(initialDraft)
  const [info, setInfo] = useState<GuideInfo>(initialInfo ?? {
    title: '', synopsis: '', storyline: '', writing_style: '', art_style: '', character_mode: 'virtual', tags: [],
  })
  const [materials, setMaterials] = useState<StagedMaterial[]>([])
  const [aspect, setAspect] = useState<'16:9' | '9:16'>(initialAspect)
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)

  const patchInfo = (p: Partial<GuideInfo>) => setInfo(v => ({ ...v, ...p }))
  const draftOk = draft.trim().length >= 10
  const meta = steps[step]
  const isLast = step === steps.length - 1
  const basicIdx = steps.findIndex(s => s.key === 'basic')

  const create = async () => {
    if (!draftOk) { alert('草稿至少 10 字'); setStep(basicIdx); return }
    setBusy(true)
    try {
      const p = await api.createProject({ draft: draft.trim(), ...info,
        ...(info.project_type ? { project_type: info.project_type } : {}),
        aspect_ratio: aspect, materials,
        character_mode: info.character_mode || 'virtual' })
      onDone?.(p.id)
    } catch (e) { alert(String(e)); setBusy(false) }
  }
  const save = async () => {
    setBusy(true)
    try { await onSave?.(info, aspect) } catch (e) { alert(String(e)) } finally { setBusy(false) }
  }

  const body = () => {
    if (meta.key === 'basic')
      return <div className="guide-combined-basic">
        <BasicInfoStep draft={draft} setDraft={setDraft} info={info} onPatch={patchInfo} noDraft={editing} />
        {!editing && <MaterialsStep materials={materials}
          onAdd={m => setMaterials(v => [...v, m])}
          onRemove={i => setMaterials(v => v.filter((_, k) => k !== i))} />}
      </div>
    if (meta.key === 'materials')
      return <MaterialsStep materials={materials}
        onAdd={m => setMaterials(v => [...v, m])}
        onRemove={i => setMaterials(v => v.filter((_, k) => k !== i))} />
    if (meta.key === 'preview')
      return <PreviewStep draft={draft} info={info} materials={materials} aspect={aspect}
        onJump={setStep} steps={steps} />
    // key 使内容设定↔画面设定切换时重挂（清空各自的微调指令输入）；画面设定步含比例选择
    // 编辑模式无草稿，AI 评估的上下文以梗概代草稿
    return <StyleStep key={meta.key} kind={meta.key === 'writing' ? 'writing' : 'art'}
      value={meta.key === 'writing' ? info.writing_style : info.art_style}
      context={{ draft: editing ? info.synopsis : draft, title: info.title, synopsis: info.synopsis }}
      aspect={meta.key === 'art' ? aspect : undefined} onAspect={setAspect}
      videoTags={meta.key === 'art' ? (info.tags || []) : undefined}
      onVideoTags={tags => patchInfo({ tags, project_type: tags[0] })}
      onChange={v => patchInfo(meta.key === 'writing' ? { writing_style: v } : { art_style: v })} />
  }

  return (
    <div className="guide-shell">
      <GuideRail active={step} onJump={setStep} steps={steps}
        title={editing ? '编辑设定' : '新建作品'}
        foot={editing ? '各步可随时跳转修改，点右下角「保存」统一落库生效。' : undefined} />
      <div className="guide-pane">
        <header className="guide-pane-head">
          <div>
            <h2><Icon name={meta.icon} /> {meta.label}</h2>
            <p className="dim">{meta.hint}</p>
          </div>
          {onExit && <button className="modal-x" title="关闭" onClick={() => !busy && onExit()}>✕</button>}
        </header>
        <div className="guide-pane-body">{body()}</div>
        <footer className="guide-pane-foot">
          <button className="small ghost" disabled={step === 0 || busy} onClick={() => setStep(s => s - 1)}>
            ‹ 上一步
          </button>
          <div className="guide-foot-right">
            {!isLast && (
              <button className="small ghost" disabled={busy}
                onClick={() => setStep(s => s + 1)}>下一步 ›</button>
            )}
            {/* 新建：创建按钮仅在最后一步（设定预览），全部暂存值随这一次提交落库；编辑：任意步都可保存 */}
            {editing ? (
              <button className="small" disabled={busy} onClick={save}>
                {busy ? <><Icon name="spinner" spin /> 保存中…</> : <><Icon name="check" /> 保存</>}
              </button>
            ) : isLast && (
              <button className="small" disabled={busy || !draftOk}
                title={!draftOk ? '草稿至少 10 字（「基本信息」步）' : undefined}
                onClick={create}>
                {busy ? <><Icon name="spinner" spin /> 创建中…</> : <><Icon name="rocket" /> 创建作品</>}
              </button>
            )}
          </div>
        </footer>
      </div>
    </div>
  )
}
