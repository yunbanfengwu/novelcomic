import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api'
import type { KbEntry, KbFolder } from '../../api'
import { Icon, type IconName } from '../../components/Icon'
import { KbEntryEditor } from './KbEntryEditor'

const CAT_META: Record<string, { icon: IconName; label: string }> = {
  camera: { icon: 'camera', label: '镜头语言' }, angle: { icon: 'compass', label: '机位角度' },
  lens: { icon: 'video', label: '焦段感' }, lighting: { icon: 'sparkles', label: '光效' },
  camera_move: { icon: 'video', label: '运镜' }, motion: { icon: 'motion', label: '肢体动作' },
  pace: { icon: 'clapper', label: '节奏' }, style: { icon: 'palette', label: '视觉风格' },
  sheet: { icon: 'clipboard', label: '设定图版式' }, quality: { icon: 'sparkles', label: '质量词' },
  writing_style: { icon: 'pen', label: '文风' }, persona: { icon: 'user', label: '人物特征' },
  // 技能 tab：category=agent_code，按数字员工分组
  writer: { icon: 'pen', label: '写作员工' }, artist: { icon: 'palette', label: '绘画员工' },
  director: { icon: 'clapper', label: '导演员工' }, voice: { icon: 'mic', label: '配音员工' },
}
const catLabel = (c: string) => CAT_META[c]?.label || c
const catIcon = (c: string): IconName => CAT_META[c]?.icon || 'folder'

/** 左菜单+右内容布局：左侧分类菜单（含计数），右侧当前分类的条目列表 + 新增/编辑。
 * 按知识库文件夹（folder）或直接按 kind（如技能 tab）查询。
 * actionsEl：文件夹 header 挂载点——「新增条目」提升到标题同一行（无挂载点时就地渲染）。 */
export function KbEntryPanel({ folder, kind, onCountChanged, actionsEl }: {
  folder?: KbFolder
  kind?: string
  onCountChanged?: () => void
  actionsEl?: HTMLElement | null
}) {
  const [entries, setEntries] = useState<KbEntry[]>([])
  const [cat, setCat] = useState<string | null>(null)
  const [editing, setEditing] = useState<Partial<KbEntry> | null>(null)

  const reload = useCallback(() => {
    api.listKb(folder ? { folder_id: folder.id } : { kind }).then(setEntries)
  }, [folder, kind])
  useEffect(() => { reload() }, [reload])

  const cats = [...new Set(entries.map(e => e.category || '未分类'))]
  const active = cat && cats.includes(cat) ? cat : (cats[0] ?? null)
  const shown = entries.filter(e => (e.category || '未分类') === active)

  const blank = (): Partial<KbEntry> => ({
    scope: 'global', kind: folder?.kind || kind || 'knowledge',
    category: folder?.category ?? (active === '未分类' ? null : active),
    name: '', title: '', description: '', content: '', tags: [], meta: {},
    folder_id: folder && !folder.system ? folder.id : null, enabled: true,
  })
  const save = async (e: Partial<KbEntry>) => {
    if (!e.name?.trim()) { alert('名称必填'); return }
    try {
      if (e.id) await api.updateKb(e.id, e)
      else await api.createKb(e)
      setEditing(null); reload(); onCountChanged?.()
    } catch (err) { alert(String(err)) }
  }
  const remove = async (id: number) => {
    if (!confirm('确认删除该条目？')) return
    await api.deleteKb(id); reload(); onCountChanged?.()
  }

  return (
    <div className="kb-cat-layout">
      <nav className="kb-cat-menu">
        {cats.map(c => (
          <div key={c} className={`kb-cat-item${c === active ? ' active' : ''}`} onClick={() => setCat(c)}>
            <Icon name={catIcon(c)} />
            <span className="kb-cat-label">{catLabel(c)}</span>
            <span className="kb-cat-count">{entries.filter(e => (e.category || '未分类') === c).length}</span>
          </div>
        ))}
        {!cats.length && <div className="dim">（空）</div>}
      </nav>
      <div className="kb-cat-content">
        {(() => {
          const toolbar = (
            <div className="btns kbv-toolbar">
              <button onClick={() => setEditing(blank())}>＋新增条目</button>
            </div>
          )
          return actionsEl ? createPortal(toolbar, actionsEl) : toolbar
        })()}
        {editing && <KbEntryEditor key={editing.id ?? 'new'} entry={editing}
          onSave={save} onCancel={() => setEditing(null)} />}
        <div className="card">
          {shown.map(e => (
            <div key={e.id} className="kb-row">
              {e.thumbnail_url && <img className="kb-thumb" src={e.thumbnail_url} alt={e.name} />}
              <div className="kb-row-main">
                <b>{e.title || e.name}</b>
                {e.title && e.title !== e.name && <span className="dim"> {e.name}</span>}
                <span className="dim"> {e.description}</span>
                {e.meta.positive && <div className="prompt-box">{e.meta.positive}</div>}
                {typeof e.meta.sample_audio_url === 'string' && e.meta.sample_audio_url && (
                  <audio controls preload="none" src={e.meta.sample_audio_url} className="kb-audio" />
                )}
                {!!e.meta.attachments?.length && (
                  <div className="kb-atts-line">
                    {e.meta.attachments.map((a, i) => (
                      <a key={i} className="tag" href={a.url} target="_blank" rel="noreferrer">
                        <Icon name="clip" /> {a.title || `附件${i + 1}`}
                      </a>
                    ))}
                  </div>
                )}
              </div>
              <div className="btns">
                <button className="small ghost" onClick={() => setEditing(e)}>编辑</button>
                <button className="small ghost" onClick={() => remove(e.id)}>删除</button>
              </div>
            </div>
          ))}
          {!shown.length && <div className="dim">该分类暂无条目，点击"＋新增条目"添加。</div>}
        </div>
      </div>
    </div>
  )
}
