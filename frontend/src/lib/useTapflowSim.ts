// tapflow 假模拟运行（接接口前）：按连线拓扑序逐节点推进状态并写运行日志。
// 之后接真实工作流时，本 hook 换成「异步 run + 轮询节点状态」，签名不变。
import { useCallback, useEffect, useRef, useState } from 'react'
import type { TapEdge, TapNode } from './tapflowData'
import {
  rangeToRun, topoOrder, type TapRunOptions, type TapRunRange,
} from './tapflowRunPlan'

export interface TapRunLog { t: string; text: string; kind?: 'ok' | 'err' | 'info' }
export type { TapRunOptions, TapRunRange } from './tapflowRunPlan'

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))
const now = () => new Date().toTimeString().slice(0, 8)

export function useTapflowSim(
  getState: () => { nodes: TapNode[]; edges: TapEdge[] },
  patch: (id: string, p: Partial<TapNode>) => void,
) {
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<TapRunLog[]>([])
  const dead = useRef(false)
  // 挂载时复位：StrictMode 开发态会 挂载→卸载→再挂载，只写卸载侧会让 dead 永远为 true
  useEffect(() => {
    dead.current = false
    return () => { dead.current = true }
  }, [])
  const say = (text: string, kind?: TapRunLog['kind']) =>
    setLog(ls => [...ls, { t: now(), text, kind }])

  const run = useCallback(async (range?: TapRunRange, forceAll = false,
                                 options?: TapRunOptions) => {
    if (running) return
    setRunning(true)
    const singleNodeId = options?.mode === 'single' ? options.nodeId : undefined
    const label = singleNodeId
      ? `单节点运行：${getState().nodes.find(n => n.id === singleNodeId)?.title ?? singleNodeId}`
      : '全量运行'
    setLog([{ t: now(), text: `运行开始（模拟）：${label}`, kind: 'info' }])
    try {
      await runSteps(range, forceAll, singleNodeId)
    } finally {
      setRunning(false)   // 中途卸载/异常也要复位，否则按钮永久禁用
    }
  }, [running, getState, patch])  // eslint-disable-line react-hooks/exhaustive-deps

  /** 节点内置质检的模拟：第一轮故意不合格，演示「回退重生成 → 复检」这条链。
   * 返回 true = 重试用尽、停链（真实引擎里这时出图不入队）。 */
  const runNodeQc = async (n: TapNode): Promise<boolean> => {
    const qc = n.bind!.qc!
    const rounds = qc.retry ?? 0
    const line = qc.stage === 'image' ? '画面质检' : '提示词质检'
    for (let i = 0; i <= rounds; i++) {
      patch(n.id, { stage: { label: i ? `质检中 · 第 ${i + 1} 轮` : '质检中', tone: 'run' } })
      await sleep(700)
      // 假数据：第一轮 72 分不合格，之后每轮 +9，够到阈值就通过
      const score = 72 + i * 9
      const pass = score >= (qc.threshold ?? 80)
      say(`${line}（${qc.skill ?? '未绑技能'}）：${score} 分 / 合格线 ${qc.threshold ?? 80}`,
        pass ? 'ok' : 'err')
      // 判完把分数留在生成条右上角（通过绿 / 不通过红）
      patch(n.id, {
        stage: {
          label: `提示词 ${score} 分${i ? ` · ${i + 1} 轮` : ''}`,
          tone: pass ? 'ok' : 'err',
        },
      })
      if (pass) return false
      if (i === rounds) {
        say(rounds
          ? `${rounds} 次重试后仍不合格，停链——本节点产物不入库`
          : '不合格（重试 0 次=不回退），只记录结论', rounds ? 'err' : 'info')
        patch(n.id, { status: undefined, error: `${line}未通过：${score} 分` })
        return !!rounds
      }
      say(`回退重生成（第 ${i + 1}/${rounds} 次），带上一轮问题清单：构图缺中景、材质描述笼统`, 'info')
      patch(n.id, { status: 'generating' })
      await sleep(1200)
    }
    return false
  }

  const runSteps = async (range?: TapRunRange, forceAll = false, singleNodeId?: string) => {
    const { nodes, edges } = getState()
    // 整图从前往后跑（不截段）：范围只决定「哪些强制重跑」与「跑到哪停」，
    // 起点之前的节点照旧缺才跑——只查、缺了才补，链不会断
    const fullOrder = topoOrder(nodes, edges)
    const { force, stopAfter } = rangeToRun(nodes, edges, range, forceAll, singleNodeId)
    const order = singleNodeId
      ? fullOrder.filter(n => n.id === singleNodeId)
      : fullOrder
    if (singleNodeId && !order.length) {
      say(`找不到要运行的节点：${singleNodeId}`, 'err')
      return
    }
    if (singleNodeId) {
      say(`单节点运行：${order[0].title}（强制重新生成，不跳过）`, 'info')
    }
    if (!singleNodeId && force.length) {
      say(`从「${nodes.find(n => n.id === range?.from)?.title}」起强制重跑`, 'info')
    }
    if (stopAfter) say(`跑到「${nodes.find(n => n.id === stopAfter)?.title}」为止`, 'info')
    for (const n of order) {
      if (dead.current) return
      if (n.type === 'start') {
        say(`带入参数：${(n.params ?? []).map(p => `${p.k}=${p.v}`).join('，') || '（无）'}`)
      } else if (n.type === 'mount') {
        // 挂载点：演示运行里模拟「产物落库」——落了新东西就报一声
        patch(n.id, { status: 'generating', done: false })
        await sleep(500)
        patch(n.id, { status: undefined, done: true })
        say(`${n.title} 已落库`, 'ok')
      } else if (n.type === 'link') {
        say(`关联落库 ${n.link?.action ?? ''} → ${n.link?.target ?? ''}`)
        patch(n.id, { status: 'generating', done: false })
        await sleep(600)
        patch(n.id, { status: undefined, done: true })
        say(`${n.title} 完成`, 'ok')
      } else if (n.type === 'gen' || n.type === 'flow' || n.type === 'text') {
        const cur = getState().nodes.find(x => x.id === n.id)
        const had = n.type === 'gen' ? cur?.done && cur?.src : cur?.done
        if (had && (cur?.bind?.onlyMissing ?? true) && !force.includes(n.id)) {
          patch(n.id, { badge: { label: '跳过', tone: 'skip' } })
          say(`${n.title}：已有产物，跳过（缺才跑）`, 'info')
          continue
        }
        say(n.type === 'flow'
          ? `执行引用流程「${n.flow?.name ?? '未选择'}」…`
          : n.type === 'text'
            ? `${n.title} 装配中…`
            : `${n.title} 生成中${n.bind?.step ? `（${n.bind.step}）` : ''}…`)
        patch(n.id, {
          status: 'generating', done: false, badge: undefined,
          stage: { label: n.type === 'gen' ? '装配提示词' : '生成中', tone: 'run' },
        })
        await sleep(n.type === 'text' ? 1200 : 2200)
        if (n.type === 'gen') patch(n.id, { stage: { label: '图片生成中', tone: 'run' } })
        // 节点内置质检：不合格 → 回退本节点重生成（带上一轮问题清单），重试次数用尽则停链
        if (n.type === 'gen' && n.bind?.qc?.on) {
          const stopped = await runNodeQc(n)
          if (stopped) return
        }
        patch(n.id, {
          status: undefined, done: true,
          ...(n.type === 'gen'
            ? { src: `https://picsum.photos/seed/tap-run-${n.id}-${Date.now() % 997}/640/380` }
            : n.type === 'text'
              ? { text: '中远景与中景双联画幅：风暴夜的灯塔顶层信号室，铜制灯座与巨大棱镜，'
                  + '黄铜与玻璃材质在物理可信的光照下泛出暖光；电影级奇幻写实动画画风；'
                  + '画面中无人物与生物。' }
              : {}),
        })
        say(n.type === 'gen' ? `${n.title} 完成，产物已入附件库` : `${n.title} 完成`, 'ok')
      } else if (n.type === 'qc') {
        // 质检只看上游提示词（图片/视频不质检）
        patch(n.id, { status: 'generating', done: false })
        await sleep(700)
        const ups = getState().edges.filter(e => e.to === n.id)
          .map(e => getState().nodes.find(x => x.id === e.from))
        const ok = ups.length > 0 && ups.every(u => u?.done)
        patch(n.id, {
          status: undefined,
          qc: { ...n.qc, state: ok ? 'pass' : 'fail', score: ok ? '92 分' : undefined },
          done: ok,
        })
        say(`${n.title}：${ok ? '通过 · 92 分' : '未通过（上游提示词未产出）'}`, ok ? 'ok' : 'err')
      }
      if (stopAfter && n.id === stopAfter) break
    }
    say('运行结束', 'ok')
  }

  // 演示流程没有运行记录可回填，给个空实现让两个引擎接口一致
  const restoreLatest = useCallback(async () => {}, [])
  return { running, log, run, restoreLatest }
}
