import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../../../../api'
import type { StagedMaterial } from '../../../../api'
import { Icon } from '../../../../components/Icon'
import type { GuideInfo } from '../GuidedCreate'
import type { GuideStepMeta } from '../../../../lib/guideSteps'

const AI_FILL = <span className="tag">创建时由 AI 拟定</span>

/** 设定预览步（终点站）：汇总各步暂存值供确认——只有到这一步底部「创建作品」才可点击。纯 props→JSX。 */
export function PreviewStep({ draft, info, materials, aspect, onJump, steps }: {
  draft: string
  info: GuideInfo
  materials: StagedMaterial[]
  aspect: '16:9' | '9:16'
  onJump: (step: number) => void
  steps: GuideStepMeta[]
}) {
  const stepOf = (key: string) => {
    const index = steps.findIndex(s => s.key === key)
    // 新建向导把材料并入基本信息页，因此材料的“修改”按钮跳回基本信息。
    return index >= 0 ? index : steps.findIndex(s => s.key === 'basic')
  }
  const row = (label: string, step: number, content: ReactNode) => (
    <div className="guide-review-row">
      <div className="guide-review-head">
        <b>{label}</b>
        <button className="small ghost" onClick={() => onJump(step)}><Icon name="pen" /> 修改</button>
      </div>
      <div className="guide-review-body">{content}</div>
    </div>
  )
  // 标签名回显：code → 名称（标签库加载失败时退回显示 code）
  const [tagNames, setTagNames] = useState<Record<string, string>>({})
  useEffect(() => {
    api.listTagGroups().then(gs => setTagNames(Object.fromEntries(
      gs.flatMap(g => g.tags.map(t => [t.code, t.name])),
    ))).catch(() => {})
  }, [])
  return (
    <div className="guide-form guide-review">
      {row('画面设定', stepOf('art'), (
        <>
          <p><b>类型：</b>{(info.tags || []).length
            ? info.tags!.map(c => <span key={c} className="tag accent">{tagNames[c] || c}</span>)
            : <span className="dim">未选择</span>}</p>
          <p><b>画风：</b>{info.art_style.trim() ? <span className="dim">{info.art_style}</span> : AI_FILL}</p>
          <p><b>比例：</b><span className="tag accent">
            {aspect === '16:9' ? <><Icon name="monitor" /> 横屏 16:9</> : <><Icon name="phone" /> 竖屏 9:16</>}
          </span></p>
        </>
      ))}
      {row('基本信息', stepOf('basic'), (
        <>
          <p><b>草稿：</b><span className="dim">{draft.trim() ? `${draft.trim().length} 字` : '未填写（必填）'}</span></p>
          <p><b>书名：</b>{info.title.trim() ? <span className="dim">{info.title}</span> : AI_FILL}</p>
          <p><b>梗概：</b>{info.synopsis.trim() ? <span className="dim">{info.synopsis}</span> : AI_FILL}</p>
          <p><b>主线：</b>{info.storyline.trim() ? <span className="dim">{info.storyline}</span> : AI_FILL}</p>
        </>
      ))}
      {row('相关材料', stepOf('materials'), materials.length ? (
        <ul className="guide-review-mats">
          {materials.map((m, i) => (
            <li key={i}>
              <Icon name={m.source === 'upload' ? 'clip' : 'text'} /> {m.title}
              <span className="dim">{m.source === 'upload' ? '（已上传）' : `（${m.content?.length ?? 0} 字）`}</span>
            </li>
          ))}
        </ul>
      ) : <span className="dim">无（可后续在项目里补充）</span>)}
      {row('内容设定', stepOf('writing'), info.writing_style.trim()
        ? <span className="dim">{info.writing_style}</span> : AI_FILL)}
    </div>
  )
}
