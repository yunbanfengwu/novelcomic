import { useEffect, useState } from 'react'
import { api } from '../../../api'
import type { Memory, Project } from '../../../api'
import { Icon } from '../../../components/Icon'
import { SubNav } from '../../../components/SubNav'
import { InfoPane } from '../InfoPane'
import { ProjectEditDrawer } from '../ProjectEditDrawer'
import { EmployeesPane } from '../EmployeesPane'

type OverviewTab = 'info' | 'employees'

/**
 * 总览分区：左右布局——左侧二级菜单（基本信息 / 数字员工），右侧对应内容。
 * 数字员工=员工卡片；其中「总导演」卡即项目级偏好（抽象卡，非特定员工），承载数字员工记忆编辑。
 * 参考资料已挪入「素材库」分区（核心要素左栏入口）。
 */
export function OverviewSection({ id, p, setP, memories, onMemoriesChange }: {
  id: number
  p: Project
  setP: (p: Project) => void
  memories: Memory[]
  onMemoriesChange: () => void
}) {
  const [tab, setTab] = useState<OverviewTab>('info')
  const [editing, setEditing] = useState(false)

  // 渐进式引导：进入总览发现尚无架构大纲 → 自动补发后台任务链（基本信息初拟→大纲；
  // 服务端幂等去重，重复进入/StrictMode 双跑不会重复入队）。任务失败不自动重发（依赖不变），
  // 用户可在大纲区手动重新生成
  useEffect(() => {
    if (!p.outline_md) api.ensureProjectInfo(id).catch(console.error)
  }, [id, p.outline_md])

  const setAspect = async (r: '16:9' | '9:16') => {
    await api.updateConfig(id, { aspect_ratio: r })
    setP({ ...p, config: { ...p.config, aspect_ratio: r } })
  }
  const setRealistic = async (v: 'enable' | 'disable' | 'follow') => {
    const character_mode = v === 'enable' ? 'real' : 'virtual'
    await api.updateConfig(id, { realistic_character: v, character_mode })
    setP({ ...p, config: { ...p.config, realistic_character: v, character_mode } })
  }
  // 新增偏好：总导演→agentCode 为空（全局）；专职员工→其 code（只对自己生效）
  const addMemory = async (agentCode: string | undefined, text: string) => {
    await api.addMemory(id, text, agentCode)
    onMemoriesChange()
  }

  return (
    <div className="overview-split">
      <SubNav
        items={[
          { key: 'info', icon: <Icon name="clipboard" />, label: '基本信息' },
          { key: 'employees', icon: <Icon name="robot" />, label: '数字员工' },
        ]}
        active={tab} onSelect={k => setTab(k as OverviewTab)} />
      <div className="overview-pane">
        {tab === 'info' ? (
          <InfoPane p={p} onAspectChange={setAspect} onRealisticChange={setRealistic} onEdit={() => setEditing(true)}
            onTagsChange={async tags => {
              await api.updateConfig(id, { tags })
              setP({ ...p, config: { ...p.config, tags } })
              api.getProject(id).then(setP).catch(() => {})
            }}
            onCoverChange={url => setP({ ...p, config: { ...p.config, cover_url: url } })}
            onTrailerChange={url => setP({ ...p, config: { ...p.config, trailer_url: url } })}
            onOutlineChange={md => setP({ ...p, outline_md: md })} />
        ) : (
          <EmployeesPane
            employees={p.employees}
            memories={memories} onAddMemory={addMemory} />
        )}
      </div>
      {editing && (
        <ProjectEditDrawer p={p}
          onSaved={np => { setP(np); setEditing(false) }}
          onClose={() => setEditing(false)} />
      )}
    </div>
  )
}
