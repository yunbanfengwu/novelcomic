// tapflow 画布保存：画布状态 → graph → POST /api/workflows。**唯一保存入口**
// （编排台的手动保存与生产态的自动保存共用它，免得两条路各写一套合并规则）。
//
// 版本策略（2026-08-01 定稿）：**published 的图保存成新草稿版本，草稿原地覆盖**。
// 理由是 element-sheet / scene-brief 这类原子工作流被 canvas 按 slug+version 引用，
// 原地改会立刻影响正在跑的流程；改完要生效得显式「发布」。
//
// 画布实例（subject）例外：那是「某个对象的专属画布」，没有别的流程引用它 →
// 原地存、存即生效，不走草稿/发布两态（生产态用户改一次还要点发布才跑得到新图，
// 那是编排台的规矩，不该摊到业务用户头上）。
import { useCallback, useRef, useState } from 'react'
import { api, type WorkflowSubject } from '../api'
import type { TapEdge, TapFlowMeta, TapNode } from './tapflowData'
import { toGraph, type TapGraphIn } from './tapflowGraphWrite'

export interface TapSaveState {
  /** 演示流程没有 slug，存不了——按钮整个不出现 */
  savable: boolean
  saving: boolean
  /** 保存/发布的结果提示（成功或失败都走它，一处显示） */
  msg: string | null
  /** 存下了但跑不起来的问题（如未选执行体），保存后回填 */
  warnings: string[]
  save: (nodes: TapNode[], edges: TapEdge[]) => Promise<void>
  publish: () => Promise<void>
  /** 当前落在哪个版本上（保存后可能变成新草稿版本） */
  version?: number
  status?: string
  /** 支持智能调用（被别的画布当节点引用时能否炸开生成条）。按 slug 全版本生效，
   * 与图内容无关，所以不进 save()，点一下即时生效。 */
  smartCall: boolean
  setSmartCall: (on: boolean) => Promise<void>
}

/**
 * @param flow  当前画布的元信息（含合并底稿 raw）
 * @param subject 画布实例的归属对象。给了它 = 生产态的「专属画布」语义：
 *              保存前若还落在模板上，先 fork 出这个对象的副本再存进副本。
 * @param onFlow 保存后回传新的 flow 元信息——fork 时运行要跟着换 slug；
 *              编排台另存草稿时也要跟着换 version，否则刷新/运行仍落在已发布旧版。
 */
export function useTapflowSave(flow: TapFlowMeta, subject?: WorkflowSubject,
                               onFlow?: (f: TapFlowMeta) => void): TapSaveState {
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [version, setVersion] = useState(flow.version)
  const [status, setStatus] = useState(flow.status)
  const [smartCall, setSmartCall] = useState(!!flow.smartCall)
  // 合并底稿与目标 slug 随保存滚动更新：
  // 底稿必须是**上一次存进去的那份**，否则新加节点的 payload/skip_if（画布模型不带的键）
  // 每存一次就被按空对象重建一次，用户在属性面板改过的执行体配置会被打回默认值。
  const target = useRef<{ slug?: string; base: TapGraphIn; schema: Record<string, unknown> }>({
    slug: flow.slug,
    base: flow.raw?.graph ?? { nodes: [], edges: [] },
    schema: flow.raw?.input_schema ?? {},
  })

  const save = useCallback(async (nodes: TapNode[], edges: TapEdge[]) => {
    const from = target.current.slug ?? flow.slug
    if (!from) return
    setSaving(true); setMsg(null)
    try {
      let slug = from
      let forked: TapFlowMeta | null = null
      // 还在模板上而这次是「某个对象的画布」→ 先 fork。幂等：后端 find-or-create
      if (subject && !flow.subject) {
        const d = await api.forkWorkflowInstance(from, subject)
        slug = d.slug
        forked = {
          ...flow, name: d.name, slug: d.slug, version: d.version, status: d.status,
          subject: { kind: subject.kind, id: subject.id, canvasRole: subject.canvasRole },
          raw: { graph: d.graph, input_schema: d.input_schema ?? {} },
        }
        target.current = {
          slug: d.slug, base: d.graph, schema: d.input_schema ?? {},
        }
      }
      const out = toGraph(target.current.base, target.current.schema, nodes, edges)
      setWarnings(out.warnings)
      const r = await api.saveWorkflow({
        slug, name: forked?.name ?? flow.name, description: flow.desc,
        input_schema: out.input_schema, graph: out.graph,
        // 实例是一个人的画布，原地存即生效；模板/编排台的图不原地改，另存草稿版本
        draft_from_published: !subject,
      })
      // 存进去的这份就是下一次的底稿
      target.current = { slug, base: out.graph, schema: out.input_schema }
      setVersion(r.version); setStatus(r.status)
      onFlow?.({
        ...(forked ?? flow), slug, version: r.version, status: r.status,
        raw: { graph: out.graph, input_schema: out.input_schema },
      })
      setMsg(subject
        ? '已保存到本对象的专属画布'
        : r.status === 'draft' && r.version !== flow.version
          ? `已存为草稿 v${r.version}——发布后才对运行生效`
          : `已保存 v${r.version}`)
    } catch (e) {
      setMsg(`保存失败：${String(e)}`)
    }
    setSaving(false)
  }, [flow, subject, onFlow])

  const publish = useCallback(async () => {
    const slug = target.current.slug ?? flow.slug
    if (!slug || version === undefined) return
    setSaving(true); setMsg(null)
    try {
      await api.publishWorkflow(slug, version)
      setStatus('published')
      setMsg(`v${version} 已发布`)
    } catch (e) {
      setMsg(`发布失败：${String(e)}`)
    }
    setSaving(false)
  }, [flow.slug, version])

  const setSmart = useCallback(async (on: boolean) => {
    const slug = target.current.slug ?? flow.slug
    if (!slug) return
    // 先落库再改本地态：失败时开关不该停在一个后端并不认可的位置上
    try {
      await api.setWorkflowSmartCall(slug, on)
      setSmartCall(on)
      setMsg(on ? '已标记为智能节点——被引用时可炸开输入提示词' : '已取消智能节点标记')
    } catch (e) {
      setMsg(`智能调用开关保存失败：${String(e)}`)
    }
  }, [flow.slug])

  return { savable: !!flow.slug && !!flow.raw, saving, msg, warnings, save, publish,
           version, status, smartCall, setSmartCall: setSmart }
}
