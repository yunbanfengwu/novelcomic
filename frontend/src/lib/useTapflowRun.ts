// tapflow 真实运行:async run + 轮询 node_runs 点亮画布节点(与 useTapflowSim 同签名,
// 假数据流程仍走 sim,真实流程走本 hook)。执行本体在后端解释器,这里只做状态投影。
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type WorkflowDetail, type WorkflowNodeRun } from '../api'
import { isGenType, type TapEdge, type TapNode } from './tapflowData'
import type { TapRunLog } from './useTapflowSim'
import { jsonbObj, resolveTitle, startInputs, titleVars } from './tapflowGraphAdapter'
import { rangeToRun, type TapRunOptions, type TapRunRange, upstreamNodes } from './tapflowRunPlan'

const POLL_MS = 2000
const TIMEOUT_MS = 20 * 60_000
const DEFAULT_IMAGE_WIDTH = 460
const RUN_ROW_GAP = 48
const now = () => new Date().toTimeString().slice(0, 8)
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))
const runtimeNodeId = (loopId: string, childNodeKey: string, iteration: number) =>
  `${loopId}::${childNodeKey}::${iteration}`

const imageHeightForAspect = (width: number, aspect: string | undefined) =>
  Math.round(width * (aspect === '9:16' ? 16 / 9 : 9 / 16))

/** 循环 body 的媒体产物可能嵌套在 subflow 节点名下面，递归取实际图片。 */
const mediaUrl = (value: unknown): string | undefined => {
  if (typeof value === 'string' && /^(https?:|data:|blob:)/.test(value)) return value
  if (Array.isArray(value)) {
    for (const item of value) { const found = mediaUrl(item); if (found) return found }
  } else if (value && typeof value === 'object') {
    const obj = value as Record<string, unknown>
    for (const key of ['url', 'sheet_url', 'image_url', 'value']) {
      const found = mediaUrl(obj[key]); if (found) return found
    }
    for (const child of Object.values(obj)) { const found = mediaUrl(child); if (found) return found }
  }
  return undefined
}

const directMediaUrl = (outputs: Record<string, unknown>) => {
  for (const key of ['url', 'sheet_url', 'image_url', 'video_url', 'keyframe_url', 'value']) {
    const value = outputs[key]
    if (typeof value === 'string' && /^(https?:|data:|blob:)/.test(value)) return value
  }
  return undefined
}

/** 生成产物落卡：视频卡进 video（<video> 播放器），其余进 src（缩略图/poster）。
 * 不分的话 mp4 会被塞进 <img>，视频卡上直接破图。done/跳过/重开回填三处共用。
 * 判型看 type=video 或 modality=video——通用 gen 节点（type=gen）配了视频生成步骤
 * 时产物也是 mp4，只看 type 会把预告片塞进 src 破图。 */
const genMediaPatch = (n: TapNode, url: string | undefined): Partial<TapNode> =>
  url ? (n.type === 'video' || n.modality === 'video' ? { video: url } : { src: url }) : {}

const runtimeResult = (outputs: Record<string, unknown>) => {
  const summary = Object.entries(outputs).map(([key, value]) => {
    if (Array.isArray(value)) return `${key}: ${value.length} items`
    if (value && typeof value === 'object') return `${key}: object`
    return `${key}: ${String(value ?? '')}`
  }).filter(Boolean).join(' | ') || 'No output'
  let json = '{}'
  try { json = JSON.stringify(outputs, null, 2) } catch { json = String(outputs) }
  return { summary, json: json.slice(0, 12000) }
}

/** Convert a workflow's persisted QC payload into the prompt bar status. */
const qcBadge = (outputs: Record<string, unknown>): TapNode['stage'] => {
  const qc = outputs.qc as {
    passed?: boolean; score?: number; rounds?: number; issues?: unknown[]; user?: string
  } | undefined
  if (!qc || typeof qc.score !== 'number') return undefined
  return {
    label: `提示词 ${qc.score} 分${(qc.rounds ?? 1) > 1 ? ` · ${qc.rounds} 轮` : ''}`,
    tone: qc.passed ? 'ok' : 'err',
    issues: (qc.issues ?? []).map(String).filter(Boolean),
    user: qc.user,
    anchor: typeof outputs.anchor === 'string' ? outputs.anchor : undefined,
  }
}

const outputStage = (outputs: Record<string, unknown>): TapNode['stage'] =>
  qcBadge(outputs) ?? (typeof outputs.phase === 'string' && outputs.phase
    ? { label: outputs.phase, tone: 'run' }
    : undefined)

/** Prefer the concrete generating node over an outer workflow's summary output. */
const generationOutputs = (runOutputs: unknown, rows: WorkflowNodeRun[]) => {
  const merged = { ...jsonbObj(runOutputs) }
  for (const row of rows) {
    const outputs = jsonbObj(row.outputs)
    if (typeof outputs.prompt === 'string' && outputs.prompt.trim()) {
      merged.prompt = outputs.prompt
    }
    if (Array.isArray(outputs.reference_images)) {
      merged.reference_images = outputs.reference_images
    }
    for (const key of ['qc', 'phase', 'anchor'] as const) {
      if (outputs[key] !== undefined) merged[key] = outputs[key]
    }
    const url = directMediaUrl(outputs)
    if (url) merged.url = url
  }
  return merged
}

const itemIdentity = (item: Record<string, unknown> | undefined) => {
  if (!item) return ''
  const value = item.element_id ?? item.target_ref ?? item.id ?? item.name ?? item.title
  return value == null ? '' : String(value)
}

const itemElementId = (item: Record<string, unknown>) => {
  const direct = Number(item.element_id)
  if (Number.isFinite(direct) && direct > 0) return direct
  const match = typeof item.target_ref === 'string'
    ? item.target_ref.match(/^element:(\d+)$/) : undefined
  return match ? Number(match[1]) : undefined
}

const itemAttachmentId = (item: Record<string, unknown>) => {
  const existing = item.existing_asset && typeof item.existing_asset === 'object'
    ? item.existing_asset as Record<string, unknown> : undefined
  const value = existing?.attachment_id ?? item.attachment_id
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : undefined
}

const subflowInputsForItem = (baseInputs: Record<string, unknown>, item: Record<string, unknown>) =>
  Object.fromEntries(Object.entries({
    project_id: baseInputs.project_id,
    target_ref: item.target_ref,
    asset_type: item.asset_type,
    element_id: item.element_id,
    scene_name: item.name,
  }).filter(([, value]) => value !== undefined && value !== null && value !== ''))

const RUN_SUBJECT_KEYS = [
  'target_ref', 'element_id', 'shot_id', 'node_id', 'chapter_id',
] as const
const RUN_NAME_KEYS = ['scene_name', 'character_name'] as const

/** Keep restored run state scoped to the business object currently open. */
const sameRunContext = (current: Record<string, unknown>, historical: Record<string, unknown>) => {
  if (current.project_id != null && historical.project_id != null
      && String(current.project_id) !== String(historical.project_id)) return false

  let compared = false
  for (const key of RUN_SUBJECT_KEYS) {
    if (current[key] == null || historical[key] == null) continue
    compared = true
    if (String(current[key]) !== String(historical[key])) return false
  }
  if (compared) return true

  for (const key of RUN_NAME_KEYS) {
    if (current[key] == null || historical[key] == null) continue
    return String(current[key]).trim() === String(historical[key]).trim()
  }
  return true
}

export function useTapflowRun(
  slug: string | undefined, version: number | undefined,
  getState: () => { nodes: TapNode[]; edges: TapEdge[] },
  patch: (id: string, p: Partial<TapNode>) => void,
  /** 节点 id → 文本节点直出的输出字段（graph 的 config.ui.show） */
  show: Record<string, string> = {},
  /** 节点 id → 接收其产物的生成节点 id（graph 的 config.ui.feeds）：
   * 出图提示词属于图片本身，装配节点不画在画布上，产物直接进图片的生成条 */
  feeds: Record<string, string> = {},
  /** A production instance can inherit persisted results from its source template. */
  historySlug?: string,
) {
  // show/feeds 每次渲染是新对象，进 useCallback 依赖会让回调恒新——用 ref 透传
  const showRef = useRef(show)
  showRef.current = show
  const feedsRef = useRef(feeds)
  feedsRef.current = feeds
  /** 文本节点该显示的产物：优先 ui.show 指定的字段，其次常见字段名 */
  const textOf = (key: string, o: Record<string, unknown>): string | undefined => {
    const want = showRef.current[key]
    // value 兜底：subflow/task 跳过时后端把探到的产物放在 value 里
    const v = want ? (o[want] ?? o.value) : (o.summary ?? o.prompt ?? o.text ?? o.value)
    return typeof v === 'string' && v ? v : undefined
  }
  const [running, setRunning] = useState(false)
  const [runtimeNodes, setRuntimeNodes] = useState<TapNode[]>([])
  const [runtimeEdges, setRuntimeEdges] = useState<TapEdge[]>([])
  const [runtimeLoopOwners, setRuntimeLoopOwners] = useState<string[]>([])
  /** 只在一次完整预检把所有 loop 集合投影完后递增，供画布精确触发一次重排。 */
  const [projectionRevision, setProjectionRevision] = useState(0)
  const [log, setLog] = useState<TapRunLog[]>([])
  const runningRef = useRef(false)
  runningRef.current = running
  /** A run invalidates any slower preview that started before the manual action. */
  const previewEpoch = useRef(0)
  const dead = useRef(false)
  const workflows = useRef(new Map<string, Promise<WorkflowDetail>>())
  const subflowQcHistory = useRef(new Map<string, Promise<Record<string, unknown>>>())
  useEffect(() => {
    dead.current = false
    return () => { dead.current = true }
  }, [])
  const say = useCallback((text: string, kind?: TapRunLog['kind']) =>
    setLog(ls => [...ls, { t: now(), text, kind }]), [])

  const workflowFor = useCallback((ref: { slug?: string; version?: number } | undefined) => {
    if (!ref?.slug) return undefined
    const cacheKey = `${ref.slug}@${ref.version ?? 'published'}`
    let pending = workflows.current.get(cacheKey)
    if (!pending) {
      pending = api.getWorkflow(ref.slug, ref.version)
      workflows.current.set(cacheKey, pending)
    }
    return pending
  }, [])

  const childWorkflow = useCallback((owner: TapNode) =>
    workflowFor(owner.bind?.subflow), [workflowFor])

  const currentWorkflow = useCallback(() =>
    workflowFor(slug ? { slug, version } : undefined), [slug, version, workflowFor])

  /**
   * A parent run keeps the exact child run that originally supplied its image. That
   * run may predate QC, while a later run for the same business object has the
   * verdict. Recover only qc/anchor so a newer verdict never replaces the image
   * currently projected by the parent.
   */
  const latestSubflowQc = useCallback((
    ref: { slug: string; version?: number }, context: Record<string, unknown>, projectId?: number,
  ) => {
    if (!projectId) return Promise.resolve({} as Record<string, unknown>)
    const contextKey = ['project_id', ...RUN_SUBJECT_KEYS, ...RUN_NAME_KEYS]
      .map(key => `${key}:${String(context[key] ?? '')}`).join('|')
    const key = `${ref.slug}@${ref.version ?? 'published'}|${contextKey}`
    let pending = subflowQcHistory.current.get(key)
    if (!pending) {
      pending = (async () => {
        try {
          const candidates = (await api.workflowRuns(projectId)).filter(run => {
            const direct = run.slug === ref.slug
              && (ref.version === undefined || run.version === ref.version)
            // Production canvases fork to `${origin}@...`; their run summary does
            // not expose origin_slug, so the stable instance prefix is the only
            // frontend-visible link back to the referenced child workflow.
            const instance = run.slug.startsWith(`${ref.slug}@`)
            return direct || instance
          })
          for (const candidate of candidates) {
            const detail = await api.workflowRun(candidate.id)
            if (!sameRunContext(context, jsonbObj(detail.inputs))) continue
            const outputs = generationOutputs(
              detail.outputs, await api.workflowRunNodes(candidate.id))
            if (!qcBadge(outputs)) continue
            return {
              qc: outputs.qc,
              ...(outputs.anchor !== undefined ? { anchor: outputs.anchor } : {}),
            }
          }
        } catch { /* The exact child run remains a valid image-only fallback. */ }
        return {}
      })()
      subflowQcHistory.current.set(key, pending)
    }
    return pending
  }, [])

  const readSubrunOutputs = useCallback(async (subrunId: number) => {
    const [run, rows] = await Promise.all([
      api.workflowRun(subrunId), api.workflowRunNodes(subrunId),
    ])
    return generationOutputs(run.outputs, rows)
  }, [])

  const childNodeForItem = (wf: WorkflowDetail | undefined, item: Record<string, unknown>) => {
    if (!wf) return 'item'
    const loops = (wf.graph.nodes ?? []).filter(n => n.type === 'loop')
    for (const loop of loops) {
      const body = Array.isArray(loop.config?.body) ? loop.config.body.map(String) : []
      for (const key of body) {
        const candidate = wf.graph.nodes.find(n => n.id === key)
        const condition = candidate?.config?.run_if as { value?: unknown; equals?: unknown } | undefined
        if (!condition || condition.equals === undefined) continue
        if (condition.equals === item.asset_type) return key
      }
      if (body.length === 1) return body[0]
    }
    return 'item'
  }

  /** Recover the source workflow marker for a real subflow body node. */
  const subflowRefForNode = (wf: WorkflowDetail | undefined, nodeKey: string) => {
    const node = wf?.graph.nodes.find(n => n.id === nodeKey)
    if (!node || node.type !== 'subflow') return undefined
    const cfg = node.config ?? {}
    const slug = typeof cfg.slug === 'string' ? cfg.slug : ''
    if (!slug) return undefined
    const version = typeof cfg.version === 'number' ? cfg.version : undefined
    return version === undefined ? { slug } : { slug, version }
  }

  /** Aggregate projection: one transient media node per iteration, never persisted in the parent graph. */
  const projectLoopInstance = useCallback((loop: TapNode, childNodeKey: string, iteration: number,
    label: string, status: string, outputs: Record<string, unknown>, error?: string,
    subrunId?: number, subflow?: { slug: string; version?: number },
    sourceItem?: Record<string, unknown>) => {
    const id = runtimeNodeId(loop.id, childNodeKey, iteration)
    const src = mediaUrl(outputs)
    const prompt = typeof outputs.prompt === 'string' && outputs.prompt.trim()
      ? outputs.prompt : undefined
    const refs = Array.isArray(outputs.reference_images)
      ? (outputs.reference_images as { url?: unknown }[])
        .map(ref => typeof ref?.url === 'string' ? ref.url : '')
        .filter(Boolean)
      : undefined
    const stage = status === 'running'
      ? outputStage(outputs) ?? { label: '执行中', tone: 'run' as const }
      : outputStage(outputs)
    const start = getState().nodes.find(n => n.type === 'start')
    const aspect = start?.project?.aspect
    setRuntimeLoopOwners(xs => xs.includes(loop.id) ? xs : [...xs, loop.id])
    setRuntimeNodes(xs => {
      const old = xs.find(n => n.id === id)
      const manualSize = !!old?.manualSize
      const width = manualSize ? old.w : DEFAULT_IMAGE_WIDTH
      const height = manualSize ? old.h : imageHeightForAspect(width, aspect)
      // Nested subflows pass their exact child-graph reference. Direct loops
      // can recover it from the visible body node; ordinary gen bodies stay
      // untagged.
      const bodyNode = getState().nodes.find(n => n.id === childNodeKey)
      const ref = subflow ?? (bodyNode ? bodyNode.bind?.subflow : old?.bind?.subflow)
      const gen = prompt || refs?.length
        ? {
            model: old?.gen?.model ?? '系统出图模型',
            params: old?.gen?.params ?? ['自适应(4K)'],
            prompt: prompt ?? old?.gen?.prompt ?? '',
            refs: refs ?? old?.gen?.refs ?? [],
            ...(old?.gen?.edited ? { edited: true } : {}),
          }
        : old?.gen
      const runtime: TapNode = {
        id, type: 'image', title: label,
        // 编排态使用画布预设尺寸；运行态按开始节点的项目画幅计算新占位高度。
        x: old?.x ?? loop.x,
        y: old?.y ?? loop.y + iteration * (height + RUN_ROW_GAP),
        w: width,
        h: height,
        manualSize: manualSize || undefined,
        runtime: {
          loopOwner: loop.id, childNodeKey, iteration, transient: true, subrunId,
          sourceItem: sourceItem ?? old?.runtime?.sourceItem,
        },
        ...(ref?.slug ? { bind: { subflow: { ...ref } } } : {}),
        ...(gen ? { gen } : {}),
        ...(src ? { src } : old?.src ? { src: old.src } : {}),
        ...(stage ? { stage } : {}),
        ...(status === 'running' ? { status: 'generating' as const } : {}),
        ...(status === 'done' || status === 'skipped' ? { done: true } : {}),
        ...(status === 'skipped' ? { badge: { label: '复用', tone: 'skip' as const } } : {}),
        ...(status === 'failed' ? { error: error || '生成失败', badge: { label: '失败', tone: 'err' as const } } : {}),
      }
      // A loop can report its aggregate row before its body row. Keep exactly one
      // visible product per iteration and let the actual body/child node replace it.
      return [...xs.filter(n => !(n.runtime?.loopOwner === loop.id
          && n.runtime.iteration === iteration)), runtime]
        .sort((a, b) => (a.runtime?.iteration ?? 0) - (b.runtime?.iteration ?? 0))
    })
    const templateEdges = getState().edges
    const projected: TapEdge[] = [
      {
        id: `${loop.id}::${iteration}:expand`, from: loop.id, to: id, mapping: 'each',
      },
      ...templateEdges.filter(e => e.from === loop.id)
        .map(e => ({ ...e, id: `${e.id}::${iteration}:out`, from: id })),
    ]
    const instancePrefix = `${loop.id}::`
    setRuntimeEdges(xs => [...xs.filter(e => {
      const endpoint = [e.from, e.to].find(x => x.startsWith(instancePrefix))
      return !endpoint || !endpoint.endsWith(`::${iteration}`)
    }), ...projected])
  }, [getState])

  const projectChildRun = useCallback(async (owner: TapNode, subrunId: number) => {
    const wf = await childWorkflow(owner)
    if (!wf) return 0
    const childRuns = await api.workflowRunNodes(subrunId)
    const loopNodes = wf.graph.nodes.filter(n => n.type === 'loop')
    const bodyIds = new Set(loopNodes.flatMap(n => Array.isArray(n.config?.body)
      ? n.config.body.map(String) : []))
    const descriptors = new Map<number, Record<string, unknown>>()
    for (const nr of childRuns) {
      if (!loopNodes.some(n => n.id === nr.node_key)) continue
      const item = jsonbObj(nr.inputs).item
      if (item && typeof item === 'object') descriptors.set(nr.iteration, item as Record<string, unknown>)
    }
    const products = childRuns.filter(nr => bodyIds.has(nr.node_key))
    for (const nr of products) {
      const childInputs = jsonbObj(nr.inputs)
      const item = descriptors.get(nr.iteration) ?? childInputs
      const outputs = jsonbObj(nr.outputs)
      const label = String(item.name ?? item.title ?? item.role ?? `第 ${nr.iteration + 1} 项`)
      const subflow = subflowRefForNode(wf, nr.node_key)
      const exactSubrunId = nr.subrun_id ?? subrunId
      let displayOutputs = Object.keys(outputs).length ? outputs : item
      if (subflow?.slug && nr.subrun_id) {
        try {
          displayOutputs = { ...displayOutputs, ...await readSubrunOutputs(nr.subrun_id) }
        } catch { /* Parent row still remains a valid projection fallback. */ }
      }
      if (subflow?.slug && (nr.status === 'done' || nr.status === 'skipped')
          && !qcBadge(displayOutputs)) {
        const projectId = Number(childInputs.project_id)
        displayOutputs = {
          ...displayOutputs,
          ...await latestSubflowQc(subflow, childInputs,
            Number.isFinite(projectId) && projectId > 0 ? projectId : undefined),
        }
      }
      projectLoopInstance(owner, nr.node_key, nr.iteration, label, nr.status,
        displayOutputs, nr.error, exactSubrunId, subflow, item)
    }
    if (products.length) setProjectionRevision(x => x + 1)
    return products.length
  }, [childWorkflow, projectLoopInstance, readSubrunOutputs, latestSubflowQc])

  const updateRuntimeOutput = useCallback((id: string, outputs: Record<string, unknown>) => {
    setRuntimeNodes(xs => xs.map(node => {
      if (node.id !== id) return node
      const src = mediaUrl(outputs)
      const prompt = typeof outputs.prompt === 'string' && outputs.prompt.trim()
        ? outputs.prompt : undefined
      const refs = Array.isArray(outputs.reference_images)
        ? (outputs.reference_images as { url?: unknown }[])
          .map(ref => typeof ref?.url === 'string' ? ref.url : '')
          .filter(Boolean)
        : undefined
      const gen = prompt || refs?.length
        ? {
            model: node.gen?.model ?? '系统出图模型',
            params: node.gen?.params ?? ['自适应(4K)'],
            prompt: prompt ?? node.gen?.prompt ?? '',
            refs: refs ?? node.gen?.refs ?? [],
            ...(node.gen?.edited ? { edited: true } : {}),
          }
        : node.gen
      const stage = outputStage(outputs)
      return {
        ...node,
        ...(src ? { src } : {}),
        ...(gen ? { gen } : {}),
        ...(stage ? { stage } : {}),
      }
    }))
  }, [])

  /** A projected loop product is not a node in the parent graph. Rerun its real executor. */
  const runProjectedNode = useCallback(async (
    node: TapNode, send: TapRunOptions | undefined,
    baseInputs: Record<string, unknown>, projectId: number | undefined,
  ) => {
    const ref = node.bind?.subflow
    const childNodeKey = node.runtime?.childNodeKey
    const sourceItem = node.runtime?.sourceItem ?? {}
    const prompt = (send?.promptOverride ?? node.gen?.prompt ?? '').trim()
    const descriptorPrompt = typeof sourceItem.prompt === 'string'
      ? sourceItem.prompt.trim() : ''
    // A router descriptor's generic prompt is not an override for a referenced
    // workflow. Only a real child prompt or a user's edit may be sent verbatim.
    const usePrompt = send?.rewrite !== node.id && !!prompt
      && (send?.promptOverride !== undefined
        || !ref?.slug || node.gen?.edited || !descriptorPrompt || prompt !== descriptorPrompt)

    setRuntimeNodes(xs => xs.map(n => n.id === node.id ? {
      ...n, status: 'generating', done: undefined, error: undefined, badge: undefined,
      stage: { label: '执行中', tone: 'run' },
    } : n))

    let runId: number
    if (ref?.slug) {
      let childInputs: Record<string, unknown> = {}
      if (node.runtime?.subrunId) {
        try {
          childInputs = jsonbObj((await api.workflowRun(node.runtime.subrunId)).inputs)
        } catch { /* Fall back to the descriptor when an old run was removed. */ }
      }
      if (!Object.keys(childInputs).length) {
        childInputs = subflowInputsForItem(baseInputs, sourceItem)
      }
      const node_overrides: Record<string, { prompt?: string }> = usePrompt
        ? { '*': { prompt } } : {}
      const submitted = await api.runWorkflowAsync(ref.slug, {
        version: ref.version, project_id: projectId, inputs: childInputs,
        force: ['*'], node_overrides,
        run_mode: 'single', run_node: node.id,
      })
      runId = submitted.run_id
      say(`已调用引用工作流「${ref.slug}」，run #${runId}`, 'info')
    } else {
      const elementId = Number(sourceItem.element_id)
      if (!childNodeKey || !Number.isFinite(elementId) || elementId <= 0) {
        throw new Error('当前循环产物缺少可定位的要素 ID，无法只运行这一项')
      }
      const node_overrides: Record<string, { prompt?: string }> = usePrompt
        ? { [childNodeKey]: { prompt } } : {}
      const submitted = await api.runWorkflowAsync(slug!, {
        version, project_id: projectId,
        inputs: {
          ...baseInputs,
          source_type: 'explicit.element_ids',
          source_ref: undefined,
          related_element_ids: [elementId],
        },
        force: [childNodeKey], node_overrides,
        run_mode: 'single', run_node: node.id,
      })
      runId = submitted.run_id
      say(`已只提交当前要素，run #${runId}`, 'info')
    }

    const t0 = Date.now()
    while (!dead.current && Date.now() - t0 < TIMEOUT_MS) {
      const [detail, rows] = await Promise.all([
        api.workflowRun(runId), api.workflowRunNodes(runId),
      ])
      const relevantRows = ref?.slug ? rows : rows.filter(row => row.node_key === childNodeKey)
      const latestOutputs = generationOutputs(detail.outputs, relevantRows)
      updateRuntimeOutput(node.id, latestOutputs)
      const failed = relevantRows.find(row => row.status === 'failed')
      if (detail.status === 'done' && !failed) {
        let completedOutputs = latestOutputs
        const elementId = itemElementId(sourceItem)
        if (projectId && elementId) {
          try {
            const element = (await api.getElements(projectId)).find(item => item.id === elementId)
            if (element?.meta.sheet_url) {
              completedOutputs = { ...completedOutputs, url: element.meta.sheet_url }
              updateRuntimeOutput(node.id, completedOutputs)
            }
          } catch { /* The workflow output remains visible if the business object cannot be refreshed. */ }
        }
        setRuntimeNodes(xs => xs.map(n => n.id === node.id ? {
          ...n, status: undefined, done: true, error: undefined, badge: undefined,
          stage: qcBadge(completedOutputs),
        } : n))
        say(`${node.title}：重新生成完成`, 'ok')
        return
      }
      if (detail.status === 'failed' || failed) {
        const error = detail.error || failed?.error || '生成失败'
        setRuntimeNodes(xs => xs.map(n => n.id === node.id ? {
          ...n, status: undefined, error, badge: { label: '失败', tone: 'err' },
          stage: qcBadge(latestOutputs) ?? { label: '失败', tone: 'err' },
        } : n))
        say(`${node.title} 失败：${error}`, 'err')
        return
      }
      await sleep(POLL_MS)
    }
    if (!dead.current) throw new Error('等待生成结果超时，请稍后在运行记录里查看')
  }, [say, slug, updateRuntimeOutput, version])

  /** 通用 gen 节点的产物补丁：装配出的最终提示词与参考图直接填进生成条。 */
  const genPatch = (n: TapNode, o: Record<string, unknown>): Partial<TapNode> => {
    // subflow 卡（首帧/视频编排产物）与 gen 同通道：不回填的话打开画布
    // 生成条永远是空框（首帧的提示词只存在于子画布运行结果里）
    if (!isGenType(n.type) && n.type !== 'subflow') return {}
    // subflow 没有自己的 gen 配置：params 不预置图片专属参数，避免首帧卡
    // 参数条出现“自适应(4K)”这种与产物无关的假参数
    const base = { model: '系统出图模型',
      params: n.type === 'subflow' ? [] : ['自适应(4K)'], prompt: '', refs: [], ...n.gen }
    const next = { ...base }
    // 生成条只回显**用户需求层**（画布作者配的默认指令/上次的输入）；系统层
    //（上文/装配叙事/系统提示词）实跑时隐式挂载，不进输入框。空回显不覆盖
    // 用户正在输入的内容
    if (!n.gen?.edited && typeof o.prompt === 'string' && o.prompt) next.prompt = o.prompt
    if (Array.isArray(o.reference_images)) {
      next.refs = (o.reference_images as { url?: string }[]).map(r => r.url ?? '').filter(Boolean)
    }
    return { gen: next }
  }

  /** 装配节点的产物 → 图片节点的生成条（提示词 + 参考图缩略图）。
   * 该节点本身不画在画布上（ui.hide），提示词跟着图片走，选中图片炸开即可见。 */
  const feedGen = useCallback((target: string, o: Record<string, unknown>) => {
    const t = getState().nodes.find(n => n.id === target)
    if (!t) return
    const prompt = typeof o.prompt === 'string' && o.prompt ? o.prompt : undefined
    const refs = Array.isArray(o.reference_images)
      ? (o.reference_images as { url?: string }[]).map(r => r.url ?? '').filter(Boolean)
      : undefined
    if (!prompt && !refs) return
    patch(target, {
      gen: {
        model: '系统出图模型', params: ['自适应(4K)'], refs: [], prompt: '',
        ...t.gen, ...(prompt ? { prompt } : {}), ...(refs ? { refs } : {}),
      },
    })
  }, [getState, patch])

  /** 单节点状态 → 画布补丁 + 日志(seen 防止同状态重复报) */
  const applyNode = useCallback((key: string, status: string, outputs: Record<string, unknown>,
                                 skipReason?: string, error?: string) => {
    // 先喂生成条：装配节点不在画布上，下面的 find 会落空，但它的产物必须送达
    if (status === 'done' && feedsRef.current[key]) feedGen(feedsRef.current[key], outputs)
    const n = getState().nodes.find(x => x.id === key)
    if (!n) return
    // 日志里的节点名与卡片标题同源（都带出本次运行的对象名），否则一边写着
    // 「场景介绍 · 浮空灯塔」、一边写「场景介绍 · {{input.scene_name}}」
    const name = resolveTitle(n.title, titleVars(getState().nodes))
    if (status === 'running') {
      // 所有类型都标执行中：画布上「跑到哪了」靠这圈流光边框，
      // 只给出图节点标的话，取数/LLM/质检那几步在画布上完全看不出动静
      patch(key, {
        status: 'generating', done: false, error: undefined,
        ...(n.type === 'tool' ? { runtimeResult: undefined } : {}),
        // outputs.phase 是节点内部的子阶段（装配/质检/出图），后端每换一段就写一次
        stage: { label: String(outputs.phase || '执行中'), tone: 'run' },
      })
      say(`${name} 执行中…`)
    } else if (status === 'done') {
      const url = [outputs.url, outputs.sheet_url, outputs.value]
        .find(v => typeof v === 'string' && v) as string | undefined
      if (isGenType(n.type)) {
        patch(key, {
          status: undefined, done: true, badge: undefined, ...genMediaPatch(n, url),
          stage: qcBadge(outputs), ...genPatch(n, outputs),
        })
      } else if (n.type === 'qc') {
        const ok = outputs.exists !== false
        patch(key, { status: undefined, done: ok, qc: { ...n.qc, state: ok ? 'pass' : 'fail' } })
      } else if (n.type === 'text') {
        // 取数/装配/LLM 类节点:真实产物直出到卡上
        patch(key, {
          status: undefined, done: true, badge: undefined,
          ...(textOf(key, outputs) ? { text: textOf(key, outputs) } : {}),
        })
      } else if (n.type === 'tool') {
        patch(key, {
          status: undefined, done: true, badge: undefined,
          runtimeResult: runtimeResult(outputs),
        })
      } else if (n.type === 'condition') {
        patch(key, {
          status: undefined, done: true, badge: undefined,
          condition: { ...n.condition, matchedBranch: typeof outputs.matched_branch === 'string' ? outputs.matched_branch : undefined },
          runtimeResult: runtimeResult(outputs),
        })
      } else if (n.type === 'mount') {
        // 挂载点：回显它当前指向的产物（真实数据指向这个节点），
        // stored/unchanged/version 一并带上——卡上要能看出「本次新落」还是「已指向」
        const url = typeof outputs.url === 'string' ? outputs.url : undefined
        patch(key, {
          status: undefined, done: true, badge: undefined,
          mount: {
            ...n.mount, target: String(outputs.target ?? n.mount?.target ?? ''),
            ...(url ? { url } : {}),
            ...(typeof outputs.version === 'number' ? { version: outputs.version } : {}),
            ...(typeof outputs.source_node === 'string' ? { sourceNode: outputs.source_node } : {}),
            ...(outputs.unchanged ? { unchanged: true } : {}),
            ...(typeof outputs.stored === 'string' ? { stored: outputs.stored } : {}),
          },
        })
      } else patch(key, { status: undefined, done: true, badge: undefined })
      // 提示词分析（提案 A）：后端在出图/出视频**前**让规划模型先检查需求与材料，
      // 分析要点随产物返回——在 run 卡明细里单列一行，让「为什么这么画」看得见
      const analysis = typeof outputs.prompt_analysis === 'string' ? outputs.prompt_analysis.trim() : ''
      if (analysis) {
        for (const line of analysis.split('\n').map(x => x.trim().replace(/^[-•·]\s*/, '')).filter(Boolean)) {
          say(`提示词分析：${line}`, 'info')
        }
      }
      say(`${name} 完成${isGenType(n.type) ? ',产物已入素材库' : ''}`, 'ok')
    } else if (status === 'skipped') {
      // 跳过时后端把**库里已有的那份产物**一并带回来了（文本/图片 url），
      // 照样回填上卡——否则卡上带个对勾、内容还是占位符，等于什么都没交代
      // Reused products use the same output shape as completed generation
      // nodes. Keep every media URL variant here (sheet_url is used by the
      // core-element canvas) so an upstream node that was skipped from the
      // current run still renders its existing image for downstream refs.
      const url = isGenType(n.type) || n.type === 'subflow'
        ? [outputs.url, outputs.sheet_url, outputs.image_url, outputs.video_url,
           outputs.keyframe_url, outputs.value]
          .find(v => typeof v === 'string' && v) as string | undefined
        : undefined
      const t = n.type === 'text' ? textOf(key, outputs) : undefined
      patch(key, {
        status: undefined, done: true,
        badge: { label: '跳过', tone: 'skip' },
        ...genMediaPatch(n, url), ...(t ? { text: t } : {}),
        ...genPatch(n, outputs),
        ...(n.type === 'tool' ? { runtimeResult: runtimeResult(outputs) } : {}),
      })
      say(`${name}:${skipReason || '已有产物,跳过(缺才跑)'}`, 'info')
    } else if (status === 'failed') {
      // 质检没过导致的失败：徽标留分数，比一句「执行失败」说得清
      patch(key, {
        status: undefined, error: error || '执行失败',
        ...(n.type === 'tool' ? { runtimeResult: undefined } : {}),
        badge: { label: '失败', tone: 'err' },
        stage: qcBadge(outputs) ?? { label: '失败', tone: 'err' },
      })
      say(`${name} 失败:${error || '未知错误'}`, 'err')
    }
  }, [getState, patch, say, feedGen])

  // 整图始终从前往后跑，默认全「缺才跑」（有产物就取回来用，缺了才生成）。
  // 运行范围只决定两件事：从哪个节点起强制重跑、跑到哪个节点为止。
  /** send：生成条发送的两种语义——verbatim=照搬框里这段；rewrite=重写提示词再出图 */
  const run = useCallback(async (range?: TapRunRange, forceAll = false,
                                 send?: TapRunOptions) => {
    if (runningRef.current || !slug) return
    const { inputs, projectId, missing } = startInputs(getState().nodes)
    if (missing.length) {
      setLog(ls => [...ls, { t: now(), text: `请先填必填入参:${missing.join('、')}`, kind: 'err' }])
      return
    }
    const { nodes: cur, edges } = getState()
    const singleNodeId = send?.mode === 'single' ? send.nodeId : undefined
    // A single-node request still executes any missing upstream dependencies.
    // Keep those rows in the live projection so their running/skip/done state
    // is visible and their media is fed into the requested node. Previously
    // the poller hid every row except the target, making the canvas look idle
    // while the backend was correctly preparing dependencies.
    const singleVisibleIds = singleNodeId
      ? new Set([...upstreamNodes(singleNodeId, cur, edges).map(n => n.id), singleNodeId])
      : undefined
    const projectedNode = singleNodeId
      ? runtimeNodes.find(node => node.id === singleNodeId) : undefined
    if (send?.mode === 'single' && !singleNodeId) {
      setLog(ls => [...ls, { t: now(), text: '单节点运行缺少目标节点', kind: 'err' }])
      return
    }
    if (singleNodeId && !cur.some(n => n.id === singleNodeId) && !projectedNode) {
      setLog(ls => [...ls, { t: now(), text: `找不到要运行的节点：${singleNodeId}`, kind: 'err' }])
      return
    }
    if (projectedNode) {
      previewEpoch.current += 1
      runningRef.current = true
      setRunning(true)
      setLog([{ t: now(), text: `单节点运行：${projectedNode.title}（强制重新生成，不跳过）`, kind: 'info' }])
      try {
        await runProjectedNode(projectedNode, send, inputs, projectId)
      } catch (e) {
        const error = e instanceof Error ? e.message : String(e)
        setRuntimeNodes(xs => xs.map(n => n.id === projectedNode.id ? {
          ...n, status: undefined, error, badge: { label: '失败', tone: 'err' },
        } : n))
        say(`运行异常：${error}`, 'err')
      } finally {
        runningRef.current = false
        setRunning(false)
      }
      return
    }
    const { force, stopAfter } = rangeToRun(cur, edges, range, forceAll, singleNodeId)
    const singleNode = singleNodeId ? cur.find(n => n.id === singleNodeId) : undefined
    previewEpoch.current += 1
    runningRef.current = true
    setRunning(true)
    // Preserve cached products while the next run is preparing. Projection
    // updates replace individual loop iterations and trigger a fresh layout.
    setProjectionRevision(x => x + 1)
    const runLabel = singleNodeId
      ? `单节点运行：${cur.find(n => n.id === singleNodeId)?.title ?? singleNodeId}（强制重新生成，不跳过）`
      : `全量运行：${slug}`
    setLog([{ t: now(), text: runLabel, kind: 'info' }])
    const vars = titleVars(cur)
    const titleOf = (id?: string | null) =>
      resolveTitle(cur.find(n => n.id === id)?.title ?? '', vars)
    if (singleNodeId) {
      say(`${titleOf(singleNodeId)}：强制重新生成（人工点击，不跳过）`, 'info')
    } else if (force.length) {
      say(`从「${titleOf(range?.from)}」起强制重跑（之前的仍缺才跑）`, 'info')
    }
    if (stopAfter) say(`跑到「${titleOf(stopAfter)}」为止`, 'info')
    try {
      // flow（引用另一张流程）同样在列：它炸开的生成条里那句话不是出图提示词，
      // 而是**给子流程规划器的指令**——后端按 instruction 判子图里哪几步要重生成。
      // 漏了它，智能节点上打了字点生成，后端收到的是空指令，等于整图重跑。
      const runnablePrompts = getState().nodes.filter(
        n => isGenType(n.type) || n.type === 'text' || n.type === 'qc' || n.type === 'flow')
      // 手编的一律整段覆盖,没改的让后端照常跑
      // (装配/模型能跟上画风库与设定的更新,原样回传反而会把旧版本钉死)
      const node_overrides: Record<string,
        { prompt?: string; instruction?: string; text?: string; ref_nodes?: string[] }> = {}
      if (singleNodeId && send?.promptOverride?.trim()) {
        node_overrides[singleNodeId] = singleNode && isGenType(singleNode.type)
          ? { prompt: send.promptOverride.trim() }
          : { instruction: send.promptOverride.trim() }
      }
      const includeOverride = (id: string) => !singleNodeId || id === singleNodeId
      // 生成条里手选的参考节点：只用这几个上游，不再无差别收全部入边
      for (const n of getState().nodes) {
        if (includeOverride(n.id) && n.gen?.refNodes) {
          node_overrides[n.id] = { ...node_overrides[n.id], ref_nodes: n.gen.refNodes }
        }
      }
      for (const g of runnablePrompts) {
        if (!includeOverride(g.id)) continue
        const p = (g.id === singleNodeId ? send?.promptOverride : undefined)?.trim()
          || (g.gen?.prompt ?? '').trim()
        // 三种语义分清楚：
        //  · send.rewrite 命中 → **不送提示词**，让后端重新写一遍再出图（勾了「重写提示词」）
        //  · send.verbatim 命中 → 一律照框里这段出图，不管改没改（生成条默认发送）
        //  · 全局运行 → 只覆盖手改过的；没改的让装配跟上画风库与设定的更新，
        //    原样回传反而把旧版本钉死
        if (g.id === send?.rewrite) continue
        if (p && (g.id === send?.verbatim || g.gen?.edited)) {
          // 媒体节点把输入框内容当最终出图提示词；文本/质检节点则把同一个输入框
          // 当本次模型指令。以前这里只遍历媒体节点，新建 Text 点击发送时后端 task
          // 仍是空串，模型只能返回「消息可能为空」的兜底回复。
          node_overrides[g.id] = {
            ...node_overrides[g.id],
            ...(isGenType(g.type) ? { prompt: p } : { instruction: p }),
          }
        }
      }
      // 文本节点(场景介绍这类)手改过:模型不跑,改的那份直接当产出并落库——
      // 否则改了画布上的文字,重跑出来的图还是按库里旧介绍画的,还看不出为什么
      for (const t of getState().nodes) {
        const v = (t.text ?? '').trim()
        if (includeOverride(t.id) && t.type === 'text' && t.textEdited && v) {
          node_overrides[t.id] = { text: v }
        }
      }
      if (Object.keys(node_overrides).length) {
        say(`生成条需求将参与本次生成:${Object.keys(node_overrides).join('、')}`, 'info')
      }
      const { run_id } = await api.runWorkflowAsync(slug, {
        version, project_id: projectId, inputs,
        force, stop_after: stopAfter, node_overrides,
        // 引擎不读这两个，是留给下次打开画布回填「上次怎么跑的」
        force_all: forceAll, run_range: { from: range?.from ?? null, to: range?.to ?? null },
        run_mode: singleNodeId ? 'single' : 'all', run_node: singleNodeId,
      })
      say(`已提交,run #${run_id},轮询进度…`, 'info')
      const seen = new Map<string, string>()
      const t0 = Date.now()
      while (!dead.current && Date.now() - t0 < TIMEOUT_MS) {
        const [run, nodes] = await Promise.all([
          api.workflowRun(run_id), api.workflowRunNodes(run_id)])
        for (const nr of nodes) {
          const targetLoopBody = singleNode?.type === 'loop'
            && singleNode.loop?.body?.includes(nr.node_key)
          if (singleNodeId && !targetLoopBody
              && !singleVisibleIds?.has(nr.node_key)) continue
          const k = `${nr.node_key}#${nr.iteration}`
          const aggregateSubflow = getState().nodes.find(n => n.id === nr.node_key
            && n.loop?.aggregate && n.bind?.subflow?.slug)
          // The parent row can remain "running" while child nodes advance. Poll the
          // exact child run on every cycle instead of suppressing it by parent status.
          if (aggregateSubflow && nr.subrun_id) {
            await projectChildRun(aggregateSubflow, nr.subrun_id)
          }
          const signature = `${nr.status}:${nr.subrun_id ?? ''}`
          if (seen.get(k) === signature) continue
          seen.set(k, signature)
          // loop 母节点及其 body 的 node_run 都带 iteration。编排态只保留一张母卡，
          // 运行态把这些 iteration 投影成实例列表，而不是把母卡反复标成“完成”。
          const loop = getState().nodes.find(n => n.type === 'loop'
            && (n.id === nr.node_key || n.loop?.body?.includes(nr.node_key)))
          if (loop) {
            const input = jsonbObj(nr.inputs)
            const item = input.item
            const old = loop.loop?.instances?.find(x => x.iteration === nr.iteration)
            const label = item && typeof item === 'object'
              ? String((item as Record<string, unknown>).name
                ?? (item as Record<string, unknown>).title ?? `第 ${nr.iteration + 1} 项`)
              : item != null ? String(item) : old?.label ?? `第 ${nr.iteration + 1} 项`
            let outputs = jsonbObj(nr.outputs)
            const bodyNode = getState().nodes.find(n => n.id === nr.node_key)
            const subflow = bodyNode?.bind?.subflow?.slug ? {
              slug: bodyNode.bind.subflow.slug,
              version: bodyNode.bind.subflow.version,
            } : undefined
            if (subflow?.slug && nr.subrun_id) {
              try {
                outputs = { ...outputs, ...await readSubrunOutputs(nr.subrun_id) }
              } catch { /* Keep the parent node output while the child is starting. */ }
            }
            projectLoopInstance(loop, nr.node_key, nr.iteration, label, nr.status, outputs,
              nr.error, nr.subrun_id, subflow)
            const src = [outputs.url, outputs.sheet_url, outputs.value]
              .find(v => typeof v === 'string' && v) as string | undefined
            const prev = loop.loop?.instances ?? []
            const instance = {
              iteration: nr.iteration, label, status: nr.status as 'running' | 'done' | 'skipped' | 'failed',
              ...((src ?? old?.src) ? { src: src ?? old?.src } : {}),
              ...(nr.error ? { error: nr.error } : old?.error ? { error: old.error } : {}),
            }
            const instances = [...prev.filter(x => x.iteration !== nr.iteration), instance]
              .sort((a, b) => a.iteration - b.iteration)
            patch(loop.id, {
              loop: { ...loop.loop, instances },
              status: instances.some(x => x.status === 'running') ? 'generating' : undefined,
              done: instances.length > 0 && instances.every(x => x.status === 'done' || x.status === 'skipped'),
              error: instances.some(x => x.status === 'failed') ? '部分实例失败' : undefined,
            })
            continue
          }
          applyNode(nr.node_key, nr.status, jsonbObj(nr.outputs), nr.skip_reason, nr.error)
        }
        if (run.status === 'done') {
          const outs = jsonbObj(run.outputs)
          // 跳过的生成节点没有本次产物 url——用整体 outputs 的 sheet_url 回显
          const url = typeof outs.sheet_url === 'string' ? outs.sheet_url : undefined
          if (url) {
            const fallbackNodes = singleNodeId
              ? getState().nodes.filter(n => n.id === singleNodeId)
              : getState().nodes
            for (const n of fallbackNodes) {
              if (isGenType(n.type) && !n.src) patch(n.id, { src: url, done: true })
            }
          }
          say('运行结束', 'ok')
          return
        }
        if (run.status === 'failed') {
          say(`运行失败:${run.error || '未知错误'}`, 'err')
          return
        }
        await sleep(POLL_MS)
      }
      if (!dead.current) say('等待超时,请稍后在运行记录里查看', 'err')
    } catch (e) {
      say(`运行异常:${e instanceof Error ? e.message : String(e)}`, 'err')
    } finally {
      runningRef.current = false
      setRunning(false)
      // 收尾兜底：本次没跑到的节点可能还挂着上一轮留下的「执行中」徽标
      // （范围跑只覆盖一段，范围外的节点这一轮压根没有状态更新）。
      // 运行已经结束了，屏幕上就不该再有转圈的东西。
      for (const n of getState().nodes) {
        if (n.status === 'generating' || n.stage?.tone === 'run') {
          patch(n.id, { status: undefined, stage: undefined })
        }
      }
    }
  }, [slug, version, getState, patch, say, applyNode, projectLoopInstance,
      projectChildRun, readSubrunOutputs, runProjectedNode, runtimeNodes])

  /** 按节点分别回填最近一次产物与质检结论。
   *
   * 数据本来就存着（workflow_node_runs.outputs.qc），只是没人来取：预检只探
   * 「库里有没有产物」，读不到历史运行的判定。结果是打开画布看到一张图，
   * 却不知道它上次判了多少分、卡在哪一条——而这正是决定"要不要重出"的依据。
   *
   * 不能只读最后一轮 run：分支 A、B 分别单独生成后，最后一轮没有 A；必须后端按
   * node_key 各取最新一条，重开时才能恢复整张画布。 */
  const restoreLatest = useCallback(async () => {
    if (!slug) return
    try {
      const currentNodes = getState().nodes
      const { inputs, projectId } = startInputs(currentNodes)
      let latestRows: WorkflowNodeRun[]
      const qcHistory = new Map<string, NonNullable<TapNode['stage']>>()

      if (projectId) {
        const latestByNode = new Map<string, WorkflowNodeRun>()
        const restorableIds = new Set(currentNodes.filter(n => n.type !== 'start').map(n => n.id))
        const qcTargetIds = new Set(currentNodes
          .filter(n => isGenType(n.type) && n.bind?.qc?.on).map(n => n.id))
        const candidates = (await api.workflowRuns(projectId)).filter(run =>
          (run.slug === slug && (version === undefined || run.version === version))
          || (!!historySlug && run.slug === historySlug))

        for (const candidate of candidates) {
          const detail = await api.workflowRun(candidate.id)
          if (!sameRunContext(inputs, jsonbObj(detail.inputs))) continue
          for (const row of await api.workflowRunNodes(candidate.id)) {
            if (!latestByNode.has(row.node_key)) latestByNode.set(row.node_key, row)
            const badge = qcBadge(jsonbObj(row.outputs))
            if (badge && !qcHistory.has(row.node_key)) qcHistory.set(row.node_key, badge)
          }
          const hasLatestRows = [...restorableIds].every(id => latestByNode.has(id))
          const hasQcRows = [...qcTargetIds].every(id => qcHistory.has(id))
          if (hasLatestRows && hasQcRows) break
        }
        latestRows = [...latestByNode.values()]
      } else {
        latestRows = await api.workflowLatestNodes(slug, version)
        if (!latestRows.length && historySlug) {
          latestRows = await api.workflowLatestNodes(historySlug)
        }
      }

      for (const nr of latestRows) {
        const outputs = jsonbObj(nr.outputs)
        // A later manual run may contain the newest image but omit QC metadata.
        // Keep the most recent persisted verdict for this same business object.
        const badge = qcHistory.get(nr.node_key) ?? qcBadge(outputs)
        const n = getState().nodes.find(x => x.id === nr.node_key)
        if (!n) continue
        if (n.loop?.aggregate && n.bind?.subflow?.slug && nr.subrun_id) {
          await projectChildRun(n, nr.subrun_id)
        }
        const p: Partial<TapNode> = badge ? { stage: badge } : {}
        // graph 保存“怎么生成”，node_runs 保存“上次生成了什么”。重开时把最后产物投影回来。
        if (nr.status === 'done' || nr.status === 'skipped') {
          if (isGenType(n.type) || n.type === 'subflow') {
            const url = [outputs.url, outputs.sheet_url, outputs.value, outputs.keyframe_url]
              .find(v => typeof v === 'string' && v) as string | undefined
            Object.assign(p, { done: true, ...genMediaPatch(n, url), ...genPatch(n, outputs) })
          } else if (n.type === 'text') {
            const text = textOf(nr.node_key, outputs)
            if (text) Object.assign(p, { done: true, text })
          } else if (n.type === 'tool') {
            Object.assign(p, { done: true, runtimeResult: runtimeResult(outputs) })
          }
        }
        if (Object.keys(p).length) patch(nr.node_key, p)
      }
    } catch { /* 取不到就算了，历史结论缺失不该挡住画布打开 */ }
  }, [slug, version, historySlug, getState, patch, projectChildRun])

  /** 预检(零副作用):打开运行态/参数齐了就回显已有产物。
   * reloadId = 工具条「重新读取」点的那个节点:它是用户主动要求以库为准,
   * 手编冻结对它不生效(否则点了没反应,还以为库里就是屏幕上这份)。 */
  const preview = useCallback(async (reloadId?: string) => {
    if (!slug || runningRef.current) return
    const { inputs, missing } = startInputs(getState().nodes)
    if (missing.length) return
    const requestEpoch = ++previewEpoch.current
    const isCurrent = () => requestEpoch === previewEpoch.current && !runningRef.current
    try {
      const r = await api.previewWorkflow(slug, { version, inputs })
      if (!isCurrent()) return
      const currentElementUrls = new Map<number, string>()
      const currentProjectId = Number(inputs.project_id)
      if (Number.isFinite(currentProjectId) && currentProjectId > 0) {
        try {
          for (const element of await api.getElements(currentProjectId)) {
            if (element.meta.sheet_url) currentElementUrls.set(element.id, element.meta.sheet_url)
          }
        } catch { /* Workflow preview still provides a usable fallback image. */ }
      }
      let latestRows: WorkflowNodeRun[] = []
      try {
        const latest = await api.workflowLastRun(slug)
        const latestInputs = jsonbObj(latest?.inputs)
        if (latest && String(latestInputs.project_id ?? '') === String(inputs.project_id ?? '')) {
          latestRows = await api.workflowRunNodes(latest.id)
        }
      } catch { /* Existing products from preview are still enough to render the cards. */ }
      if (!isCurrent()) return
      // 选定分镜后的只读预检已经能拿到 elements.items：立即投影循环实例。
      // 执行按钮只负责补齐缺图并继续下游，不再承担“看见关联要素”的职责。
      let projectedCount = 0
      const projectedIds = new Set<string>()
      const projectedOwners = new Set<string>()
      for (const loop of getState().nodes.filter(n => n.loop?.aggregate)) {
        const child = loop.bind?.subflow?.slug
          ? await childWorkflow(loop) : await currentWorkflow()
        if (!isCurrent()) return
        const source = loop.loop?.source?.match(/^\{\{\s*([^.}\s]+)\.([^.}\s]+)\s*\}\}$/)
        if (!source) continue
        let items: unknown
        if (source[1] === '@in') {
          // The backend preview is canonical for fan-in semantics. The edge
          // aggregation fallback keeps older servers compatible.
          const loopPreview = r.nodes[loop.id]
          const loopOutputs = loopPreview?.outputs
            ?? (loopPreview?.value != null ? { value: loopPreview.value } : {})
          const previewItems = (loopOutputs as Record<string, unknown>).items
          if (Array.isArray(previewItems)) {
            items = previewItems
          } else {
            const inbound = getState().edges
              .filter(edge => edge.to === loop.id)
              .map(edge => edge.from)
            items = inbound.flatMap(nodeId => {
              const sourcePreview = r.nodes[nodeId]
              const sourceOutputs = sourcePreview?.outputs
                ?? (sourcePreview?.value != null ? { value: sourcePreview.value } : {})
              const value = (sourceOutputs as Record<string, unknown>)[source[2]]
              if (value == null) return []
              return Array.isArray(value) ? value : [value]
            })
          }
        } else {
          const sourcePreview = r.nodes[source[1]]
          const sourceOutputs = sourcePreview?.outputs
            ?? (sourcePreview?.value != null ? { value: sourcePreview.value } : {})
          items = (sourceOutputs as Record<string, unknown>)[source[2]]
        }
        // A loop aggregate is still a visible downstream structure when its
        // source is blocked, pending, or empty.  Project one virtual child so
        // users can see where resolved resources will appear after upstream
        // inputs become available, rather than making the whole column vanish.
        if (!Array.isArray(items) || items.length === 0) {
          projectedIds.add(runtimeNodeId(loop.id, 'pending', 0))
          projectedOwners.add(loop.id)
          projectLoopInstance(loop, 'pending', 0, '等待查询关联资源', 'pending', {})
          projectedCount += 1
          continue
        }
        const historicItems = new Map<number, Record<string, unknown>>()
        for (const row of latestRows.filter(row => row.node_key === loop.id)) {
          const item = jsonbObj(row.inputs).item
          if (item && typeof item === 'object') {
            historicItems.set(row.iteration, item as Record<string, unknown>)
          }
        }
        for (let iteration = 0; iteration < items.length; iteration += 1) {
          const raw = items[iteration]
          const item: Record<string, unknown> = raw && typeof raw === 'object'
            ? raw as Record<string, unknown> : { value: raw }
          const label = String(item.name ?? item.title ?? item.role ?? `第 ${iteration + 1} 项`)
          const childNodeKey = childNodeForItem(child, item)
          const subflow = subflowRefForNode(child, childNodeKey)
          const childInputs = subflowInputsForItem(inputs, item)
          const identity = itemIdentity(item)
          const historic = latestRows.find(row => row.node_key === childNodeKey
            && (identity
              ? itemIdentity(historicItems.get(row.iteration)) === identity
              : row.iteration === iteration))
          let outputs: Record<string, unknown> = subflow?.slug
            ? (mediaUrl(item) ? { url: mediaUrl(item) } : {})
            : item
          if (historic) outputs = { ...outputs, ...jsonbObj(historic.outputs) }
          let sourceRunId = historic?.subrun_id
          if (subflow?.slug && !sourceRunId) {
            const attachmentId = itemAttachmentId(item)
            if (attachmentId) {
              try {
                const source = await api.workflowArtifactSource(attachmentId)
                const elementId = itemElementId(item)
                const sameWorkflow = source?.slug === subflow.slug
                  || source?.origin_slug === subflow.slug
                const sameTarget = !elementId
                  || (source?.target_kind === 'element' && source.target_id === elementId)
                if (source && sameWorkflow && sameTarget) sourceRunId = source.workflow_run_id
              } catch { /* An asset without workflow provenance can still use child preview. */ }
            }
          }
          if (subflow?.slug && sourceRunId) {
            try {
              outputs = { ...outputs, ...await readSubrunOutputs(sourceRunId) }
            } catch { /* The parent output still contains the last known media. */ }
          }
          if (subflow?.slug && !qcBadge(outputs)) {
            outputs = {
              ...outputs,
              ...await latestSubflowQc(subflow, childInputs,
                Number.isFinite(currentProjectId) && currentProjectId > 0
                  ? currentProjectId : undefined),
            }
          }
          if (subflow?.slug && typeof outputs.prompt !== 'string') {
            try {
              const childPreview = await api.previewWorkflow(subflow.slug, {
                version: subflow.version,
                inputs: childInputs,
              })
              for (const previewNode of Object.values(childPreview.nodes)) {
                const previewOutputs = previewNode.outputs
                  ?? (previewNode.value != null ? { value: previewNode.value } : {})
                if (typeof previewOutputs.prompt === 'string' && previewOutputs.prompt.trim()) {
                  outputs.prompt = previewOutputs.prompt
                }
                if (Array.isArray(previewOutputs.reference_images)) {
                  outputs.reference_images = previewOutputs.reference_images
                }
                const url = directMediaUrl(previewOutputs)
                if (url) outputs.url = url
              }
            } catch { /* Keep the existing asset visible even if child preview is unavailable. */ }
          }
          if (!isCurrent()) return
          const currentElementUrl = currentElementUrls.get(itemElementId(item) ?? -1)
          if (currentElementUrl) outputs.url = currentElementUrl
          projectedIds.add(runtimeNodeId(loop.id, childNodeKey, iteration))
          projectedOwners.add(loop.id)
          projectLoopInstance(loop, childNodeKey, iteration, label,
            historic?.status ?? (mediaUrl(item) ? 'done' : 'pending'), outputs,
            historic?.error, sourceRunId, subflow, item)
          projectedCount += 1
        }
      }
      // 同一事件循环内的实例 state 会被 React 批处理；revision 与完整集合一起提交，
      // 重排看到的是最终 N，而不是第 1、2、3 个实例逐次出现的中间态。
      if (!isCurrent()) return
      // Keep the old projection visible while async child history is resolving.
      // Only a complete, current preview may remove nodes that no longer belong
      // to the selected parameters.
      setRuntimeNodes(xs => xs.filter(node => projectedIds.has(node.id)))
      setRuntimeEdges(xs => xs.filter(edge =>
        projectedIds.has(edge.from) || projectedIds.has(edge.to)))
      setRuntimeLoopOwners([...projectedOwners])
      if (projectedCount > 0) setProjectionRevision(x => x + 1)
      // 装配节点在预检里真执行(只读),提示词与参考图直接进图片的生成条;
      // 它探不出来时(如场景还没建)退回 element.find 存的上次装配结果
      if (!isCurrent()) return
      for (const [key, pv] of Object.entries(r.nodes)) {
        // task/subflow 的预检只探 skip_if，探到的产物在 pv.value 里、没有 outputs
        // （见 workflow.preview_workflow）。归一成 {value} 交给 textOf——
        // 不兜这一支，引用最小集的文本卡（场景介绍）打开画布就永远停在占位符，
        // 真跑一遍才显示（run 的 skipped 分支读的正是 outputs.value）
        const outs = pv.outputs ?? (pv.value != null ? { value: pv.value } : {})
        if (feedsRef.current[key]) feedGen(feedsRef.current[key], outs)
        else if (typeof outs.sheet_prompt === 'string' && outs.sheet_prompt) {
          for (const g of getState().nodes.filter(n => isGenType(n.type) && !n.gen?.prompt)) {
            feedGen(g.id, { prompt: outs.sheet_prompt, reference_images: outs.extra_refs })
          }
        }
        const n = getState().nodes.find(x => x.id === key)
        if (!n) continue
        if (n.type === 'text') {
          // 手改过就冻结，与生成条 gen.edited 同一语义（预检是防抖跑的，
          // 不设防就会在用户打字后把库里那份旧介绍盖回去）
          const t = n.textEdited && key !== reloadId ? undefined : textOf(key, outs)
          if (t) {
            patch(key, {
              text: t, ...(pv.exists ? { done: true } : {}),
              // 以库为准了，冻结标记跟着解除：不解的话下次运行还会拿屏幕上这份去覆盖
              ...(key === reloadId ? { textEdited: false } : {}),
            })
          }
        }
        if (isGenType(n.type) || n.type === 'subflow') {
          // 装配器零副作用,所以预检就能算出即将提交的那份提示词与参考图。
          // subflow（如「首帧（缺才跑）」）走同一条通道：后端已把子画布探到的
          // 已有产物提升为 exists/value，这里照 gen 回显，否则打开画布永远空占位。
          const url = pv.exists && typeof pv.value === 'string' ? pv.value : directMediaUrl(outs)
          // subflow 的装配提示词不在 end.outputs 里（那是产物合同），在子画布
          // gen 节点的运行输出里——从 child_preview 提取，首帧卡的生成条
          // 才能带出“生成这张首帧所用的提示词”（用户改过则冻结不覆盖）
          let promptOuts = outs
          if (n.type === 'subflow') {
            const cpNodes = (pv as { child_preview?: { nodes?: Record<string, { outputs?: Record<string, unknown> }> } })
              .child_preview?.nodes
            const childGen = cpNodes?.gen?.outputs
            if (childGen) promptOuts = { ...childGen, ...outs }
          }
          patch(key, {
            ...(url ? { src: url, done: true } : {}),
            ...genPatch(n, promptOuts),
          })
        }
        if (n.type === 'qc' && typeof outs.exists === 'boolean') {
          patch(key, { qc: { ...n.qc, state: outs.exists ? 'pass' : 'idle' } })
        }
        if (n.type === 'tool' && Object.keys(outs).length) {
          patch(key, { done: true, runtimeResult: runtimeResult(outs) })
        }
        if (n.type === 'condition' && Object.keys(outs).length) {
          patch(key, {
            done: true,
            condition: { operator: n.condition?.operator ?? 'truthy', ...n.condition, matched: outs.matched === true },
            runtimeResult: runtimeResult(outs),
          })
        }
      }
    } catch { /* 预检尽力而为,失败不打扰 */ }
  }, [slug, version, getState, patch, feedGen, childWorkflow, currentWorkflow,
      projectLoopInstance, readSubrunOutputs, latestSubflowQc])

  return {
    running, log, run, preview, restoreLatest,
    runtimeNodes, runtimeEdges, runtimeLoopOwners, projectionRevision,
    setRuntimeProjectionNodes: setRuntimeNodes,
  }
}
