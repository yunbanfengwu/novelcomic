// 按句末标点（中英文句号/分号）切分文本为行，标点保留在行尾
const SENTENCE_END = /([。；.;])/

export function splitSentences(text: string): string[] {
  const parts = text.split(SENTENCE_END)
  const lines: string[] = []
  let cur = ''
  for (const part of parts) {
    cur += part
    if (SENTENCE_END.test(part)) {
      lines.push(cur.trim())
      cur = ''
    }
  }
  if (cur.trim()) lines.push(cur.trim())
  return lines.filter(Boolean)
}
