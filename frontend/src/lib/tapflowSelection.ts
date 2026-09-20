// tapflow 画布「框选 / 多选」的纯逻辑（零 JSX）：矩形命中、选区包围盒、批量复制。
// 命中与包围盒都走 tapflowEdges.nodeRect（节点占位矩形的唯一实现），别再各算一份。
import type { TapEdge, TapNode } from './tapflowData'
import { nodeRect } from './tapflowEdges'

export interface Rect { x: number; y: number; w: number; h: number }

const hits = (a: Rect, b: Rect) =>
  a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y

/** 与框选矩形**相交**（不要求整个圈住）的节点 id。世界坐标。 */
export function nodesInRect(nodes: TapNode[], rect: Rect,
                            heights: Record<string, number>, titleH: number): string[] {
  return nodes.filter(n => hits(rect, nodeRect(n, heights, titleH))).map(n => n.id)
}

/** 一组节点的世界包围盒（多选工具条锚在它的上边中点）；一个都没命中返回 null */
export function selectionBounds(nodes: TapNode[], ids: string[],
                                heights: Record<string, number>, titleH: number): Rect | null {
  const rs = nodes.filter(n => ids.includes(n.id)).map(n => nodeRect(n, heights, titleH))
  if (!rs.length) return null
  const x = Math.min(...rs.map(r => r.x))
  const y = Math.min(...rs.map(r => r.y))
  return {
    x, y,
    w: Math.max(...rs.map(r => r.x + r.w)) - x,
    h: Math.max(...rs.map(r => r.y + r.h)) - y,
  }
}

/** 一张流程只有一个开始节点：它不参与复制/删除 */
export const selectable = (n: TapNode) => n.type !== 'start'

/** 组：把一批节点圈成一块（**纯画布视觉**，不进图数据，也不参与运行） */
export interface TapGroup { id: string; name: string; nodeIds: string[] }
/** 组框比成员包围盒外扩这么多（世界坐标），给标题与呼吸留位 */
export const GROUP_PAD = 26

let groupSeq = 0
/** seq 只保证 id 唯一（模块级、跨画布递增）；显示名由调用方按**本画布**的组数给 */
export function newGroup(nodeIds: string[], index: number): TapGroup {
  return { id: `g-${++groupSeq}`, name: `组 ${index}`, nodeIds: [...nodeIds] }
}

/** 两个 id 集合是不是同一批（判断当前选中是否恰好等于某个组 → 按钮切「解组」） */
export const sameIds = (a: string[], b: string[]) =>
  a.length === b.length && [...a].sort().join() === [...b].sort().join()

/** 节点被删/被过滤后修剪组：成员少于 2 个的组自动消失（一个节点的组没有意义） */
export function pruneGroups(groups: TapGroup[], aliveIds: Set<string>): TapGroup[] {
  const next = groups
    .map(g => ({ ...g, nodeIds: g.nodeIds.filter(id => aliveIds.has(id)) }))
    .filter(g => g.nodeIds.length > 1)
  const same = next.length === groups.length
    && next.every((g, i) => sameIds(g.nodeIds, groups[i].nodeIds))
  return same ? groups : next
}

let copySeq = 0
/**
 * 复制一批节点：新 id + 整体偏移；**两端都在选区内**的连线一并复制（跨出选区的不带，
 * 否则副本会挂回原图的上下游，语义上不是「副本」而是「多连了几条线」）。
 * 返回的是**新增部分**，由调用方追加进画布状态。
 */
export function duplicateSelection(nodes: TapNode[], edges: TapEdge[], ids: string[],
                                   offset = 48): { nodes: TapNode[]; edges: TapEdge[] } {
  const src = nodes.filter(n => ids.includes(n.id) && selectable(n))
  if (!src.length) return { nodes: [], edges: [] }
  const seq = ++copySeq
  const idMap = new Map(src.map(n => [n.id, `${n.id}-copy${seq}`]))
  return {
    nodes: src.map(n => ({ ...n, id: idMap.get(n.id)!, x: n.x + offset, y: n.y + offset })),
    edges: edges
      .filter(e => idMap.has(e.from) && idMap.has(e.to))
      .map(e => ({
        ...e,
        id: `${e.id}-copy${seq}`,
        from: idMap.get(e.from)!,
        to: idMap.get(e.to)!,
      })),
  }
}
