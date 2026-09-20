import type { ToolCall } from '../../api'

const stamp = (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false })

/** 工具调用审计：谁、从哪、用什么参数调了哪个工具、成没成、多久。 */
export function ToolCallLog({ calls }: { calls: ToolCall[] }) {
  if (calls.length === 0) return <div className="tool-empty">还没有调用记录</div>
  return (
    <div className="tool-calls">
      {calls.map(c => (
        <div key={c.id} className={`tool-call${c.ok ? '' : ' failed'}`}>
          <div className="tool-call-head">
            <code>{c.tool}</code>
            <span className="tool-call-who">{c.caller} · {c.source}</span>
            <span className="tool-call-time">{stamp(c.created_at)}</span>
            <span className="tool-call-cost">
              {c.row_count != null && `${c.row_count} 行 · `}{c.duration_ms ?? '—'}ms
            </span>
          </div>
          <pre>{typeof c.args === 'string' ? c.args : JSON.stringify(c.args)}</pre>
          {c.error && <div className="tool-call-err">{c.error}</div>}
        </div>
      ))}
    </div>
  )
}
