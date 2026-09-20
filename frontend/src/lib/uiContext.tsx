import { useSyncExternalStore } from 'react'
import type { ChatMsg, ChatScope } from '../components/chat/chatTypes'

/** 全站 UI 感知 store（2026-09）：
 * 右下角全局对话悬浮球要能「感知用户在哪」——当前页面、打开的弹窗、当前项目、
 * 以及页面里注册进来的深度上下文（画布节点清单等）。本模块是唯一事实来源：
 *
 * - 页面位置：UiContextProvider 挂在 App.tsx，路由切换自动解析成语义位置；
 * - 弹窗：components/Modal 一处埋点（push/pop），全站弹窗自动可感知；
 * - 深度上下文：页面/弹窗挂载时 registerChatContributor 注册，卸载注销——
 *   画布注册 scope + 上下文生成器 + 动作处理器，对话面板按 scope 隔离会话；
 * - 注入消息：画布运行日志桥接出的瞬态对话消息走 pushChatInject，不落库。
 *
 * store 是模块级单例 + useSyncExternalStore，portal 出去的浮层（对话面板、
 * 任务日志弹框）与 React 树位置无关地共享同一份状态。 */

/** 深度上下文贡献者：某个页面/弹窗（如画布）注册自己的对话能力。
 * id 唯一；重复注册按 id 覆盖，unmount 时 unregisterChatContributor(id)。 */
export interface ChatContributor {
  id: string
  /** 该页面会话的作用域（画布 = tapflow slug@version） */
  scope: ChatScope
  /** 每次提问时实时生成的深度上下文摘要（拼进发给 AI 的上下文） */
  contextBuilder?: () => string | undefined
  /** AI 回复携带的动作（如 focus_node）；返回 true = 已消费，不再向后分发 */
  onAction?: (action: Record<string, unknown>) => boolean | Promise<boolean>
  /** 输入框 @ 可引用的实体（画布节点等），选中后以 @名称 胶囊插入消息 */
  mentions?: () => { id: string; title: string }[]
}

/**
 * A completed canvas artifact is a visible assistant message.  It is kept as
 * a short lived event in the UI store so the canvas can publish it without
 * importing ChatDock (which is rendered in a portal).  ChatDock persists the
 * event in the active conversation and renders it as normal assistant output.
 */
export interface ChatResultEvent {
  id: number
  scope: ChatScope
  nodeKey: string
  nodeTitle?: string
  nodeType?: string
  content: string
  mediaUrl?: string
}

export interface UiState {
  route: string
  /** 语义页面名：桌面 / 章节工作台 / 系统管理 / 画布窗口 / 绘图画布 */
  page: string
  /** 页面附加语义（项目 N · 视频模式 · 第 12 章 / 管理子页 / 画布 slug） */
  detail?: string
  /** 路由解析出的当前项目 id（/project/:id） */
  projectId?: number
  /** 打开中的弹窗标题栈（Modal 埋点；后开在上） */
  modalStack: string[]
  /** 全局对话面板开合（悬浮球 / 各页面入口按钮都改这同一个状态） */
  chatOpen: boolean
  /** 活跃贡献者（后注册的在上，dispatch 从栈顶先试） */
  contributors: ChatContributor[]
  /** 瞬态注入消息（画布运行日志等），追加在持久化消息后，不落库 */
  inject: { msgs: ChatMsg[]; v: number }
  /** 待发送的对话请求（通用下发通道，2026-09-18）：画布生成条等任何入口
   * 把指令投递进来，对话面板自动展开并作为用户消息发出——
   * 走同一条流式规划链路（思考过程→逐字输出→画布动作），执行全程可见。 */
  chatRequest: { id: number; text: string; scope?: ChatScope; meta?: Record<string, unknown> } | null
  /** Latest completed canvas artifact awaiting persistence by ChatDock. */
  chatResult: ChatResultEvent | null
}

let state: UiState = {
  route: '', page: '', modalStack: [], chatOpen: false,
  contributors: [], inject: { msgs: [], v: 0 },
  chatRequest: null, chatResult: null,
}
const subs = new Set<() => void>()
function update(patch: Partial<UiState>) {
  state = { ...state, ...patch }
  subs.forEach(f => f())
}
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f) } }
const snapshot = () => state

/** 订阅全站 UI 态。页面/弹窗变化、面板开合、贡献者增删都会触发重渲染。 */
export function useUi(): UiState { return useSyncExternalStore(subscribe, snapshot) }

// ── 页面位置：路由 → 语义（解析逻辑在 UiContextProvider.tsx，全站唯一实例） ──

/** 供 UiContextProvider 写入路由解析结果；其余代码不应调用。 */
export function setRouteLocation(patch: {
  route: string; page: string; detail?: string; projectId?: number
}) {
  update(patch)
}

// ── 当前项目：路由优先，否则回落最近活跃项目（进项目页时自动记录） ──────────
export function useActivePid(): number | undefined {
  const { projectId } = useUi()
  if (projectId) return projectId
  try {
    const v = localStorage.getItem('ui-last-pid')
    const n = v ? Number(v) : NaN
    if (Number.isFinite(n) && n > 0) return n
  } catch { /* ignore */ }
  return undefined
}

// ── 弹窗感知：Modal 组件一处埋点，全站弹窗自动进栈 ─────────────────────────
export function pushModal(title: string) {
  if (state.modalStack[state.modalStack.length - 1] === title) return
  update({ modalStack: [...state.modalStack, title] })
}
export function popModal(title: string) {
  if (!state.modalStack.includes(title)) return
  update({ modalStack: state.modalStack.filter(t => t !== title) })
}

// ── 全局对话面板开合（悬浮球 / 其它入口全走这里） ─────────────────────────
// 面板是右侧停靠区：开合同步到 body class，页面(#root)与弹窗(rx-modal/Lightbox)
// 通过 CSS 让位挤压（见 chatFab.css 的 body.chat-dock-open 规则组）
export function setChatOpen(v: boolean) {
  if (state.chatOpen !== v) update({ chatOpen: v })
  try { document.body.classList.toggle('chat-dock-open', v) } catch { /* SSR/测试环境忽略 */ }
}

// ── 深度上下文贡献者注册 ────────────────────────────────────────────────
export function registerChatContributor(c: ChatContributor) {
  update({ contributors: [...state.contributors.filter(x => x.id !== c.id), c] })
}
export function unregisterChatContributor(id: string) {
  if (!state.contributors.some(x => x.id === id)) return
  update({ contributors: state.contributors.filter(x => x.id !== id) })
}

/** AI 回复动作分发：从栈顶（最后注册、最贴近当前视图的页面）向下找第一个消费者。 */
export async function dispatchChatAction(action: Record<string, unknown>): Promise<boolean> {
  for (let i = state.contributors.length - 1; i >= 0; i--) {
    if (await state.contributors[i].onAction?.(action)) return true
  }
  return false
}

// ── 瞬态注入消息（画布运行日志桥接等），追加在会话消息之后、不落库 ──────────
export function pushChatInject(msgs: ChatMsg[]) {
  update({ inject: { msgs, v: state.inject.v + 1 } })
}
export function clearChatInject() {
  if (state.inject.msgs.length) update({ inject: { msgs: [], v: state.inject.v + 1 } })
}

// ── 通用对话下发通道（2026-09-18） ────────────────────────────────────
/** 画布生成条「发送」等入口把指令投递给对话面板：面板自动展开、
 * 指令作为用户消息自动发出，走流式规划链路（思考→输出→画布动作）。
 * onSent：指令真正发进会话（用户气泡上屏、AI 开始接手）时回调——
 * 入口按钮的 loading 只需盖到这一刻，后续节点执行进度由对话区展示。
 * id 带随机尾数防同毫秒碰撞；ChatDock 按 id 去重消费。 */
export function requestChatSend(text: string, options?: { scope?: ChatScope; meta?: Record<string, unknown>; onSent?: () => void }) {
  const t = text.trim()
  if (!t) return
  update({ chatRequest: { id: Date.now() + Math.random(), text: t, ...options } })
}
/** ChatDock 消费完成后清除，避免重开面板重发 */
export function consumeChatRequest(id: number) {
  if (state.chatRequest?.id === id) update({ chatRequest: null })
}

/** Publish a completed node artifact to the active canvas conversation. */
export function publishChatResult(event: Omit<ChatResultEvent, 'id'>) {
  update({ chatResult: { ...event, id: Date.now() + Math.random() } })
}

export function clearChatResult(id: number) {
  if (state.chatResult?.id === id) update({ chatResult: null })
}
