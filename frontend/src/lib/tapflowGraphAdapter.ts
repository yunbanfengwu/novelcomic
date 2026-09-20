// 后端工作流 graph → tapflow 画布投影(单一实现:执行模型在后端解释器,画布只是展示层)。
// 后端节点 config.ui 是画布提示(tap 类型/标题/尺寸/运行态隐藏),解释器不读它。
import type { WorkflowDetail, WorkflowNode } from '../api'
import { applyLayout } from './tapflowLayout'
import {
  defaultGen, isGenType, TAP_CTX_ORDER, textOutputs, toolInputParams, toolOutputParams,
} from './tapflowData'
import type {
  TapCanvasData, TapCtxKey, TapCtxRef, TapNode, TapParam, TapQcConf, TapVarType,
} from './tapflowData'

interface UiHint {
  tap?: string; title?: string; w?: number; h?: number
  loop_action?: string
  show_loop_body?: boolean
  loop_item_fields?: TapParam[]
  hide?: boolean; hide_in_run?: boolean
  /** 生成条上显示的模型名(不写死型号,免得与实际出图模型对不上) */
  model?: string
  /** 文本节点直出哪个输出字段(如 element.get 的 summary、prepare 的 prompt) */
  show?: string
  /** 本节点的产物喂给哪个生成节点的生成条(出图提示词属于图片,不另占一张卡) */
  feeds?: string
  /** 坐标由画布保存过(见 tapflowGraphWrite)。种子里手写的 position 靠不住——
   * 摆位是随手写的、也不随节点增删更新,所以只认画布自己盖的这个章。 */
  xy?: boolean
  /** 用户在画布上手工加的节点（不是模板带的）。生产态据此放行属性面板 */
  custom?: boolean
  manual_size?: boolean
  /** 提示词里 {{}} 占位符的展示名清单。占位符本体在 charter 里（引擎解析那一份），
   * 这里只存「这个 token 在编辑器里显示成什么」——纯展示，解释器不读。
   * 不存的话，重开画布后一串标签会退化成裸的 {{n1abc.text}}。 */
  refs?: TapCtxRef[]
  /** 画布作者态内容。这里只存用户输入/编辑的内容；模型产物从 workflow_node_runs 恢复。 */
  state?: {
    prompt?: string; prompt_edited?: boolean; ref_nodes?: string[]
    text?: string; text_edited?: boolean
  }
}

/** 节点 id → 它的文本直出字段(ui.show);运行/预检据此把真实产物写上卡 */
export type TapShowMap = Record<string, string>
/** 节点 id → 接收其产物的生成节点 id(ui.feeds) */
export type TapFeedMap = Record<string, string>

/** 入参 schema 键名 → 画布 ctx 参数的映射(项目/场景/角色按名字识别,其余按类型) */
const CTX_BY_KEY: Record<string, { ctx: TapCtxKey; label: string }> = {
  target_ref: { ctx: 'target_ref', label: '关联要素或内容' },
  project_id: { ctx: 'project_id', label: '项目' },
  scene_name: { ctx: 'scene_id', label: '场景' },
  character_name: { ctx: 'character_id', label: '角色' },
  chapter_id: { ctx: 'chapter_id', label: '章' },
  shot_id: { ctx: 'shot_id', label: '镜' },
}

interface SchemaField {
  type?: string; required?: boolean; label?: string; desc?: string
  /** 显式排序位（小者在前）。jsonb 不保作者写的键序，内容类参数之间只能靠它定顺序 */
  seq?: number
  ui?: { hide?: boolean }
  resource_kinds?: string[]
  allowed_values?: string[]
}

/** input_schema → 开始节点入参声明(值留空,运行面板填)。
 *
 * **不能按声明顺序**：input_schema 存在 jsonb 里，Postgres 会按「键长度 → 字典序」
 * 重排键——种子里写的 project_id/chapter_id/scene_name 取回来就成了
 * chapter_id/project_id/scene_name，表单上「章」排在「项目」前面，
 * 而没选项目根本列不出章的候选。
 *
 * 排序优先级：
 *   1. 字段自带 `seq`（显式，最高）——内容类参数之间只能靠它，jsonb 保不住书写顺序；
 *   2. 定位类(ctx)参数按 TAP_CTX_ORDER 的**级联关系**排（项目→卷→章→镜→要素）；
 *   3. 其余内容类参数排在定位参数之后，按 jsonb 归一化序（稳定但作者控制不了，
 *      在意顺序就写 seq）。 */
export function schemaToParams(schema: Record<string, unknown>): TapParam[] {
  const CONTENT = 1000       // 内容类参数的基准位：一律排在定位参数之后
  const rows = Object.entries(schema).filter(([, raw]) => !(raw as SchemaField)?.ui?.hide).map(([k, raw], i) => {
    const f = (raw ?? {}) as SchemaField
    const ctx = CTX_BY_KEY[k]
    const p: TapParam = ctx
      ? { k, label: f.label || f.desc || ctx.label, type: 'ctx', ctx: ctx.ctx, required: !!f.required, v: '', resourceKinds: f.resource_kinds, allowedValues: f.allowed_values }
      : {
          k, label: f.label || f.desc || k, required: !!f.required, v: '',
          type: (k.endsWith('_url') ? 'image' : f.type === 'int' ? 'int' : 'text') as TapVarType,
          allowedValues: f.allowed_values,
        }
    const at = ctx ? TAP_CTX_ORDER.indexOf(ctx.ctx) : -1
    const seq = typeof f.seq === 'number' ? f.seq : (at >= 0 ? at : CONTENT)
    return { p, seq, i }
  })
  return rows.sort((a, b) => a.seq - b.seq || a.i - b.i).map(x => x.p)
}

/** config.qc → 面板的质检段。**必须投影**：库里配着「场景设定图质检/阈值 80/重试 1」，
 * 面板却显示「未开」，比不显示更糟——照着面板判断的人会以为这条产线没做质检。 */
function qcOf(cfg: Record<string, unknown>): TapQcConf | undefined {
  const q = cfg.qc as Record<string, unknown> | undefined
  if (!q || typeof q !== 'object') return undefined
  return {
    on: !!q.on,
    skill: q.skill ? String(q.skill) : undefined,
    kb: (q.folder_ids as unknown[] | undefined)?.map(String),
    threshold: typeof q.threshold === 'number' ? q.threshold : undefined,
    stage: q.stage === 'image' ? 'image' : 'prompt',
    retry: typeof q.retry === 'number' ? q.retry : undefined,
  }
}

/** llm 节点的模型配置 → 面板的「LLM 生成」态。charter 是系统提示词,
 * skills/folder_ids/tools 直接就是 agent_runtime.run_batch 的入参,一一对应。 */
function llmBind(cfg: Record<string, unknown>, refs: TapCtxRef[] = []): TapNode['bind'] {
  return {
    mode: 'llm', refs,
    charter: cfg.charter ? String(cfg.charter) : '',
    skills: (cfg.skills as string[] | undefined) ?? [],
    kb: ((cfg.folder_ids as unknown[] | undefined) ?? []).map(String),
    tools: (cfg.tools as string[] | undefined) ?? [],
    onlyMissing: !cfg.force,
    qc: qcOf(cfg),
  }
}

/** 类型默认尺寸(与 tapflowData NODE_PRESET 对齐;ui.w/h 可覆盖) */
const SIZE: Record<string, { w: number; h: number }> = {
  start: { w: 560, h: 460 }, link: { w: 320, h: 96 }, gen: { w: 460, h: 273 },
  qc: { w: 132, h: 132 }, text: { w: 460, h: 280 },
  image: { w: 460, h: 273 }, video: { w: 460, h: 259 }, audio: { w: 460, h: 140 },
  tool: { w: 460, h: 273 }, loop: { w: 460, h: 273 }, mount: { w: 460, h: 273 },
  condition: { w: 380, h: 180 },
}

function argParamValue(value: unknown): Pick<TapParam, 'source' | 'ref' | 'v'> {
  if (typeof value === 'string') {
    const match = value.match(/^\{\{\s*([^{}]+)\s*\}\}$/)
    if (match) {
      const [head, ...tail] = match[1].trim().split('.')
      if (tail.length) return {
        source: 'ref', ref: { node: head === 'input' ? 'start' : head, k: tail.join('.') }, v: '',
      }
    }
    return { source: 'const', v: value }
  }
  if (value === undefined || value === null) return { source: 'const', v: '' }
  return { source: 'const', v: typeof value === 'object' ? JSON.stringify(value) : String(value) }
}

function toTapNode(n: WorkflowNode, schema: Record<string, unknown>,
                   contracts: WorkflowDetail['subflow_contracts'] = {},
                   toolContracts: WorkflowDetail['tool_contracts'] = {}): TapNode | null {
  const cfg = n.config ?? {}
  const ui = (cfg.ui ?? {}) as UiHint
  // end 节点（画布上曾经的 next 卡）不再投影：收尾/落库职责留在引擎侧，
  // 画布上产物归宿由挂载点声明。ui.hide 的节点同样不画（反向保存会原样保留两者）
  if (ui.hide || n.type === 'end') return null
  const tap = ui.tap ?? (n.type === 'start' ? 'start'
    : n.type === 'loop' ? 'loop' : n.type === 'value' ? 'upload'
    : n.type === 'mount' ? 'mount' : 'gen')
  const size = SIZE[tap] ?? SIZE.gen
  const manualSize = !!ui.manual_size
  const base: TapNode = {
    id: n.id, type: tap as TapNode['type'],
    title: ui.title ?? n.id,
    x: n.position?.x ?? 0, y: n.position?.y ?? 0,
    // 早期工具节点各自带了不同的 ui.w/h。未手动缩放的统一回标准尺寸；
    // 用户明确拖过右下角后仍以保存尺寸为准。
    w: tap === 'tool' && !manualSize ? size.w : ui.w ?? size.w,
    h: tap === 'tool' && !manualSize ? size.h : ui.h ?? size.h,
    hideInRun: ui.hide_in_run || undefined,
    custom: ui.custom || undefined,
    manualSize: manualSize || undefined,
  }
  if (tap === 'start') base.params = schemaToParams(schema)
  // value 节点 = 画布素材（参考图）：上传/外链的 url 存在 config.value，投影成卡面图片；
  // 运行期引擎把它当常量透传，下游生成节点按入边收它当参考图（workflow._upstream_media）
  if (tap === 'upload') base.src = String((cfg.value as { url?: string } | undefined)?.url ?? '')
  if (tap === 'loop') {
    const bodyIds = Array.isArray(cfg.body) ? cfg.body.map(String) : []
    const bodyNodes = bodyIds.map(id => (n as WorkflowNode & { __allNodes?: WorkflowNode[] }).__allNodes
      ?.find(candidate => candidate.id === id)).filter(Boolean) as WorkflowNode[]
    const subflow = bodyNodes.some(body => body.type === 'subflow')
    base.loop = {
      aggregate: true,
      source: typeof cfg.source === 'string' ? cfg.source : undefined,
      body: bodyIds,
      concurrency: typeof cfg.concurrency === 'number' ? cfg.concurrency : 1,
      itemFields: ui.loop_item_fields,
      isSubflow: subflow,
      actionTitle: ui.loop_action ?? (subflow ? '引用工作流' : undefined),
    }
    base.outputs = [
      { k: 'results', label: '循环结果', type: 'json', v: '' },
      { k: 'count', label: '循环次数', type: 'int', v: '' },
      { k: 'failed', label: '失败数量', type: 'int', v: '' },
    ]
  }
  if (tap === 'tool') {
    const name = String(cfg.name ?? '')
    const contract = toolContracts?.[name]
    const declared = toolInputParams(contract ?? { params: {} })
    const args = (cfg.args ?? {}) as Record<string, unknown>
    base.tool = {
      name, writes: !!contract?.writes, description: contract?.description,
    }
    base.params = declared.map(p => ({ ...p, ...argParamValue(args[p.k]) }))
    base.outputs = toolOutputParams(contract)
  }
  if (tap === 'condition') {
    const stored = Array.isArray(cfg.branches) ? cfg.branches as Array<Record<string, unknown>> : []
    base.condition = {
      branches: stored.length ? stored.map((branch, index) => ({
        id: String(branch.id ?? (index ? `else-if-${index}` : 'if-1')),
        kind: branch.kind === 'else' ? 'else' : branch.kind === 'else_if' ? 'else_if' : 'if',
        clauses: Array.isArray(branch.clauses) ? branch.clauses as never : undefined,
      })) : [
        { id: 'if-1', kind: 'if', clauses: [{ left: '{{input.source.prompt_text}}', operator: 'truthy' }] },
        { id: 'else', kind: 'else' },
      ],
    }
    base.outputs = [{ k: 'matched_branch', label: 'matched branch', type: 'text', v: '' }]
  }
  if (tap === 'link') {
    base.link = { action: String(cfg.name ?? ''), target: ui.title ?? '' }
  }
  // 挂载点（2026-09-17）：归宿声明存在 config.target/subject，运行回显在 outputs
  if (tap === 'mount' || n.type === 'mount') {
    const sub = cfg.subject as { kind?: string; id?: number } | undefined
    base.mount = {
      target: String(cfg.target ?? ''),
      ...(sub?.kind && sub?.id ? { subject: { kind: String(sub.kind), id: Number(sub.id) } } : {}),
      ...(cfg.variant ? { variant: String(cfg.variant) } : {}),
    }
  }
  // 出媒体的四种 tap 走同一套投影：库里它们都是 type=gen，差别只在 modality。
  // 早先这里只认 tap==='gen'，于是画布上拖出来的「图片」节点存下去、再打开就成了
  // 没有 bind、没有生成条的哑卡——配过的执行体、提示词全看不见
  if (isGenType(tap as TapNode['type'])) {
    // 执行体拆成两段投影:step 可选可存(候选来自 flow.STEPS),assemble 由后端定义只读。
    // 拼成一句 "a → b" 的展示串是没法回写的——面板要能改,就得分字段。
    base.bind = {
      onlyMissing: !cfg.force, qc: qcOf(cfg),
      step: cfg.step ? String(cfg.step) : undefined,
      outputSlot: typeof cfg.output_slot === 'object' && cfg.output_slot
        ? { role: String((cfg.output_slot as { role?: string }).role ?? ''),
            variant: (cfg.output_slot as { variant?: string }).variant } : undefined,
      assemble: (cfg.assemble as { name?: string } | undefined)?.name,
      modelProfileId: typeof cfg.model_profile_id === 'number' ? cfg.model_profile_id : undefined,
      // charter/技能/知识库 = anchor 段的来源(引擎 _anchor_from_config 读它),
      // 出图节点同样要投影出来,否则面板永远是空框——那就成了"配了没用"的死控件
      mode: 'llm', refs: ui.refs ?? [],
      charter: cfg.charter ? String(cfg.charter) : '',
      skills: (cfg.skills as string[] | undefined) ?? [],
      kb: ((cfg.folder_ids as unknown[] | undefined) ?? []).map(String),
    }
    // 生成条里预填**装配出来的最终提示词**(运行/预检时回填);用户改过就冻结,
    // 装配不再覆盖 —— 与 meta.*_edited 的手编冻结同一语义。
    // 模板原文不预填（提案 A，2026-09-18）：instruction 配的是 {{input.x}} 传参占位符时
    // 投影成空需求句——占位符是给引擎的合同，不是给用户的文案，投到输入框
    // 就会出现「生成条显示 {{input.instruction}}」这种字面量，还可能被原样发回去。
    const _instrRaw = String(cfg.instruction ?? '')
    // modality 上卡：视频生成节点（modality=video）产物是 mp4，运行回填与媒体卡
    // 渲染都靠它分流——不投影的话 mp4 会被当图片塞进 src 破图
    if (String(cfg.modality ?? '') === 'video') base.modality = 'video'
    base.gen = {
      refs: [], prompt: _instrRaw.includes('{{') ? '' : _instrRaw,
      // 视频节点的兜底模型名不能写死成出图模型——生成条能力档案拉不到时，
      // 视频卡至少显示“系统视频模型”而不是误导性的出图模型名
      model: String(ui.model ?? (cfg.model_profile_name as string | undefined)
        ?? (String(cfg.modality ?? '') === 'video' ? '系统视频模型' : '系统出图模型')),
      params: String(cfg.modality ?? 'image') === 'video' ? ['视频'] : [],
    }
    // 节点自带的静态参考图（画布作者在卡上上传的）：投影成缩略图条，可增删。
    // 引擎读 payload.reference_images，画布另存顶层 cfg.reference_images——两处取并集去重；
    // 占位符（{{input.x}}）与对象项不投影——它们不是画布能编辑的图，保存时也不被覆盖。注意
    // payload.reference_images 可能是**字符串**（单个 url 或 {{占位}}），不能当数组展开。
    const pickRefList = (v: unknown): unknown[] =>
      Array.isArray(v) ? v : typeof v === 'string' && !v.startsWith('{{') ? [v] : []
    const seededRefs: unknown[] = [
      ...pickRefList(cfg.reference_images),
      ...pickRefList((cfg.payload as Record<string, unknown> | undefined)?.reference_images),
    ]
    const staticRefs = [...new Set(seededRefs.filter((u): u is string =>
      typeof u === 'string' && !u.startsWith('{{')))]
    if (staticRefs.length) base.refImages = staticRefs
  }
  if (tap === 'qc') base.qc = { state: 'idle', rule: '产物存在性' }
  if (tap === 'text') {
    // 同一个 tap=text 有两种来源:action 是内置取数(不进模型),llm 是真让模型写一段。
    // 面板要如实分流——把 llm 节点画成「查询数据」,charter 就整段消失了。
    base.text = `(运行时取数:${ui.title ?? cfg.name}）`
    base.bind = n.type === 'llm'
      ? llmBind(cfg, ui.refs ?? [])
      : { mode: 'query', tools: [String(cfg.name ?? '')] }
    // 两种来源都产出正文（llm 返回 text，query 走 action 也按 text/summary 回显），
    // 所以输出合同一视同仁——否则重开画布后下游就引用不到这个节点了
    base.outputs = textOutputs()
  }
  // 用户输入属于画布定义，必须跟节点一起保存；否则节点外壳虽在，重开后生成条会变空。
  // 模型生成结果不塞 graph，统一从最近一次 workflow_node_runs 恢复，避免每次运行改定义。
  if (ui.state) {
    if (ui.state.prompt_edited || ui.state.ref_nodes) {
      base.gen = {
        ...defaultGen(base.type), ...base.gen,
        prompt: ui.state.prompt ?? '', edited: !!ui.state.prompt_edited,
        refNodes: ui.state.ref_nodes ?? [],
      }
    }
    if (ui.state.text_edited) {
      base.text = ui.state.text ?? ''
      base.textEdited = true
    }
  }
  // subflow 的引用信息跟 tap 类型无关：库里的 subflow 节点可能被画成 gen 卡（设定图）
  // 也可能画成 text 卡（场景介绍）。挂在 tap 分支里就会漏掉后者,反向保存时误判成「没选流程」。
  if (n.type === 'subflow') {
    base.bind = {
      ...base.bind,
      subflow: { slug: String(cfg.slug ?? ''), version: cfg.version as number | undefined },
    }
    const contract = contracts?.[String(cfg.slug ?? '')]
    base.smart = !!contract?.smart_call
    if (contract?.is_multi_child) {
      base.loop = { aggregate: true, imported: true, isSubflow: true,
        source: `{{${n.id}.descriptors}}`, actionTitle: '循环聚合子产物' }
    }
  }
  return base
}

/** ui.hide 的节点不画,但它的上下游要接起来(A→隐→B 变 A→B)。
 * 单独抽出来是因为**反向保存也要用**:画布上的连线是桥接后的形状,
 * 要判断"用户改没改连线",得先按同一套规则把库里的图桥接一遍再比。 */
export function bridgeEdges(raw: { from: string; to: string; mapping?: 'auto' | 'each' | 'collect'; branch?: string }[],
                            hidden: Set<string>): Array<{
                              id: string; from: string; to: string
                              mapping?: 'auto' | 'each' | 'collect'; branch?: string
                            }> {
  let edges: Array<{
    id: string; from: string; to: string; mapping?: 'auto' | 'each' | 'collect'; branch?: string
  }> = raw.map((e, i) => ({ id: `e${i}`, from: e.from, to: e.to, mapping: e.mapping, branch: e.branch }))
  for (const h of hidden) {
    const ins = edges.filter(e => e.to === h)
    const outs = edges.filter(e => e.from === h)
    edges = [
      ...edges.filter(e => e.from !== h && e.to !== h),
      ...ins.flatMap(a => outs.map(b => ({ id: `${a.id}~${b.id}`, from: a.from, to: b.to,
        mapping: b.mapping ?? a.mapping, branch: b.branch ?? a.branch }))),
    ]
  }
  return edges
}

/** 后端工作流定义 → tapflow 画布数据。ui.hide 与 end 节点整个不画并桥接其连线;
 * 坐标不取种子值,一律 tapflowLayout 自动算(真实运行会衍生节点,种子摆位靠不住);
 * 画布切到运行态时会按「去掉隐藏节点后的图」再算一次,列距始终均匀。 */
export function adaptWorkflow(wf: WorkflowDetail):
  TapCanvasData & { show: TapShowMap; feeds: TapFeedMap; placed: boolean } {
  const nodes: TapNode[] = []
  const hidden = new Set<string>()
  const show: TapShowMap = {}
  const feeds: TapFeedMap = {}
  const loopBodies = new Set((wf.graph.nodes ?? [])
    .filter(n => n.type === 'loop' && !(n.config?.ui as UiHint | undefined)?.show_loop_body)
    .flatMap(n => Array.isArray(n.config?.body) ? (n.config!.body as unknown[]).map(String) : []))
  for (const n of wf.graph.nodes ?? []) {
    const ui = ((n.config ?? {}).ui ?? {}) as UiHint
    if (ui.show) show[n.id] = ui.show
    if (ui.feeds) feeds[n.id] = ui.feeds
    // 循环体由 loop 母节点在运行态按 iteration 展开；编排态不把它误画成孤立卡。
    if (loopBodies.has(n.id)) { hidden.add(n.id); continue }
    const t = toTapNode({ ...n, __allNodes: wf.graph.nodes ?? [] } as WorkflowNode,
      wf.input_schema ?? {}, wf.subflow_contracts, wf.tool_contracts)
    if (t) nodes.push(t)
    else hidden.add(n.id)
  }
  // 旧图没有 ui.loop_item_fields 时，从循环 source 指向的工具输出合同实时推导。
  // 合同始终来自后端注册表，不要求用户在循环节点重复声明一遍输出结构。
  for (const loop of nodes.filter(n => n.type === 'loop' && !n.loop?.itemFields?.length)) {
    const match = loop.loop?.source?.match(/^\{\{\s*([^{}.]+)\.([^{}]+)\s*\}\}$/)
    if (!match) continue
    const source = nodes.find(n => n.id === match[1])
    const output = source?.outputs?.find(p => p.k === match[2])
    if (output?.itemFields?.length) loop.loop = { ...loop.loop, itemFields: output.itemFields }
  }
  const edges = bridgeEdges(wf.graph.edges ?? [], hidden)
  // 画布存过坐标就照存的摆(那是用户亲手拖的,自动布局会把它冲掉);
  // 只要有一个节点没盖章(比如后端新加了节点),整张图重新自动布局——
  // 半自动半手动会摆出重叠,还不如统一算一遍
  const laidOut = nodes.length > 0 && nodes.every(
    n => !!((wf.graph.nodes ?? []).find(g => g.id === n.id)?.config?.ui as UiHint | undefined)?.xy)
  if (!laidOut) applyLayout(nodes, edges)
  // placed=true 时画布**不再**做挂载时的整图重排：那一遍会把用户亲手拖的位置推回去，
  // 「拖动也算编辑、要存下来」就成了空话（存了，下次打开又被排版盖掉）
  return { nodes, edges, show, feeds, placed: laidOut }
}

/** `{{input.x}}` 占位（ui.title 里用它带出本次运行的对象名） */
const TITLE_VAR = /\{\{\s*input\.([a-zA-Z0-9_]+)\s*\}\}/g

/** 开始节点当前入参 → 展示用取值表。**画布本地就有**,不用等运行:
 * 用户在运行面板选完场景,标题当场就能带出场景名。 */
export function titleVars(nodes: TapNode[]): Record<string, string> {
  const vals: Record<string, string> = {}
  for (const p of nodes.find(n => n.type === 'start')?.params ?? []) {
    const v = (p.v ?? '').trim()
    // 项目这类 ctx 参数存的是「25 · 逃脱追捕」,标题里只要名字
    if (v) vals[p.k] = v.replace(/^\d+\s*·\s*/, '')
  }
  return vals
}

/** ui.title 的 `{{input.x}}` → 实际入参值。**取不到就连分隔符一起抹掉**——
 * 「场景介绍 · 」这种半截标题比不带名字更糟,看着像数据丢了。 */
export function resolveTitle(raw: string, vals: Record<string, string>): string {
  if (!raw.includes('{{')) return raw
  return raw.replace(TITLE_VAR, (_m, k: string) => vals[k] ?? '')
    .replace(/[·:：|/-]\s*$/, '').trim()
}

/** 存的是「819 · 镜头1」这类显示串、取前缀数字传后端的 ctx 类型——
 * 项目/卷/章/镜都定位到 content_nodes 的整数 id，场景/角色/道具存的是名字本身。 */
const ID_CTX_KEYS: TapCtxKey[] = ['project_id', 'volume_id', 'chapter_id', 'shot_id']

/** 开始节点当前入参 → 工作流 inputs。ctx 项目/卷/章/镜参数存的是「25 · 标题」,取前缀数字——
 * 漏了这一步,shot_id 这类 int 入参会把整条「819 · 镜头1」传给后端,
 * 落到 SQL 参数上就是 invalid input for query argument（str 当 int 用）。 */
export function startInputs(nodes: TapNode[]): { inputs: Record<string, unknown>; projectId?: number; missing: string[] } {
  const start = nodes.find(n => n.type === 'start')
  const inputs: Record<string, unknown> = {}
  const missing: string[] = []
  let projectId: number | undefined
  for (const p of start?.params ?? []) {
    const v = (p.v ?? '').trim()
    if (p.required && !v) missing.push(p.label || p.k)
    if (!v) continue
    if (p.ctx === 'project_id') {
      projectId = parseInt(v, 10) || undefined
      inputs[p.k] = projectId
    } else if (p.ctx === 'target_ref') {
      inputs[p.k] = v.split(' · ', 1)[0]
    } else if (p.ctx && ID_CTX_KEYS.includes(p.ctx)) {
      // 「（不分卷）」这类占位值不是 id：不往下送，让后端按「没给」处理
      const id = parseInt(v, 10)
      if (id) inputs[p.k] = id
    } else if (p.type === 'int') inputs[p.k] = parseInt(v, 10)
    else inputs[p.k] = v
  }
  return { inputs, projectId, missing }
}

/** jsonb 经 asyncpg 出来是字符串——安全解包成对象 */
export function jsonbObj(v: unknown): Record<string, unknown> {
  if (v && typeof v === 'object') return v as Record<string, unknown>
  if (typeof v === 'string') {
    try { return JSON.parse(v) as Record<string, unknown> } catch { return {} }
  }
  return {}
}
