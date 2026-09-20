import { Fragment, useEffect, useRef } from 'react'
import type { SceneGroup, Shot } from '../../api'
import { Icon } from '../../components/Icon'

/** 时间轴首卡「总览故事板」的选中哨兵 id（真实镜 id 恒为正） */
export const OVERVIEW_ID = -1

/** 时间轴缩略图：视频＞首帧＞文本兜底 */
function tlThumb(s: Shot) {
  if (s.meta.video_url) {
    const poster = s.meta.keyframe_url || s.meta.video_cover_url
    return poster
      ? <div className="tl-thumb"><img src={poster} alt="" /><span className="tl-play">▶</span></div>
      : <div className="tl-thumb"><video src={s.meta.video_url} muted preload="metadata" /><span className="tl-play">▶</span></div>
  }
  if (s.meta.keyframe_url) return <div className="tl-thumb"><img src={s.meta.keyframe_url} alt="" /></div>
  return <div className="tl-text">{s.meta.video_prompt || s.summary || `镜头 ${s.meta.shot_no}`}</div>
}

/** 底部时间轴：首卡=首帧总览（点击后预览区宫格平铺每镜首帧），其后按场景组分节逐镜点选。
 * 组竖条（scene_seg 变化处，用户 2026-07-16 二版）：竖排场景名 + 场景图状态点——
 * 点击选中场景组：右侧辅助区切场景设定面板（空间布局/角色站位/场景空间站位图） */
export function ShotTimeline({ shots, selId, selGroup, pending, overview, groups, onSelect, onSelectGroup }: {
  shots: Shot[]
  selId: number | null
  selGroup?: number | null
  pending: Record<number, number>
  overview: { busy?: boolean }
  groups?: SceneGroup[]
  onSelect: (id: number) => void
  onSelectGroup?: (seg: number) => void
}) {
  // 首卡固定 2×2 四宫格缩略：取前 4 张已生成首帧作背景撑满，不足的灰格占位
  const kfDone = shots.filter(s => s.meta.keyframe_url).length
  const kfUrls = shots.filter(s => s.meta.keyframe_url).slice(0, 4).map(s => s.meta.keyframe_url!)
  const scrollRef = useRef<HTMLDivElement>(null)
  const activeRef = useRef<HTMLDivElement>(null)
  // 总览 / 场景组 / 镜 三者互斥高亮：选中场景组时镜卡与总览首卡一律不亮
  //（selId 仍留着记住"回到镜视图时是哪一镜"，只是不参与高亮）；反向由容器在选镜时清空 selGroup
  const activeId = selGroup == null ? selId : null

  // 选中镜变化（含播放自动推进）时，把选中卡滚入可视区；已可见则不动。
  // 首卡「总览」已移出滚动区常驻左端，不参与滚动计算。
  useEffect(() => {
    const box = scrollRef.current
    const card = activeRef.current
    if (!box || !card) return
    const left = card.offsetLeft - box.scrollLeft
    const right = left + card.offsetWidth
    if (left < 0) box.scrollTo({ left: card.offsetLeft, behavior: 'smooth' })
    else if (right > box.clientWidth) box.scrollTo({ left: card.offsetLeft + card.offsetWidth - box.clientWidth, behavior: 'smooth' })
  }, [activeId])

  return (
    <div className="vt-timeline-wrap">
      {/* 故事板首卡：滚动区外常驻左端；未生成时灰色占位卡 */}
      <div
        className={'tl-card tl-ov' + (kfDone ? '' : ' tl-ov-empty') + (activeId === OVERVIEW_ID ? ' active' : '')}
        title="首帧总览：宫格平铺每镜首帧，点击在预览区查看全部"
        onClick={() => onSelect(OVERVIEW_ID)}>
        <div className="tl-thumb tl-quad">
          {[0, 1, 2, 3].map(i => (
            <span key={i} className="tl-quad-cell"
              style={kfUrls[i] ? { backgroundImage: `url(${kfUrls[i]})` } : undefined} />
          ))}
          <span className="tl-badge">故事板</span>
          <span className="tl-quad-count">{kfDone ? `${kfDone}/${shots.length}` : '未生成'}</span>
        </div>
        <div className="tl-foot">
          <b>总览</b>
          {overview.busy && <span title="拆镜中"><Icon name="spinner" spin /></span>}
        </div>
      </div>
      {/* 时间轴滚动区：flex:1，内部横向滚动 */}
      <div className="vt-timeline" ref={scrollRef}>
      {shots.map((s, i) => {
        // 场景组头卡：scene_seg 变化处插一张（场景名+空间站位图状态；未规划的镜无组号则不插）
        const seg = s.meta.scene_seg
        const head = seg != null && (i === 0 || shots[i - 1].meta.scene_seg !== seg)
        const g = head ? groups?.find(x => x.seg === seg) : undefined
        const sceneName = (s.meta.scene || '').split(/[/／]/)[0] || `场景${seg}`
        return (
          <Fragment key={s.id}>
            {head && (
              <div className={'tl-strip' + (g?.sheet_url ? ' has-sheet' : '') + (selGroup === seg ? ' active' : '')}
                onClick={() => onSelectGroup?.(seg!)}>
                {g?.sheet_url && <img className="tl-strip-sheet" src={g.sheet_url} alt="" />}
                <div className="tl-strip-body">
                  <span className="tl-strip-name">{sceneName}</span>
                  {/* 状态点只在缺场景图时提示；有图时图本身即状态，不再点缀 */}
                  {!g?.sheet_url && <span className="tl-strip-dot" title="场景图未生成" />}
                </div>
              </div>
            )}
            <div ref={activeId === s.id ? activeRef : undefined}
              className={'tl-card' + (activeId === s.id ? ' active' : '')}
              onClick={() => onSelect(s.id)}>
              {tlThumb(s)}
              <div className="tl-foot">
                <b>镜{s.meta.shot_no}</b>
                <span className="dim">{s.meta.duration_s}s</span>
                {s.meta.video_url ? <span title="已有视频"><Icon name="video" /></span>
                  : s.meta.keyframe_url ? <span title="已有首帧"><Icon name="palette" /></span> : null}
                {s.id in pending && <span title="生成中"><Icon name="spinner" spin /></span>}
              </div>
            </div>
          </Fragment>
        )
      })}
      </div>
    </div>
  )
}
