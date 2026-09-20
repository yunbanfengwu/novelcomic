import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from './Icon'
import { UserConsole } from './console/UserConsole'
import './Shell.css'

/**
 * 统一「细图标栏 + 圆角看板」布局（与系统管理同款）。
 * 图标栏：顶部 logo（→首页）、中间插槽（各页面自填 icon 菜单）、底部控制台 + 系统管理。
 * 右侧看板为圆角卡片、四周留白；内容是否滚动由各分区自行决定。
 */
export function SidebarLayout({ sidebar, children }: { sidebar: ReactNode; children: ReactNode }) {
  const navigate = useNavigate()
  const [consoleOpen, setConsoleOpen] = useState(false)
  return (
    <div className="shell">
      <nav className="rail">
        <div className="rail-brand" title="首页" onClick={() => navigate('/')}><Icon name="home" /></div>
        <div className="rail-mid">
          {sidebar}
          <button className="rail-btn" title="控制台" onClick={() => setConsoleOpen(true)}><Icon name="console" /></button>
        </div>
        <button className="rail-btn" title="系统管理" onClick={() => navigate('/admin')}><Icon name="gear" /></button>
      </nav>
      <div className="board">{children}</div>
      <UserConsole open={consoleOpen} onClose={() => setConsoleOpen(false)} />
    </div>
  )
}
