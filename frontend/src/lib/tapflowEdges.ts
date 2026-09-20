// tapflow 画布连线的纯几何/图论（零 JSX）：拖线落点命中、连线合法性、连线中点。
import type { TapEdge, TapNode } from './tapflowData'

/** 节点占位矩形：h 优先用实测高度（含标题行），未测到时用声明高度兜底 */
export function nodeRect(n: TapNode, heights: Record<string, number>, titleH: number) {
  return { x: n.x, y: n.y, w: n.w, h: heights[n.id] ?? titleH + n.h }
}

/** 世界坐标 (wx,wy) 命中的节点（后声明的在上层，故倒序找） */
export function nodeAt(nodes: TapNode[], wx: number, wy: number,
                       heights: Record<string, number>, titleH: number): TapNode | null {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const r = nodeRect(nodes[i], heights, titleH)
    if (wx >= r.x && wx <= r.x + r.w && wy >= r.y && wy <= r.y + r.h) return nodes[i]
  }
  return null
}

/** from 能否沿连线走到 target（用于成环判断） */
function reaches(edges: TapEdge[], from: string, target: string): boolean {
  const seen = new Set([from])
  const queue = [from]
  while (queue.length) {
    const cur = queue.shift()!
    if (cur === target) return true
    for (const e of edges) {
      if (e.from === cur && !seen.has(e.to)) { seen.add(e.to); queue.push(e.to) }
    }
  }
  return false
}

/** 能否新建 from→to：不自环、不重复（含反向重复）、不成环 */
export function canConnect(edges: TapEdge[], from: string, to: string): boolean {
  if (from === to) return false
  if (edges.some(e => (e.from === from && e.to === to) || (e.from === to && e.to === from))) return false
  return !reaches(edges, to, from)
}

/** bezierPath 的 t=0.5 中点：两端控制点只在 x 上平移，弯度项恰好抵消，即两端点均值 */
export const edgeMid = (x1: number, y1: number, x2: number, y2: number) =>
  ({ x: (x1 + x2) / 2, y: (y1 + y2) / 2 })

/** 连线两端锚点。与 TapflowEdges 里画线用的是**同一套规则**（包括选择器分支端口
 * 在右侧各占一行）——两处各写一份，删线按钮/框选命中就会跟看到的线错开。 */
export function edgeAnchors(e: TapEdge, byId: Map<string, TapNode>,
                            midYOf: (n: TapNode) => number, edges: TapEdge[], titleH: number) {
  const a = byId.get(e.from), z = byId.get(e.to)
  if (!a || !z) return null
  const byBranch = a.type === 'condition' && e.branch
    ? (a.condition?.branches ?? []).findIndex(b => b.id === e.branch) : -1
  const idx = byBranch >= 0 ? byBranch
    : a.type === 'condition' ? edges.filter(x => x.from === a.id).findIndex(x => x.id === e.id) : -1
  return {
    sx: idx >= 0 ? a.x + a.w - 14 : a.x + a.w,
    sy: idx >= 0 ? a.y + titleH + 17 + idx * 38 : midYOf(a),
    tx: z.x, ty: midYOf(z),
  }
}

/** 线段与矩形是否相交（框选连线用）。直线近似就够：用户框的是「这条线大致在这里」，
 * 真按贝塞尔曲线算反而会把擦着弯道经过的框判成命中。 */
export function segHitsBox(x1: number, y1: number, x2: number, y2: number,
                           box: { x: number; y: number; w: number; h: number }): boolean {
  const inside = (x: number, y: number) =>
    x >= box.x && x <= box.x + box.w && y >= box.y && y <= box.y + box.h
  if (inside(x1, y1) || inside(x2, y2)) return true
  const x3 = box.x, y3 = box.y, x4 = box.x + box.w, y4 = box.y + box.h
  const cross = (ax: number, ay: number, bx: number, by: number, cx: number, cy: number) =>
    (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
  const segCross = (ax: number, ay: number, bx: number, by: number,
                    cx: number, cy: number, dx: number, dy: number) =>
    cross(ax, ay, bx, by, cx, cy) * cross(ax, ay, bx, by, dx, dy) <= 0
      && cross(cx, cy, dx, dy, ax, ay) * cross(cx, cy, dx, dy, bx, by) <= 0
  return segCross(x1, y1, x2, y2, x3, y3, x4, y3)
    || segCross(x1, y1, x2, y2, x4, y3, x4, y4)
    || segCross(x1, y1, x2, y2, x4, y4, x3, y4)
    || segCross(x1, y1, x2, y2, x3, y4, x3, y3)
}

/** 连线层 svg 的世界包围盒。svg 尺寸必须真实覆盖内容——只靠 overflow:visible
 * 画得出来却命中不了，连线就点不中（1×1 的 svg 只有 1px 可点）。 */
export function edgesBounds(nodes: TapNode[], heights: Record<string, number>, titleH: number) {
  if (!nodes.length) return { x: 0, y: 0, w: 1, h: 1 }
  const pad = 400
  const rects = nodes.map(n => nodeRect(n, heights, titleH))
  const x = Math.min(...rects.map(r => r.x)) - pad
  const y = Math.min(...rects.map(r => r.y)) - pad
  return {
    x, y,
    w: Math.max(...rects.map(r => r.x + r.w)) + pad - x,
    h: Math.max(...rects.map(r => r.y + r.h)) + pad - y,
  }
}
