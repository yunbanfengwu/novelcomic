import { useEffect, useSyncExternalStore } from 'react'
import { api } from '../api'
import type { TaskInfo } from '../api'

// ═══════════ 全局任务中心（SSE 订阅 + 单一 store）═══════════
// 取代各组件散装 setInterval 轮询：每个项目一条 EventSource 长连接，
// 连接即收全量快照（type=snapshot），此后增量收任务状态转移（type=task）
// 与流式拆镜逐镜产出（type=shot / shots_reset）。断线由 EventSource 自动重连，
// 重连再收快照收敛；服务端异常关闭（HTTP 错误）由本层 5s 定时重建兜底。

/** 在途状态（与后端 flow.LIVE_STATUSES 同口径） */
const LIVE = new Set(['waiting_deps', 'pending', 'running', 'waiting_external'])
export const isLive = (t: TaskInfo) => LIVE.has(t.status)

export interface ShotStreamEvent {
  type: 'shot' | 'shots_reset'
  chapter_id: number
  shot_no?: number
  count?: number
  final?: boolean
}

/** 智能体编排运行画布的节点级实时进度（见后端 agent_progress.py）。
 * `run_token` 是前端发起这次运行时生成的一次性值，同一条项目 SSE 上可能混着
 * 别的运行/别的标签页的事件，订阅方按 run_token 自己过滤。 */
export interface AgentNodeEvent {
  type: 'agent_node'
  run_token: string
  slug: string
  section: 'before' | 'run' | 'output' | 'next'
  field: string
  value: string
  item_id?: number | null
  label: string
  state: 'running' | 'done' | 'failed'
  source: 'test' | 'production'
  content?: string | null
  url?: string | null
  error?: string | null
  /** 输出产物段入队成功时带上："已入队"≠"已生成"，前端拿它盯 task_queue 终态 */
  task_id?: number | null
}

type ServerEvent =
  | { type: 'snapshot'; tasks: TaskInfo[] }
  | { type: 'task'; task: TaskInfo }
  | ShotStreamEvent
  | AgentNodeEvent

class ProjectTaskStore {
  private pid: number
  private tasks = new Map<number, TaskInfo>()
  private snapshot: TaskInfo[] = []
  private listeners = new Set<() => void>()
  private shotListeners = new Set<(ev: ShotStreamEvent) => void>()
  private agentListeners = new Set<(ev: AgentNodeEvent) => void>()
  private es: EventSource | null = null
  private retry: ReturnType<typeof setTimeout> | null = null
  refs = 0

  constructor(pid: number) { this.pid = pid }

  connect() {
    if (this.es) return
    const es = new EventSource(api.taskEventsUrl(this.pid))
    this.es = es
    es.onmessage = e => {
      try { this.apply(JSON.parse(e.data) as ServerEvent) } catch { /* 非 JSON 心跳忽略 */ }
    }
    // 网络断连 EventSource 自动重连；服务端 HTTP 错误会永久关闭 → 5s 后重建
    es.onerror = () => {
      if (es.readyState !== EventSource.CLOSED || this.es !== es) return
      this.es = null
      this.retry = setTimeout(() => { this.retry = null; if (this.refs > 0) this.connect() }, 5000)
    }
  }

  private apply(ev: ServerEvent) {
    if (ev.type === 'snapshot') {
      this.tasks = new Map(ev.tasks.map(t => [t.id, t]))
    } else if (ev.type === 'task') {
      this.tasks.set(ev.task.id, ev.task)
    } else if (ev.type === 'agent_node') {
      this.agentListeners.forEach(fn => fn(ev))
      return
    } else {
      this.shotListeners.forEach(fn => fn(ev))
      return
    }
    this.snapshot = [...this.tasks.values()].sort((a, b) => a.id - b.id)
    this.listeners.forEach(fn => fn())
  }

  /** 入队后乐观占位（API 返回与 SSE 事件之间的毫秒窗口内按钮即刻置忙）；SSE 到达后被真实数据覆盖 */
  optimistic(partial: Pick<TaskInfo, 'id' | 'kind'> & Partial<TaskInfo>) {
    if (this.tasks.has(partial.id)) return
    this.apply({
      type: 'task',
      task: {
        project_id: this.pid, node_id: null, status: 'pending', progress: 0, error: null,
        attempt: 0, priority: 0, deps_remaining: 0, root_task_id: null, created_at: null,
        started_at: null, finished_at: null, element_id: null, node_kind: null,
        node_title: null, shot_no: null, parents: [], ...partial,
      },
    })
  }

  getSnapshot = () => this.snapshot
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn) } }
  subscribeShots = (fn: (ev: ShotStreamEvent) => void) => {
    this.shotListeners.add(fn)
    return () => { this.shotListeners.delete(fn) }
  }
  subscribeAgentNodes = (fn: (ev: AgentNodeEvent) => void) => {
    this.agentListeners.add(fn)
    return () => { this.agentListeners.delete(fn) }
  }

  acquire() {
    this.refs += 1
    if (this.close) { clearTimeout(this.close); this.close = null }
    this.connect()
  }

  release() {
    this.refs -= 1
    if (this.refs > 0 || this.close) return
    // 延迟关闭：StrictMode 卸载/重挂与页面内切换不反复重建长连接
    this.close = setTimeout(() => {
      this.close = null
      if (this.refs > 0) return
      if (this.retry) { clearTimeout(this.retry); this.retry = null }
      this.es?.close()
      this.es = null
    }, 1000)
  }

  private close: ReturnType<typeof setTimeout> | null = null
}

// store 常驻（每项目一个，不随组件卸载销毁——refs 归零只断开 SSE，数据保留供回来即用）
const stores = new Map<number, ProjectTaskStore>()

function getStore(pid: number): ProjectTaskStore {
  let s = stores.get(pid)
  if (!s) { s = new ProjectTaskStore(pid); stores.set(pid, s) }
  return s
}

const EMPTY_TASKS: TaskInfo[] = []
const noSub = () => () => {}

/** 项目任务流（实时）：在途全量 + 最近已结束。所有需要任务状态的组件订阅同一份数据。
 * pid 未定（还没选项目）时不占连接，返回空数组。 */
export function useProjectTasks(pid: number | undefined): TaskInfo[] {
  const store = pid ? getStore(pid) : null
  useEffect(() => {
    if (!store) return
    store.acquire()
    return () => store.release()
  }, [store])
  return useSyncExternalStore(store?.subscribe ?? noSub, store?.getSnapshot ?? (() => EMPTY_TASKS))
}

/** 流式拆镜逐镜事件订阅（shot / shots_reset）：前端实时逐镜刷新用 */
export function useShotStream(pid: number, onEvent: (ev: ShotStreamEvent) => void) {
  useEffect(() => {
    const s = getStore(pid)
    s.acquire()
    const off = s.subscribeShots(onEvent)
    return () => { off(); s.release() }
  }, [pid, onEvent])
}

/** 智能体编排节点级进度订阅：pid 未定（还没选项目）时什么都不做——
 * 运行画布在没有项目上下文时本来也跑不起来。 */
export function useAgentNodeEvents(pid: number | undefined,
                                   onEvent: (ev: AgentNodeEvent) => void) {
  useEffect(() => {
    if (!pid) return
    const s = getStore(pid)
    s.acquire()
    const off = s.subscribeAgentNodes(onEvent)
    return () => { off(); s.release() }
  }, [pid, onEvent])
}

/** 入队后立即占位（无需等 SSE 回包）：给按钮即时 busy 反馈 */
export function noteEnqueued(pid: number, task: Pick<TaskInfo, 'id' | 'kind'> & Partial<TaskInfo>) {
  getStore(pid).optimistic(task)
}
