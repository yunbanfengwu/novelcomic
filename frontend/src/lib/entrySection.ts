import type { Chapter, Element, Project } from '../api'

/** 基本信息是否齐备：书名/梗概/文风/画风均有值（主线为可选项，不计入） */
export function infoComplete(p: Project): boolean {
  return [p.title, p.synopsis, p.writing_style, p.art_style].every(v => !!(v && v.trim()))
}

/** 章节是否已有正文：status 生命周期 planned→drafted→storyboarded→rendered，drafted 起即有正文 */
const hasBody = (c: Chapter) => ['drafted', 'storyboarded', 'rendered'].includes(c.status)

/**
 * 详情页落点（相对 /project/:id 的子路径）——渐进式引导：
 * 无大纲→总览（进入后自动补拟基本信息+大纲）；有大纲无要素→核心要素（自动判定要素类型）；
 * 尚无任何正文→正文；已有正文→视频。
 * 落集：默认第一集；若本会话内在本项目停留过某集（lastSeq，且该集仍存在）则回到那一集。
 */
export function resolveEntrySection(p: Project, chapters: Chapter[], elements: Element[], lastSeq?: number): string {
  if (!p.outline_md || !infoComplete(p)) return 'overview'
  if (!elements.length) return 'elements'
  const seq = (lastSeq != null && chapters.some(c => c.seq === lastSeq)) ? lastSeq : (chapters[0]?.seq ?? 1)
  return chapters.some(hasBody) ? `video/${seq}` : `body/${seq}`
}
