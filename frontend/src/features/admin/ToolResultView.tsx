import type { ToolQueryResult } from '../../api'

/** 工具返回值展示：db.query 那种 {columns,rows} 走表格，其余工具原样展示 JSON。 */
function isQueryResult(v: unknown): v is ToolQueryResult {
  const o = v as ToolQueryResult
  return !!o && Array.isArray(o.columns) && Array.isArray(o.rows)
}

function cell(v: unknown) {
  if (v === null || v === undefined) return <span className="tool-null">NULL</span>
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

export function ToolResultView({ value }: { value: unknown }) {
  if (!isQueryResult(value)) {
    return <pre className="test-json">{JSON.stringify(value ?? {}, null, 2)}</pre>
  }
  return (
    <div className="tool-result">
      <div className="tool-result-meta">
        {value.row_count} 行{value.truncated && '（已截断，还有更多；加大 limit 或收紧条件）'}
      </div>
      {value.rows.length === 0 ? <div className="tool-empty">查询无结果</div> : (
        <div className="tool-table-wrap">
          <table className="tool-table">
            <thead>
              <tr>{value.columns.map(c => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {value.rows.map((row, i) => (
                <tr key={i}>
                  {value.columns.map(c => <td key={c} title={String(row[c] ?? '')}>{cell(row[c])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
