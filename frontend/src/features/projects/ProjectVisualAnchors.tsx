import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import type { ProjectVisualAsset } from '../../api'
import { Icon } from '../../components/Icon'
import { openLightbox } from '../../lib/lightbox'
import { openProjectPosterCanvas } from '../../lib/tapflowEntries'

const ROLES: { role: ProjectVisualAsset['asset_role']; title: string; note: string }[] = [
  { role: 'project_environment_style_anchor', title: '场景画风定位图', note: '锁定世界、材质、色彩与光影语言' },
  { role: 'project_character_ensemble_style_anchor', title: '主要角色风格定位图', note: '固定纯黑背景，只统一角色比例、材质与代表动作' },
  { role: 'project_cover_poster', title: '封面海报', note: '商业主视觉，不作为连续性事实来源' },
]

export function ProjectVisualAnchors({ projectId }: { projectId: number }) {
  const [assets, setAssets] = useState<ProjectVisualAsset[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<ProjectVisualAsset['asset_role'] | 'all' | ''>('')
  useEffect(() => {
    api.projectVisualAssets(projectId).then(setAssets).catch(() =>
      setError('视觉锚点服务尚未就绪，请重启后端服务后刷新'))
  }, [projectId])
  const latest = useMemo(() => {
    const out = new Map<ProjectVisualAsset['asset_role'], ProjectVisualAsset>()
    for (const asset of assets) if (!out.has(asset.asset_role)) out.set(asset.asset_role, asset)
    return out
  }, [assets])

  async function generate(role: ProjectVisualAsset['asset_role']) {
    setBusy(role); setError('')
    try {
      const asset = await api.generateProjectVisualAsset(projectId, role)
      setAssets(prev => [asset, ...prev])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  async function generateAll() {
    setBusy('all'); setError('')
    try {
      const created: ProjectVisualAsset[] = []
      for (const item of ROLES) {
        created.push(await api.generateProjectVisualAsset(projectId, item.role))
      }
      setAssets(prev => [...created.reverse(), ...prev])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      api.projectVisualAssets(projectId).then(setAssets).catch(() => undefined)
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="project-visual-anchors">
      <div className="project-visual-head">
        <h3><Icon name="palette" /> 项目视觉锚点</h3>
        <div className="project-visual-head-actions">
          <span className="dim">项目设定和主要角色完成后生成；重生成不会覆盖历史</span>
          <button type="button" className="ghost" disabled={!!busy} onClick={generateAll}>
            {busy === 'all' ? '依次生成中…' : '依次生成三张'}
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="project-visual-grid">
        {ROLES.map(item => {
          const a = latest.get(item.role)
          return (
            <article className="project-visual-card" key={item.role}>
              <button className="project-visual-image" type="button" disabled={!a}
                onClick={() => a && openLightbox(a.url, `${item.title} · v${a.version}`)}>
                {a ? <img src={a.url} alt={item.title} /> : <span className="dim">尚未生成</span>}
              </button>
              <strong>{item.title}</strong>
              <span className="dim">{item.note}</span>
              {a?.meta.poster_plan && (
                <small title={a.meta.poster_plan.selection_reason}>
                  版式：{a.meta.poster_plan.layout_id}
                </small>
              )}
              {a && <small>当前 v{a.version} · 共 {assets.filter(x => x.asset_role === item.role).length} 个版本</small>}
              <button type="button" className="ghost project-visual-generate"
                disabled={!!busy}
                onClick={() => item.role === 'project_cover_poster'
                  ? openProjectPosterCanvas(projectId, a?.url)
                  : generate(item.role)}>
                {item.role === 'project_cover_poster'
                  ? 'Generate in canvas'
                  : busy === item.role ? 'Generating?' : a ? 'Generate new version' : 'Generate'}
              </button>


            </article>
          )
        })}
      </div>
    </section>
  )
}
