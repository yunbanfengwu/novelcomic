import { useEffect, useMemo, useState } from 'react'
import { api, type AgentTemplate, type ExpertTeam, type SkillPackage } from '../../api'
import { Icon } from '../../components/Icon'
import { Modal } from '../../components/Modal'

type Draft = Omit<AgentTemplate, 'id' | 'skills'> & { id?: number; skill_ids: number[] }
const empty: Draft = {
  code: '', name: '', role: '', description: '', charter: '', model: null,
  config: {}, enabled: true, skill_ids: [],
}

export function AgentsAdmin() {
  const [agents, setAgents] = useState<AgentTemplate[]>([])
  const [teams, setTeams] = useState<ExpertTeam[]>([])
  const [skills, setSkills] = useState<SkillPackage[]>([])
  const [mode, setMode] = useState<'agents' | 'teams'>('agents')
  const [editing, setEditing] = useState<Draft | null>(null)
  const [selectedTeam, setSelectedTeam] = useState<ExpertTeam | null>(null)
  const [error, setError] = useState('')
  const load = () => Promise.all([api.agentTemplates(), api.expertTeams(), api.skillPackages()])
    .then(([a, t, s]) => { setAgents(a); setTeams(t); setSkills(s) }).catch(e => setError(String(e)))
  useEffect(() => { void load() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const installed = useMemo(() => skills.filter(s => s.status === 'installed'), [skills])
  const edit = (a: AgentTemplate) => setEditing({
    ...a, skill_ids: a.skills.map(s => s.id),
  })
  async function save() {
    if (!editing?.name.trim() || !editing.code.trim()) return
    try {
      const body = { ...editing }
      if (editing.id) await api.updateAgentTemplate(editing.id, body)
      else await api.createAgentTemplate(body)
      setEditing(null); await load()
    } catch (e) { setError(String(e)) }
  }
  return (
    <div className="experts">
      <div className="expert-head">
        <div className="expert-tabs">
          <button className={mode === 'agents' ? 'active' : ''} onClick={() => setMode('agents')}>数字员工</button>
          <button className={mode === 'teams' ? 'active' : ''} onClick={() => setMode('teams')}>专家团</button>
        </div>
        {mode === 'agents' && <button className="primary" onClick={() => setEditing({ ...empty })}>
          <Icon name="plus" /> 新增数字员工
        </button>}
      </div>
      {error && <div className="fm-err" onClick={() => setError('')}>{error}</div>}
      {mode === 'agents' ? <div className="expert-grid">{agents.map(a =>
        <button className="expert-card" key={a.id} onClick={() => edit(a)}>
          <span className="expert-avatar">{a.name.slice(0, 1)}</span>
          <div className="expert-title"><b>{a.name}</b><code>{a.code}</code></div>
          <p>{a.description || a.charter.slice(0, 100)}</p>
          <div className="expert-skills">{a.skills.map(s => <span key={s.id}>{s.name}</span>)}
            {!a.skills.length && <span className="empty">未挂载 Skill</span>}</div>
        </button>)}</div>
        : <div className="expert-grid">{teams.map(t =>
          <button className="expert-card team" key={t.id} onClick={() => setSelectedTeam(t)}>
            <span className="expert-avatar"><Icon name="users" /></span>
            <div className="expert-title"><b>{t.name}</b><code>{t.code}</code></div>
            <p>{t.description}</p>
            <div className="expert-skills">{t.members.map(m => <span key={m.id}>{m.name} · {m.role_in_team}</span>)}</div>
          </button>)}</div>}
      <Modal open={!!editing} onClose={() => setEditing(null)}
        title={editing?.id ? '编辑数字员工' : '新增数字员工'} wide
        footer={editing && <div className="kbe-actions">
          <button className="ghost" onClick={() => setEditing(null)}>取消</button>
          <button className="primary" onClick={save}>保存</button>
        </div>}>
        {editing && <div className="agent-editor">
          <div className="agent-form">
            <label>中文名称<input value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} /></label>
            <label>唯一 code<input value={editing.code} onChange={e => setEditing({ ...editing, code: e.target.value })} /></label>
            <label>角色类型<input value={editing.role} onChange={e => setEditing({ ...editing, role: e.target.value })} /></label>
            <label>简介<textarea value={editing.description} onChange={e => setEditing({ ...editing, description: e.target.value })} /></label>
            <label>员工章程<textarea className="charter" value={editing.charter} onChange={e => setEditing({ ...editing, charter: e.target.value })} /></label>
            <fieldset><legend>挂载 Skills（可多选）</legend>
              <div className="agent-skill-picker">{installed.map(s => <label key={s.id}>
                <input type="checkbox" checked={editing.skill_ids.includes(s.id)}
                  onChange={e => setEditing({ ...editing, skill_ids: e.target.checked
                    ? [...editing.skill_ids, s.id] : editing.skill_ids.filter(id => id !== s.id) })} />
                <span><b>{s.name}</b><small>{s.description}</small></span>
              </label>)}</div>
            </fieldset>
          </div>
        </div>}
      </Modal>
      <Modal open={!!selectedTeam} onClose={() => setSelectedTeam(null)}
        title={selectedTeam?.name ?? '专家团详情'} wide>
        {selectedTeam && <div className="team-detail">
          <p>{selectedTeam.description}</p>
          <div className="team-meta"><code>{selectedTeam.code}</code>
            <span>{selectedTeam.members.length} 位成员</span></div>
          <div className="skill-section-title">专家成员</div>
          <div className="team-members">{selectedTeam.members.map(member =>
            <div className="team-member" key={member.id}>
              <span className="expert-avatar">{member.name.slice(0, 1)}</span>
              <div><b>{member.name}</b><span>{member.role_in_team}</span></div>
            </div>)}
          </div>
        </div>}
      </Modal>
    </div>
  )
}
