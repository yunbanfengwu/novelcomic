import { useState, type ReactNode } from 'react'
import { api, type ProjectAsset } from '../api'
import { Icon, type IconName } from './Icon'
import { openLightbox } from '../lib/lightbox'
import { closeElementPreview, pushElementPreview } from '../lib/elementPreview'
import type { EditRef } from '../lib/kinds'
import { historyKey, pushPromptVersion, type PromptTarget, type PromptVersion } from '../lib/promptHistory'
import { AssetPicker } from './AssetPicker'
import { GenRefList } from './GenRefList'
import { PromptHistory } from './PromptHistory'
import './ImageGenModal.css'

/** 版本历史归类维度（首帧/视频/尾帧=镜头 id，要素=要素 id，封面=项目 id）；缺省不启用历史 */
export interface GenHistory { pid: number; id: number; target: PromptTarget; seq?: number | string }

/** 宿主处理资产选取后的指令：EditRef=就地追加参考；'close'=收口弹窗（如要素关联触发异步重装配） */
export type PickResult = EditRef | 'close' | null

/** 公共图片生成弹框：封面/角色图/场景图/首帧/视频等所有「提示词→出图」共用一套固定形态，
 * 经 openElementPreview 宿主弹出。布局：左列（标题→成品图→提示词→参考卡片/胶囊）｜右列
 * 素材库面板（canPick 宿主常驻，不可收起），两列各自独立滚动；底部按钮通栏钉底居中——
 * AI 按钮（可选）+ 保存（可选）+ 唯一高亮的生成按钮。
 * 提示词与参考由宿主提供；怎么存也由宿主传入（onSave 缺省则不显示保存按钮，生成不落库）。
 * AI 按钮一钮两用：在原文下方追加修改要求 → onAiEdit 按要求改写；否则 → onRegen 重新装配。 */
export function ImageGenModal({
  icon, title, titleExtra, media, refs, off, refsHint,
  onToggleRef, onDeleteRef, pid, onPickAsset,
  prompt, placeholder, busy, busyHint, aiBusy,
  onAiEdit, aiEditTitle, onRegen, regenTitle,
  onSave, onGenerate, onApply, generateLabel, generateTitle, history,
  script, onSaveScript, footStart,
}: {
  icon: IconName
  title: string
  titleExtra?: ReactNode  // 标题右侧附加（如「手编」标记）
  media?: string          // 已出的成品图（点击放大）
  refs?: EditRef[]        // 参考池（缺省则不渲染参考区）
  off?: string[]          // 已停用的参考名
  refsHint?: string
  onToggleRef?: (name: string) => void
  onDeleteRef?: (name: string) => boolean | void  // 返回 false=取消（confirm 由宿主做）
  pid?: number            // 项目 id：与 onPickAsset 同时提供才显示「＋ 添加参考」资产面板
  onPickAsset?: (a: ProjectAsset) => PickResult | Promise<PickResult>  // 持久化由宿主做
  prompt?: string
  promptHint?: string
  placeholder?: string
  busy?: boolean          // 宿主生成任务在途
  busyHint?: string
  aiBusy?: boolean        // AI 改写在途（容器态：关弹窗再开也保持）
  onAiEdit?: (instruction: string, base: string) => Promise<string | null>
  aiEditTitle?: string
  onRegen?: (current: string) => void | Promise<void>  // AI 重新装配提示词（快照/触发由宿主做）
  regenConfirm?: string   // 覆盖已有内容前的确认文案（缺省不确认）
  regenTitle?: string
  onSave?: (text: string) => Promise<void>  // 存储由宿主传入
  // refs=生成时启用的参考图（visible 去掉停用项）——宿主从库读参考的可忽略，独立参考图（子弹框）据此传给出图
  onGenerate: (text: string, refs: { name: string; kind: string; url?: string }[]) => void | Promise<void>
  onApply?: (url: string) => void | Promise<void>  // 直接把某参考图应用为最终成品（跳过生成）；缺省不显示「直接应用」
  generateLabel?: string
  generateTitle?: string
  history?: GenHistory   // 传入则内置版本历史：save/generate/regen/ai-edit 自动打快照 + 底部回退面板
  script?: string        // 分镜脚本原始正文（镜头弹框顶部展示、可编辑）；配 onSaveScript 才渲染
  onSaveScript?: (text: string) => Promise<void>  // 保存分镜脚本正文（「保存」时与提示词一并落库）
  footStart?: ReactNode  // 底栏左下角附加区（如新增素材弹框的两开关勾选）
}) {
  const [text, setText] = useState(prompt ?? '')
  const [saved, setSaved] = useState(prompt ?? '')   // 最近落库值（判断是否有未存改动）
  const [scriptText, setScriptText] = useState(script ?? '')       // 分镜脚本正文编辑框
  const [savedScript, setSavedScript] = useState(script ?? '')     // 最近落库的正文
  const [offSet, setOffSet] = useState(() => new Set(off ?? []))
  const [gone, setGone] = useState<Set<string>>(new Set())
  const [extraRefs, setExtraRefs] = useState<EditRef[]>([])  // 本次从素材库新添的参考（宿主已持久化）
  const [localAiBusy, setLocalAiBusy] = useState(false)  // 本弹窗触发的在途（宿主快照 props 不更新，故本地兜住）
  const [saving, setSaving] = useState(false)
  const [genBusy, setGenBusy] = useState(false)   // onGenerate 同步等待中（如封面直出）
  const [histBump, setHistBump] = useState(0)     // 版本历史刷新计数（打完快照 +1 重拉面板）
  // 打一版历史快照（history 未传则空操作），随后刷新面板；落盘失败不阻断生成
  const snapshot = async (value: string, reason: PromptVersion['reason']) => {
    if (!history || !value.trim()) return
    await pushPromptVersion(historyKey(history.pid, history.id, history.target),
      { ts: Date.now(), seq: history.seq, target: history.target, reason, prompt: value })
    setHistBump(b => b + 1)
  }
  const changed = text.trim() !== saved.trim() && !!text.trim()
  const aiInFlight = !!aiBusy || localAiBusy
  // 修改要求 = 原提示词（最近落库值）下方追加的文字；有追加 → AI 修改，否则 → 重新生成
  const base = saved.trim()
  const cur = text.trim()
  const instruction = base && cur.startsWith(base) ? cur.slice(base.length).trim() : ''
  const hasAi = !!(onAiEdit || onRegen)

  const toggle = (name: string) => {
    setOffSet(s => { const n = new Set(s); if (n.has(name)) n.delete(name); else n.add(name); return n })
    onToggleRef?.(name)
  }
  const del = (name: string) => {
    if (onDeleteRef?.(name) === false) return
    setGone(s => new Set(s).add(name))
  }
  const aiAction = async () => {
    if (aiInFlight || busy || saving || genBusy) return
    // 有追加修改要求 → AI 按要求改写并回填编辑框（弹窗保留）
    if (instruction && onAiEdit) {
      setLocalAiBusy(true)
      try {
        await snapshot(base, 'ai-edit')   // 改写前存底：可回退到 AI 改写前的原文
        const p = await onAiEdit(instruction, base)
        if (p != null) { setText(p); setSaved(p) }
      } finally { setLocalAiBusy(false) }
      return
    }
    // 无追加：镜头走异步重装配 onRegen（入队后收口弹窗，卡片自动刷新）——直接执行不再弹确认
    if (onRegen) {
      if (cur) await snapshot(cur, 'regen')
      await onRegen(cur)
      closeElementPreview()
      return
    }
    // 无追加且无 onRegen：用空指令走 onAiEdit 同步重写并回填（要素/封面——其提示词是可直接重写的源头）
    if (onAiEdit) {
      setLocalAiBusy(true)
      try {
        if (cur) await snapshot(cur, 'regen')
        const p = await onAiEdit('', cur)
        if (p != null) { setText(p); setSaved(p) }
      } finally { setLocalAiBusy(false) }
    }
  }
  const scriptChanged = onSaveScript != null && scriptText.trim() !== savedScript.trim()
  // 保存=提示词与分镜脚本正文一并落库（各自有改动才写）；生成前也调用，无改动则跳过
  const save = async (): Promise<boolean> => {
    if (!(onSave && changed) && !scriptChanged) return true
    setSaving(true)
    try {
      if (onSave && changed) { await onSave(text); setSaved(text) }
      if (onSaveScript && scriptChanged) { await onSaveScript(scriptText); setSavedScript(scriptText) }
      return true
    } catch (e) { alert(String(e)); return false }
    finally { setSaving(false) }
  }
  // 保存按钮：任何时候可点——有改动则落库（提示词+正文），无改动直接收口（给"已保存"反馈）
  const saveClick = async () => { if (await save()) closeElementPreview() }
  const generate = async () => {
    if (!(await save())) return
    await snapshot(text, 'generate')
    // 生成时启用的参考（去掉已删/停用项）——独立参考图子弹框据此把参考喂给出图模型
    const active = [...(refs ?? []), ...extraRefs]
      .filter(r => !gone.has(r.name) && !offSet.has(r.name))
      .map(r => ({ name: r.name, kind: r.kind, url: r.url }))
    setGenBusy(true)
    try { await onGenerate(text, active) }
    catch (e) { alert(String(e)); return }
    finally { setGenBusy(false) }
    closeElementPreview()
  }
  const pick = async (a: ProjectAsset) => {
    try {
      const r = await onPickAsset!(a)
      if (r === 'close') { closeElementPreview(); return }
      if (r) setExtraRefs(x => [...x.filter(e => e.name !== r.name), r])
    } catch (e) { alert(String(e)) }
  }
  // 「生成参考图」：在本弹框之上叠一层公共图片生成弹框生成一张独立参考图，出图后加为本弹框参考
  const openRefGen = () => {
    if (pid == null) return
    pushElementPreview(
      <ImageGenModal icon="palette" title="生成参考图" refs={[]} off={[]} pid={pid}
        onPickAsset={a => ({ name: a.name, kind: a.kind, url: a.url ?? undefined, deletable: true })}
        promptHint="参考图提示词（可直接编辑；点右下按钮由 AI 起草/改写）"
        placeholder={'描述要生成的参考图；也可点右下「AI 生成提示词」起草，再点「生成参考图」。\n已有内容后：在原文下方另起一行写修改要求即为 AI 修改。'}
        onAiEdit={(instruction, base) => api.aiPromptAsset(pid, instruction, base).then(r => r.prompt)}
        aiEditTitle="AI 按追加的修改要求改写参考图提示词（同步回填编辑框）"
        regenConfirm="将 AI 重写参考图提示词，覆盖当前内容。继续？"
        regenTitle="AI 起草/重写一版参考图提示词（回填编辑框，需再点生成）"
        onGenerate={async (t, subRefs) => {
          const a = await api.generateAsset(pid, t,
            subRefs.filter(r => r.url).map(r => ({ name: r.name, kind: r.kind, url: r.url! })))
          await pick({ group: '参考图', kind: a.kind, name: a.name, url: a.url })
        }}
        generateLabel="生成参考图"
        generateTitle="按上方提示词生成一张参考图（存入资产库并加为当前参考）"
        history={{ pid, id: pid, target: 'ref' }} />
    )
  }

  const visible = [...(refs ?? []), ...extraRefs].filter(r => !gone.has(r.name))
  const canPick = pid != null && !!onPickAsset
  // 布局：ig-cols（左表单列 | 右素材库面板（canPick 宿主常驻），各自独立滚动）+ ig-foot 通栏钉底
  return (
    <div className={'ig-wrap' + (canPick ? ' picking' : '')}>
      <div className="ig-cols">
        <div className="ig-main">
          <div className="ig-head"><Icon name={icon} /> <b>{title}</b>{titleExtra}</div>
          {/* 分镜脚本原始正文（镜头弹框）：可编辑，「保存」时与提示词一并落库；改后作装配/AI 改写事实边界 */}
          {onSaveScript && (
            <div className="ig-script">
              <div className="ig-label">分镜脚本（原始正文，可编辑；「保存」时与提示词一并保存）</div>
              <textarea className="ig-script-ta" value={scriptText} placeholder="本镜分镜脚本 / 原始正文"
                onChange={e => setScriptText(e.target.value)} />
            </div>
          )}
          {/* 提示词区左右分栏：左=上次生成/应用的成品图（固定最大宽高），右=提示词 */}
          <div className="ig-prompt-row">
            <div className="ig-shot">
              <div className="ig-shot-box">
                {media
                  ? <img src={media} alt={title} className="ig-shot-img zoomable" title="点击放大"
                      onClick={() => openLightbox(media, title)} />
                  : <div className="ig-shot-empty"><Icon name={icon} /><span>尚无成品</span></div>}
              </div>
              <div className="ig-cap">最终效果</div>
            </div>
            <div className="ig-prompt-col">
              <textarea className="ig-prompt" value={text} placeholder={placeholder}
                onChange={e => setText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && hasAi) aiAction() }} />
              <div className="ig-cap">提示词</div>
            </div>
          </div>
          {refs && (
            <div>
              <div className="ig-label">{refsHint ?? '参考素材'}</div>
              {/* 添加参考统一走右侧「素材库」面板（选现有 / 上传 / 生成），左侧不再放入口 */}
              <GenRefList refs={visible} off={offSet}
                onToggle={onToggleRef ? toggle : undefined}
                onDelete={onDeleteRef ? del : undefined}
                onApply={onApply ? async url => { await onApply(url); closeElementPreview() } : undefined} />
            </div>
          )}
          {aiInFlight && <div className="ig-ai-hint"><Icon name="spinner" spin /> AI 正在后台改写——可直接关闭本弹框，改完自动保存并刷新</div>}
          {busy && !aiInFlight && <div className="ig-ai-hint"><Icon name="spinner" spin /> {busyHint ?? '生成任务在途——完成后自动刷新'}</div>}
          {history && (
            <PromptHistory pid={history.pid} id={history.id} target={history.target}
              bump={histBump} current={text} onRestore={setText} />
          )}
        </div>
        {canPick && (
          <AssetPicker pid={pid!} exclude={visible.map(r => r.name)} onPick={pick}
            onGenerateRef={openRefGen} />
        )}
      </div>
      {/* 底部动作组：与「正文/视频」同款 tab 组（.seg），主操作「生成」高亮（.active），AI/保存为次操作 */}
      <div className="ig-foot">
        {footStart && <div className="ig-foot-start">{footStart}</div>}
        <div className="seg ig-acts">
          {hasAi && (
            <button type="button" className="seg-btn" disabled={aiInFlight || busy || saving || genBusy} onClick={aiAction}
              title={instruction && onAiEdit
                ? (aiEditTitle ?? 'AI 按下方追加的修改要求改写原提示词（后台改写、改完自动落库并刷新）')
                : (regenTitle ?? 'AI 重新装配提示词，覆盖当前内容；也可用 Ctrl+Enter 触发')}>
              {(aiInFlight || busy) ? <Icon name="spinner" spin /> : <Icon name="wand" />}
              {instruction && onAiEdit ? ' AI 修改提示词' : (cur ? ' AI 优化提示词' : ' AI 生成提示词')}
            </button>
          )}
          {(onSave || onSaveScript) && (
            <button type="button" className="seg-btn" disabled={saving || genBusy}
              onClick={saveClick}
              title="保存编辑后的提示词与分镜脚本正文（不触发生成）；参考素材的增删已即时生效">
              {saving ? <Icon name="spinner" spin /> : <Icon name="save" />} 保存
            </button>
          )}
          <button type="button" className="seg-btn active" disabled={saving || genBusy || aiInFlight || !text.trim()} onClick={generate}
            title={generateTitle ?? '有改动先保存，再触发生成'}>
            {genBusy ? <Icon name="spinner" spin /> : <Icon name={icon} />} {generateLabel ?? '生成图片'}
          </button>
        </div>
      </div>
    </div>
  )
}
