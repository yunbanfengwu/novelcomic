import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type ChatConversationItem, type ChatConversationMsg, type WorkflowRun } from '../../api'
import { clearChatResult, dispatchChatAction, useActivePid, useUi } from '../../lib/uiContext'
import { Icon } from '../Icon'
import { Markdown } from '../Markdown'
import { chatScopeKey, type ChatMsg, type ChatScope } from './chatTypes'
import { TaskQueuePanel } from './TaskQueuePanel'
import './chat.css'

/** 输入框占位文案（原 CHAT_DEMO.fixture 里的真实有用项；演示假数据已删） */
const INPUT_HINT = '输入内容，/ 使用技能，@ 引用画布内容'

/** 一次运行的日志折叠卡（对齐「已执行 N 个任务」的紧凑摘要样式）：
 * 头部一行 = 状态图标 + 「正在/已执行 1 个任务」+ 节点名副标题 + 查看画布 + 展开箭头；
 * 点箭头才展开时间戳明细。点「查看画布」经贡献者动作通道聚焦本次运行的节点。 */
function RunGroup({ msg }: { msg: Extract<ChatMsg, { kind: 'run' }> }) {
  const [open, setOpen] = useState(false)
  const ui = useUi()
  const err = msg.lines.some(l => l.kind === 'err')
  const done = msg.lines.some(l => l.text.includes('运行结束') || l.text.includes('完成'))
  const running = !err && !done && msg.lines.length > 0
  // 找到当前激活的画布贡献者：「查看画布」用它把 focus_node 动作发回画布
  const contributor = ui.contributors.length ? ui.contributors[ui.contributors.length - 1] : undefined
  const focusCanvas = () => {
    if (msg.nodeId && contributor?.onAction) {
      contributor.onAction({ type: 'focus_node', node_key: msg.nodeId })
    }
  }
  return (
    <div className={'tap-msg-run' + (err ? ' err' : '') + (running ? ' running' : '')}>
      <div className="tap-msg-run-head">
        <Icon name={err ? 'alert' : running ? 'spinner' : 'check'} spin={running} />
        <div className="texts">
          <div className="title">{running ? '正在执行 1 个任务' : err ? '执行失败 · 1 个任务' : '已执行 1 个任务'}</div>
          <div className="sub">{msg.nodeTitle || msg.label}</div>
        </div>
        {msg.nodeId && contributor?.onAction && (
          <button type="button" className="tap-msg-op" onClick={focusCanvas}>
            <Icon name="clipboard" /> 查看画布
          </button>
        )}
        <button type="button" className={'caret' + (open ? ' open' : '')}
          onClick={() => setOpen(o => !o)} aria-label={open ? '收起日志明细' : '展开日志明细'}>▾</button>
      </div>
      {open && (
        <div className="tap-msg-run-lines">
          {msg.lines.map((l, i) => (
            <div key={i} className={'tap-msg-run-line' + (l.kind ? ` ${l.kind}` : '')}>
              <span className="t">{l.t}</span>
              <span className="text">{l.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** 思考过程时间线卡：规划步骤逐步点亮，完成后可折叠（历史会话里同样可回放） */
function ThinkCard({ msg }: { msg: Extract<ChatMsg, { kind: 'think' }> }) {
  const [open, setOpen] = useState(true)
  const running = msg.steps.some(s => s.state === 'run')
  return (
    <div className={'tap-msg-think' + (open ? ' open' : '')}>
      <button type="button" className="tap-think-head" onClick={() => setOpen(o => !o)}>
        <Icon name="sparkles" />
        <span>{running ? '思考中…' : '思考过程'}</span>
        <span className="count">{msg.steps.length} 步</span>
        <span className={'caret' + (open ? ' open' : '')}>▾</span>
      </button>
      {open && (
        <div className="tap-think-steps">
          {msg.steps.map((s, i) => (
            <div key={i} className={'tap-think-step ' + s.state}>
              <span className="ico">
                {s.state === 'done' ? <Icon name="check" />
                  : s.state === 'err' ? <Icon name="alert" />
                  : <Icon name="spinner" spin />}
              </span>
              <span className="label">{s.label}</span>
              {s.detail && <span className="detail">{s.detail}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const TASK_STATUS: Record<string, string> = {
  running: '运行中', done: '已完成', failed: '失败',
}

/** 画布运行记录（workflow_runs）：画布 scope 下的后台流程运行清单。
 * 与下方「项目任务队列」（task_queue）是两个体系：前者是画布流程的编排运行，
 * 后者是项目内各生成任务的依赖树。专属画布（fork 出来的 slug 形如
 * `模板slug@project-N@归宿`）的 run 也算在模板头上，所以除精确匹配外
 * 再放行「模板 slug @」前缀。 */
function CanvasRuns({ slug }: { slug: string }) {
  const [runs, setRuns] = useState<WorkflowRun[] | null>(null)
  useEffect(() => {
    let dead = false
    setRuns(null)
    api.workflowRuns()
      .then(rs => { if (!dead) setRuns(rs.filter(r => r.slug === slug || r.slug?.startsWith(`${slug}@`))) })
      .catch(() => { if (!dead) setRuns([]) })
    return () => { dead = true }
  }, [slug])
  const fmt = (iso: string) => iso?.slice(5, 16).replace('T', ' ')
  const dur = (r: WorkflowRun) => {
    if (!r.finished_at) return ''
    const ms = new Date(r.finished_at).getTime() - new Date(r.created_at).getTime()
    if (!Number.isFinite(ms) || ms < 0) return ''
    return ` · ${Math.round(ms / 1000)}s`
  }
  return (
    <div className="tq-sec" style={{ display: 'block' }}>
      <div>画布运行（最近的排在前）</div>
      {runs === null && <div className="tq-empty">正在读取运行记录…</div>}
      {runs !== null && !runs.length && <div className="tq-empty">暂无运行记录，从执行面板发起一次运行试试</div>}
      <div className="tap-task-list">
        {(runs ?? []).map(r => {
          const key = r.status === 'running' ? 'running' : r.status === 'failed' ? 'failed' : r.status === 'done' ? 'done' : 'idle'
          return (
            <div className="tap-task-row" key={r.id}>
              <span className={'tap-task-badge ' + key}>{TASK_STATUS[r.status] ?? r.status}</span>
              <span className="tap-task-main">
                <span className="tap-task-name">#{r.id} · {r.name}</span>
                <span className="tap-task-sub">v{r.version} · {fmt(r.created_at)}{dur(r)}</span>
                {r.error && <span className="tap-task-error">{r.error}</span>}
              </span>
              <span className={'tap-task-state ' + key}>
                {r.status === 'running' && <Icon name="spinner" spin />}
                {r.status === 'done' && <Icon name="check" />}
                {r.status === 'failed' && <Icon name="alert" />}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** 后端消息 → 渲染消息。assistant 统一走 Markdown 渲染；
 * meta.steps = 流式规划回复的思考步骤（随消息落库，历史里可回放）；
 * meta.suggestions = 模型返回的后续问题建议（SUGGEST 协议），作为快捷问题展示。 */
function fromServer(m: ChatConversationMsg): ChatMsg[] {
  if (m.role === 'user') {
    // node_request is intentionally hidden.  node_ref is a small, explicit
    // presentation tag supplied by the canvas entry point and is safe to show.
    const ref = m.meta?.node_ref as { title?: unknown; type?: unknown; mode?: unknown } | undefined
    const tags = ref && typeof ref === 'object'
      ? ['画布', `${String(ref.type ?? '节点')} · ${String(ref.title ?? '当前节点')}`,
        ...(ref.mode && ref.mode !== 'on_demand' ? [String(ref.mode) === 'rewrite_only' ? '仅改写' : '改写并生成'] : [])]
      : undefined
    return [{ kind: 'user', text: m.content, meta: tags }]
  }
  const out: ChatMsg[] = []
  const steps = Array.isArray(m.meta?.steps) ? m.meta.steps as { title?: string; detail?: string; state?: string }[] : []
  if (steps.length) {
    out.push({
      kind: 'think',
      steps: steps.map(s => ({
        label: String(s.title ?? ''),
        detail: s.detail ? String(s.detail) : undefined,
        state: s.state === 'err' ? 'err' : 'done',
      })),
    })
  }
  // Keep the assistant's visible response even when it also contains canvas
  // actions.  Previously short action acknowledgements were dropped here,
  // leaving users with only the thought timeline and no readable answer (or
  // the generated prompt/plan text).  Hidden node_request/context metadata is
  // still filtered above and never reaches this renderer.
  if (m.content?.trim() || !steps.length) {
    const mediaUrl = typeof m.meta?.media_url === 'string' ? m.meta.media_url : ''
    const nodeType = String(m.meta?.node_type ?? '')
    const mediaKind = nodeType === 'video' || /\.(?:mp4|webm|mov)(?:[?#]|$)/i.test(mediaUrl)
      ? 'video' as const : 'image' as const
    const md = mediaUrl
      ? m.content.replace(/\s*!\[[^\]]*\]\([^)]*\)\s*$/i, '').trim()
      : m.content
    out.push({
      kind: 'assistant',
      md: m.meta?.kind === 'node_output' && m.meta?.node_title
        ? `**${String(m.meta.node_title)} · 输出**\n\n${md}`
        : md,
      ...(mediaUrl ? { media: { url: mediaUrl, kind: mediaKind, alt: String(m.meta?.node_title ?? nodeType) } } : {}),
      suggestions: Array.isArray(m.meta?.suggestions) ? m.meta.suggestions as string[] : undefined,
    })
  }
  return out
}

/** 公共对话面板（全站唯一实例，宿主 = ChatFab 右下角悬浮面板）：
 * - 两个 tab：「对话」= 消息流（Markdown、运行日志折叠组、状态行 + 建议 chips + 输入条）；
 *   「任务队列」= 画布运行记录（画布 scope 下）+ 项目任务队列（SSE 依赖树）。
 * - scope 跟随当前页面（lib/uiContext）：画布页由画布注册 contributor 决定，
 *   项目工作台 = project:{id}，其它页面 = global 兜底会话；切页面自动换会话。
 * - 上下文注入：页面对话自动携带「用户当前在哪/开了什么弹窗」；画布 contributor
 *   额外提供节点清单等深度上下文。
 * - 动作分发：AI 回复解析出的动作（如 focus_node）经 dispatchChatAction 交给
 *   当前页面的 contributor 消费（驱动画布等）。
 * - 后端不可达时回退本地演示模式（fixture + 回声），不报错打扰。 */
/** autoSend：ChatFab 常驻层受理的下发指令（画布生成条等入口投递）；
 * 会话就绪后自动作为用户消息发出，发完回调 onAutoSent 清除。 */
export function ChatDock({ onClose, autoSend, onAutoSent }: {
  onClose?: () => void
  /** 下发的指令文本（带 id 防重发）；onSent = 消息真正发进会话时回调（入口按钮取消 loading） */
  autoSend?: { id: number; text: string; scope?: ChatScope; meta?: Record<string, unknown>; onSent?: () => void } | null
  /** 自动发送完成后通知父层清除，避免重开面板重发 */
  onAutoSent?: () => void
}) {
  const ui = useUi()
  const activePid = useActivePid()
  // 深度上下文贡献者：后注册的优先（最贴近当前视图的页面）。
  const contributor = ui.contributors.length ? ui.contributors[ui.contributors.length - 1] : undefined
  // scope：贡献者优先（画布），否则按页面派生（项目工作台 → project，其余 → global）。
  // useMemo 稳定引用——会话加载 effect 依赖它，字面量重建会反复打后端。
  const scope = useMemo<ChatScope>(
    () => autoSend?.scope ?? contributor?.scope
      ?? (activePid ? { kind: 'project', id: activePid } : { kind: 'global' }),
    [autoSend?.scope, contributor?.scope, activePid])

  const [tab, setTab] = useState<'chat' | 'tasks'>('chat')
  /** 本地瞬态消息：乐观上屏的用户消息、错误状态、（demo 模式的）回声 */
  const [transient, setTransient] = useState<ChatMsg[]>([])
  /** live 会话：后端可达时存在，消息刷新不丢 */
  const [live, setLive] = useState<{ convId: number; msgs: ChatMsg[] } | null>(null)
  const [busy, setBusy] = useState(false)
  const handledResultRef = useRef(new Set<number>())
  /** 流式回复进行中（transient 里有 streaming 助手消息）：进度已在思考时间线里，不再叠加全局 spinner */
  const streaming = transient.some(m => m.kind === 'assistant' && m.streaming)
  const bodyRef = useRef<HTMLDivElement>(null)
  const msgs: ChatMsg[] = [
    ...(live ? live.msgs : []), ...transient,
    // Canvas execution logs used to be injected as a second "executed task"
    // card below every answer.  Node stage badges and the thought timeline
    // are the live progress surface now; keep other transient injections but
    // omit that redundant run card from the conversation tab.
    ...ui.inject.msgs.filter(m => m.kind !== 'run'),
  ]

  // ── 输入卡：多行 contenteditable + 参考附件 + @ 引用（对齐画布生成条的能力）──
  // 胶囊编辑器：@引用 只在渲染层是胶囊，序列化仍是纯文本 @标题，后端协议不变
  const ediRef = useRef<HTMLDivElement>(null)
  const [entry, setEntry] = useState('')
  /** 参考附件（本地预览）：发送时清单拼进消息；图片本体待后端附件接口后直传 */
  const [chatRefs, setRefs] = useState<{ id: string; url: string; name: string }[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  /** 对话模型名：来自能力档案（text 档），拉不到用默认文案 */
  const [modelName, setModelName] = useState('默认模型')
  useEffect(() => {
    api.getModelCapabilities('text').then(d => { if (d.active?.name) setModelName(d.active.name) }).catch(() => { /* 保持默认 */ })
  }, [])

  const serializeEdi = (el: HTMLElement) => {
    let out = ''
    el.childNodes.forEach(n => {
      if (n.nodeType === Node.TEXT_NODE) out += n.textContent ?? ''
      else if (n instanceof HTMLElement && n.dataset.mention) out += n.dataset.label || ''
      else if (n instanceof HTMLElement) {
        if (n.tagName === 'BR') out += '\n'
        else out += (n.tagName === 'DIV' || n.tagName === 'P' ? '\n' : '') + (n.textContent ?? '')
      }
    })
    return out
  }
  const makeChip = (label: string) => {
    const chip = document.createElement('span')
    chip.className = 'tap-chip'
    chip.contentEditable = 'false'
    chip.dataset.mention = '1'
    chip.dataset.label = label
    const b = document.createElement('b')
    b.textContent = label
    chip.appendChild(b)
    return chip
  }
  /** @ 候选：贡献者提供（画布=节点清单）；无贡献者时不弹 */
  const mentionCandidates = useMemo(
    () => (contributor?.mentions?.() ?? []), [contributor])
  const [mention, setMention] = useState<{ q: string } | null>(null)
  const mentionList = mention
    ? mentionCandidates
      .filter(c => !mention.q || c.title.toLowerCase().includes(mention.q.toLowerCase()))
      .slice(0, 8)
    : []
  // 光标前是否正打着 @xxx：是则弹候选菜单（tapflow 生成条同款交互）
  const checkMention = () => {
    const el = ediRef.current
    const sel = window.getSelection()
    if (!el || !sel || !sel.isCollapsed || !sel.anchorNode || !el.contains(sel.anchorNode)
      || sel.anchorNode.nodeType !== Node.TEXT_NODE) { setMention(null); return }
    const before = (sel.anchorNode.textContent || '').slice(0, sel.anchorOffset)
    const m = /(?:^|\s)@([^\s@]*)$/.exec(before)
    setMention(m ? { q: m[1] } : null)
  }
  const pickMention = (c: { id: string; title: string }) => {
    const el = ediRef.current
    if (!el) return
    const sel = window.getSelection()
    const inEdi = sel && sel.anchorNode && el.contains(sel.anchorNode)
      && sel.anchorNode.nodeType === Node.TEXT_NODE
    if (inEdi && sel) {
      // 输入 @ 后从菜单选中：吃掉 @query 文本，原位插胶囊（tapflow 同款）。
      // off 必须在动 DOM 前固化：插入不可编辑胶囊后浏览器会重置选区，
      // 再读 anchorOffset 会拿到 0，尾文本 slice(0) 变全文 → 文本双写
      const node = sel.anchorNode
      const text = node.textContent || ''
      const off = sel.anchorOffset
      const before = text.slice(0, off)
      const m = /(?:^|\s)@([^\s@]*)$/.exec(before)
      if (m) {
        node.textContent = before.slice(0, before.length - m[0].length)
        const chip = makeChip(`@${c.title}`)
        const tail = document.createTextNode(' ' + text.slice(off))
        node.parentNode?.insertBefore(chip, node.nextSibling)
        node.parentNode?.insertBefore(tail, chip.nextSibling)
        const r = document.createRange()
        r.setStart(tail, 1); r.collapse(true)
        sel.removeAllRanges(); sel.addRange(r)
        setEntry(serializeEdi(el))
        setMention(null)
        return
      }
    }
    // 没有有效光标（如点「@」按钮刚唤起）：追加到末尾
    el.appendChild(makeChip(`@${c.title}`))
    el.appendChild(document.createTextNode(' '))
    setEntry(serializeEdi(el))
    setMention(null)
    el.focus()
  }
  const addRefFiles = (files: FileList | File[] | null) => {
    if (!files?.length) return
    const imgs = [...files].filter(f => f.type.startsWith('image/')).slice(0, 9)
    setRefs(rs => [...rs, ...imgs.map(f => ({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      url: URL.createObjectURL(f), name: f.name || '图片',
    }))].slice(0, 9))
  }
  const setEdiText = (t: string) => {
    const el = ediRef.current
    if (!el) return
    el.textContent = t
    setEntry(t)
    el.focus()
  }

  // scope 就绪时确保会话存在并加载（fresh=false = 有活跃会话拿活跃，没有则建；
  // 后端不可达 → 保持演示模式兜底）
  useEffect(() => {
    const key = scope ? chatScopeKey(scope) : null
    if (!scope || !key) return
    let dead = false
    api.chatNew(scope.kind, key, false, scope.legacyKeys)
      .then(c => { if (!dead && c) setLive({ convId: c.id, msgs: c.messages.flatMap(m => fromServer(m)) }) })
      .catch(() => { /* 演示模式兜底，不报错打扰 */ })
    return () => { dead = true }
  }, [scope])

  // Canvas runs finish after the chat action stream has already returned.  Turn
  // the actual artifact into an assistant message so the next turn can refer to
  // it naturally and the server-side history contains the output, not just a
  // generic "submitted" acknowledgement.
  useEffect(() => {
    const result = ui.chatResult
    if (!result || !live || chatScopeKey(result.scope) !== chatScopeKey(scope)
      || handledResultRef.current.has(result.id)) return
    handledResultRef.current.add(result.id)
    const meta = {
      kind: 'node_output', node_key: result.nodeKey,
      node_title: result.nodeTitle, node_type: result.nodeType,
      ...(result.mediaUrl ? { media_url: result.mediaUrl } : {}),
    }
    void api.chatAppend(live.convId, 'assistant', result.content, meta)
      .then(saved => setLive(current => current
        ? { ...current, msgs: [...current.msgs, ...fromServer(saved)] } : current))
      .finally(() => clearChatResult(result.id))
  }, [ui.chatResult, live, scope])

  // 新消息/切 tab/等待回复/流式增量 自动滚到底：对话面板的价值就在「永远看得见最新一条」
  useEffect(() => {
    if (tab !== 'chat') return
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight })
  }, [msgs.length, busy, tab, transient])

  const pushStatus = (text: string, tone: 'err' | 'info' = 'err') =>
    setTransient(s => [...s, { kind: 'status', text, tone }])

  /** 发给 AI 的上下文 = 页面感知（在哪/开了什么弹窗）+ 贡献者的深度上下文（画布等）。
   * 每次提问实时组装，页面切换后下一问自动带上新位置。 */
  const buildContext = (): string | undefined => {
    const parts: string[] = []
    if (ui.page) parts.push(`用户当前所在页面：${ui.page}${ui.detail ? `（${ui.detail}）` : ''}`)
    if (ui.modalStack.length) parts.push(`打开中的弹窗：${ui.modalStack.join(' → ')}`)
    const deep = contributor?.contextBuilder?.()
    if (deep) parts.push(deep)
    return parts.length ? parts.join('\n') : undefined
  }

  /** 画布动作 → 思考时间线上的一步（动作可见化：改了什么/跑了什么一目了然） */
  const actionLabel = (a: Record<string, unknown>): string => {
    const key = String(a.node_key ?? a.from ?? '')
    switch (String(a.type ?? '')) {
      case 'focus_node': return `定位节点 ${key}`
      case 'update_node_prompt': return `改写提示词：${key}`
      case 'update_node_content': return `更新成稿：${key}`
      case 'add_node': return `添加${String(a.node_type ?? '')}节点${a.title ? `「${String(a.title)}」` : ''}`
      case 'connect': return `连线 ${String(a.from ?? '')} → ${String(a.to ?? '')}`
      case 'remove_node': return `删除节点 ${key}`
      case 'run_node': return `重新生成 ${key}`
      case 'run_canvas': return '运行整张画布'
      default: return `执行动作 ${String(a.type ?? '')}`
    }
  }

  const streamGotRef = useRef(false)

  /** 流式规划回复：思考时间线 + 逐字正文 + 画布动作即时分发。
   * transient 占位（think + streaming assistant），done 后换成落库消息（含步骤回放）。
   * 流式端点不可用时回退旧 /reply（一次性返回，仍走同一渲染链路）。 */
  const streamReply = async (convId: number): Promise<void> => {
    setTransient(s => [...s, { kind: 'think', steps: [] }, { kind: 'assistant', md: '', streaming: true }])
    const patchThink = (fn: (steps: Extract<ChatMsg, { kind: 'think' }>['steps']) => Extract<ChatMsg, { kind: 'think' }>['steps']) =>
      setTransient(list => {
        const out = [...list]
        for (let i = out.length - 1; i >= 0; i--) {
          const m = out[i]
          if (m.kind === 'think') { out[i] = { ...m, steps: fn(m.steps) }; break }
        }
        return out
      })
    const patchAssistant = (fn: (m: Extract<ChatMsg, { kind: 'assistant' }>) => Extract<ChatMsg, { kind: 'assistant' }>) =>
      setTransient(list => {
        const out = [...list]
        for (let i = out.length - 1; i >= 0; i--) {
          const m = out[i]
          if (m.kind === 'assistant' && m.streaming) { out[i] = fn(m); break }
        }
        return out
      })
    const addStep = (label: string, detail?: string, state: 'run' | 'done' | 'err' = 'done') =>
      patchThink(ss => {
        const index = ss.findIndex(step => step.label === label)
        if (index < 0) return [...ss, { label, detail, state }]
        const next = [...ss]
        next[index] = { ...next[index], detail: detail ?? next[index].detail, state }
        return next
      })
    let sawAnswer = false
    streamGotRef.current = false
    const done = await api.chatReplyStream(convId, buildContext(), async ev => {
      streamGotRef.current = true
      if (ev.event === 'step') {
        addStep(ev.title ?? '', ev.detail,
          ev.state === 'err' ? 'err' : ev.state === 'run' || ev.state === 'running' ? 'run' : 'done')
      } else if (ev.event === 'phase' && ev.phase === 'answer') {
        patchThink(ss => ss.map(step => step.state === 'run' ? { ...step, state: 'done' } : step))
        addStep('组织回复，执行画布动作', undefined, 'run')
      } else if (ev.event === 'delta' && ev.text) {
        sawAnswer = true
        patchAssistant(m => ({ ...m, md: m.md + ev.text }))
      } else if (ev.event === 'action' && ev.action) {
        addStep(actionLabel(ev.action))
        await dispatchChatAction(ev.action)
      } else if (ev.event === 'suggestions' && ev.items?.length) {
        patchAssistant(m => ({ ...m, suggestions: ev.items }))
      } else if (ev.event === 'done' && ev.message) {
        patchThink(ss => ss.map(step => step.state === 'run' ? { ...step, state: 'done' } : step))
        await dispatchChatAction({ type: 'chat_done' })
        setTransient(() => [])
        setLive(L => L ? { ...L, msgs: [...L.msgs, ...fromServer(ev.message!)] } : L)
      } else if (ev.event === 'error') {
        if (ev.partial_message?.content) {
          patchAssistant(m => ({ ...m, md: ev.partial_message!.content, streaming: false }))
        }
        throw new Error(String(ev.title ?? '模型调用失败'))
      }
    })
    // 后端正常关流但没发 done（极端情况）：用已收到的内容收尾，不丢字
    if (!done || done.event !== 'done') {
      if (sawAnswer) {
        setTransient(list => {
          const keep = list.filter(m => m.kind === 'assistant' && m.streaming && m.md.trim())
          return keep.map(m => m.kind === 'assistant' ? { ...m, streaming: false } : m)
        })
      } else {
        setTransient(() => [])
      }
    }
  }

  const send = async (override?: string, sendMeta?: Record<string, unknown>) => {
    const el = ediRef.current
    const raw = override ?? (el ? serializeEdi(el) : entry).trim()
    if ((!raw && !chatRefs.length) || busy) return
    // 参考附件目前先以清单形式随消息告知 AI（图片本体待后端附件接口后直传）
    const text = chatRefs.length
      ? `${raw}${raw ? '\n' : ''}（随消息附 ${chatRefs.length} 张参考图：${chatRefs.map(r => r.name).join('、')}）`
      : raw
    setEdiText('')
    setEntry('')
    setRefs([])
    setMention(null)
    if (!live) {
      // 演示模式（后端不可达）：本地回声
      setTransient(s => [...s, { kind: 'user', text }])
      setTimeout(() => setTransient(s => [...s, {
        kind: 'assistant',
        md: scope.kind === 'tapflow' && scope.slug
          ? `已收到，会结合画布《${scope.name ?? scope.slug}》的节点、参数与最近运行继续讨论。`
          : '已收到。',
      }]), 500)
      return
    }
    // live 会话：乐观上屏 → 落库 → 流式规划回复（思考步骤→逐字正文→画布动作）→ 落屏
    const convId = live.convId
    setTransient(s => [...s, { kind: 'user', text, pending: true }])
    setBusy(true)
    try {
      const saved = await api.chatAppend(convId, 'user', text, sendMeta)
      setTransient(s => s.filter(m => !(m.kind === 'user' && m.pending)))
      setLive(L => L ? { ...L, msgs: [...L.msgs, ...fromServer(saved)] } : L)
      try {
        await streamReply(convId)
      } catch (streamErr) {
        // 流式端点不可用（老后端/代理不支持 SSE，一个事件都没收到）：回退一次性回复。
        // 已经流出一部分才失败的：保留已收到的正文，直接报错不再重发（避免重复扣费）
        if (!streamGotRef.current) {
          const rep = await api.chatReply(convId, buildContext())
          setTransient(s => s.filter(m => !(m.kind === 'think' || (m.kind === 'assistant' && m.streaming))))
          setLive(L => L ? { ...L, msgs: [...L.msgs, ...fromServer(rep)] } : L)
          const replyActions = rep.actions?.length ? rep.actions : (rep.action ? [rep.action] : [])
          for (const action of replyActions) await dispatchChatAction(action)
        } else {
          throw streamErr
        }
      }
    } catch (e) {
      // 乐观消息转正（后端没收到也留在本地看得到），错误进状态行；清掉空的流式占位
      setTransient(s => s
        .filter(m => !(m.kind === 'think' || (m.kind === 'assistant' && m.streaming && !m.md.trim())))
        .map(m => m.kind === 'assistant' && m.streaming ? { ...m, streaming: false } : m))
      setTransient(s => s.map(m => m.kind === 'user' && m.pending ? { ...m, pending: false } : m))
      void dispatchChatAction({ type: 'chat_error', error: e instanceof Error ? e.message : String(e) })
      pushStatus(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  // ── 通用下发通道自动发送（2026-09-18）：ChatFab 常驻层受理的下发指令经 autoSend 传入，
  // 会话就绪后作为用户消息自动发出——思考过程、逐字输出、画布动作、运行日志
  // 全部在对话区可见。busy 时等本轮回复结束的 effect 重跑再发。
  const autoSendText = autoSend?.text
  const autoSentRef = useRef(0)
  useEffect(() => {
    if (!autoSendText || busy) return
    if (!live) {
      // 会话还没就绪：先给一条可见状态，避免面板开着但一片空白让人以为没反应
      pushStatus('指令已送达，正在接入会话…', 'info')
      return
    }
    if (autoSentRef.current === (autoSend?.id ?? 0)) return
    autoSentRef.current = autoSend?.id ?? 0
    void send(autoSendText, autoSend?.meta)
    // 消息已递交会话（气泡上屏、AI 接手）：入口按钮的 loading 到此为止，
    // 后续思考/节点执行进度都由对话区自己展示
    autoSend?.onSent?.()
    onAutoSent?.()
  // The request id is the stable event key; including the render-scoped send
  // function would replay the queue on every transient message update.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSend?.id, autoSendText, live?.convId, busy])

  const newConversation = async () => {
    if (busy) return
    setBusy(true)
    try {
      const c = await api.chatNew(scope.kind, chatScopeKey(scope) ?? '', true)
      setLive({ convId: c.id, msgs: [] })
      setTransient([])
      setMenuOpen(false)
    } catch (e) {
      pushStatus(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  // ── 会话弹层（标题前三条杠）：新对话 + 会话列表（活跃在前，点一条进入）──
  const [menuOpen, setMenuOpen] = useState(false)
  const [convList, setConvList] = useState<ChatConversationItem[] | null>(null)
  const openMenu = () => {
    setMenuOpen(v => {
      if (!v) api.chatList(scope.kind, chatScopeKey(scope) ?? '')
        .then(setConvList).catch(() => setConvList([]))
      return !v
    })
  }
  // 弹层开着时点外部关闭（radix 焦点陷阱不影响纯 div）
  useEffect(() => {
    if (!menuOpen) return
    const close = (e: PointerEvent) => {
      const t = e.target as Element
      if (!t.closest?.('.tap-chat-menu') && !t.closest?.('.tap-menu-btn')) setMenuOpen(false)
    }
    document.addEventListener('pointerdown', close, true)
    return () => document.removeEventListener('pointerdown', close)
  }, [menuOpen])
  const switchConversation = async (cid: number) => {
    if (busy || !live || cid === live.convId) { setMenuOpen(false); return }
    setBusy(true)
    try {
      const c = await api.chatSwitch(cid, scope.kind, chatScopeKey(scope) ?? '')
      setLive({ convId: c.id, msgs: c.messages.flatMap(m => fromServer(m)) })
      setTransient([])
      setMenuOpen(false)
    } catch (e) {
      pushStatus(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="tap-chat">
      <header className="tap-chat-head">
        {/* 三条杠：会话列表弹层（新对话 + 历史），每 scope 一组互不串台 */}
        <button type="button" className={'tap-tool tap-menu-btn' + (menuOpen ? ' on' : '')}
          title="会话列表" onClick={openMenu}>
          <Icon name="menu" />
        </button>
        <span className="tap-chat-title">
          {scope.kind === 'tapflow' ? (scope.name ?? '画布对话')
            : scope.kind === 'project' ? '项目对话' : 'AI 对话'}
          <span className="caret"> ▾</span>
        </span>
        {scope.kind === 'tapflow' && (
          <span className="tap-chat-workspace" title="当前对话绑定的画布工作空间">画布工作空间</span>
        )}
        <span className="tap-seg-mini">
          <button type="button" className={tab === 'chat' ? 'on' : ''}
            onClick={() => setTab('chat')}>对话</button>
          <button type="button" className={tab === 'tasks' ? 'on' : ''}
            onClick={() => setTab('tasks')}>任务队列</button>
        </span>
        {onClose && (
          <button type="button" className="tap-tool" title="收起" onClick={onClose}>
            <Icon name="collapse" />
          </button>
        )}
        {menuOpen && (
          <div className="tap-chat-menu" role="menu" aria-label="会话列表">
            <button type="button" className="tap-menu-new" role="menuitem"
              onClick={newConversation}>
              <Icon name="plus" /> 新对话
            </button>
            <div className="tap-menu-list">
              {(convList ?? []).map(c => (
                <button type="button" key={c.id}
                  className={'tap-menu-item' + (live && c.id === live.convId ? ' on' : '')}
                  role="menuitem" onClick={() => switchConversation(c.id)}>
                  <em>{c.preview}</em>
                  <span className="tap-menu-meta">
                    {c.updated_at ? new Date(c.updated_at).toLocaleDateString() : ''}
                    {!c.archived && <i>当前</i>}
                  </span>
                </button>
              ))}
              {convList?.length === 0 && <div className="tap-menu-empty">暂无历史会话</div>}
            </div>
          </div>
        )}
      </header>

      {tab === 'chat' ? (
        <>
          <div className="tap-chat-body" ref={bodyRef}>
            {msgs.length === 0 && (
              <div className="tap-chat-empty">
                <Icon name="chat" />
                <p>还没有对话</p>
                <em>输入问题开始，AI 会结合当前页面与画布上下文回答</em>
              </div>
            )}
            {msgs.map((m, i) => {
              if (m.kind === 'user') {
                return (
                  <div key={i} className="tap-msg-user" style={m.pending ? { opacity: 0.6 } : undefined}>
                    <div className="bubble">{m.text}</div>
                    {m.meta?.length ? <div className="meta">{m.meta.map(x => <span key={x}>{x}</span>)}</div> : null}
                  </div>
                )
              }
              if (m.kind === 'status') {
                return (
                  <div key={i} className={'tap-msg-status' + (m.tone ? ` ${m.tone}` : '')}>
                    <div><Icon name={m.tone === 'err' ? 'alert' : m.tone === 'ok' ? 'check' : 'clipboard'} /> {m.text}</div>
                    {m.sub && <div className="sub">{m.sub}</div>}
                  </div>
                )
              }
              if (m.kind === 'op') {
                return (
                  <button key={i} type="button" className="tap-msg-op"
                    onClick={m.onClick}><Icon name="clipboard" /> {m.text}</button>
                )
              }
              if (m.kind === 'run') return <RunGroup key={i} msg={m} />
              if (m.kind === 'think') return <ThinkCard key={i} msg={m} />
              return (
                <div key={i} className="tap-msg-ai">
                  <Markdown text={m.md} />
                  {m.media?.kind === 'video' && (
                    <video className="tap-chat-media" src={m.media.url} controls preload="metadata" />
                  )}
                  {m.media?.kind === 'image' && (
                    <img className="tap-chat-media" src={m.media.url} alt={m.media.alt ?? ''} />
                  )}
                  {m.streaming && <span className="tap-chat-caret" aria-hidden />}
                </div>
              )
            })}
            {busy && live && !streaming && (
              <div className="tap-msg-status">
                <div><Icon name="spinner" spin /> 思考中…</div>
              </div>
            )}
            {(() => {
              // 快捷问题：取最新一条 AI 回复的 suggestions（SUGGEST 协议，随会话持久化）；
              // 没有就不显示——不再放与页面无关的写死问题
              const lastAi = [...msgs].reverse().find(m => m.kind === 'assistant' && m.suggestions?.length)
              const chips = lastAi?.kind === 'assistant' ? (lastAi.suggestions ?? []) : []
              if (!chips.length) return null
              return (
                <div className="tap-chat-chips">
                  {chips.map(c => (
                    <button key={c} type="button" className="tap-chip"
                      onClick={() => send(c)}><Icon name="sparkles" /> {c}</button>
                  ))}
                </div>
              )
            })()}
          </div>

          {/* 输入卡：参考附件条 + 多行编辑器（@ 引用）+ 工具行，对齐画布生成条的卡片形态 */}
          <footer className="tap-chat-input">
            {chatRefs.length > 0 && (
              <div className="tap-chat-refs">
                {chatRefs.map(r => (
                  <span key={r.id} className="tap-ref-node img" title={r.name}>
                    <img src={r.url} alt={r.name} draggable={false} />
                    <button type="button" className="tap-ref-del" title={`移除参考：${r.name}`}
                      onClick={() => setRefs(rs => rs.filter(x => x.id !== r.id))}>×</button>
                  </span>
                ))}
              </div>
            )}
            <div className="tap-chat-card">
              <span className="tap-mention-host">
                {mention && mentionList.length > 0 && (
                  <span className="tap-mention-menu" role="listbox" aria-label="可引用的实体">
                    {mentionList.map(c => (
                      <button type="button" key={c.id} className="tap-mention-item" role="option"
                        onMouseDown={e => { e.preventDefault(); pickMention(c) }}>
                        <Icon name="node" />
                        <em>{c.title}</em>
                      </button>
                    ))}
                    <span className="tap-mention-hint">选中即以 @名称 插入消息</span>
                  </span>
                )}
                <div
                  ref={ediRef} className="tap-chat-edi" contentEditable suppressContentEditableWarning
                  role="textbox" aria-multiline="true" aria-label="消息输入"
                  data-ph={INPUT_HINT}
                  // 页面开着 Modal 弹窗时，radix 焦点陷阱会拦掉外部点击的默认聚焦
                  // （pointerdown 被 preventDefault），这里在 click 阶段手动抢回焦点
                  onClick={e => e.currentTarget.focus()}
                  onInput={() => { const el = ediRef.current; if (el) setEntry(serializeEdi(el)); checkMention() }}
                  onKeyUp={checkMention}
                  onKeyDown={e => {
                    if (e.key === 'Escape') { setMention(null); return }
                    // Enter 发送（输入法组词中不触发）；@ 菜单开着时先选首个候选
                    if (e.key === 'Enter' && !e.nativeEvent.isComposing && !e.shiftKey) {
                      e.preventDefault()
                      if (mention && mentionList.length > 0) pickMention(mentionList[0])
                      else send()
                    }
                  }}
                  onBlur={() => { setTimeout(() => setMention(null), 120) }}
                  onPaste={e => {
                    // 粘贴图片 → 进参考附件区；文本一律当纯文本插入
                    const imgs = [...(e.clipboardData?.files ?? [])].filter(f => f.type.startsWith('image/'))
                    if (imgs.length) {
                      e.preventDefault()
                      addRefFiles(imgs)
                      return
                    }
                    e.preventDefault()
                    const t = e.clipboardData.getData('text/plain')
                    if (t) document.execCommand('insertText', false, t)
                  }} />
              </span>
              <div className="tap-chat-foot">
                <span className="tap-foot-left">
                  <button type="button" className="tap-foot-btn" title="添加参考图"
                    onClick={() => fileRef.current?.click()}><Icon name="plus" /></button>
                  {mentionCandidates.length > 0 && (
                    <button type="button" className="tap-foot-btn tap-foot-at" title="@ 引用（画布节点）"
                      onMouseDown={e => { e.preventDefault(); setMention(v => v ? null : { q: '' }); ediRef.current?.focus() }}>
                      <b>@</b>
                    </button>
                  )}
                  <span className="tap-chat-model" title={`对话模型：${modelName}`}>
                    <Icon name="blocks" /> <span>{modelName}</span>
                  </span>
                </span>
                <span className="tap-foot-right">
                  <button type="button" className="tap-foot-btn" title="语音（即将支持）"><Icon name="mic" /></button>
                  {/* 发送件用 div 不用 button：base.css 全局 button 规则（渐变底/居中字/线框）
                      会破坏圆形外观，画布生成条同款改法。busy 时压暗并忽略点击 */}
                  <div role="button" tabIndex={busy ? -1 : 0} aria-disabled={busy}
                    title="发送 (Enter)"
                    className={'tap-send-btn' + (busy ? ' busy' : '')}
                    onClick={() => { if (!busy) send() }}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (!busy) send() }
                    }}><Icon name={busy ? 'spinner' : 'arrowup'} spin={busy} /></div>
                </span>
              </div>
            </div>
            <input ref={fileRef} type="file" accept="image/*" multiple hidden
              onChange={e => { addRefFiles(e.target.files); e.target.value = '' }} />
          </footer>
        </>
      ) : (
        <div className="tap-chat-body tap-chat-tasks">
          {scope.kind === 'tapflow' && scope.slug && <CanvasRuns slug={scope.slug} />}
          <TaskQueuePanel />
        </div>
      )}
    </aside>
  )
}
