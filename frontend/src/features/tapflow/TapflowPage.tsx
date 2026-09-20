import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type WorkflowSummary } from '../../api'
import { Icon } from '../../components/Icon'
import { TAPFLOWS } from '../../lib/tapflowData'
import { latestCanvasFlows } from '../../lib/tapflowLoad'
import { flowKind, TAP_FLOW_KIND_LABEL } from '../../lib/tapflowKind'
import { TapflowCreateCard } from './TapflowCreateCard'
import { isTapflowWindowClosedMessage, openTapflowWindow } from '../../lib/tapflowWindow'
import './tapflow.css'

/** Workflow list for the admin area. Each canvas opens in its own browser window. */
export function TapflowPage() {
  const [real, setReal] = useState<WorkflowSummary[]>([])
  const windowRequests = useRef(new Set<string>())

  const reload = useCallback(() => {
    api.listWorkflows()
      .then(ws => setReal(latestCanvasFlows(ws)))
      .catch(() => setReal([]))
  }, [])
  useEffect(() => { reload() }, [reload])

  useEffect(() => {
    const onWindowMessage = (event: MessageEvent) => {
      const requestId = [...windowRequests.current]
        .find(id => isTapflowWindowClosedMessage(event, id))
      if (!requestId) return
      windowRequests.current.delete(requestId)
      reload()
    }
    window.addEventListener('message', onWindowMessage)
    return () => window.removeEventListener('message', onWindowMessage)
  }, [reload])

  const openReal = (flow: WorkflowSummary) => {
    const requestId = openTapflowWindow({ slug: flow.slug, version: flow.version, variant: 'studio' })
    if (requestId) windowRequests.current.add(requestId)
  }

  const openDemo = (flow: typeof TAPFLOWS[number]) => {
    const requestId = openTapflowWindow({ flow, variant: 'studio' })
    if (requestId) windowRequests.current.add(requestId)
  }

  const card = (key: string, name: string, desc: string, meta: React.ReactNode,
                onClick: () => void, demo = false) => (
    <button key={key} type="button" className="tap-flow-card" onClick={onClick}>
      <div className="tap-flow-name">
        <Icon name="layers" /> {name}
        {demo && <span className="tap-flow-demo">演示</span>}
      </div>
      <div className="tap-flow-desc">{desc}</div>
      <div className="tap-flow-meta">{meta}</div>
    </button>
  )

  return (
    <div className="tap-flow-list">
      <div className="tap-flow-grid">
        <TapflowCreateCard onCreated={requestId => {
          if (requestId) windowRequests.current.add(requestId)
          reload()
        }} />
        {real.map(flow => card(flow.slug, flow.name, flow.description, (
          <>
            <span>{TAP_FLOW_KIND_LABEL[flowKind(flow.tags)]}</span>
            {/* 被别的画布引用时可炸开输入提示词，由规划模型决定重跑子图哪几步 */}
            {flow.smart_call && <span>智能节点</span>}
            <span>v{flow.version}</span>
            <span>真实运行</span>
            <span className="time">{(flow.updated_at ?? '').slice(0, 16).replace('T', ' ')}</span>
          </>
        ), () => openReal(flow)))}
        {TAPFLOWS.map(flow => card(flow.id, flow.name, flow.desc, (
          <>
            <span>{flow.data.nodes.length} 节点</span>
            <span>{flow.data.edges.length} 连线</span>
            <span className="time">{flow.updated}</span>
          </>
        ), () => openDemo(flow), true))}
      </div>
    </div>
  )
}
