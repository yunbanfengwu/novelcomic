import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Element } from '../../api'
import { Icon } from '../../components/Icon'

/** 要素基本信息（名称 / 描述 / 出现章节）展示 + 手动编辑：对所有要素类型通用（角色/场景/剧情线…）。
 *  名称/描述落 content_elements.name/brief；出现章节按 seq 列表重建 element_appearances 索引；
 *  角色的生图「外貌提示词」另走图片生成弹框，互不影响。 */
const parseSeqs = (s: string): number[] =>
  [...new Set((s.match(/\d+/g) ?? []).map(Number))].sort((a, b) => a - b)

export function ElementBasicInfo({ pid, el, onReload }: {
  pid: number; el: Element; onReload: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(el.name)
  const [brief, setBrief] = useState(el.brief)
  const [chapters, setChapters] = useState(el.appears_in.join(', '))
  const [saving, setSaving] = useState(false)

  // 切换要素 / 库内值变化后退出编辑并以库内值重置草稿（避免残留上一个要素的编辑）
  useEffect(() => {
    setEditing(false); setName(el.name); setBrief(el.brief); setChapters(el.appears_in.join(', '))
  }, [el.id, el.name, el.brief, el.appears_in])

  const start = () => {
    setName(el.name); setBrief(el.brief); setChapters(el.appears_in.join(', ')); setEditing(true)
  }
  const save = async () => {
    if (!name.trim()) { alert('名称不能为空'); return }
    setSaving(true)
    try {
      await api.updateElement(pid, el.id, { name: name.trim(), brief })
      // 出现章节走独立索引表，仅在变化时落
      const seqs = parseSeqs(chapters)
      if (seqs.join(',') !== [...el.appears_in].join(','))
        await api.updateElementAppears(pid, el.id, seqs)
      onReload()
      setEditing(false)
    } catch (e) { alert(String(e)) } finally { setSaving(false) }
  }

  if (editing) {
    return (
      <div className="el-basic-edit">
        <label className="el-edit-row">
          <span className="el-edit-label">名称</span>
          <input className="modal-input" value={name} autoFocus
            onChange={e => setName(e.target.value)} />
        </label>
        <label className="el-edit-row">
          <span className="el-edit-label">描述</span>
          <textarea className="modal-textarea" rows={4} value={brief}
            onChange={e => setBrief(e.target.value)} placeholder="要素的剧情描述 / 设定简介…" />
        </label>
        <label className="el-edit-row">
          <span className="el-edit-label">出现章节</span>
          <input className="modal-input" value={chapters}
            onChange={e => setChapters(e.target.value)}
            placeholder="章节序号，逗号分隔，如 1, 2, 5（未匹配到的章节忽略）" />
        </label>
        <div className="btns el-edit-acts">
          <button className="small ghost" disabled={saving} onClick={() => setEditing(false)}>取消</button>
          <button className="small" disabled={saving} onClick={save}>
            {saving ? <><Icon name="spinner" spin /> 保存中…</> : <><Icon name="save" /> 保存</>}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="el-basic">
      <div className="el-basic-text">
        <p className="el-basic-brief">{el.brief || <span className="dim">（暂无描述）</span>}</p>
        <p className="dim el-basic-appears">出现章节:{el.appears_in.join(', ') || '—'}</p>
      </div>
      <button className="small ghost el-basic-edit-btn" onClick={start} title="编辑名称 / 描述 / 出现章节">
        <Icon name="pen" /> 编辑
      </button>
    </div>
  )
}
