import { useState } from 'react'
import type { TapNode } from '../../lib/tapflowData'

/**
 * 文本节点的卡内正文，双击进编辑、失焦提交。
 *
 * 改完的正文下次运行会**整段覆盖该节点产出并落库**——这里不是本地便签，
 * 是真能改到下游的输入（装配器只认库里的值，不认画布）。
 * 编辑态的局部状态跟着这件走，主节点件不必背这个 useState。
 */
export function TapflowNodeText({ node, onText, editing, onEditDone }: {
  node: TapNode
  /** 不给则不可编辑（只读展示） */
  onText?: (id: string, text: string) => void
  /** 由画布控制的编辑态（工具条「编辑」）；本组件内双击也能进 */
  editing?: boolean
  onEditDone?: () => void
}) {
  const [self, setSelf] = useState(false)
  const on = editing || self
  const done = () => { setSelf(false); onEditDone?.() }
  if (on) {
    return (
      <textarea
        className="tap-node-text tap-node-edit" defaultValue={node.text ?? ''} autoFocus
        // 画布在外层监听拖拽/空格平移/滚轮缩放——编辑时别让它们冒泡出去
        onPointerDown={e => e.stopPropagation()}
        onKeyDown={e => e.stopPropagation()}
        onWheel={e => e.stopPropagation()}
        onBlur={e => {
          done()
          if (e.target.value !== (node.text ?? '')) onText?.(node.id, e.target.value)
        }} />
    )
  }
  return (
    <div className="tap-node-text" onDoubleClick={() => onText && setSelf(true)}>
      {node.text || <span className="placeholder">双击开始编辑…</span>}
    </div>
  )
}
