import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type ProjectAsset, type UnifiedReference, type WorkflowSubject } from '../../api'
import { clearChatInject, publishChatResult, pushChatInject, registerChatContributor,
  requestChatSend, unregisterChatContributor, type ChatContributor } from '../../lib/uiContext'
import type { ChatMsg } from '../../components/chat/chatTypes'
import { Modal } from '../../components/Modal'
import {
  isGenType, mountTargetForCanvasRole, mountTargetLabel, mountTargetMedia, newTapNode, setParamValue,
  syncMountSizes, visibleFlow, type TapEdge, type TapFlowMeta, type TapNode, type TapParam,
  type TapUpstreamVar,
} from '../../lib/tapflowData'
import { startInputs } from '../../lib/tapflowGraphAdapter'
import { canConnect } from '../../lib/tapflowEdges'
import { canvasChatContext, canvasChatScope } from '../../lib/tapflowChat'
import { useTapflowCtx } from '../../lib/useTapflowCtx'
import { useTapflowHistory } from '../../lib/useTapflowHistory'
import { useTapflowLastRun } from '../../lib/useTapflowLastRun'
import { useTapflowRun } from '../../lib/useTapflowRun'
import { layoutPositions } from '../../lib/tapflowLayout'
import type { TapFlowKind } from '../../lib/tapflowKind'
import { useTapflowAutosave } from '../../lib/useTapflowAutosave'
import { useTapflowSave } from '../../lib/useTapflowSave'
import { useTapflowSim } from '../../lib/useTapflowSim'
import { TapflowAutosaveBar } from './TapflowAutosaveBar'
import { TapflowCanvas } from './TapflowCanvas'
import { TapflowInspectorBody } from './TapflowInspectorBody'
import type { TapPromptSendMode } from './TapflowPromptBar'
import { TapflowRunBody } from './TapflowRunBody'
import { TapflowSaveBar } from './TapflowSaveBar'
import { TapflowSidePanel } from './TapflowSidePanel'
import './tapflow.css'

/** 没有开始节点时的空入参：常量身份，免得每次渲染都触发回填 effect */
const EMPTY_PARAMS: TapParam[] = []

/** 本次运行落在哪个要素上：关联落库节点（element.upsert）跑完会把 id 写进它的输出。
 * 重写提示词要带上要素设定，否则模型只能对着文字空转、不知道这张图画的是什么。 */
function elementIdOf(nodes: TapNode[]): number | undefined {
  for (const n of nodes) {
    for (const o of n.outputs ?? []) {
      if (o.k === 'id' && n.type === 'link' && o.v) return parseInt(o.v, 10) || undefined
    }
  }
  return undefined
}

/**
 * 单个 tapflow 流程的画布弹窗（全屏）：编排 ⇄ 运行切换 + 画布 + 右侧停靠面板。
 * 节点/连线状态在本容器持有（受控画布）——属性面板编辑、运行面板推进都直接回写。
 * flow.slug 有值 = 真实工作流：运行走后端引擎（async run + 轮询点亮），入参候选走真实上下文；
 * 无 slug = 演示假数据，运行走模拟。两者共用同一套画布组件——视觉效果对齐演示实现。
 */
export function TapflowModal({ flow, flows = [], initialInputs, variant = 'studio',
                               subject, productUrl, onFlow, onClose }: {
  flow: TapFlowMeta
  /** 生产态的画布归属对象（如素材库那个场景要素）。给了它就启用「专属画布」语义：
   * 改结构自动 fork 出这个对象的副本并持续自动保存，模板保持干净 */
  subject?: WorkflowSubject
  /** fork 之后把新的 flow 交回给持有方——**运行要跟着换 slug**，
   * 否则改动存进了副本，跑的还是模板 */
  onFlow?: (f: TapFlowMeta) => void
  /** 入口业务对象的当前产物（如项目现有封面）：入口归宿对应的挂载点进画布即回显它 */
  productUrl?: string
  /** studio=系统管理里的编排台（编排⇄运行、属性面板、保存发布俱全）；
   * production=业务页嵌入（如素材库点场景出图）：同一张画布，只是
   * 入参已按业务上下文填好、不给编排能力——没有属性面板、没有属性/新建按钮、
   * 不能切编排态。画布本体是同一个组件，差别只在外层给不给这些回调。 */
  variant?: 'studio' | 'production'
  /** 可被 subflow 节点引用的真实工作流（slug+version），来自列表页 */
  flows?: { slug: string; version: number; name: string; kind?: TapFlowKind }[]
  /** 业务入口带进来的入参预填（如素材库点某个场景 → project_id/scene_name）。
   * 键就是 input_schema 的键。定位类参数的候选是「25 · 标题」形式，
   * 但这里只要给裸 id 就行——加载到候选后会自动补成完整那条。 */
  initialInputs?: Record<string, string | number>
  onClose: () => void
}) {
  const real = !!flow.slug
  const prod = variant === 'production'
  // 编排台（系统管理 → tapflow 列表点开）**永远从编排态进**：从那个列表进来是来看/改
  // 这张图怎么编排的，不是来跑它的（真实流程也一样，别因为它能跑就默认落到运行态）。
  // 只有生产态（业务页嵌入）才是「进来就为跑一次」。
  const [mode, setMode] = useState<'edit' | 'run'>(prod ? 'run' : 'edit')
  // 进来一律不预先占掉半屏——右侧面板全部按需开。右侧只有两个角色：
  // 合并面板（属性|执行 两 tab）与对话面板（对话|任务队列），二者互斥
  const [dock, setDock] = useState<'panel' | null>(null)
  // 合并面板当前的 tab：属性（节点编排配置）/ 执行（参数 + 运行卡）。
  // 原运行面板的「日志」tab 已删除——日志由对话面板以运行折叠卡承载
  const [panelTab, setPanelTab] = useState<'props' | 'run'>('run')
  // 挂载点尺寸在投影源头就规范好（1.5 倍上游）：后续 autoLayout/整理都按真实尺寸排，
// 不会出现「先按 460 排好再放大 → 压到左列节点」的重叠
const [nodes, setNodes] = useState<TapNode[]>(
  () => syncMountSizes(flow.data.nodes, flow.data.edges) ?? flow.data.nodes)
  const [edges, setEdges] = useState<TapEdge[]>(flow.data.edges)
  const [selNode, setSelNode] = useState<TapNode | null>(null)
  const [selCtx, setSelCtx] = useState<{ upstream: TapUpstreamVar[] }>({ upstream: [] })

  // ── 入口默认挂载点（2026-09-17）：从角色页进来，画布结尾就该是「这个角色的
  // 图片挂载点」；从封面进来就是封面挂载点——归宿由入口的 canvas_role 决定，
  // 不再让用户自己去选。只在「该归宿还没有挂载点」时补一个，并接到链路末端：
  // 空挂牌没有意义，默认挂载点必须真的连在产物上。
  // 入口归宿（canvas_role → 挂载点归宿）：productUrl 只回显到这个归宿的挂载点上，
  // 别的挂载点不吃这份回显——那是别的归宿的产物
  const entryMount = useMemo(() => {
    const target = mountTargetForCanvasRole(subject?.canvasRole)
    return target && productUrl ? { target, url: productUrl } : undefined
  }, [subject, productUrl])
  const defaultMount = useRef('')
  useEffect(() => {
    if (!subject || subject.id === undefined) return
    const target = mountTargetForCanvasRole(subject.canvasRole)
    if (!target) return
    const sig = `${flow.slug ?? flow.id}|${target}|${subject.kind}:${subject.id}`
    if (defaultMount.current === sig) return
    defaultMount.current = sig
    if (nodes.some(n => n.type === 'mount' && n.mount?.target === target)) return
    const hasOut = new Set(edges.map(e => e.from))
    const tail = [...nodes].filter(n => n.type !== 'start' && !hasOut.has(n.id))
      .sort((a, b) => (b.x + b.w) - (a.x + a.w))[0]
    const x = tail ? tail.x + tail.w + 110 : 200
    const y = tail ? tail.y + 40 : 200
    const m = newTapNode('mount', x, y)
    m.mount = { target, subject: { kind: subject.kind, id: subject.id } }
    m.title = subject.name ? `${subject.name} 的挂载点` : `${mountTargetLabel(target)}挂载点`
    m.custom = false
    setNodes(ns => [...ns, m])
    if (tail) setEdges(es => [...es, { id: `e-${tail.id}-${m.id}`, from: tail.id, to: m.id }])
  }, [flow.slug, flow.id, subject, nodes, edges])
  // 忽略已有产物、范围内全部重出。默认关——缺才跑才是常态
  const [forceAll, setForceAll] = useState(false)
  // 运行范围：null 端点 = 流程默认。整图始终从前往后跑、默认缺才跑；
  // 范围只决定「从哪起强制重跑」与「跑到哪停」（见 lib/tapflowRunPlan）
  const [range, setRange] = useState<{ from: string | null; to: string | null }>({
    from: null, to: null,
  })
  const projectId = Number(initialInputs?.project_id) || undefined
  // 连线即落库（2026-09-18）：挂载点接上新上游的瞬间就把那张图写进归宿，
  // 不用等一次运行——用户连的常常是现有的图（素材/上传/历史产物），
  // 为存一张图白跑一遍模型说不通。落库走运行收尾同一条 apply_mount_binding，
  // 成功后把 url/version 回填到节点（运行回显同款字段，不进保存指纹）。
  // 空产物（连过来的 gen 还没跑出图）与落库失败都静默：编排继续，运行收尾还会补一次
  const onMountWire = useCallback(async (mountId: string, srcId: string) => {
    const m = nodes.find(n => n.id === mountId)
    const s = nodes.find(n => n.id === srcId)
    const target = m?.mount?.target
    // 按归宿要的产物形态取：视频归宿吃 video 字段，其余吃 src；拿不到（比如还没跑出图）就只记编排
    const url = (target && mountTargetMedia(target) === 'video' ? s?.video : s?.src) || undefined
    if (!m || !s || !url || !target || !flow.slug) return
    try {
      const stored = await api.storeMount(flow.slug, {
        project_id: projectId,
        target,
        subject: m.mount?.subject?.kind
          ? { kind: m.mount.subject.kind, id: m.mount.subject.id } : undefined,
        url, prompt: s.gen?.prompt ?? '', variant: m.mount?.variant,
      })
      if (stored.stored && stored.stored !== 'skipped') {
        setNodes(ns => ns.map(n => n.id === mountId
          ? { ...n, mount: { ...n.mount!, url, version: stored.version,
              unchanged: stored.unchanged, sourceNode: srcId } }
          : n))
      }
    } catch { /* 落库失败不打断编排；下次运行收尾还会补 */ }
  }, [nodes, flow.slug, projectId])
  // 业务参考是「某个业务对象的画布参考」：后端 content_reference_links 对任意
  // subject_kind 通用（shot 另有专属联动），画布层不再按 kind 限死——
  // 封面画布同样能从素材库拉参考并持久化，重开还在
  const unifiedSubject = !!subject && subject.id !== undefined
  const [businessRefs, setBusinessRefs] = useState<UnifiedReference[]>([])
  const reloadBusinessRefs = useCallback(async () => {
    if (!projectId || !unifiedSubject || subject?.id === undefined) return
    const rows = await api.listUnifiedReferences(projectId, subject.kind, subject.id, 'image')
    setBusinessRefs(rows.filter(r => r.enabled))
  }, [projectId, subject?.id, subject?.kind, unifiedSubject])
  useEffect(() => { void reloadBusinessRefs() }, [reloadBusinessRefs])
  const addBusinessRef = useCallback(async (asset: ProjectAsset) => {
    if (!projectId || !unifiedSubject || subject?.id === undefined) return
    await api.addUnifiedReference(projectId, {
      subject_kind: subject.kind, subject_id: subject.id, purpose: 'image',
      source_kind: asset.element_id ? 'element' : 'url', source_id: asset.element_id,
      snapshot: { name: asset.name, kind: asset.kind, url: asset.url },
    })
    await reloadBusinessRefs()
  }, [projectId, reloadBusinessRefs, subject?.id, subject?.kind, unifiedSubject])
  const removeBusinessRef = useCallback(async (referenceId: number) => {
    if (!projectId) return
    await api.deleteUnifiedReference(projectId, referenceId)
    await reloadBusinessRefs()
  }, [projectId, reloadBusinessRefs])

  // 运行要读「跑到这一步时」的最新画布状态——用 ref 透传，避免闭包旧值
  const stateRef = useRef({ nodes, edges })
  stateRef.current = { nodes, edges }
  const getState = useCallback(() => stateRef.current, [])
  const patchNode = useCallback((id: string, p: Partial<TapNode>) => {
    // A streamed edit may be followed immediately by run_node before React renders.
    stateRef.current = { ...stateRef.current,
      nodes: stateRef.current.nodes.map(n => n.id === id ? { ...n, ...p } : n) }
    setNodes(ns => ns.map(n => n.id === id ? { ...n, ...p } : n))
  }, [])
  const save = useTapflowSave(flow, subject, onFlow)
  const saveFlow = save.save
  // 生产态：拖出节点、挪位置、改配置——任何结构改动都自动落进「这个对象的专属画布」
  // （首次改动时从模板 fork）。编排台不自动存，那边是显式保存 + 发布两态
  useTapflowAutosave(prod && real && !!subject, nodes, edges, save.save)
  const sim = useTapflowSim(getState, patchNode)
  const live = useTapflowRun(
    flow.slug, flow.version, getState, patchNode, flow.show, flow.feeds, flow.originSlug)
  const setRuntimeProjectionNodes = live.setRuntimeProjectionNodes
  const eng = real ? live : sim
  const runtimeProjected = real && mode === 'run' && live.runtimeNodes.length > 0
  const rawCanvasNodes = useMemo(() => runtimeProjected
    ? [...nodes, ...live.runtimeNodes] : nodes,
  [runtimeProjected, nodes, live.runtimeNodes])
  const canvasEdges = useMemo(() => runtimeProjected
    ? [...edges.filter(e => !live.runtimeLoopOwners.includes(e.from)), ...live.runtimeEdges]
    : edges,
  [runtimeProjected, edges, live.runtimeLoopOwners, live.runtimeEdges])
  const [runtimePositions, setRuntimePositions] = useState<Record<string, { x: number; y: number }>>({})
  const runtimeSignature = `${live.projectionRevision}:` + live.runtimeNodes
    .map(n => `${n.id}:${n.title}:${n.w}x${n.h}`).join('|')
  const autoArrangedSignature = useRef<string | null>(null)
  const arrangeAll = useCallback((persist: boolean) => {
    const arrangedFlow = visibleFlow(rawCanvasNodes, canvasEdges, mode)
    const laidOut = layoutPositions(arrangedFlow.nodes, arrangedFlow.edges)
    // 每个循环拥有后一条独立扩展列；N 个实例纵向成组并与 owner 中线对齐。
    const positions = Object.fromEntries(rawCanvasNodes.flatMap(n => {
      const p = laidOut.get(n.id)
      return p ? [[n.id, p]] : []
    }))
    setRuntimePositions(positions)
    setRuntimeProjectionNodes(live.runtimeNodes.map(n => ({ ...n, ...(laidOut.get(n.id) ?? {}) })))
    const arrangedTemplate = nodes.map(n => {
      let p = laidOut.get(n.id)
      if (!p && live.runtimeLoopOwners.includes(n.id)) {
        const first = live.runtimeNodes.find(x => x.runtime?.loopOwner === n.id)
        if (first) p = laidOut.get(first.id)
      }
      return p ? { ...n, ...p } : n
    })
    // Production runtime projections are a transient view. Keep their layout
    // in runtimePositions so an execution cannot autosave a temporary reset
    // over the user's persisted canvas; studio and explicit relayouts still
    // update the template as before.
    if (!prod || persist) setNodes(arrangedTemplate)
    if (persist && prod && subject) void saveFlow(arrangedTemplate, edges)
  }, [rawCanvasNodes, canvasEdges, mode, live.runtimeNodes, live.runtimeLoopOwners,
    nodes, edges, prod, subject, saveFlow, setRuntimeProjectionNodes])
  useEffect(() => {
    if (!runtimeProjected) { setRuntimePositions({}); return }
    if (autoArrangedSignature.current === runtimeSignature) return
    autoArrangedSignature.current = runtimeSignature
    // 所有参数齐全、循环数量已经由预检解析后，只执行这一次全量重排。
    // 生产对象首次从模板进入时立即保存；已有专属画布以后不再自动重排。
    const firstProductionOpen = prod && !!subject && !flow.subject
    // Every runtime projection needs the reset layout rule. Only the first
    // production projection is persisted; later runs must remain transient.
    arrangeAll(firstProductionOpen)
  }, [runtimeProjected, runtimeSignature]) // eslint-disable-line react-hooks/exhaustive-deps
  const canvasNodes = useMemo(() => runtimeProjected
    ? rawCanvasNodes.map(n => runtimePositions[n.id] ? { ...n, ...runtimePositions[n.id] } : n)
    : rawCanvasNodes,
  [runtimeProjected, rawCanvasNodes, runtimePositions])
  // Pointer drag/resize handlers live for the whole gesture. In runtime mode they
  // must not keep applying functional updates to the render-time node snapshot.
  const canvasNodesRef = useRef(canvasNodes)
  canvasNodesRef.current = canvasNodes
  const changeCanvasNodes: React.Dispatch<React.SetStateAction<TapNode[]>> = useCallback(action => {
    if (!runtimeProjected) { setNodes(action); return }
    const next = typeof action === 'function' ? action(canvasNodesRef.current) : action
    // Advance synchronously so every pointermove accumulates from the preceding frame,
    // even before React has committed the projection state updates below.
    canvasNodesRef.current = next
    setRuntimePositions(Object.fromEntries(next.map(n => [n.id, { x: n.x, y: n.y }])))
    setRuntimeProjectionNodes(next.filter(n => !!n.runtime))
    // 运行投影允许拖动，但坐标只留在视图层；正文/提示词等真实编辑仍同步回模板节点。
    setNodes(cur => cur.map(n => {
      const changed = next.find(x => x.id === n.id)
      return changed ? { ...changed, x: n.x, y: n.y, runtime: undefined } : n
    }))
  }, [runtimeProjected, setRuntimeProjectionNodes])
  const patchVisibleNode = useCallback((id: string, patch: Partial<TapNode>) => {
    const runtime = canvasNodesRef.current.find(n => n.id === id)?.runtime
    canvasNodesRef.current = canvasNodesRef.current.map(n => n.id === id ? { ...n, ...patch } : n)
    if (runtime) {
      setRuntimeProjectionNodes(current => current.map(n => n.id === id ? { ...n, ...patch } : n))
      return
    }
    patchNode(id, patch)
  }, [patchNode, setRuntimeProjectionNodes])

  const start = nodes.find(n => n.type === 'start') ?? null
  const projVal = start?.params?.find(p => p.ctx === 'project_id')?.v
  const startAspect = start?.project?.aspect ?? ''
  const ctx = useTapflowCtx(real, projVal)
  // 一次填多个入参：逐个调 onParam 会互相覆盖（同一 tick 里 start.params 是同一份旧值）
  const applyParams = useCallback((vals: Record<string, string>) => {
    setNodes(ns => ns.map(n => n.type !== 'start' ? n : {
      ...n,
      // 后端规范解析已经一次性校验了整组上下文。这里必须原子回填，不能逐项调用
      // setParamValue：若 project_id 最后写入，旧级联会把同批刚写入的章/镜再次清空。
      params: (n.params ?? []).map(param => param.k in vals
        ? { ...param, v: vals[param.k] }
        : param),
    }))
  }, [])
  // 业务入口预填：**优先于**「上次运行参数」回填——用户是点着某个场景进来的，
  // 这次就该跑这个场景，不能被上一次跑别的场景的参数盖掉。
  const seeded = useRef(false)
  useEffect(() => {
    if (!initialInputs || seeded.current) return
    seeded.current = true
    applyParams(Object.fromEntries(
      Object.entries(initialInputs).map(([k, v]) => [k, String(v)])))
  }, [initialInputs, applyParams])
  // 定位类参数的候选是「25 · 标题」形式：候选到货后把裸 id 补成完整那条，
  // 否则下拉显示空白（值其实是对的，但看着像没选）
  useEffect(() => {
    if (!initialInputs || !real) return
    setNodes(ns => {
      let changed = false
      const next = ns.map(n => {
        if (n.type !== 'start') return n
        let paramsChanged = false
        const params = (n.params ?? []).map(p => {
          if (!p.ctx || !p.v || p.v.includes(' · ')) return p
          const { list } = ctx.optionsFor(p.ctx, n.params ?? [])
          const hit = list.find(o => parseInt(o, 10) === parseInt(p.v, 10))
          if (!hit || hit === p.v) return p
          paramsChanged = true
          return { ...p, v: hit }
        })
        if (!paramsChanged) return n
        changed = true
        return { ...n, params }
      })
      return changed ? next : ns
    })
  }, [initialInputs, real, ctx, ctx.optionsFor])
  // 打开画布就把上次运行的入参/范围/强制开关填回来（数据源 workflow_runs，不另存一份）。
  // 生产态**只回入参、不回范围**：上次可能是编排台里跑到某个节点为止的调试运行，业务用户点
  // 「生成场景设定图」要的是整条链跑完，继承那个 range 会让流程在半路停下——
  // 实测踩过：run 61 只跑到 brief 就 stopped_at，图根本没出。
  // 入参则该回：用户在开始表单改过的文本/图片变量是他对这张画布的输入意图，
  // 重开就丢等于白改；业务入口本次预填的键（如 ref_url）是现场，优先于历史值。
  const lastRun = useTapflowLastRun(
    real ? flow.slug : undefined, start?.params ?? EMPTY_PARAMS,
    real ? ctx.optionsFor : undefined,
    { params: applyParams, range: setRange, forceAll: setForceAll },
    prod ? { paramsOnly: true, excludeKeys: Object.keys(initialInputs ?? {}),
             requireProjectId: projectId } : undefined)
  const paramSig = (start?.params ?? []).map(p => p.v).join('|')
  // 打开画布就按节点分别恢复最近一次产物与质检结论。不能只跟最后一轮 run：
  // 分支节点可能是分几次单独生成的，最后一轮不包含其它分支。
  useEffect(() => {
    if (!real) return
    const currentInputs = startInputs(stateRef.current.nodes).inputs
    const startParamKeys = new Set(
      stateRef.current.nodes.find(node => node.type === 'start')?.params?.map(param => param.k) ?? [])
    // Production URL inputs are committed in the preceding effect. Waiting for
    // them prevents a refresh from restoring another project's global latest run.
    if (initialInputs && Object.keys(initialInputs)
      .some(key => startParamKeys.has(key) && currentInputs[key] == null)) return
    void live.restoreLatest()
  }, [real, flow.slug, paramSig])  // eslint-disable-line react-hooks/exhaustive-deps

  // 选中项目 → 开始节点带出项目设定卡
  useEffect(() => {
    if (real && start && start.project !== (ctx.project ?? undefined)) {
      patchNode(start.id, { project: ctx.project ?? undefined })
    }
  }, [real, ctx.project])  // eslint-disable-line react-hooks/exhaustive-deps
  // 入参齐了自动预检（零副作用）：回显已有产物，「缺才跑」在跑之前就看得见
  useEffect(() => {
    if (!real || mode !== 'run') return
    const t = setTimeout(() => void live.preview(), 600)
    return () => clearTimeout(t)
  }, [real, mode, paramSig, startAspect])  // eslint-disable-line react-hooks/exhaustive-deps

  // 编排态选中节点即展开属性（那时就是在配节点）；运行态只炸开节点自身的浮层，
  // 不抢右侧面板——运行时用户看的是产物与日志
  const onSelectNode = useCallback((n: TapNode | null, c: { upstream: TapUpstreamVar[] }) => {
    setSelNode(n)
    setSelCtx(c)
    // 2026-09-17：选中节点不再自动弹右侧属性面板——弹出来就是半屏，用户只是想看看节点。
    // 属性入口统一改为节点炸开上方工具条的「属性」icon，点击才开（再点收起）。
  }, [])
  // rail 上两个按钮各自带上它所属的模式：运行 → 运行态，属性 → 编排态。
  // 属性面板配的是「这个节点怎么生成」，那是编排态的事；在运行态开着它只会看到
  // 一堆改不动的配置。再点一次收起，不动模式。
  const openRun = useCallback(() => { setMode('run'); setPanelTab('run'); setDock('panel') }, [])

  // scope 对象用 useMemo 稳定化：ChatDock 的会话加载 effect 依赖它，
  // 字面量每次渲染都是新引用会把后端请求打爆
  const chatScope = useMemo(() => canvasChatScope(flow, subject, projectId),
    [flow, subject, projectId])

  // ── 画布上下文：对话 AI 每次提问时实时生成画布摘要（节点清单/入参/最近运行）。
  // 只在真实画布（real）下给——演示画布无后端对象可描述。模型引用节点时用 id，
  // 配合 ACTION focus_node 协议回传，前端就能定位到具体节点。 ──
  const buildCanvasContext = useCallback(() => {
    if (!real) return undefined
    const current = canvasNodesRef.current.filter(n => !n.runtime?.transient)
    const ctx = canvasChatContext(flow, current, stateRef.current.edges, selNode?.id)
    return lastRun ? `${ctx}\n最近运行：run #${lastRun.id}，状态 ${lastRun.status}，${lastRun.created_at?.slice(0, 16) ?? ''}` : ctx
  }, [real, flow, lastRun, selNode])

  // Text `text` is the visible artifact. Keep an AI rewrite instruction out
  // of that field until a run is explicitly requested.
  const pendingTextPrompts = useRef(new Map<string, string>())
  const textRewriteOnly = useRef(new Set<string>())
  const publishNodeResult = useCallback((nodeId: string) => {
    const n = stateRef.current.nodes.find(x => x.id === nodeId)
    if (!n) return
    const output = n.type === 'text' ? (n.text ?? '').trim() : n.runtimeResult?.summary?.trim() || ''
    const isVideo = n.type === 'video' || (n.type === 'gen' && n.modality === 'video')
    const mediaUrl = isVideo ? (n.video || n.src) : n.src
    if (!output && !mediaUrl) return
    // The assembled generator prompt is a useful result of the run and is
    // safe to show as user-facing output. System instructions and upstream
    // payloads remain in the hidden planner context and are never echoed.
    const generatedPrompt = isGenType(n.type) ? n.gen?.prompt?.trim() : ''
    const visible = [
      generatedPrompt ? `生成提示词：\n${generatedPrompt}` : '',
      output || `已完成「${n.title || n.type}」生成。`,
    ].filter(Boolean).join('\n\n')
    const nodeType = isVideo ? 'video' : n.type
    publishChatResult({ scope: chatScope, nodeKey: n.id, nodeTitle: n.title, nodeType,
      content: visible,
      ...(mediaUrl ? { mediaUrl } : {}) })
  }, [chatScope])

  // Mark planning as soon as the user presses send. The chat turn and its
  // model actions are still the source of truth for the actual run, but the
  // canvas must acknowledge the click immediately instead of waiting for the
  // first backend poll.
  const markNodePlanning = useCallback((nodeId: string) => {
    patchVisibleNode(nodeId, { stage: { label: 'Planning', tone: 'run' }, error: undefined })
  }, [patchVisibleNode])
  const markCanvasPlanning = useCallback(() => {
    for (const node of canvasNodesRef.current) {
      if (node.type === 'start' || node.type === 'upload' || node.runtime?.transient) continue
      patchVisibleNode(node.id, { stage: { label: 'Planning', tone: 'run' }, error: undefined })
    }
  }, [patchVisibleNode])

  // rail 主按钮「运行」：直接跑当前范围，**不开右侧面板**。
  // 参数在生产态已按业务上下文填好，再弹一次边栏让人确认纯属多一步。
  const runNow = useCallback(async () => { await eng.run(range, forceAll, { mode: 'all' }) }, [eng, range, forceAll])
  // 质检未通过 →「重新生成」：重写当前提示词后，立即强制重跑这一个节点。
  const [regenBusy] = useState(false) // 下发通道化后由对话面板展示进度，保留 prop 兼容旧签名
  const regen = useCallback((nodeId: string) => {
    // 「智能生成」统一走下发通道（与生成条发送一致）：指令进对话面板，
    // AI 改写提示词/正文后再执行——不再直接弹运行面板、不再前端直跑。
    // 文本节点的“提示词”就是正文本身（llm 指令）。
    const n = canvasNodesRef.current.find(x => x.id === nodeId)
    const cur = n?.gen?.prompt?.trim() || (n?.type === 'text' ? (n.text ?? '').trim() : '')
    // Production media nodes can assemble their instruction from hidden
    // upstream context, so an empty visible prompt is still runnable.
    const canRunWithoutPrompt = !!n && isGenType(n.type)
    if (!n || (!cur.trim() && !canRunWithoutPrompt)) {
      patchVisibleNode(nodeId, { error: '提示词为空，无法智能生成' })
      return
    }
    const mode: TapPromptSendMode = cur ? 'rewrite_generate' : 'on_demand'
    markNodePlanning(nodeId)
    requestChatSend(`\u6267\u884c\u8282\点\u300c${n.title || 'Current node'}\u300d`, {
      scope: chatScope,
      meta: { node_request: { node_key: nodeId, mode, prompt: cur },
        node_ref: { node_key: nodeId, title: n.title, type: n.type, mode } },
    })
  }, [patchVisibleNode, chatScope])
  // 生成条「发送」= **只重跑这一个节点**：范围两端都指向它 →
  // force=[它]、stop_after=它，前面的照旧缺才跑（只查、缺了才补）
  // 生成条发送 = **就按框里这段重新出图，且只跑这一个节点**。
  // 通用下发方案（2026-09-18）：发送不再弹属性/运行面板，而是把指令投递给
  // 对话面板自动发出——AI 流式规划（思考过程→改写提示词→执行生成）全程在
  // 对话区可见，运行日志同步回流。三种发送模式语义都写进指令文本，由
  // 后端规划模型用 update_node_prompt / run_node 动作落地。
  // via='chat'：AI 自己触发的节点运行（onChatAction.run_node）——本地确定性
  // 执行、不回注对话（否则 AI 动作→再发对话→再动作，死循环）。
  const runOne = useCallback(async (nodeId: string, sendMode: TapPromptSendMode,
                                   via: 'promptbar' | 'chat' = 'promptbar',
                                   promptOverride?: string) => {
    if (via === 'chat') {
      if (sendMode === 'on_demand') {
        patchVisibleNode(nodeId, { stage: { label: '执行中', tone: 'run' }, error: undefined })
        try {
          await eng.run({ from: nodeId, to: nodeId }, false, {
            mode: 'single', nodeId, verbatim: nodeId,
            ...(promptOverride?.trim() ? { promptOverride: promptOverride.trim() } : {}),
          })
          publishNodeResult(nodeId)
        } finally {
          patchVisibleNode(nodeId, { stage: undefined })
        }
        return
      }
      const n = canvasNodesRef.current.find(x => x.id === nodeId)
      // 文本节点的“提示词”就是正文本身（llm 指令），与媒体节点同一份优化语义
      const currentPrompt = n?.gen?.prompt?.trim() || (n?.type === 'text' ? (n.text ?? '').trim() : '')
      if (!n || !currentPrompt) {
        patchVisibleNode(nodeId, { error: '提示词为空，无法优化' })
        return
      }
      const runtimeElementId = Number(n.runtime?.sourceItem?.element_id)
      try {
        const rewritten = await api.qcRewrite({
          prompt: currentPrompt,
          element_id: Number.isFinite(runtimeElementId) && runtimeElementId > 0
            ? runtimeElementId : elementIdOf(stateRef.current.nodes),
          project_id: startInputs(stateRef.current.nodes).projectId,
          extra: '在不改变核心内容与系统护栏的前提下，主动优化叙事表达、镜头调度和画面可执行性。',
        })
        patchVisibleNode(nodeId, {
          gen: { ...(n.gen ?? { refs: [], prompt: '', model: '', params: [] }),
                 prompt: rewritten.prompt, edited: true },
          error: undefined,
        })
        if (sendMode === 'rewrite_only') return
        await eng.run({ from: nodeId, to: nodeId }, false, {
          mode: 'single', nodeId, verbatim: nodeId, promptOverride: rewritten.prompt,
        })
        publishNodeResult(nodeId)
      } catch (e) {
        patchVisibleNode(nodeId, { error: `提示词优化失败：${String(e)}` })
      }
      return
    }
    // promptbar 下发：不弹面板，指令进对话面板自动发送
    const n = canvasNodesRef.current.find(x => x.id === nodeId)
    const prompt = n?.gen?.prompt?.trim() || (n?.type === 'text' ? (n.text ?? '').trim() : '')
    // Some generation nodes (for example the core-element image node) build
    // their actual prompt from hidden upstream context at execution time.
    // They are still runnable when the visible prompt field is empty.
    const canRunWithoutPrompt = !!n && isGenType(n.type) && sendMode === 'on_demand'
    if (!n || (!prompt && !canRunWithoutPrompt)) {
      patchVisibleNode(nodeId, { error: '提示词为空，无法下发' })
      return
    }
    const title = n.title || 'Current node'
    const executionPrompt = prompt.trim()
    markNodePlanning(nodeId)
    if (sendMode !== 'on_demand') {
      requestChatSend(`\u6267\u884c\u8282\u70b9\u300c${title}\u300d`, {
        scope: chatScope,
        meta: {
          node_request: { node_key: nodeId, mode: sendMode, prompt: executionPrompt },
          node_ref: { node_key: nodeId, title, type: n.type, mode: sendMode },
        },
      })
      if (n.type === 'text' && sendMode === 'rewrite_only') textRewriteOnly.current.add(nodeId)
      return
    }
    // The conversation is the planner for a node request. Send immediately so
    // the user sees the turn; the backend then preserves this prompt for the
    // on-demand run (or rewrites it before running for the rewrite modes).
    requestChatSend(`\u6267\u884c\u8282\u70b9\u300c${title}\u300d`, {
      scope: chatScope,
      meta: {
        node_request: {
          node_key: nodeId, mode: sendMode, prompt: executionPrompt,
        },
        node_ref: { node_key: nodeId, title, type: n.type, mode: sendMode },
      },
    })
    // Demo canvases have no backend planner; preserve their local execution
    // while keeping the same immediate user-message behavior.
    if (!real && sendMode === 'on_demand') {
      void (async () => {
        patchVisibleNode(nodeId, { stage: { label: 'Executing', tone: 'run' }, error: undefined })
        try {
          await eng.run({ from: nodeId, to: nodeId }, false, {
            mode: 'single', nodeId, verbatim: nodeId,
            ...(executionPrompt ? { promptOverride: executionPrompt } : {}),
          })
          publishNodeResult(nodeId)
        } finally {
          patchVisibleNode(nodeId, { stage: undefined })
        }
      })()
    }
  }, [eng, patchVisibleNode, chatScope, publishNodeResult, markNodePlanning, real])

  // ── AI 对话动作 → 画布执行（2026-09-18 扩展）：focus 之外支持改提示词/加节点/
  // 连线/删节点/跑单节点/跑整图。流式回复边到边执行：动作一到就改画布。
  // 安全边界：模型只能点名「节点清单」里存在的 key；删除仅限用户自己加的
  // 节点（custom）——模板结构是业务契约，AI 不能拆；连线走 canConnect 防环。 ──
  const onChatAction = useCallback(async (action: Record<string, unknown>): Promise<boolean> => {
    const type = String(action.type ?? '')
    if (type === 'chat_done') {
      const pending = [...pendingTextPrompts.current.entries()]
      pendingTextPrompts.current.clear()
      for (const [nodeId, prompt] of pending) {
        if (textRewriteOnly.current.delete(nodeId)) {
          const n = canvasNodesRef.current.find(x => x.id === nodeId)
          if (n) patchVisibleNode(nodeId, {
            gen: { ...(n.gen ?? { refs: [], prompt: '', model: '', params: [] }), prompt, edited: true },
            stage: undefined,
          })
          continue
        }
        try { await runOne(nodeId, 'on_demand', 'chat', prompt) } catch { /* engine log carries failure */ }
      }
      for (const n of canvasNodesRef.current) {
        if (n.stage?.tone === 'run' && n.stage.label !== '执行中') patchVisibleNode(n.id, { stage: undefined })
      }
      return true
    }
    if (type === 'chat_error') {
      pendingTextPrompts.current.clear()
      textRewriteOnly.current.clear()
      const error = String(action.error ?? '对话执行失败')
      for (const n of canvasNodesRef.current) {
        if (n.stage?.tone === 'run' && n.stage.label !== '执行中') {
          patchVisibleNode(n.id, { stage: { label: 'Execution failed', tone: 'err' }, error })
        }
      }
      return true
    }
    const findNode = (key: unknown) => {
      const k = String(key ?? '').trim()
      if (!k) return undefined
      return canvasNodesRef.current.find(x => x.id === k)
        ?? canvasNodesRef.current.find(x => x.title === k)
    }
    const withPrompt = (n: TapNode, prompt: string): Partial<TapNode> => ({
      gen: { ...(n.gen ?? { refs: [], prompt: '', model: '', params: [] }), prompt, edited: true },
      error: undefined,
    })
    if (type === 'focus_node') {
      const n = findNode(action.node_key)
      if (!n) return false
      setSelNode(n)
      if (!prod || n.custom) setPanelTab('props')
      setDock('panel')
      return true
    }
    if (type === 'update_node_content') {
      const n = findNode(action.node_key)
      const content = String(action.content ?? action.text ?? '').trim()
      if (!n || n.type !== 'text' || !content) return false
      pendingTextPrompts.current.delete(n.id)
      textRewriteOnly.current.delete(n.id)
      patchVisibleNode(n.id, { text: content, textEdited: true, done: true,
        status: undefined, error: undefined, stage: undefined })
      publishChatResult({ scope: chatScope, nodeKey: n.id, nodeTitle: n.title, nodeType: n.type, content })
      setSelNode({ ...n, text: content, textEdited: true, done: true,
        status: undefined, error: undefined, stage: undefined })
      return true
    }
    if (type === 'update_node_prompt') {
      const n = findNode(action.node_key)
      const prompt = String(action.prompt ?? '').trim()
      if (!n || !prompt) return false
      // 文本节点（llm）同样接受 AI 改写：改写目标就是正文本身
      const editable = isGenType(n.type) || n.type === 'text'
      if (!editable) return false
      if (isGenType(n.type)) patchVisibleNode(n.id, withPrompt(n, prompt))
      else {
        pendingTextPrompts.current.set(n.id, prompt)
        patchVisibleNode(n.id, { stage: { label: 'Waiting to execute', tone: 'run' }, error: undefined })
      }
      setSelNode(n)
      return true
    }
    if (type === 'add_node') {
      const t = (['text', 'image', 'video', 'tool', 'condition', 'qc', 'mount'] as const)
        .find(x => x === String(action.node_type ?? ''))
      if (!t) return false
      const up = findNode(action.connect_from) ?? (String(action.connect_from ?? 'auto') === 'auto' ? selNode : undefined)
      const anchor = up ?? [...canvasNodesRef.current].filter(n => !n.runtime?.transient).at(-1)
      const n = newTapNode(t, anchor ? anchor.x + anchor.w + 110 : 200, (anchor ? anchor.y : 200) + 40)
      const title = String(action.title ?? '').trim()
      if (title) n.title = title.slice(0, 24)
      const prompt = String(action.prompt ?? '').trim()
      if (prompt && isGenType(t) && n.gen) n.gen = { ...n.gen, prompt, edited: true }
      setNodes(ns => [...ns, n])
      if (anchor) setEdges(es => canConnect(es, anchor.id, n.id)
        ? [...es, { id: `e-${anchor.id}-${n.id}`, from: anchor.id, to: n.id }] : es)
      setSelNode(n)
      if (!prod) setPanelTab('props')
      setDock('panel')
      return true
    }
    if (type === 'connect') {
      const a = findNode(action.from), b = findNode(action.to)
      if (!a || !b || a.id === b.id) return false
      setEdges(es => es.some(e => e.from === a.id && e.to === b.id) || !canConnect(es, a.id, b.id)
        ? es : [...es, { id: `e-${a.id}-${b.id}`, from: a.id, to: b.id }])
      return true
    }
    if (type === 'remove_node') {
      const n = findNode(action.node_key)
      if (!n || !n.custom || n.type === 'start') return false
      setNodes(ns => ns.filter(x => x.id !== n.id))
      setEdges(es => es.filter(e => e.from !== n.id && e.to !== n.id))
      return true
    }
    if (type === 'run_node') {
      const n = findNode(action.node_key)
      if (!n) return false
      // 文本节点（llm 投影）同样可被 AI 指名运行：生成条语义里文本节点的
      // 输入框就是本次模型指令（见 useTapflowRun 的 verbatim 注释），与媒体节点
      // 同一动作；不支持的类型（qc/tool 等）依旧静默拒绝由模型自行纠偏。
      const runnable = isGenType(n.type) || n.type === 'text'
      if (!runnable) return false
      const prompt = String(action.prompt ?? '').trim() || pendingTextPrompts.current.get(n.id) || ''
      if (prompt && isGenType(n.type)) patchVisibleNode(n.id, withPrompt(n, prompt))
      if (n.type === 'text') {
        pendingTextPrompts.current.delete(n.id)
        textRewriteOnly.current.delete(n.id)
      }
      // via='chat'：AI 动作触发的本地确定性执行，不回注对话（防循环）
      // Wait for the canvas action to finish before ending the chat turn. This
      // keeps the generated artifact in the canvas/history for an immediate
      // follow-up instead of racing the next user message.
      await runOne(n.id, 'on_demand', 'chat', prompt || undefined)
      return true
    }
    if (type === 'run_canvas') {
      await runNow()
      return true
    }
    return false
  }, [chatScope, prod, patchVisibleNode, runOne, runNow, selNode])

  // ── 对话贡献者注册：把画布的 scope/上下文生成器/动作处理器注册给全局面板
  // （lib/uiContext），全局面板在画布页自动关联画布会话；卸载时注销。
  // ref 存最新闭包避免反复注销重注册；scope/contextBuilder 本身都是稳定的。
  const contribRef = useRef<ChatContributor>({ id: 'tapflow', scope: { kind: 'tapflow' } })
  useEffect(() => {
    registerChatContributor(contribRef.current)
    return () => { unregisterChatContributor('tapflow'); clearChatInject() }
  }, [])
  contribRef.current.scope = chatScope
  contribRef.current.contextBuilder = buildCanvasContext
  contribRef.current.onAction = a => onChatAction(a)
  // 输入框 @ 可引用的实体：画布节点清单（跳过临时投影节点，与上下文同口径）
  contribRef.current.mentions = () => canvasNodesRef.current
    .filter(n => !n.runtime?.transient)
    .map(n => ({ id: n.id, title: n.title }))

  // 撤销/重做栈（Ctrl/⌘+Z、+Shift+Z，只认增删节点/连线）：状态在本容器，栈也就挂在这儿；
  // 纯内存，弹窗一关就没了——重开画布拉的是库里那份图，撤销无从谈起
  const history = useTapflowHistory(nodes, edges, setNodes, setEdges)
  const toggleInspector = useCallback(() => {
    if (dock === 'panel' && panelTab === 'props') { setDock(null); return }
    // 生产态不切编排：那边整条产线是模板定的，切过去只会看到一堆改不动的配置。
    // 这里开面板是为了配「自己加的那个节点」，运行态就能配（生成配置段不分模式）
    if (!prod) setMode('edit')
    setPanelTab('props')
    setDock('panel')
  }, [dock, panelTab, prod])

  // ── 运行日志 → 对话流桥接（2026-09）：日志不再是执行面板的 tab，
  // 而是拆进公共对话面板的「对话」tab：在这里监听 eng.log 增量，
  // 按 run 归组转换成折叠卡消息注入 ChatDock（sim / 真实引擎同签名，一份转换两层共用）。
  // 新一轮 run 会整表重置日志：长度变小说明整份都是新行。
  const [chatLog, setChatLog] = useState<ChatMsg[]>([])
  const logSeen = useRef(0)
  useEffect(() => {
    const seen = logSeen.current
    if (eng.log.length === seen) return
    const fresh = eng.log.length < seen ? eng.log : eng.log.slice(seen)
    logSeen.current = eng.log.length
    setChatLog(msgs => {
      const next = [...msgs]
      for (const l of fresh) {
        // 这三个短语是两个引擎 run 首行的固定开头（全量运行/单节点运行/运行开始）
        const isRunHead = l.text.includes('运行开始') || l.text.includes('单节点运行')
          || l.text.includes('全量运行')
        const last = next[next.length - 1]
        if (isRunHead || !last || last.kind !== 'run') {
          // 从首行提取运行目标：单节点运行「单节点运行：X（…）」/ 全量运行画布；
          // 配对画布节点拿 id，供卡片的「查看画布」聚焦到该节点
          const name = l.text.includes('单节点运行')
            ? (l.text.split('：')[1]?.split('（')[0]?.trim() ?? '')
            : ''
          const target = name
            ? canvasNodesRef.current.find(n => n.title === name || n.id === name)
            : undefined
          next.push({
            kind: 'run', label: l.text, lines: [l],
            nodeId: target?.id, nodeTitle: name || '整张画布',
          })
        } else {
          next[next.length - 1] = { ...last, lines: [...last.lines, l] }
          // 全量运行但限了范围（AI 动作常见形态：range 从 X 到 X）：首行拿不到节点名，
          // 等到「跑到「X」为止」这行再回填副标题与「查看画布」的聚焦目标
          if (last.nodeTitle === '整张画布') {
            const m = l.text.match(/跑到「(.+?)」为止/)
            if (m) {
              const target = canvasNodesRef.current.find(n => n.title === m[1] || n.id === m[1])
              next[next.length - 1] = {
                ...next[next.length - 1],
                nodeTitle: m[1],
                ...(target ? { nodeId: target.id } : {}),
              } as ChatMsg
            }
          }
        }
      }
      return next
    })
  }, [eng.log])

  // chatLog → 全局注入通道：全局面板的对话流实时显示画布运行日志（不落库），
  // 面板关着也在写——用户在全站任何角落都能从徽标/任务队列感知到运行进展。
  useEffect(() => { pushChatInject(chatLog) }, [chatLog])

  return (
    <Modal open onClose={onClose} full title={flow.name} cardClass="tap-modal">
      <div className="tap-page">
        <div className="tap-main">
          {/* 编排⇄运行切换与保存都属于编排台；生产态只跑不改，整条都不出现 */}
          {!prod && (
            <span className="tap-mode-seg" onPointerDown={e => e.stopPropagation()}>
              <button type="button" className={mode === 'edit' ? 'on' : ''} onClick={() => setMode('edit')}>编排</button>
              <button type="button" className={mode === 'run' ? 'on' : ''} onClick={openRun}>运行</button>
            </span>
          )}
          {!prod && mode === 'edit' && (
            <TapflowSaveBar save={save} onSave={() => void save.save(stateRef.current.nodes, stateRef.current.edges)} />
          )}
          {/* 生产态：自动保存的回执（改动落进「本对象的专属画布」了没有） */}
          {prod && subject && <TapflowAutosaveBar save={save} />}
          <TapflowCanvas
            nodes={canvasNodes} edges={canvasEdges}
            onNodesChange={changeCanvasNodes}
            onEdgesChange={runtimeProjected ? () => undefined : setEdges}
            // 坐标存过就别再整图重排：那一遍会把用户亲手拖的位置推回去
            // 自动排版统一由“参数齐全后的首次整图重排”接管；Canvas 不再持续吸附坐标。
            mode={mode} autoLayout={false}
            onRelayout={() => arrangeAll(prod && !!subject)}
            onSelectNode={onSelectNode}
            onRun={openRun}
            // rail 那枚高亮「运行」是**生产态专用**的一键跑；编排台不给——
            // 编排/运行两态下它都不该出现，编排台要跑就走运行面板那条（能看范围与参数）
            onRunNow={prod ? runNow : undefined} onSend={runOne}
            // 底部条输入框：请求立即进入当前对话，由规划动作按“整理最终提示词→执行画布”
            // 的顺序处理；特殊要求可以为空，按钮本身不显示 loading。
            onInstruct={text => {
              const requirement = text.trim()
              markCanvasPlanning()
              requestChatSend(
                requirement || '\u5df2\u6267\u884c\u5f53\u524d\u753b\u5e03\uff0c\u8bf7\u57fa\u4e8e\u6700\u65b0\u7ed3\u679c\u7ee7\u7eed\u89c4\u5212\u3002',
                { scope: chatScope, meta: {
                  canvas_request: { execute_after_planning: true, special_requirement: requirement },
                } })
              if (!real) void runNow()
            }}
            onRegen={regen} regenBusy={regenBusy} flows={flows}
            // 「重新读取」只对真实流程有意义（演示画布没有库里那份产物可查）
            onReload={real ? (id => void live.preview(id)) : undefined}
            projectId={projectId} businessRefs={businessRefs}
            onBusinessRefAdd={unifiedSubject ? addBusinessRef : undefined}
            onBusinessRefRemove={unifiedSubject ? removeBusinessRef : undefined}
            onBgClick={() => setDock(null)} onUndo={history.undo} onRedo={history.redo}
            // 生产态也给属性按钮，但只在选中「自己加的节点」时——模板那几个节点
            // 的编排语义归编排台管，业务用户改不得
            onToggleInspector={!prod || selNode?.custom ? toggleInspector : undefined}
            inspectorOpen={dock === 'panel' && panelTab === 'props'}
            // 「+ 新建节点」：生产态同样给（拖出来的节点现在是能存能跑的），
            // 但演示画布与没有归属的生产画布不给——存不下的东西不该让人建
            canAdd={!prod || !!subject}
            entryMount={entryMount} onMountWire={prod ? onMountWire : undefined}
          />
        </div>
        {dock === 'panel' && (panelTab === 'run' || !prod || selNode?.custom) && (
          <TapflowSidePanel
            tab={panelTab} onTab={setPanelTab} onClose={() => setDock(null)}
            canProps={!prod || !!selNode?.custom}
            inspector={
              <TapflowInspectorBody
                node={selNode} mode={mode} upstream={selCtx.upstream}
                flows={flows.filter(f => f.slug !== flow.slug)}
                smartCall={save.smartCall}
                onSmartCall={save.savable ? on => void save.setSmartCall(on) : undefined}
                inEdges={edges.filter(e => e.to === selNode?.id).map(e => ({
                  id: e.id, from: e.from,
                  fromTitle: nodes.find(n => n.id === e.from)?.title ?? e.from,
                }))}
                onRemoveEdge={id => setEdges(es => es.filter(e => e.id !== id))}
                onPatch={patchNode} />
            }
            run={
              <TapflowRunBody
                start={start} nodes={nodes} range={range} running={eng.running}
                forceAll={forceAll}
                workflowSlug={flow.slug} workflowVersion={flow.version}
                hint={lastRun ? `已沿用上次运行（${lastRun.created_at.slice(5, 16).replace('T', ' ')}）的参数` : undefined}
                optionsFor={real ? ctx.optionsFor : undefined}
                onParam={(k, v) => start && patchNode(start.id, {
                  params: setParamValue(start.params ?? [], k, v),
                })}
                onParams={applyParams}
                onRange={setRange}
                onForceAll={setForceAll}
                onRun={() => void eng.run(range, forceAll, { mode: 'all' })} />
            } />
        )}
      </div>
    </Modal>
  )
}
