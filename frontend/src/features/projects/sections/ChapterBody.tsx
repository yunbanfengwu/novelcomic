import { useEffect, useState } from 'react'
import { api } from '../../../api'
import type { Chapter, Element, Project, Volume } from '../../../api'
import { ChapterCatalog } from '../ChapterCatalog'
import { ChapterElements } from '../ChapterElements'
import { needsImage } from '../../../lib/kinds'
import { Icon } from '../../../components/Icon'

/** 正文分区（视频菜单下）：左栏目录 + 右侧「正文 + 关联要素」自适应双栏（预览区 <1080px 堆叠，要素在下）；
 *  生成/编辑动作以浮动段控钉在正文列（body-main）右下角。 */
export function ChapterBody({ pid, chapter, chapters, volumes, project, elements, onChaptersChange, onVolumesChange }: {
  pid: number
  chapter: Chapter
  chapters: Chapter[]
  volumes: Volume[]
  project: Project
  elements: Element[]
  onChaptersChange: () => void
  onVolumesChange: () => void
}) {
  const [body, setBody] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  // 人工编辑态：draft=编辑框内容；进入编辑即以当前正文预填
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  // 目标成片时长：后端据此下发字数硬约束（约 240-420 字/分钟）。默认 6——不带约束时
  // 实测只写 346 字、拆出 8 镜共 42 秒，远撑不起一集。
  const [minutes, setMinutes] = useState(6)

  useEffect(() => {
    let on = true
    setLoading(true); setBody('')
    api.getBody(pid, chapter.id)
      .then(r => { if (on) setBody(r.content || '') })
      .catch(() => { if (on) setBody('') })
      .finally(() => { if (on) setLoading(false) })
    return () => { on = false }
  }, [pid, chapter.id])

  const writeBody = async () => {
    setBusy(true)
    try {
      // 流式：边写边显示（截掉末尾 <STATE> 回写块）；流完后端落库，再取终稿
      await api.streamWriteChapter(pid, chapter.id, acc => {
        setBody(acc.split('<STATE>')[0])
      }, minutes)
      const r = await api.getBody(pid, chapter.id)
      setBody(r.content || '')
      onChaptersChange()
    } catch (e) { alert(String(e)) }
    setBusy(false)
  }

  const startEdit = () => { setDraft(body); setEditing(true) }
  const cancelEdit = () => { setEditing(false) }
  const saveEdit = async () => {
    setSaving(true)
    try {
      // 人工保存：只覆盖正文文本，不触发 AI 回写（要素状态/流水账不受改稿影响）
      const r = await api.saveBody(pid, chapter.id, draft)
      setBody(r.content || '')
      setEditing(false)
      onChaptersChange()
    } catch (e) { alert(String(e)) }
    setSaving(false)
  }

  // 本章关联要素：需要设定图的要素（角色/场景/设定…）——出现在本章或未标注章节的通用要素；抽象要素（冲突线/伏笔等）不展示
  const related = elements.filter(e =>
    needsImage(e) && (e.appears_in.includes(chapter.seq) || e.appears_in.length === 0))

  return (
    <div className="body-split">
      <ChapterCatalog pid={pid} chapters={chapters} volumes={volumes} project={project}
        onChaptersChange={onChaptersChange} onVolumesChange={onVolumesChange} />
      <div className="body-pane">
        <div className={`body-cols${related.length > 0 ? ' has-aside' : ''}`}>
          <div className="body-main">
            <div className="body-main-scroll">
              <p className="dim">{chapter.summary}</p>
              {editing
                ? <textarea className="body-editor" value={draft} autoFocus
                    onChange={e => setDraft(e.target.value)} placeholder="在此撰写／编辑本章正文…" />
                : loading
                  ? <div className="empty-hint">正文加载中…</div>
                  : body
                    ? <div className="body-text">{body}</div>
                    : <div className="empty-hint">尚无正文，点击右下角「生成正文」开始，或「编辑正文」手动撰写</div>}
            </div>
            {/* 浮动动作条：钉在正文列右下角（外观复用顶部 tab 段控 .seg，高亮态用 .active） */}
            <div className="body-actions">
              <div className="seg">
                {editing ? (
                  <>
                    <button className="seg-btn" disabled={saving} onClick={cancelEdit}>取消</button>
                    <button className="seg-btn active" disabled={saving} onClick={saveEdit}>
                      {saving ? <><Icon name="spinner" spin /> 保存中…</> : <><Icon name="save" /> 保存</>}
                    </button>
                  </>
                ) : (
                  <>
                    <select className="seg-select" value={minutes} disabled={busy}
                      onChange={e => setMinutes(Number(e.target.value))} title="目标时长">
                      {[6, 7, 8, 9, 10].map(m => <option key={m} value={m}>{m} 分钟</option>)}
                    </select>
                    <button className={`seg-btn active${!body && !loading && !busy ? ' guide-glow' : ''}`} disabled={busy} onClick={writeBody}>
                      {busy ? <><Icon name="spinner" spin /> 写作员工创作中…</>
                        : <><Icon name="pen" /> {body ? '重写正文' : '生成正文'}</>}
                    </button>
                    <button className="seg-btn" disabled={busy || loading} onClick={startEdit} title="手动编辑正文">
                      <Icon name="text" /> 编辑正文
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
          {related.length > 0 && <aside className="body-aside"><ChapterElements elements={related} /></aside>}
        </div>
      </div>
    </div>
  )
}
