import { useState } from 'react'
import { Icon } from '../../components/Icon'
import { Switch } from '../../components/Switch'
import {
  TAP_NO_VOLUME, ctxOptions, type TapCtxKey, type TapNode, type TapParam,
} from '../../lib/tapflowData'
import { TapflowFixedParamCard } from './TapflowFixedParamCard'

/** 执行 tab 的 body（合并面板的「执行」tab 内容）：固定参数卡 + 实际参数 + 执行卡。
 * 原独立面板的「日志」tab 已删除——运行日志改由公共对话面板（ChatDock「对话」tab）
 * 以运行折叠卡承载；跑起来的进度看画布节点状态与对话流。
 * real=真实流程：ctx 候选走 optionsFor（真实项目/场景），free 类参数可手填新名；
 * 整图执行不支持截段，运行范围行隐藏。 */
export function TapflowRunBody({
  start, nodes, range, running, workflowSlug, workflowVersion, optionsFor, forceAll, hint,
  onParam, onParams, onRange, onForceAll, onRun,
}: {
  /** 画布上的开始节点（含 params 当前值）；无开始节点时只读提示 */
  start: TapNode | null
  /** 全部节点：给运行范围下拉列选项 */
  nodes: TapNode[]
  /** null = 用流程默认端点（起点 / 终点） */
  range: { from: string | null; to: string | null }
  running: boolean
  workflowSlug?: string
  workflowVersion?: number
  /** 真实 ctx 候选（不传即走假数据 ctxOptions） */
  optionsFor?: (ctx: TapCtxKey, params: TapParam[]) => { list: string[]; free: boolean }
  /** 参数是从哪来的（如「已沿用上次运行…的参数」）：填好的框不说一句会以为是自己上次没关页面 */
  hint?: string
  onParam: (k: string, v: string) => void
  onParams?: (values: Record<string, string>) => void
  /** 忽略已有产物，范围内全部重出（默认关：一律缺才跑） */
  forceAll: boolean
  onRange: (next: { from: string | null; to: string | null }) => void
  onForceAll: (v: boolean) => void
  onRun: () => void
}) {
  const [canonicalLabels, setCanonicalLabels] = useState<Record<string, string>>({})
  // 首/尾节点即流程默认端点：选中它们等同于「不指定」（range=null，按钮亮）
  const headId = nodes[0]?.id ?? ''
  const tailId = nodes[nodes.length - 1]?.id ?? ''
  const paramLabel = (param: TapParam) => param.label && param.label !== param.k
    ? param.label : canonicalLabels[param.k] || param.label || param.k
  // 必填项还差哪些：差就在按钮下方点名，齐了按钮点亮（白底黑字）
  const missing = (start?.params ?? [])
    .filter(p => p.required && !(p.v ?? '').trim())
    .map(paramLabel)
  const ready = !missing.length

  const ctxField = (p: TapParam) => {
    if (!p.ctx) return null
    // 真实候选：free（场景/角色名）可手填新名 → datalist；其余仍下拉
    const opt = optionsFor?.(p.ctx, start?.params ?? [])
    if (opt?.free) {
      return (
        <>
          <input className="tap-insp-input" value={p.v} disabled={running}
            placeholder="选已有或输入新名称" list={`tap-dl-${p.k}`}
            onChange={e => onParam(p.k, e.target.value)} />
          <datalist id={`tap-dl-${p.k}`}>
            {opt.list.map(o => <option key={o} value={o} />)}
          </datalist>
        </>
      )
    }
    const list = opt?.list ?? ctxOptions(p.ctx, start?.params ?? []).filter(o => o !== TAP_NO_VOLUME)
    const currentMissing = !!p.v && !list.includes(p.v)
    return (
      <select className="tap-insp-input" value={p.v} disabled={running}
        onChange={e => onParam(p.k, e.target.value)}>
        <option value="">{p.ctx === 'volume_id' ? TAP_NO_VOLUME : '未选择'}</option>
        {currentMissing && <option value={p.v}>{p.v}</option>}
        {list.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    )
  }

  return (
    <div className="tap-insp-body">
      {!start && <div className="tap-insp-note">本流程没有开始节点，直接运行</div>}
      {hint && <div className="tap-insp-note">{hint}</div>}
      <TapflowFixedParamCard params={start?.params ?? []}
        workflowSlug={workflowSlug} workflowVersion={workflowVersion} disabled={running}
        onParam={onParam} onParams={onParams} onLabels={setCanonicalLabels} />
      <section className="tap-insp-part tap-actual-params" aria-label="实际参数">
        <div className="tap-insp-sec">实际参数</div>
        {(start?.params ?? []).map(p => (
          <div key={p.k} className="tap-insp-field">
            <span className="k">{paramLabel(p)}
              {p.required && <i className="req">*</i>}</span>
            {p.type === 'ctx' && p.ctx ? ctxField(p) : p.allowedValues?.length ? (
              <select className="tap-insp-input" value={p.v} disabled={running}
                onChange={e => onParam(p.k, e.target.value)}>
                <option value="">未选择</option>
                {p.allowedValues.map(value => <option key={value} value={value}>{value}</option>)}
              </select>
            ) : (
              <input className="tap-insp-input" value={p.v} disabled={running}
                onChange={e => onParam(p.k, e.target.value)} />
            )}
          </div>
        ))}
      </section>

      {/* 执行卡片 = 运行范围 + 运行按钮：这三样都是「怎么跑」，跟上面的
          「跑什么参数」分开成一张卡；范围行放按钮正上方，改完立刻就能按。
          运行按钮紧跟参数不钉底：参数只有几行时，钉底会让按钮离最后一个
          输入框隔着大半屏空白。必填齐了就点亮成白底黑字。 */}
      <div className="tap-insp-part tap-run-card">
        <div className="tap-insp-sec">执行</div>
        {/* 两行各自「按钮 ⇄ 下拉」互斥——按钮亮 = 用流程默认端点。
            语义不是「截段跑」：整图始终从前往后走、默认缺才跑；
            开始节点 = 从它起强制重跑（之前的只查、缺了才补），结束节点 = 跑到它为止。 */}
        <div className="tap-range-row">
          <button type="button" className={'tap-range-tag' + (range.from ? '' : ' on')}
            title="从起点跑" disabled={running}
            onClick={() => onRange({ ...range, from: null })}>从开始</button>
          <select className="tap-insp-input" value={range.from ?? headId} disabled={running}
            onChange={e => onRange({ ...range, from: e.target.value === headId ? null : e.target.value })}>
            {nodes.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
          </select>
        </div>
        <div className="tap-range-row">
          <button type="button" className={'tap-range-tag' + (range.to ? '' : ' on')}
            title="跑到终点" disabled={running}
            onClick={() => onRange({ ...range, to: null })}>到结束</button>
          <select className="tap-insp-input" value={range.to ?? tailId} disabled={running}
            onChange={e => onRange({ ...range, to: e.target.value === tailId ? null : e.target.value })}>
            {nodes.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
          </select>
        </div>

        {/* 默认一律缺才跑（有产物就取回来用）；这个开关是「这次全部重出」的总闸。
            单个节点重出走生成条的「重新生成」，不必为它开全局。 */}
        <label className="tap-insp-check">
          <Switch checked={forceAll} disabled={running} label="强制重新生成"
            onChange={onForceAll} />
          <span>强制重新生成本画布内自有节点（仅所选的开始到结束节点之间）</span>
        </label>

        <button type="button" className={'tap-run-btn' + (ready ? ' ready' : '')}
          disabled={running} onClick={onRun}>
          {running ? <><Icon name="spinner" spin /> 运行中…</> : <><Icon name="play" /> 运行</>}
        </button>
        {!ready && !running && (
          <div className="tap-insp-note">还差必填项：{missing.join('、')}</div>
        )}
      </div>
    </div>
  )
}
