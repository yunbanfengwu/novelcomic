import { useState, type Dispatch, type SetStateAction } from 'react'
import { api } from '../../api'
import type { KbEntry } from '../../api'
import { Icon } from '../../components/Icon'
import { TagPicker } from './TagPicker'

type Attachment = { title?: string; url: string }

/** 条目编辑弹窗的「结构化」tab：逐字段表单 + 正负提示词（prompt_block）+ 缩略图生成 + 附件列表 */
export function KbEntryFields({ e, setE }: {
  e: Partial<KbEntry>
  setE: Dispatch<SetStateAction<Partial<KbEntry>>>
}) {
  const [thumbBusy, setThumbBusy] = useState(false)
  const [attDraft, setAttDraft] = useState<Attachment>({ title: '', url: '' })
  const patch = (p: Partial<KbEntry>) => setE(v => ({ ...v, ...p }))
  const patchMeta = (p: Record<string, unknown>) => setE(v => ({ ...v, meta: { ...v.meta, ...p } }))
  const isBlock = e.kind === 'prompt_block'
  const atts: Attachment[] = (e.meta?.attachments as Attachment[]) || []

  const genThumb = async () => {
    if (!e.id) { alert('先保存条目，再生成缩略图'); return }
    setThumbBusy(true)
    try {
      // 缩略图=用本条正向提示词渲染示例场景（画风库卡片）；其他条目按内容出概念示意图
      const { thumbnail_url } = await api.genKbThumbnail(e.id)
      patch({ thumbnail_url })
    } catch (err) { alert(String(err)) } finally { setThumbBusy(false) }
  }
  const addAtt = () => {
    if (!attDraft.url.trim()) return
    patchMeta({ attachments: [...atts, { title: attDraft.title?.trim(), url: attDraft.url.trim() }] })
    setAttDraft({ title: '', url: '' })
  }

  return (
    <>
      <div className="inline">
        <input placeholder="名称 name（召回匹配用）" value={e.name || ''}
          onChange={ev => patch({ name: ev.target.value })} />
        <input placeholder="展示标题（空=用名称）" value={e.title || ''}
          onChange={ev => patch({ title: ev.target.value })} />
        <input placeholder="分类 category" value={e.category || ''}
          onChange={ev => patch({ category: ev.target.value })} />
        <input type="number" className="kb-weight-input" placeholder="权重" title="权重：搜索与展示排序，越大越靠前"
          value={e.weight ?? 0}
          onChange={ev => patch({ weight: Number(ev.target.value) || 0 })} />
      </div>
      <input placeholder="触发描述（何时召回此条）" value={e.description || ''}
        onChange={ev => patch({ description: ev.target.value })} />
      <textarea rows={4} placeholder="内容 content（中文说明/知识正文/文风指令）" value={e.content || ''}
        onChange={ev => patch({ content: ev.target.value })} />
      {isBlock && (
        <>
          <textarea rows={2} placeholder="正向提示词 positive" value={e.meta?.positive || ''}
            onChange={ev => patchMeta({ positive: ev.target.value })} />
          <textarea rows={1} placeholder="负面提示词 negative" value={e.meta?.negative || ''}
            onChange={ev => patchMeta({ negative: ev.target.value })} />
        </>
      )}
      <TagPicker value={e.tags || []} onChange={tags => patch({ tags })} />
      <div className="kb-thumb-edit">
        {e.thumbnail_url && <img className="kb-thumb" src={e.thumbnail_url} alt="缩略图" />}
        <input placeholder="缩略图 URL（或点右侧按提示词生成）" value={e.thumbnail_url || ''}
          onChange={ev => patch({ thumbnail_url: ev.target.value })} />
        <button className="small ghost" disabled={thumbBusy} onClick={genThumb}
          title={e.id ? '用本条提示词/内容生成缩略图并转存' : '先保存条目'}>
          {thumbBusy ? <><Icon name="spinner" spin /> 生成中…</> : <><Icon name="image" /> 生成缩略图</>}
        </button>
      </div>
      <div className="kb-atts">
        {atts.map((a, i) => (
          <div key={i} className="kb-att">
            <a href={a.url} target="_blank" rel="noreferrer"><Icon name="clip" /> {a.title || a.url}</a>
            <button className="small ghost" onClick={() =>
              patchMeta({ attachments: atts.filter((_, k) => k !== i) })}>✕</button>
          </div>
        ))}
        <div className="inline">
          <input placeholder="附件标题（可选）" value={attDraft.title || ''}
            onChange={ev => setAttDraft(v => ({ ...v, title: ev.target.value }))} />
          <input placeholder="附件 URL（图/音频/文档）" value={attDraft.url}
            onChange={ev => setAttDraft(v => ({ ...v, url: ev.target.value }))} />
          <button className="small ghost" onClick={addAtt}><Icon name="clip" /> 加附件</button>
        </div>
      </div>
    </>
  )
}
