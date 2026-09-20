import { useRef } from 'react'
import type {
  Chapter, EpisodeFlashBatch, EpisodeFlashBeat, EpisodeFlashExtractedFrame, EpisodeFlashGroup,
  EpisodeFlashMode, EpisodeFlashStatus, PreviewScriptBand, PreviewTimelineSegment, SceneGroup, Shot,
} from '../../api'
import { Icon } from '../../components/Icon'
import { openLightbox } from '../../lib/lightbox'
import { ChapterBodyCard } from './ChapterBodyCard'
import { PreviewTimelineEditor } from './PreviewTimelineEditor'
import { SceneAnchorBlock } from './SceneAnchorBlock'

const clock = (seconds: number) => {
  const whole = Math.max(0, Math.round(seconds))
  return `${String(Math.floor(whole / 60)).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`
}

const seconds = (value: number) => `${Math.round(value * 100) / 100}秒`

const groupDuration = (group: EpisodeFlashGroup) => {
  if (group.duration_s != null) return group.duration_s
  if (group.output_start_s != null && group.output_end_s != null) {
    return Math.max(0, group.output_end_s - group.output_start_s)
  }
  const count = group.beat_count ?? group.shot_count ?? group.beats?.length ?? 0
  return Math.max(4, Math.ceil(count / 3))
}

function FlashSegments({ beats, duration = 5, outputOffset = 0 }: {
  beats: EpisodeFlashBeat[]; duration?: number; outputOffset?: number
}) {
  const step = beats.length ? duration / beats.length : 0
  return (
    <div className="flash-segments">
      {beats.map((beat, i) => {
        const outputStart = beat.output_start_s ?? outputOffset + i * step
        const outputEnd = beat.output_end_s ?? outputOffset + (i + 1) * step
        return (
          <div className="flash-segment" key={`${beat.group_no ?? 0}:${beat.no ?? i}:${i}`}>
            <div className="flash-segment-head">
              <span className="flash-time">{outputStart.toFixed(2)}–{outputEnd.toFixed(2)}s</span>
              <b>镜 {beat.no ?? i + 1}</b>
              {beat.group_no != null && <span className="tag">第 {beat.group_no} 组</span>}
              {beat.source_start_s != null && beat.source_end_s != null &&
                <span className="tag">原片 {clock(beat.source_start_s)}–{clock(beat.source_end_s)}</span>}
              {beat.stage && <span className="dim">{beat.stage}</span>}
            </div>
            <div className="flash-story"><span>剧情</span>{beat.picture}</div>
            <div className="flash-meta">
              {[beat.scene, beat.shot_size, ...(beat.characters ?? [])].filter(Boolean).join(' · ')}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function FlashGroups({ groups }: { groups: EpisodeFlashGroup[] }) {
  return (
    <div className="flash-groups">
      {groups.map((group, i) => {
        const no = group.no ?? i + 1
        const beats = group.beats ?? []
        const count = group.beat_count ?? group.shot_count ?? beats.length
        const duration = groupDuration(group)
        const videoUrl = group.video_url ?? group.group_video_url
        return (
          <section className="flash-group" key={`${no}:${group.attachment_id ?? i}`}>
            <div className="flash-group-head">
              <b>第 {no} 组{group.title ? ` · ${group.title}` : ''}</b>
              <span className="tag">{count} 次切换</span>
              <span className="tag">{seconds(duration)}</span>
            </div>
            {(group.source_start_s != null || group.output_start_s != null) && (
              <div className="flash-group-timeline">
                {group.source_start_s != null && group.source_end_s != null &&
                  <span>原片 {clock(group.source_start_s)}–{clock(group.source_end_s)}</span>}
                {group.output_start_s != null && group.output_end_s != null &&
                  <span>母带 {seconds(group.output_start_s)}–{seconds(group.output_end_s)}</span>}
              </div>
            )}
            {videoUrl && (
              <a className="flash-group-video" href={videoUrl} target="_blank" rel="noreferrer">
                打开第 {no} 组独立原视频
              </a>
            )}
            {(group.continuity_in || group.continuity_out) && (
              <div className="flash-continuity">
                {group.continuity_in && <div><span>承接</span>{group.continuity_in}</div>}
                {group.continuity_out && <div><span>交接</span>{group.continuity_out}</div>}
              </div>
            )}
            {!!beats.length && (
              <FlashSegments beats={beats} duration={duration}
                outputOffset={group.output_start_s ?? 0} />
            )}
            {group.prompt && (
              <details className="flash-full-prompt">
                <summary>第 {no} 组完整提示词</summary>
                <pre>{group.prompt}</pre>
              </details>
            )}
          </section>
        )
      })}
    </div>
  )
}

/** 总览视图右侧辅助区：母带分组/镜头提示词及其动态输出时间。 */
function FlashPrompt({ title, prompt, beats, groups, duration_s, pending = false }: {
  title: string; prompt?: string; beats?: EpisodeFlashBeat[]; groups?: EpisodeFlashGroup[]
  duration_s?: number; pending?: boolean
}) {
  if (!prompt && !beats?.length && !groups?.length) return null
  const groupCount = groups?.length ?? 0
  const count = beats?.length || groups?.reduce(
    (sum, group) => sum + (group.beat_count ?? group.shot_count ?? group.beats?.length ?? 0), 0) || 0
  const duration = duration_s ?? groups?.reduce((sum, group) => sum + groupDuration(group), 0) ?? 5
  return (
    <div className={'flash-prompt' + (pending ? ' pending' : '')}>
      <div className="flash-prompt-head">
        <b>{title}</b>
        {!!groupCount && <span className="tag">{groupCount} 组</span>}
        {!!count && <span className="tag">{count} 次切换</span>}
        <span className="tag">总计 {seconds(duration)}</span>
      </div>
      {groups?.length
        ? <FlashGroups groups={groups} />
        : beats?.length ? <FlashSegments beats={beats} duration={duration} /> : null}
      {!!prompt && (
        <details className="flash-full-prompt">
          <summary>完整母带提示词</summary>
          <pre>{prompt}</pre>
        </details>
      )}
    </div>
  )
}

function flashTitle(mode: EpisodeFlashMode, sourceMinutes: number, duration: number,
  shotCount: number, groupCount: number, resolution?: string | null, markerCount = 0) {
  const prefix = resolution ? `${resolution} · ` : ''
  if (mode === 'sampled_story') return `${prefix}${seconds(duration)} · 约${sourceMinutes}分钟剧情抽帧式超级加速母带`
  if (mode === 'timeline_supercut') return `${prefix}${seconds(duration)} · ${sourceMinutes}分钟分镜时间轴合并超级加速母带`
  if (mode === 'adaptive_groups') {
    return `${prefix}${seconds(duration)} · ${shotCount}次切换 · 自动分为${groupCount}组（每组≤15次）`
  }
  if (mode === 'adaptive_duration') {
    return `${prefix}${seconds(duration)} · ${shotCount}次切换自适应整数秒母带`
  }
  if (mode === 'slate_marked') {
    return `${prefix}${seconds(duration)} · 单帧黑场镜号板母带（${markerCount}帧标记）`
  }
  return `${prefix}${seconds(duration)} · 约${sourceMinutes}分钟剧情20镜超快闪回母带`
}

function FlashRefs({ title, refs }: {
  title: string; refs?: { name: string; kind: string; url: string }[]
}) {
  if (!refs?.length) return null
  return (
    <>
      <div className="dim" style={{ marginTop: 8 }}>{title}</div>
      <div className="aux-refs">
        {refs.map((r, i) => (
          <img key={`${r.kind}:${r.name}:${i}`} src={r.url} alt={r.name}
            title={`${r.name}@图片${i + 1}（点击放大）`} className="zoomable"
            onClick={() => openLightbox(r.url, r.name)} />
        ))}
      </div>
      <div className="btns" style={{ marginTop: 4 }}>
        {refs.map((r, i) => (
          <span className="tag" key={`${r.name}:${i}`}>{r.name}@图片{i + 1}</span>
        ))}
      </div>
    </>
  )
}

function FlashFrameGallery({ frames }: { frames?: EpisodeFlashExtractedFrame[] }) {
  if (!frames?.length) return null
  return (
    <div className="flash-frame-gallery">
      {frames.map((frame, index) => {
        const label = `镜 ${frame.beat_no} · ${frame.at_s.toFixed(2)}s`
        return (
          <button type="button" className="flash-frame" title={`${label}（点击放大）`}
            key={`${frame.attachment_id}:${frame.beat_no}:${frame.at_s}:${index}`}
            onClick={() => openLightbox(frame.url, label)}>
            <img src={frame.url} alt={label} loading="lazy" />
            <span>{label}</span>
          </button>
        )
      })}
    </div>
  )
}

function FlashExtractFrames({ batch, busy, onExtractFrames }: {
  batch: EpisodeFlashBatch; busy: boolean; onExtractFrames: (attachmentId: number) => void
}) {
  const frames = batch.extracted_frames ?? []
  const done = frames.length > 0
  return (
    <>
      <div className="flash-extract-actions">
        <button type="button" className="small ghost" disabled={busy || done}
          onClick={() => onExtractFrames(batch.attachment_id)}>
          {busy ? <><Icon name="spinner" spin /> 抽帧中…</>
            : done ? <><Icon name="clip" /> 已抽取 {frames.length} 帧</>
              : <><Icon name="clip" /> 抽取关键帧</>}
        </button>
        <span>独立图片结果，不创建或修改正式分镜</span>
      </div>
      <FlashFrameGallery frames={frames} />
    </>
  )
}

export function OverviewInspector({
  pid, chapter, shots, groups, onOpenSheet,
  episodeFlash, extractingAttachmentIds, timelineActions,
  onExtractFrames, onTimelineAnalyze, onTimelineSave, onTimelineConvert,
}: {
  pid: number; chapter: Chapter              // 未拆镜时辅助区读本章正文
  groups: SceneGroup[]                       // 本集场景组（场景锚定总览）
  onOpenSheet: (g: SceneGroup) => void       // 进该场景组的场景图画布
  shots: Shot[]; episodeFlash?: EpisodeFlashStatus | null
  extractingAttachmentIds: Set<number>; onExtractFrames: (attachmentId: number) => void
  timelineActions: Map<number, 'analyze' | 'save' | 'convert'>
  onTimelineAnalyze: (attachmentId: number) => Promise<void>
  onTimelineSave: (
    attachmentId: number,
    segments: PreviewTimelineSegment[],
    scriptBands: PreviewScriptBand[],
  ) => Promise<void>
  onTimelineConvert: (attachmentId: number) => Promise<void>
}) {
  const masterVideoRef = useRef<HTMLVideoElement>(null)
  const kfDone = shots.filter(s => s.meta.keyframe_url).length
  // 聚合本章关联要素：设定图按 url 去重，角色/场景按名去重
  const refs: { name: string; kind: string; url: string }[] = []
  const chars: string[] = []
  const scenes: string[] = []
  for (const s of shots) {
    for (const r of s.meta.reference_images ?? []) {
      if (!refs.some(x => x.url === r.url)) refs.push(r)
    }
    for (const c of s.meta.characters ?? []) if (!chars.includes(c)) chars.push(c)
    const sc = s.meta.scene_element
    if (sc && sc !== '无' && !scenes.includes(sc)) scenes.push(sc)
  }
  const latest = episodeFlash?.latest
  const draft = episodeFlash?.draft
  const draftIsNew = !!draft && (!latest || draft.id !== latest.draft_id)
  const activeMode = (draftIsNew ? draft?.mode : latest?.mode) ?? 'flash20'
  const sourceMinutes = (draftIsNew ? draft?.source_minutes : latest?.source_minutes) ?? 8
  const resolution = draftIsNew ? draft?.resolution : latest?.resolution
  const active = draftIsNew ? draft : latest
  const activeGroups = active?.groups ?? []
  const groupedDuration = activeGroups.reduce((sum, group) => sum + groupDuration(group), 0)
  const duration = active?.duration_s ?? (groupedDuration || 5)
  const groupedShots = activeGroups.reduce(
    (sum, group) => sum + (group.beat_count ?? group.shot_count ?? group.beats?.length ?? 0), 0)
  const flatShotCount = active?.beats?.length ?? 0
  const shotCount = active?.shot_count ??
    (flatShotCount || groupedShots || (activeMode === 'flash20' ? 20 : 0))
  const plannedMarkerCount = Math.max(0, shotCount - 1)
  const markerCount = !draftIsNew && latest?.markers ? latest.markers.length : plannedMarkerCount
  const splitRunCount = latest?.split_runs?.length ?? 0
  const hasPresetSplit = !!latest && latest.mode === 'slate_marked' &&
    (latest.frames > 0 || splitRunCount > 0)
  const historyBatches = (episodeFlash?.batches ?? []).filter(
    batch => batch.attachment_id !== latest?.attachment_id)
  return (
    <aside className="vt-aside">
      <div className="vt-aside-head">
        <b>分镜故事板总览</b>
        <span className="tag">{shots.length}镜</span>
        <span className="tag">{kfDone ? `首帧 ${kfDone}/${shots.length}` : '首帧未生成'}</span>
      </div>
      {(latest || draft) && (
        <div className="aux-block">
          <div className="aux-title"><Icon name="video" />
            {flashTitle(activeMode, sourceMinutes, duration, shotCount,
              activeGroups.length, resolution, markerCount)}
          </div>
          {latest && (
            <>
              {activeMode === 'slate_marked' && <div className="flash-master-label">最终标记母带</div>}
              <video ref={masterVideoRef} src={latest.video_url} controls preload="metadata"
                style={{ width: '100%', borderRadius: 8, background: '#0a0a0c' }} />
              {activeMode === 'slate_marked' && (
                <div className="flash-master-links">
                  {latest.raw_video_url && (
                    <a href={latest.raw_video_url} target="_blank" rel="noreferrer">
                      打开原始母带（未插镜号板）
                    </a>
                  )}
                  <a href={latest.video_url} target="_blank" rel="noreferrer">打开最终标记母带</a>
                </div>
              )}
              <div className="btns" style={{ marginTop: 6 }}>
                <span className="tag">批次 {latest.id}</span>
                {resolution && <span className="tag">{resolution}</span>}
                {latest.duration_s != null && <span className="tag">总时长 {seconds(latest.duration_s)}</span>}
                {latest.shot_count != null && <span className="tag">{latest.shot_count} 次切换</span>}
                {!!latest.groups?.length && <span className="tag">{latest.groups.length} 组</span>}
                {activeMode === 'slate_marked' && <span className="tag">标记帧 {markerCount}</span>}
                <span className="tag">抽帧 {latest.visible_frames}/{latest.frames}</span>
                {latest.status === 'awaiting_review' && <span className="tag">待审核·尚未抽帧</span>}
                {!latest.valid && <span className="tag danger">无效实验·已保留</span>}
              </div>
              <FlashExtractFrames batch={latest}
                busy={extractingAttachmentIds.has(latest.attachment_id)}
                onExtractFrames={onExtractFrames} />
              <PreviewTimelineEditor batch={latest}
                action={timelineActions.get(latest.attachment_id) ?? null}
                onAnalyze={() => onTimelineAnalyze(latest.attachment_id)}
                onSave={(segments, scriptBands) =>
                  onTimelineSave(latest.attachment_id, segments, scriptBands)}
                onConvert={() => onTimelineConvert(latest.attachment_id)}
                onSeek={at => {
                  if (!masterVideoRef.current) return
                  masterVideoRef.current.currentTime = at
                }}
                getPlayhead={() => masterVideoRef.current?.currentTime} />
              {hasPresetSplit && (
                <div className="btns" style={{ marginTop: 6 }}>
                  <span className="tag accent">拆分方法：预设时间表</span>
                  <span className="tag">检出分镜数 {latest.frames}</span>
                  {latest.total_extracted_frames != null &&
                    <span className="tag">总剧情帧 {latest.total_extracted_frames}</span>}
                </div>
              )}
            </>
          )}
          {!!historyBatches.length && (
            <details className="flash-history">
              <summary>已保留 {historyBatches.length} 个历史实验批次</summary>
              <div>
                {[...historyBatches].reverse().map(batch => (
                  <section className="flash-history-item" key={batch.id}>
                    <a href={batch.video_url} target="_blank" rel="noreferrer">
                      批次 {batch.id}{batch.resolution ? ` · ${batch.resolution}` : ''}
                      {batch.duration_s != null ? ` · ${seconds(batch.duration_s)}` : ''}
                      {batch.shot_count != null ? ` · ${batch.shot_count}次切换` : ''}
                      {' · '}{batch.valid ? batch.status : '无效实验·已保留'}
                    </a>
                    <FlashExtractFrames batch={batch}
                      busy={extractingAttachmentIds.has(batch.attachment_id)}
                      onExtractFrames={onExtractFrames} />
                    <PreviewTimelineEditor batch={batch}
                      action={timelineActions.get(batch.attachment_id) ?? null}
                      onAnalyze={() => onTimelineAnalyze(batch.attachment_id)}
                      onSave={(segments, scriptBands) =>
                        onTimelineSave(batch.attachment_id, segments, scriptBands)}
                      onConvert={() => onTimelineConvert(batch.attachment_id)} />
                  </section>
                ))}
              </div>
            </details>
          )}
          {draftIsNew && (
            <>
              <FlashPrompt title="待生成的新母带提示词" prompt={draft?.prompt} beats={draft?.beats}
                groups={draft?.groups} duration_s={draft?.duration_s} pending />
              <FlashRefs title="待生成提示词关联核心要素" refs={draft?.refs} />
            </>
          )}
          {latest && (!draft || latest.draft_id !== draft.id) &&
            <FlashPrompt title="当前视频使用的母带提示词" prompt={latest.prompt} beats={latest.beats}
              groups={latest.groups} duration_s={latest.duration_s} />}
          {latest && draft && latest.draft_id === draft.id &&
            <FlashPrompt title="本母带使用的分段提示词" prompt={latest.prompt || draft.prompt}
              beats={latest.beats?.length ? latest.beats : draft.beats}
              groups={latest.groups?.length ? latest.groups : draft.groups}
              duration_s={latest.duration_s ?? draft.duration_s} />}
          {latest && <FlashRefs title="当前母带关联核心要素" refs={latest.refs} />}
        </div>
      )}
      {/* 未拆镜：关联要素/场景锚定都由镜数据派生，此时全空——顶替成本章正文（拆镜依据） */}
      {!shots.length && <ChapterBodyCard pid={pid} chapter={chapter} />}
      {!!shots.length && <>
      <div className="aux-block">
        <div className="aux-title"><Icon name="clip" /> 本章关联要素</div>
        {refs.length > 0 && (
          <div className="aux-refs" style={{ marginTop: 0, marginBottom: 6 }}>
            {refs.map(r => (
              <img key={r.url} src={r.url} alt={r.name} title={`${r.name}（点击放大）`} className="zoomable"
                onClick={() => openLightbox(r.url, r.name)} />
            ))}
          </div>
        )}
        <div className="btns" style={{ marginTop: 0 }}>
          {scenes.map(s => <span key={s} className="tag accent"><Icon name="scene" /> {s}</span>)}
          {chars.map(c => <span key={c} className="tag"><Icon name="user" /> {c}</span>)}
        </div>
      </div>
      {/* 场景锚定总览：本集每组场景空间站位图铺开——与镜级前置条件区同一份数据、同一画布入口 */}
      <SceneAnchorBlock groups={groups} onOpenSheet={onOpenSheet} />
      </>}
    </aside>
  )
}
