import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { ArkCharacter, Element } from '../../api'
import { Icon } from '../../components/Icon'
import { arkBodyFromElement, sameChar } from '../../lib/arkChar'

/** 把「作品产出的角色」推进火山虚拟人像库：以角色设定图为形象图新建 category='work' 的角色库条目，
 * 后端建条即自动单向注册火山（CreateAssetGroup→CreateAsset→轮询 Active）。此处只做提交入口与状态回显：
 * 未出设定图不可提交；已提交则显示入库状态并在 pending/processing 时轮询刷新，失败可重试。 */
const STATUS: Record<ArkCharacter['ark_status'], { label: string; cls: string }> = {
  pending: { label: '待入库', cls: 'st-pending' },
  processing: { label: '备案中', cls: 'st-processing' },
  active: { label: '已入库', cls: 'st-active' },
  failed: { label: '入库失败', cls: 'st-failed' },
}

export function ArkLibraryButton({ pid, el }: { pid: number; el: Element }) {
  const [row, setRow] = useState<ArkCharacter | null>(null)
  const [busy, setBusy] = useState(false)
  const sheet = el.meta.sheet_url
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const refresh = useCallback(async () => {
    try {
      const rows = await api.listArkCharacters(pid)
      setRow(rows.find(r => sameChar(r.name, el.name)) ?? null)
    } catch { /* 静默：入库状态非关键路径 */ }
  }, [pid, el.name])

  useEffect(() => { refresh() }, [refresh])

  // pending/processing 时轮询到终态（active/failed）
  useEffect(() => {
    clearTimeout(timer.current)
    if (row && (row.ark_status === 'pending' || row.ark_status === 'processing'))
      timer.current = setTimeout(refresh, 5000)
    return () => clearTimeout(timer.current)
  }, [row, refresh])

  const submit = async () => {
    setBusy(true)
    try {
      await api.createArkCharacter(arkBodyFromElement(pid, el))
      await refresh()
    } catch (e) { alert(String((e as Error).message || e)) } finally { setBusy(false) }
  }

  const retry = async () => {
    if (!row) return
    setBusy(true)
    try { await api.registerArkCharacter(row.id); await refresh() }
    catch (e) { alert(String((e as Error).message || e)) } finally { setBusy(false) }
  }

  const unregister = async () => {
    if (!row || !confirm(`解除角色「${row.name}」的火山备案？将删除火山侧素材组，可稍后重新提交。`)) return
    setBusy(true)
    try { await api.unregisterArkCharacter(row.id); await refresh() }
    catch (e) { alert(String((e as Error).message || e)) } finally { setBusy(false) }
  }

  if (row) {
    const st = STATUS[row.ark_status] || STATUS.pending
    const canUnreg = (row.ark_status === 'active' || row.ark_status === 'processing') && !!row.ark_group_id
    return (
      <span className="ark-lib">
        <span className={`tag ark-badge ${st.cls}`} title={row.ark_error || '火山虚拟人像库入库状态'}>
          {(row.ark_status === 'processing' || row.ark_status === 'pending')
            ? <Icon name="spinner" spin /> : row.ark_status === 'active'
              ? <Icon name="check" /> : <Icon name="warn" />} 火山·{st.label}
        </span>
        {row.ark_status === 'failed' && (
          <button className="small" disabled={busy} onClick={retry} title={row.ark_error}>
            {busy ? <Icon name="spinner" spin /> : <Icon name="refresh" />} 重试
          </button>
        )}
        {canUnreg && (
          <button className="small" disabled={busy} onClick={unregister}
            title="删除火山侧素材组、状态退回待入库；本地角色与设定图保留">
            {busy ? <Icon name="spinner" spin /> : <Icon name="unlink" />} 解除
          </button>
        )}
      </span>
    )
  }

  return (
    <button className="small" disabled={busy || !sheet} onClick={submit}
      title={sheet ? '以角色设定图为形象图，提交到火山虚拟人像库（自动入库）' : '先生成角色设定图，再提交入库'}>
      {busy ? <Icon name="spinner" spin /> : <Icon name="upload" />} 加入火山角色库
    </button>
  )
}
