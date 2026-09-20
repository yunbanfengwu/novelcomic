// 引用候选清单的唯一实现（零 JSX）：顶部「+」与正文里的 @ 共用同一份候选与打包格式，
// 免得两处各写一遍、候选集慢慢长歪。
import { TAP_CTX_REFS, type TapCtxRef, type TapUpstreamVar, type TapVarType } from './tapflowData'
import { normOption, type TapOptionLike } from './tapflowOption'

// 选项值要把四个字段打包成一个字符串（选择浮窗的 onPick 只回传 value）。
// 分隔符用 \u001f（单元分隔符）：正文里不可能出现，比 | 之类安全。
const SEP = '\u001f'

export interface TapRefOption { value: string; label: string }
export interface TapRefGroup { title: string; items: TapRefOption[] }

const pack = (kind: string, label: string, token: string, type: string): string =>
  [kind, label, token, type].join(SEP)

/** 打包字符串 → 引用对象 */
export function unpackRef(raw: string): TapCtxRef {
  const [kind, label, token, type] = raw.split(SEP)
  return {
    kind: kind as TapCtxRef['kind'], label, token,
    type: (type || (kind === 'ctx' ? 'ctx' : 'text')) as TapVarType,
  }
}

/** 三组候选：上游节点（沿连线回溯，点节点即引用）/ 运行上下文 / 取数工具。
 * has 用来排除已经引用过的，避免重复。
 * queryTools 由调用方从系统目录传入（useTapflowCatalog），这里不再自带写死清单。 */
export function refGroups(upstream: TapUpstreamVar[],
                          has: (token: string) => boolean,
                          queryTools: TapOptionLike[] = []): TapRefGroup[] {
  // 占位符里必须是**节点 id**：运行期 ctx 就是按 id 存各节点产物（workflow._resolve），
  // 用标题拼出来的 {{Text.text}} 解析不到任何东西——_fill 会把它替换成空串，
  // 引用等于凭空消失，且不报错。展示名走 refs 清单里的 label，不靠 token 好看。
  // 开始节点在引擎里的键是 input，与 toolArg 的口径保持一致。
  const nodes = upstream
    .map(u => ({
      label: `${u.nodeTitle} · ${u.label || u.k}`,
      token: `{{${u.nodeId === 'start' ? 'input' : u.nodeId}.${u.k}}}`,
      type: (u.type ?? 'text') as TapVarType,
    }))
    .filter(x => !has(x.token))
  return [
    { title: '上游节点', items: nodes.map(x => ({ value: pack('node', x.label, x.token, x.type), label: x.label })) },
    {
      title: '运行上下文',
      items: TAP_CTX_REFS.filter(c => !has(c.token))
        .map(c => ({ value: pack('ctx', c.label, c.token, 'ctx'), label: c.label })),
    },
    {
      title: '取数工具',
      items: queryTools.map(normOption)
        .map(t => ({ label: t.label, token: `{{${t.value}}}` }))
        .filter(x => !has(x.token))
        .map(x => ({ value: pack('tool', x.label, x.token, 'text'), label: x.label })),
    },
  ]
}
