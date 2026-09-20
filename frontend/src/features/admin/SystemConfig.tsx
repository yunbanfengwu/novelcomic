import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { GenConfig, HomeBgGroup } from '../../api'
import { Icon } from '../../components/Icon'
import { primeGenConfig } from '../../lib/useGenConfig'

/**
 * 系统配置：运行期可编辑的全局配置——首页背景（多组图 + 视频供轮播，
 * 前端当前只取第一组展示）与生成配置开关。
 */
export function SystemConfig() {
  const [groups, setGroups] = useState<HomeBgGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [gen, setGen] = useState<GenConfig>({ realistic_character: true, allow_project_ark_upload: true })
  const [genMsg, setGenMsg] = useState('')

  useEffect(() => {
    api.getHomeBg()
      .then(d => setGroups(d.groups?.length ? d.groups : [{ image: '', video: '' }]))
      .catch(e => setMsg(String(e.message || e)))
      .finally(() => setLoading(false))
    api.getGenConfig()
      .then(c => { setGen(c); primeGenConfig(c) })
      .catch(() => {})
  }, [])

  // 生成配置各开关：即改即存，只发变动字段（后端按字段合并，互不清零）
  const patchGen = async (p: Partial<GenConfig>) => {
    const prev = gen
    setGen({ ...gen, ...p }); setGenMsg('')
    try {
      const c = await api.setGenConfig(p)
      setGen(c); primeGenConfig(c); setGenMsg('已保存')
    } catch (e) {
      setGen(prev); setGenMsg(String((e as Error).message || e))
    }
  }

  const patch = (i: number, k: keyof HomeBgGroup, v: string) =>
    setGroups(gs => gs.map((g, j) => (j === i ? { ...g, [k]: v } : g)))
  const addGroup = () => setGroups(gs => [...gs, { image: '', video: '' }])
  const removeGroup = (i: number) => setGroups(gs => gs.filter((_, j) => j !== i))

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      // 去掉图与视频都为空的组，避免存空壳
      const clean = groups.filter(g => g.image.trim() || g.video.trim())
      const d = await api.setHomeBg(clean.map(g => ({ image: g.image.trim(), video: g.video.trim() })))
      setGroups(d.groups.length ? d.groups : [{ image: '', video: '' }])
      setMsg('已保存')
    } catch (e) {
      setMsg(String((e as Error).message || e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="adm-panel">
      <div className="adm-head">
        <h2><Icon name="monitor" /> 系统配置</h2>
        <div className="adm-actions">
          {msg && <span className="dim sc-msg">{msg}</span>}
          <button className="primary" onClick={save} disabled={saving || loading}>
            {saving ? <><Icon name="spinner" spin /> 保存中</> : '保存'}
          </button>
        </div>
      </div>
      <div className="adm-scroll">
        <section className="sc-section">
          <div className="sc-sec-head">
            <h3>首页背景</h3>
            <span className="dim sc-hint">支持多组轮播；前端当前只取第一组展示。图作视频加载前的封面/回退。</span>
          </div>
          {loading ? (
            <div className="dim"><Icon name="spinner" spin /> 加载中…</div>
          ) : (
            <div className="sc-groups">
              {groups.map((g, i) => (
                <div key={i} className="sc-group">
                  <div className="sc-group-head">
                    <span className="tag">第 {i + 1} 组{i === 0 ? '（当前使用）' : ''}</span>
                    {groups.length > 1 && (
                      <button className="elem-x" onClick={() => removeGroup(i)} title="删除该组">✕</button>
                    )}
                  </div>
                  <label className="sc-field">
                    <span className="sc-label"><Icon name="image" /> 背景图 URL</span>
                    <input value={g.image} placeholder="https://…/xxx.webp"
                      onChange={e => patch(i, 'image', e.target.value)} />
                  </label>
                  <label className="sc-field">
                    <span className="sc-label"><Icon name="video" /> 背景视频 URL</span>
                    <input value={g.video} placeholder="https://…/xxx.mp4"
                      onChange={e => patch(i, 'video', e.target.value)} />
                  </label>
                </div>
              ))}
              <button className="ghost sc-add" onClick={addGroup}>+ 添加一组</button>
            </div>
          )}
        </section>

        <section className="sc-section">
          <div className="sc-sec-head">
            <h3>生成配置</h3>
            {genMsg && <span className="dim sc-hint">{genMsg}</span>}
          </div>
          <label className="sc-toggle">
            <button type="button" role="switch" aria-checked={gen.realistic_character}
              className={`sc-switch${gen.realistic_character ? ' on' : ''}`}
              onClick={() => patchGen({ realistic_character: !gen.realistic_character })}>
              <span className="sc-switch-knob" />
            </button>
            <span className="sc-toggle-text">
              <span className="sc-toggle-title">生成真人角色卡</span>
              <span className="dim sc-hint">
                {gen.realistic_character
                  ? '启用：允许照片级真人写实。质感更强，但出图/视频提交可能被判"疑似真人"拒收。'
                  : '禁用：角色强制为虚拟人物——保留物理真实感，但五官不贴近真人，规避拒收。'}
              </span>
            </span>
          </label>
          <label className="sc-toggle">
            <button type="button" role="switch" aria-checked={gen.allow_project_ark_upload}
              className={`sc-switch${gen.allow_project_ark_upload ? ' on' : ''}`}
              onClick={() => patchGen({ allow_project_ark_upload: !gen.allow_project_ark_upload })}>
              <span className="sc-switch-knob" />
            </button>
            <span className="sc-toggle-text">
              <span className="sc-toggle-title">允许项目直接上传到火山虚拟角色库</span>
              <span className="dim sc-hint">
                {gen.allow_project_ark_upload
                  ? '启用：项目角色面板保留「加入火山角色库」入口，可直接把角色设定图提交备案。'
                  : '禁用：隐藏项目侧直传入口，统一到「角色库」集中管理（角色可分组、一角色多套图）。'}
              </span>
            </span>
          </label>
        </section>
      </div>
    </div>
  )
}
