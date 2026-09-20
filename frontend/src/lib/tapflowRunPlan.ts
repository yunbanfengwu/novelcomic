// 运行范围 → 引擎参数（唯一实现：模拟运行与真实运行共用）。
import type { TapEdge, TapNode } from './tapflowData'

/** 运行范围：null 端点 = 流程默认端点（从头 / 到尾） */
export interface TapRunRange { from: string | null; to: string | null }

/** The action that started a run. Manual node actions must always rerun that node. */
export type TapRunMode = 'all' | 'single'

export interface TapRunOptions {
  mode?: TapRunMode
  nodeId?: string
  verbatim?: string
  rewrite?: string
  /** Immediate actions can run before React commits the edited node state. */
  promptOverride?: string
}

/** 拓扑序（画布保证无环；有环时按原序兜底）。排版与运行计划共用一份。 */
export function topoOrder(nodes: TapNode[], edges: Pick<TapEdge, 'from' | 'to'>[]): TapNode[] {
  const indeg = new Map(nodes.map(n => [n.id, 0]))
  for (const e of edges) {
    if (indeg.has(e.to)) indeg.set(e.to, (indeg.get(e.to) ?? 0) + 1)
  }
  const ready = nodes.filter(n => !indeg.get(n.id))
  const out: TapNode[] = []
  const seen = new Set<string>()
  while (ready.length) {
    const n = ready.shift()!
    if (seen.has(n.id)) continue
    seen.add(n.id)
    out.push(n)
    for (const e of edges.filter(x => x.from === n.id)) {
      const d = (indeg.get(e.to) ?? 0) - 1
      indeg.set(e.to, d)
      if (d <= 0) {
        const t = nodes.find(x => x.id === e.to)
        if (t) ready.push(t)
      }
    }
  }
  return out.length === nodes.length ? out : nodes
}

/** 会真花钱、值得「重跑还是取用」区别对待的节点类型 */
const COSTLY: TapNode['type'][] = ['gen', 'text', 'video', 'image', 'audio', 'flow']

/**
 * 运行范围 → {force, stopAfter}。
 *
 * **整图始终从前往后跑，默认全是「缺才跑」**：每步先探产物，有就取回来用（不花钱），
 * 缺了才真跑。所以「开始节点」不是从中间起跑，而是——
 *
 * - `from`：它**及其之后**的花钱节点强制重跑；它之前的照旧缺才跑（只查、缺了才补）。
 *   这才是「从这一步重来」的正确语义：上游该有的值照样拿得到，不会因为跳过而断链。
 * - `to`：跑到它为止，后面的不跑。
 * - 两端都不选 = 整图缺才跑（最省的默认）。
 */
export function rangeToRun(nodes: TapNode[], edges: Pick<TapEdge, 'from' | 'to'>[],
                           range?: TapRunRange,
                           forceAll = false,
                           singleNodeId?: string): { force: string[]; stopAfter?: string } {
  const order = topoOrder(nodes, edges)
  const at = (id: string | null | undefined) =>
    id ? order.findIndex(n => n.id === id) : -1
  // A manual node action is intentionally stronger than the normal cache rule:
  // the clicked node must be regenerated even when a product already exists.
  if (singleNodeId && at(singleNodeId) >= 0) {
    return { force: [singleNodeId], stopAfter: singleNodeId }
  }
  const fromAt = at(range?.from)
  const toAt = at(range?.to)
  const end = toAt >= 0 ? toAt : order.length - 1
  // forceAll = **所选开始→结束之间**全部重出（不选起点才等于整条链）。
  // 原来无条件从 0 开始，等于把用户选的起点吞掉——开关一开，前面那些不想重跑的
  // 节点也跟着重出，钱白花。结束节点本身含在内（slice 到 end+1）：选了它就是要它重跑。
  const begin = forceAll ? Math.max(fromAt, 0) : fromAt
  const force = begin < 0 ? [] : order
    .slice(begin, end + 1)
    .filter(n => COSTLY.includes(n.type))
    .map(n => n.id)
  return { force, stopAfter: toAt >= 0 ? range?.to ?? undefined : undefined }
}

/** 某节点的全部上游节点（含间接），按拓扑序。生成条「添加参考」的候选集。
 * 只回溯上游是刻意的：参考下游会成环，跑起来必然拿不到值。 */
export function upstreamNodes(id: string, nodes: TapNode[],
                              edges: Pick<TapEdge, 'from' | 'to'>[]): TapNode[] {
  const seen = new Set<string>()
  const queue = edges.filter(e => e.to === id).map(e => e.from)
  while (queue.length) {
    const cur = queue.shift()!
    if (seen.has(cur)) continue
    seen.add(cur)
    queue.push(...edges.filter(e => e.to === cur).map(e => e.from))
  }
  return topoOrder(nodes, edges).filter(n => seen.has(n.id))
}
