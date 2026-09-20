import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type { Chapter, Project, Volume } from '../../api'
import { Icon } from '../../components/Icon'
import { groupChaptersByVolume } from '../../lib/volumeGroups'
import { AppendChaptersModal } from './AppendChaptersModal'
import { NameModal } from './NameModal'
import { ChapterLink } from './ChapterLink'
import { VolumeGroup } from './VolumeGroup'
import { VolumeSettingsModal } from './VolumeSettingsModal'

/**
 * 正文左栏目录：无卷时平铺全集；建卷后按卷分组（可折叠、卷设置/删除）。
 * 底部：新增章节（续写）+ 新建卷（首次建卷会把现有散章收编为「第一卷」，再追加新卷）。
 */
export function ChapterCatalog({ pid, chapters, volumes, project, onChaptersChange, onVolumesChange }: {
  pid: number
  chapters: Chapter[]
  volumes: Volume[]
  project: Project
  onChaptersChange: () => void
  onVolumesChange: () => void
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const [modal, setModal] = useState(false)
  const [volModal, setVolModal] = useState(false)
  const [settingVol, setSettingVol] = useState<Volume | null>(null)
  const [busy, setBusy] = useState(false)
  const [gen, setGen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const pendingScroll = useRef(false)

  // 新建卷后列表已刷新（卷数变化）→ 自动滚到底部，露出刚建的卷。
  // 直接在 effect 里滚（此时 DOM 已布局），不用 rAF——后台标签页 rAF 可能不触发
  useEffect(() => {
    if (!pendingScroll.current) return
    pendingScroll.current = false
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [volumes.length, chapters.length])

  // 弹框已关，续写在目录里跑：后端逐章推送、每章即刷新目录（章节实时逐条长出）；首章即跳转
  const append = async (requirement: string) => {
    setGen(true)
    let first = true
    try {
      await api.appendChaptersStream(pid, requirement, c => {
        onChaptersChange()
        if (first) { first = false; navigate(`/project/${pid}/body/${c.seq}`) }
      })
    } catch (e) { alert(String(e)) }
    finally { setGen(false) }
  }

  const addVolume = async (title: string) => {
    setBusy(true)
    try {
      await api.createVolume(pid, title || undefined)
      pendingScroll.current = true
      onVolumesChange(); onChaptersChange()
    }
    catch (e) { alert(String(e)) }
    setBusy(false)
  }

  const removeVolume = async (v: Volume) => {
    if (!confirm(`删除「${v.title}」？其 ${v.chapter_count} 集将并入相邻卷（章节不会丢失）。`)) return
    try { await api.deleteVolume(pid, v.id); onVolumesChange(); onChaptersChange() }
    catch (e) { alert(String(e)) }
  }

  const removeChapter = async (c: Chapter) => {
    if (!confirm(`删除「第${c.seq}集 ${c.title}」？本集正文、分镜及生成记录都会被删除。`)) return
    try { await api.deleteChapter(pid, c.id) }
    catch (e) { alert(String(e)); return }
    const wasActive = new RegExp(`/project/${pid}/(?:body|video)/${c.seq}(?:$|/)`).test(location.pathname)
    onChaptersChange()
    if (wasActive) {
      const next = chapters.filter(item => item.id !== c.id).sort((a, b) => a.seq - b.seq)[0]
      navigate(`/project/${pid}/body/${next?.seq ?? 1}`)
    }
  }

  const groups = groupChaptersByVolume(volumes, chapters)

  return (
    <nav className="chapter-catalog">
      <div className="cat-list" ref={listRef}>
        {groups.length === 0
          ? chapters.map(c => <ChapterLink key={c.id} pid={pid} c={c} onDelete={removeChapter} />)
          : groups.map(g => (
            <VolumeGroup key={g.volume.id} pid={pid} volume={g.volume} chapters={g.chapters}
              onSettings={() => setSettingVol(g.volume)} onDelete={() => removeVolume(g.volume)}
              onDeleteChapter={removeChapter} />
          ))}
      </div>
      <div className="seg cat-foot">
        <button className="seg-btn cat-folder" disabled={busy} onClick={() => setVolModal(true)}
          title={volumes.length === 0 ? '新建卷：现有章节归为第一卷，并新建下一卷' : '在末尾新建一卷'}
          aria-label="新建卷">
          <Icon name="folderplus" />
        </button>
        <button className="seg-btn active cat-main" disabled={gen} onClick={() => setModal(true)} title="按续写要求新增后续章节">
          {gen ? <><Icon name="spinner" spin /> 续写中…</> : <><Icon name="pen" /> 新增章节</>}
        </button>
      </div>
      {modal && <AppendChaptersModal onClose={() => setModal(false)} onSubmit={append} />}
      {volModal && <NameModal title="新建卷" label="卷名称" submitLabel="新建卷" icon="folderplus" allowEmpty
        placeholder={volumes.length === 0 ? '留空自动命名；现有章节将归为第一卷' : '例如：第二卷 风起云涌（留空自动命名）'}
        onClose={() => setVolModal(false)} onSubmit={addVolume} />}
      {settingVol && (
        <VolumeSettingsModal pid={pid} volume={settingVol} project={project}
          onClose={() => setSettingVol(null)} onSaved={onVolumesChange} />
      )}
    </nav>
  )
}
