import { useEffect, useMemo, useState } from 'react'
import { api, type Capability } from '../../api'
import { Icon } from '../../components/Icon'
import { CapabilityDetail } from './CapabilityDetail'

type KindFilter = 'all' | 'tool' | 'flow'

/**
 * 能力目录（系统管理 → 能力）：工具与 tapflow 抹平成同一份清单。
 *
 * 这页不是给人另做的镜像——渲染的就是规划节点调 `capability.catalog` 拿到的那一份。
 * 所以这里读起来含糊的描述，模型选能力时一样含糊，页面把「没写描述」标出来就是为此。
 */
export function CapabilityCatalog() {
  const [all, setAll] = useState<Capability[]>([])
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<KindFilter>('all')
  const [picked, setPicked] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setBusy(true); setError('')
    try {
      const { capabilities } = await api.listCapabilities()
      setAll(capabilities)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
  useEffect(() => { void load() }, [])

  // 与后端 capabilities._matches 同样的判据（空格分隔取交集），免得页面筛出来的
  // 与模型筛出来的不是一回事
  const hits = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean)
    return all.filter(c => (kind === 'all' || c.kind === kind)
      && words.every(w => `${c.id} ${c.title} ${c.description}`.toLowerCase().includes(w)))
  }, [all, query, kind])

  const current = hits.find(c => c.id === picked) ?? hits[0]
  const counts = useMemo(() => ({
    tool: all.filter(c => c.kind === 'tool').length,
    flow: all.filter(c => c.kind === 'flow').length,
    thin: all.filter(c => !c.description.trim()).length,
  }), [all])

  return (
    <div className="cap-page">
      <div className="cap-toolbar">
        <div>
          <h2>能力目录</h2>
          <p>
            工具 {counts.tool} · 流程 {counts.flow}
            {counts.thin > 0 && <em>　{counts.thin} 条没写描述，规划节点选不准</em>}
          </p>
        </div>
        <div className="cap-filters">
          <input value={query} placeholder="按名称 / 描述搜（空格分隔取交集）"
            onChange={e => setQuery(e.target.value)} />
          {(['all', 'tool', 'flow'] as KindFilter[]).map(k => (
            <button key={k} className={'btn' + (kind === k ? ' primary' : '')}
              onClick={() => setKind(k)}>
              {k === 'all' ? '全部' : k === 'tool' ? '工具' : '流程'}
            </button>
          ))}
          <button className="btn" onClick={() => void load()} disabled={busy}>
            <Icon name="refresh" spin={busy} /> 刷新
          </button>
        </div>
      </div>
      {error && <div className="test-error">{error}</div>}
      <div className="cap-columns">
        <aside className="cap-list">
          <div className="cap-list-title">命中 <span>{hits.length}</span></div>
          {hits.map(c => (
            <button key={c.id}
              className={'cap-row' + (current?.id === c.id ? ' active' : '')}
              onClick={() => setPicked(c.id)}>
              <strong>{c.title}</strong>
              <code>{c.id}</code>
              <div className="cap-row-tags">
                <span className={`cap-kind ${c.kind}`}>{c.kind === 'flow' ? '流程' : '工具'}</span>
                {c.writes && <span className="cap-kind write">副作用</span>}
                {!c.description.trim() && <span className="cap-kind thin">缺描述</span>}
              </div>
            </button>
          ))}
          {!hits.length && !busy && <div className="empty">没有命中的能力</div>}
        </aside>
        <main className="cap-main">
          {current ? <CapabilityDetail cap={current} />
            : <div className="empty">选择一条能力查看合同</div>}
        </main>
      </div>
    </div>
  )
}
