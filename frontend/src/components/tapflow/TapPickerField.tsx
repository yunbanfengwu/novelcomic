import { useState } from 'react'
import { normOption, optionLabel, type TapOptionLike } from '../../lib/tapflowOption'
import { Icon, type IconName } from '../Icon'
import { TapPickMenu } from './TapPickMenu'

export interface TapPickerGroup {
  /** 回写字段名（如 skills / kb / tools） */
  key: string
  /** 浮窗里的分组名；只有一组时可省 */
  title?: string
  /** 已选行前的类型图标，用来区分来源 */
  icon?: IconName
  /** 候选。value=引擎认的值（技能 slug / 知识库 folder_id / 工具 name），label 才给人看 */
  options: TapOptionLike[]
  value: string[]
}

/** 「已选清单 + 添加浮窗」字段。支持多来源合并成一个区域——
 * 如「专业能力」一个标题下同时挑技能/知识库/工具，各自回写自己的字段。 */
export function TapPickerField({ title, note, addLabel = '+ 添加', groups, onChange }: {
  title: string
  note?: string
  addLabel?: string
  groups: TapPickerGroup[]
  onChange: (key: string, next: string[]) => void
}) {
  const [adding, setAdding] = useState(false)
  const picked = groups.flatMap(g => g.value.map(v => ({ v, g })))

  return (
    <>
      <div className="tap-insp-sec row">
        <span>{title}</span>
        <span className="tap-param-add">
          <button type="button" className="tap-param-add-btn" onClick={() => setAdding(v => !v)}>
            {addLabel}
          </button>
          {adding && (
            <TapPickMenu
              groups={groups.map(g => ({
                title: groups.length > 1 ? g.title : undefined,
                // 已选的不再列出；多组时给 value 加前缀，回写才知道归谁
                items: g.options.map(normOption).filter(o => !g.value.includes(o.value))
                  .map(o => ({ value: `${g.key}::${o.value}`, label: o.label, note: o.note })),
              }))}
              onPick={raw => {
                const [key, ...rest] = raw.split('::')
                const g = groups.find(x => x.key === key)
                if (g) onChange(key, [...g.value, rest.join('::')])
              }}
              onClose={() => setAdding(false)} />
          )}
        </span>
      </div>
      {note && <div className="tap-insp-note">{note}</div>}
      {picked.map(({ v, g }) => (
        <div key={`${g.key}:${v}`} className="tap-picked">
          {g.icon && (
            <em className={'tap-picked-ico ' + g.key} title={g.title}><Icon name={g.icon} /></em>
          )}
          <span>{optionLabel(g.options, v)}</span>
          <button type="button" className="tap-p-del" title="移除"
            onClick={() => onChange(g.key, g.value.filter(x => x !== v))}>×</button>
        </div>
      ))}
      {!picked.length && <div className="tap-insp-note">未添加</div>}
    </>
  )
}
