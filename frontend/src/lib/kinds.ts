import type { Element } from '../api'
import type { IconName } from '../components/Icon'

/** 要素类型 → 图标 + 中文标签（知识库内置类型的前端展示映射；未知类型兜底 puzzle） */
export const KIND_META: Record<string, { icon: IconName; label: string }> = {
  character: { icon: 'user', label: '角色' },
  scene: { icon: 'scene', label: '场景' },
  plotline: { icon: 'web', label: '剧情线' },
  conflict: { icon: 'conflict', label: '冲突线' },
  foreshadow: { icon: 'hook', label: '伏笔' },
  setting: { icon: 'scroll', label: '设定' },
  faction: { icon: 'users', label: '组织势力' },
  item: { icon: 'wand', label: '关键道具' },
}

/** 纯文本标签（无图标），用于兜底缩略图文字等 */
export const KIND_LABEL: Record<string, string> =
  Object.fromEntries(Object.entries(KIND_META).map(([k, v]) => [k, v.label]))

/** 生成参考条目（多类）：character/scene/prop/storyboard=要素类（可删除=解除关联）；
 * keyframe=首帧图、lastframe=尾帧图、audio=声线参考（仅可启停，不可删除）。
 * hint=悬停补充说明（占位待生成/接缝帧来源等）。
 * audio 专用：audioUrl=试听小样（有=点击试听，无=未生成，点击按角色特征捏音色生成）；
 * elementId/voiceId=对应角色要素/已绑音色 id（生成时用）；busy=该音频卡正在生成中。 */
export interface EditRef {
  name: string; kind: string; url?: string; deletable?: boolean; hint?: string
  audioUrl?: string; elementId?: number; voiceId?: number; busy?: boolean
}

/** 参考类型 → 图标（无缩略图时的胶囊图标） */
export const REF_ICON: Record<string, IconName> = {
  character: 'user', scene: 'scene', scene_sheet: 'scene', prop: 'wand', storyboard: 'image',
  keyframe: 'palette', lastframe: 'palette', audio: 'speaker',
}

/** 有视觉形象、可出设定图的要素类型（兜底：老数据无 needs_image 字段时按类型判定） */
const IMAGE_KINDS = new Set(['character', 'scene', 'setting'])

/** 该要素是否需要设定图：优先用模型生成的 meta.needs_image，缺省按类型兜底 */
export function needsImage(el: Element): boolean {
  return el.meta.needs_image ?? IMAGE_KINDS.has(el.kind)
}

/** 把要素按 kind 分组：优先按项目已判定的要素类型顺序（config.element_kinds），
 * 未传则按 KIND_META 固定顺序，未知 kind 追加在末尾 */
export function groupByKind(elements: Element[], kindOrder?: string[]): [string, Element[]][] {
  const order = kindOrder?.length ? kindOrder : Object.keys(KIND_META)
  const groups = new Map<string, Element[]>()
  for (const el of elements) {
    if (!groups.has(el.kind)) groups.set(el.kind, [])
    groups.get(el.kind)!.push(el)
  }
  return [...groups.entries()].sort(([a], [b]) => {
    const ia = order.indexOf(a), ib = order.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
}
