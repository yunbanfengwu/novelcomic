import { Icon } from '../../components/Icon'
import type { TapSaveState } from '../../lib/useTapflowSave'

/**
 * 编排态右上角的保存条：保存 → 草稿版本；发布 → 该版本对运行生效。
 *
 * 增删节点、连线、拖动位置都存得下（画布专属层就是 node.position + config.ui）。
 * 这里显示的是**存下了但跑不起来**的问题，比如新生成节点还没选执行体——
 * 存和跑是两回事，不能因为跑不了就不让存。
 */
export function TapflowSaveBar({ save, onSave }: {
  save: TapSaveState
  onSave: () => void
}) {
  if (!save.savable) return null
  const draft = save.status === 'draft'
  return (
    <div className="tap-savebar" onPointerDown={e => e.stopPropagation()}>
      {save.msg && <span className="tap-save-msg">{save.msg}</span>}
      {save.warnings.map(w => (
        <span key={w} className="tap-save-warn" title={w}><Icon name="alert" /> {w}</span>
      ))}
      <span className="tap-save-ver">v{save.version}{draft ? ' 草稿' : ''}</span>
      <button type="button" className="tap-tool" title="保存" disabled={save.saving} onClick={onSave}>
        <Icon name={save.saving ? 'spinner' : 'save'} spin={save.saving} />
      </button>
      {draft && (
        <button type="button" className="tap-save-pub" disabled={save.saving}
          onClick={() => void save.publish()}>发布</button>
      )}
    </div>
  )
}
