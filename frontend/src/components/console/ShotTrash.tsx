import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import type { RecycledShot, ShotTrashProject } from '../../api'
import { Icon } from '../Icon'
import { fmtDateTime } from '../../lib/fmtTime'

/** 同一次删除的分镜共享 (章, deleted_at) → 天然一批（重拆镜=整集一批 / 删除本镜=单镜一批）。 */
interface Batch {
  key: string; project_title: string
  chapter_seq: number | null; chapter_title: string | null
  deleted_at: string; items: RecycledShot[]
}
function groupBatches(shots: RecycledShot[]): Batch[] {
  const map = new Map<string, Batch>()
  for (const s of shots) {
    const key = `${s.chapter_id}|${s.deleted_at}`
    let b = map.get(key)
    if (!b) {
      b = { key, project_title: s.project_title, chapter_seq: s.chapter_seq,
            chapter_title: s.chapter_title, deleted_at: s.deleted_at, items: [] }
      map.set(key, b)
    }
    b.items.push(s)
  }
  return [...map.values()]
}

/**
 * 分镜回收站：跨项目列出被软删除的分镜（手动删除本镜 / 重拆镜整集移入），按项目筛选。
 * 依产品要求暂不做恢复，仅支持彻底删除（单镜 / 整批）。视频/首帧资料随镜行保留，缩略图直接可见。
 */
export function ShotTrash() {
  const [projects, setProjects] = useState<ShotTrashProject[]>([])
  const [shots, setShots] = useState<RecycledShot[] | null>(null)
  const [pid, setPid] = useState<number | 'all'>('all')
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      const [ps, ss] = await Promise.all([
        api.shotTrashProjects(),
        api.listShotTrash(pid === 'all' ? undefined : pid),
      ])
      setProjects(ps); setShots(ss)
    } catch (e) { alert((e as Error).message); setShots([]) }
  }
  useEffect(() => { load() }, [pid])  // eslint-disable-line react-hooks/exhaustive-deps

  const batches = useMemo(() => groupBatches(shots ?? []), [shots])

  const purgeOne = async (s: RecycledShot) => {
    if (!confirm(`彻底删除 镜${s.shot_no ?? s.seq}？该镜及其视频/首帧记录将永久清除，不可恢复。`)) return
    setBusy(true)
    try { await api.purgeShot(s.id); await load() }
    catch (e) { alert((e as Error).message) }
    finally { setBusy(false) }
  }
  const purgeBatch = async (b: Batch) => {
    if (!confirm(`彻底删除本批 ${b.items.length} 个分镜？将永久清除，不可恢复。`)) return
    setBusy(true)
    try { await api.purgeShotBatch(b.items.map(s => s.id)); await load() }
    catch (e) { alert((e as Error).message) }
    finally { setBusy(false) }
  }

  if (shots === null) return <div className="console-loading"><Icon name="spinner" spin /> 加载中…</div>

  return (
    <div className="shot-trash">
      <div className="strash-bar">
        <select value={pid} disabled={busy}
          onChange={e => setPid(e.target.value === 'all' ? 'all' : Number(e.target.value))}>
          <option value="all">全部项目（{projects.reduce((n, p) => n + p.cnt, 0)}）</option>
          {projects.map(p => (
            <option key={p.project_id} value={p.project_id}>{p.title}（{p.cnt}）</option>
          ))}
        </select>
      </div>

      {!shots.length ? (
        <div className="console-empty">
          <Icon name="trash" /><b>没有已删除的分镜</b>
          <span className="dim">删除本镜或重新拆镜时，旧分镜会移到这里（视频资料保留）</span>
        </div>
      ) : batches.map(b => (
        <div key={b.key} className="strash-group">
          <div className="strash-group-head">
            <div className="strash-group-title">
              <b title={b.project_title}>{b.project_title}</b>
              <span className="dim">
                {b.chapter_seq != null ? `第${b.chapter_seq}章 ` : ''}{b.chapter_title || ''}
              </span>
            </div>
            <span className="dim">删除于 {fmtDateTime(b.deleted_at)} · {b.items.length}镜</span>
            <button className="ghost small trash-purge" disabled={busy} onClick={() => purgeBatch(b)}>
              <Icon name="trash" /> 彻底删除本批
            </button>
          </div>
          <div className="strash-shots">
            {b.items.map(s => {
              const thumb = s.video_cover_url || s.keyframe_url || s.last_frame_url
              return (
                <div key={s.id} className="strash-shot">
                  <div className="strash-thumb">
                    {thumb ? <img src={thumb} alt="" /> : <span>镜{s.shot_no ?? s.seq}</span>}
                    {s.video_url && <span className="strash-play">▶</span>}
                  </div>
                  <div className="strash-info">
                    <b>镜{s.shot_no ?? s.seq}</b>
                    {s.duration_s != null && <span className="dim">{s.duration_s}s</span>}
                  </div>
                  <button className="strash-del" title="彻底删除" disabled={busy}
                    onClick={() => purgeOne(s)}>
                    <Icon name="trash" />
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
