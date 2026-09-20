import { useEffect, useMemo, useState } from 'react'
import { api, getCurrentUserId, setCurrentUserId, type SysUser, type ToolCall, type ToolSpec } from '../../api'
import { Icon } from '../../components/Icon'
import { ToolRunner } from './ToolRunner'
import { ToolCallLog } from './ToolCallLog'

/**
 * 工具菜单：系统能力的统一清单，技能/工作流将来按名字调用同一批工具。
 * 查询不逐个封装端点镜像——给一把只读 SQL（db.query）+ 一份自解释的库结构（db.schema）；
 * 增删改一律走命名动作，不开放裸 SQL 写（理由见 backend/app/services/tools.py 模块头）。
 */
export function ToolsAdmin() {
  const [tools, setTools] = useState<ToolSpec[]>([])
  const [me, setMe] = useState<SysUser>()
  const [users, setUsers] = useState<SysUser[]>([])
  const [pick, setPick] = useState('db.query')
  const [tab, setTab] = useState<'run' | 'calls'>('run')
  const [calls, setCalls] = useState<ToolCall[]>([])

  const load = async () => {
    const [{ me: who, tools: list }, all] = await Promise.all([api.listTools(), api.listUsers()])
    setMe(who); setTools(list); setUsers(all)
  }
  useEffect(() => { void load() }, [])
  useEffect(() => { if (tab === 'calls') void api.listToolCalls().then(setCalls) }, [tab])

  const groups = useMemo(() => {
    const m = new Map<string, ToolSpec[]>()
    for (const t of tools) m.set(t.group, [...(m.get(t.group) ?? []), t])
    return [...m.entries()]
  }, [tools])
  const current = tools.find(t => t.name === pick)

  const switchUser = (id: string) => { setCurrentUserId(id); void load() }

  return (
    <div className="tools-admin">
      <div className="test-toolbar">
        <div>
          <h2>工具</h2>
          <p>可被技能与工作流调用的系统能力。查询走只读 SQL，增删改走命名动作。</p>
        </div>
        <div className="btns">
          <select value={getCurrentUserId()} onChange={e => switchUser(e.target.value)}
            title="当前用户">
            {users.map(u => <option key={u.id} value={u.id}>{u.name}（{u.id}）</option>)}
          </select>
          <button className={`btn${tab === 'run' ? ' primary' : ''}`} onClick={() => setTab('run')}>
            <Icon name="console" /> 调用</button>
          <button className={`btn${tab === 'calls' ? ' primary' : ''}`} onClick={() => setTab('calls')}>
            <Icon name="clipboard" /> 调用记录</button>
        </div>
      </div>
      <div className="tools-columns">
        <aside className="test-pane">
          <div className="test-pane-title">工具 <span>{tools.length}</span></div>
          {groups.map(([g, items]) => (
            <div key={g} className="tool-group">
              <div className="tool-group-title">{g}</div>
              {items.map(t => (
                <button key={t.name} className={`tool-item${t.name === pick ? ' on' : ''}`}
                  onClick={() => { setPick(t.name); setTab('run') }}>
                  <b>{t.title}</b>
                  <code>{t.name}</code>
                  {t.writes && <span className="tool-badge write">写</span>}
                </button>
              ))}
            </div>
          ))}
        </aside>
        <section className="tool-pane-main">
          {tab === 'calls'
            ? <ToolCallLog calls={calls} />
            : current
              ? <ToolRunner tool={current} onRan={() => setCalls([])} />
              : <div className="tool-empty">左侧选一个工具</div>}
        </section>
      </div>
      {me && <div className="tools-foot">当前身份 {me.name}（{me.role}）——系统尚未接入登录，
        身份来自请求头 X-User-Id，所有新数据默认归属 sys_dev。</div>}
    </div>
  )
}
