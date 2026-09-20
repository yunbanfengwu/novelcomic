/** 角色库分类（两类）：系统生成 / 作品产出 */
export const CHAR_CATEGORIES = [
  { key: 'system', label: '系统生成' },
  { key: 'work', label: '作品产出' },
] as const

export type CharCategory = typeof CHAR_CATEGORIES[number]['key']

export const CHAR_CATEGORY_LABEL: Record<string, string> =
  Object.fromEntries(CHAR_CATEGORIES.map(c => [c.key, c.label]))
