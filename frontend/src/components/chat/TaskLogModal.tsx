import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { GenLog, TaskInfo } from '../../api'
import { Modal } from '../Modal'
import { GenLogItem } from '../GenLogItem'
import { TASK_KIND_LABEL, taskTargetLabel } from '../../lib/taskKinds'

/** 任务日志弹框：任务队列里点「日志」/失败错误行打开，拉取该任务的全部真实提交
 * 记录（gen_logs），每条一张 GenLogItem 展开看完整提示词/参考图/错误/结果。
 * 无 gen_logs 时（尚未真正提交到生成服务，如前置阶段就失败）回退显示任务自身 error。 */
export function TaskLogModal({ pid, task, onClose }: {
  pid: number; task: TaskInfo; onClose: () => void
}) {
  const [logs, setLogs] = useState<GenLog[] | null>(null)
  useEffect(() => {
    api.listGenLogs({ project_id: pid, task_id: task.id, page_size: 100 })
      .then(result => setLogs(result.items)).catch(() => setLogs([]))
  }, [pid, task.id])

  const title = `${TASK_KIND_LABEL[task.kind] ?? task.kind} ${taskTargetLabel(task)} · 日志`
  return (
    <Modal open onClose={onClose} wide topmost title={title}>
      <div className="tlm-body">
        {logs === null && <div className="dim">加载中…</div>}
        {logs?.length === 0 && (
          <div className="genlog-detail">
            {task.error
              ? <><div className="genlog-label">错误</div>
                  <div className="genlog-text genlog-err">{task.error}</div></>
              : <div className="dim">该任务暂无提交记录（可能尚未真正提交到生成服务）。</div>}
          </div>
        )}
        {logs?.map((g, i) => <GenLogItem key={g.id} g={g} defaultOpen={i === 0} />)}
      </div>
    </Modal>
  )
}
