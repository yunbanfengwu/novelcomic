// tapflow 编排画布:回填「上次是怎么跑的」——入参 + 运行范围 + 强制重跑开关。
// 数据源是 workflow_runs(每次运行本来就落了 inputs/run_options),不另存一份。
import { useEffect, useRef, useState } from 'react'
import { api, type WorkflowLastRun, type WorkflowRunOptions } from '../api'
import type { TapCtxKey, TapParam } from './tapflowData'
import { jsonbObj } from './tapflowGraphAdapter'

/** 值指向某条记录、画布上要显示成「617 · 线索交汇」的那几类 ctx。
 * 场景/角色/道具存的就是名字本身,原样填回即可。 */
const LOOKUP_CTX: TapCtxKey[] = ['project_id', 'target_ref', 'volume_id', 'chapter_id', 'shot_id']

type OptionsFor = (ctx: TapCtxKey, params: TapParam[]) => { list: string[]; free: boolean }

/**
 * 上次入参 → 这一轮能填上的值。纯函数,单独导出便于验证。
 *
 * 库里存的形态并不统一(startInputs 只把 project_id 折成数字,卷/章/镜原样存显示串),
 * 所以 ID 类一律「取前缀数字」两边对齐:20 与「20 · 北境灯塔」、「617 · 线索交汇」
 * 与「617 · 线索交汇」都能对上。
 *
 * @returns vals=这轮要填的;done=可以从待填里划掉的键(填上了,或那条数据已经没了)
 */
export function resolveLastInputs(
  params: TapParam[], pending: Record<string, unknown>, optionsFor?: OptionsFor,
): { vals: Record<string, string>; done: string[] } {
  const vals: Record<string, string> = {}
  const done: string[] = []
  for (const p of params) {
    if (!(p.k in pending)) continue
    const raw = pending[p.k]
    if (raw === null || raw === undefined || raw === '') { done.push(p.k); continue }
    if (!p.ctx || !LOOKUP_CTX.includes(p.ctx)) {
      done.push(p.k)
      vals[p.k] = String(raw)
      continue
    }
    const list = optionsFor?.(p.ctx, params).list ?? []
    if (!list.length) continue                 // 候选还没到(卷/章/镜要先选中项目):下一轮再试
    done.push(p.k)
    const source = String(raw).split(' · ', 1)[0]
    const hit = p.ctx === 'target_ref'
      ? list.find(o => o.split(' · ', 1)[0] === source)
      : list.find(o => parseInt(o, 10) === parseInt(source, 10))
    if (hit) vals[p.k] = hit                   // 对不上说明那条数据没了:不填,也不再等
  }
  return { vals, done }
}

export interface TapLastRunApply {
  /** 一次填多个:逐个 setParamValue 会互相覆盖(同一 tick 里拿的是同一份旧 params) */
  params: (vals: Record<string, string>) => void
  range: (r: { from: string | null; to: string | null }) => void
  forceAll: (v: boolean) => void
}

export interface TapLastRunOpts {
  /** 只回填入参，跳过运行范围与强制重跑开关——生产态的画布是从业务入口进来的，
   * 上次可能是编排台里跑到某个节点为止的调试运行，继承那个 range 会让流程在半路停下。 */
  paramsOnly?: boolean
  /** 这些键不回填（业务入口本次预填的现场值优先于上次运行的历史值） */
  excludeKeys?: string[]
  /** 只认这个项目的运行（防跨项目串台；实例 slug 天然专属，模板 slug 需要这道闸） */
  requireProjectId?: number
}

export function useTapflowLastRun(
  slug: string | undefined,
  /** 开始节点的当前入参(要它的 k/ctx 才知道每个值该怎么填) */
  params: TapParam[],
  /** 真实上下文候选;演示流程不传 */
  optionsFor: OptionsFor | undefined,
  apply: TapLastRunApply,
  opts?: TapLastRunOpts,
): WorkflowLastRun | null {
  const [last, setLast] = useState<WorkflowLastRun | null>(null)
  // 还没填上的键。填一个划掉一个——回填只发生一次,之后用户改成什么就是什么
  const pending = useRef<Record<string, unknown>>({})
  const applyRef = useRef(apply)
  applyRef.current = apply
  const optsRef = useRef(opts)
  optsRef.current = opts

  useEffect(() => {
    if (!slug) return
    let dead = false
    api.workflowLastRun(slug).then(r => {
      if (dead || !r) return
      const runInputs = jsonbObj(r.inputs)
      if (optsRef.current?.requireProjectId != null
          && String(runInputs.project_id ?? '') !== String(optsRef.current.requireProjectId)) return
      setLast(r)
      pending.current = runInputs
      // 生产态只回入参：范围/强制开关属于编排台的调试现场，不该闯进业务画布
      if (!optsRef.current?.paramsOnly) {
        const o = jsonbObj(r.run_options) as WorkflowRunOptions
        if (o.range) applyRef.current.range({ from: o.range.from ?? null, to: o.range.to ?? null })
        if (o.force_all) applyRef.current.forceAll(true)
      }
    }).catch(() => { /* 没跑过/取不到:画布照常打开,只是没得回填 */ })
    return () => { dead = true }
  }, [slug])

  // 候选是异步来的而且级联(先选中项目才拉得到它的卷/章/镜),所以每次候选或参数变化
  // 都再试一轮:这一轮填得上的填掉,填不上的留到下一轮。
  useEffect(() => {
    if (!Object.keys(pending.current).length) return
    const { vals, done } = resolveLastInputs(params, pending.current, optionsFor)
    for (const k of done) delete pending.current[k]
    // 业务入口本次预填的键是「现场」，优先级高于上次运行的历史值
    for (const k of optsRef.current?.excludeKeys ?? []) {
      delete pending.current[k]
      delete vals[k]
    }
    if (Object.keys(vals).length) applyRef.current.params(vals)
  }, [params, optionsFor])

  return last
}
