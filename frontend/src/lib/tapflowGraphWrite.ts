// tapflow 画布 → 后端 graph（正向投影 tapflowGraphAdapter 的反面）。
//
// **合并而不是重建**：以库里那份 graph 为底，只覆盖画布真正能编辑的键，其余
// （payload/skip_if/preview/inputs/args/ui.show/ui.feeds…）原样带过去。重建整张 config
// 就意味着「凡是画布没投影的字段都会丢」——投影层永远落后于后端 config 的演进，
// 那样每加一个后端字段就要同步改画布，改漏一次就静默丢配置。
//
// 画布的**专属存储**就是 `node.position` + `config.ui`（解释器完全不读 ui）：
// 坐标、尺寸、标题、节点在画布上是什么形态，全落在这两处。保存时给每个节点盖
// `ui.xy` 章，正向 adapter 见到章就用存的坐标、不再自动布局。
//
// 增删节点与改连线都存得下——`validate_graph` 只查 id 唯一 / 边指向存在的节点 /
// start·end 各至多一个 / 无环，对 config 没有任何要求。存得下和跑得起来是两回事：
// 新的生成节点没选执行体照样存，只是运行到它会报错，面板上就地标红。
import type { WorkflowNode } from '../api'
import type { TapEdge, TapNode, TapNodeType, TapParam, TapQcConf } from './tapflowData'
import { customGenConfig } from './tapflowCustomNode'
import { bridgeEdges } from './tapflowGraphAdapter'

export interface TapGraphIn {
  nodes: WorkflowNode[]
  edges: { from: string; to: string; mapping?: 'auto' | 'each' | 'collect'; branch?: string }[]
}

export interface TapWriteResult {
  graph: TapGraphIn
  input_schema: Record<string, unknown>
  /** 存下去了但**跑不起来**的问题（如生成节点没选执行体）。与「存不下」不是一回事 */
  warnings: string[]
}

/** 画布节点类型 → 后端节点类型。新增节点靠它决定存成什么。
 * 画布上的 qc 圆点与 link 卡在后端都是 action（只读判据 / 写库动作）。
 * value 节点（引擎当常量透传的画布素材）不再从菜单新增——上传参考图的入口
 * 已合并进图片生成节点（t.refImages）；这个映射保留只为兼容已有画布里的 value 节点。 */
const NODE_TYPE: Record<TapNodeType, string> = {
  start: 'start', text: 'llm',
  image: 'gen', video: 'gen', audio: 'gen', gen: 'gen',
  flow: 'subflow', tool: 'action', condition: 'condition', loop: 'loop', qc: 'action', link: 'action', upload: 'value',
  mount: 'mount',
}

/** 生成节点的模态：出图/出视频/出音频走的是不同的 Step，modality 得跟着节点类型走。
 * tap='gen'（模板投影出的通用生成节点）不写死模态——保留库里已有的 modality
 * （视频模板节点就是 video），没有才兜 image。此前把它硬编码成 'image'，
 * 导致视频节点保存一次就被覆写成图片模态，运行时走错 Step。 */
const MODALITY: Partial<Record<TapNodeType, string>> = {
  image: 'image', video: 'video', audio: 'audio',
}

/** 面板的质检段 → config.qc。没配过质检的节点不该凭空长出一个 qc 键。 */
function qcOut(qc: TapQcConf | undefined): Record<string, unknown> | undefined {
  if (!qc) return undefined
  if (!qc.on) return { on: false }
  return {
    on: true,
    ...(qc.skill ? { skill: qc.skill } : {}),
    ...(qc.kb?.length ? { folder_ids: qc.kb.map(Number).filter(Number.isFinite) } : {}),
    ...(typeof qc.threshold === 'number' ? { threshold: qc.threshold } : {}),
    stage: qc.stage ?? 'prompt',
    ...(qc.retry ? { retry: qc.retry } : {}),
  }
}

function toolArg(p: TapParam): unknown {
  if (p.source === 'ref' && p.ref) {
    const head = p.ref.node === 'start' ? 'input' : p.ref.node
    return `{{${head}.${p.ref.k}}}`
  }
  const raw = (p.v ?? '').trim()
  if (!raw) return undefined
  if (p.type === 'int') {
    const value = Number(raw)
    return Number.isFinite(value) ? value : raw
  }
  if (p.type === 'json') {
    try { return JSON.parse(raw) } catch { return raw }
  }
  return p.v
}

/** 开始节点的入参声明 → input_schema。键名与类型沿用原 schema，
 * 画布只改「要不要这个参数、显示名是什么、必填与否、什么顺序」。 */
function schemaOut(params: TapParam[], base: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  params.forEach((p, i) => {
    const prev = (base[p.k] ?? {}) as Record<string, unknown>
    out[p.k] = {
      ...prev,
      ...(p.type === 'int' ? { type: 'int' } : prev.type ? { type: prev.type } : {}),
      required: !!p.required,
      desc: p.label || p.k,
      seq: i,          // 显式排序：jsonb 保不住书写顺序，见 tapflowGraphAdapter.schemaToParams
    }
  })
  return out
}

/** 把画布节点上「能配的那几层」盖到一份 config 上。base 是库里原来的 config
 * （新节点就是空对象），没被画布覆盖的键原样留着。
 *
 * projectKey = 入参里哪个键是项目（自由节点的「缺才跑」探针要用它按项目查产物）。 */
function applyNode(t: TapNode, backendType: string, base: Record<string, unknown>,
                   projectKey: string): Record<string, unknown> {
  const cfg: Record<string, unknown> = { ...base }
  const ui = { ...((cfg.ui ?? {}) as Record<string, unknown>) }

  // ── 画布专属层：这一整块解释器不读，画布说了算 ──
  ui.tap = t.type
  ui.title = t.title
  ui.w = t.w
  ui.h = t.h
  ui.xy = true                       // 盖章：坐标由画布维护，正向别再自动布局
  if (t.manualSize) ui.manual_size = true
  else delete ui.manual_size
  if (t.hideInRun) ui.hide_in_run = true
  else delete ui.hide_in_run
  if (t.custom) ui.custom = true     // 「这是用户自己加的」——生产态据此放行属性面板
  else delete ui.custom
  // 提示词标签的展示名。占位符本体已经在 charter 里（那份才是引擎解析的），
  // 这里只是「token → 显示成什么」。不存的话重开画布标签就退化成裸 {{n1abc.text}}。
  if (t.bind?.refs?.length) ui.refs = t.bind.refs
  else delete ui.refs
  // 作者态内容跟 graph 走；运行产物留在 workflow_node_runs / 附件表，不把一次运行
  // 误当成一次编排修改。空字符串也要存：用户主动清空后不能被旧值“复活”。
  const state = { ...((ui.state ?? {}) as Record<string, unknown>) }
  if (t.gen?.edited) {
    state.prompt = t.gen.prompt
    state.prompt_edited = true
  } else {
    delete state.prompt
    delete state.prompt_edited
  }
  if (t.gen?.refNodes !== undefined) state.ref_nodes = t.gen.refNodes
  else delete state.ref_nodes
  if (t.textEdited) {
    state.text = t.text ?? ''
    state.text_edited = true
  } else {
    delete state.text
    delete state.text_edited
  }
  if (Object.keys(state).length) ui.state = state
  else delete ui.state
  cfg.ui = ui

  // 缺才跑：面板的开关 = config.force 取反（引擎里 force=true 就是每次都跑）
  if (t.bind?.onlyMissing !== undefined) {
    if (t.bind.onlyMissing) delete cfg.force
    else cfg.force = true
  }

  // 挂载点（2026-09-17）：归宿声明落进 config.target/subject/variant；
  // 画布不写 outputs——运行回显由后端落到 workflow_node_runs，不从结构数据走
  if (backendType === 'mount') {
    if (t.mount?.target) cfg.target = t.mount.target
    else delete cfg.target
    if (t.mount?.subject?.kind && t.mount?.subject?.id) cfg.subject = t.mount.subject
    else delete cfg.subject
    if (t.mount?.variant) cfg.variant = t.mount.variant
    else delete cfg.variant
  }

  if (backendType === 'gen') {    if (t.bind?.step) cfg.step = t.bind.step
    else delete cfg.step
    if (t.bind?.outputSlot?.role) cfg.output_slot = t.bind.outputSlot
    else delete cfg.output_slot
    cfg.modality = MODALITY[t.type]
      ?? (typeof base.modality === 'string' && base.modality ? base.modality : 'image')
    if (t.bind?.modelProfileId) cfg.model_profile_id = t.bind.modelProfileId
    else delete cfg.model_profile_id
    const q = qcOut(t.bind?.qc)
    if (q) cfg.qc = q
    else delete cfg.qc
    // 出图节点的 charter + 技能 + 知识库 = anchor（约束）段的来源。
    // 引擎 `_anchor_from_config` 读它：配了就以它为准，没配才回落到装配器的硬编码 anchor。
    cfg.charter = t.bind?.charter ?? ''
    cfg.skills = t.bind?.skills ?? []
    cfg.folder_ids = (t.bind?.kb ?? []).map(Number).filter(Number.isFinite)
    // 手工新建的生成节点：补上「跑起来还缺的那几项」（payload / 缺才跑探针）。
    // 只补 base 里没有的，用户改过的配置不覆盖
    if (t.custom) Object.assign(cfg, customGenConfig(t, base, projectKey))
    // 卡上上传的静态参考图：顶层存一份供画布回显，同步进 payload.reference_images——
    // 引擎 _apply_refs 读的是 payload 那份（排最优先，去重后受 max_refs 上限约束）。
    // t.refImages === undefined 表示画布没动过它：不写，种子/模板里的配置原样保留。
    if (t.refImages !== undefined) {
      cfg.reference_images = t.refImages
      cfg.payload = { ...((cfg.payload ?? {}) as Record<string, unknown>), reference_images: t.refImages }
    }
  }

  // value 节点 = 参考图素材：上传/外链的 url 跟着画布走（引擎当常量透传，
  // 下游生成节点按入边收它当参考图；投影见 tapflowGraphAdapter 的 upload 分支）
  if (backendType === 'value') {
    cfg.value = { ...((base.value ?? {}) as Record<string, unknown>), url: t.src ?? '', name: t.title }
  }

  if (backendType === 'llm') {
    cfg.charter = t.bind?.charter ?? ''
    cfg.skills = t.bind?.skills ?? []
    cfg.folder_ids = (t.bind?.kb ?? []).map(Number).filter(Number.isFinite)
    cfg.tools = t.bind?.tools ?? []
    const q = qcOut(t.bind?.qc)
    if (q) cfg.qc = q
    else delete cfg.qc
  }

  if (backendType === 'subflow' && t.bind?.subflow?.slug) {
    cfg.slug = t.bind.subflow.slug
    if (t.bind.subflow.version) cfg.version = t.bind.subflow.version
  }

  if (backendType === 'action' && t.type === 'tool') {
    cfg.name = t.tool?.name ?? ''
    cfg.args = Object.fromEntries((t.params ?? [])
      .map(p => [p.k, toolArg(p)] as const)
      .filter(([, value]) => value !== undefined))
  }

  if (backendType === 'condition') {
    cfg.branches = t.condition?.branches ?? [
      { id: 'if-1', kind: 'if', clauses: [{ left: '{{input.source.prompt_text}}', operator: 'truthy' }] },
      { id: 'else', kind: 'else' },
    ]
    delete cfg.when
    delete cfg.then
    delete cfg.else
  }

  if (backendType === 'loop') {
    if (t.loop?.source) cfg.source = t.loop.source
    cfg.body = t.loop?.body ?? []
    cfg.concurrency = Math.max(1, Math.min(8, t.loop?.concurrency ?? 1))
    ui.show_loop_body = true
    ui.loop_action = t.loop?.actionTitle ?? `循环执行 ${(t.loop?.body ?? []).length} 个节点`
    if (t.loop?.itemFields?.length) ui.loop_item_fields = t.loop.itemFields
    else delete ui.loop_item_fields
  }

  return cfg
}

/** 画布连线 → graph 连线。
 *
 * 不能直接照抄画布：`ui.hide` 的节点（如某些图的 end）在投影时被**桥接**掉了——
 * 库里的 `write→end`、`gen→end` 在画布上变成了一根 `A→B`。原样存回去，那个隐藏节点
 * 就成了没有入边的孤儿，拓扑序里可能排到生成节点前面，outputs 取到空值。
 *
 * 所以：画布边里凡是「桥接产物」（桥接后有、原图里没有）的一律丢掉，改用原图里
 * 经过隐藏节点的那两条；其余画布边（用户真连的、新连的）照收。 */
function mergeEdges(base: TapGraphIn, canvas: TapEdge[],
                    hiddenKept: WorkflowNode[]): Array<{
                      from: string; to: string; mapping?: 'auto' | 'each' | 'collect'; branch?: string
                    }> {
  const hidden = new Set(hiddenKept.map(n => n.id))
  if (!hidden.size) return canvas.map(e => ({ from: e.from, to: e.to, ...(e.mapping ? { mapping: e.mapping } : {}), ...(e.branch ? { branch: e.branch } : {}) }))
  const key = (e: { from: string; to: string }) => `${e.from}→${e.to}`
  const raw = new Set((base.edges ?? []).map(key))
  const artifacts = new Set(
    bridgeEdges(base.edges ?? [], hidden).map(key).filter(k => !raw.has(k)))
  return [
    ...canvas.filter(e => !artifacts.has(key(e))).map(e => ({ from: e.from, to: e.to,
      ...(e.mapping ? { mapping: e.mapping } : {}), ...(e.branch ? { branch: e.branch } : {}) })),
    ...(base.edges ?? []).filter(e => hidden.has(e.from) || hidden.has(e.to)),
  ]
}

/** 画布状态 + 库里那份 graph → 可提交的 graph。base 必须是**这次打开时拉到的原图**。 */
export function toGraph(base: TapGraphIn, baseSchema: Record<string, unknown>,
                        nodes: TapNode[], edges: TapEdge[] = []): TapWriteResult {
  const warnings: string[] = []
  const baseById = new Map((base.nodes ?? []).map(n => [n.id, n]))
  const onCanvas = new Set(nodes.map(n => n.id))

  // end 与 ui.hide 的节点不投影到画布上——它们「不在画布里」是正常的：
  // 产物归宿由挂载点接管，end 的 outputs 收集职责留在引擎侧，原样保留，别当成被删了
  const bodyIds = new Set(nodes.flatMap(n => n.loop?.body ?? []))
  const hiddenKept = (base.nodes ?? []).filter(n => !onCanvas.has(n.id) && (
    n.type === 'end' || !!((n.config?.ui ?? {}) as { hide?: boolean }).hide || bodyIds.has(n.id)))

  // 入参里代表「项目」的键：自由生成节点的缺才跑探针按项目查自己上次的产物。
  // 按 schema 找而不是写死 'project_id'——别的画布可能叫别的名字，找不到就退化成每次都跑
  const projectKey = Object.keys(baseSchema).find(k => k === 'project_id')
    ?? Object.keys(baseSchema).find(k => k.endsWith('project_id')) ?? 'project_id'

  const outNodes: WorkflowNode[] = nodes.map(t => {
    const bn = baseById.get(t.id)
    const type = bn?.type ?? NODE_TYPE[t.type] ?? 'gen'
    if (type === 'gen' && !t.bind?.step) {
      warnings.push(`「${t.title}」没选执行体（生成步骤）——图存得下，但运行到它会报错`)
    }
    if (type === 'subflow' && !t.bind?.subflow?.slug) {
      warnings.push(`「${t.title}」没选要引用的流程——图存得下，但运行到它会报错`)
    }
    if (type === 'action' && t.type === 'tool' && !t.tool?.name) {
      warnings.push(`「${t.title}」还没有选择系统工具——图存得下，但运行到它会报错`)
    }
    if (type === 'loop' && !t.loop?.source) {
      warnings.push(`「${t.title}」还没有选择循环数据源——图存得下，但运行到它会报错`)
    }
    return {
      id: t.id, type,
      position: { x: Math.round(t.x), y: Math.round(t.y) },
      config: applyNode(t, type, bn?.config ?? {}, projectKey),
    }
  })

  return {
    graph: { nodes: [...outNodes, ...hiddenKept], edges: mergeEdges(base, edges, hiddenKept) },
    input_schema: (() => {
      const start = nodes.find(n => n.type === 'start')
      return start?.params ? schemaOut(start.params, baseSchema) : baseSchema
    })(),
    warnings,
  }
}
