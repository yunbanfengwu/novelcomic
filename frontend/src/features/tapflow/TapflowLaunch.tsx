import { useCallback, useEffect, useState } from 'react'
import type { WorkflowSubject } from '../../api'
import { Icon } from '../../components/Icon'
import type { TapFlowMeta } from '../../lib/tapflowData'
import type { TapFlowKind } from '../../lib/tapflowKind'
import { loadSubjectTapflow, loadTapflow } from '../../lib/tapflowLoad'
import { TapflowModal } from './TapflowModal'

/**
 * 业务页里打开一条 tapflow 的**生产态**画布（如素材库点场景 →「生成场景设定图」）。
 *
 * 与系统管理里那张画布是**同一个组件**，只是走 variant="production"：
 * 入参按业务上下文填好、不给编排能力。跨业务域引用一个入口件，
 * 与 ElementPreview 引 voice/VoiceBlock 同一先例。
 *
 * 带 subject 时是「这个对象的专属画布」：
 * 打开先找它自己那份（有就打开实例，没有才打开模板），画布上一改结构就 fork 并自动保存。
 * 本组件持有 flow —— fork 之后 slug 变了，**运行也得跟着换**，否则改动存进了副本，
 * 跑的还是模板那张图。
 */
export function TapflowLaunch({ slug, version, inputs, subject, productUrl,
                                variant = 'production', flows = [],
                                onVersionChange, onClose }: {
  slug: string
  /** 精确打开的版本；编排台保存草稿后用它跨刷新继续编辑该草稿。 */
  version?: number
  /** 入参预填，键即 input_schema 的键（如 project_id / scene_name） */
  inputs: Record<string, string | number>
  /** 画布归属对象（如素材库那个场景要素）：给了它才有「专属画布」这一层 */
  subject?: WorkflowSubject
  /** 入口业务对象的当前产物（如项目现有封面）：归宿挂载点进画布就回显它，不用等运行 */
  productUrl?: string
  /** Production is the embedded business flow; studio is used by the standalone admin window. */
  variant?: 'studio' | 'production'
  flows?: { slug: string; version: number; name: string; kind?: TapFlowKind }[]
  onVersionChange?: (version: number) => void
  /** 关闭回调：业务页在这里重新拉数据——流程跑完产物已落库，列表要跟着变 */
  onClose: () => void
}) {
  const [flow, setFlow] = useState<TapFlowMeta | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const subjectKind = subject?.kind
  const subjectId = subject?.id
  const subjectName = subject?.name
  const subjectRole = subject?.canvasRole

  useEffect(() => {
    let alive = true
    const load = subjectKind && subjectId !== undefined
      ? loadSubjectTapflow(slug, { kind: subjectKind, id: subjectId, name: subjectName,
        canvasRole: subjectRole })
      : loadTapflow(slug, version)
    load
      .then(f => { if (alive) setFlow(f) })
      .catch(e => { if (alive) setErr(String(e)) })
    return () => { alive = false }
  }, [slug, version, subjectKind, subjectId, subjectName, subjectRole])

  // fork 出实例后换 slug/version：运行、预检、「上次运行」全部跟着落到副本上。
  // 只换元信息，不碰画布节点——那份状态在 Modal 里，重置它等于把用户刚拖的节点抹掉
  const onFlow = useCallback((f: TapFlowMeta) => {
    setFlow(f)
    if (f.version !== undefined) onVersionChange?.(f.version)
  }, [onVersionChange])

  if (err) {
    return (
      <div className="tap-launch-err">
        <Icon name="alert" /> 打不开生成流程「{slug}」：{err}
        <button type="button" onClick={onClose}>关闭</button>
      </div>
    )
  }
  if (!flow) return null      // 加载很快（一次 GET），不闪加载态
  return (
    <TapflowModal flow={flow} variant={variant} initialInputs={inputs}
      subject={subject} productUrl={productUrl} flows={flows} onFlow={onFlow} onClose={onClose} />
  )
}
