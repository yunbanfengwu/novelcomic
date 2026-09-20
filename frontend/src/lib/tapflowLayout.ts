// Tapflow 拓扑列布局：普通节点按最长路径分列，循环为自己的实例组预留扩展列。
import type { TapEdge, TapNode } from './tapflowData'

// 列距/行距（2026-09-2X 放宽）：画布常年在 0.4 倍缩放下看，留白太窄整张图就是
// 一坨挤在一起的卡片——列间要能容下 1.5 倍挂载点的溢出，行间要能分清上下两条链
export const COL_GAP = 200
export const ROW_GAP = 96
export const LAYOUT_MARGIN = 40
export const COLUMN_WIDTH = 560
export const COLUMN_STEP = COLUMN_WIDTH + COL_GAP

const fullH = (n: TapNode, heights: Record<string, number>, titleH: number) =>
  heights[n.id] ?? titleH + n.h

export function layoutPositions(
  nodes: TapNode[], edges: Pick<TapEdge, 'from' | 'to'>[],
  heights: Record<string, number> = {}, titleH = 26,
): Map<string, { x: number; y: number }> {
  const out = new Map<string, { x: number; y: number }>()
  if (!nodes.length) return out
  const byId = new Map(nodes.map(n => [n.id, n]))
  const ids = new Set(byId.keys())
  const live = edges.filter(e => ids.has(e.from) && ids.has(e.to))

  const depth = new Map(nodes.map(n => [n.id, 0]))
  for (let i = 0; i < nodes.length; i++) {
    let moved = false
    for (const e of live) {
      const a = depth.get(e.from)!, b = depth.get(e.to)!
      if (a + 1 > b) { depth.set(e.to, a + 1); moved = true }
    }
    if (!moved) break
  }

  // 只有运行投影真的展开出实例时才需要预留扩展列。编辑态的循环体模板已经
  // 自然处在 loop 的下一层；再把 loop 本身当 owner 会多预留一整列，形成空洞。
  // 运行态即使母卡不在 nodes 中，也能通过 runtime.loopOwner 还原 owner。
  const ownersByDepth = new Map<number, string[]>()
  for (const n of nodes.filter(n => !!n.runtime?.loopOwner)) {
    const owner = n.runtime!.loopOwner!
    if (!owner) continue
    const d = byId.has(owner)
      ? (depth.get(owner) ?? 0)
      : Math.max(0, (depth.get(n.id) ?? 0) - 1)
    const owners = ownersByDepth.get(d) ?? []
    if (!owners.includes(owner)) ownersByDepth.set(d, [...owners, owner])
  }
  const slotsBefore = (d: number) => [...ownersByDepth.entries()]
    .filter(([at]) => at < d).reduce((sum, [at, owners]) => {
      const projected = nodes.some(n => n.runtime && n.runtime.loopOwner
        && (byId.has(n.runtime.loopOwner) ? depth.get(n.runtime.loopOwner) : (depth.get(n.id) ?? 1) - 1) === at)
      // 运行图的实例边已经自然增加了一层，只补同列额外循环所需的列。
      return sum + Math.max(0, owners.length - (projected ? 1 : 0))
    }, 0)

  // 开始节点永远独占最左一条列线：它是整张流程的入口，别的根节点不许与它同列，
  // 其余节点一律往后顺延一列。（开始节点被拖去负列是用户的手工摆位，重排时拉回）
  const startNode = nodes.find(n => n.type === 'start' && !n.runtime) ?? null
  const colShift = startNode ? 1 : 0

  // 结束节点 = 没有出边的节点（产物/挂载点这一类终点）。它们不参与基础列排序，
  // 最后统一排进「所有内容列之后」的专用结束列——结束永远是自己的一条线，
  // 不会跟中间过程挤在同一列里。
  const hasOut = new Set(live.map(e => e.from))
  const isEndNode = (n: TapNode) => !n.runtime && n !== startNode && !hasOut.has(n.id)

  // 普通节点与 loop 模板先排入基础列；运行实例稍后按 owner 单独成组。
  const cols = new Map<number, TapNode[]>()
  for (const n of nodes.filter(n => !n.runtime && n !== startNode && !isEndNode(n))) {
    const d = depth.get(n.id) ?? 0
    const col = d + slotsBefore(d) + colShift
    cols.set(col, [...(cols.get(col) ?? []), n])
  }
  // 内容最右到哪一列：结束列要排在它后面
  let maxCol = -1
  for (const [colIndex, members] of [...cols.entries()].sort(([a], [b]) => a - b)) {
    let nextY = -Infinity
    for (const n of [...members].sort((a, b) => a.y - b.y)) {
      const y = Math.max(n.y, nextY)
      out.set(n.id, {
        x: LAYOUT_MARGIN + colIndex * COLUMN_STEP + (COLUMN_WIDTH - n.w) / 2,
        y,
      })
      if (colIndex > maxCol) maxCol = colIndex
      nextY = y + fullH(n, heights, titleH) + ROW_GAP
    }
  }
  if (startNode) {
    out.set(startNode.id, {
      x: LAYOUT_MARGIN + (COLUMN_WIDTH - startNode.w) / 2,
      y: startNode.y,
    })
    if (maxCol < 0) maxCol = 0
  }

  // 每个循环拥有后一条独立扩展列。N 个实例纵向成组，组中心与 owner 中心对齐。
  // baseCol 同样要加上 colShift：实例列跟在内容列后面，开始节点占掉的那一列要跳过
  for (const [d, owners] of ownersByDepth) {
    const baseCol = d + slotsBefore(d) + colShift
    owners.forEach((owner, ownerIndex) => {
      const instances = nodes.filter(n => n.runtime?.loopOwner === owner)
        .sort((a, b) => (a.runtime?.iteration ?? 0) - (b.runtime?.iteration ?? 0))
      if (!instances.length) return
      const totalH = instances.reduce((sum, n) => sum + fullH(n, heights, titleH), 0)
        + ROW_GAP * Math.max(0, instances.length - 1)
      const ownerNode = byId.get(owner)
      const ownerPos = ownerNode ? out.get(owner) : undefined
      // 运行态母卡不在 nodes 中：用实例入边来源组的中心作为 owner 锚点。
      const incoming = live.filter(e => instances.some(n => n.id === e.to))
        .map(e => byId.get(e.from)).filter(Boolean) as TapNode[]
      const fallbackCenter = incoming.length
        ? incoming.reduce((sum, n) => sum + (out.get(n.id)?.y ?? n.y) + fullH(n, heights, titleH) / 2, 0)
          / incoming.length
        : instances[0].y + totalH / 2
      const ownerCenter = ownerNode
        ? (ownerPos?.y ?? ownerNode.y) + fullH(ownerNode, heights, titleH) / 2
        : fallbackCenter
      let y = ownerCenter - totalH / 2
      const col = baseCol + 1 + ownerIndex
      for (const n of instances) {
        out.set(n.id, {
          x: LAYOUT_MARGIN + col * COLUMN_STEP + (COLUMN_WIDTH - n.w) / 2,
          y,
        })
        if (col > maxCol) maxCol = col
        y += fullH(n, heights, titleH) + ROW_GAP
      }
    })
  }

  // 结束列：所有终点节点统一排在内容列之后的一条独立列上，纵向以整图
  // 竖直中心为基准堆叠。终点少时它独享一条线；多时同列上下排开。
  const sinks = nodes
    .filter(isEndNode)
    .sort((a, b) => (depth.get(a.id) ?? 0) - (depth.get(b.id) ?? 0) || a.y - b.y)
  if (sinks.length) {
    const endCol = maxCol + 1
    const placed = [...out.entries()]
    const centerY = placed.length
      ? placed.reduce((sum, [id, p]) =>
        sum + p.y + fullH(byId.get(id)!, heights, titleH) / 2, 0) / placed.length
      : sinks[0].y + fullH(sinks[0], heights, titleH) / 2
    const totalH = sinks.reduce((sum, n) => sum + fullH(n, heights, titleH), 0)
      + ROW_GAP * (sinks.length - 1)
    let y = centerY - totalH / 2
    for (const n of sinks) {
      out.set(n.id, {
        x: LAYOUT_MARGIN + endCol * COLUMN_STEP + (COLUMN_WIDTH - n.w) / 2,
        y,
      })
      y += fullH(n, heights, titleH) + ROW_GAP
    }
  }
  return out
}

export function applyLayout(nodes: TapNode[], edges: Pick<TapEdge, 'from' | 'to'>[]) {
  const pos = layoutPositions(nodes, edges)
  for (const n of nodes) {
    const p = pos.get(n.id)
    if (p) { n.x = p.x; n.y = p.y }
  }
}

/** 拖拽松手后的列吸附（单一实现：节点与文件夹共用，测试也打这里）。
 * 列号**不设下限**：参考线铺满整个画布，往两边拖多远都有列可吸——
 * 负列 = 开始列以左，不再被钳回第 0 列。 */
export function snapColumnX(center: number, nodeW: number): number {
  const col = Math.round((center - LAYOUT_MARGIN - COLUMN_WIDTH / 2) / COLUMN_STEP)
  return LAYOUT_MARGIN + col * COLUMN_STEP + (COLUMN_WIDTH - nodeW) / 2
}
