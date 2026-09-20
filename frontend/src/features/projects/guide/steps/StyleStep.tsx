import { useEffect, useState } from 'react'
import { api } from '../../../../api'
import type { StyleOption } from '../../../../api'
import { Icon } from '../../../../components/Icon'
import { Seg } from '../../../../components/Seg'
import { StylePicker } from './StylePicker'
import { VideoTypePicker } from './VideoTypePicker'

/**
 * 内容设定/画面设定步：从知识库画风库/文风库**选择**（卡片，画风带缩略图），
 * 选中即回填暂存值 `名称——内容`（创建落库后，生成链路按名称精确召回对应知识块）。
 * 「自定义」卡切回自由输入 + AI 评估（草稿态接口）。留空=创建时由 AI 按草稿初拟。
 * 画面设定（kind=art）另含画幅比例选择，比例行下方为视频类型标签选择（决定项目类型路由）。
 */
export function StyleStep({ kind, value, context, aspect, onAspect, videoTags, onVideoTags, onChange }: {
  kind: 'writing' | 'art'
  value: string
  context: { draft: string; title: string; synopsis: string }
  aspect?: '16:9' | '9:16'
  onAspect?: (r: '16:9' | '9:16') => void
  /** 视频类型标签 code（仅画面设定步）：单选，落 info.tags + project_type。 */
  videoTags?: string[]
  onVideoTags?: (codes: string[]) => void
  onChange: (v: string) => void
}) {
  const [options, setOptions] = useState<StyleOption[]>([])
  const [custom, setCustom] = useState(false)
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState(false)
  const draftOk = context.draft.trim().length >= 10

  useEffect(() => {
    api.styleLibrary(kind === 'writing' ? 'writing' : 'art')
      .then(opts => {
        setOptions(opts)
        // 已有值但不是库里选出来的（AI 初拟/手填）→ 进自定义态展示
        if (value && !opts.some(o => value.startsWith(o.name))) setCustom(true)
      })
      .catch(() => { setOptions([]); setCustom(true) })
    // 仅按步骤种类加载一次；value 变化不重判（选择/输入过程中不来回跳）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind])

  const selected = custom ? null : (options.find(o => value.startsWith(o.name))?.name ?? null)

  const restyle = async () => {
    setBusy(true)
    try {
      const { suggestion } = await api.restyle({
        target: kind, instruction: instruction || undefined,
        draft: context.draft, title: context.title, synopsis: context.synopsis, current: value,
      })
      onChange(suggestion)
      setInstruction('')
    } catch (e) { alert(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="guide-form">
      {aspect && onAspect && (
        <div className="guide-aspect-row">
          <Seg items={[
            { key: '16:9', label: <><Icon name="monitor" /> 横屏 16:9</> },
            { key: '9:16', label: <><Icon name="phone" /> 竖屏 9:16</> },
          ]} active={aspect} onSelect={onAspect} />
          <label className="modal-label guide-aspect-label">画幅比例</label>
        </div>
      )}
      {/* 视频类型标签行：仅画面设定步，紧跟画幅比例——先选类型再选画风 */}
      {kind === 'art' && onVideoTags && (
        <VideoTypePicker value={videoTags || []} onChange={onVideoTags} />
      )}
      <label className="modal-label">
        {kind === 'writing' ? '选择文风（来自知识库·文风库）' : '选择画风（来自知识库·画风库）'}
      </label>
      <StylePicker kind={kind} options={options} selectedName={selected} customActive={custom}
        onPick={o => { setCustom(false); onChange(`${o.name}——${o.content}`) }}
        onCustom={() => setCustom(true)} />
      {custom && (
        <>
          <textarea id="g-style" className="modal-textarea guide-style-text" value={value}
            onChange={e => onChange(e.target.value)}
            placeholder={kind === 'writing'
              ? '如：莫言式乡土魔幻，长句铺排，感官轰炸（留空 = 创建时由 AI 拟定）'
              : '如：日漫赛璐璐 / 国漫水墨 / 美漫厚涂 / 电影感写实（留空 = 创建时由 AI 拟定）'} />
          <label className="modal-label" htmlFor="g-instr">让 AI 帮你评估（可选，基于「基本信息」步的草稿）</label>
          <div className="guide-inline-actions guide-restyle">
            <input id="g-instr" className="modal-input" value={instruction}
              onChange={e => setInstruction(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !busy && draftOk) restyle() }}
              placeholder={kind === 'writing' ? '如：再冷硬克制一点' : '如：更偏国漫水墨'} />
            <button className="small ghost" disabled={busy || !draftOk}
              title={draftOk ? undefined : '先在「基本信息」步填写草稿（至少 10 字）'}
              onClick={restyle}>
              {busy ? <><Icon name="spinner" spin /> 评估中…</> : <><Icon name="sparkles" /> AI 评估</>}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
