// ═══════════ 提示词双字段（2026-07-17）：用户提示词(user) × 系统锚定提示词(anchor) ═══════════
// user 段=叙事内容（系统预填、用户可改不被覆盖）；anchor 段=结构句（画风锚词/一致性/质量词，
// 随装配自动刷新，改过则冻结）。编辑框两段用分隔线合并展示，保存由后端按线拆回、提交剥线。

/** 编辑框两段之间的分隔线（独占一行；与后端 prompt_fields.DIVIDER 一致） */
export const PROMPT_DIVIDER = '——————'

/** 与后端 compose 同构：full = user ⊕ anchor（用于校验分段与库中全文是否一致） */
const compose = (user: string, anchor: string): string => {
  const u = (user ?? '').trim(), a = (anchor ?? '').trim()
  if (!u) return a
  if (!a) return u
  return `${u.replace(/[。, ]+$/, '')}。${a}`
}

/** 两段 → 编辑框文本（user 在上、anchor 在下、分隔线居中）。
 * full 传入时做一致性校验：分段拼不回全文（如质检重构过、旧数据）→ 直接展示全文
 * （整段编辑模式，保存走旧整段语义），避免把重构内容"藏"起来。 */
export function joinPromptSegments(user?: string, anchor?: string, full?: string): string {
  const u = (user ?? '').trim(), a = (anchor ?? '').trim()
  if (!u && !a) return full ?? ''
  if (full && compose(u, a) !== full.trim()) return full
  if (!a) return u
  return `${u}\n${PROMPT_DIVIDER}\n${a}`
}

/** 编辑框文本 → [user, anchor]；无分隔线返回 null（整段语义）。与后端 split_edit_text 同构。 */
export function splitPromptSegments(text: string): [string, string] | null {
  const m = /^\s*(?:[—\-_=]{4,}|锚定提示词[:：]?)\s*$/m.exec(text ?? '')
  if (!m) return null
  return [text.slice(0, m.index).trim(), text.slice(m.index + m[0].length).trim()]
}

/** 与后端一致的全文拼接（前端需要自己落 config 的场合用，如封面）。 */
export const composePrompt = compose
