import type { Tag, TagGroup } from '../../api'
import { Icon } from '../../components/Icon'

/** 标签右栏：选中分组下的标签卡片（缩略图 + 名称 + code）+ 新建标签卡。 */
export function TagGrid({ group, onNew, onEdit, onDelete }: {
  group: TagGroup | null
  onNew: () => void
  onEdit: (t: Tag) => void
  onDelete: (id: number) => void
}) {
  if (!group) return <div className="tag-grid-empty dim">左侧选择或新建一个分组</div>
  return (
    <div className="tag-grid-wrap">
      <div className="tag-grid-head">
        <b>{group.title}</b>
        <span className="dim">共 {group.tags.length} 个标签</span>
      </div>
      <div className="tag-grid">
        {group.tags.map(t => (
          <div key={t.id} className="tag-card">
            {t.thumbnail_url
              ? <img className="tag-card-thumb" src={t.thumbnail_url} alt={t.name} />
              : <div className="tag-card-thumb tag-card-thumb-empty"><Icon name="tag" /></div>}
            <div className="tag-card-body">
              <b>{t.name}</b>
              <code className="tag-card-code">{t.code}</code>
            </div>
            <div className="tag-card-acts">
              <button className="small ghost" title="编辑" onClick={() => onEdit(t)}><Icon name="pen" /></button>
              <button className="small ghost" title="删除"
                onClick={() => { if (confirm(`删除标签「${t.name}」？`)) onDelete(t.id) }}>
                <Icon name="trash" />
              </button>
            </div>
          </div>
        ))}
        <button className="tag-card tag-card-new" onClick={onNew}>
          <Icon name="plus" /> 新建标签
        </button>
      </div>
    </div>
  )
}
