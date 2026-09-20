import { Icon } from '../../components/Icon'
import type { TapSaveState } from '../../lib/useTapflowSave'

/**
 * 生产态的自动保存回执（编排态那条是手动保存 + 发布，见 TapflowSaveBar）。
 *
 * 没有按钮：这里的保存是自动的。但**得有个交代**——用户拖出一个节点、挪了个位置，
 * 屏幕上不出声的话，他只能靠信仰相信这次改动进了库。存下了但跑不起来的问题
 * （如新节点还没选执行体）一并在这儿说，那是运行前唯一的提示。
 */
export function TapflowAutosaveBar({ save }: { save: TapSaveState }) {
  if (!save.saving && !save.msg) return null
  return (
    <div className="tap-savebar" onPointerDown={e => e.stopPropagation()}>
      {save.warnings.map(w => (
        <span key={w} className="tap-save-warn" title={w}><Icon name="alert" /> {w}</span>
      ))}
      <span className="tap-save-msg">
        {save.saving ? <><Icon name="spinner" spin /> 保存中…</> : save.msg}
      </span>
    </div>
  )
}
