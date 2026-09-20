// 工作流的**呈现类型**：这张流程产出什么，被引用时该投影成哪种节点。
//
// 存在 workflows.tags 里（text / image / video / audio 之一），不另开列——
// tags 本来就是"这张图是什么"的多值描述，类型只是其中一维；另加一列会让
// 「一张流程是什么」分裂成两处，列表筛选也得各写各的。
//
// 没标类型的按 image 兜底（历史流程都是出图的），不至于因为漏标就画不出节点。

export type TapFlowKind = 'text' | 'image' | 'video' | 'audio'

const KINDS: TapFlowKind[] = ['text', 'image', 'video', 'audio']

export const TAP_FLOW_KIND_LABEL: Record<TapFlowKind, string> = {
  text: '文本', image: '图片', video: '视频', audio: '音频',
}

/** tags → 呈现类型。多标了取第一个命中的，漏标按图片兜底。 */
export function flowKind(tags?: string[]): TapFlowKind {
  return KINDS.find(k => (tags ?? []).includes(k)) ?? 'image'
}

/** 呈现类型 → 画布节点类型（被引用时投影成什么卡）。 */
export function kindToNodeType(kind: TapFlowKind): 'text' | 'image' | 'video' | 'audio' {
  return kind
}
