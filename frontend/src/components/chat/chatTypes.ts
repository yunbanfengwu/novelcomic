/** 公共对话组件的类型契约：全站通用（右下角悬浮面板是唯一宿主，见 ChatFab）。
 * 消息渲染沿用原 tapflow 对话面板的卡片格式（.tap-msg-user / .tap-msg-status /
 * .tap-msg-op / .tap-msg-ai + .tap-chat-chips），新增「运行日志折叠组」——
 * 运行日志不再是独立面板，而是拆进对话流里的一种消息。 */

export type ChatTone = 'info' | 'ok' | 'err'

export type ChatMsg =
  /** 用户消息：bubble 正文 + meta 徽标行（模型/比例/尺寸那套）；
   * pending=已上屏未落库（发请求中的乐观态） */
  | { kind: 'user'; text: string; meta?: string[]; pending?: boolean }
  /** 状态行（图标 + 文案 + sub）：引擎事件、提示类信息 */
  | { kind: 'status'; text: string; sub?: string; tone?: ChatTone }
  /** 可点操作胶囊（如「查看画布」「重新生成」） */
  | { kind: 'op'; text: string; onClick?: () => void }
  /** 助手回复：Markdown 渲染（components/Markdown）；suggestions=模型给出的
   * 后续问题建议（SUGGEST 协议，随消息存 meta，作为底部快捷问题展示）；
   * streaming=流式输出中（尾随光标，滚动跟随） */
  | { kind: 'assistant'; md: string; suggestions?: string[]; streaming?: boolean;
      media?: { url: string; kind: 'image' | 'video'; alt?: string } }
  /** 思考过程时间线（规划步骤逐步点亮）：ctx=读上下文，plan=规划步骤。
   * 随 assistant 消息的 meta.steps 持久化，历史会话里可回放。 */
  | { kind: 'think'; steps: { label: string; detail?: string; state: 'run' | 'done' | 'err' }[] }
  /** 一次运行的日志折叠组：头部一行摘要（已执行 N 个任务 + 节点名 + 查看画布），
   * 明细默认收起。由画布把引擎 eng.log 增量按 run 归组、经 uiContext 注入进来。
   * nodeId/nodeTitle 用于「查看画布」聚焦到本次运行的节点。 */
  | { kind: 'run'; label: string; lines: { t: string; text: string; kind?: ChatTone }[]; nodeId?: string; nodeTitle?: string }

/** 会话作用域：决定消息挂在哪、上下文取什么。面板的 scope 跟随当前页面
 * （见 lib/uiContext 的贡献者机制），切页面自动换会话，互不串台。
 * - tapflow：画布对话——画布注册 contributor 后自动关联画布对象，画布内容
 *   （节点/参数/最近运行）经 contextBuilder 进对话上下文。
 * - project：项目级通用对话（章节工作台等）。
 * - global：全站兜底会话（桌面/系统管理等）。 */
export interface ChatScope {
  kind: 'tapflow' | 'project' | 'global'
  slug?: string
  version?: number
  name?: string
  /** project scope 的项目 id：持久化 scope_key 用（画布 scope 用 slug@version） */
  id?: number
  /** Stable canvas identity; unlike version this does not change on draft/fork. */
  key?: string
  /** Previous version-scoped keys used to migrate existing canvas history once. */
  legacyKeys?: string[]
}

/** 会话 scope 的持久化 key：画布 = slug@version，项目 = project:{id}，全站 = global。
 * 与后端 app/api/chat.py 的 scope 约定一一对应。 */
export function chatScopeKey(scope: ChatScope): string | null {
  if (scope.kind === 'tapflow') return scope.key ?? (scope.slug ? `${scope.slug}@${scope.version ?? 0}` : null)
  if (scope.kind === 'project') return scope.id ? `project:${scope.id}` : null
  return 'global'
}
