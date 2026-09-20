import { createPortal } from 'react-dom'
import { GuidedCreate } from './GuidedCreate'
import './guide.css'

/** 引导式新建的弹框外壳：首页「输入草稿/点击新建」进入。内容即独立的 GuidedCreate 组件。 */
export function GuidedCreateModal({ initialDraft, onDone, onClose }: {
  initialDraft?: string
  onDone: (projectId: number) => void
  onClose: () => void
}) {
  return createPortal(
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card guide-modal-card" onClick={e => e.stopPropagation()}>
        <GuidedCreate initialDraft={initialDraft} onDone={onDone} onExit={onClose} />
      </div>
    </div>,
    document.body,
  )
}
