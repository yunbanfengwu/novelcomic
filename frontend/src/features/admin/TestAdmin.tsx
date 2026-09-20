import { useEffect, useMemo, useState } from 'react'
import { api, type TestLog, type TestRunSummary } from '../../api'
import { Icon } from '../../components/Icon'

const statusLabel: Record<string, string> = {
  done: '通过', failed: '失败', running: '进行中', cancelled: '已取消',
}

function stamp(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="test-json">{JSON.stringify(value ?? {}, null, 2)}</pre>
}

export function TestAdmin() {
  const [runs, setRuns] = useState<TestRunSummary[]>([])
  const [runId, setRunId] = useState('')
  const [logs, setLogs] = useState<TestLog[]>([])
  const [stepId, setStepId] = useState<number>()
  const [busy, setBusy] = useState(false)

  const loadRuns = async () => {
    setBusy(true)
    try {
      const rows = await api.testRuns()
      setRuns(rows)
      if (!runId && rows[0]) setRunId(rows[0].test_run_id)
    } finally { setBusy(false) }
  }
  useEffect(() => { void loadRuns() }, [])
  useEffect(() => {
    if (!runId) { setLogs([]); return }
    void api.testRun(runId).then(rows => {
      const steps = rows.filter(row => row.kind === 'qa_test')
      setLogs(steps)
      if (!steps.some(row => row.id === stepId)) setStepId(steps[0]?.id)
    })
  }, [runId])

  const selected = useMemo(
    () => logs.find(row => row.id === stepId), [logs, stepId])

  return (
    <div className="test-admin">
      <div className="test-toolbar">
        <div>
          <h2>全链路测试台</h2>
          <p>复用生成日志，记录真实请求及其员工、Skills、知识、SOP 与规划证据。</p>
        </div>
        <button className="btn" onClick={() => void loadRuns()} disabled={busy}>
          <Icon name="refresh" spin={busy} /> 刷新
        </button>
      </div>
      <div className="test-columns">
        <aside className="test-pane test-runs">
          <div className="test-pane-title">测试批次 <span>{runs.length}</span></div>
          {runs.map(run => (
            <button key={run.test_run_id}
              className={'test-run-card' + (runId === run.test_run_id ? ' active' : '')}
              onClick={() => setRunId(run.test_run_id)}>
              <strong>{run.title || '未命名测试'}</strong>
              <small>{stamp(run.started_at)}</small>
              <div className="test-counts">
                <span className="ok">{run.passed} 通过</span>
                <span className="bad">{run.failed} 失败</span>
                {run.running > 0 && <span>{run.running} 进行中</span>}
              </div>
              {run.project_id && <small>项目 #{run.project_id}</small>}
            </button>
          ))}
          {!runs.length && <div className="empty">暂无测试记录</div>}
        </aside>

        <section className="test-pane test-steps">
          <div className="test-pane-title">测试项目 <span>{logs.length}</span></div>
          {logs.map(step => (
            <button key={step.id}
              className={'test-step-card' + (stepId === step.id ? ' active' : '')}
              onClick={() => setStepId(step.id)}>
              <i className={`test-dot ${step.status}`} />
              <div>
                <strong>{step.test_item}</strong>
                <small>{statusLabel[step.status] || step.status} · {stamp(step.created_at)}</small>
              </div>
              <span>{step.duration_ms != null ? `${(step.duration_ms / 1000).toFixed(1)}s` : '—'}</span>
            </button>
          ))}
          {!logs.length && <div className="empty">该批次暂无测试项目</div>}
        </section>

        <main className="test-pane test-detail">
          <div className="test-pane-title">测试证据</div>
          {!selected ? <div className="empty">选择一个测试项目查看详情</div> : <>
            <div className="test-result-head">
              <span className={`test-status ${selected.status}`}>
                {statusLabel[selected.status] || selected.status}
              </span>
              <div>
                <h3>{selected.test_item}</h3>
                <p>开始 {stamp(selected.created_at)}　结束 {stamp(selected.finished_at)}</p>
              </div>
            </div>
            <div className="test-facts">
              <label>数字员工</label>
              <div>{selected.employee_codes.length
                ? selected.employee_codes.map(x => <span key={x}>{x}</span>) : '未关联'}</div>
              <label>调用 Skills</label>
              <div>{selected.skill_slugs.length
                ? selected.skill_slugs.map(x => <span key={x}>{x}</span>) : '未调用'}</div>
              <label>调用知识</label>
              <div>{selected.knowledge_refs.length
                ? selected.knowledge_refs.map(x => <span key={x}>{x}</span>) : '未调用'}</div>
              <label>SOP</label><div>{selected.sop_code || '未使用'}</div>
              <label>模型</label><div>{[selected.provider, selected.model].filter(Boolean).join(' / ') || '—'}</div>
              <label>任务</label><div>{selected.task_id ? `#${selected.task_id}` : '同步调用'}</div>
            </div>
            {selected.error && <div className="test-error">{selected.error}</div>}
            <details open><summary>输出结果</summary><JsonBlock value={selected.result} /></details>
            <details><summary>before / run / next 规划快照</summary>
              <JsonBlock value={selected.planner_snapshot} /></details>
            <details><summary>真实输入</summary><JsonBlock value={selected.request} /></details>
          </>}
        </main>
      </div>
    </div>
  )
}
