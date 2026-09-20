import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { FeatureModelConfig, ModelProfile } from '../../api'
import { Icon } from '../../components/Icon'
import { ModelRow } from './ModelRow'
import { PURPOSE_META } from '../../lib/modelPresets'

/** 模型配置的「按功能」视图：功能清单后端写死（feature_registry），每个功能挂一组
 *  有序模型档，第一个为默认；空列表回退该大类的「当前使用」模型。行样式与按类型视图同源。 */
export function FeatureModelView({ models, onEdit }: {
  models: ModelProfile[]; onEdit: (m: ModelProfile) => void
}) {
  const [features, setFeatures] = useState<FeatureModelConfig[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const reload = useCallback(() => { api.listModelFeatures().then(setFeatures) }, [])
  useEffect(() => { reload() }, [reload])

  const save = async (code: string, ids: number[]) => {
    setBusy(code); setError('')
    try { await api.saveModelFeature(code, ids); reload() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy('') }
  }
  const move = (f: FeatureModelConfig, idx: number, delta: -1 | 1) => {
    const ids = f.models.map(m => m.id)
    const j = idx + delta
    if (j < 0 || j >= ids.length) return
    ;[ids[idx], ids[j]] = [ids[j], ids[idx]]
    save(f.code, ids)
  }
  const removeAt = (f: FeatureModelConfig, idx: number) =>
    save(f.code, f.models.filter((_, i) => i !== idx).map(m => m.id))
  const add = (f: FeatureModelConfig, id: number) =>
    save(f.code, [...f.models.map(m => m.id), id])

  return (
    <div className="adm-scroll">
      <div className="dim fma-hint">按功能维护模型顺序，生成时默认使用第一个；未配置的功能回退该大类的「当前使用」模型。</div>
      {error && <div className="model-error">{error}</div>}
      {features.map(f => {
        const used = new Set(f.models.map(m => m.id))
        const candidates = models.filter(m => m.purpose === f.purpose && !used.has(m.id))
        const saving = busy === f.code
        return (
          <div key={f.code} className="card">
            <div className="fma-head">
              <h2>
                <Icon name={PURPOSE_META[f.purpose]?.icon || 'puzzle'} /> {f.label}
                <span className="tag">{f.code}</span>
                <span className="tag">{PURPOSE_META[f.purpose]?.label || f.purpose}</span>
                {saving && <Icon name="spinner" spin />}
              </h2>
              <select className="fma-add" value="" disabled={saving || !candidates.length}
                onChange={e => e.target.value && add(f, Number(e.target.value))}>
                <option value="">{candidates.length ? '＋添加模型…' : '无可添加模型'}</option>
                {candidates.map(m =>
                  <option key={m.id} value={m.id}>{m.name} · {m.model_name}</option>)}
              </select>
            </div>
            {f.hint && <div className="dim">{f.hint}</div>}
            {!f.models.length &&
              <div className="dim">未配置——使用「{PURPOSE_META[f.purpose]?.label || f.purpose}」的当前启用模型</div>}
            {f.models.map((m, i) => {
              const prof = models.find(x => x.id === m.id)
              return (
                <ModelRow key={m.id} m={prof ?? m} seq={i + 1} isDefault={i === 0} actions={<>
                  <button className="small ghost" disabled={saving || i === 0}
                    title="上移" onClick={() => move(f, i, -1)}>↑</button>
                  <button className="small ghost" disabled={saving || i === f.models.length - 1}
                    title="下移" onClick={() => move(f, i, 1)}>↓</button>
                  {prof && <button className="small ghost" disabled={saving}
                    onClick={() => onEdit(prof)}>编辑</button>}
                  <button className="small ghost" disabled={saving}
                    onClick={() => removeAt(f, i)}>移除</button>
                </>} />
              )
            })}
          </div>
        )
      })}
    </div>
  )
}
