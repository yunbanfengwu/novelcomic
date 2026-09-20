import type { SceneGroup, SceneImageRef, Shot } from '../api'

/** 出图阶段：产物只有一张场景空间站位图（sheet），empty 是它的中间锚（无人基准图）。 */
export type SceneStage = 'empty' | 'sheet'
export const STAGE_CN: Record<SceneStage, { title: string }> = {
  empty: { title: '空场景基准图' },
  sheet: { title: '场景空间站位图' },
}

/** 某一阶段的参考池现状：实际会传给模型的图 + 有站位却没有设定图的角色。
 * 「不知道是否参考了角色和原始场景」的答案就是这两个数组——缺谁直接点名。
 * 站位图的首位参考（空场景基准图）在后端 before 里动态插入，此处按 empty_url 补上。 */
export function sheetRefStatus(g: SceneGroup, stage: SceneStage): {
  refs: SceneImageRef[]; missing: string[]
} {
  if (stage === 'empty') {
    return { refs: (g.empty_refs ?? []).filter(r => r.url).slice(0, 4), missing: [] }
  }
  const base: SceneImageRef[] = g.empty_url
    ? [{ name: '空场景基准图', kind: 'scene_empty', url: g.empty_url }] : []
  const refs = [...base, ...(g.sheet_refs ?? []).filter(r => r.url)].slice(0, 4)
  const named = new Set(refs.map(r => r.name))
  return { refs, missing: Object.keys(g.anchors ?? {}).filter(n => !named.has(n)) }
}

/** 总览图块的一行进度说明。基准图是中间锚，只在站位图还没出时才值得提。 */
export function stageBrief(g: SceneGroup): string {
  if (g.sheet_url) return ''
  return g.empty_url ? '基准图已出 · 站位图待生成' : '站位图待生成'
}

// ═══ 场景空间站位图的说明文字（前置条件·场景块右侧）═══
// 数据全部来自章级空间规划产物（scene_blocking）：space=机位无关的空间布局、
// anchors=组开场各角色站位、sheet_desc=组图叙事段（光线/天气写在其中）。

/** 含光线/天气/时间线索的句子（sheet_desc 里光影句一般在后半段） */
const LIGHT_HINT = /光|天气|时间|黄昏|清晨|正午|夜|阴|雨|雪|雾|霞|逆光|顶光|侧光/

/** 从组图叙事段里挑出光影句（最多两句）；挑不到返回空串。
 * 句首的视角标签（"全景："/"局部："/"视角A："…）在此剥掉——那是构图分区，不是光影信息。 */
export function lightLine(sheetDesc: string): string {
  const hits = (sheetDesc || '').split(/[。；;]/)
    .map(s => s.trim().replace(/^[^：:]{1,6}[：:]\s*/, ''))
    .filter(s => s && LIGHT_HINT.test(s))
  return hits.slice(-2).join('；')
}

/** 场景块右侧文字：空间布局 → 角色站位 → 镜内移动 → 光影；缺图时末尾补一行去处。
 * 站位优先用本镜站位（shot.meta.blocking.chars，逐镜站位链产物；原挂在分镜脚本末尾），
 * 本镜没有才回落组开场占位（group.anchors）。 */
export function sceneNoteLines(
  g: SceneGroup | undefined, hasSheet: boolean, blocking?: Shot['meta']['blocking'],
): string[] {
  const chars = Object.entries(blocking?.chars ?? {})
  const anchors = chars.length ? chars : Object.entries(g?.anchors ?? {})
  const light = lightLine(g?.sheet_desc || '')
  return [
    g?.space ? `空间：${g.space}` : '',
    anchors.length ? `站位：${anchors.map(([n, p]) => `${n}：${p}`).join('；')}` : '',
    blocking?.moves ? `移动：${blocking.moves}` : '',
    light ? `光影：${light}` : '',
    hasSheet ? '' : g ? '设定图待生成——点图块进场景设定' : '本镜未做场景空间规划——点图块进场景设定',
  ].filter(Boolean)
}
