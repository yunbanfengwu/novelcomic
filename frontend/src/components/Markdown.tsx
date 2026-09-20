import { Fragment, type ReactNode } from 'react'
import './Markdown.css'

/**
 * 轻量 Markdown 渲染（零依赖）：块级解析 # 标题 / --- 分隔线 / | | 表格 /
 * - 有序·无序列表（支持缩进嵌套）/ > 引用 / 段落；行内解析 **加粗** 与 `代码`。
 * 面向本项目的架构大纲文本，非通用 CommonMark 实现（不做嵌套强调、图片、链接）。
 */
export function Markdown({ text }: { text: string }) {
  return <div className="md">{renderBlocks(text.replace(/\r\n/g, '\n').split('\n'))}</div>
}

// 行内：**加粗** 与 `代码`，其余原样
function inline(s: string): ReactNode {
  const nodes: ReactNode[] = []
  const re = /(\*\*(.+?)\*\*|`(.+?)`)/g
  let last = 0, m: RegExpExecArray | null, k = 0
  while ((m = re.exec(s))) {
    if (m.index > last) nodes.push(s.slice(last, m.index))
    if (m[2] !== undefined) nodes.push(<b key={k++}>{m[2]}</b>)
    else nodes.push(<code key={k++}>{m[3]}</code>)
    last = m.index + m[0].length
  }
  if (last < s.length) nodes.push(s.slice(last))
  return nodes.length ? <>{nodes.map((n, i) => <Fragment key={i}>{n}</Fragment>)}</> : s
}

const indentOf = (l: string) => (l.match(/^\s*/)?.[0].length ?? 0)
const isBullet = (l: string) => /^\s*([-*]|\d+\.)\s+/.test(l)
const bulletText = (l: string) => l.replace(/^\s*([-*]|\d+\.)\s+/, '')

function renderBlocks(lines: string[]): ReactNode[] {
  const out: ReactNode[] = []
  let i = 0, key = 0
  while (i < lines.length) {
    const line = lines[i]
    const t = line.trim()
    if (!t) { i++; continue }

    // 分隔线
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) { out.push(<hr key={key++} />); i++; continue }

    // 标题
    const h = t.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      const L = h[1].length
      const Tag = `h${Math.min(L + 1, 6)}` as 'h2'
      out.push(<Tag key={key++} className={`md-h${L}`}>{inline(h[2])}</Tag>)
      i++; continue
    }

    // 表格：当前行含 | 且下一行是分隔行 |---|---|
    if (t.includes('|') && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      const rows: string[] = []
      while (i < lines.length && lines[i].includes('|')) { rows.push(lines[i]); i++ }
      out.push(renderTable(rows, key++))
      continue
    }

    // 引用
    if (/^>\s?/.test(t)) {
      const buf: string[] = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^\s*>\s?/, '')); i++ }
      out.push(<blockquote key={key++}>{buf.map((b, j) => <p key={j}>{inline(b)}</p>)}</blockquote>)
      continue
    }

    // 列表（含缩进嵌套）
    if (isBullet(line)) {
      const buf: string[] = []
      while (i < lines.length && (isBullet(lines[i]) || (lines[i].trim() && indentOf(lines[i]) > 0 && buf.length))) {
        buf.push(lines[i]); i++
      }
      out.push(renderList(buf, key++))
      continue
    }

    // 段落（连续非空、非块起始行）
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() &&
      !/^(#{1,6})\s/.test(lines[i].trim()) && !isBullet(lines[i]) &&
      !/^>\s?/.test(lines[i].trim()) && !/^(-{3,}|\*{3,})$/.test(lines[i].trim())) {
      buf.push(lines[i].trim()); i++
    }
    if (buf.length) out.push(<p key={key++}>{inline(buf.join(' '))}</p>)
  }
  return out
}

function renderTable(rows: string[], key: number): ReactNode {
  const cells = (r: string) => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())
  const head = cells(rows[0])
  const body = rows.slice(2).map(cells)
  return (
    <div className="md-table-wrap" key={key}>
      <table>
        <thead><tr>{head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
        <tbody>{body.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

// 缩进嵌套列表：按最小缩进分组，子行递归
function renderList(lines: string[], key: number): ReactNode {
  const base = Math.min(...lines.filter(isBullet).map(indentOf))
  const ordered = /^\s*\d+\.\s/.test(lines[0])
  const items: { text: string; children: string[] }[] = []
  for (const l of lines) {
    if (isBullet(l) && indentOf(l) <= base) items.push({ text: bulletText(l), children: [] })
    else if (items.length) items[items.length - 1].children.push(l)
  }
  const Tag = ordered ? 'ol' : 'ul'
  return (
    <Tag key={key}>
      {items.map((it, j) => (
        <li key={j}>
          {inline(it.text)}
          {it.children.some(c => c.trim()) && renderBlocks(it.children)}
        </li>
      ))}
    </Tag>
  )
}
