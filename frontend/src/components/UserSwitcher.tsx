import { useEffect, useRef, useState } from 'react'
import { api, getCurrentUserId, setCurrentUserId } from '../api'
import type { SysUser } from '../api'
import './UserSwitcher.css'

// ═══════════ 开发期用户切换（2026-09-17）═══════════
//
// 注册/登录未接入（开发阶段不挡 AI 流水线）：身份 = X-User-Id 头（api.ts 统一带），
// 后端按它判定数据归属（app/users.py current_user）。这里提供首页下拉：
// 点选用户 → setCurrentUserId 落 localStorage → 整页刷新，首页列表即按归属过滤。
// 接真登录时删掉本组件、api.ts 的身份头换成 Bearer 即可，业务代码不动。

export function UserSwitcher() {
  const [users, setUsers] = useState<SysUser[]>([])
  const [open, setOpen] = useState(false)
  const [err, setErr] = useState('')
  const boxRef = useRef<HTMLDivElement>(null)
  const currentId = getCurrentUserId()
  const current = users.find(u => u.id === currentId)

  useEffect(() => {
    api.listUsers().then(setUsers).catch(e => setErr((e as Error).message))
  }, [])

  // 点击组件外任意处收起下拉
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const pick = (u: SysUser) => {
    setOpen(false)
    if (u.id === currentId) return
    setCurrentUserId(u.id)
    location.reload() // 整页刷新：所有已加载页面数据按新身份重新拉取
  }

  return (
    <div className="usw" ref={boxRef}>
      <button className="sys-btn" onClick={() => setOpen(v => !v)} title="切换用户（开发期调试）">
        <span className={'usw-dot' + (current?.role === 'admin' ? ' usw-admin' : '')} />
        <span>{current ? current.name : currentId}</span>
        <span className="usw-caret">▾</span>
      </button>
      {open && (
        <div className="usw-menu">
          {err && <div className="usw-err">{err}</div>}
          {users.filter(u => u.enabled).map(u => (
            <button key={u.id} className={'usw-item' + (u.id === currentId ? ' usw-cur' : '')}
              onClick={() => pick(u)}>
              <span className={'usw-dot' + (u.role === 'admin' ? ' usw-admin' : '')} />
              <span className="usw-name">{u.name}</span>
              <span className="usw-id">{u.id}</span>
              {u.id === currentId && <span className="usw-check">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
