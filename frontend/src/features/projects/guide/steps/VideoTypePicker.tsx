import { useEffect, useState } from 'react'
import { api } from '../../../../api'
import type { Tag } from '../../../../api'
import { Icon } from '../../../../components/Icon'
import { openLightbox } from '../../../../lib/lightbox'

/**
 * 视频类型选择卡片墙（画面设定步·画幅比例下方）：数据来自标签库 video_type 分组，
 * 只列视频类型标签；样式与画风卡片一致（缩略图 + 名称 + 选中角标，缩略图缺省显示图标）。
 * 单选——视频类型决定项目 project_type 路由；再次点击选中卡=取消选择。
 * value 里非视频类型的 code（旧数据可能带风格标签）原样保留，不因本选择器丢失。
 */
export function VideoTypePicker({ value, onChange }: {
  value: string[]
  onChange: (codes: string[]) => void
}) {
  const [tags, setTags] = useState<Tag[]>([])
  useEffect(() => {
    api.listTagGroups()
      .then(gs => setTags(gs.find(g => g.code === 'video_type')?.tags ?? []))
      .catch(() => setTags([]))
  }, [])

  if (!tags.length) return null
  const videoCodes = new Set(tags.map(t => t.code))
  const others = value.filter(c => !videoCodes.has(c))  // 非视频类型标签（旧数据兼容）
  const selected = value.find(c => videoCodes.has(c)) ?? null

  const pick = (code: string | null) => onChange(code ? [...others, code] : others)

  return (
    <>
      <label className="modal-label">作品类型（来自标签库·视频类型，可留空）</label>
      <div className="style-cards">
        {tags.map(t => (
          <button key={t.id} type="button"
            className={`style-card${selected === t.code ? ' active' : ''}`}
            onClick={() => pick(selected === t.code ? null : t.code)}>
            {t.thumbnail_url ? (
              <span className="style-card-thumb-box">
                <img className="style-card-thumb" src={t.thumbnail_url} alt={t.name} />
                {/* 右下角放大：查看大图，不触发选中（阻止冒泡到卡片选择） */}
                <span className="style-card-zoom" title="查看大图"
                  onClick={e => { e.stopPropagation(); openLightbox(t.thumbnail_url!, t.name) }}>
                  <Icon name="search" />
                </span>
              </span>
            ) : (
              <div className="style-card-thumb style-card-thumb-empty"><Icon name="tag" /></div>
            )}
            <div className="style-card-body">
              <b>{t.name}</b>
              <span className="dim">{t.code}</span>
            </div>
            {selected === t.code && <span className="style-card-check"><Icon name="check" /></span>}
          </button>
        ))}
      </div>
    </>
  )
}
