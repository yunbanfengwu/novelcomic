import { useEffect, useState } from 'react'
import { api, type ToolSpec } from '../../api'
import { Icon } from '../../components/Icon'
import { ToolResultView } from './ToolResultView'
import { toolArgs, toolPreset } from '../../lib/toolArgs'

/** 单个工具的调用面板：按 params 渲染表单 → 调用 → 展示返回值。 */
export function ToolRunner({ tool, onRan }: { tool: ToolSpec; onRan: () => void }) {
  const [form, setForm] = useState<Record<string, string>>({})
  const [result, setResult] = useState<unknown>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setForm(toolPreset(tool))
    setResult(undefined)
    setError('')
  }, [tool])

  const run = async () => {
    setBusy(true); setError(''); setResult(undefined)
    try {
      const { result: out } = await api.invokeTool(tool.name, toolArgs(tool, form))
      setResult(out)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      onRan()
    }
  }

  const entries = Object.entries(tool.params)
  return (
    <div className="tool-runner">
      <div className="tool-head">
        <h3>{tool.title}<code>{tool.name}</code>
          {tool.writes && <span className="tool-badge write">写</span>}</h3>
        <p>{tool.description}</p>
      </div>
      <div className="tool-form">
        {entries.length === 0 && <div className="tool-empty">该工具没有入参</div>}
        {entries.map(([key, p]) => (
          <label key={key} className="tool-field">
            <span>{key}{p.required && <b>*</b>}<em>{p.desc}</em></span>
            {key === 'sql' || p.type === 'array' ? (
              <textarea className="tool-sql" rows={key === 'sql' ? 7 : 2} spellCheck={false}
                value={form[key] ?? ''} placeholder={p.type === 'array' ? '[]' : ''}
                onChange={e => setForm({ ...form, [key]: e.target.value })} />
            ) : (
              <input value={form[key] ?? ''} placeholder={p.type}
                onChange={e => setForm({ ...form, [key]: e.target.value })} />
            )}
          </label>
        ))}
        <div className="btns">
          <button className="btn primary" onClick={() => void run()} disabled={busy}>
            <Icon name={busy ? 'spinner' : 'play'} spin={busy} /> 运行
          </button>
        </div>
      </div>
      {error && <div className="test-error">{error}</div>}
      {result !== undefined && <ToolResultView value={result} />}
    </div>
  )
}
