import { useState } from 'react'
import { Icon } from '../../components/Icon'

/** 选中节点上方浮动工具条。按节点性质给不同的动作：
 * - 媒体类（图片/视频）：复制 / 裁剪 / 放大 / 重新读取 / 智能生成
 * - 文本类（场景介绍这类卡）：复制 / 编辑 / 重新读取 / 智能生成
 *
 * 「重新读取」与「智能生成」是**两件事**，分成两个按钮：前者只查库（零副作用、不花钱），
 * 后者真让模型重写并落库。混成一个按钮，用户点一下就不知道会不会产生费用。
 * 「智能生成」也不在这里执行，只是把下方的生成输入条唤出来——真正重跑要带参数，
 * 那是生成条的事（这也是唯一能强制重跑单个节点的入口：默认一律缺才跑）。 */
export function TapflowNodeToolbar({ onCopy, onCrop, onExpand, onEdit, onReload, onRegen,
                                     onRedit, onInspect, inspectorOpen }: {
  /** 返回要复制的内容；返回空串表示没什么可复制 */
  onCopy?: () => string
  onCrop?: () => void
  onExpand?: () => void
  onEdit?: () => void
  /** 只查库：把这个节点在库里的那份产物重新取回卡上（不跑模型、不写库） */
  onReload?: () => void
  onRegen?: () => void
  /** 挂载点：重新打开归宿点选列表（改产物落到哪） */
  onRedit?: () => void
  /** 开/收右侧属性面板（2026-09-17：面板不再随选中自动弹，入口统一收进这里） */
  onInspect?: () => void
  inspectorOpen?: boolean
}) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    const text = onCopy?.() ?? ''
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch { /* 剪贴板不可用（非安全上下文）时静默失败 */ }
  }
  return (
    <div className="tap-node-toolbar" onPointerDown={e => e.stopPropagation()}>
      {onCopy && (
        <button type="button" className={'tap-tool' + (copied ? ' ok' : '')}
          title={copied ? '已复制' : '复制'} onClick={copy}>
          <Icon name={copied ? 'check' : 'clipboard'} />
        </button>
      )}
      {onCrop && (
        <button type="button" className="tap-tool" title="裁剪" onClick={onCrop}><Icon name="crop" /></button>
      )}
      {onExpand && (
        <button type="button" className="tap-tool" title="放大" onClick={onExpand}><Icon name="fullscreen" /></button>
      )}
      {onEdit && (
        <button type="button" className="tap-tool" title="编辑" onClick={onEdit}><Icon name="pencil" /></button>
      )}
      {onRedit && (
        <button type="button" className="tap-tool" title="修改归宿" onClick={onRedit}><Icon name="pencil" /></button>
      )}
      {onReload && (
        <button type="button" className="tap-tool" title="重新读取" onClick={onReload}><Icon name="refresh" /></button>
      )}
      {onRegen && (
        <button type="button" className="tap-tool" title="智能生成" onClick={onRegen}><Icon name="sparkles" /></button>
      )}
      {onInspect && (
        <button type="button" className={'tap-tool' + (inspectorOpen ? ' on' : '')}
          title={inspectorOpen ? '收起属性' : '属性'} onClick={onInspect}>
          <Icon name="gear" />
        </button>
      )}
    </div>
  )
}
