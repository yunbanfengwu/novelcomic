import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { KbEntry } from '../../api'
import { Icon } from '../../components/Icon'
import { Seg } from '../../components/Seg'
import { entryToText, applyEntryText, SMART_PLACEHOLDER } from '../../lib/kbEntryText'
import { KbEntryFields } from './KbEntryFields'

type Tab = 'smart' | 'form'

/** 知识库条目编辑弹窗：智能解析（一个输入框，按「标签：值」行解析各字段）/ 结构化（逐字段表单）
 * 两 tab 同一份数据——切换时互相换算；编辑打开时把已有字段合并成一段文本展示在智能 tab。 */
export function KbEntryEditor({ entry, onSave, onCancel }: {
  entry: Partial<KbEntry>
  onSave: (e: Partial<KbEntry>) => Promise<void>
  onCancel: () => void
}) {
  const [e, setE] = useState<Partial<KbEntry>>(entry)
  const [tab, setTab] = useState<Tab>('smart')
  const [text, setText] = useState(() => entryToText(entry))
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [onCancel])

  // 切 tab 时把当前 tab 的编辑结果换算给另一个 tab，两边始终是同一份数据
  const switchTab = (t: Tab) => {
    if (t === tab) return
    if (t === 'form') setE(v => applyEntryText(v, text))
    else setText(entryToText(e))
    setTab(t)
  }
  const save = async () => {
    setSaving(true)
    try { await onSave(tab === 'smart' ? applyEntryText(e, text) : e) }
    finally { setSaving(false) }
  }

  return createPortal(
    <div className="kbe-overlay" onClick={() => { if (!saving) onCancel() }}>
      <div className="kbe-modal" onClick={ev => ev.stopPropagation()}>
        <div className="kbe-head">
          <b>{e.id ? `编辑 #${e.id}` : '新增条目'}</b>
          <Seg<Tab> active={tab} onSelect={switchTab} items={[
            { key: 'smart', label: '智能解析', title: '一个输入框写完，按「标签：值」行自动拆成各字段' },
            { key: 'form', label: '结构化', title: '逐字段表单编辑' },
          ]} />
          <button className="kbe-close" title="关闭 (Esc)" onClick={onCancel}>✕</button>
        </div>
        <div className="kbe-body">
          {tab === 'smart' ? (
            <>
              <div className="dim kbe-hint">
                每行「字段：值」自动解析（名称/标题/分类/权重/触发/内容/缩略图/附件…）；空字段省略即可，纯文本首行作名称。
              </div>
              <textarea className="kbe-smart" value={text} placeholder={SMART_PLACEHOLDER}
                onChange={ev => setText(ev.target.value)} autoFocus />
            </>
          ) : <KbEntryFields e={e} setE={setE} />}
        </div>
        <div className="btns kbe-foot">
          <button disabled={saving} onClick={save}>
            {saving ? <Icon name="spinner" spin /> : <Icon name="save" />} 保存
          </button>
          <button className="ghost" disabled={saving} onClick={onCancel}>取消</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
