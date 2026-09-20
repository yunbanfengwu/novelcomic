import { useState } from 'react'
import { Modal } from '../Modal'
import { Icon } from '../Icon'
import type { IconName } from '../Icon'
import { RecycleBin } from './RecycleBin'
import { ConsolePlaceholder } from './ConsolePlaceholder'
import './console.css'

// ═══════════ 用户控制台：弹窗 · 左右结构（左菜单 + 右内容） ═══════════

type Tab = 'account' | 'recharge' | 'trash'
const MENU: { key: Tab; icon: IconName; label: string }[] = [
  { key: 'account', icon: 'idcard', label: '用户信息' },
  { key: 'recharge', icon: 'wallet', label: '充值管理' },
  { key: 'trash', icon: 'trash', label: '回收站' },
]

/**
 * 控制台弹窗容器：左菜单切换、右内容分发。用户信息/充值管理暂为占位（菜单已就位待开发），
 * 回收站为可用功能。onProjectsChanged：回收站恢复/彻底删除后回调，供首页刷新项目列表。
 */
export function UserConsole({ open, onClose, onProjectsChanged }: {
  open: boolean; onClose: () => void; onProjectsChanged?: () => void
}) {
  const [tab, setTab] = useState<Tab>('account')
  return (
    <Modal open={open} onClose={onClose} title="控制台" wide>
      <div className="console-body">
        <nav className="console-nav">
          {MENU.map(m => (
            <button key={m.key} className={`console-nav-item${tab === m.key ? ' active' : ''}`}
              onClick={() => setTab(m.key)}>
              <Icon name={m.icon} /><span>{m.label}</span>
            </button>
          ))}
        </nav>
        <div className="console-panel">
          {tab === 'account' && <ConsolePlaceholder icon="idcard" title="用户信息管理" />}
          {tab === 'recharge' && <ConsolePlaceholder icon="wallet" title="充值管理" />}
          {tab === 'trash' && <RecycleBin onChanged={onProjectsChanged} />}
        </div>
      </div>
    </Modal>
  )
}
