import { useState } from 'react'
import { api } from '../../api'
import type { KbFolder } from '../../api'
import { Icon } from '../../components/Icon'
import { FOLDER_ICONS } from '../../lib/kbFolders'
import { KbEntryCards } from './KbEntryCards'
import { KbEntryPanel } from './KbEntryPanel'
import { VoiceAdmin } from './VoiceAdmin'

/**
 * 文件夹内页：上 header（返回/标题/条数/面板全局按钮同一行）+ 下内容。
 * 面板的全局操作按钮经 actionsEl（portal 挂载点）提升进 header 区。
 * 内容两种布局：直接卡片流（角色库/音色库=专用面板，画风库=缩略图卡片）；
 * 其余（提示词块/文风库/知识/自定义）=左侧分类菜单+右侧内容。
 */
export function KbFolderView({ folder, onBack, onChanged }: {
  folder: KbFolder
  onBack: () => void
  onChanged: () => void
}) {
  const [actionsEl, setActionsEl] = useState<HTMLElement | null>(null)

  const rename = async () => {
    const t = prompt('文件夹名称', folder.title)?.trim()
    if (!t || t === folder.title) return
    try { await api.renameKbFolder(folder.id, t); onChanged() } catch (e) { alert(String(e)) }
  }
  const remove = async () => {
    if (!confirm(`删除文件夹「${folder.title}」？其中条目将归回对应系统文件夹。`)) return
    try { await api.deleteKbFolder(folder.id); onBack(); onChanged() } catch (e) { alert(String(e)) }
  }

  const body = () => {
    if (folder.system && folder.kind === 'voice') return <VoiceAdmin actionsEl={actionsEl} />
    if (folder.system && folder.name === 'art_styles')
      return <KbEntryCards folder={folder} onCountChanged={onChanged} actionsEl={actionsEl} />
    return <KbEntryPanel folder={folder} onCountChanged={onChanged} actionsEl={actionsEl} />
  }

  return (
    <div className="kbv">
      <header className="kbv-head">
        <button className="small ghost" onClick={onBack}>‹ 返回知识库</button>
        <span className="kbv-title">
          <Icon name={FOLDER_ICONS[folder.name] || 'folder'} /> <b>{folder.title}</b>
        </span>
        <span className="dim">{folder.count} 条</span>
        <span className="kbv-actions" ref={setActionsEl} />
        {!folder.system && (
          <span className="kbv-ops">
            <button className="small ghost" onClick={rename}><Icon name="pen" /> 改名</button>
            <button className="small ghost" onClick={remove}>✕ 删除文件夹</button>
          </span>
        )}
      </header>
      <div className="kbv-body">{body()}</div>
    </div>
  )
}
