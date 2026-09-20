import type { ToolSpec } from '../api'

/** 工具入参的表单值 ↔ 实参转换（纯逻辑，不进组件）。 */

/** 表单预填：db.query 给一条能直接跑通的示例，省得每次从空白开始想表名。 */
export function toolPreset(tool: ToolSpec): Record<string, string> {
  if (tool.name === 'db.query') {
    return {
      sql: 'SELECT id, title, status, owner_id, updated_at\n'
        + 'FROM content_projects\nWHERE deleted_at IS NULL\nORDER BY id DESC',
      limit: '50',
    }
  }
  return {}
}

/** 表单字符串按 params 声明的类型转成实参；空的非必填项直接不传，交给后端默认值。 */
export function toolArgs(tool: ToolSpec, form: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, p] of Object.entries(tool.params)) {
    const raw = (form[key] ?? '').trim()
    if (!raw) continue
    if (p.type === 'int') {
      const n = Number(raw)
      if (Number.isNaN(n)) throw new Error(`${key} 需要是数字`)
      out[key] = n
    } else if (p.type === 'array') {
      try {
        out[key] = JSON.parse(raw)
      } catch {
        throw new Error(`${key} 需要是 JSON 数组，例如 [1, "abc"]`)
      }
    } else {
      out[key] = raw
    }
  }
  return out
}
