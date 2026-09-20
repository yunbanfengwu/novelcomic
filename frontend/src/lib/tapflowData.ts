// tapflow 画布：类型定义 + 假数据（真实数据由工作流 graph 经 tapflowGraphAdapter 投影而来）
import { TAP_CANVAS_IMAGE_STEP, TAP_CANVAS_VIDEO_STEP } from './tapflowCustomNode'
import type { AgentTool, ToolParam } from '../api'

// start/qc/link 是接真实工作流后新增的节点类型（开始节点/质检圆点/关联落库卡），
// 样式遵循 tapflow 风格、尽量简单。
export type TapNodeType = 'image' | 'text' | 'video' | 'audio' | 'upload' | 'gen'
  | 'start' | 'qc' | 'link' | 'flow' | 'tool' | 'condition' | 'loop' | 'mount'

/** 出媒体的节点类型（后端一律是 type=gen，差别只在 modality）。
 * **唯一判据**：投影、反投影、运行状态回填都用它——散着写 `n.type === 'gen'`
 * 就会出现「模板里的设定图卡认得、自己拖出来的图片卡不认得」这种半瘫状态。 */
export const TAP_GEN_TYPES: TapNodeType[] = ['gen', 'image', 'video', 'audio']
export const isGenType = (t: TapNodeType) => TAP_GEN_TYPES.includes(t)

export interface TapNode {
  id: string
  type: TapNodeType
  /** 节点标题：文件名或类型名（男主.jpeg / Image / Text / 上传图片 / 图片生成 / Video） */
  title: string
  x: number; y: number; w: number; h: number
  /** 仅运行视图存在的循环实例；不得反写或自动保存到工作流定义。 */
  runtime?: {
    loopOwner: string; iteration: number; transient: true
    /** Stable identity of the actual loop body / child-workflow node being shown. */
    childNodeKey?: string
    /** Exact child workflow run supplying status and media for a subflow projection. */
    subrunId?: number
    /** Exact loop descriptor represented by this card; used to rerun only this item. */
    sourceItem?: Record<string, unknown>
  }
  src?: string          // 图片 / 视频封面
  video?: string        // 视频源：hover 自动播放、移开暂停；放大可全屏查看
  /** 产物形态（投影自后端 config.modality）：modality=video 的通用 gen 节点
   * 产物是 mp4，必须进 video 字段渲染视频卡——不认它的话 mp4 会被塞进 src，
   * 卡上 img 直接破图（「生成预告片」节点曾因此显示成坏图片卡）。 */
  modality?: 'image' | 'video'
  /** 出图节点自带的**静态参考图**（用户在卡上上传的已有图片，url 清单）。
   * 属画布作者态，随 graph 保存（config.reference_images，并同步进
   * payload.reference_images——引擎 _apply_refs 里这一份排最优先、去重后受上限约束）。
   * 与上游连线收来的参考互补：连线是「别的节点的产物」，这里是「手头现成的图」。 */
  refImages?: string[]
  text?: string         // 文本节点正文（空 = 「双击开始编辑…」占位）
  /** 正文被手改过：下次运行**整段覆盖**该节点的产出（模型不跑，改的那份直接落库）。
   * 与生成条提示词的手编冻结同一语义——你改过的，装配/模型都不许再覆盖。 */
  textEdited?: boolean
  /** 引用的工作流声明了「支持智能调用」（后端 workflows.smart_call）。
   * 只有它为真，这张引用卡才允许炸开生成条：输入的提示词会先经大模型规划出
   * 「子流程里哪几个节点重生成、哪几个复用」，而不是笼统地整图重跑。
   * 由 subflow_contracts 投影而来，属派生态，不反写进图定义。 */
  smart?: boolean
  done?: boolean        // 运行完成 → 标题旁蓝色对勾徽章
  status?: 'generating' // 生成中 → 卡片红字「生成中」占位
  starred?: boolean     // 图片左上角星标
  /** 选中时下方生成输入条的内容（有值才显示）。
   * prompt = **最终提示词**（装配产物，预填后可改）；edited=true 表示用户手改过，
   * 此后装配不再覆盖它（沿用 prompt_fields 的手编冻结语义）。 */
  gen?: {
    /** 参考图缩略图 url（运行/预检回填的实体参考图） */
    refs: string[]
    prompt: string; model: string; params: string[]
    edited?: boolean
    /** 手选的上游参考**节点 id**（不是 url）：节点重跑后产物会变，存 id 才永远是最新的。
     * undefined = 还没选过，按直属上游自动带；空数组 = 用户全删了，就是不要参考。 */
    refNodes?: string[]
  }
  /** 输入变量（每个节点都有；开始节点的输入即整张流程的入参）。
   * ctx 类走运行上下文下拉；其余类型可填常量或**引用上游节点的输出变量**。 */
  params?: TapParam[]
  /** 输出变量：本节点产出什么，供下游按 {{节点.变量}} 引用 */
  outputs?: TapParam[]
  /** 开始节点：本次运行所在项目的基本信息（画风/主线/比例/角色类型，只读回显） */
  project?: TapProjectInfo
  /** 质检节点：圆点状态（绿=通过/红=未通过/灰=未跑）+ 卡上评分 + 判据 */
  qc?: { state: 'pass' | 'fail' | 'idle'; score?: string; rule?: string }
  /** 生成配置（编排态属性面板的核心：这个节点**怎么来**，参考智能体编排运行段）。
   * mode=query 走内置工具取数（不进模型）；mode=llm 由模型生成，用 charter 当系统提示词。
   * skills=技能包；kb=知识库；onlyMissing=缺才跑。
   * step=执行体（跑哪个已注册生成步骤），可选可存；assemble 由后端定义只读。 */
  bind?: {
    mode?: 'query' | 'llm'
    /** 执行体：跑哪个已注册的生成步骤（config.step）。候选来自后端 flow.STEPS，
     * 落库/附件/回写焊在该 Step 的 next 里。可选可存；没选也能存，只是跑不了。 */
    step?: string
    outputSlot?: { role: string; variant?: string }
    /** Model profile explicitly bound to this media node. */
    modelProfileId?: number
    /** 装配器名（config.assemble.name）：由后端定义，画布只读回显 */
    assemble?: string
    /** subflow 节点引用的工作流（slug / version）：也是一种执行体，可选可存 */
    subflow?: { slug?: string; version?: number }
    charter?: string; skills?: string[]
    kb?: string[]; tools?: string[]; onlyMissing?: boolean
    /** AI 自主取上下文（2026-09-17）：开启后写提示词的智能体默认挂全部只读工具 +
     * 画布上游 ctx 探索（ctx.outline/search/get/trace），查什么、查多深由模型按
     * 提示词自己规划——「根据项目的基本信息和画风生成封面」不用再手工勾 project_info。 */
    autoContext?: boolean
    /** 系统提示词下方的「+ 引用」：运行时才有值的动态上下文。
     * **拼进 user 段，不进 system 段**——system 要稳定可复用，上下文每次都不同。 */
    refs?: TapCtxRef[]
    /** 质检（勾上才有）：判法来自技能/知识，阈值与时机是本条产线的策略 */
    qc?: TapQcConf
  }
  /** 工作流节点：引用另一张已编排好的 tapflow 流程（组合集引入最小集） */
  flow?: { id?: string; name?: string }
  /** 系统工具节点。name 是共享工具注册表中的稳定名称，入参在 params，输出由合同自动生成。 */
  tool?: { name?: string; writes?: boolean; description?: string }
  /** Declarative branch selector. Each row owns one outgoing branch port. */
  condition?: { branches?: TapConditionBranch[]; matchedBranch?: string; operator?: string; thenLabel?: string; elseLabel?: string; matched?: boolean }
  /** 本次运行的工具/查询返回，纯运行态，不写回工作流定义。 */
  runtimeResult?: { summary: string; json: string }
  /** 通用 foreach 节点。source 是集合表达式，body 是被逐项执行的后端节点 id。
   * 运行实例只用于运行态展示，不写回工作流定义。 */
  loop?: {
    /** Unified loop-aggregate semantic label, independent from node execution type. */
    aggregate?: boolean
    source?: string; body?: string[]; concurrency?: number
    /** source 为对象数组时，循环体可引用的 {{__item__.字段}} 合同。 */
    itemFields?: TapParam[]
    /** 编排态循环体的业务动作；子流程必须显式标为“引用工作流”。 */
    actionTitle?: string; isSubflow?: boolean
    /** A subflow that aggregates multiple children; display it as a loop without changing execution type. */
    imported?: boolean
    instances?: Array<{
      iteration: number; label: string; status: 'running' | 'done' | 'skipped' | 'failed'
      src?: string; error?: string
    }>
  }
  /** 关联节点：落库动作与落点说明（运行态隐藏但自动执行；入参走 params） */
  link?: { action: string; target: string }
  /** 挂载点（2026-09-17）：独立声明的「产物归宿」。连到它的产物就落进这个归宿，
   * 节点卡上回显当前指向的那张图——真实数据指向这个节点，不再是「谁最后跑谁当封面」。
   * subject 缺省时按运行入参推断（角色/场景入口自动带）。 */
  mount?: {
    target: string
    subject?: { kind: string; id: number }
    variant?: string
    /** 运行时回显：已落的 url / 版本 / 来源节点 / 是否本次新落 */
    stored?: string
    url?: string
    version?: number
    sourceNode?: string
    unchanged?: boolean
  }
  /** 运行失败的错误摘要（Inspector 展示） */
  error?: string
  /** 节点卡右上角的胶囊：跳过（缺才跑命中）/ 失败。与生成条右上角那枚同一套样式。
   * 「跳过」必须看得见——不然卡上带个对勾、内容却是上一次的，看着像这轮真跑过。 */
  badge?: { label: string; tone?: 'ok' | 'err' | 'skip' }
  /** 炸开的生成条右上角那枚徽标：节点**内部**跑到哪一段了。
   * 一个生成节点里有装配→质检→出图三段各几十秒，只标「生成中」看不出在干嘛。
   * 质检跑完后留着显示分数（tone 决定颜色）。
   * issues=质检给出的问题清单：点徽标就在生成条里摊开——不合格却看不到为什么，
   * 用户只能瞎改提示词重试。 */
  stage?: {
    label: string; tone?: 'run' | 'ok' | 'err'; issues?: string[]
    /** 被判的那段 user（不含 anchor）+ 系统锁死的 anchor：
     * 「重新生成」要拿它俩当输入。拿生成条里合成后的整段去重写会把 anchor
     * 也送进判据——那是后端明写踩过的坑，必然轮轮不合格。 */
    user?: string; anchor?: string
  }
  /** 运行视图隐藏（但照常执行），如关联落库节点 */
  hideInRun?: boolean
  /** 用户在画布上手工加的节点（不是模板里那些）。**要落库**（config.ui.custom），
   * 生产态据此决定「这个节点能不能配」——模板节点只读，自己加的当然要能配，
   * 否则拖出来就是个配不了、跑不了的空壳。 */
  custom?: boolean
  /** 用户通过右下角手柄明确调整过宽高；自适应节点也采用保存尺寸。 */
  manualSize?: boolean
}

/** 运行视图投影：隐藏辅助节点与循环体模板，并把它们上下游桥接起来（A→隐→B 变 A→B）。
 * loop.body 是编排定义；真正运行时由 transient 实例节点取代，不能两套同时出现。
 * 纯函数，不动源数据。 */
export function visibleFlow(nodes: TapNode[], edges: TapEdge[], mode: 'edit' | 'run'):
  { nodes: TapNode[]; edges: TapEdge[] } {
  if (mode === 'edit') return { nodes, edges }
  const hidden = new Set(nodes.filter(n => n.hideInRun).map(n => n.id))
  for (const loop of nodes.filter(n => n.type === 'loop' && !n.runtime)) {
    for (const bodyId of loop.loop?.body ?? []) hidden.add(bodyId)
  }
  if (!hidden.size) return { nodes, edges }
  let cur = edges
  for (const h of hidden) {
    const ins = cur.filter(e => e.to === h)
    const outs = cur.filter(e => e.from === h)
    cur = [
      ...cur.filter(e => e.from !== h && e.to !== h),
      ...ins.flatMap(a => outs.map(b => ({
        id: `${a.id}~${b.id}`, from: a.from, to: b.to,
        mapping: b.mapping ?? a.mapping,
      }))),
    ]
  }
  return { nodes: nodes.filter(n => !hidden.has(n.id)), edges: cur }
}

/** 运行/预检状态对节点的覆盖片段：画布渲染时合并，不落进结构数据 */
export type TapNodeOverlay = Partial<
  Pick<TapNode, 'src' | 'video' | 'done' | 'status' | 'qc' | 'params' | 'gen' | 'error' | 'runtimeResult'>>

/** 上下文类入参绑定的字段。卷/章/镜拆成三级并级联：选了卷才在该卷下选章，
 * 选了章才在该章下选镜；卷可不填（项目不分卷时直接选章）。 */
export type TapCtxKey = 'project_id' | 'volume_id' | 'chapter_id' | 'shot_id'
  | 'character_id' | 'scene_id' | 'prop_id' | 'target_ref'

/** 变量类型：ctx=运行上下文（下拉选）；其余是可赋值/可引用的数据类型 */
export type TapVarType = 'ctx' | 'text' | 'int' | 'json' | 'image' | 'video'

export const TAP_VAR_TYPE_LABEL: Record<TapVarType, string> = {
  ctx: '上下文', text: '文本', int: '数字', json: 'JSON', image: '图片', video: '视频',
}

/** 输出变量只允许这三种：产物本体（图片/视频）走附件库，节点输出的是它们的引用与数据 */
export const TAP_OUTPUT_TYPES: TapVarType[] = ['text', 'int', 'json']

/** 「+ 引用」的一条动态上下文。三种来源对应三种取值时机：
 * node=上游节点产物（引擎按连线解析）｜ctx=运行上下文实体｜tool=前置取数工具 */
export interface TapCtxRef {
  kind: 'node' | 'ctx' | 'tool'
  /** 展示名（节点标题 / 上下文名 / 工具名） */
  label: string
  /** 插进提示词的占位符，如 {{场景介绍}} / {{ctx.project_id}} */
  token: string
  /** 数据类型：决定这颗引用方块显示什么图标（图片走缩略图占位） */
  type?: TapVarType
  /** 图片/视频引用的缩略图 */
  thumb?: string
}

/** 质检配置。判法（维度/怎么算分）来自技能与知识；
 * 阈值与时机是**这条产线的策略**，同一套技能角色卡要 85、场景图 75 就够。 */
export interface TapQcConf {
  on: boolean
  /** 质检技能（判哪些维度、怎么算分）；输出结构由引擎强制，技能不管 */
  skill?: string
  /** 判据词表/禁忌清单这类事实依据 */
  kb?: string[]
  /** 合格线 */
  threshold?: number
  /** 时机：出图前判提示词（便宜，改了再出）｜出图后判画面（贵，只能重出） */
  stage?: 'prompt' | 'image'
  /** 不合格回退重生成的次数（0=不回退）。重试 N 次 = 最多 N+1 次生成 */
  retry?: number
}

export const TAP_QC_STAGES: {
  k: NonNullable<TapQcConf['stage']>; short: string; tip: string; note: string
}[] = [
  { k: 'prompt', short: '前', tip: '出图前', note: '出图前判提示词：文本模型，不合格改了再出，不浪费出图开销' },
  { k: 'image', short: '后', tip: '出图后', note: '出图后判画面：视觉模型，不合格只能重出，开销已经花掉' },
]

/** 一条变量声明（输入/输出共用；对齐 Dify 的变量表 + agentflow 的 ParamDecl）。
 * k 是**变量名**（下游按 {{节点.变量名}} 引用），label 是显示名。 */
export interface TapParam {
  k: string
  label?: string
  type?: TapVarType
  ctx?: TapCtxKey
  resourceKinds?: string[]
  allowedValues?: string[]
  required?: boolean
  /** 取值来源：const=直接给值（默认）；ref=引用上游节点的输出变量 */
  source?: 'const' | 'ref'
  /** source=ref 时指向的上游变量 */
  ref?: { node: string; k: string }
  /** 常量值 / 运行时填的值（source=ref 时不用） */
  v: string
  /** 数组输出的单项字段合同；循环数据源选中该输出后自动带入，不由用户重复配置。 */
  itemFields?: TapParam[]
}

/** 可被引用的上游变量（沿连线回溯收集） */
export interface TapUpstreamVar {
  nodeId: string
  nodeTitle: string
  k: string
  label?: string
  type?: TapVarType
  itemFields?: TapParam[]
}

/** 系统工具字段类型 → Tapflow 变量类型。array/object/bool 都用 JSON 编辑与传递。 */
export function toolVarType(type?: string): TapVarType {
  if (type === 'int' || type === 'number') return 'int'
  if (type === 'array' || type === 'object' || type === 'bool' || type === 'boolean') return 'json'
  if (type === 'image') return 'image'
  if (type === 'video') return 'video'
  return 'text'
}

function toolItemFields(field?: ToolParam): TapParam[] | undefined {
  const properties = field?.items?.properties
  if (!properties) return undefined
  return Object.entries(properties).map(([k, p]) => ({
    k, label: p.desc || k, type: toolVarType(p.type), v: '', required: !!p.required,
  }))
}

/** 工具注册合同 → 画布参数。current 用于切换/刷新合同时保留用户已做的映射。 */
export function toolInputParams(tool: Pick<AgentTool, 'params'>,
                                current: TapParam[] = []): TapParam[] {
  const old = new Map(current.map(p => [p.k, p]))
  return Object.entries(tool.params ?? {}).map(([k, field]) => {
    const previous = old.get(k)
    return {
      ...previous,
      k, label: k, type: toolVarType(field.type), required: !!field.required,
      v: previous?.v ?? '',
    }
  })
}

/** 工具输出完全来自系统注册合同；画布只读展示并提供给下游引用。 */
export function toolOutputParams(tool?: Pick<AgentTool, 'outputs'>): TapParam[] {
  return Object.entries(tool?.outputs ?? {}).map(([k, field]) => ({
    k, label: field.desc || k, type: toolVarType(field.type), v: '',
    itemFields: toolItemFields(field),
  }))
}

/** 收集某节点所有上游节点（含间接）的输出变量——输入变量「关联上游」的候选集。
 * 只给类型兼容的：文本可接文本，图片只接图片，视频只接视频。 */
export function upstreamVars(nodeId: string, nodes: TapNode[], edges: TapEdge[],
                             want?: TapVarType): TapUpstreamVar[] {
  const byId = new Map(nodes.map(n => [n.id, n]))
  const seen = new Set<string>()
  const queue = edges.filter(e => e.to === nodeId).map(e => e.from)
  const out: TapUpstreamVar[] = []
  // 循环体里的每个节点都天然拥有当前项变量。它不是普通图节点输出，只在 body 内有效。
  const owner = nodes.find(n => n.type === 'loop' && n.loop?.body?.includes(nodeId))
  for (const item of owner?.loop?.itemFields ?? []) {
    if (want && want !== 'ctx' && item.type && item.type !== want) continue
    out.push({ nodeId: '__item__', nodeTitle: '当前循环项', k: item.k,
      label: item.label, type: item.type })
  }
  while (queue.length) {
    const id = queue.shift()!
    if (seen.has(id)) continue
    seen.add(id)
    const n = byId.get(id)
    if (!n) continue
    const declared = n.type === 'start' ? (n.params ?? []) : (n.outputs ?? [])
    for (const o of declared) {
      if (want && want !== 'ctx' && o.type && o.type !== want) continue
      out.push({ nodeId: n.id, nodeTitle: n.title, k: o.k, label: o.label, type: o.type,
        itemFields: o.itemFields })
    }
    queue.push(...edges.filter(e => e.to === id).map(e => e.from))
  }
  return out
}

/** 画布常驻的项目基本信息（始终贴在开始节点上方）：运行时按入参里的项目带出，
 * 与项目页 InfoPane 同一套字段（画风/主线/尺寸比例/角色类型）。 */
export interface TapProjectInfo {
  id: number
  title: string
  artStyle: string
  storyline: string
  aspect: '16:9' | '9:16'
  characterMode: 'real' | 'virtual'
  /** 文风（写作风格），与画风并列——一个管文字一个管画面 */
  writingStyle?: string
  /** 画风示意图：一眼看出这个项目长什么样，比一段画风文字管用。
   * 取项目封面（config.cover_url）；没有就只显示文字。 */
  styleImage?: string
}

/** 假图占位（演示画布用）。声明在此处：下面的项目信息卡就要用它 */
const pic = (seed: string, w = 640, h = 360) => `https://picsum.photos/seed/${seed}/${w}/${h}`

export const TAP_PROJECT_INFO: TapProjectInfo = {
  id: 25,
  title: '北境灯塔',
  artStyle: '电影级奇幻写实动画；角色为高品质风格化动画造型，材质与光照物理可信；'
    + '飞龙有可信的生物结构与皮膜细节',
  storyline: '黄昏港口→暴雨夜救龙→发现晶纹秘密→穿越险阻→点亮灯塔',
  aspect: '16:9',
  characterMode: 'virtual',
  writingStyle: '冷峻克制、少年视角、白描为主',
  styleImage: pic('tap-style-north', 640, 360),
}

/** 「整体设定」入参的固定键名。没选项目时它顶替故事线/文风那一块——
 * 项目是设定的来源，没有项目做底，整体设定就得由人给。 */
export const TAP_OVERALL_KEY = 'overall_setting'

/** 上下文入参的**级联顺序**：上级不选，下级就没得选（没选项目，章的候选从哪来）。
 * 表单必须按它排——不能靠声明顺序，jsonb 存 input_schema 时会按
 * 「键长度 → 字典序」重排键，project_id/chapter_id/scene_name 同为 10 字符，
 * 排出来就成了「章、项目、场景」。级联关系是事实，书写顺序不是。 */
export const TAP_CTX_ORDER: TapCtxKey[] = [
  'project_id', 'target_ref', 'volume_id', 'chapter_id', 'shot_id',
  'character_id', 'scene_id', 'prop_id',
]

/** ctx 类入参的可选项（假数据；接接口后换成真实项目/卷/章/镜/要素列表）。
 * 卷→章→镜是级联的：下级按上级过滤，上级没选就给全量。 */
export const TAP_NO_VOLUME = '（不分卷）'
const PROJECTS = ['25 · 北境灯塔', '24 · 迷雾之城', '21 · 巡山探秘记']
const VOLUMES = [TAP_NO_VOLUME, '第一卷 · 港口风起', '第二卷 · 龙与灯塔']
const CHAPTERS: Record<string, string[]> = {
  [TAP_NO_VOLUME]: ['第一章 · 黄昏港口', '第二章 · 暴雨夜', '第三章 · 断桥', '第四章 · 点亮灯塔'],
  '第一卷 · 港口风起': ['第一章 · 黄昏港口', '第二章 · 暴雨夜'],
  '第二卷 · 龙与灯塔': ['第三章 · 断桥', '第四章 · 点亮灯塔'],
}
const SHOTS: Record<string, string[]> = {
  '第一章 · 黄昏港口': ['镜 1 · 远景码头', '镜 2 · 少年登船'],
  '第二章 · 暴雨夜': ['镜 1 · 雷雨海面', '镜 2 · 幼龙坠落'],
  '第三章 · 断桥': ['镜 1 · 断桥全景', '镜 2 · 晶纹特写', '镜 3 · 跨越'],
  '第四章 · 点亮灯塔': ['镜 1 · 塔顶信号室', '镜 2 · 灯光刺破夜色'],
}
// 要素按类型分三个独立参数（角色/场景/道具），各自的候选互不混淆
const CHARACTERS = ['守塔人 · 老阿蒙', '少年 · 里恩', '幼龙 · 晶纹']
const SCENES = ['灯塔顶层信号室', '黄昏港口', '断桥与龙骨峡谷']
const PROPS = ['铜制灯座', '棱镜灯芯', '龙鳞护符']

/** 按已选上级算某个 ctx 参数的可选项（params=开始节点当前全部入参） */
export function ctxOptions(ctx: TapCtxKey, params: TapParam[]): string[] {
  const val = (c: TapCtxKey) => params.find(p => p.ctx === c)?.v ?? ''
  if (ctx === 'project_id') return PROJECTS
  if (ctx === 'volume_id') return VOLUMES
  if (ctx === 'chapter_id') {
    // 卷留空 = 项目不分卷，直接给全部章
    const vol = val('volume_id')
    return CHAPTERS[vol && vol !== TAP_NO_VOLUME ? vol : TAP_NO_VOLUME] ?? []
  }
  if (ctx === 'shot_id') {
    const ch = val('chapter_id')
    return ch ? SHOTS[ch] ?? [] : Object.values(SHOTS).flat()
  }
  if (ctx === 'character_id') return CHARACTERS
  if (ctx === 'scene_id') return SCENES
  return PROPS
}

/** 改一个入参的值：级联下级若已失效（不在新可选项里）就一并清空——
 * 换了卷还留着旧卷的章、换了章还留着旧章的镜，跑起来必然对不上。 */
export function setParamValue(params: TapParam[], k: string, v: string): TapParam[] {
  const next = params.map(p => p.k === k ? { ...p, v } : p)
  const changed = params.find(p => p.k === k)
  if (changed?.type !== 'ctx') return next
  // 级联清空只看卷/章/镜这条链：要素（角色/场景/道具）挂在项目下，不随章镜变
  const order = TAP_CTX_ORDER.slice(0, 4)
  const from = order.indexOf(changed.ctx as TapCtxKey)
  if (from < 0) return next
  return next.map(p => {
    if (p.type !== 'ctx' || !p.ctx) return p
    const at = order.indexOf(p.ctx)
    if (at <= from || !p.v) return p
    return ctxOptions(p.ctx, next).includes(p.v) ? p : { ...p, v: '' }
  })
}

/** 「+」能加的入参种类（对齐 agentflow 的 PARAM_KINDS）。
 * 卷/章/镜分三项各自可加：只要章就只加章，要定位到镜就三项都加。 */
export const TAP_PARAM_KINDS: TapParam[] = [
  { k: 'project_id', label: '项目', type: 'ctx', ctx: 'project_id', required: true, v: '' },
  { k: 'volume_id', label: '卷', type: 'ctx', ctx: 'volume_id', v: TAP_NO_VOLUME },
  { k: 'chapter_id', label: '章', type: 'ctx', ctx: 'chapter_id', required: true, v: '' },
  { k: 'shot_id', label: '镜', type: 'ctx', ctx: 'shot_id', required: true, v: '' },
  { k: 'character_id', label: '角色', type: 'ctx', ctx: 'character_id', required: true, v: '' },
  { k: 'scene_id', label: '场景', type: 'ctx', ctx: 'scene_id', required: true, v: '' },
  { k: 'prop_id', label: '道具/素材', type: 'ctx', ctx: 'prop_id', required: true, v: '' },
  { k: 'text_var', label: '文本', type: 'text', v: '' },
  { k: 'int_var', label: '数字', type: 'int', v: '' },
  { k: 'json_var', label: 'JSON', type: 'json', v: '' },
  { k: 'image_var', label: '图片', type: 'image', v: '' },
  { k: 'video_var', label: '视频', type: 'video', v: '' },
]

export type TapEdgeMapping = 'auto' | 'each' | 'collect'
export interface TapConditionClause {
  left: string
  operator: 'truthy' | 'equals' | 'not_equals' | 'contains' | 'empty'
  right?: unknown
}
export interface TapConditionBranch {
  id: string
  kind: 'if' | 'else_if' | 'else'
  clauses?: TapConditionClause[]
}
export interface TapEdge { id: string; from: string; to: string; mapping?: TapEdgeMapping; branch?: string }

export interface TapCanvasData { nodes: TapNode[]; edges: TapEdge[] }


// ═══ 运行态（≈最终 tapflow-canvas）：自由画布 + 右侧 AI 对话 ═══
// 图片/视频节点统一宽 460，h = 460 × 原图纵横比（仅作连线锚点，渲染高度由图片自适应）
export const RUN_DATA: TapCanvasData = {
  nodes: [
    { id: 'hero', type: 'image', title: '男主.jpeg', x: 80, y: 130, w: 460, h: 460, src: pic('tap-hero', 480, 480) },
    { id: 'lady', type: 'image', title: '女眷.png', x: 40, y: 700, w: 460, h: 460, src: pic('tap-lady', 480, 480) },
    { id: 'yayi', type: 'image', title: '衙役.png', x: 620, y: 920, w: 460, h: 498, src: pic('tap-yayi', 480, 520) },
    {
      id: 'cart', type: 'image', title: 'Image', x: 700, y: 400, w: 460, h: 253, src: pic('tap-cart', 800, 440), starred: true,
      gen: {
        refs: [pic('tap-hero', 96, 96), pic('tap-lady', 96, 96)],
        prompt: '帮我生成一张一辆破旧的马车，背景是穿过盐荒地的过程中。大家闺秀在车上睡过去了，现代女主穿越到古代附身在这个人身上。醒过来后被衙役玩弄。就是需要这样一辆车，包含三视图',
        model: 'Seedream 4.0', params: ['自适应(4K)'],
      },
    },
    { id: 'txt', type: 'text', title: 'Text', x: 1420, y: 180, w: 320, h: 330 },
    { id: 'vid', type: 'video', title: 'Video', x: 1360, y: 640, w: 460, h: 259 },
  ],
  edges: [
    { id: 'e1', from: 'hero', to: 'cart' }, { id: 'e2', from: 'lady', to: 'cart' },
    { id: 'e3', from: 'yayi', to: 'vid' }, { id: 'e4', from: 'cart', to: 'txt' },
    { id: 'e5', from: 'cart', to: 'vid' },
  ],
}

// ═══ 编排态（tapflow）：Workflow 分组 + 更多节点 + 整组执行 ═══
const WF_TEXT_1 = '《图析递进》\n· 剧情递进关系：镜后2镜、左右X轴、上下Y轴\n· 剧情递进构图：影调构图\n· 剧情本身镜头（张力）：色阶、背景虚化\n核心模型：稳机三维坐标系 + 镜头逻辑公式：一个镜头 = [叙事距离] + [Y轴情境] + [X轴方位] + [特殊属性] 第一维度：Z轴——距离与信息量 (Distance & Scale) 逻辑定义：稳机与被摄主体的距离，决定了画面中是"看清什么"还是"看清世界"。'
const WF_TEXT_2 = '[分镜16] 29 大远景 (交代环境) + Y6 俯视 (第三视角) + 海面 (推处) + 广角镜头 (强化空间透视，展示斗兽场巨大的压迫感与斗士走进场内的孤独感)\n[分镜17] 21 大特写 (探索感觉) + Y4 平视 (平等视线)'
const WF_TEXT_3 = '斗兽场的勇士牌斗，凶悍，充满张力'

export const FLOW_DATA: TapCanvasData = {
  nodes: [
    // 首尾是每张流程都有的固定节点：开始（入参）与 next（回写通知）
    {
      id: 'start', type: 'start', title: '开始', x: -520, y: 1080, w: 560, h: 460,
      project: TAP_PROJECT_INFO,
      params: [
        { k: 'project_id', label: '项目', type: 'ctx', ctx: 'project_id', required: true, v: '25 · 北境灯塔' },
        { k: 'volume_id', label: '卷', type: 'ctx', ctx: 'volume_id', v: '第二卷 · 龙与灯塔' },
        { k: 'chapter_id', label: '章', type: 'ctx', ctx: 'chapter_id', required: true, v: '第三章 · 断桥' },
        { k: 'shot_id', label: '镜', type: 'ctx', ctx: 'shot_id', required: true, v: '镜 1 · 断桥全景' },
      ],
      outputs: [
        { k: 'shot_id', label: '镜', type: 'ctx', ctx: 'shot_id', v: '' },
        { k: 'shot_brief', label: '镜级设定', type: 'text', v: '' },
      ],
    },
    { id: 't1', type: 'text', title: 'Text', x: 40, y: 900, w: 320, h: 380, text: WF_TEXT_1 },
    { id: 't2', type: 'text', title: 'Text', x: 60, y: 1400, w: 300, h: 160, text: WF_TEXT_3 },
    { id: 't3', type: 'text', title: 'Text', x: 440, y: 1080, w: 320, h: 320, text: WF_TEXT_2 },
    { id: 'u1', type: 'upload', title: '上传图片', x: 430, y: 1520, w: 460, h: 273, done: true, src: pic('tap-arena', 640, 380) },
    { id: 'i1', type: 'image', title: 'Image', x: 1020, y: 0, w: 460, h: 273, src: pic('tap-w1', 640, 380) },
    { id: 'i2', type: 'image', title: 'Image', x: 1020, y: 360, w: 460, h: 273, done: true, src: pic('tap-w2', 640, 380) },
    { id: 'i3', type: 'image', title: 'Image', x: 1020, y: 720, w: 460, h: 273, done: true, src: pic('tap-w3', 640, 380) },
    { id: 'i4', type: 'image', title: 'Image', x: 1020, y: 1080, w: 460, h: 273, done: true, src: pic('tap-w4', 640, 380) },
    {
      id: 'i5', type: 'image', title: 'Image', x: 1020, y: 1440, w: 460, h: 273, done: true, src: pic('tap-lion', 640, 380),
      gen: {
        refs: [pic('tap-w2', 96, 96), pic('tap-w3', 96, 96), pic('tap-w4', 96, 96), pic('tap-lion', 96, 96), pic('tap-w6', 96, 96)],
        prompt: '根据图片先后顺序生成一部电影大片',
        model: 'Kling O1', params: ['16:9', '自适应', '10s'],
      },
    },
    { id: 'i6', type: 'image', title: 'Image', x: 1020, y: 1800, w: 460, h: 273, done: true, src: pic('tap-w6', 640, 380) },
    { id: 'g1', type: 'gen', title: '图片生成', x: 1020, y: 2160, w: 460, h: 273, done: true, src: pic('tap-w7', 640, 380) },
    { id: 'i7', type: 'image', title: 'Image', x: 1020, y: 2520, w: 460, h: 273, done: true, src: pic('tap-w8', 640, 380) },
    { id: 'i8', type: 'image', title: 'Image', x: 1020, y: 2880, w: 460, h: 273, src: pic('tap-disc', 640, 380) },
    {
      id: 'v1', type: 'video', title: 'Video', x: 1720, y: 1000, w: 460, h: 259, done: true,
      src: pic('tap-v1', 640, 360), video: 'https://www.w3schools.com/html/mov_bbb.mp4',
    },
    {
      id: 'v2', type: 'video', title: 'Video', x: 1700, y: 2320, w: 460, h: 259, done: true,
      src: pic('tap-v2', 640, 360), video: 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4',
    },
    { id: 'light', type: 'gen', title: '打光', x: 1720, y: 1700, w: 460, h: 420, status: 'generating' },
  ],
  edges: [
    { id: 'e0a', from: 'start', to: 't1' }, { id: 'e0b', from: 'start', to: 't2' },
    { id: 'e0c', from: 'start', to: 'u1' },
    { id: 'e1', from: 't1', to: 't3' }, { id: 'e2', from: 't2', to: 't3' },
    { id: 'e3', from: 't3', to: 'i1' }, { id: 'e4', from: 't3', to: 'i2' },
    { id: 'e5', from: 't3', to: 'i3' }, { id: 'e6', from: 't3', to: 'i4' },
    { id: 'e7', from: 't3', to: 'i5' }, { id: 'e8', from: 't3', to: 'i6' },
    { id: 'e9', from: 't3', to: 'g1' }, { id: 'e10', from: 't3', to: 'i8' },
    { id: 'e11', from: 'u1', to: 'i2' }, { id: 'e12', from: 'u1', to: 'i4' },
    { id: 'e13', from: 'u1', to: 'i5' }, { id: 'e14', from: 'u1', to: 'i7' },
    { id: 'e15', from: 'i2', to: 'v1' }, { id: 'e16', from: 'i3', to: 'v1' },
    { id: 'e17', from: 'i4', to: 'v1' }, { id: 'e18', from: 'i5', to: 'v1' },
    { id: 'e19', from: 'i6', to: 'v2' }, { id: 'e20', from: 'g1', to: 'v2' },
    { id: 'e21', from: 'i7', to: 'v2' },
    { id: 'e22', from: 'u1', to: 'light' },
  ],
}

/** 画幅比例的取值集合：生成条上的比例项由**项目设定**决定，不是节点自己写死的 */
export const TAP_ASPECTS: string[] = ['16:9', '9:16']
const HIDDEN_AUTO_PARAMS = new Set(['自适应', '自适应(4K)'])

/** 画风取第一个分句，长了截断——生成条只需要认出是哪种画风，全文在开始节点卡上 */
function styleShort(s: string): string {
  const head = (s || '').split(/[；;，,。]/)[0].trim()
  return head.length > 12 ? head.slice(0, 12) + '…' : head
}

/** 从项目设定继承到生成条上的参数项（比例 + 画风）。
 * 不加「画风 ·」这类前缀——参数条上一眼就看得出是什么，加了只是噪音。 */
export function projectParams(project?: TapProjectInfo): string[] {
  if (!project) return []
  const style = styleShort(project.artStyle)
  return [project.aspect, ...(style ? [style] : [])]
}

/** 把生成条上的**画幅比例与画风**换成本次运行所在项目的设定。
 *
 * 这两样都不是节点自己的属性，是项目的：后端出图本来就按项目比例算尺寸
 * （16:9→2560x1440，9:16→1440x2560），画风也按项目 art_style 召回画风块进 anchor 段。
 * 生成条写死「自适应」等于把这个事实藏起来——必须跟着开始节点的项目走。 */
export function withProjectParams(gen: NonNullable<TapNode['gen']>,
                                  project?: TapProjectInfo): NonNullable<TapNode['gen']> {
  const inherited = projectParams(project)
  // 先去掉上一轮继承进来的项和旧版本的“自适应”展示标签，避免反复叠加。
  const rest = (gen.params ?? []).filter(p => !inherited.includes(p)
    && !TAP_ASPECTS.includes(p) && !HIDDEN_AUTO_PARAMS.has(p))
  return { ...gen, params: [...inherited, ...rest] }
}

/** 文本节点的输出合同。**不是可选的装饰**：llm 节点在引擎里永远返回 {text:…}
 * （workflow._run_llm_node），画布不声明的话 upstreamVars 看不见它，下游工具入参的
 * 「关联上游」和提示词里的 @ 引用就都挑不到这个节点——节点跑出了东西却没人能引用。
 * 与工具节点同理：输出来自合同，不由用户手填，也不写回 graph（每次按类型推出来）。 */
export const textOutputs = (): TapParam[] => [
  { k: 'text', label: '正文', type: 'text', v: '' },
]

/** 节点未配置 gen 时的默认生成条（按类型给模型/参数）。
 * 文本/质检产出的是文字，不该出现画幅、分辨率这类画面参数。 */
export function defaultGen(type: TapNodeType): NonNullable<TapNode['gen']> {
  if (type === 'text' || type === 'qc') {
    return { refs: [], prompt: '', model: '全能文本模型 3 Pro', params: [] }
  }
  if (type === 'video') {
    return { refs: [], prompt: '', model: 'Kling O1', params: ['16:9', '10s'] }
  }
  if (type === 'flow') {
    // 引用卡不自己出图，模型由子流程各节点自己定；这里显示的是「谁来排这次生成」。
    return { refs: [], prompt: '', model: '智能调用规划', params: [] }
  }
  if (type === 'audio') {
    return { refs: [], prompt: '', model: 'Tap Audio', params: [] }
  }
  return { refs: [], prompt: '', model: 'Seedream 4.0', params: [] }
}

// ═══ 新建节点（+ 号 / 端口拖出菜单选类型后落到画布） ═══
/** 挂载点的可选归宿：与后端资产类型注册表（backend/app/assets）一一对应。
 * subject 说明该归宿要不要绑业务对象：项目封面绑项目、角色/场景绑要素、镜绑内容节点、
 * 通用素材不绑（subject=none）。 */
/** 挂载点可选归宿清单（画布 UI 侧）。与后端注册表（app/services/mount_targets.py）
 * 一一对应——后端测试有对齐校验：清单里每个码注册表必须有、subject 必须一致。
 * media 是该归宿要的产物形态：连线即落库时据此从源节点取 src（图）还是 video（视频）。 */
export const MOUNT_TARGETS: Array<{
  v: string; label: string; subject: 'project' | 'element' | 'content_node' | 'none'
  media: 'image' | 'video' | 'text'
}> = [
  { v: 'project_cover', label: '项目封面', subject: 'project', media: 'image' },
  { v: 'project_trailer', label: '项目预告片', subject: 'project', media: 'video' },
  { v: 'pro.character.sheet', label: '角色设定图', subject: 'element', media: 'image' },
  { v: 'pro.scene.sheet', label: '场景设定图', subject: 'element', media: 'image' },
  { v: 'pro.prop.sheet', label: '道具设定图', subject: 'element', media: 'image' },
  { v: 'pro.scene.brief', label: '场景介绍', subject: 'element', media: 'text' },
  { v: 'pro.shot.keyframe', label: '镜头关键帧', subject: 'content_node', media: 'image' },
  { v: 'pro.shot.script', label: '分镜脚本', subject: 'content_node', media: 'text' },
  { v: 'pro.shot.video', label: '镜头视频', subject: 'content_node', media: 'video' },
  { v: 'com.image', label: '通用图片', subject: 'none', media: 'image' },
  { v: 'com.video', label: '通用视频', subject: 'none', media: 'video' },
]

export const mountTargetLabel = (v?: string) =>
  MOUNT_TARGETS.find(t => t.v === v)?.label ?? (v || '未声明归宿')

/** 该归宿要的产物形态：'text' 没有可连线落库的 url（走运行内落库） */
export const mountTargetMedia = (v?: string): 'image' | 'video' | 'text' =>
  MOUNT_TARGETS.find(t => t.v === v)?.media ?? 'image'

/** 画布角色（后端 workflows.canvas_role）→ 默认挂载归宿。
 * 从角色页点进来，画布结尾就应该是「角色设定图」挂载点，而不是让用户自己去选；
 * 封面入口同理。取冒号前的段匹配（role 形如 scene.sheet:img / core-element.image:探索者）。 */
export const CANVAS_ROLE_MOUNT: Array<{ prefix: string; target: string }> = [
  { prefix: 'project.cover', target: 'project_cover' },
  { prefix: 'scene.sheet', target: 'pro.scene.sheet' },
  { prefix: 'character.sheet', target: 'pro.character.sheet' },
  { prefix: 'prop.sheet', target: 'pro.prop.sheet' },
  { prefix: 'scene.brief', target: 'pro.scene.brief' },
  { prefix: 'shot.keyframe', target: 'pro.shot.keyframe' },
  { prefix: 'shot.script', target: 'pro.shot.script' },
  { prefix: 'shot.video', target: 'pro.shot.video' },
  { prefix: 'project.trailer', target: 'project_trailer' },
  { prefix: 'core-element.image', target: 'com.image' },
]

export function mountTargetForCanvasRole(role?: string | null): string | null {
  const raw = String(role ?? '').split(':')[0].trim()
  if (!raw) return null
  return CANVAS_ROLE_MOUNT.find(r => raw === r.prefix || raw.startsWith(r.prefix + '.'))?.target
    ?? null
}

const NODE_PRESET: Record<TapNodeType, { w: number; h: number; title: string }> = {
  text: { w: 460, h: 280, title: 'Text' },
  image: { w: 460, h: 273, title: 'Image' },
  video: { w: 460, h: 259, title: 'Video' },
  audio: { w: 460, h: 140, title: 'Audio' },
  upload: { w: 460, h: 273, title: '参考图' },
  gen: { w: 460, h: 273, title: '图片生成' },
  start: { w: 320, h: 200, title: '开始' },
  qc: { w: 132, h: 132, title: '检查员' },
  link: { w: 320, h: 150, title: '关联' },
  flow: { w: 340, h: 170, title: '工作流' },
  tool: { w: 460, h: 280, title: '工具' },
  condition: { w: 380, h: 180, title: '选择器' },
  loop: { w: 460, h: 273, title: '逐项运行' },
  mount: { w: 460, h: 273, title: '挂载点' },
}
/** 挂载点尺寸规范（2026-09-18 视觉定稿）：挂载点是画布链路的**终点/归宿**，
 * 要比上游连线节点明显大一号——宽高取最近一根入边来源节点的 **1.5 倍**
 * （至少保持默认尺寸），且**中心点不动**（卡片对称变大，不遮上游、不偏离原位）。
 *
 * 尺寸写实进节点数据而不是只在渲染层放大：连线端点、框选命中、工具条定位
 * 全部按 node.w/node.h 计算，渲染层单独放大会让这些几何全部错位。
 * 手动缩放过（manualSize）的挂载点尊重用户意图，不重算。
 *
 * 返回 null = 无需变化（调用方据此避免多余 setState）。 */
export function syncMountSizes(nodes: TapNode[], edges: TapEdge[]): TapNode[] | null {
  const byId = new Map(nodes.map(n => [n.id, n]))
  let changed = false
  const out = nodes.map(n => {
    if (n.type !== 'mount' || n.manualSize) return n
    // 参照物 = 最近一根入边（edges 尾部最新）的来源节点——「上个连线节点」
    let upstream: TapNode | undefined
    for (let i = edges.length - 1; i >= 0; i--) {
      const e = edges[i]
      if (e.to !== n.id) continue
      const u = byId.get(e.from)
      if (u) { upstream = u; break }
    }
    const w = upstream ? Math.max(NODE_PRESET.mount.w, Math.round(upstream.w * 1.5)) : n.w
    const h = upstream ? Math.max(NODE_PRESET.mount.h, Math.round(upstream.h * 1.5)) : n.h
    if (w === n.w && h === n.h) return n
    changed = true
    return { ...n, x: Math.round(n.x + (n.w - w) / 2), y: Math.round(n.y + (n.h - h) / 2), w, h }
  })
  return changed ? out : null
}

let newSeq = 0
/** 新节点 id：**必须跨会话唯一**。原来是 `new-1`、`new-2` 计数器，存过一次之后原来是 `new-1`、`new-2` 计数器，存过一次之后
 * 下次打开画布再拖一个，又叫 `new-1` —— 与库里那个撞 id，保存时 validate_graph
 * 直接判「id 重复」，整张图存不下去。加时间戳基数即可，肉眼也还认得出是新节点。 */
const newId = () => `n${Date.now().toString(36)}${(++newSeq).toString(36)}`

/** 以 (x, y) 为竖直中心新建一个空节点。
 *
 * 「落下来就能跑」是这里的目标：出图类节点直接绑上自由出图执行体（gen_canvas_image：
 * 生成条里的提示词 + 上游连进来的图当参考 → 出一张图 → 落项目附件）。
 * 不给默认执行体的话，拖出来的卡片是个跑到它必报错的空壳——那就是"毫无作用"。
 * 视频绑自由出视频执行体（gen_canvas_video，2026-09-18 补，与自由出图同构：提示词 +
 * 上游首/尾帧 → 一段视频 → 落项目附件）；
 * 音频仍不给默认：现成的执行体焊在镜级上下文里，随手绑上只会跑一半才炸。 */
export function newTapNode(type: TapNodeType, x: number, y: number): TapNode {
  const p = NODE_PRESET[type]
  const n: TapNode = {
    id: newId(), type, title: p.title, x, y: y - p.h / 2, w: p.w, h: p.h, custom: true,
  }
  // 质检节点新建即带默认判据与未运行状态，落到画布上就是个完整可用的圆点
  if (type === 'qc') n.qc = { state: 'idle', rule: TAP_QC_RULES[0] }
  if (type === 'condition') n.condition = {
    branches: [
      { id: 'if-1', kind: 'if', clauses: [{ left: '', operator: 'truthy' }] },
      { id: 'else', kind: 'else' },
    ],
  }
  if (type === 'image' || type === 'gen') {
    n.bind = { step: TAP_CANVAS_IMAGE_STEP, onlyMissing: true }
    n.gen = defaultGen(type)
  }
  if (type === 'video') {
    n.bind = { step: TAP_CANVAS_VIDEO_STEP, onlyMissing: true }
    n.gen = defaultGen(type)
  }
  if (type === 'text') {
    n.bind = { mode: 'llm', charter: '', skills: [], kb: [], tools: [] }
    n.outputs = textOutputs()
  }
  if (type === 'tool') { n.tool = {}; n.params = []; n.outputs = [] }
  // 挂载点新建为「待选归宿」：卡面上直接列出可选归宿、点选即绑定；
  // 不再默认项目封面——归宿是用户要做的决定，不该替他选。
  if (type === 'mount') n.mount = { target: '' }
  return n
}

// ═══ 单场景设定图（四节点形态，见 docs/report-scene-flow-redesign-2026-08-01.md）═══
//   开始（只定位，不填内容）→ 场景介绍（LLM，缺才跑）→ 场景设定图（图片 LLM =
//   装配 + 质检 + 出图，三合一）→ 挂载点（产物归宿，落库由挂载点声明）
// 开始节点不再有「场景说明」与「参考图」入参：说明是**产物**不是入参（由场景介绍节点生成）；
// 参考图有两个正当来源——要素已有的 extra_refs、画布上游连进来的图片节点，不该手填。
export const SCENE_FLOW_DATA: TapCanvasData = {
  nodes: [
    {
      // project / params[].v 是**运行态**才有的东西（编排是项目无关模板）；
      // 这里预置成「已从业务页面点入」的运行现场，方便切到运行态直接看效果
      id: 'start', type: 'start', title: '开始', x: 40, y: 220, w: 560, h: 380,
      project: TAP_PROJECT_INFO,
      params: [
        { k: 'project_id', label: '项目', type: 'ctx', ctx: 'project_id', v: '25 · 北境灯塔' },
        { k: 'chapter_id', label: '章', type: 'ctx', ctx: 'chapter_id', v: '第三章 · 断桥' },
        { k: 'scene_id', label: '场景', type: 'ctx', ctx: 'scene_id', required: true, v: '灯塔顶层信号室' },
        // 没选项目时顶替故事线/文风：项目是设定的来源，没项目就得由人给整体设定
        { k: TAP_OVERALL_KEY, label: '整体设定', type: 'text', v: '' },
      ],
      outputs: [
        { k: 'scene_id', label: '场景', type: 'ctx', ctx: 'scene_id', v: '' },
        { k: 'element_id', label: '要素 ID', type: 'int', v: '' },
      ],
    },
    {
      id: 'brief', type: 'text', title: '场景介绍', x: 660, y: 200, w: 360, h: 300,
      bind: {
        mode: 'llm',
        charter: '你是世界观设定师。根据场景名与所在章节，写一段场景详细介绍：'
          + '空间格局、材质与光照、时段与氛围、可供表演的关键道具。只写场景，不写人物。',
        skills: ['场景空间连续性'],
        kb: ['画风库'],
        tools: ['project.info'],
        onlyMissing: true,
        refs: [
          { kind: 'ctx', label: '项目', token: '{{ctx.project_id}}', type: 'ctx' },
          { kind: 'node', label: '开始 · 场景', token: '{{开始.scene_id}}', type: 'text' },
          { kind: 'tool', label: 'chapter.info · 本章信息', token: '{{chapter.info}}', type: 'text' },
        ],
      },
      text: '（缺才跑：要素已有介绍就跳过，没有才让模型写一段）',
      params: [
        { k: 'scene', label: '场景', type: 'text', required: true, source: 'ref', ref: { node: 'start', k: 'scene_id' }, v: '' },
      ],
      outputs: [{ k: 'brief', label: '场景介绍', type: 'text', v: '' }],
    },
    {
      // 图片 LLM：装配 + 质检 + 出图三合一。对用户是一件事（「给我出这张图」），
      // 拆开只会让画布变成流程图而不是创作台
      id: 'gen', type: 'gen', title: '场景设定图', x: 1220, y: 180, w: 460, h: 273,
      bind: {
        step: 'gen_element_sheet', assemble: 'element.layers',
        mode: 'llm', onlyMissing: true,
        charter: '你是场景概念设计师：严格遵循项目画风与年代锚定，'
          + '大远景+中景双景别构图，画面中禁止出现人物与生物。',
        skills: ['画风一致性守则', '场景空间连续性'],
        kb: ['画风库', '场景设定图版式'],
        // 混排演示：文本引用出文本图标，图片引用出缩略图，上下文引用出上下文图标
        refs: [
          { kind: 'node', label: '场景介绍', token: '{{场景介绍.brief}}', type: 'text' },
          { kind: 'node', label: '参考图 · 灯塔外景', token: '{{参考图.url}}', type: 'image', thumb: pic('tap-ref-a', 96, 96) },
          { kind: 'node', label: '参考图 · 信号室内景', token: '{{参考图2.url}}', type: 'image', thumb: pic('tap-ref-b', 96, 96) },
          { kind: 'ctx', label: '项目', token: '{{ctx.project_id}}', type: 'ctx' },
        ],
        qc: {
          on: true, skill: '场景设定图质检 · 十维', kb: ['场景禁忌清单'],
          threshold: 80, stage: 'prompt', retry: 2,
        },
      },
      // 生成条里预填的是**装配出来的最终提示词**（这里是假数据；真实流程由
      // element.layers 三层装配后回填）。用户改一笔就冻结，之后装配不再覆盖
      gen: {
        refs: [], model: '系统出图模型', params: ['自适应(4K)'],
        prompt: '灯塔顶层信号室：铜制灯座与巨大棱镜，风暴夜里透出微光。'
          + '空间格局为八角形观测台，黄铜与玻璃材质在物理可信的光照下泛出暖光；'
          + '须贴合本项目世界观（北境海岛、云海、岩石、木船、金属与天气的材质和光照物理可信）。'
          + '强制纯场景多景别版式：同一地点必须同时包含一幅大远景全貌和一幅中景细部，'
          + '地点与空间关系是唯一主体；画面中无人物、无动物、无生物。'
          + '电影级奇幻写实动画画风，高品质渲染，细节丰富。',
      },
      params: [
        { k: 'brief', label: '场景介绍', type: 'text', required: true, source: 'ref', ref: { node: 'brief', k: 'brief' }, v: '' },
        { k: 'element_id', label: '要素 ID', type: 'int', source: 'ref', ref: { node: 'start', k: 'element_id' }, v: '' },
      ],
      outputs: [
        { k: 'sheet_url', label: '设定图', type: 'text', v: '' },
        { k: 'meta', label: '产物信息', type: 'json', v: '' },
      ],
    },
  ],
  edges: [
    { id: 'e1', from: 'start', to: 'brief' },
    { id: 'e2', from: 'brief', to: 'gen' },
  ],
}

// ═══ tapflow 列表（每个流程 = 一个智能体最小集 = 一个画布） ═══
// slug 有值 = 真实工作流（后端 graph 投影而来，运行走真实引擎）；无 = 本地演示假数据。
// 演示流程刻意保留：它是视觉/交互的对齐基准，真实流程的最终效果必须长成它这样。
export interface TapFlowMeta {
  id: string; name: string; desc: string; updated: string; data: TapCanvasData
  slug?: string; version?: number
  /** Instance canvases restore older run state from their source template too. */
  originSlug?: string
  /** 发布状态：published 的图保存时另存草稿版本，不原地改（它可能正被别的流程按
   * slug+version 引用，原地改会立刻影响在跑的运行） */
  status?: string
  /** 支持智能调用：这张流程被别的画布当节点引用时，卡片能炸开生成条，
   * 输入的提示词由大模型规划成「子图里哪几个节点重生成」。按 slug 全版本生效。 */
  smartCall?: boolean
  /** 打开时拉到的**原始 graph 与 input_schema**：保存要以它为底做合并，
   * 只覆盖画布能改的键，没投影的字段原样带回去（见 tapflowGraphWrite.toGraph） */
  raw?: {
    graph: { nodes: { id: string; type: string; config?: Record<string, unknown>
                      position?: { x: number; y: number } }[]
             edges: { from: string; to: string }[] }
    input_schema: Record<string, unknown>
  }
  /** 图里每个节点的坐标都是画布存过的（config.ui.xy）→ 挂载时不再整图重排，
   * 否则用户亲手拖的位置会被排版推回去 */
  placed?: boolean
  /** 已经是「某个业务对象的专属画布」（从模板 fork 出来的实例）。
   * 有值 = 编辑落进这份副本；没值 = 现在打开的是模板，首次改结构才 fork。 */
  subject?: { kind: string; id: number; canvasRole?: string }
  /** 节点 id → 文本节点直出的输出字段（来自 graph 的 config.ui.show） */
  show?: Record<string, string>
  /** 节点 id → 接收其产物的生成节点 id（config.ui.feeds）：出图提示词进图片的生成条 */
  feeds?: Record<string, string>
}

/** 前端概念验证：展示资产类型驱动的画布语义，不请求后端、不写入任何项目数据。 */
const colorPreview = (primary: string, accent: string, label: string) =>
  `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="#111827"/><rect x="0" y="0" width="426" height="360" fill="${primary}"/><rect x="426" y="0" width="214" height="360" fill="${accent}"/><rect x="42" y="246" width="322" height="58" rx="12" fill="rgba(255,255,255,.9)"/><text x="68" y="283" fill="#111827" font-family="Arial,sans-serif" font-size="26" font-weight="700">${label}</text></svg>`)}`

export const COLOR_ASSET_FLOW_DATA: TapCanvasData = {
  nodes: [
    {
      id: 'start', type: 'start', title: '颜色资产入口', x: 40, y: 220, w: 500, h: 320,
      project: TAP_PROJECT_INFO,
      params: [
        { k: 'project_id', label: '项目', type: 'ctx', ctx: 'project_id', required: true, v: '25 · 北境灯塔' },
        { k: 'asset_type', label: '资产类型', type: 'text', required: true, v: 'demo.color' },
        { k: 'asset_id', label: '颜色资产', type: 'text', required: true, v: '北境主色 · 雾青' },
      ],
      outputs: [{ k: 'asset', label: '颜色资产', type: 'json', v: '' }],
    },
    {
      id: 'resolve', type: 'text', title: '解析资产类型', x: 650, y: 180, w: 380, h: 250,
      text: 'demo.color → 颜色 Token\n查询：项目颜色集合\n能力：读取、生成色板、关联素材\n默认产物：color.palette',
      bind: { mode: 'query', tools: ['asset_type.resolve'] },
      params: [{ k: 'asset', label: '资产', type: 'json', required: true, source: 'ref', ref: { node: 'start', k: 'asset' }, v: '' }],
      outputs: [{ k: 'palette_spec', label: '色板规格', type: 'json', v: '' }],
    },
    {
      id: 'core', type: 'text', title: '获取核心颜色', x: 1100, y: 180, w: 380, h: 250,
      text: '主色：雾青 #0EA5A4\n强调色：琥珀 #F59E0B\n中性色：深墨 #111827\n动态子项按颜色类型路由',
      bind: { mode: 'llm', charter: '识别当前资产的核心颜色并输出结构化颜色描述。', skills: ['color-harmony'], tools: ['asset.query'] },
      outputs: [{ k: 'colors', label: '核心颜色', type: 'json', v: '' }],
    },
    {
      id: 'gen', type: 'gen', title: '生成颜色资产卡', x: 1580, y: 170, w: 460, h: 273,
      src: colorPreview('#0EA5A4', '#F59E0B', '北境 · 雾青 / 琥珀'), done: true,
      bind: {
        step: 'demo.generate_color_palette', mode: 'llm', outputSlot: { role: 'color.palette' },
        charter: '将核心颜色编排为项目可复用的颜色资产卡。', skills: ['color-harmony'], tools: ['asset.attach'],
      },
      gen: { refs: [], model: '演示模型', params: ['色板', '假数据'], prompt: '雾青主色、琥珀强调色、深墨中性色的项目颜色资产卡。' },
      params: [{ k: 'colors', label: '核心颜色', type: 'json', required: true, source: 'ref', ref: { node: 'core', k: 'colors' }, v: '' }],
      outputs: [{ k: 'palette_url', label: '颜色资产卡', type: 'text', v: '' }],
    },
    {
      id: 'link', type: 'link', title: '关联颜色资产', x: 2110, y: 225, w: 300, h: 150,
      link: { action: 'asset.attach_output', target: 'demo.color / color.palette' }, hideInRun: false,
    },
  ],
  edges: [
    { id: 'c1', from: 'start', to: 'resolve' }, { id: 'c2', from: 'resolve', to: 'core' },
    { id: 'c3', from: 'core', to: 'gen' }, { id: 'c4', from: 'gen', to: 'link' },
  ],
}

export const TAPFLOWS: TapFlowMeta[] = [
  {
    id: 'flow-color-asset-demo', name: '颜色资产 · 类型驱动演示',
    desc: '假数据演示：资产类型 → 核心颜色 → 颜色资产卡 → 类型化产物关联；不请求后端、不写入项目。',
    updated: '2026-08-02', data: COLOR_ASSET_FLOW_DATA,
  },
  {
    id: 'flow-scene-sheet', name: '单场景设定图',
    desc: '项目信息 + 画风 + 场景说明 → 场景要素入库 → 设定图 → 质检', updated: '2026-07-31 17:20', data: SCENE_FLOW_DATA,
  },
  {
    id: 'flow-shot-keyframe', name: '分镜关键帧-单镜',
    desc: '镜级文本设定 + 参考图 → 关键帧生成 → 视频合成', updated: '2026-07-30 18:42', data: FLOW_DATA,
  },
]

// ═══ Inspector 的画布语义常量 ═══
// 技能 / 知识库 / 工具的候选**不在这里**：唯一目录源是后端 `GET /api/agents/assets`，
// 见 lib/useTapflowCatalog.ts。写死数组一律不要——挑得再欢，跟引擎认的 slug /
// folder_id 对不上，存进 graph 就是跑不起来的配置（2026-08-01 收敛）。

/** 质检节点可选判据（画布上那颗圆点，定位是**跨节点批量抽检**，与节点内置自检不是一回事） */
export const TAP_QC_RULES = ['产物存在性', '提示词评分 ≥ 80', '画面质检（视觉模型）']
/** 「+ 引用」可选的运行上下文（运行时才有值，拼进 user 段） */
export const TAP_CTX_REFS: { label: string; token: string }[] = [
  { label: '项目', token: '{{ctx.project_id}}' },
  { label: '章', token: '{{ctx.chapter_id}}' },
  { label: '镜', token: '{{ctx.node_id}}' },
  { label: '要素', token: '{{ctx.element_id}}' },
]
// next 段的回写落点 / 通知去向**不做成可选目录**：真正落库的是执行体（Step.next），
// 画布上配的只会是一句展示文案，改了也不生效——跟被删掉的「引用最小集」同一个坑。
// 所以 next 节点如实回显 graph 里的 ui.next，只读。
