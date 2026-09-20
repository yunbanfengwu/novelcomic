import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type { Project } from '../../api'
import { Icon } from '../../components/Icon'
import { GuidedCreateModal } from './guide/GuidedCreateModal'
import { UserConsole } from '../../components/console/UserConsole'
import { UserSwitcher } from '../../components/UserSwitcher'
import './projects.css'

// ═══════════ 首页：系统桌面 —— 视频背景 + 胶囊创建栏 + 桌面图标（作品 / 系统管理） ═══════════

export function ProjectList() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [draft, setDraft] = useState('')
  const [time, setTime] = useState('')
  // 引导式新建弹框：null=关；string=开（携带首页已输入的草稿，可为空）
  const [wizardDraft, setWizardDraft] = useState<string | null>(null)
  // 用户控制台弹窗（用户信息/充值管理/回收站）
  const [consoleOpen, setConsoleOpen] = useState(false)

  // 首页背景：无默认值，未配置=纯黑；系统配置里取第一组（有视频放视频，只有图就只显示图）
  const [bg, setBg] = useState<{ image: string; video: string }>({ image: '', video: '' })

  const reload = () => api.listProjects().then(setProjects).catch(console.error)
  useEffect(() => { reload() }, [])

  // 删除项目到回收站（软删除，可在控制台·回收站恢复）
  const handleDelete = async (p: Project) => {
    if (!confirm(`将「${p.title}」移入回收站？\n可在「控制台 · 回收站」恢复或彻底删除。`)) return
    try { await api.deleteProject(p.id); reload() }
    catch (e) { alert((e as Error).message) }
  }

  useEffect(() => {
    api.getHomeBg().then(d => {
      const g = d.groups?.[0]
      if (g) setBg({ image: g.image || '', video: g.video || '' })
    }).catch(() => { /* 配置读不到就纯黑背景，不打扰用户 */ })
  }, [])
  useEffect(() => {
    const updateTime = () => {
      const now = new Date()
      const h = String(now.getHours()).padStart(2, '0')
      const m = String(now.getMinutes()).padStart(2, '0')
      setTime(`${h}:${m}`)
    }
    updateTime()
    const timer = setInterval(updateTime, 60000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="desktop">
      <div className="desk-bg">
        {bg.video ? (
          <video key={bg.video} poster={bg.image || undefined}
            autoPlay muted loop playsInline preload="auto">
            <source src={bg.video} type="video/mp4" />
          </video>
        ) : bg.image ? (
          <img src={bg.image} alt="" />
        ) : null}
      </div>
      <div className="desk-sys-float">
        {/* 开发期用户切换：X-User-Id 身份下拉，后端按归属过滤项目列表 */}
        <UserSwitcher />
        <button className="sys-btn" onClick={() => setConsoleOpen(true)}>
          <Icon name="console" />
          <span>控制台</span>
        </button>
        <button className="sys-btn" onClick={() => navigate('/admin')}>
          <Icon name="gear" />
          <span>系统管理</span>
        </button>
      </div>
      <div className="desk-time">{time}</div>
      <div className="omnibar">
        <Icon name="wand" />
        <input value={draft} onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') setWizardDraft(draft) }}
          placeholder="即刻创作..." />
        <button className="omni-go" onClick={() => setWizardDraft(draft)} title="开始创建">去创作</button>
      </div>
      <div className="desk-icons">
        {projects.map(p => (
          <div key={p.id} className="desk-icon-wrap">
            <button className="desk-icon" onClick={() => navigate(`/project/${p.id}`)} title={p.title}>
              <span className="desk-ico">{p.title.slice(0, 1)}</span>
              <span className="desk-label">{p.title}</span>
            </button>
            <button className="desk-icon-del" title="删除到回收站"
              onClick={() => handleDelete(p)}><Icon name="trash" /></button>
          </div>
        ))}
      </div>
      {!projects.length && <div className="desk-hint">&nbsp;;</div>}
      {wizardDraft !== null && (
        <GuidedCreateModal initialDraft={wizardDraft}
          onDone={id => { setWizardDraft(null); navigate(`/project/${id}`) }}
          onClose={() => { setWizardDraft(null); reload() }} />
      )}
      <UserConsole open={consoleOpen} onClose={() => setConsoleOpen(false)} onProjectsChanged={reload} />
    </div>
  )
}
