import { useState } from 'react'
import { api } from '../../api'
import type { ResourceVendor } from '../../api'
import { Icon } from '../../components/Icon'
import { Modal } from '../../components/Modal'

/** 手动登记一条资源包/免费额度：百炼「免费额度」页没有 CSV 导出，照着控制台一行一行补即可。 */
export function ResourcePackageForm({ open, vendor, onClose, onSaved }: {
  open: boolean
  vendor: ResourceVendor
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState({ config_name: '', total: '', remaining: '', expires_at: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value })

  const save = async () => {
    const name = form.config_name.trim()
    if (!name) { setError('模型 Code / 配置名称必填'); return }
    setSaving(true); setError('')
    try {
      const total = Number(form.total || 0)
      await api.createResourcePackage({
        vendor, config_name: name, total,
        remaining: form.remaining === '' ? total : Number(form.remaining),
        expires_at: form.expires_at.trim(), status: '生效中',
      })
      setForm({ config_name: '', total: '', remaining: '', expires_at: '' })
      onSaved(); onClose()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setSaving(false) }
  }

  const isBailian = vendor === 'bailian'
  return (
    <Modal open={open} onClose={() => !saving && onClose()} closeOnBackdrop={!saving}
      title={`手动新增资源包 · ${isBailian ? '阿里百炼' : '火山方舟'}`}>
      <div className="model-editor">
        <label><span>{isBailian ? '模型 Code' : '配置名称'}</span>
          <input value={form.config_name} onChange={set('config_name')}
            placeholder={isBailian ? '控制台原样，如 qwen3-vl-32b-thinking' : '如 Doubao-Seedream-4.0-在线推理资源包'} />
        </label>
        <div className="model-form-grid">
          <label><span>总量</span>
            <input type="number" value={form.total} onChange={set('total')} placeholder="如 1000000" />
          </label>
          <label><span>余量</span>
            <input type="number" value={form.remaining} onChange={set('remaining')} placeholder="留空=同总量" />
          </label>
        </div>
        <label><span>失效时间</span>
          <input value={form.expires_at} onChange={set('expires_at')} placeholder="如 2026/10/31" />
        </label>
        <div className="dim">
          模态与真实模型名由后端按名称派生（百炼的模型 Code 即 API 可调用模型名），保存后可直接「插入模型管理」。
        </div>
        {error && <div className="model-error">{error}</div>}
        <div className="modal-actions btns">
          <button className="ghost" disabled={saving} onClick={onClose}>取消</button>
          <button disabled={saving} onClick={save}>
            <Icon name={saving ? 'spinner' : 'save'} spin={saving} /> {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
