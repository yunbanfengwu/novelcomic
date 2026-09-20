import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { GenLog } from '../../api'
import { Icon } from '../../components/Icon'
import { GenLogItem } from '../../components/GenLogItem'
import { GENLOG_STATUS_CN } from '../../lib/genLogLabels'

function pageItems(current: number, total: number): Array<number | 'ellipsis'> {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  if (current <= 4) return [1, 2, 3, 4, 5, 'ellipsis', total]
  if (current >= total - 3) return [1, 'ellipsis', total - 4, total - 3, total - 2, total - 1, total]
  return [1, 'ellipsis', current - 1, current, current + 1, 'ellipsis', total]
}

/** 生成日志面板：每次视频/图片提交一行（视频降级级联多行同 task_id），展开看完整入参与结果。
 * 单行渲染复用 components/GenLogItem（任务队列错误弹框同款）。
 * 排查口径：同一镜"之前好现在差"→ 按来源标记（如 project_10_2_21）筛出该分镜全部提交对比。 */
export function GenLogPanel() {
  const [logs, setLogs] = useState<GenLog[]>([])
  const [pid, setPid] = useState('')
  const [source, setSource] = useState('')
  const [status, setStatus] = useState('')
  const [media, setMedia] = useState<'' | 'video' | 'image'>('')
  const [page, setPage] = useState(1)
  const pageSize = 20
  const [total, setTotal] = useState(0)

  const reload = useCallback(() => {
    api.listGenLogs({
      project_id: pid ? Number(pid) : undefined,
      source: source.trim() || undefined,
      media: media || undefined,
      status: status || undefined, page, page_size: pageSize,
    }).then(result => {
      setLogs(result.items)
      setTotal(result.total)
    }).catch(e => alert(String(e)))
  }, [pid, source, media, status, page, pageSize])
  useEffect(() => { reload() }, [reload])

  const pageCount = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="adm-panel">
      <div className="adm-head">
        <h2><Icon name="clipboard" /> 生成日志</h2>
        <div className="seg">
          {([['', '全部'], ['video', '视频'], ['image', '图片']] as const).map(([k, v]) => (
            <button key={k} className={`seg-btn${media === k ? ' active' : ''}`}
              onClick={() => { setMedia(k); setPage(1) }}>{v}</button>
          ))}
        </div>
        <div className="seg">
          <button className={`seg-btn${status === '' ? ' active' : ''}`}
            onClick={() => { setStatus(''); setPage(1) }}>全部</button>
          {Object.entries(GENLOG_STATUS_CN).map(([k, v]) => (
            <button key={k} className={`seg-btn${status === k ? ' active' : ''}`}
              onClick={() => { setStatus(k); setPage(1) }}>{v}</button>
          ))}
        </div>
        <div className="adm-actions">
          <input style={{ width: 110 }} placeholder="项目ID" value={pid}
            onChange={e => { setPid(e.target.value); setPage(1) }} />
          <input style={{ width: 190 }} placeholder="来源前缀 如 project_10_2_21"
            value={source} onChange={e => { setSource(e.target.value); setPage(1) }} />
          <button className="small ghost" onClick={reload}><Icon name="refresh" /> 刷新</button>
        </div>
      </div>
      <div className="adm-scroll genlog-scroll">
        <div className="dim" style={{ fontSize: 12, marginBottom: 10 }}>
          每次真实提交一行（视频降级级联为多行同任务ID）；点来源标记可筛出该分镜/条目的全部记录
        </div>
        {logs.map(g => <GenLogItem key={g.id} g={g}
          onFilterSource={value => { setSource(value); setPage(1) }} />)}
        {!logs.length && <div className="dim">暂无记录——每次视频与图片生成的真实提交（含降级级联每一跳）都会记录在此。</div>}
      </div>
      {total > 0 && <div className="genlog-pager" aria-label="生成日志分页">
        <button className="genlog-page-btn" disabled={page <= 1}
          onClick={() => setPage(p => Math.max(1, p - 1))} title="上一页">‹</button>
        {pageItems(page, pageCount).map((item, index) =>
          item === 'ellipsis'
            ? <span className="genlog-page-ellipsis" key={`ellipsis-${index}`}>…</span>
            : <button key={item} className={`genlog-page-btn${item === page ? ' active' : ''}`}
                onClick={() => setPage(item)} aria-current={item === page ? 'page' : undefined}>
                {item}
              </button>
        )}
        <button className="genlog-page-btn" disabled={page >= pageCount}
          onClick={() => setPage(p => Math.min(pageCount, p + 1))} title="下一页">›</button>
        <span className="genlog-page-total">共 {total} 条</span>
      </div>}
    </div>
  )
}
