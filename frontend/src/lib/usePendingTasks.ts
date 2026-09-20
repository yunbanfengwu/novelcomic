import { useEffect, useMemo, useRef } from 'react'
import { isLive, noteEnqueued, useProjectTasks } from './taskCenter'

/** 要素级任务在途状态（element_id → task_id）：由全局任务中心（SSE）实时驱动，
 * 不再各自 setInterval 轮询。track 保留旧签名——入队后乐观占位（SSE 回包前按钮即刻置忙）；
 * 刷新页面由 SSE 快照自动恢复在途状态。任一要素任务结束（含失败）回调 onDone 刷新数据。 */
export function usePendingTasks(pid: number, onDone: () => void) {
  const tasks = useProjectTasks(pid)
  const pending = useMemo(() => {
    const m: Record<number, number> = {}
    tasks.filter(t => isLive(t) && t.element_id != null).forEach(t => { m[t.element_id!] = t.id })
    return m
  }, [tasks])
  // 完成检测：上一渲染在途的要素任务从在途集合消失 → onDone（done/failed/canceled 都要刷新）
  const prev = useRef<Set<number>>(new Set())
  useEffect(() => {
    const cur = new Set(tasks.filter(t => isLive(t) && t.element_id != null).map(t => t.id))
    const finished = [...prev.current].some(id => !cur.has(id))
    prev.current = cur
    if (finished) onDone()
  }, [tasks, onDone])
  const track = (key: number, task_id: number) =>
    noteEnqueued(pid, { id: task_id, kind: 'gen_element_sheet', element_id: key })
  return { pending, track }
}
