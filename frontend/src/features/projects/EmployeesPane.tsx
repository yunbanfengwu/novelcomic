import type { Memory, Project } from '../../api'
import type { IconName } from '../../components/Icon'
import { EmployeeCard } from './EmployeeCard'

/** 员工 code → 头像图标（缺省 robot） */
const EMP_ICON: Record<string, IconName> = {
  writer: 'pen', director: 'clapper', artist: 'palette', voice: 'mic',
}

const CHIEF_DESC = '总导演即项目级偏好：把控整体创作方向、统一各员工风格；在此设置的偏好默认对全体数字员工生效。'

/**
 * 数字员工分区：总导演卡（居首，偏好=全局生效）+ 各专职员工卡（偏好=对自己生效）。
 * 每张卡自带偏好编辑器、只显示属于自己的偏好，无需下拉选择目标。
 */
export function EmployeesPane({ employees, memories, onAddMemory }: {
  employees: Project['employees']
  memories: Memory[]
  onAddMemory: (agentCode: string | undefined, text: string) => Promise<void>
}) {
  return (
    <div className="emp-grid">
      {/* 总导演 = 项目级偏好（agent_code 为空=全员生效） */}
      <EmployeeCard chief icon="compass" name="总导演" role="项目级偏好 · 对全体数字员工生效"
        desc={CHIEF_DESC}
        placeholder="设置全局偏好，如：整体走冷色调、克制煽情"
        memories={memories.filter(m => !m.agent_code)}
        onAdd={t => onAddMemory(undefined, t)} />
      {/* 各专职员工：偏好只对自己生效（agent_code=该员工 code） */}
      {employees?.map(e => (
        <EmployeeCard key={e.code} icon={EMP_ICON[e.code] ?? 'robot'} name={e.name} role={e.role}
          desc={e.charter}
          placeholder={`设置对${e.name}的偏好，如：用莫言的语言写`}
          memories={memories.filter(m => m.agent_code === e.code)}
          onAdd={t => onAddMemory(e.code, t)} />
      ))}
    </div>
  )
}
