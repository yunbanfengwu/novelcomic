import { useEffect, useMemo, useState } from 'react'
import { api, type SkillPackage } from '../../api'
import { Icon } from '../../components/Icon'
import { Modal } from '../../components/Modal'

export function SkillsAdmin() {
  const [skills, setSkills] = useState<SkillPackage[]>([])
  const [query, setQuery] = useState('')
  const [source, setSource] = useState('')
  const [installing, setInstalling] = useState(false)
  const [showInstall, setShowInstall] = useState(false)
  const [selected, setSelected] = useState<SkillPackage | null>(null)
  const [error, setError] = useState('')
  const load = () => api.skillPackages().then(setSkills).catch(e => setError(String(e)))
  useEffect(() => { void load() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? skills.filter(s => `${s.name} ${s.slug} ${s.description}`.toLowerCase().includes(q)) : skills
  }, [skills, query])
  async function install() {
    if (!source.trim()) return
    setInstalling(true); setError('')
    try {
      await api.installSkillPackage(source.trim())
      setSource(''); setShowInstall(false); await load()
    } catch (e) { setError(String(e)) } finally { setInstalling(false) }
  }
  return (
    <div className="skillhub">
      <div className="skillhub-head">
        <div>
          <h2>Skills</h2>
          <p className="dim">符合 Agent Skills 规范的独立能力包，可被多个数字员工和 SOP 复用。</p>
        </div>
        <div className="skillhub-actions">
          <input placeholder="搜索已安装 Skills" value={query} onChange={e => setQuery(e.target.value)} />
          <button className="primary" onClick={() => setShowInstall(v => !v)}>
            <Icon name="plus" /> 从 GitHub / URL 安装
          </button>
        </div>
      </div>
      {showInstall && <div className="skill-install">
        <input value={source} onChange={e => setSource(e.target.value)}
          placeholder="https://github.com/owner/repo/tree/main/path/to/skill" />
        <button disabled={installing || !source.trim()} onClick={install}>
          {installing ? '下载并校验中…' : '安装 Skill'}
        </button>
        <span className="dim">自动读取并校验 SKILL.md、frontmatter、references 和 scripts。</span>
      </div>}
      {error && <div className="fm-err" onClick={() => setError('')}>{error}</div>}
      <div className="skill-grid">
        {shown.map(s => <button className="skill-card" key={s.id} onClick={() => setSelected(s)}>
          <span className="skill-avatar">{s.name.slice(0, 1).toUpperCase()}</span>
          <div><b>{s.name}</b><code>{s.slug} · v{s.version}</code></div>
          <p>{s.description}</p>
          <div className="skill-card-foot">
            <span>{s.manifest.legacy ? '兼容迁移' : 'Agent Skills'}</span>
            <span>{s.file_count} 文件 · {s.agent_count} 员工挂载</span>
          </div>
        </button>)}
      </div>
      <Modal open={!!selected} onClose={() => setSelected(null)}
        title={selected?.name ?? 'Skill 详情'} wide>
        {selected && <div className="skill-detail">
          <p className="skill-description">{selected.description}</p>
          <div className="skill-meta"><code>{selected.slug}</code><span>v{selected.version}</span>
            {selected.source_url && <a href={selected.source_url} target="_blank" rel="noreferrer">来源</a>}</div>
          <div className="skill-section-title">SKILL.md</div>
          <pre className="skill-md">{selected.skill_md}</pre>
        </div>}
      </Modal>
    </div>
  )
}
