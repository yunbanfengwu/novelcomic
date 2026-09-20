import { bezierPath } from '../../lib/canvasGeometry'
import { edgeAnchors, edgesBounds } from '../../lib/tapflowEdges'
import type { TapEdge, TapNode } from '../../lib/tapflowData'

/**
 * 连线层：源右锚点 → 目标左锚点 的三次贝塞尔。
 *
 * 命中靠**两条 path 一起**：细的可见线本身也能点（鼠标就悬在它上面，最直觉），
 * 外加一条 24px 宽的透明命中线兜住「差几个像素」的手抖。只给透明线绑事件时，
 * 用户在可见线上点半天没反应——那条透明线在 DOM 里，但他看不见。
 * svg 按内容包围盒定尺寸并把世界坐标平移进去，只靠 overflow:visible 命中不了。
 */
export function TapflowEdges({ edges, byId, midY, heights, titleH, selected, onSelect }: {
  edges: TapEdge[]
  byId: Map<string, TapNode>
  midY: (n: TapNode) => number
  heights: Record<string, number>
  titleH: number
  /** 选中的连线 id 集合；空/缺省 = 未选。传 onSelect 才可点选 */
  selected?: string[]
  onSelect?: (id: string, additive?: boolean) => void
}) {
  const b = edgesBounds([...byId.values()], heights, titleH)
  const sel = selected ?? []
  return (
    <svg className={'tap-edges' + (onSelect ? ' pickable' : '')}
      style={{ left: b.x, top: b.y, width: b.w, height: b.h }}>
      <g transform={`translate(${-b.x}, ${-b.y})`}>
        {edges.map(e => {
          const a = byId.get(e.from), z = byId.get(e.to)
          if (!a || !z) return null
          const p = edgeAnchors(e, byId, midY, edges, titleH)
          if (!p) return null
          const d = bezierPath(p.sx, p.sy, p.tx, p.ty)
          return (
            <g key={e.id} className={'tap-edge' + (sel.includes(e.id) ? ' sel' : '')}
              onPointerDown={onSelect
                ? ev => { ev.stopPropagation(); onSelect(e.id, ev.shiftKey || ev.metaKey) }
                : undefined}>
              <path className="tap-edge-line" d={d} style={{ pointerEvents: 'stroke' }} />
              {onSelect && <path className="tap-edge-hit" d={d} style={{ pointerEvents: 'stroke' }} />}
            </g>
          )
        })}
      </g>
    </svg>
  )
}
