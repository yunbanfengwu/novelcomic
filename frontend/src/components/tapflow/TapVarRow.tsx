import { useState } from 'react'
import { Icon } from '../Icon'
import { TAP_NO_VOLUME, ctxOptions, type TapParam, type TapUpstreamVar, type TapVarType } from '../../lib/tapflowData'
import { TapPickMenu } from './TapPickMenu'

/** 类型的紧凑写法（Dify 那种 str. / int. 标记） */
const TYPE_LABEL: Record<TapVarType, string> = {
  ctx: '上下文', text: '文本 str.', int: '数字 int.', json: 'JSON',
  image: '图片 img.', video: '视频 vid.',
}
const SELECTABLE: TapVarType[] = ['text', 'int', 'json', 'image', 'video']

/** 一条变量：左列变量名，右列「类型 + 值/引用」。
 * ⊙ 按钮弹上游变量浮窗，选中即变引用 chip；再点 × 回到常量输入。 */
export function TapVarRow({ v: p, siblings, upstream, valueless, onPatch, onRemove }: {
  v: TapParam
  /** 同组其余变量：ctx 类算级联候选要用 */
  siblings: TapParam[]
  /** 可引用的上游输出变量（已按类型过滤好） */
  upstream?: TapUpstreamVar[]
  /** true=只声明不取值（输出变量） */
  valueless?: boolean
  onPatch: (patch: Partial<TapParam>) => void
  onRemove: () => void
}) {
  const [picking, setPicking] = useState(false)
  const [menu, setMenu] = useState(false)
  const isRef = p.source === 'ref' && !!p.ref
  const refLabel = isRef
    ? (() => {
        const u = upstream?.find(x => x.nodeId === p.ref!.node && x.k === p.ref!.k)
        return u ? `${u.nodeTitle} · ${u.label || u.k}` : `${p.ref!.node} · ${p.ref!.k}`
      })()
    : ''

  // JSON 值一行放不下：变量名与值改上下排布，值用多行文本域
  const isJson = p.type === 'json'
  return (
    <div className={'tap-vrow' + (isJson ? ' json' : '')}>
      <span className="tap-vrow-name">
        <input className="tap-insp-input flat" value={p.label || p.k}
          onChange={e => onPatch({ label: e.target.value })} />
        {p.required && <i className="tap-vreq" title="必填">*</i>}
      </span>

      {valueless ? (
        <span className="tap-vrow-val">
          {isJson ? (
            <textarea className="tap-vinput area" rows={3} value={p.v} placeholder="{ }"
              onChange={e => onPatch({ v: e.target.value })} />
          ) : (
            <input className="tap-vinput" value={p.v} placeholder="运行时产出"
              onChange={e => onPatch({ v: e.target.value })} />
          )}
        </span>
      ) : (
        <span className="tap-vrow-val">
          {isRef ? (
            <span className="tap-vref">
              <b>{refLabel}</b>
              <button type="button" title="清除引用"
                onClick={() => onPatch({ source: 'const', ref: undefined })}>×</button>
            </span>
          ) : p.type === 'ctx' && p.ctx ? (
            <select className="tap-vinput" value={p.v}
              onChange={e => onPatch({ v: e.target.value })}>
              <option value="">{p.ctx === 'volume_id' ? TAP_NO_VOLUME : '未选择'}</option>
              {ctxOptions(p.ctx, siblings).filter(o => o !== TAP_NO_VOLUME)
                .map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            isJson ? (
              <textarea className="tap-vinput area" rows={3} value={p.v}
                placeholder="{ } 或引用参数值"
                onChange={e => onPatch({ v: e.target.value })} />
            ) : (
              <input className="tap-vinput" value={p.v} placeholder="输入或引用参数值"
                onChange={e => onPatch({ v: e.target.value })} />
            )
          )}

          {p.type !== 'ctx' && (
            <span className="tap-vpick">
              <button type="button" className="tap-vpick-btn" title="引用上游变量"
                onClick={() => setPicking(v => !v)}>
                <Icon name="link" />
              </button>
              {picking && (
                <TapPickMenu
                  groups={[{ items: (upstream ?? []).map(u => `${u.nodeTitle} · ${u.label || u.k}`) }]}
                  onPick={label => {
                    const u = (upstream ?? []).find(x => `${x.nodeTitle} · ${x.label || x.k}` === label)
                    if (u) onPatch({ source: 'ref', ref: { node: u.nodeId, k: u.k } })
                  }}
                  onClose={() => setPicking(false)} />
              )}
            </span>
          )}
        </span>
      )}

      {/* 行操作：类型切换 / 必填 / 删除都收进这里，hover 行才浮现 */}
      <span className="tap-vrow-more">
        <button type="button" className="tap-vmore-btn" title="更多"
          onClick={() => setMenu(v => !v)}>⋯</button>
        {menu && (
          <TapPickMenu
            groups={valueless
              // 输出变量：类型在添加时就定了，不给改——要换类型就删掉重加
              ? [{ items: [{ value: '__del', label: '删除', danger: true }] }]
              : [
                  {
                    title: '数据类型',
                    items: p.type === 'ctx'
                      ? [{ value: 'ctx', label: TYPE_LABEL.ctx, active: true }]
                      : SELECTABLE.map(t => ({
                          value: t, label: TYPE_LABEL[t], active: (p.type ?? 'text') === t,
                        })),
                  },
                  {
                    items: [
                      { value: '__req', label: p.required ? '取消必填' : '设为必填' },
                      { value: '__del', label: '删除', danger: true },
                    ],
                  },
                ]}
            onPick={v => {
              if (v === '__del') return onRemove()
              if (v === '__req') return onPatch({ required: !p.required })
              if (v !== 'ctx') onPatch({ type: v as TapVarType, source: 'const', ref: undefined })
            }}
            onClose={() => setMenu(false)} />
        )}
      </span>
    </div>
  )
}
