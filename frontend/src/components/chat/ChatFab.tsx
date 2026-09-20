import { createPortal } from 'react-dom'
import { useEffect, useRef, useState } from 'react'
import { FocusScope } from '@radix-ui/react-focus-scope'
import { Icon } from '../Icon'
import { isLive, useProjectTasks } from '../../lib/taskCenter'
import { useDraggableFab } from '../../lib/useDraggableFab'
import { setChatOpen, useActivePid, useUi, consumeChatRequest } from '../../lib/uiContext'
import { ChatDock } from './ChatDock'
import './chatFab.css'

const POS_KEY = 'chat-fab-pos'
const FAB = 44 // 浮标直径，与 .chat-fab 的 width/height 保持一致（拖动钳制要用）

/** 「AI 对话」全局常驻浮标 + 右下角悬浮面板：全站唯一对话入口（App.tsx 挂一次）。
 * - 浮标 portal 到 body 且 fixed 定位，可拖动挪开（复用任务队列浮标验证过的方案）；
 *   徽标 = 当前/最近活跃项目的在途任务数（SSE 实时），近期有失败亮警示。
 * - 点击展开悬浮面板 = ChatDock（对话 + 任务队列两 tab），scope 自动跟随当前
 *   页面（画布/项目/全站兜底），z 分层压过普通弹窗、让位给置顶弹窗（日志等）。
 * - 原项目工作台的「任务队列」浮标（TaskQueueButton）已并入这里。 */
export function ChatFab() {
  const ui = useUi()
  const pid = useActivePid()
  const tasks = useProjectTasks(pid)
  const liveN = tasks.filter(isLive).length
  const hasFailed = tasks.some(t => t.status === 'failed')
  const { style, dragging, moved, handlers } = useDraggableFab(POS_KEY, FAB, FAB)

  // ── 通用下发通道（2026-09-18）：本组件常驻，ChatDock 只在面板展开时挂载，
  // 所以请求在这里受理：自动展开面板并把指令传下去，ChatDock 会话就绪后自动发送。
  const [autoSend, setAutoSend] = useState<typeof ui.chatRequest>(null)
  const handledReqRef = useRef(0)
  const req = ui.chatRequest
  useEffect(() => {
    if (!req || req.id === handledReqRef.current) return
    handledReqRef.current = req.id
    consumeChatRequest(req.id)
    setChatOpen(true)
    setAutoSend(req)
  }, [req, req?.id])

  return createPortal(
    <>
      {/* 面板展开时收起浮标：浮标留在原地只会压在面板上 */}
      {!ui.chatOpen && (
        <button className={'chat-fab' + (dragging ? ' dragging' : '')}
          style={style} title="AI 对话 / 任务队列"
          {...handlers}
          onClick={() => { if (!moved.current) setChatOpen(true) }}>
          <Icon name="chat" />
          {liveN > 0
            ? <span className="chat-fab-badge">{liveN > 99 ? '99+' : liveN}</span>
            : hasFailed && <span className="chat-fab-badge err">!</span>}
        </button>
      )}
      {ui.chatOpen && (
        /* FocusScope：借 radix 焦点栈的嵌套规则——新 scope mount 会把栈内旧 scope
           （身后画布/弹窗的 radix Dialog 焦点陷阱）pause，面板关了自动恢复。
           不加它：画布开着时真实点击输入框，焦点刚落就被 Dialog 的 FocusScope
           拉回弹窗（实测焦点落在弹窗关闭键上，打字全丢）。
           自己不 trapped：面板不能反向劫持，用户点画布节点仍要能聚焦。 */
        <FocusScope trapped={false} asChild>
          <div className="chat-float"><ChatDock onClose={() => setChatOpen(false)}
            autoSend={autoSend} onAutoSent={() => setAutoSend(null)} /></div>
        </FocusScope>
      )}
    </>,
    document.body)
}
