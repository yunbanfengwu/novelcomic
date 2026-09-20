import { useState, type ReactNode } from 'react'
import { Icon } from './Icon'
import { UserConsole } from './console/UserConsole'
import './Shell.css'

// ═══════════ 统一外壳：细图标栏（app 级框架）+ 圆角看板 ═══════════

export type RailKey = 'project' | 'admin'

/**
 * 框架只负责：最左细图标栏（首页 / 控制台 / 系统管理）+ 右侧圆角看板。看板内部（是否要二级
 * 菜单、如何排布）完全交给各页面在 children 里自由决定——二级菜单不属于框架，属于页面内容。
 */
export function Shell({ rail, onHome, onAdmin, children }: {
  rail: RailKey
  onHome: () => void
  onAdmin: () => void
  children: ReactNode
}) {
  const [consoleOpen, setConsoleOpen] = useState(false)
  return (
    <div className="shell">
      <nav className="rail">
        <div className="rail-brand" title="首页" onClick={onHome}><Icon name="home" /></div>
        <div className="rail-mid">
          <button className="rail-btn" title="控制台" onClick={() => setConsoleOpen(true)}><Icon name="console" /></button>
        </div>
        {rail === 'admin'
          ? <button className="rail-btn" title="返回" onClick={onAdmin}><Icon name="back" /></button>
          : <button className="rail-btn" title="系统管理" onClick={onAdmin}><Icon name="gear" /></button>}
      </nav>
      <div className="board">{children}</div>
      <UserConsole open={consoleOpen} onClose={() => setConsoleOpen(false)} />
    </div>
  )
}
