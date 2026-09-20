import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import type { ResourcePackage, ResourceVendor } from '../../api'
import { Icon } from '../../components/Icon'
import { ResourcePackageTable } from './ResourcePackageTable'
import { ResourcePackageForm } from './ResourcePackageForm'
import { ResourcePackageTest } from './ResourcePackageTest'

const VENDORS = [
  { key: '', label: '全部' }, { key: 'volc', label: '火山方舟' }, { key: 'bailian', label: '阿里百炼' },
] as const
// 与后端 resource_map.MODALITY_LABEL 同序同名。数学/代码/重排/OCR/翻译从「文本」里
// 拆出来独立成模态——它们插入模型管理时挂的是同名 purpose，不会污染文本 LLM 候选。
const MODALITIES = [
  { key: '', label: '全部' }, { key: 'text', label: '文本' }, { key: 'image', label: '图片' },
  { key: 'video', label: '视频' }, { key: 'audio', label: '音频' },
  { key: 'embedding', label: '向量' }, { key: '3d', label: '3D' },
  { key: 'math', label: '数学' }, { key: 'code', label: '代码' },
  { key: 'rerank', label: '重排' }, { key: 'ocr', label: 'OCR' },
  { key: 'translate', label: '翻译' }, { key: 'other', label: '其它' },
] as const

/** 资源包剩余：火山方舟 / 阿里百炼两家的余量与免费额度浏览 + 拍寻过滤
 * + 一键插入模型管理/设为默认 + 按厂商重传 CSV / 手动登记。 */
export function ResourcePackages() {
  const [rows, setRows] = useState<ResourcePackage[]>([])
  const [vendor, setVendor] = useState<'' | ResourceVendor>('')
  const [modality, setModality] = useState('')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [testing, setTesting] = useState<ResourcePackage | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const reload = useCallback(() => { api.listResourcePackages().then(setRows) }, [])
  useEffect(() => { reload() }, [reload])

  const shown = useMemo(() => {
    const s = search.trim().toLowerCase()
    return rows.filter(r =>
      (!vendor || r.vendor === vendor) &&
      (!modality || r.modality === modality) &&
      (!s || r.config_name.toLowerCase().includes(s) ||
        r.real_model_name.toLowerCase().includes(s) || r.product.toLowerCase().includes(s)))
      // 有余量的在前、已用完(余量0且总量>0)的沉底——额度未登记的行按正常处理，
      // 不受失效时间影响；组内再按失效时间升序（最快到期在前）
      .sort((a, b) =>
        (a.remaining <= 0 && a.total > 0 ? 1 : 0) - (b.remaining <= 0 && b.total > 0 ? 1 : 0) ||
        a.expires_at.localeCompare(b.expires_at))
  }, [rows, vendor, modality, search])

  const toModel = async (r: ResourcePackage, activate: boolean) => {
    setBusy(r.instance_id)
    try {
      const res = await api.resourcePackageToModel(r.instance_id, activate)
      const verb = activate ? '已设为当前默认' : (res.reused ? '已更新到模型管理' : '已插入模型管理')
      alert(`${verb}：${res.name}（${res.purpose} / ${res.model_name}）`)
    } catch (e) {
      alert((e as Error).message)
    } finally { setBusy(null) }
  }

  // 重传只替换所选厂商的行，另一家不受影响——故必须先选定厂商
  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (!f || !vendor) return
    try {
      const { count } = await api.importResourcePackages(f, vendor)
      alert(`已刷新 ${count} 条资源包`); reload()
    } catch (err) { alert((err as Error).message) }
    finally { if (fileRef.current) fileRef.current.value = '' }
  }

  const del = async (r: ResourcePackage) => {
    if (!confirm(`删除该资源包记录？\n${r.config_name}\n（仅删本地展示，不影响${r.vendor_label}账户）`)) return
    try { await api.deleteResourcePackage(r.instance_id); reload() }
    catch (err) { alert((err as Error).message) }
  }

  return (
    <div className="adm-panel">
      <div className="adm-head">
        <h2><Icon name="blocks" /> 资源包剩余</h2>
        <div className="seg">
          {VENDORS.map(v => (
            <button key={v.key} className={`seg-btn${vendor === v.key ? ' active' : ''}`}
              onClick={() => setVendor(v.key)}>{v.label}</button>
          ))}
        </div>
        <div className="adm-actions">
          <div className="rp-search">
            <Icon name="search" />
            <input placeholder="搜索：配置名 / 模型名 / 产品" value={search}
              onChange={e => setSearch(e.target.value)} />
          </div>
          <span className="dim">{shown.length} / {rows.length} 条</span>
          <button className="small ghost" onClick={reload}><Icon name="refresh" /> 刷新</button>
          <button className="small ghost" disabled={!vendor} title={vendor ? '手动登记' : '先选厂商'}
            onClick={() => setAdding(true)}>＋手动新增</button>
          <button className="small" disabled={!vendor} title={vendor ? '整表刷新该厂商' : '先选厂商'}
            onClick={() => fileRef.current?.click()}>重传 CSV</button>
          <input ref={fileRef} type="file" accept=".csv" hidden onChange={onUpload} />
        </div>
        {/* 模态过滤换到第二行：标题行只留厂商 + 操作区，避免挤成一排 */}
        <div className="rp-modality seg">
          {MODALITIES.map(m => (
            <button key={m.key} className={`seg-btn${modality === m.key ? ' active' : ''}`}
              onClick={() => setModality(m.key)}>{m.label}</button>
          ))}
        </div>
      </div>

      <div className="adm-scroll rp-body">
        <ResourcePackageTable rows={shown} busy={busy} onToModel={toModel}
          onTest={setTesting} onDelete={del} />
      </div>

      {vendor && <ResourcePackageForm open={adding} vendor={vendor}
        onClose={() => setAdding(false)} onSaved={reload} />}
      <ResourcePackageTest pkg={testing} onClose={() => setTesting(null)} />
    </div>
  )
}
