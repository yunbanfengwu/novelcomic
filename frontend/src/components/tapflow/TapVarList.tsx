import { useState } from 'react'
import { setParamValue, type TapParam, type TapUpstreamVar, type TapVarType } from '../../lib/tapflowData'
import { TapVarAddMenu } from './TapVarAddMenu'
import { TapVarRow } from './TapVarRow'

/** 变量清单（输入 / 输出通用）：标题行右侧「+ 添加」，下面逐条变量。
 * 自管浮窗开合、变量名去重、ctx 级联清理；宿主只给 vars + onChange。 */
export function TapVarList({ title, note, vars, upstream, valueless, onChange }: {
  title: string
  note?: string
  vars: TapParam[]
  /** 可引用的上游输出变量（输入清单才传） */
  upstream?: TapUpstreamVar[]
  /** true=只声明不取值（输出清单） */
  valueless?: boolean
  onChange: (next: TapParam[]) => void
}) {
  const [adding, setAdding] = useState(false)
  const [open, setOpen] = useState(true)
  const add = (kind: TapParam) => {
    const taken = new Set(vars.map(v => v.k))
    let k = kind.k
    for (let n = 2; taken.has(k); n++) k = `${kind.k}_${n}`
    onChange([...vars, { ...kind, k }])
  }
  const patch = (i: number, p: Partial<TapParam>) => {
    // 改的是 ctx 类的值 → 走级联清理（换卷清掉旧章之类）
    if ('v' in p && vars[i].type === 'ctx') {
      onChange(setParamValue(vars, vars[i].k, p.v ?? ''))
      return
    }
    onChange(vars.map((x, j) => j === i ? { ...x, ...p } : x))
  }
  const forType = (t?: TapVarType) =>
    upstream?.filter(u => !t || t === 'ctx' || !u.type || u.type === 'ctx' || u.type === t)

  return (
    <div className="tap-insp-part">
      <div className="tap-insp-sec row">
        <button type="button" className="tap-fold" onClick={() => setOpen(o => !o)}>
          <span className={'tap-fold-arrow' + (open ? ' open' : '')}>▾</span>{title}
        </button>
        <span className="tap-param-add">
          <button type="button" className="tap-add-sq" title="添加变量"
            onClick={() => setAdding(v => !v)}>+</button>
          {adding && (
            <TapVarAddMenu existing={vars} ctxAllowed={!valueless}
              onPick={add} onClose={() => setAdding(false)} />
          )}
        </span>
      </div>
      {open && (
        <>
          {note && <div className="tap-insp-note">{note}</div>}
          {!!vars.length && (
            <div className="tap-vrow head">
              <span className="tap-vrow-name">变量名</span>
              <span className="tap-vrow-val">变量值</span>
              <span />
            </div>
          )}
          {vars.map((v, i) => (
            <TapVarRow key={v.k} v={v} siblings={vars} valueless={valueless}
              upstream={forType(v.type)}
              onPatch={p => patch(i, p)}
              onRemove={() => onChange(vars.filter((_, j) => j !== i))} />
          ))}
          {!vars.length && <div className="tap-insp-note">尚未声明变量</div>}
        </>
      )}
    </div>
  )
}
