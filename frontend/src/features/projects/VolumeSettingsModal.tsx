import { useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api'
import type { Project, Volume } from '../../api'
import { Icon } from '../../components/Icon'

/**
 * 卷设置弹框：改卷标题 + 覆盖项（画风/文风/画幅比例）。留空=继承项目（占位提示项目当前值）。
 * 要素类型为项目级、跨卷共享，不在此覆盖。
 */
export function VolumeSettingsModal({ pid, volume, project, onClose, onSaved }: {
  pid: number
  volume: Volume
  project: Project
  onClose: () => void
  onSaved: () => void
}) {
  const ov = volume.overrides
  const [title, setTitle] = useState(volume.title)
  const [art, setArt] = useState(ov.art_style ?? '')
  const [writing, setWriting] = useState(ov.writing_style ?? '')
  const [ratio, setRatio] = useState<string>(ov.aspect_ratio ?? '')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      // 覆盖项传空串=清除覆盖（回到继承项目）；aspect_ratio 传 '' 表示继承
      await api.updateVolume(pid, volume.id, {
        title: title.trim() || volume.title,
        art_style: art.trim(),
        writing_style: writing.trim(),
        aspect_ratio: (ratio || '') as '16:9' | '9:16',
      })
      onSaved(); onClose()
    } catch (e) { alert(String(e)); setBusy(false) }
  }

  return createPortal(
    <div className="modal-backdrop" onClick={() => !busy && onClose()}>
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <b>卷设置</b>
          <button className="modal-x" onClick={() => !busy && onClose()} title="关闭">✕</button>
        </div>

        <label className="modal-label" htmlFor="vol-title">卷标题</label>
        <input id="vol-title" className="modal-input" value={title} autoFocus
          onChange={e => setTitle(e.target.value)} placeholder="如 第二卷·风起" />

        <label className="modal-label" htmlFor="vol-ratio">画幅比例</label>
        <select id="vol-ratio" className="modal-input" value={ratio} onChange={e => setRatio(e.target.value)}>
          <option value="">继承项目（{project.config.aspect_ratio || '16:9'}）</option>
          <option value="16:9">16:9 横屏</option>
          <option value="9:16">9:16 竖屏</option>
        </select>

        <label className="modal-label" htmlFor="vol-art">画风（留空继承项目）</label>
        <textarea id="vol-art" className="modal-textarea" value={art} rows={2}
          onChange={e => setArt(e.target.value)}
          placeholder={`继承项目：${project.art_style || '（未设定）'}`} />

        <label className="modal-label" htmlFor="vol-writing">文风（留空继承项目）</label>
        <textarea id="vol-writing" className="modal-textarea" value={writing} rows={2}
          onChange={e => setWriting(e.target.value)}
          placeholder={`继承项目：${project.writing_style || '（未设定）'}`} />

        <div className="modal-actions">
          <button className="small ghost" disabled={busy} onClick={() => onClose()}>取消</button>
          <button className="small" disabled={busy} onClick={save}>
            {busy ? <><Icon name="spinner" spin /> 保存中…</> : <><Icon name="check" /> 保存</>}
          </button>
        </div>
      </div>
    </div>, document.body)
}
