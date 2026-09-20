import { useEffect, useMemo, useRef } from 'react'
import { isLive, useProjectTasks } from './taskCenter'

/** 监听指定类型的项目级任务结束（done/failed/canceled 均回调，以 kind 为参）：
 * 由全局任务中心（SSE）驱动——后台补拟基本信息/大纲/要素类型完成后刷新项目数据用。
 * onDone 需 useCallback 稳定引用；kinds 内部按 join 串比较，字面量数组可直接传。 */
export function useTaskDone(pid: number, kinds: string[], onDone: (kind: string) => void) {
  const tasks = useProjectTasks(pid)
  const key = kinds.join(',')
  const prev = useRef(new Map<number, string>())
  useEffect(() => {
    const want = new Set(key.split(','))
    const cur = new Map(tasks.filter(t => isLive(t) && want.has(t.kind)).map(t => [t.id, t.kind]))
    const finished = [...prev.current].filter(([id]) => !cur.has(id))
    prev.current = cur
    finished.forEach(([, kind]) => onDone(kind))
  }, [tasks, key, onDone])
}

/** 指定类型中当前有在途任务的集合（自动后台生成的加载态展示用） */
export function useLiveKinds(pid: number, kinds: string[]): Set<string> {
  const tasks = useProjectTasks(pid)
  const key = kinds.join(',')
  return useMemo(() => {
    const want = new Set(key.split(','))
    return new Set(tasks.filter(t => isLive(t) && want.has(t.kind)).map(t => t.kind))
  }, [tasks, key])
}
