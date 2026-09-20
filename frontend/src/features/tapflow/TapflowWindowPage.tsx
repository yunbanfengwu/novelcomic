import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { latestCanvasFlows } from '../../lib/tapflowLoad'
import { flowKind } from '../../lib/tapflowKind'
import {
  notifyTapflowWindowClosed,
  readTapflowWindowLocation,
  readTapflowWindowState,
  type TapflowWindowPayload,
} from '../../lib/tapflowWindow'
import { TapflowLaunch } from './TapflowLaunch'
import { TapflowModal } from './TapflowModal'
import './tapflow.css'

/** Standalone browser-window host for both studio and production canvases. */
export function TapflowWindowPage() {
  const requestIdRef = useRef<string | null>(null)
  const [payload] = useState<TapflowWindowPayload | null>(() => {
    const params = new URLSearchParams(window.location.search)
    const requestId = params.get('state')
    requestIdRef.current = requestId
    const stored = requestId ? readTapflowWindowState(requestId) : null
    const located = readTapflowWindowLocation(window.location.search)
    // 保存草稿后会原地更新 URL 的 version。刷新时它必须覆盖最初开窗时 localStorage
    // 里的已发布版本，否则明明存到了 v2，页面又会读回 v1。
    return stored && located?.version !== undefined
      ? { ...stored, version: located.version }
      : stored ?? located
  })
  const [flows, setFlows] = useState<{ slug: string; version: number; name: string; kind?: ReturnType<typeof flowKind> }[]>([])
  const closedRef = useRef(false)

  useEffect(() => {
    document.title = payload?.flow?.name ?? 'tapflow'
  }, [payload?.flow?.name])

  useEffect(() => {
    if (!payload || payload.variant !== 'studio') return
    api.listWorkflows()
      .then(ws => setFlows(latestCanvasFlows(ws).map(w => ({
        slug: w.slug, version: w.version, name: w.name, kind: flowKind(w.tags),
      }))))
      .catch(() => setFlows([]))
  }, [payload])

  const close = useCallback(() => {
    if (closedRef.current) return
    closedRef.current = true
    if (requestIdRef.current) notifyTapflowWindowClosed(requestIdRef.current)
    window.close()
  }, [])

  const rememberVersion = useCallback((version: number) => {
    const url = new URL(window.location.href)
    url.searchParams.set('version', String(version))
    window.history.replaceState(window.history.state, '', url)
  }, [])

  // Native window close has no React callback, so notify the owner before unload.
  useEffect(() => {
    const onBeforeUnload = () => {
      if (closedRef.current) return
      closedRef.current = true
      if (requestIdRef.current) notifyTapflowWindowClosed(requestIdRef.current)
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [])

  if (!payload) {
    return (
      <div className="tap-window-error">
        <p>无法加载 tapflow 画布。</p>
        <button type="button" onClick={close}>关闭窗口</button>
      </div>
    )
  }

  if (payload.flow) {
    return <TapflowModal flow={payload.flow} flows={flows} variant="studio" onClose={close} />
  }

  if (!payload.slug) {
    return (
      <div className="tap-window-error">
        <p>tapflow 参数不完整。</p>
        <button type="button" onClick={close}>关闭窗口</button>
      </div>
    )
  }

  return (
    <TapflowLaunch slug={payload.slug} version={payload.version} variant={payload.variant}
      inputs={payload.inputs ?? {}} subject={payload.subject} productUrl={payload.productUrl}
      flows={flows} onVersionChange={rememberVersion} onClose={close} />
  )
}
