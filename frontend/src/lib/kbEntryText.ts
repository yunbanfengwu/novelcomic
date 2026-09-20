import type { KbEntry } from '../api'

/** 知识库条目 ⇄ 纯文本互转（智能解析 tab 用）。
 * 文本形态：每行「标签：值」；内容等多行字段的后续无标签行自动归入上一字段；
 * 通篇无标签时按「首行=名称，其余=内容」兜底；空字段直接省略行。 */

type Attachment = { title?: string; url: string }

// 标签别名（统一小写查表）→ 内部字段名；正则按长度降序拼，避免长标签被短前缀截胡
const LABELS: Record<string, string> = {
  '名称': 'name', 'name': 'name',
  '标题': 'title', '展示标题': 'title', 'title': 'title',
  '分类': 'category', 'category': 'category',
  '权重': 'weight', 'weight': 'weight',
  '触发': 'description', '触发描述': 'description', '描述': 'description', 'description': 'description',
  '内容': 'content', '正文': 'content', 'content': 'content',
  '正向': 'positive', '正向提示词': 'positive', 'positive': 'positive',
  '负面': 'negative', '负向': 'negative', '负面提示词': 'negative', 'negative': 'negative',
  '缩略图': 'thumbnail', '封面': 'thumbnail', 'thumbnail': 'thumbnail',
  '附件': 'attachment', 'attachment': 'attachment',
}
const LABEL_RE = new RegExp(
  `^(${Object.keys(LABELS).sort((a, b) => b.length - a.length).join('|')})\\s*[:：]\\s*(.*)$`, 'i')

/** 条目 → 文本：非空字段各占一行（内容可多行），编辑时作为智能 tab 的初始值 */
export function entryToText(e: Partial<KbEntry>): string {
  const lines: string[] = []
  const add = (label: string, v?: string | number | null) => {
    const s = v == null ? '' : String(v).trim()
    if (s) lines.push(`${label}：${s}`)
  }
  add('名称', e.name)
  add('标题', e.title)
  add('分类', e.category)
  if (e.weight) add('权重', e.weight)
  add('触发', e.description)
  add('内容', e.content)
  add('正向', e.meta?.positive)
  add('负面', e.meta?.negative)
  add('缩略图', e.thumbnail_url)
  for (const a of (e.meta?.attachments as Attachment[]) || []) {
    lines.push(`附件：${a.title ? `${a.title} | ` : ''}${a.url}`)
  }
  return lines.join('\n')
}

/** 解析文本并合并回条目：文本是字段的完整表达——文本里没写的字段视为清空；
 * meta 中的非表单字段（samples 等）原样保留。 */
export function applyEntryText(base: Partial<KbEntry>, text: string): Partial<KbEntry> {
  const fields: Record<string, string[]> = {}
  const attachments: Attachment[] = []
  const loose: string[] = []   // 无标签且无归属的行
  let cur: string | null = null
  for (const raw of text.split('\n')) {
    const m = raw.match(LABEL_RE)
    if (m) {
      const key = LABELS[m[1].toLowerCase()]
      if (key === 'attachment') {
        const [a, b] = m[2].split('|').map(s => s.trim())
        if (b || a) attachments.push(b ? { title: a, url: b } : { url: a })
        cur = null
      } else {
        ;(fields[key] ??= []).push(m[2])
        cur = key
      }
    } else if (cur) fields[cur].push(raw)
    else if (raw.trim()) loose.push(raw)
  }
  // 通篇没写标签的纯文本：首行当名称，其余当内容
  if (!fields.name?.length && loose.length) {
    fields.name = [loose.shift()!]
    if (loose.length && !fields.content?.length) fields.content = loose
  }
  const val = (k: string) => (fields[k]?.join('\n') ?? '').trim()
  // 分类/权重是上下文预设（新增时由所在文件夹带入）：文本里没写该行 → 保留原值，写了才覆盖
  return {
    ...base,
    name: val('name'),
    title: val('title'),
    category: 'category' in fields ? (val('category') || null) : (base.category ?? null),
    weight: 'weight' in fields ? (Number(val('weight')) || 0) : (base.weight ?? 0),
    description: val('description'),
    content: val('content'),
    thumbnail_url: val('thumbnail') || null,
    meta: {
      ...base.meta,
      positive: val('positive') || undefined,
      negative: val('negative') || undefined,
      attachments: attachments.length ? attachments : undefined,
    },
  }
}

/** 智能 tab 空白时的占位模板 */
export const SMART_PLACEHOLDER = [
  '每行「字段：值」，字段可省略。例如：',
  '名称：都市爽文风',
  '触发：写都市题材正文时召回',
  '内容：短句为主，强钩子开头，每段末留悬念…',
  '（可多行，直接换行续写）',
  '缩略图：https://…',
  '附件：参考文档 | https://…',
  '',
  '也可直接粘贴一段纯文本：首行作名称，其余作内容。',
].join('\n')
