import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import type { ArkCharacter } from '../../api'
import { Icon } from '../../components/Icon'
import { CHAR_CATEGORIES } from '../../lib/charCategories'
import { CharacterEditor } from './CharacterEditor'
import { CharacterGroup } from './CharacterGroup'

/** 独立角色库：形象图单向注册火山虚拟人像库（与知识库分离，不参与召回）。
 * 按 group_name 分组（folder）展示——同一分组=同一逻辑角色的多套图/多形象；空 group_name 归「未分组」。
 * 每组可重命名（批量改本地 group_name，不动火山备案）、可在组内「新建角色」加一套图。 */
export function CharacterLibrary() {
  const [chars, setChars] = useState<ArkCharacter[]>([])
  const [cat, setCat] = useState<string>('all')
  const [editing, setEditing] = useState<Partial<ArkCharacter> | null>(null)
  const timer = useRef<number | null>(null)

  const reload = useCallback(async () => {
    const rows = await api.listArkCharacters()
    setChars(rows)
    return rows
  }, [])
  useEffect(() => { reload() }, [reload])

  // 有「备案中/待入库」的角色时轮询刷新，直到全部落定
  useEffect(() => {
    const pending = chars.some(c => c.ark_status === 'processing' || c.ark_status === 'pending')
    if (pending && timer.current == null) {
      timer.current = window.setInterval(() => { reload() }, 4000)
    } else if (!pending && timer.current != null) {
      clearInterval(timer.current); timer.current = null
    }
    return () => { if (timer.current != null) { clearInterval(timer.current); timer.current = null } }
  }, [chars, reload])

  const save = async (c: Partial<ArkCharacter>) => {
    try {
      if (c.id) await api.updateArkCharacter(c.id, c)
      else await api.createArkCharacter(c)
      setEditing(null); reload()
    } catch (e) { alert((e as Error).message) }
  }
  const del = async (c: ArkCharacter) => {
    if (!confirm(`删除角色「${c.name}」？将一并删除火山侧素材组。`)) return
    try { await api.deleteArkCharacter(c.id); reload() } catch (e) { alert((e as Error).message) }
  }
  const register = async (c: ArkCharacter) => {
    try { await api.registerArkCharacter(c.id); reload() } catch (e) { alert((e as Error).message) }
  }
  const unregister = async (c: ArkCharacter) => {
    if (!confirm(`解除角色「${c.name}」的火山备案？将删除火山侧素材组，本地角色与形象图保留，可稍后再重新入库。`)) return
    try { await api.unregisterArkCharacter(c.id); reload() } catch (e) { alert((e as Error).message) }
  }
  const renameGroup = async (name: string, category: string) => {
    const next = prompt(`把分组「${name}」重命名为（留空=解散该组，条目变独立角色）：`, name)
    if (next == null || next.trim() === name) return
    try { await api.renameArkGroup(category, name, next.trim()); reload() }
    catch (e) { alert((e as Error).message) }
  }

  const shown = cat === 'all' ? chars : chars.filter(c => c.category === cat)
  // 按 group_name 分组：命名组在前（按名排序），未分组('')垫底
  const groups = useMemo(() => {
    const m = new Map<string, ArkCharacter[]>()
    for (const c of shown) {
      const k = c.group_name || ''
      const arr = m.get(k); if (arr) arr.push(c); else m.set(k, [c])
    }
    const named = [...m.keys()].filter(Boolean).sort((a, b) => a.localeCompare(b, 'zh'))
    return [...named, ...(m.has('') ? [''] : [])].map(k => ({ name: k, chars: m.get(k)! }))
  }, [shown])
  const allGroupNames = useMemo(
    () => [...new Set(chars.map(c => c.group_name).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'zh')),
    [chars])

  const active = shown.filter(c => c.ark_status === 'active').length
  const countOf = (k: string) => chars.filter(c => c.category === k).length
  const defaultCat = cat === 'all' ? 'system' : cat
  return (
    <div className="adm-panel">
      <div className="adm-head">
        <h2><Icon name="user" /> 角色库</h2>
        <div className="adm-actions">
          <span className="dim">{shown.length} 套 · {groups.filter(g => g.name).length} 个分组 · {active} 已备案火山 · 形象图单向注册，生视频用 asset:// 引用</span>
          <button className="small" onClick={() => setEditing({ category: defaultCat })}>
            <Icon name="folderplus" /> 新建角色
          </button>
        </div>
      </div>
      <div className="cl-groups">
        <button className={`seg-btn${cat === 'all' ? ' active' : ''}`} onClick={() => setCat('all')}>
          全部（{chars.length}）
        </button>
        {CHAR_CATEGORIES.map(c => (
          <button key={c.key} className={`seg-btn${cat === c.key ? ' active' : ''}`}
            onClick={() => setCat(c.key)}>
            {c.label}（{countOf(c.key)}）
          </button>
        ))}
      </div>
      {editing && (
        <CharacterEditor character={editing} groups={allGroupNames}
          onSave={save} onCancel={() => setEditing(null)} />
      )}
      <div className="cl-body">
        {groups.map(g => (
          <CharacterGroup key={g.name || '__ungrouped__'} name={g.name} chars={g.chars}
            onAddEntry={() => setEditing({ category: g.chars[0]?.category || defaultCat, group_name: g.name })}
            onRename={() => renameGroup(g.name, g.chars[0]?.category || defaultCat)}
            onEdit={setEditing} onDelete={del}
            onRegister={register} onUnregister={unregister} />
        ))}
        {shown.length === 0 && !editing && (
          <div className="dim cl-empty">该分类暂无角色，点右上「新建角色」开始</div>
        )}
      </div>
    </div>
  )
}
