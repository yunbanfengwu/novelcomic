import { useState } from 'react'
import { api } from '../../api'
import type { TaskInfo } from '../../api'
import { Icon } from '../Icon'
import { isLive, useProjectTasks } from '../../lib/taskCenter'
import { fmtLogTime } from '../../lib/genLogLabels'
import { buildTaskForest, TASK_KIND_LABEL, TASK_STATUS_META, taskTargetLabel } from '../../lib/taskKinds'
import type { TaskNode } from '../../lib/taskKinds'
import { useActivePid } from '../../lib/uiContext'
import { TaskLogModal } from './TaskLogModal'
import './taskqueue.css'

/** 任务行的时间戳：结束态取 finished_at，在途取 started_at，未起取 created_at（取到即显示）。 */
function rowTime(t: TaskInfo): string {
  return fmtLogTime(t.finished_at ?? t.started_at ?? t.created_at)
}

/** 一行任务（含依赖子任务缩进递归）：类型 + 对象（镜N/章）+ 时间 + 状态 + 取消/重试/日志 */
function TaskRow({ pid, node, depth, onOpenLog }: {
  pid: number; node: TaskNode; depth: number; onOpenLog: (t: TaskInfo) => void
}) {
  const t = node.task
  const st = TASK_STATUS_META[t.status] ?? { label: t.status, tone: 'wait' as const }
  const cancelable = ['pending', 'waiting_deps', 'waiting_external'].includes(t.status)
  const time = rowTime(t)
  return (
    <>
      <div className={`tq-row tone-${st.tone}`} style={{ paddingLeft: 8 + depth * 16 }}>
        {depth > 0 && <span className="tq-branch">└</span>}
        <span className={`tq-dot tone-${st.tone}`} />
        <span className="tq-kind">{TASK_KIND_LABEL[t.kind] ?? t.kind}</span>
        <span className="tq-target">{taskTargetLabel(t)}</span>
        {time && <span className="tq-time" title="创建/开始/结束时间">{time}</span>}
        <span className="tq-state" title={t.error ?? undefined}>
          {(t.status === 'running' || t.status === 'waiting_external') && <Icon name="spinner" spin />}
          {st.label}
          {t.status === 'waiting_deps' && t.deps_remaining > 0 && `·差${t.deps_remaining}项`}
          {t.status === 'running' && t.progress > 0 && ` ${t.progress}%`}
        </span>
        <span className="tq-ops">
          <button className="small ghost" title="查看该任务的完整生成日志（提示词/参考图/错误/结果）"
            onClick={() => onOpenLog(t)}>日志</button>
          {cancelable && (
            <button className="small ghost" title="取消本任务（等待它的父任务会连锁失败）"
              onClick={() => api.cancelTask(pid, t.id).catch(e => alert(String(e)))}>取消</button>
          )}
          {t.status === 'failed' && (
            <button className="small ghost" title="重新入队（仍缺前置会自动重新派发子任务）"
              onClick={() => api.retryTask(pid, t.id).catch(e => alert(String(e)))}>重试</button>
          )}
        </span>
      </div>
      {t.status === 'failed' && t.error && (
        <div className="tq-err" style={{ paddingLeft: 24 + depth * 16 }}
          title="点击查看完整日志" onClick={() => onOpenLog(t)}>{t.error}</div>
      )}
      {node.children.map((c, i) => (
        <TaskRow key={`${t.id}:${c.task.id}:${i}`} pid={pid} node={c} depth={depth + 1} onOpenLog={onOpenLog} />
      ))}
    </>
  )
}

const liveDeep = (n: TaskNode): boolean => isLive(n.task) || n.children.some(liveDeep)

/** 任务队列（内嵌版）：对话面板「任务队列」tab 的下半区。
 * 原独立右侧抽屉（TaskQueuePanel + TaskQueueButton 浮标）的功能原样并入：
 * 在途依赖任务树（每棵一张卡）+「最近结束」折叠区（失败可看日志/重试），
 * 点「日志」弹 TaskLogModal 看完整生成记录。数据由全局任务中心 SSE 实时驱动。
 * 项目取自当前页面（uiContext）；没有当前项目时跟随最近活跃项目——
 * 桌面/系统管理页也能看到刚才那个项目的任务在跑。 */
export function TaskQueuePanel() {
  const pid = useActivePid()
  const tasks = useProjectTasks(pid)
  const [showDone, setShowDone] = useState(false)
  const [logTask, setLogTask] = useState<TaskInfo | null>(null)
  const forest = buildTaskForest(tasks)
  const live = forest.filter(liveDeep)
  const recent = forest.filter(n => !liveDeep(n)).slice(0, 20)
  return (
    <div className="tq-embedded" aria-label="任务队列">
      <div className="tq-sec">
        <Icon name="queue" /> 项目任务队列
        <span className="dim">{pid ? (live.length > 0 ? ` · 在途 ${live.length}` : '') : '（跟随最近活跃项目）'}</span>
      </div>
      {!pid && <div className="tq-empty">还没进入过项目；进入一次项目页，这里就会显示它的任务。</div>}
      {pid && live.length === 0 && <div className="tq-empty">当前没有在途任务</div>}
      {pid && live.map(n => (
        <div className="tq-card" key={n.task.id}><TaskRow pid={pid} node={n} depth={0} onOpenLog={setLogTask} /></div>
      ))}
      {pid && recent.length > 0 && (
        <button className="tq-sec tq-fold" onClick={() => setShowDone(v => !v)}
          title={showDone ? '折叠最近结束的任务' : '展开最近结束的任务'}>
          最近结束 {recent.length > 0 && recent.length}
          <span className={'tq-chev' + (showDone ? ' open' : '')}>›</span>
        </button>
      )}
      {pid && showDone && recent.map(n => (
        <div className="tq-card tq-card-done" key={n.task.id}><TaskRow pid={pid} node={n} depth={0} onOpenLog={setLogTask} /></div>
      ))}
      {logTask && pid && <TaskLogModal pid={pid} task={logTask} onClose={() => setLogTask(null)} />}
    </div>
  )
}
