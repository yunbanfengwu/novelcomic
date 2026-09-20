import { useState } from 'react'
import type { Memory } from '../../api'
import { Icon, type IconName } from '../../components/Icon'

/**
 * 数字员工卡：头像/名称/角色 + 职责描述 + 自带偏好编辑器（输入 + ＋记住 + 本卡偏好列表）。
 * 卡内设置的偏好只属于这张卡（总导演=全局；专职员工=对自己生效），无需选择下拉框。
 */
export function EmployeeCard({ icon, name, role, desc, memories, placeholder, chief, onAdd }: {
  icon: IconName
  name: string
  role: string
  desc: string
  memories: Memory[]
  placeholder?: string
  chief?: boolean
  onAdd: (text: string) => Promise<void>
}) {
  const [text, setText] = useState('')
  const add = async () => {
    const t = text.trim()
    if (!t) return
    await onAdd(t); setText('')
  }

  return (
    <div className={`emp-card${chief ? ' emp-card-chief' : ''}`}>
      <div className="emp-head">
        <span className="emp-ava"><Icon name={icon} /></span>
        <div className="emp-id">
          <div className="emp-name">{name}</div>
          <div className="emp-role dim">{role}</div>
        </div>
      </div>
      <div className="emp-charter">{desc}</div>
      <div className="emp-prefs">
        <div className="inline">
          <input value={text} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') add() }}
            placeholder={placeholder ?? '设置偏好…'} />
          <button className="small" onClick={add}>＋记住</button>
        </div>
        {memories.map(m => <div key={m.id} className="memory-item">{m.content}</div>)}
      </div>
    </div>
  )
}
