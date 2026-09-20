import { useState } from 'react'
import { api } from '../../api'
import type { KbFolder } from '../../api'
import { Icon } from '../../components/Icon'
import { FOLDER_ICONS } from '../../lib/kbFolders'

/** 知识库首页：文件夹卡片墙（点击进入文件夹）+「新建文件夹」卡 */
export function KbFolderGrid({ folders, onOpen, onChanged }: {
  folders: KbFolder[]
  onOpen: (id: number) => void
  onChanged: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [title, setTitle] = useState('')

  const create = async () => {
    const t = title.trim()
    if (!t) return
    try {
      // name 需唯一 slug：自定义文件夹用时间基串，展示始终走 title
      const f = await api.createKbFolder({ name: `c_${Date.now().toString(36)}`, title: t })
      setTitle(''); setAdding(false); onChanged(); onOpen(f.id)
    } catch (e) { alert(String(e)) }
  }

  return (
    <div className="kbf-grid">
      {folders.map(f => (
        <button key={f.id} type="button" className="kbf-card" onClick={() => onOpen(f.id)}>
          <span className="kbf-icon"><Icon name={FOLDER_ICONS[f.name] || 'folder'} /></span>
          <b>{f.title}</b>
          <span className="kbf-count">{f.count} 条{f.system ? '' : ' · 自定义'}</span>
        </button>
      ))}
      {adding ? (
        <div className="kbf-card kbf-new">
          <input className="modal-input" autoFocus placeholder="文件夹名称，如「世界观设定」"
            value={title} onChange={e => setTitle(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') create(); if (e.key === 'Escape') setAdding(false) }} />
          <div className="btns">
            <button className="small" onClick={create}>创建</button>
            <button className="small ghost" onClick={() => setAdding(false)}>取消</button>
          </div>
        </div>
      ) : (
        <button type="button" className="kbf-card kbf-new" onClick={() => setAdding(true)}>
          <span className="kbf-icon"><Icon name="folderplus" /></span>
          <b>新建文件夹</b>
          <span className="kbf-count">存放自定义知识</span>
        </button>
      )}
    </div>
  )
}
