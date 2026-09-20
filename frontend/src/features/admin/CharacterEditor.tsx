import { useState } from 'react'
import { api } from '../../api'
import type { ArkCharacter } from '../../api'
import { Icon } from '../../components/Icon'
import { Modal } from '../../components/Modal'
import { CHAR_CATEGORIES } from '../../lib/charCategories'

const GENDERS = [['neutral', '中性'], ['male', '男'], ['female', '女'], ['child', '孩童'], ['creature', '非人']]
const AGES = [['adult', '成年'], ['young', '青年'], ['child', '孩童'], ['middle', '中年'], ['elder', '老年'], ['none', '不限']]

/** 角色新建/编辑表单：名称/分组/描述/性别/年龄/标签 + 形象图（上传或 AI 生成）。
 * 分组=同一逻辑角色的多套图 folder；groups 提供已有分组名做输入联想。 */
export function CharacterEditor({ character, onSave, onCancel, groups = [] }: {
  character: Partial<ArkCharacter>
  onSave: (c: Partial<ArkCharacter>) => void
  onCancel: () => void
  groups?: string[]
}) {
  const [c, setC] = useState<Partial<ArkCharacter>>({
    category: 'system', gender: 'neutral', age: 'adult', tags: [], ...character,
  })
  const [busy, setBusy] = useState<'' | 'upload' | 'gen'>('')
  const set = (p: Partial<ArkCharacter>) => setC(prev => ({ ...prev, ...p }))

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy('upload')
    try { const { url } = await api.uploadCharacterImage(file); set({ image_url: url }) }
    catch (err) { alert((err as Error).message) }
    finally { setBusy(''); e.target.value = '' }
  }
  const onGenerate = async () => {
    const prompt = (c.description || '').trim()
    if (!prompt) { alert('先填「形象描述」，作为生成提示词'); return }
    setBusy('gen')
    try { const { url } = await api.generateCharacterImage(prompt); set({ image_url: url }) }
    catch (err) { alert((err as Error).message) }
    finally { setBusy('') }
  }
  const submit = () => {
    if (!(c.name || '').trim()) { alert('角色名必填'); return }
    onSave(c)
  }
  const title = character.id ? '编辑角色'
    : character.group_name ? `在「${character.group_name}」分组新建角色`
    : '新建角色'

  return (
    <Modal open onClose={onCancel} wide title={title} closeOnBackdrop={!busy}>
      <div className="char-edit-grid">
        <div className="char-edit-fields">
          <div className="char-edit-row">
            <label>角色名<input value={c.name || ''} onChange={e => set({ name: e.target.value })} placeholder="如：冷面女将军·戎装" /></label>
            <label>分组（同一角色的多套图归一组，可留空）
              <input list="char-group-list" value={c.group_name || ''}
                onChange={e => set({ group_name: e.target.value })} placeholder="如：冷面女将军" />
              <datalist id="char-group-list">{groups.map(g => <option key={g} value={g} />)}</datalist>
            </label>
          </div>
          <label>形象描述（也用作 AI 生成提示词）
            <textarea value={c.description || ''} rows={4}
              onChange={e => set({ description: e.target.value })}
              placeholder="外貌、发型、服装、气质…越具体越稳" />
          </label>
          <label>分类<select value={c.category} onChange={e => set({ category: e.target.value })}>
            {CHAR_CATEGORIES.map(cat => <option key={cat.key} value={cat.key}>{cat.label}</option>)}</select></label>
          <div className="char-edit-row">
            <label>性别<select value={c.gender} onChange={e => set({ gender: e.target.value })}>
              {GENDERS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>
            <label>年龄<select value={c.age} onChange={e => set({ age: e.target.value })}>
              {AGES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>
          </div>
          <label>标签（逗号分隔）
            <input value={(c.tags || []).join(',')}
              onChange={e => set({ tags: e.target.value.split(/[，,]/).map(s => s.trim()).filter(Boolean) })}
              placeholder="威严, 帝王, 反派" />
          </label>
          <div className="char-edit-row">
            <label>归属用户（暂可空）
              <input value={c.owner_user || ''} onChange={e => set({ owner_user: e.target.value })}
                placeholder="暂无用户系统，可留空" />
            </label>
            <label>来源作品
              <input value={c.source_work || ''} onChange={e => set({ source_work: e.target.value })}
                placeholder="由哪个作品产出（可留空）" />
            </label>
          </div>
        </div>
        <div className="char-edit-image">
          <div className="char-img-preview">
            {c.image_url
              ? <img src={c.image_url} alt="形象图" />
              : <div className="char-img-empty"><Icon name="user" /><span>暂无形象图</span></div>}
          </div>
          <div className="btns">
            <label className="small btn-like">
              <Icon name={busy === 'upload' ? 'spinner' : 'image'} spin={busy === 'upload'} /> 上传形象图
              <input type="file" accept="image/*" hidden onChange={onUpload} disabled={!!busy} />
            </label>
            <button className="small" onClick={onGenerate} disabled={!!busy}>
              <Icon name={busy === 'gen' ? 'spinner' : 'wand'} spin={busy === 'gen'} /> AI 生成
            </button>
          </div>
          <p className="dim char-hint">火山推荐竖版人像：全身正面或正面无表情特写</p>
        </div>
      </div>
      <div className="btns char-edit-actions">
        <button className="primary" onClick={submit} disabled={!!busy}>保存并入库</button>
        <button className="ghost" onClick={onCancel}>取消</button>
      </div>
    </Modal>
  )
}
