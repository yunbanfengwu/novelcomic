import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../api'
import type { Chapter, Element, Project, Volume } from '../../../api'
import { ShotBoard } from '../../storyboard/ShotBoard'
import { ChapterBody } from './ChapterBody'
import { ChapterPager } from '../ChapterPager'
import { AppendChaptersModal } from '../AppendChaptersModal'
import { Icon } from '../../../components/Icon'

/**
 * 章节工作台分区：按集号定位章节，模式（正文/视频）由 URL 决定，顶栏「正文/视频」组切换。
 * 正文=左目录+右正文两栏；视频=分镜工作台撑满+底部跳集分页（时间轴下方）。动作按钮由子件 portal 到顶栏。
 */
export function VideoSection({ pid, chapters, volumes, project, seq, mode, elements, headSlot, onChaptersChange, onVolumesChange, onElementsChange }: {
  pid: number
  chapters: Chapter[]
  volumes: Volume[]
  project: Project
  seq: number
  mode: 'body' | 'video'
  elements: Element[]
  headSlot?: HTMLElement | null
  onChaptersChange: () => void
  onVolumesChange: () => void
  onElementsChange: () => void
}) {
  const [modal, setModal] = useState(false)
  const [gen, setGen] = useState(false)
  // 分页行左下角「从头逐镜播放」钮的挂载点：ShotBoard 把播放钮 portal 到这里（播放逻辑仍留在 ShotBoard）
  const [playSlot, setPlaySlot] = useState<HTMLElement | null>(null)
  const navigate = useNavigate()

  // 弹框已关，续写在分区里跑：解析到一章即刷新一章（目录实时逐条长出）；首章即跳转
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

  const chapter = chapters.find(c => c.seq === seq) ?? chapters[0] ?? null

  if (!chapter) {
    // 空态（正文/视频同款）：不显示左栏目录，整区居中提示 + 新增章节（空要求=直接生成整本目录）
    return (
      <div className="section-empty">
        <div>{gen ? 'AI 正在续写章节，稍候会逐条出现…' : '尚无章节'}</div>
        <button className={`empty-hint-btn${gen ? '' : ' guide-glow'}`} disabled={gen} onClick={() => setModal(true)}>
          {gen ? <><Icon name="spinner" spin /> 续写中…</> : <><Icon name="pen" /> 新增章节</>}
        </button>
        {modal && <AppendChaptersModal onClose={() => setModal(false)} onSubmit={append} />}
      </div>
    )
  }

  return (
    <div className="video-section">
      {mode === 'video' ? (
        // key=项目+章：切项目/切分集都重挂载分镜工作台 → 播放形式重置为「顺序播放」（页面级状态随挂载生命周期）
        <ShotBoard key={`${pid}-${chapter.id}`} pid={pid} chapter={chapter} elements={elements}
          onElementsReload={onElementsChange} headSlot={headSlot} playSlot={playSlot} />
      ) : (
        // key=项目+章：切分集重挂载正文分区 → body 本地态随之重置，杜绝「切章瞬间残留上一章正文」
        <ChapterBody key={`${pid}-${chapter.id}`} pid={pid} chapter={chapter} chapters={chapters}
          volumes={volumes} project={project} elements={elements} onChaptersChange={onChaptersChange}
          onVolumesChange={onVolumesChange} />
      )}
      {/* 跳集分页：仅视频模式常驻底部（时间轴下方）；正文模式用左栏目录导航 */}
      {mode === 'video' && (
        <div className="video-pager">
          {/* 左下角播放钮挂载点：ShotBoard 在有分镜时把「从头逐镜播放」钮 portal 进来 */}
          <div className="video-pager-lead" ref={setPlaySlot} />
          <ChapterPager id={pid} chapters={chapters} current={chapter.seq} />
        </div>
      )}
    </div>
  )
}
