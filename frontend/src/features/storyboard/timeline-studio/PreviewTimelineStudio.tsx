import {
  useEffect, useMemo, useRef, useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { createPortal } from 'react-dom'
import type {
  EpisodeFlashBatch, EpisodePreviewTimeline, PreviewScriptBand, PreviewStoryEvent,
  PreviewTimelineSegment,
} from '../../../api'
import { Icon } from '../../../components/Icon'
import { openLightbox } from '../../../lib/lightbox'
import {
  clock, copySegments, remapSegments, restoreScriptBands, type ScriptBand,
} from './timelineModel'
import './PreviewTimelineStudio.css'

export type TimelineAction = 'analyze' | 'save' | 'convert' | null

export interface PreviewTimelineStudioProps {
  open: boolean
  batch: EpisodeFlashBatch
  timeline: EpisodePreviewTimeline
  action: TimelineAction
  onClose: () => void
  onSave: (
    segments: PreviewTimelineSegment[],
    scriptBands: PreviewScriptBand[],
  ) => Promise<void>
  onConvert: () => Promise<void>
  onSeek?: (seconds: number) => void
  getPlayhead?: () => number | undefined
}

const uid = () => globalThis.crypto?.randomUUID?.()
  ?? `segment-${Date.now()}-${Math.random()}`

export function PreviewTimelineStudio({
  open, batch, timeline, action, onClose, onSave, onConvert, onSeek, getPlayhead,
}: PreviewTimelineStudioProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [segments, setSegments] = useState<PreviewTimelineSegment[]>([])
  const [scriptBands, setScriptBands] = useState<ScriptBand[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [zoom, setZoom] = useState(100)
  const [playhead, setPlayhead] = useState(0)

  useEffect(() => {
    const next = copySegments(timeline.segments)
    setSegments(next)
    setScriptBands(restoreScriptBands(
      timeline.events, timeline.duration_s, timeline.script_bands))
    setSelectedId(current => next.some(segment => segment.id === current)
      ? current : next[0]?.id ?? null)
    setDirty(false)
    setPlayhead(0)
  }, [timeline])

  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose, open])

  const selectedIndex = segments.findIndex(segment => segment.id === selectedId)
  const selected = selectedIndex >= 0 ? segments[selectedIndex] : null
  const eventById = useMemo(
    () => new Map(timeline.events.map(event => [event.id, event])),
    [timeline.events],
  )
  const activeEvents = selected
    ? (selected.script_event_ids
      .map(id => eventById.get(id))
      .filter(Boolean) as PreviewStoryEvent[])
    : []
  const missingRefs = segments.filter(segment => !segment.selected_frame_attachment_id).length
  const baseWidth = Math.max(1040, segments.length * 82)
  const timelineWidth = Math.round(baseWidth * zoom / 100)
  const playheadLeft = timeline.duration_s
    ? `${Math.min(100, Math.max(0, playhead / timeline.duration_s * 100))}%` : '0%'
  const rulerSteps = Math.max(2, Math.ceil(timeline.duration_s / 0.5))

  const seek = (seconds: number) => {
    const at = Math.min(timeline.duration_s, Math.max(0, seconds))
    if (videoRef.current) videoRef.current.currentTime = at
    setPlayhead(at)
    onSeek?.(at)
  }

  const chooseSegment = (segment: PreviewTimelineSegment) => {
    setSelectedId(segment.id)
    seek(segment.preview_start_s)
  }

  const updateSegments = (next: PreviewTimelineSegment[], remap = false) => {
    setSegments(remap ? remapSegments(next, scriptBands, timeline.segments) : next)
    setDirty(true)
  }

  const updateBoundary = (edge: 'start' | 'end', value: number) => {
    if (!selected || selected.locked || !Number.isFinite(value)) return
    const next = copySegments(segments)
    const current = next[selectedIndex]
    if (edge === 'start') {
      if (selectedIndex === 0) return
      const lower = next[selectedIndex - 1].preview_start_s + 0.02
      const upper = current.preview_end_s - 0.02
      const boundary = Math.min(upper, Math.max(lower, value))
      next[selectedIndex - 1].preview_end_s = boundary
      current.preview_start_s = boundary
    } else {
      if (selectedIndex === next.length - 1) return
      const lower = current.preview_start_s + 0.02
      const upper = next[selectedIndex + 1].preview_end_s - 0.02
      const boundary = Math.min(upper, Math.max(lower, value))
      current.preview_end_s = boundary
      next[selectedIndex + 1].preview_start_s = boundary
    }
    updateSegments(next, true)
  }

  const splitAt = () => {
    if (!selected || selected.locked) return
    const external = getPlayhead?.()
    const current = videoRef.current?.currentTime ?? external
    const at = current != null
      && current > selected.preview_start_s + 0.02
      && current < selected.preview_end_s - 0.02
      ? current : (selected.preview_start_s + selected.preview_end_s) / 2
    if (at - selected.preview_start_s < 0.02 || selected.preview_end_s - at < 0.02) return
    const left: PreviewTimelineSegment = {
      ...selected, id: uid(), preview_end_s: at, converted_shot_id: null,
    }
    const right: PreviewTimelineSegment = {
      ...selected, id: uid(), preview_start_s: at, converted_shot_id: null,
    }
    const next = [...segments.slice(0, selectedIndex), left, right,
      ...segments.slice(selectedIndex + 1)]
      .map((segment, index) => ({ ...segment, seq: index + 1 }))
    updateSegments(next, true)
    setSelectedId(right.id)
    seek(at)
  }

  const mergeRight = () => {
    if (!selected || selected.locked || selectedIndex >= segments.length - 1) return
    const right = segments[selectedIndex + 1]
    if (right.locked) return
    const merged: PreviewTimelineSegment = {
      ...selected,
      id: uid(),
      preview_end_s: right.preview_end_s,
      converted_shot_id: null,
    }
    const next = [...segments.slice(0, selectedIndex), merged,
      ...segments.slice(selectedIndex + 2)]
      .map((segment, index) => ({ ...segment, seq: index + 1 }))
    updateSegments(next, true)
    setSelectedId(merged.id)
  }

  const selectFrame = (attachmentId: number) => {
    if (!selected) return
    updateSegments(segments.map(segment => segment.id === selected.id
      ? { ...segment, selected_frame_attachment_id: attachmentId, converted_shot_id: null }
      : segment))
  }

  const toggleLock = () => {
    if (!selected) return
    updateSegments(segments.map(segment => segment.id === selected.id
      ? { ...segment, locked: !segment.locked } : segment))
  }

  const startScriptResize = (
    boundaryIndex: number,
    event: ReactPointerEvent<HTMLElement>,
  ) => {
    if (boundaryIndex < 0 || boundaryIndex >= scriptBands.length - 1) return
    event.preventDefault()
    event.stopPropagation()
    const startX = event.clientX
    const initial = scriptBands.map(band => ({ ...band }))
    const durationPerPixel = timeline.duration_s / timelineWidth
    const minBand = Math.max(0.015, 28 * durationPerPixel)
    const onMove = (move: PointerEvent) => {
      const left = initial[boundaryIndex]
      const right = initial[boundaryIndex + 1]
      const boundary = Math.min(
        right.end_s - minBand,
        Math.max(left.start_s + minBand,
          left.end_s + (move.clientX - startX) * durationPerPixel),
      )
      const next = initial.map(band => ({ ...band }))
      next[boundaryIndex].end_s = boundary
      next[boundaryIndex + 1].start_s = boundary
      setScriptBands(next)
      setSegments(current => remapSegments(current, next, timeline.segments))
      setDirty(true)
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp, { once: true })
  }

  const seekFromTrack = (event: ReactMouseEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('button')) return
    const rect = event.currentTarget.getBoundingClientRect()
    seek((event.clientX - rect.left) / rect.width * timeline.duration_s)
  }

  if (!open) return null

  return createPortal(
    <div className="pts-backdrop" role="presentation">
      <section className="pts-studio" role="dialog" aria-modal="true"
        aria-label="脚本与分镜时间线剪辑台">
        <header className="pts-toolbar">
          <div className="pts-title">
            <b>脚本 × 分镜时间线剪辑台</b>
            <span>批次 {batch.id} · 版本 {timeline.version}
              · 历史 {batch.timeline_version_count ?? 1} 个</span>
          </div>
          <div className="pts-toolbar-actions">
            <span className="pts-count">{segments.length} 段</span>
            <div className="pts-zoom-control">
              <button type="button" aria-label="缩小时间轴"
                onClick={() => setZoom(value => Math.max(50, value - 10))}>−</button>
              <label className="pts-zoom">
                <span>时间轴 {zoom}%</span>
                <input type="range" min="50" max="300" step="10" value={zoom}
                  onChange={event => setZoom(Number(event.target.value))} />
              </label>
              <button type="button" aria-label="放大时间轴"
                onClick={() => setZoom(value => Math.min(300, value + 10))}>＋</button>
            </div>
            <button type="button" className="small ghost" onClick={() => setZoom(100)}>
              还原
            </button>
            <button type="button" className="small ghost" disabled={!dirty || !!action}
              onClick={() => void onSave(segments, scriptBands.map(band => ({
                event_id: band.eventId,
                start_s: band.start_s,
                end_s: band.end_s,
              })))}>
              {action === 'save' ? <><Icon name="spinner" spin /> 保存中…</> : '保存新版本'}
            </button>
            <button type="button" className="small"
              disabled={dirty || !!action || !!missingRefs}
              title={dirty ? '请先保存当前修改'
                : missingRefs ? `还有 ${missingRefs} 段未选参考帧` : '转为分镜草稿'}
              onClick={() => void onConvert()}>
              {action === 'convert'
                ? <><Icon name="spinner" spin /> 转换中…</>
                : timeline.status === 'converted' ? '重新关联分镜' : '转为草稿分镜'}
            </button>
            <button type="button" className="pts-close" onClick={onClose}
              aria-label="关闭剪辑台">×</button>
          </div>
        </header>

        <div className="pts-upper">
          <div className="pts-monitor">
            <video ref={videoRef} src={batch.video_url} controls preload="metadata"
              onTimeUpdate={event => setPlayhead(event.currentTarget.currentTime)}
              onLoadedMetadata={event => setPlayhead(event.currentTarget.currentTime)} />
            <div className="pts-monitor-status">
              <span>母带主预览</span>
              <code>{clock(playhead)} / {clock(timeline.duration_s)}</code>
            </div>
          </div>

          <aside className="pts-inspector">
            {selected ? (
              <>
                <div className="pts-inspector-head">
                  <div>
                    <small>当前片段</small>
                    <b>镜段 {selectedIndex + 1}</b>
                  </div>
                  <button type="button" className={selected.locked ? 'active' : ''}
                    onClick={toggleLock}>{selected.locked ? '已锁定' : '锁定'}</button>
                </div>
                <div className="pts-time-fields">
                  <label>入点
                    <input type="number" min={0} max={timeline.duration_s} step="0.01"
                      disabled={selectedIndex === 0 || selected.locked}
                      value={selected.preview_start_s}
                      onChange={event => updateBoundary('start', Number(event.target.value))} />
                  </label>
                  <label>出点
                    <input type="number" min={0} max={timeline.duration_s} step="0.01"
                      disabled={selectedIndex === segments.length - 1 || selected.locked}
                      value={selected.preview_end_s}
                      onChange={event => updateBoundary('end', Number(event.target.value))} />
                  </label>
                </div>
                <div className="pts-inspector-buttons">
                  <button type="button" disabled={selected.locked} onClick={splitAt}>
                    在播放头拆分
                  </button>
                  <button type="button"
                    disabled={selected.locked || selectedIndex >= segments.length - 1
                      || !!segments[selectedIndex + 1]?.locked}
                    onClick={mergeRight}>与右段合并</button>
                </div>
                <div className="pts-story-card">
                  <small>脚本映射</small>
                  {activeEvents.map(event => (
                    <p key={event.id}><b>{event.id}</b>{event.picture}</p>
                  ))}
                </div>
                <div className="pts-candidates-title">
                  <span>动作构图参考帧</span>
                  <small>单击选择 · 双击查看</small>
                </div>
                <div className="pts-candidates">
                  {selected.candidate_frames.map(frame => {
                    const chosen = selected.selected_frame_attachment_id === frame.attachment_id
                    return (
                      <button type="button" className={chosen ? 'active' : ''}
                        key={frame.attachment_id}
                        onClick={() => selectFrame(frame.attachment_id)}
                        onDoubleClick={() =>
                          openLightbox(frame.url, `动作构图帧 ${frame.at_s.toFixed(2)}s`)}>
                        <img src={frame.url} alt={`母带 ${frame.at_s.toFixed(2)}s`} />
                        <span>{frame.at_s.toFixed(2)}s{chosen ? ' · 已选' : ''}</span>
                      </button>
                    )
                  })}
                  {!selected.candidate_frames.length
                    && <span className="dim">该片段暂无候选帧</span>}
                </div>
              </>
            ) : <span className="dim">请选择一个分镜片段</span>}
          </aside>
        </div>

        <div className="pts-timeline-shell">
          <div className="pts-track-guide">
            <span className="pts-track-icon">V</span>
            <div><b>预览分镜</b><small>点击片段定位视频</small></div>
          </div>
          <div className="pts-track-guide">
            <span className="pts-track-icon script">S</span>
            <div><b>故事脚本</b><small>拖动块边缘改变映射</small></div>
          </div>

          <div className="pts-scroll">
            <div className="pts-timeline" style={{ width: timelineWidth }}>
              <div className="pts-ruler" onClick={seekFromTrack}>
                {Array.from({ length: rulerSteps + 1 }, (_, index) => {
                  const at = timeline.duration_s * index / rulerSteps
                  return (
                    <span key={index} style={{ left: `${index / rulerSteps * 100}%` }}>
                      {at.toFixed(1)}s
                    </span>
                  )
                })}
              </div>
              <div className="pts-playhead" style={{ left: playheadLeft }}>
                <i />
              </div>

              <div className="pts-track pts-video-track" onClick={seekFromTrack}>
                {segments.map((segment, index) => {
                  const selectedFrame = segment.candidate_frames.find(
                    frame => frame.attachment_id === segment.selected_frame_attachment_id)
                  return (
                    <button type="button" key={segment.id}
                      className={segment.id === selectedId ? 'active' : ''}
                      style={{
                        width: `${(segment.preview_end_s - segment.preview_start_s)
                          / timeline.duration_s * 100}%`,
                      }}
                      onClick={() => chooseSegment(segment)}>
                      {selectedFrame && <img src={selectedFrame.url} alt="" />}
                      <span><b>镜段 {index + 1}</b>
                        <small>{segment.preview_start_s.toFixed(2)}
                          –{segment.preview_end_s.toFixed(2)}s</small></span>
                      {segment.locked && <em>锁</em>}
                    </button>
                  )
                })}
              </div>

              <div className="pts-track pts-script-track" onClick={seekFromTrack}>
                {scriptBands.map((band, index) => {
                  const storyEvent = eventById.get(band.eventId)
                  const active = selected?.script_event_ids.includes(band.eventId)
                  return (
                    <button type="button" key={band.eventId}
                      className={active ? 'active' : ''}
                      style={{ width: `${(band.end_s - band.start_s)
                        / timeline.duration_s * 100}%` }}
                      title={storyEvent?.picture}
                      onClick={() => {
                        const segment = segments.find(
                          item => item.script_event_ids.includes(band.eventId))
                        if (segment) chooseSegment(segment)
                      }}>
                      <b>{band.eventId}</b>
                      <span>{storyEvent?.picture}</span>
                      {index < scriptBands.length - 1 && (
                        <i role="separator" aria-label={`调整 ${band.eventId} 结束位置`}
                          onPointerDown={event => startScriptResize(index, event)} />
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </div>

        <footer className="pts-footer">
          <span>{dirty
            ? '有未保存修改；保存将新增版本，历史版本不会覆盖'
            : '当前版本已保存；拖动脚本块边缘可改变它与上方分镜段的对应关系'}</span>
          <span>{missingRefs ? `${missingRefs} 段未选择动作构图帧` : '全部片段已有动作构图帧'}</span>
        </footer>
      </section>
    </div>,
    document.body,
  )
}
