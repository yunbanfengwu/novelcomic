import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '../../components/Icon'

/** 新增章节弹框：输入续写要求（章数由后端按要求自动判断），确认后回调续写。
 * 点「开始续写」即关闭弹框、把续写交给分区（章节在目录里逐条流式长出），弹框不再阻塞等待整批完成。 */
export function AppendChaptersModal({ onClose, onSubmit }: {
  onClose: () => void
  onSubmit: (requirement: string) => void
}) {
  const [req, setReq] = useState('')

  // 先关弹框露出目录，再触发续写——章节才能在眼前逐条流式出现，而非被黑幕挡到整批结束
  const submit = () => { const r = req.trim(); onClose(); onSubmit(r) }

  return createPortal(
    <div className="modal-backdrop" onClick={() => onClose()}>
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <b>新增章节</b>
          <button className="modal-x" onClick={() => onClose()} title="关闭">✕</button>
        </div>
        <label className="modal-label" htmlFor="append-req">续写要求</label>
        <textarea id="append-req" className="modal-textarea" value={req} autoFocus
          onChange={e => setReq(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit() }}
          placeholder="例如：续写10章；或 让XX复活并展开复仇——章数由系统按要求自动判断。留空则续写1章" />
        <div className="modal-actions">
          <button className="small ghost" onClick={() => onClose()}>取消</button>
          <button className="small" onClick={submit}>
            <Icon name="pen" /> 开始续写
          </button>
        </div>
      </div>
    </div>, document.body)
}
