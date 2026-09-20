import { useEffect, useRef } from 'react'
import { isTapflowWindowClosedMessage, openTapflowWindow } from './tapflowWindow'

/** 画布收编（2026-09-18）：旧 InfiniteMediaCanvas 九处入口全部收敛到这里。
 * 每个入口 = 一条 tapflow 模板 + 预填入参 + 业务对象（subject）。
 * 统一走独立窗口（openTapflowWindow）：生成是分钟级长任务，窗口不阻塞业务页；
 * 窗口关闭（可能跑完也可能没跑）都回调 onReload，让列表拉到最新落库状态。 */

export type TapflowWindowOpener = () => string | null

/** 监听本页打开过的 tapflow 窗口关闭 → 触发刷新（多个窗口合并成一次回调）。 */
export function useTapflowWindowReload(onReload: () => void) {
  const requests = useRef(new Set<string>())
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const requestId = [...requests.current]
        .find(id => isTapflowWindowClosedMessage(event, id))
      if (!requestId) return
      requests.current.delete(requestId)
      onReload()
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [onReload])
  return {
    open(payload: Parameters<typeof openTapflowWindow>[0]) {
      const requestId = openTapflowWindow(payload)
      if (requestId) requests.current.add(requestId)
    },
  }
}

/* ── 分镜三画布（首帧/视频/尾帧）：subject=镜头专属画布（fork） ────────────── */

export function openShotKeyframeCanvas(pid: number, shot: {
  id: number; meta: { shot_no?: number | string }
}) {
  return openTapflowWindow({
    slug: 'shot-keyframe-canvas', variant: 'production',
    inputs: { project_id: pid, shot_id: shot.id, target_ref: `content_node:${shot.id}`,
      asset_type: 'pro.shot.keyframe' },
    subject: { kind: 'shot', id: shot.id,
      name: `镜头${shot.meta.shot_no ?? shot.id}`, canvasRole: 'shot.keyframe' },
  })
}

export function openShotVideoCanvas(pid: number, shot: {
  id: number; meta: { shot_no?: number | string; video_url?: string }
}) {
  return openTapflowWindow({
    slug: 'shot-video-canvas', variant: 'production',
    inputs: { project_id: pid, shot_id: shot.id, target_ref: `content_node:${shot.id}`,
      asset_type: 'pro.shot.video' },
    subject: { kind: 'shot', id: shot.id,
      name: `镜头${shot.meta.shot_no ?? shot.id}`, canvasRole: 'shot.video' },
    productUrl: shot.meta.video_url || undefined,
  })
}

export function openShotLastframeCanvas(pid: number, shot: {
  id: number; meta: { shot_no?: number | string; last_frame_url?: string }
}) {
  return openTapflowWindow({
    slug: 'shot-lastframe-canvas', variant: 'production',
    inputs: { project_id: pid, shot_id: shot.id },
    subject: { kind: 'shot', id: shot.id,
      name: `镜头${shot.meta.shot_no ?? shot.id}`, canvasRole: 'shot.lastframe' },
    productUrl: shot.meta.last_frame_url || undefined,
  })
}

/* ── 项目级画布 ──────────────────────────────────────────────────────────── */

/** 先导预告片（TrailerCard 入口）：产物挂项目预告片字段，旧片在挂载点回显。 */
export function openTrailerCanvas(pid: number, currentUrl?: string) {
  return openTapflowWindow({
    slug: 'project-trailer-canvas', variant: 'production',
    inputs: { project_id: pid },
    subject: { kind: 'project', id: pid, canvasRole: 'project.trailer' },
    productUrl: currentUrl || undefined,
  })
}

/** Project cover poster: anchors -> planner/prepare -> persisted poster. */
export function openProjectPosterCanvas(pid: number, currentUrl?: string) {
  return openTapflowWindow({
    slug: 'project-poster-canvas', variant: 'production',
    inputs: { project_id: pid },
    subject: { kind: 'project', id: pid, canvasRole: 'project.poster' },
    productUrl: currentUrl || undefined,
  })
}

/* ── 素材库自由生成（AddElementModal / AssetLibrarySection） ─────────────── */

export function openAssetImageCanvas(pid: number, refUrl?: string, prompt?: string) {
  return openTapflowWindow({
    slug: 'asset-image-canvas', variant: 'production',
    inputs: {
      project_id: pid,
      ...(refUrl ? { ref_url: refUrl } : {}),
      ...(prompt ? { prompt } : {}),
    },
  })
}

export function openAssetVideoCanvas(pid: number, refUrl?: string, prompt?: string) {
  return openTapflowWindow({
    slug: 'asset-video-canvas', variant: 'production',
    inputs: {
      project_id: pid,
      ...(refUrl ? { ref_url: refUrl } : {}),
      ...(prompt ? { prompt } : {}),
    },
  })
}

/* ── 章级画布 ────────────────────────────────────────────────────────────── */

/** 场景组两阶段画布（空场景基准图 → 角色站位图）。 */
export function openSceneGroupCanvas(pid: number, chapterId: number, seg: number) {
  return openTapflowWindow({
    slug: 'scene-group-canvas', variant: 'production',
    inputs: { project_id: pid, chapter_id: chapterId, seg },
  })
}

/** Single scene sheet canvas (the reusable scene asset entry). */
export function openSceneSheetCanvas(pid: number, sceneName: string, chapterId?: number) {
  return openTapflowWindow({
    slug: 'scene-sheet-canvas', variant: 'production',
    inputs: { project_id: pid, scene_name: sceneName,
      ...(chapterId != null ? { chapter_id: chapterId } : {}) },
    subject: { kind: 'project', id: pid, canvasRole: `scene.sheet:${sceneName}` },
  })
}

/** 章级宫格故事板。board 给定只重出那一张，缺省整章全部。 */
export function openStoryboardGridCanvas(pid: number, chapterId: number, board?: number) {
  return openTapflowWindow({
    slug: 'storyboard-grid-canvas', variant: 'production',
    inputs: { project_id: pid, chapter_id: chapterId, ...(board != null ? { board } : {}) },
  })
}

/** Optional 3x3 storyboard reference canvas. */
export function openNineGridCanvas(pid: number, gridPrompt: string,
                                  gridReferenceImages?: unknown[]) {
  return openTapflowWindow({
    slug: 'nine-grid-keyframe-reference', variant: 'production',
    inputs: { project_id: pid, grid_prompt: gridPrompt,
      ...(gridReferenceImages?.length ? {
        grid_reference_images: JSON.stringify(gridReferenceImages),
      } : {}) },
  })
}

/** 批量首帧：整集分镜按场景切组，画布 loop 逐批 gen_keyframes_group。 */
export function openBatchKeyframeCanvas(pid: number, chapterId: number, seg?: number) {
  return openTapflowWindow({
    slug: 'batch-keyframe-canvas', variant: 'production',
    inputs: { project_id: pid, chapter_id: chapterId, ...(seg != null ? { seg } : {}) },
  })
}
