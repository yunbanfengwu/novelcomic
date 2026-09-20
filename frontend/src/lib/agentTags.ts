/** 智能体标签词表与展示顺序：阶段 → 类别 → 产物模态。
 * 标签本身是自由文本（后端 TEXT[]），这里只管排序——词表外的自定义标签排在已知标签之后。
 * 「向量」目前没有编排产出，先占位；一旦有编排打上它，标签栏自动出现。 */
export const TAG_ORDER = [
  // 阶段（第一个标签兼当列表页分组名）
  '项目', '要素', '章节', '镜头', '音色', '工作流',
  // 类别
  '生成', '查询', '组合',
  // 产物模态
  '文本', '图片', '视频', '音频', '向量',
]

export const tagRank = (t: string) => {
  const i = TAG_ORDER.indexOf(t)
  return i < 0 ? TAG_ORDER.length : i
}

/** 顶部标签栏的标签集合及图标（键序即栏内顺序）：产物类型 + 组合。
 * 阶段/类别等其余标签只在卡片上展示，不进标签栏。 */
export const TAG_ICONS: Record<string, string> = {
  文本: 'text', 图片: 'image', 视频: 'video', 音频: 'speaker', 向量: 'blocks',
  组合: 'puzzle',
}

/** 自由文本 → 标签数组：中英文逗号/空白都当分隔符 */
export const parseTags = (raw: string) => raw.split(/[,，\s]+/).filter(Boolean)

/** 颜色标签（人工分色，与上面的语义词表无关）：同样存在 tags 里，但**不当文字 chip 显示**，
 * 卡片上渲染成右上角色点。一张编排最多一个颜色，没标色的在标签栏归「灰」。 */
export const COLOR_HEX: Record<string, string> = {
  红: '#e5484d', 黄: '#f5c451', 绿: '#4cc38a',
}
export const COLOR_TAGS = Object.keys(COLOR_HEX)

export const isColorTag = (t: string) => t in COLOR_HEX

/** 取这张编排的颜色；未标色返回 ''（= 标签栏的「灰」） */
export const colorOf = (tags: string[]) => tags.find(isColorTag) ?? ''

/** 换色：先摘掉旧颜色再追加，保证同时只有一个；color='' 即清除 */
export const withColorTag = (tags: string[], color: string) =>
  [...tags.filter(t => !isColorTag(t)), ...(color ? [color] : [])]
