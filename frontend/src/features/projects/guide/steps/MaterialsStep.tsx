import { useRef, useState } from 'react'
import { api } from '../../../../api'
import type { StagedMaterial } from '../../../../api'
import { Icon } from '../../../../components/Icon'

/**
 * 相关材料步（暂存）：文本粘贴进本地列表；文件即时直传 OSS 只拿 URL（不落库）。
 * 全部随最后一步「创建作品」一并落库（文本→资料表；文件→附件表+资料引用）。
 */
export function MaterialsStep({ materials, onAdd, onRemove }: {
  materials: StagedMaterial[]
  onAdd: (m: StagedMaterial) => void
  onRemove: (index: number) => void
}) {
  const [text, setText] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const addText = () => {
    const content = text.trim()
    if (!content) return
    onAdd({ title: content.split('\n')[0].slice(0, 24), source: 'input', content })
    setText('')
  }
  const upload = async (file?: File) => {
    if (!file) return
    setUploading(true)
    try {
      const r = await api.uploadFile(file)
      if (!r.stored) alert('OSS 未配置，文件未实际转存（仅记录文件名）。')
      onAdd({ title: r.name, source: 'upload', url: r.url, size: r.size, content_type: r.content_type,
        staging_path: r.staging_path, extractor: r.extractor, extracted_chars: r.extracted_chars,
        chunk_count: r.chunk_count, core_excerpt: r.core_excerpt })
    } catch (e) { alert(String(e)) }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }

  return (
    <div className="guide-form">
      <label className="modal-label" htmlFor="g-mat">文本资料 / 原始小说（粘贴）</label>
      <textarea id="g-mat" className="modal-textarea" value={text}
        onChange={e => setText(e.target.value)}
        placeholder="粘贴设定、人物小传或整段原著文本…" />
      <div className="guide-inline-actions guide-mat-actions">
        <button className="small" disabled={!text.trim()} onClick={addText}>
          <Icon name="pen" /> 添加文本
        </button>
        <button className="small ghost" disabled={uploading} onClick={() => fileRef.current?.click()}>
          {uploading ? <><Icon name="spinner" spin /> 上传中…</> : <><Icon name="clip" /> 上传文件</>}
        </button>
        <input ref={fileRef} type="file" hidden
          accept=".txt,.md,.doc,.docx,.pdf,.epub"
          onChange={e => upload(e.target.files?.[0])} />
      </div>

      {materials.length > 0 ? (
        <ul className="guide-mat-list">
          {materials.map((m, i) => (
            <li key={i} className="guide-mat-item">
              <Icon name={m.source === 'upload' ? 'clip' : 'text'} />
              <span className="guide-mat-title" title={m.title}>{m.title}</span>
              <span className="dim guide-mat-meta">
                {m.source === 'upload'
                  ? (m.extracted_chars ? `已解析 ${m.extracted_chars} 字 / ${m.chunk_count ?? 0} 段` : (m.url ? '已上传' : '已暂存'))
                  : `${m.content?.length ?? 0} 字`}
              </span>
              <button className="modal-x" title="移除" onClick={() => onRemove(i)}>✕</button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty-hint guide-mat-empty"><Icon name="clip" /> 还没有资料，可跳过</div>
      )}
    </div>
  )
}
