import { useCallback, useEffect, useMemo, useRef } from 'react'
import { isLive, noteEnqueued, useProjectTasks, useShotStream } from '../../lib/taskCenter'
import type { ShotStreamEvent } from '../../lib/taskCenter'

/** 分镜工作台的任务接线（全局任务中心 SSE 驱动，取代旧 4s 轮询）：
 * - pending：镜级在途 map（shot_id → task_id，含 waiting_deps 等待前置的任务）
 * - bdBusy：本章拆分镜在途
 * - 任一在途任务结束（done/failed/canceled）→ reload（产物与 gen 状态在 shot.meta）
 * - 流式拆镜逐镜事件（shot/shots_reset）→ reload：前端实时逐镜显示
 * - track：入队后乐观占位（SSE 回包前按钮即刻置忙）；刷新页面由 SSE 快照自动恢复 */
export function useShotTasks(pid: number, chapterId: number, reload: () => void) {
  const tasks = useProjectTasks(pid)
  const pending = useMemo(() => {
    const m: Record<number, number> = {}
    tasks.filter(t => isLive(t) && t.node_id != null && t.node_kind === 'shot')
      .forEach(t => { m[t.node_id!] = t.id })
    return m
  }, [tasks])
  const bdBusy = tasks.some(t =>
    isLive(t) && t.kind === 'breakdown_chapter' && t.node_id === chapterId)
  // 本章「批量首帧·组图」章级任务在途（含等待缺提示词镜的 gen_prompts 前置）
  const groupBusy = tasks.some(t =>
    isLive(t) && t.kind === 'gen_keyframes_group' && t.node_id === chapterId)
  // 本章「章级宫格故事板」在途（前置条件·分镜图块的生成按钮据此置忙）
  const boardBusy = tasks.some(t =>
    isLive(t) && t.kind === 'gen_overview_grid' && t.node_id === chapterId)
  // 本章场景图在途（任务只挂到章上，不分组号 → 章内任一场景图在途即置忙）。
  // 两阶段都要算：出站位图会自动先派空场景基准图，只看后者会让按钮过早解除置忙。
  const sheetBusy = tasks.some(t =>
    isLive(t) && ['gen_scene_empty', 'gen_scene_sheet'].includes(t.kind)
    && t.node_id === chapterId)
  // 本章「场景空间规划」在途（总览「批量场景」据此置忙，避免重复派发规划）
  const blockingBusy = tasks.some(t =>
    isLive(t) && t.kind === 'scene_blocking' && t.node_id === chapterId)

  const prevLive = useRef<Set<number>>(new Set())
  useEffect(() => {
    const cur = new Set(tasks.filter(isLive).map(t => t.id))
    const finished = [...prevLive.current].some(id => !cur.has(id))
    prevLive.current = cur
    if (finished) reload()  // 失败详情看顶栏任务队列面板，不弹 alert 打断
  }, [tasks, reload])

  // 流式拆镜时 shot 事件密集（一镜一发）：合批 250ms 再全量重拉，降低重拉次数与闪烁；
  // shots_reset（清场/终局替换）立即重拉
  const shotTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onShotEv = useCallback((ev: ShotStreamEvent) => {
    if (ev.chapter_id !== chapterId) return
    if (ev.type === 'shots_reset') {
      if (shotTimer.current) { clearTimeout(shotTimer.current); shotTimer.current = null }
      reload()
      return
    }
    if (shotTimer.current) return
    shotTimer.current = setTimeout(() => { shotTimer.current = null; reload() }, 250)
  }, [chapterId, reload])
  useEffect(() => () => { if (shotTimer.current) clearTimeout(shotTimer.current) }, [])
  useShotStream(pid, onShotEv)

  const track = useCallback((sid: number, taskId: number, kind: string) =>
    noteEnqueued(pid, { id: taskId, kind, node_id: sid, node_kind: 'shot' }), [pid])
  return { pending, bdBusy, groupBusy, boardBusy, sheetBusy, blockingBusy, track }
}
