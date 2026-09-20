import type {
  PreviewCandidateFrame, PreviewStoryEvent, PreviewTimelineSegment,
} from '../../../api'

export interface ScriptBand {
  eventId: string
  start_s: number
  end_s: number
}

export const copySegments = (segments: PreviewTimelineSegment[]) =>
  segments.map(segment => ({
    ...segment,
    script_event_ids: [...segment.script_event_ids],
    beat_nos: [...segment.beat_nos],
    characters: [...(segment.characters ?? [])],
    candidate_frames: segment.candidate_frames.map(frame => ({ ...frame })),
  }))

export function buildScriptBands(events: PreviewStoryEvent[], duration: number): ScriptBand[] {
  if (!events.length) return []
  const storyStart = events[0].story_start_s
  const storyEnd = events[events.length - 1].story_end_s
  const storyDuration = Math.max(0.001, storyEnd - storyStart)
  return events.map((event, index) => ({
    eventId: event.id,
    start_s: index === 0
      ? 0 : ((event.story_start_s - storyStart) / storyDuration) * duration,
    end_s: index === events.length - 1
      ? duration : ((event.story_end_s - storyStart) / storyDuration) * duration,
  }))
}

export function restoreScriptBands(
  events: PreviewStoryEvent[],
  duration: number,
  saved?: { event_id: string; start_s: number; end_s: number }[],
): ScriptBand[] {
  if (saved?.length === events.length
    && saved.every((band, index) => band.event_id === events[index].id)) {
    return saved.map(band => ({
      eventId: band.event_id,
      start_s: band.start_s,
      end_s: band.end_s,
    }))
  }
  return buildScriptBands(events, duration)
}

const uniqueFrames = (frames: PreviewCandidateFrame[]) =>
  frames.filter((frame, index, all) =>
    all.findIndex(other => other.attachment_id === frame.attachment_id) === index)

/**
 * Project the editable script track onto preview segments.
 *
 * Script bands form a complete, ordered partition of preview time. A preview
 * segment links every event whose band overlaps it. Locked segments retain
 * their current mapping. Narrative text remains server-owned on save.
 */
export function remapSegments(
  segments: PreviewTimelineSegment[],
  bands: ScriptBand[],
  sourceSegments: PreviewTimelineSegment[],
): PreviewTimelineSegment[] {
  const eventFrames = new Map<string, PreviewCandidateFrame[]>()
  for (const segment of sourceSegments) {
    for (const eventId of segment.script_event_ids) {
      eventFrames.set(eventId, uniqueFrames([
        ...(eventFrames.get(eventId) ?? []),
        ...segment.candidate_frames,
      ]))
    }
  }
  return copySegments(segments).map(segment => {
    if (segment.locked) return segment
    let eventIds = bands
      .filter(band => {
        const overlap = Math.min(band.end_s, segment.preview_end_s)
          - Math.max(band.start_s, segment.preview_start_s)
        const shorter = Math.min(
          band.end_s - band.start_s,
          segment.preview_end_s - segment.preview_start_s,
        )
        // Ignore sub-frame overlap introduced by rounded timeline boundaries.
        return overlap > Math.max(0.002, shorter * 0.02)
      })
      .map(band => band.eventId)
    if (!eventIds.length && bands.length) {
      const center = (segment.preview_start_s + segment.preview_end_s) / 2
      const nearest = [...bands].sort((a, b) => {
        const aCenter = (a.start_s + a.end_s) / 2
        const bCenter = (b.start_s + b.end_s) / 2
        return Math.abs(aCenter - center) - Math.abs(bCenter - center)
      })[0]
      eventIds = [nearest.eventId]
    }
    const frames = uniqueFrames(eventIds.flatMap(id => eventFrames.get(id) ?? []))
    const selectedFrame = frames.some(
      frame => frame.attachment_id === segment.selected_frame_attachment_id)
      ? segment.selected_frame_attachment_id : frames[0]?.attachment_id ?? null
    return {
      ...segment,
      script_event_ids: eventIds,
      candidate_frames: frames,
      selected_frame_attachment_id: selectedFrame,
      converted_shot_id: null,
    }
  })
}

export function clock(seconds: number, decimals = 2) {
  const safe = Math.max(0, seconds)
  const minutes = Math.floor(safe / 60)
  const rest = safe - minutes * 60
  return `${String(minutes).padStart(2, '0')}:${rest.toFixed(decimals).padStart(5, '0')}`
}
