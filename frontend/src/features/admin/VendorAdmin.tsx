import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { ModelVendor, ProviderKeyPreset } from '../../api'
import { Icon } from '../../components/Icon'
import { Modal } from '../../components/Modal'
import { PROVIDERS, PROVIDER_BASE } from '../../lib/modelPresets'

const EMPTY = { label: '', provider: 'ark', base_url: PROVIDER_BASE.ark, api_key: '' }
type Editing = typeof EMPTY & { id?: number }

/** 模型厂商：系统内全部厂商凭据一览——「已登记」（model_vendors 表，可编辑/删除）
 *  + 派生来源（.env 内置 / 已有模型档里的 key，只读）。全部都会出现在
 *  模型配置编辑弹框的「API Key 来源」下拉里。 */
export function VendorAdmin() {
  const [vendors, setVendors] = useState<ModelVendor[]>([])
  const [keys, setKeys] = useState<ProviderKeyPreset[]>([])
  const [editing, setEditing] = useState<Editing | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(() => {
    api.listVendors().then(setVendors)
    api.listProviderKeys().then(setKeys)
  }, [])
  useEffect(() => { reload() }, [reload])

  const openNew = () => { setEditing({ ...EMPTY }); setError('') }
  const openEdit = (v: ModelVendor) => {
    setEditing({ id: v.id, label: v.label, provider: v.provider, base_url: v.base_url, api_key: '' })
    setError('')
  }
  const changeProvider = (provider: string) => {
    if (!editing) return
    // Base URL 还停在上一家默认值（或为空）时跟着换，手改过的地址不动
    const keep = editing.base_url && editing.base_url !== (PROVIDER_BASE[editing.provider] || '')
    setEditing({ ...editing, provider, base_url: keep ? editing.base_url : PROVIDER_BASE[provider] || '' })
  }
  const save = async () => {
    if (!editing?.label) { setError('厂商名称必填'); return }
    if (!editing.id && !editing.api_key) { setError('新增厂商必须填 API Key'); return }
    setSaving(true); setError('')
    try {
      if (editing.id) await api.updateVendor(editing.id, editing)
      else await api.createVendor(editing)
      setEditing(null); reload()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setSaving(false) }
  }
  const remove = async (id: number) => {
    if (confirm('确认删除？已保存的模型档不受影响。')) { await api.deleteVendor(id); reload() }
  }

  const providerLabel = (v: string) => PROVIDERS.find(p => p.value === v)?.label || v
  const srcTag = (ref: string) => ref.startsWith('vendor:') ? '已登记'
    : ref.startsWith('settings:') ? '.env 内置' : '沿用模型档'
  return (
    <div className="adm-panel">
      <div className="adm-head">
        <h2><Icon name="users" /> 模型厂商</h2>
        <span className="dim">系统内全部厂商凭据；新增模型时可在「API Key 来源」直接选用。</span>
        <div className="adm-actions">
          <button className="small" onClick={openNew}>＋新增厂商</button>
        </div>
      </div>
      <div className="adm-scroll">
        <div className="card">
          {!keys.length && <div className="dim">暂无可用凭据——请新增厂商，或在 .env 里配置内置 Key。</div>}
          {keys.map(k => {
            const vend = k.ref.startsWith('vendor:')
              ? vendors.find(v => v.id === Number(k.ref.slice('vendor:'.length))) : undefined
            return (
              <div key={k.ref} className="kb-row">
                <div>
                  <b>{k.label}</b>
                  <span className="tag">{providerLabel(k.provider)}</span>
                  <span className="tag">{srcTag(k.ref)}</span>
                  <div className="dim">{k.base_url || '（未填 Base URL）'} ｜ key: {k.masked || '（未配置）'}</div>
                </div>
                <div className="btns">
                  {vend && <>
                    <button className="small ghost" onClick={() => openEdit(vend)}>编辑</button>
                    <button className="small ghost" onClick={() => remove(vend.id)}>删除</button>
                  </>}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <Modal open={!!editing} onClose={() => !saving && setEditing(null)}
        closeOnBackdrop={!saving} title={editing?.id ? `编辑厂商 #${editing.id}` : '新增厂商'}>
        {editing && <div className="model-editor">
          <label><span>厂商名称</span>
            <input placeholder="例如：公司百炼主账号" value={editing.label}
              onChange={e => setEditing({ ...editing, label: e.target.value })} />
          </label>
          <label><span>接口类型</span>
            <select value={editing.provider} onChange={e => changeProvider(e.target.value)}>
              {PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </label>
          <label><span>Base URL</span>
            <input value={editing.base_url}
              onChange={e => setEditing({ ...editing, base_url: e.target.value })} />
          </label>
          <label><span>API Key</span>
            <input type="password" placeholder={editing.id ? '留空=沿用原 Key' : '输入 API Key'}
              value={editing.api_key}
              onChange={e => setEditing({ ...editing, api_key: e.target.value })} />
          </label>
          {error && <div className="model-error">{error}</div>}
          <div className="modal-actions btns">
            <button className="ghost" disabled={saving} onClick={() => setEditing(null)}>取消</button>
            <button disabled={saving} onClick={save}>
              <Icon name={saving ? 'spinner' : 'save'} spin={saving} /> {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </div>}
      </Modal>
    </div>
  )
}
