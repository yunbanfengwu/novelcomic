import { useState } from 'react'
import { Icon, type IconName } from '../../components/Icon'

/** Bottom canvas action bar. The node runtime owns progress/loading; the smart
 * generate button remains a normal send button. Both an optional special requirement
 * and an empty input use the same execute-canvas-then-chat path. */
export function TapflowRail({ onAdd,
                             onAssets, onInstruct,
                             onRunNow, onRun }: {
  onAdd?: () => void
  /** 资产库：打开项目素材面板（生产态有项目归属时才有） */
  onAssets?: () => void
  /** 指令下发：输入框内容送进对话面板，走 AI 规划链路。不给则不渲染输入框 */
  onInstruct?: (text: string) => void
  /** 直接运行（不开面板）。生产态专用 */
  onRunNow?: () => void
  /** 打开运行管理面板（编排台的运行入口） */
  onRun?: () => void
}) {
  const [text, setText] = useState('')
  const send = () => {
    const t = text.trim()
    if (onInstruct) {
      // Empty special requirements use the same execute-then-chat path.
      onInstruct(t)
      setText('')
      return
    }
    ;(onRunNow ?? onRun)?.()
  }
  const hasText = !!text.trim()
  const runTitle = hasText ? 'Execute canvas, then send special requirement'
    : 'Execute canvas and send to conversation'
  return (
    <div className="tap-rail" onPointerDown={e => e.stopPropagation()}>
      {onAdd && btn('plus', '新建最小集', onAdd)}
      <button type="button" className="tap-rail-btn" title={onAssets ? '资产库' : '资产库（进入业务场景后可用：按项目素材添加参考）'}
        disabled={!onAssets} onClick={onAssets}>
        <Icon name="blocks" />
      </button>
      {onInstruct && (
        <div className="tap-rail-input">
          <input
            value={text}
            placeholder="执行此画布~"
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') send() }} />
          <button type="button" className="tap-rail-go" title={runTitle}
            onClick={send}>
            智能生成
            <span className="tap-rail-go-badge">
              <Icon name="send" className="go-plane" />
            </span>
          </button>
        </div>
      )}
    </div>
  )
}

function btn(icon: IconName, title: string, onClick?: () => void) {
  return (
    <button type="button" className="tap-rail-btn" title={title} onClick={onClick}>
      <Icon name={icon} />
    </button>
  )
}
