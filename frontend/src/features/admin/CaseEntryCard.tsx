import type { CaseEntry, CaseRef } from '../../api'
import { Icon } from '../../components/Icon'

/** 单个参考素材缩略：图/视频/音频 + 标签 */
function RefThumb({ r }: { r: CaseRef }) {
  return (
    <div className="cl-ref">
      {!r.url && <div className="cl-ref-empty dim">未上传</div>}
      {r.url && r.kind === 'image' && <img src={r.url} alt={r.label} loading="lazy" />}
      {r.url && r.kind === 'video' && <video src={r.url} poster={r.cover || undefined} controls preload="none" />}
      {r.url && r.kind === 'audio' && <audio src={r.url} controls preload="none" />}
      <div className="cl-ref-label">{r.label || r.kind}</div>
    </div>
  )
}

/** 案例卡片（展示件）：标题 + 生成结果 + 提示词 + 参考素材条 */
export function CaseEntryCard({ entry, onEdit, onDelete }: {
  entry: CaseEntry
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <div className="card cl-card">
      <div className="cl-card-head">
        <span className="tag">{entry.title || '未命名案例'}</span>
        {entry.source === 'project' && <span className="dim">来自项目 #{entry.project_id}</span>}
        <div className="cl-card-actions">
          <button className="small ghost" onClick={onEdit}><Icon name="pen" /> 编辑</button>
          <button className="small ghost danger" onClick={onDelete}><Icon name="cross" /> 删除</button>
        </div>
      </div>
      <div className="cl-card-body">
        <div className="cl-result">
          {entry.result_url ? (
            entry.result_kind === 'video'
              ? <video src={entry.result_url} poster={entry.result_cover || undefined} controls preload="none" />
              : <img src={entry.result_url} alt={entry.title} loading="lazy" />
          ) : <div className="dim cl-result-empty">暂无生成结果</div>}
        </div>
        <div className="cl-info">
          {entry.prompt && <div className="prompt-box cl-prompt">{entry.prompt}</div>}
          {entry.note && <div className="dim cl-note">{entry.note}</div>}
          {entry.refs.length > 0 && (
            <div className="cl-refs">{entry.refs.map((r, i) => <RefThumb key={i} r={r} />)}</div>
          )}
        </div>
      </div>
    </div>
  )
}
