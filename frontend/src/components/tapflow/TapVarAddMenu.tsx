import { TAP_OUTPUT_TYPES, TAP_PARAM_KINDS, type TapParam } from '../../lib/tapflowData'
import { TapPickMenu } from './TapPickMenu'

/** 「添加变量」浮窗：上下文类每种只可加一次（加过就不再列出）。
 * 输入可加 文本/数字/JSON/图片/视频；输出只有 文本/数字/JSON。行为复用 TapPickMenu。 */
export function TapVarAddMenu({ existing, ctxAllowed = true, onPick, onClose }: {
  existing: TapParam[]
  /** false=输出变量：不涉及运行上下文，且类型限于 TAP_OUTPUT_TYPES */
  ctxAllowed?: boolean
  onPick: (kind: TapParam) => void
  onClose: () => void
}) {
  const used = new Set(existing.filter(p => p.type === 'ctx').map(p => p.ctx))
  const ctxKinds = ctxAllowed
    ? TAP_PARAM_KINDS.filter(k => k.type === 'ctx' && !used.has(k.ctx))
    : []
  const freeKinds = TAP_PARAM_KINDS.filter(k =>
    k.type !== 'ctx' && (ctxAllowed || TAP_OUTPUT_TYPES.includes(k.type!)))
  const label = (k: TapParam) => k.label || k.k
  return (
    <TapPickMenu
      groups={[
        { title: ctxKinds.length ? '上下文' : undefined, items: ctxKinds.map(label) },
        { title: '数据', items: freeKinds.map(label) },
      ]}
      onPick={v => {
        const kind = [...ctxKinds, ...freeKinds].find(k => label(k) === v)
        if (kind) onPick(kind)
      }}
      onClose={onClose} />
  )
}
