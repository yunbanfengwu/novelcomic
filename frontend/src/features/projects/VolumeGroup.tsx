import { useState } from 'react'
import type { Chapter, Volume } from '../../api'
import { Icon } from '../../components/Icon'
import { ChapterLink } from './ChapterLink'

/** 分卷目录里的一卷：可折叠卷头（标题 + 集数 + 设置/删除）+ 卷内章节列表。 */
export function VolumeGroup({ pid, volume, chapters, onSettings, onDelete, onDeleteChapter }: {
  pid: number
  volume: Volume
  chapters: Chapter[]
  onSettings: () => void
  onDelete: () => void
  onDeleteChapter?: (chapter: Chapter) => Promise<void> | void
}) {
  const [open, setOpen] = useState(true)
  const custom = Object.keys(volume.overrides).length > 0

  return (
    <div className="vol-group">
      <div className="vol-head">
        <button className="vol-toggle" onClick={() => setOpen(o => !o)}
          title={open ? '折叠' : '展开'}>{open ? '▾' : '▸'}</button>
        <span className="vol-name" title={volume.title}>{volume.title}</span>
        <span className="vol-count">{chapters.length}集</span>
        {custom && <span className="vol-badge" title="本卷有独立设置（画风/文风/画幅）">独立设置</span>}
        <span className="vol-actions">
          <button className="vol-btn" onClick={onSettings} title="卷设置（画风/文风/画幅）">
            <Icon name="gear" />
          </button>
          <button className="vol-btn" onClick={onDelete} title="删除本卷（章节并入相邻卷）">
            <Icon name="trash" />
          </button>
        </span>
      </div>
      {open && (
        <div className="vol-chapters">
          {chapters.length === 0
            ? <div className="vol-empty">本卷暂无章节</div>
            : chapters.map(c => <ChapterLink key={c.id} pid={pid} c={c} onDelete={onDeleteChapter} />)}
        </div>
      )}
    </div>
  )
}
