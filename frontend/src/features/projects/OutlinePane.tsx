import { useState } from 'react'
import { api } from '../../api'
import type { Project } from '../../api'
import { Icon } from '../../components/Icon'
import { Markdown } from '../../components/Markdown'
import { useLiveKinds } from '../../lib/useTaskDone'

/** 大纲（内嵌于基本信息下方）：Markdown 全文 + 后台重新生成 + 手动改稿。
 * 无大纲时显示居中空态 + 生成 / 手动编写按钮；AI 生成完成由任务事件刷新终稿。
 * 手动编辑只覆盖 outline_md 文本（PATCH 基本信息），不触发 AI 重新生成。
 * 建项目后的自动补拟走后台任务链（SSE 感知在途），完成由容器刷新项目数据带入。 */
export function OutlinePane({ p, onChange }: {
  p: Project
  onChange: (md: string) => void
}) {
  const [queuing, setQueuing] = useState(false)
  // 人工编辑态：draft=编辑框内容；进入编辑即以当前大纲预填
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const review = p.config?.outline_content_review as {
    content_stage?: string
    decision_summary?: string
    issues?: string[]
    accepted_additions?: { name?: string; reason?: string }[]
    rejected_additions?: { name?: string; reason?: string }[]
    setting_assessments?: {
      name?: string
      origin?: string
      verdict?: '保留' | '修订' | '删除'
      reason?: string
    }[]
    semantic_review?: {
      passed?: boolean
      unresolved_issues?: string[]
      reasonable_settings?: { name?: string; reason?: string }[]
      settings_requiring_revision?: { name?: string; reason?: string }[]
      summary?: string
    }
  } | undefined
  // 后台任务在途（建项目自动链/总览自动补发）：空态显示"生成中"，避免误再点手动生成
  const bgBusy = useLiveKinds(p.id, ['gen_project_info', 'gen_outline_md']).size > 0

  const regen = async () => {
    setQueuing(true)
    try {
      await api.regenerateOutlineMdTask(p.id)
    } catch (e) { alert(String(e)) } finally { setQueuing(false) }
  }

  const startEdit = () => { setDraft(p.outline_md || ''); setEditing(true) }
  const cancelEdit = () => { setEditing(false) }
  const saveEdit = async () => {
    setSaving(true)
    try {
      // 人工保存：只覆盖大纲文本，不触发 AI 重新生成
      await api.updateProject(p.id, { outline_md: draft })
      onChange(draft)
      setEditing(false)
    } catch (e) { alert(String(e)) } finally { setSaving(false) }
  }

  // 编辑态：纯文本改稿框 + 保存/取消（空态与有稿态共用）
  if (editing) {
    return (
      <div className="outline-pane">
        <div className="outline-edit-actions">
          <button className="small ghost" disabled={saving} onClick={cancelEdit}>取消</button>
          <button className="small" disabled={saving} onClick={saveEdit}>
            {saving ? <><Icon name="spinner" spin /> 保存中…</> : <><Icon name="save" /> 保存</>}
          </button>
        </div>
        <textarea className="body-editor outline-editor" value={draft} autoFocus
          onChange={e => setDraft(e.target.value)}
          placeholder="在此撰写／编辑架构大纲（支持 Markdown）…" />
      </div>
    )
  }

  // 空态：后台任务在途→生成中提示；否则居中提示 + 手动生成 / 手动编写
  if (!p.outline_md) {
    return (
      <div className="outline-pane outline-center">
        {bgBusy ? (
          <div className="dim"><Icon name="spinner" spin /> 大纲后台生成中（基本信息初拟→架构大纲），完成后自动展示…</div>
        ) : (
          <>
            <div className="dim">暂无大纲</div>
            <div className="btns">
              <button className="empty-hint-btn" disabled={queuing} onClick={regen}>
                <Icon name={queuing ? 'spinner' : 'sparkles'} spin={queuing} />
                {queuing ? '正在提交…' : '生成大纲'}
              </button>
              <button className="empty-hint-btn ghost" onClick={startEdit}>
                <Icon name="text" /> 手动编写
              </button>
            </div>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="outline-pane">
      <div className="outline-actions">
        <button className="small ghost" onClick={startEdit} title="手动编辑大纲">
          <Icon name="text" /> 编辑大纲
        </button>
        <button className="small ghost" disabled={bgBusy || queuing} onClick={regen}>
          <Icon name={bgBusy || queuing ? 'spinner' : 'sparkles'} spin={bgBusy || queuing} />
          {bgBusy || queuing ? '后台生成中…' : '重新生成大纲'}
        </button>
      </div>
      {review && (
        <details className="outline-review">
          <summary>内容质检 · {review.content_stage === 'development' ? '项目开发期' : review.content_stage}</summary>
          {review.decision_summary && <p>{review.decision_summary}</p>}
          {!!review.issues?.length && (
            <div><b>发现问题</b><ul>{review.issues.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
          )}
          {!!review.setting_assessments?.length && (
            <div><b>既有与新增设定裁决</b><ul>{review.setting_assessments.map((x, i) =>
              <li key={i}>【{x.verdict || '修订'}】{x.name}
                {x.origin ? `（${x.origin}）` : ''}{x.reason ? `：${x.reason}` : ''}</li>)}</ul></div>
          )}
          {!!review.accepted_additions?.length && (
            <div><b>接受的扩展</b><ul>{review.accepted_additions.map((x, i) =>
              <li key={i}>{x.name}{x.reason ? `：${x.reason}` : ''}</li>)}</ul></div>
          )}
          {!!review.rejected_additions?.length && (
            <div><b>拒绝或合并</b><ul>{review.rejected_additions.map((x, i) =>
              <li key={i}>{x.name}{x.reason ? `：${x.reason}` : ''}</li>)}</ul></div>
          )}
          {review.semantic_review && (
            <div>
              <b>修订成稿复核：{review.semantic_review.passed ? '通过' : '未通过'}</b>
              {review.semantic_review.summary && <p>{review.semantic_review.summary}</p>}
              {!!review.semantic_review.unresolved_issues?.length && (
                <ul>{review.semantic_review.unresolved_issues.map((x, i) =>
                  <li key={i}>{x}</li>)}</ul>
              )}
            </div>
          )}
        </details>
      )}
      <Markdown text={p.outline_md} />
    </div>
  )
}
