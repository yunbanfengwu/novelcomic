import { useState } from 'react'
import type { IconName } from '../Icon'
import { Icon } from '../Icon'
import type { TapCtxRef, TapUpstreamVar } from '../../lib/tapflowData'
import { refGroups, unpackRef } from '../../lib/tapflowRefs'
import { useTapflowCatalog } from '../../lib/useTapflowCatalog'
import { TapPickMenu } from './TapPickMenu'

/** 按数据类型给图标：文本/数字/JSON 一个文本图标，图片走缩略图占位，视频音频各自独立 */
const TYPE_ICON: Record<string, IconName> = {
  text: 'text', int: 'text', json: 'text',
  image: 'image', video: 'video', audio: 'speaker', ctx: 'compass',
}
const iconOf = (r: TapCtxRef): IconName =>
  TYPE_ICON[r.type ?? ''] ?? (r.kind === 'tool' ? 'tools' : r.kind === 'ctx' ? 'compass' : 'text')

/**
 * 贴在系统提示词**上方**的一排引用方块（与生成条的参考图条同一形态）：
 * 每个引用一颗方块，图片显示缩略图、其余按类型显示图标，超出自动换行，末尾是「+」。
 *
 * 「+」只往这排里加，**不动正文**——要把引用插进句子里（「请参考【…】生成」）
 * 是在正文里打 @ 触发的，两个入口各管各的。
 */
export function TapPromptRefs({ refs, upstream, onChange }: {
  refs: TapCtxRef[]
  /** 沿连线回溯到的上游输出变量（点节点即引用，不用手点字段） */
  upstream: TapUpstreamVar[]
  onChange: (next: TapCtxRef[]) => void
}) {
  const catalog = useTapflowCatalog()
  const [adding, setAdding] = useState(false)
  const has = (token: string) => refs.some(r => r.token === token)

  return (
    <div className="tap-charter-refs">
      {refs.map(r => (
        <span key={r.token} className={'tap-cref ' + (r.type ?? r.kind)} title={r.label}>
          {r.thumb
            ? <img src={r.thumb} alt="" draggable={false} />
            : <Icon name={iconOf(r)} />}
          <button type="button" className="tap-cref-del" title="移除"
            onClick={() => onChange(refs.filter(x => x.token !== r.token))}>×</button>
        </span>
      ))}
      <span className="tap-cref-add-wrap">
        <button type="button" className="tap-cref-add" title="添加引用"
          onClick={() => setAdding(v => !v)}><Icon name="plus" /></button>
        {adding && (
          <TapPickMenu
            groups={refGroups(upstream, has, catalog.queryTools)}
            onPick={raw => { onChange([...refs, unpackRef(raw)]); setAdding(false) }}
            onClose={() => setAdding(false)} />
        )}
      </span>
    </div>
  )
}
