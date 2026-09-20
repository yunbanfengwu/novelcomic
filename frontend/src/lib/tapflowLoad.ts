// 按 slug 载入一条真实工作流并投影成画布数据——**唯一实现**。
// tapflow 列表页与业务页（如素材库的「生成场景设定图」）都走它，
// 免得两处各写一遍 getWorkflow + adaptWorkflow，投影参数慢慢长歪。
import { api, type WorkflowDetail, type WorkflowSubject, type WorkflowSummary } from '../api'
import { adaptWorkflow } from './tapflowGraphAdapter'
import type { TapFlowMeta } from './tapflowData'

/** 工作流详情 → 画布用的 TapFlowMeta（含保存所需的原图底稿）。 */
export async function loadTapflow(slug: string, version?: number,
                                  summary?: Partial<WorkflowSummary>): Promise<TapFlowMeta> {
  return toTapflow(await withSubflowContracts(await api.getWorkflow(slug, version)), summary)
}

/**
 * 业务入口的画布：**这个对象有自己的画布就打开它，没有才打开模板**。
 *
 * 实例是用户在生产态改过结构后 fork 出来的（见 useTapflowSave）。不先查这一下，
 * 用户上次拖的节点存了也白存——每次进来还是模板那四个节点。
 */
export async function loadSubjectTapflow(slug: string, subject: WorkflowSubject): Promise<TapFlowMeta> {
  const inst = await api.getWorkflowInstance(slug, subject).catch(() => null)
  // Production canvases must be scoped before their latest run outputs are restored.
  // Falling back to the template leaks another target's latest image into this canvas.
  if (!inst) return {
    ...toTapflow(await withSubflowContracts(await api.forkWorkflowInstance(slug, subject))),
    subject: { kind: subject.kind, id: subject.id, canvasRole: subject.canvasRole },
  }
  return { ...toTapflow(await withSubflowContracts(inst)),
    subject: { kind: subject.kind, id: subject.id, canvasRole: subject.canvasRole } }
}

/**
 * Older backend instances did not return `subflow_contracts`.  Keep the canvas
 * semantic instead of silently losing the multi-child marker: derive direct
 * child contracts from their persisted graphs.  New backends already provide
 * the contract, so this performs no extra request in the normal case.
 */
async function withSubflowContracts(detail: WorkflowDetail): Promise<WorkflowDetail> {
  if (detail.subflow_contracts && Object.keys(detail.subflow_contracts).length) return detail
  const refs = [...new Map((detail.graph.nodes ?? [])
    .filter(node => node.type === 'subflow' && node.config?.slug)
    .map(node => [String(node.config?.slug), node.config?.version as number | undefined]))]
  if (!refs.length) return detail
  const children = await Promise.all(refs.map(async ([slug, version]) => {
    const child = await api.getWorkflow(slug, version).catch(() => null)
    if (!child) return null
    const cardinality = outputCardinality(child.graph)
    return [slug, {
      version: child.version,
      output_cardinality: cardinality,
      is_multi_child: cardinality === 'many',
    }] as const
  }))
  const contracts = Object.fromEntries(children.filter((item): item is NonNullable<typeof item> => !!item))
  return { ...detail, subflow_contracts: contracts }
}

function outputCardinality(graph: WorkflowDetail['graph']): 'one' | 'many' {
  const nodes = new Map((graph.nodes ?? []).map(node => [node.id, node]))
  for (const end of [...nodes.values()].filter(node => node.type === 'end')) {
    const inbound = (graph.edges ?? []).filter(edge => edge.to === end.id).map(edge => edge.from)
    if (new Set(inbound).size > 1 || inbound.some(id => nodes.get(id)?.type === 'loop')) return 'many'
  }
  return 'one'
}

function toTapflow(d: WorkflowDetail, summary?: Partial<WorkflowSummary>): TapFlowMeta {
  const { show, feeds, placed, ...data } = adaptWorkflow(d)
  const updated = String(summary?.updated_at ?? d.updated_at ?? '')
  return {
    id: `wf-${d.slug}`,
    name: summary?.name ?? d.name,
    desc: summary?.description ?? d.description ?? '',
    updated: updated.slice(0, 16).replace('T', ' '),
    data, show, feeds, placed,
    slug: d.slug, version: d.version, status: d.status,
    smartCall: !!d.smart_call,
    originSlug: d.origin_slug ?? undefined,
    // 原图留着做保存时的合并底稿——投影层没覆盖的 config 字段靠它原样带回去
    raw: { graph: d.graph, input_schema: d.input_schema ?? {} },
  }
}

/** 带 canvas 标签且已发布的工作流，每个 slug 取最新版本（画布列表与业务入口同一口径）。 */
export function latestCanvasFlows(ws: WorkflowSummary[]): WorkflowSummary[] {
  const best = new Map<string, WorkflowSummary>()
  for (const w of ws) {
    if (!(w.tags ?? []).includes('canvas') || w.status !== 'published') continue
    const cur = best.get(w.slug)
    if (!cur || w.version > cur.version) best.set(w.slug, w)
  }
  return [...best.values()]
}
