import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '../../components/Icon'
import type { IconName } from '../../components/Icon'

/** 通用命名弹框：一个单行输入 → 回传名称。用于「新建卷」「新增要素分类」等轻量新建。
 * allowEmpty=true 时可留空提交（由调用方决定默认命名，如后端自动「第N卷」）。 */
export function NameModal({ title, label, placeholder, submitLabel, icon, allowEmpty, onClose, onSubmit }: {
  title: string
  label: string
  placeholder?: string
  submitLabel: string
  icon: IconName
  allowEmpty?: boolean
  onClose: () => void
  onSubmit: (name: string) => void
}) {
  const [name, setName] = useState('')
  const ok = allowEmpty || !!name.trim()
  const submit = () => { if (!ok) return; onClose(); onSubmit(name.trim()) }

  return createPortal(
    <div className="modal-backdrop" onClick={() => onClose()}>
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <b>{title}</b>
          <button className="modal-x" onClick={() => onClose()} title="关闭">✕</button>
        </div>
        <label className="modal-label" htmlFor="name-modal-input">{label}</label>
        <input id="name-modal-input" className="modal-input" value={name} autoFocus
          onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit() }}
          placeholder={placeholder} />
        <div className="modal-actions">
          <button className="small ghost" onClick={() => onClose()}>取消</button>
          <button className="small" onClick={submit} disabled={!ok}>
            <Icon name={icon} /> {submitLabel}
          </button>
        </div>
      </div>
    </div>, document.body)
}
