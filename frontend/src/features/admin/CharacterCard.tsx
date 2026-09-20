import type { ArkCharacter } from '../../api'
import { Icon } from '../../components/Icon'

const STATUS: Record<ArkCharacter['ark_status'], { label: string; cls: string }> = {
  pending: { label: '待入库', cls: 'st-pending' },
  processing: { label: '备案中', cls: 'st-processing' },
  active: { label: '已备案', cls: 'st-active' },
  failed: { label: '入库失败', cls: 'st-failed' },
}

/** 角色卡：形象图 + 名称/描述 + 火山入库状态徽标 + 编辑/重试/删除 */
export function CharacterCard({ character, onEdit, onDelete, onRegister, onUnregister }: {
  character: ArkCharacter
  onEdit: () => void
  onDelete: () => void
  onRegister: () => void
  onUnregister: () => void
}) {
  const st = STATUS[character.ark_status] || STATUS.pending
  return (
    <div className="char-card card">
      <div className="char-card-img">
        {character.image_url
          ? <img src={character.image_url} alt={character.name} />
          : <div className="char-img-empty"><Icon name="user" /></div>}
        <span className={`char-badge ${st.cls}`}>
          {character.ark_status === 'processing' && <Icon name="spinner" spin />} {st.label}
        </span>
      </div>
      <div className="char-card-body">
        <div className="char-card-name">{character.name}</div>
        <div className="char-card-desc dim">{character.description || '—'}</div>
        {(character.source_work || character.owner_user) && (
          <div className="char-meta dim">
            {character.source_work && <span>来源：{character.source_work}</span>}
            {character.owner_user && <span>归属：{character.owner_user}</span>}
          </div>
        )}
        {character.ark_status === 'active' && character.ark_asset_id && (
          <div className="char-asset mono" title="火山素材 ID（生视频用 asset:// 引用）">
            asset://{character.ark_asset_id}
          </div>
        )}
        {character.ark_status === 'failed' && character.ark_error && (
          <div className="char-err">{character.ark_error}</div>
        )}
        <div className="btns char-card-actions">
          <button className="small" onClick={onEdit}>编辑</button>
          {character.ark_status === 'failed' && (
            <button className="small" onClick={onRegister}><Icon name="refresh" /> 重试入库</button>
          )}
          {(character.ark_status === 'active' || character.ark_status === 'processing') && character.ark_group_id && (
            <button className="small" onClick={onUnregister} title="删除火山侧素材组、状态退回待入库；本地角色与形象图保留，可再重注册">
              <Icon name="unlink" /> 解除备案
            </button>
          )}
          <button className="small danger" onClick={onDelete}>删除</button>
        </div>
      </div>
    </div>
  )
}
