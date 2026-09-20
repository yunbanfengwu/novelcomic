import { useState } from 'react'
import type {
  EpisodeFlashBatch, PreviewScriptBand, PreviewTimelineSegment,
} from '../../api'
import { Icon } from '../../components/Icon'
import {
  PreviewTimelineStudio, type TimelineAction,
} from './timeline-studio/PreviewTimelineStudio'

/**
 * Lightweight host for the independent timeline studio.
 *
 * The details panel only owns the entry point. All editing state and UI live in
 * timeline-studio so the same component can later be mounted on a dedicated
 * professional editing route without depending on OverviewInspector.
 */
export function PreviewTimelineEditor({
  batch, action, onAnalyze, onSave, onConvert, onSeek, getPlayhead,
}: {
  batch: EpisodeFlashBatch
  action: TimelineAction
  onAnalyze: () => Promise<void>
  onSave: (
    segments: PreviewTimelineSegment[],
    scriptBands: PreviewScriptBand[],
  ) => Promise<void>
  onConvert: () => Promise<void>
  onSeek?: (seconds: number) => void
  getPlayhead?: () => number | undefined
}) {
  const [studioOpen, setStudioOpen] = useState(false)
  const timeline = batch.timeline

  if (!timeline) {
    return (
      <div className="preview-timeline-entry">
        <div>
          <b>脚本 × 分镜双时间线</b>
          <span>先按预设时间建立可编辑片段，再进入剪辑台校准。</span>
        </div>
        <button type="button" className="small ghost"
          disabled={!!action || !(batch.extracted_frames?.length)}
          title={batch.extracted_frames?.length ? '建立双时间线' : '请先抽取关键帧'}
          onClick={() => void onAnalyze()}>
          {action === 'analyze'
            ? <><Icon name="spinner" spin /> 分析中…</>
            : <><Icon name="clip" /> 建立双时间线</>}
        </button>
      </div>
    )
  }

  const missingRefs = timeline.segments.filter(
    segment => !segment.selected_frame_attachment_id).length
  return (
    <>
      <div className="preview-timeline-entry preview-timeline-launcher">
        <div>
          <b>脚本 × 分镜时间线</b>
          <span>
            版本 {timeline.version} · {timeline.segments.length} 段
            · 历史 {batch.timeline_version_count ?? 1} 个
          </span>
        </div>
        <div className="btns">
          {timeline.status === 'converted'
            && <span className="tag accent">已转为分镜</span>}
          {!!missingRefs && <span className="tag danger">{missingRefs} 段待选帧</span>}
          <button type="button" className="small"
            onClick={() => setStudioOpen(true)}>
            <Icon name="clip" /> 打开时间线剪辑台
          </button>
        </div>
      </div>
      <PreviewTimelineStudio
        open={studioOpen}
        batch={batch}
        timeline={timeline}
        action={action}
        onClose={() => setStudioOpen(false)}
        onSave={onSave}
        onConvert={onConvert}
        onSeek={onSeek}
        getPlayhead={getPlayhead}
      />
    </>
  )
}
