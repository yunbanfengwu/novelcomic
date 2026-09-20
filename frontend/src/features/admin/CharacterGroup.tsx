import type { ArkCharacter } from '../../api'
import { Icon } from '../../components/Icon'
import { CharacterCard } from './CharacterCard'

/** 角色分组区块：一个 folder = 同一逻辑角色，下挂多套图/多形象条目。
 * 头部含分组名、备案计数、重命名与「新建角色」（在本组下加条目）；主体为该组的角色卡网格。
 * name 为空表示「未分组」——不显示重命名，「新建角色」建独立角色。 */
export function CharacterGroup({ name, chars, onAddEntry, onRename, onEdit, onDelete, onRegister, onUnregister }: {
  name: string
  chars: ArkCharacter[]
  onAddEntry: () => void
  onRename: () => void
  onEdit: (c: ArkCharacter) => void
  onDelete: (c: ArkCharacter) => void
  onRegister: (c: ArkCharacter) => void
  onUnregister: (c: ArkCharacter) => void
}) {
  const active = chars.filter(c => c.ark_status === 'active').length
  return (
    <section className="char-group">
      <div className="char-group-head">
        <span className="char-group-name">
          <Icon name={name ? 'users' : 'user'} /> {name || '未分组'}
        </span>
        <span className="dim char-group-count">{chars.length} 套 · {active} 已备案</span>
        <div className="btns char-group-acts">
          {name && (
            <button className="small ghost" onClick={onRename} title="重命名分组">
              <Icon name="pen" /> 重命名
            </button>
          )}
          <button className="small" onClick={onAddEntry} title="在本组新建角色">
            <Icon name="plus" /> 新建角色
          </button>
        </div>
      </div>
      <div className="char-grid">
        {chars.map(c => (
          <CharacterCard key={c.id} character={c}
            onEdit={() => onEdit(c)} onDelete={() => onDelete(c)}
            onRegister={() => onRegister(c)} onUnregister={() => onUnregister(c)} />
        ))}
      </div>
    </section>
  )
}
