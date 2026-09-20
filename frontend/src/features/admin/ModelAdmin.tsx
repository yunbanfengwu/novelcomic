import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import type { ModelProfile, ModelTestResult, ProviderKeyPreset, ResourcePackage } from '../../api'
import { Icon } from '../../components/Icon'
import { ModelRow } from './ModelRow'
import { ModelEditorModal } from './ModelEditorModal'
import { FeatureModelView } from './FeatureModelView'
import {
  EMPTY_MODEL, MODEL_PRESETS, PROVIDER_BASE, PURPOSES, PURPOSE_META, SPECIAL_HINT,
  SPECIAL_PURPOSES, VENDOR_PROVIDER,
} from '../../lib/modelPresets'
import type { ModelEditing } from '../../lib/modelPresets'

type Purpose = typeof PURPOSES[number]
const isSpecial = (p: string) => (SPECIAL_PURPOSES as readonly string[]).includes(p)

/** 模型配置：同一批模型档的两个视图——按类型（purpose 大类浏览+启用）与按功能
 *  （功能维度挂载排序），共用行样式与编辑弹框。 */
export function ModelAdmin() {
  const [view, setView] = useState<'purpose' | 'feature'>('purpose')
  const [models, setModels] = useState<ModelProfile[]>([])
  const [keys, setKeys] = useState<ProviderKeyPreset[]>([])
  const [packages, setPackages] = useState<ResourcePackage[]>([])
  // 'special' = 专用模型合并视图（数学/代码/重排/OCR/翻译/其它），与生成用途分栏浏览
  const [filter, setFilter] = useState<'' | Purpose | 'special'>('')
  const [editing, setEditing] = useState<ModelEditing | null>(null)
  const [testPrompt, setTestPrompt] = useState('')
  // 图像编辑族（qwen-image-edit 等）测试必须带底图：逗号/换行分隔的公开图片 URL
  const [testRefs, setTestRefs] = useState('')
  const [testResult, setTestResult] = useState<ModelTestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(() => { api.listModels().then(setModels) }, [])
  useEffect(() => {
    reload()
    api.listProviderKeys().then(setKeys)
    api.listResourcePackages({ only_remaining: true }).then(setPackages)
  }, [reload])

  useEffect(() => {
    setEditing(e => {
      if (!e) return e
      // provider 表示接口协议，不等于凭据厂商：火山文本/向量接口同样是 openai_compat，
      // 但必须继续使用 ARK Key。编辑已有模型时绝不能按 provider 自动换成硅基流动 Key。
      const valid = !!e.key_ref && keys.some(k => k.ref === e.key_ref)
      if (!valid && e.key_ref) return { ...e, key_ref: '' }
      if (e.id || e.api_key || e.key_ref) return e
      const mine = keys.filter(k => k.provider === e.provider)
      if (mine.length === 1) return { ...e, key_ref: mine[0].ref }
      return e
    })
  }, [editing?.provider, keys])

  // 该 provider 的 Base URL：优先用厂商 Key 预设自带的（百炼工作空间专属 maas 域名 ≠ 通用域名）
  const baseUrlFor = useCallback((provider: string) =>
    keys.find(k => k.provider === provider)?.base_url || PROVIDER_BASE[provider] || '', [keys])

  // 新建档换厂商时顺带换 Key：已选的 Key 不属于新厂商就换成该厂商唯一可用的（没有则清空）。
  // 只对新建生效——编辑已有档时绝不自动换 Key（火山文本走兼容口但必须继续用 ARK Key）。
  const keyRefFor = useCallback((provider: string, current: string) => {
    if (keys.find(k => k.ref === current)?.provider === provider) return current
    const mine = keys.filter(k => k.provider === provider)
    return mine.length === 1 ? mine[0].ref : ''
  }, [keys])

  const suggestions = useMemo(() => {
    if (!editing) return []
    const wanted = editing.purpose === 'tts' ? 'audio' : editing.purpose
    const resources = packages.filter(p => p.modality === wanted).map(p => ({
      label: `${p.config_name}（${p.vendor_label}资源包）`, name: p.config_name,
      model: p.real_model_name, provider: VENDOR_PROVIDER[p.vendor] || 'ark',
    }))
    const presets = MODEL_PRESETS.filter(p => p.purpose === editing.purpose)
      .map(p => ({ label: p.name, name: p.name, model: p.model, provider: p.provider }))
    return [...presets, ...resources]
  }, [editing, packages])

  const openNew = () => {
    const purpose = filter === 'special' ? 'math' : (filter || 'image')
    // 专用模型的候选清一色是百炼（数学/代码/重排/OCR/翻译），默认就选百炼省一次切换
    const provider = isSpecial(purpose) ? 'dashscope'
      : purpose === 'embedding' ? 'openai_compat' : 'ark'
    setEditing({ ...EMPTY_MODEL, purpose, provider, base_url: baseUrlFor(provider) })
    setTestPrompt(''); setTestResult(null); setError('')
  }
  const openEdit = (m: ModelProfile) => {
    // 后端不下发明文，只需用掩码在可选凭据中定位原 Key；找不到时保持空，
    // 测试/保存均由后端根据 id 沿用数据库里的原 Key。
    const currentKey = keys.find(k => k.masked === m.api_key_masked)
    setEditing({
      id: m.id, purpose: m.purpose, provider: m.provider, name: m.name,
      base_url: m.base_url, api_key: '', key_ref: currentKey?.ref || '', model_name: m.model_name,
      max_refs: m.max_refs ?? null, extra: m.extra || {},
    })
    setTestPrompt(''); setTestResult(null); setError('')
  }
  const applySuggestion = (value: string) => {
    const item = suggestions.find(s => s.model === value)
    if (!editing || !item) return
    setEditing({
      ...editing, model_name: item.model, name: item.name,
      provider: item.provider, base_url: baseUrlFor(item.provider),
      key_ref: editing.id ? editing.key_ref : keyRefFor(item.provider, editing.key_ref),
    })
  }
  const changePurpose = (purpose: string) => {
    if (!editing) return
    setEditing({ ...editing, purpose }); setTestResult(null)
  }
  const changeProvider = (provider: string) => {
    if (!editing) return
    // Base URL 还停在上一家的默认值（或为空）时跟着换，用户手改过的地址不动
    const keep = editing.base_url && editing.base_url !== baseUrlFor(editing.provider)
    setEditing({
      ...editing, provider, base_url: keep ? editing.base_url : baseUrlFor(provider),
      key_ref: editing.id ? editing.key_ref : keyRefFor(provider, editing.key_ref),
    })
  }
  const save = async () => {
    if (!editing?.name || !editing.model_name || !editing.base_url) {
      setError('名称、Base URL 与模型 ID 必填'); return
    }
    setSaving(true); setError('')
    try {
      if (editing.id) await api.updateModel(editing.id, editing)
      else await api.createModel(editing)
      setEditing(null); reload()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setSaving(false) }
  }
  const test = async () => {
    if (!editing || !testPrompt.trim()) { setError('请输入测试内容'); return }
    setTesting(true); setTestResult(null); setError('')
    const refs = testRefs.split(/[\n,]+/).map(x => x.trim()).filter(Boolean)
    try { setTestResult(await api.testModel({ ...editing, prompt: testPrompt.trim(),
      ...(refs.length ? { reference_images: refs } : {}) })) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setTesting(false) }
  }
  const activate = async (id: number) => { await api.activateModel(id); reload() }
  const remove = async (id: number) => {
    if (confirm('确认删除？')) { await api.deleteModel(id); reload() }
  }

  // 「全部」视图：生成用途常驻 + 只显示真正挂了档的专用分组，避免六个空卡片刷屏
  const groups: readonly string[] = filter === 'special' ? SPECIAL_PURPOSES
    : filter ? [filter]
      : [...PURPOSES, ...SPECIAL_PURPOSES.filter(p => models.some(m => m.purpose === p))]
  return (
    <div className="adm-panel">
      <div className="adm-head">
        <h2><Icon name="robot" /> 模型配置</h2>
        <div className="seg">
          <button className={`seg-btn${view === 'purpose' ? ' active' : ''}`}
            onClick={() => setView('purpose')}>按类型</button>
          <button className={`seg-btn${view === 'feature' ? ' active' : ''}`}
            onClick={() => setView('feature')}>按功能</button>
        </div>
        <div className="adm-actions">
          <button className="small" onClick={openNew}>＋新增模型</button>
        </div>
      </div>

      {view === 'purpose' && <div className="ma-filter seg">
        <button className={`seg-btn${filter === '' ? ' active' : ''}`}
          onClick={() => setFilter('')}>全部</button>
        {PURPOSES.map(p => (
          <button key={p} className={`seg-btn${filter === p ? ' active' : ''}`}
            onClick={() => setFilter(p)}>
            <Icon name={PURPOSE_META[p].icon} /> {PURPOSE_META[p].label}
          </button>
        ))}
        <button className={`seg-btn${filter === 'special' ? ' active' : ''}`}
          title="不参与生成" onClick={() => setFilter('special')}>
          <Icon name="puzzle" /> 专用模型
        </button>
      </div>}

      {view === 'purpose' ? (
        <div className="adm-scroll">
          {groups.map(purpose => (
            <div key={purpose} className="card">
              <h2><Icon name={PURPOSE_META[purpose].icon} /> {PURPOSE_META[purpose].label}</h2>
              {isSpecial(purpose) && <div className="dim">{SPECIAL_HINT}</div>}
              {!models.some(m => m.purpose === purpose) && <div className="dim">暂无配置</div>}
              {models.filter(m => m.purpose === purpose).map(m => (
                <ModelRow key={m.id} m={m} actions={<>
                  {!m.is_active && <button className="small" onClick={() => activate(m.id)}>启用</button>}
                  <button className="small ghost" onClick={() => openEdit(m)}>编辑</button>
                  <button className="small ghost" onClick={() => remove(m.id)}>删除</button>
                </>} />
              ))}
            </div>
          ))}
        </div>
      ) : (
        <FeatureModelView models={models} onEdit={openEdit} />
      )}

      <ModelEditorModal editing={editing} keys={keys} suggestions={suggestions}
        saving={saving} testing={testing} error={error}
        testPrompt={testPrompt} testResult={testResult}
        onChange={setEditing} onPurposeChange={changePurpose} onProviderChange={changeProvider}
        onApplySuggestion={applySuggestion} onTestPrompt={setTestPrompt}
        testRefs={testRefs} onTestRefs={setTestRefs}
        onTest={test} onSave={save} onClose={() => setEditing(null)} />
    </div>
  )
}
