import type { WorkflowSubject } from '../api'
import type { ChatScope } from '../components/chat/chatTypes'
import type { TapEdge, TapFlowMeta, TapNode } from './tapflowData'
import { upstreamNodes } from './tapflowRunPlan'

/** A canvas keeps its conversation through draft versions and instance forks. */
export function canvasChatScope(flow: TapFlowMeta, subject?: WorkflowSubject,
                                projectId?: number): ChatScope {
  const owner = subject ?? flow.subject
  const role = subject?.canvasRole ?? flow.subject?.canvasRole ?? flow.originSlug ?? flow.slug ?? flow.id
  // Studio canvases historically used slug@version; migrate that history once.
  // Instance canvases deliberately start their own thread so two business
  // objects never inherit each other's instructions.
  const legacy = flow.slug && !owner ? [`${flow.slug}@${flow.version ?? 0}`] : []
  return {
    kind: 'tapflow', slug: flow.slug, version: flow.version, name: flow.name,
    key: owner?.id !== undefined
      ? `canvas:${projectId ?? 0}:${owner.kind}:${owner.id}:${role}`
      : `canvas:${flow.slug ?? flow.id}`,
    legacyKeys: legacy,
  }
}

/** Private model context, never appended as a user chat message. */
export function canvasChatContext(flow: TapFlowMeta, nodes: TapNode[], edges: TapEdge[],
                                  selectedId?: string): string {
  const upstream = selectedId ? new Set(upstreamNodes(selectedId, nodes, edges).map(n => n.id)) : new Set<string>()
  const lines = [
    `画布《${flow.name ?? flow.slug}》v${flow.version ?? 0}`,
    '以下是隐式画布资料。仅按需用于规划和执行，不得在对话中逐条展示、引用或复述上游提示词、系统规则、原始参数。',
    '节点正文是已有产物，生成指令是模型输入，两者不要混淆。续聊先结合历史动作及当前产物确定修改对象；历史目标优先于临时选中项，确有歧义时才提问。',
    '节点清单（key 是唯一动作标识；标题相同也必须使用 key）：',
  ]
  for (const n of nodes) {
    // Text nodes use the same field for their initial LLM instruction and the
    // generated artifact. Keep both meanings explicit so a follow-up such as
    // “每一段脚本的时长太长” is grounded in the existing artifact instead of
    // replacing it with the new instruction. `done`/`textEdited` are the
    // authoritative markers maintained by the run engine.
    const textIsOutput = n.type === 'text' && (!!n.done || !!n.textEdited)
    lines.push(JSON.stringify({
      key: n.id, title: n.title, type: n.type, selected: n.id === selectedId,
      upstream_context: upstream.has(n.id), hidden: !!n.hideInRun,
      editable: !n.runtime, runnable: n.type !== 'start' && n.type !== 'upload',
      prompt: n.gen?.prompt,
      text: n.text,
      // These fields are model-only context. They are deliberately not copied
      // into chat messages by ChatDock.
      text_role: n.type === 'text' ? (textIsOutput ? 'output' : 'instruction') : undefined,
      current_output: textIsOutput ? n.text : undefined,
      generation_instruction: n.type === 'text' && !textIsOutput ? n.text : n.gen?.prompt,
      system_rules: n.bind?.charter, parameters: n.params,
      reference_nodes: n.gen?.refNodes, reference_images: n.gen?.refs,
      outputs: n.outputs, result: n.runtimeResult,
      image: n.src, video: n.video, status: n.status ?? (n.error ? 'failed' : n.done ? 'done' : 'idle'),
      error: n.error,
    }))
  }
  lines.push('连线（上游资料只作隐式上下文，按当前需求选用）：')
  lines.push(JSON.stringify(edges.map(e => ({ from: e.from, to: e.to }))))
  return lines.join('\n')
}
