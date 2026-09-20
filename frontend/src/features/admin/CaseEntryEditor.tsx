import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api'
import type { CaseEntry, CaseGroup, CaseRef } from '../../api'
import { Icon } from '../../components/Icon'

const REF_KINDS = [
  { key: 'image', label: '图片', accept: 'image/*' },
  { key: 'video', label: '视频', accept: 'video/*' },
  { key: 'audio', label: '音频', accept: 'audio/*' },
] as const

const KIND_LABEL: Record<CaseRef['kind'], string> = { image: '图片', video: '视频', audio: '音频' }

/** 参考素材标签自动编号：按类型独立计数（图片1、图片2、视频1、音频1…），无需手填 */
function autoLabel(refs: CaseRef[]): CaseRef[] {
  const n: Record<string, number> = {}
  return refs.map(r => {
    n[r.kind] = (n[r.kind] || 0) + 1
    return { ...r, label: `${KIND_LABEL[r.kind]}${n[r.kind]}` }
  })
}

/** 隐藏 input[file] 的上传按钮：选中即传 OSS，回调 url */
function UploadBtn({ label, accept, onDone }: {
  label: string; accept: string; onDone: (url: string) => void
}) {
  const ref = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const pick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (!f) return
    setBusy(true)
    try { onDone((await api.uploadCaseAsset(f)).url) }
    catch (err) { alert((err as Error).message) }
    finally { setBusy(false); if (ref.current) ref.current.value = '' }
  }
  return (
    <>
      <button className="small ghost" disabled={busy} onClick={() => ref.current?.click()}>
        {busy ? <Icon name="spinner" spin /> : <Icon name="clip" />} {label}
      </button>
      <input ref={ref} type="file" accept={accept} hidden onChange={pick} />
    </>
  )
}

/** 素材缩略预览（编辑态）：与展示卡片同款 16:9 缩略；无 url 显示占位 */
function RefMedia({ r }: { r: CaseRef }) {
  if (!r.url) return <div className="cl-ref-empty dim">点击上传</div>
  if (r.kind === 'image') return <img src={r.url} alt={r.label} loading="lazy" />
  if (r.kind === 'video') return <video src={r.url} poster={r.cover || undefined} controls preload="none" />
  return <audio src={r.url} controls preload="none" />
}

/** 参考素材小格：控件融合在卡片上——左上=编号胶囊（点击弹类型下拉），右上=重传/封面/移除，空位整格点击上传 */
function RefTile({ r, patch, remove }: {
  r: CaseRef; patch: (p: Partial<CaseRef>) => void; remove: () => void
}) {
  const fileR = useRef<HTMLInputElement>(null)
  const coverR = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const up = async (f: File, key: 'url' | 'cover') => {
    setBusy(true)
    try { patch({ [key]: (await api.uploadCaseAsset(f)).url }) }
    catch (err) { alert((err as Error).message) }
    finally { setBusy(false) }
  }
  const accept = REF_KINDS.find(k => k.key === r.kind)?.accept || '*/*'
  return (
    <div className="cl-ref cl-ref-edit">
      <div className="cl-ref-box" onClick={() => { if (!r.url) fileR.current?.click() }}>
        <RefMedia r={r} />
        <span className="cl-ref-kind" onClick={ev => ev.stopPropagation()}>
          {busy ? <Icon name="spinner" spin /> : r.label}
          <select value={r.kind} title="点击切换素材类型"
            onChange={ev => patch({ kind: ev.target.value as CaseRef['kind'], url: '', cover: '' })}>
            {REF_KINDS.map(k => <option key={k.key} value={k.key}>{k.label}</option>)}
          </select>
        </span>
        <span className="cl-ref-ops" onClick={ev => ev.stopPropagation()}>
          {r.url && <button title="重新上传" onClick={() => fileR.current?.click()}><Icon name="clip" /></button>}
          {r.url && r.kind === 'video' &&
            <button title="上传封面" onClick={() => coverR.current?.click()}><Icon name="image" /></button>}
          <button title="移除" onClick={remove}>✕</button>
        </span>
      </div>
      <input ref={fileR} type="file" hidden accept={accept}
        onChange={ev => { const f = ev.target.files?.[0]; if (f) up(f, 'url'); ev.target.value = '' }} />
      <input ref={coverR} type="file" hidden accept="image/*"
        onChange={ev => { const f = ev.target.files?.[0]; if (f) up(f, 'cover'); ev.target.value = '' }} />
    </div>
  )
}

/** 案例编辑弹窗：与预览卡片同构的左右布局——左生成结果、右 Prompt + 参考素材缩略格 */
export function CaseEntryEditor({ entry, groups, onSave, onCancel }: {
  entry: Partial<CaseEntry>
  groups: CaseGroup[]
  onSave: (e: Partial<CaseEntry>) => Promise<void>
  onCancel: () => void
}) {
  const [e, setE] = useState<Partial<CaseEntry>>({ result_kind: 'video', refs: [], ...entry })
  const [saving, setSaving] = useState(false)
  const patch = (p: Partial<CaseEntry>) => setE(v => ({ ...v, ...p }))
  const refs = autoLabel(e.refs ?? [])
  const patchRef = (i: number, p: Partial<CaseRef>) =>
    patch({ refs: refs.map((r, j) => (j === i ? { ...r, ...p } : r)) })

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [onCancel])

  const save = async () => {
    setSaving(true)
    try { await onSave({ ...e, refs }) }
    catch (err) { alert((err as Error).message) }
    finally { setSaving(false) }
  }

  return createPortal(
    <div className="cl-backdrop" onClick={onCancel}>
      <div className="card cl-modal cl-modal-wide" onClick={ev => ev.stopPropagation()}>
        <button className="cl-modal-x" title="关闭 (Esc)" onClick={onCancel}>✕</button>
        <div className="cl-card-head">
          <h2>{e.id ? `编辑案例 #${e.id}` : '新建案例'}</h2>
        </div>
        <div className="inline">
          <select value={e.group_id ?? ''} onChange={ev => patch({ group_id: ev.target.value ? Number(ev.target.value) : null })}>
            <option value="">（未分组）</option>
            {groups.map(g => <option key={g.id} value={g.id}>{g.title}</option>)}
          </select>
          <input placeholder="标题 / 方向（如：动效复现）" value={e.title || ''}
            onChange={ev => patch({ title: ev.target.value })} />
          <input type="number" className="cl-seq" placeholder="排序" title="展示顺序，小者在前"
            value={e.seq ?? 0} onChange={ev => patch({ seq: Number(ev.target.value) || 0 })} />
        </div>

        <div className="cl-card-body">
          <div className="cl-result">
            {e.result_url ? (
              e.result_kind === 'video'
                ? <video src={e.result_url} poster={e.result_cover || undefined} controls preload="metadata" />
                : <img src={e.result_url} alt="生成结果" />
            ) : <div className="dim cl-result-empty">暂无生成结果</div>}
            <div className="inline cl-result-row">
              <select value={e.result_kind} onChange={ev => patch({ result_kind: ev.target.value as 'video' | 'image' })}>
                <option value="video">视频</option>
                <option value="image">图片</option>
              </select>
              <UploadBtn label={e.result_kind === 'video' ? '上传视频' : '上传图片'}
                accept={e.result_kind === 'video' ? 'video/*' : 'image/*'}
                onDone={url => patch({ result_url: url })} />
              {e.result_kind === 'video' &&
                <UploadBtn label="封面" accept="image/*" onDone={url => patch({ result_cover: url })} />}
            </div>
          </div>
          <div className="cl-info">
            <div className="cl-label">Prompt</div>
            <textarea rows={7} placeholder="Prompt 提示词原文" value={e.prompt || ''}
              onChange={ev => patch({ prompt: ev.target.value })} />
            <input placeholder="补充说明（可空）" value={e.note || ''}
              onChange={ev => patch({ note: ev.target.value })} />
            <div className="cl-label">参考素材（标签自动编号）</div>
            <div className="cl-refs">
              {refs.map((r, i) => (
                <RefTile key={i} r={r} patch={p => patchRef(i, p)}
                  remove={() => patch({ refs: refs.filter((_, j) => j !== i) })} />
              ))}
              <div className="cl-ref cl-ref-add-grid" title="添加参考素材">
                {REF_KINDS.map(k => (
                  <button key={k.key} title={`添加${k.label}素材`}
                    onClick={() => patch({ refs: [...refs, { kind: k.key, label: '', url: '' }] })}>
                    <Icon name={k.key === 'image' ? 'image' : k.key === 'video' ? 'video' : 'speaker'} /> {k.label}
                  </button>
                ))}
                <button title="添加素材"
                  onClick={() => patch({ refs: [...refs, { kind: 'image', label: '', url: '' }] })}>＋</button>
              </div>
            </div>
          </div>
        </div>

        <div className="btns">
          <button disabled={saving} onClick={save}>{saving ? <Icon name="spinner" spin /> : <Icon name="save" />} 保存</button>
          <button className="ghost" onClick={onCancel}>取消</button>
        </div>
      </div>
    </div>, document.body)
}
