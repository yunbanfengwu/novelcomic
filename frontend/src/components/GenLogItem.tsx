import { useState } from 'react'
import type { GenLog } from '../api'
import { GENLOG_KIND_CN, GENLOG_STATUS_CN, fmtLogTime } from '../lib/genLogLabels'
import './GenLogItem.css'

/** 单条生成日志：头行（时间/类型/来源/镜号/任务·提交次/模型/状态/模态）可点展开，
 * 详情含提交的提示词全文、参考图、参考音频、错误、生成结果、外部任务终态。
 * 自带全部样式，后台「生成日志」面板与任务队列错误弹框共用，两处视觉一致。
 * onFilterSource：仅后台面板传（点来源标记筛该分镜全部记录）；弹框不传时来源只作展示标签。 */
export function GenLogItem({ g, defaultOpen = false, onFilterSource }: {
  g: GenLog
  defaultOpen?: boolean
  onFilterSource?: (source: string) => void
}) {
  const [open, setOpen] = useState(defaultOpen)
  const text = g.request?.content?.find(c => c.type === 'text')?.text ?? g.request?.prompt ?? ''
  const rawImgs = (g.request?.content ?? []).filter(c => c.type === 'image_url')
    .map(c => c.image_url?.url).concat(g.request?.image ?? []).filter((u): u is string => !!u)
  // asset://<id> 是角色库备案素材：解析成真实形象图地址并打「备案角色」角标；未解析到则占位
  const imgs = rawImgs.map(u => {
    const filed = u.startsWith('asset://')
    const hit = filed ? g.assets?.[u] : undefined
    return { src: hit?.url ?? (filed ? '' : u), name: hit?.name, filed }
  })
  const auds = (g.request?.content ?? []).filter(c => c.type === 'audio_url')
  const bad = ['rejected', 'failed'].includes(g.status)

  return (
    <div className="genlog-item">
      <div className="genlog-head" onClick={() => setOpen(v => !v)} title="点击展开/收起完整入参与结果">
        <span className="dim">{fmtLogTime(g.created_at)}</span>
        <span className="tag">{GENLOG_KIND_CN[g.kind] ?? g.kind}</span>
        {g.source && (onFilterSource
          ? <span className="tag" title="点击按此来源筛选"
              onClick={e => { e.stopPropagation(); onFilterSource(g.source!.replace(/_(video|image|sheet|storyboard|overview|cover)$/, '')) }}>
              {g.source}</span>
          : <span className="tag">{g.source}</span>)}
        {g.chapter_title && <span className="tag">{g.chapter_title}</span>}
        {g.shot_no != null && <span className="tag">镜{g.shot_no}</span>}
        <span className="dim">{g.task_id ? `任务${g.task_id} · ` : ''}第{g.attempt_no}次提交 · {g.model || g.provider}</span>
        <span className={'tag' + (g.status === 'done' ? ' ok' : bad ? ' bad' : '')}>
          {GENLOG_STATUS_CN[g.status] ?? g.status}
        </span>
        {g.modality && <span className="dim genlog-modality">{g.modality}</span>}
      </div>
      {open && (
        <div className="genlog-detail">
          {text && <>
            <div className="genlog-label">提交的提示词全文
              {g.request?.duration ? `（${g.request.duration}s · ${g.request.ratio}）`
                : g.request?.size ? `（${g.request.size}）` : ''}</div>
            <div className="genlog-text">{text}</div>
          </>}
          {imgs.length > 0 && <>
            <div className="genlog-label">提交的参考图（{imgs.length}张）</div>
            <div className="genlog-imgs">
              {imgs.map((im, i) =>
                <a key={i} className="genlog-img" href={im.src || undefined}
                  target="_blank" rel="noreferrer">
                  {im.src
                    ? <img src={im.src} alt={im.name ? `备案角色 ${im.name}` : `参考图${i + 1}`} />
                    : <span className="genlog-img-missing">备案素材<br />无法预览</span>}
                  {im.filed && <span className="genlog-badge"
                    title={im.name ? `火山备案角色：${im.name}` : '火山备案素材'}>
                    备案角色{im.name ? `·${im.name}` : ''}</span>}
                </a>)}
            </div>
          </>}
          {auds.length > 0 && <>
            <div className="genlog-label">提交的参考音频（{auds.length}段）</div>
            {auds.map((c, i) => c.audio_url &&
              <audio key={i} src={c.audio_url.url} controls style={{ height: 28 }} />)}
          </>}
          {!!(g.employee_codes?.length || g.skill_slugs?.length || g.knowledge_refs?.length
            || g.sop_code || Object.keys(g.planner_snapshot || {}).length) && <>
            <div className="genlog-label">生成溯源</div>
            <div className="genlog-text">
              {g.employee_codes?.length ? `数字员工：${g.employee_codes.join('、')}\n` : ''}
              {g.skill_slugs?.length ? `Skills：${g.skill_slugs.join('、')}\n` : ''}
              {g.knowledge_refs?.length ? `知识：${g.knowledge_refs.join('、')}\n` : ''}
              {g.sop_code ? `SOP：${g.sop_code}\n` : ''}
              {g.planner_snapshot && Object.keys(g.planner_snapshot).length
                ? `规划快照：${JSON.stringify(g.planner_snapshot, null, 2)}` : ''}
            </div>
          </>}
          {g.error && <>
            <div className="genlog-label">错误</div>
            <div className="genlog-text genlog-err">{g.error}</div>
          </>}
          {g.result?.video_url && <>
            <div className="genlog-label">生成结果（完成于 {fmtLogTime(g.finished_at)}）</div>
            <video src={g.result.video_url} controls className="genlog-video" />
          </>}
          {g.result?.image_url && <>
            <div className="genlog-label">生成结果（完成于 {fmtLogTime(g.finished_at)}）</div>
            <div className="genlog-imgs">
              <a href={g.result.image_url} target="_blank" rel="noreferrer">
                <img src={g.result.image_url} alt="生成结果" />
              </a>
            </div>
          </>}
          {g.external_task_id && <div className="dim" style={{ fontSize: 12 }}>
            外部任务：{g.external_task_id}
            {g.task_status && g.task_status !== g.status && ` · 任务终态：${g.task_status}`}
          </div>}
        </div>
      )}
    </div>
  )
}
