import { useState } from 'react'
import { api } from '../../api'
import { Icon } from '../../components/Icon'
import { openTapflowWindow } from '../../lib/tapflowWindow'

/** 新建画布的最小图：开始→结束，入参只有项目。其余节点用户在画布上拖。 */
function starterGraph() {
  return {
    nodes: [
      { id: 'start', type: 'start', config: { ui: { title: '开始', x: 80, y: 160 } } },
      { id: 'end', type: 'end', config: { ui: { title: '结束', x: 420, y: 160 }, outputs: {} } },
    ],
    edges: [{ from: 'start', to: 'end' }],
  }
}

/**
 * tapflow 列表页的「新建」卡：起名 → 建最小图并**立即发布** → 打开画布。
 * 必须当场发布：列表只显示 published（lib/tapflowLoad.latestCanvasFlows），
 * 存成草稿的话用户关掉窗口就再也找不到自己刚建的画布了。
 * 之后在画布上改图走 draft_from_published 的正常草稿/发布流。
 */
export function TapflowCreateCard({ onCreated }: {
  /** 建好后回调（列表重拉 + 记录窗口 requestId 以便关窗刷新） */
  onCreated: (requestId: string | null) => void
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const create = async () => {
    const title = name.trim()
    if (!title || busy) return
    setBusy(true); setErr('')
    // slug 用时间戳后缀，避免与既有 slug 撞车；名称才是用户认的标识
    const slug = `tap-${Date.now().toString(36)}`
    try {
      const saved = await api.saveWorkflow({
        slug, name: title, description: '',
        input_schema: { project_id: { type: 'int', required: true, seq: 0, label: '项目' } },
        output_schema: {},
        graph: starterGraph(),
        tags: ['canvas', '文本'],
      })
      await api.publishWorkflow(slug, saved.version)
      const requestId = openTapflowWindow({ slug, version: saved.version, variant: 'studio' })
      setEditing(false); setName('')
      onCreated(requestId)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }

  if (!editing) {
    return (
      <button type="button" className="tap-flow-card tap-flow-new" onClick={() => setEditing(true)}>
        <div className="tap-flow-name"><Icon name="plus" /> 新建 tapflow</div>
        <div className="tap-flow-desc">从空白画布开始：起个名字，进画布拖节点、连线、发布。</div>
      </button>
    )
  }
  return (
    <div className="tap-flow-card tap-flow-new editing">
      <div className="tap-flow-name"><Icon name="plus" /> 新建 tapflow</div>
      <input autoFocus value={name} placeholder="画布名称（如：章节梗概生成）"
        onChange={e => setName(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') void create(); if (e.key === 'Escape') setEditing(false) }} />
      {err && <div className="tap-flow-err">{err}</div>}
      <div className="btns">
        <button className="btn primary" onClick={() => void create()} disabled={busy || !name.trim()}>
          <Icon name={busy ? 'spinner' : 'play'} spin={busy} /> 创建并打开
        </button>
        <button className="btn" onClick={() => { setEditing(false); setErr('') }}>取消</button>
      </div>
    </div>
  )
}
