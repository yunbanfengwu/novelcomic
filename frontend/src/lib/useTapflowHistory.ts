import { useCallback, useEffect, useRef } from 'react'
import type { TapEdge, TapNode } from './tapflowData'

interface TapSnap { nodes: TapNode[]; edges: TapEdge[] }

/** 撤销栈上限。快照只是两个数组的浅拷贝，未变的节点对象 React 本来就在复用，
 * 50 步的内存开销可忽略——不必为省内存去做差量。 */
const LIMIT = 50
/** 结构指纹：只认「有哪些节点、哪些连线」。拖动坐标、改正文、运行回填产物都**不算一步**——
 * 否则拖一下节点就压进几十条快照，Ctrl+Z 得按半天才退回上一次真正的编辑。 */
const sigOf = (s: TapSnap) =>
  s.nodes.map(n => n.id).join(',') + '|' + s.edges.map(e => e.id).join(',')

export interface TapHistory {
  /** Ctrl/⌘+Z：退回上一次结构变更之前 */
  undo: () => void
  /** Ctrl/⌘+Shift+Z（Windows 习惯的 Ctrl+Y 同义）：把撤销掉的那步再做回来 */
  redo: () => void
}

/**
 * tapflow 画布的撤销/重做栈（Ctrl/⌘+Z / +Shift+Z）：**只活在内存里**，随画布弹窗卸载一起消失——
 * 关掉画布就撤不回来，这是设计不是缺陷：
 * - 画布是后端 graph 的投影，落 localStorage 会与下次打开时拉到的 graph 打架；
 * - 撤销本就是「这次编辑会话」的语义，跨会话找回是回收站那类持久层的活儿。
 *
 * 入栈时机由结构指纹自动判定（见 sigOf），调用方不必在每个增删点手动埋 commit——
 * 以后新增的增删入口自动被覆盖，不会漏。
 * 回填时也只还原结构：还活着的节点一律取现场那份（见 step），所以运行态撤销一次删除，
 * 这中间跑出来的产物、拖过的位置都不会被快照里的旧对象盖回去。
 */
export function useTapflowHistory(
  nodes: TapNode[], edges: TapEdge[],
  setNodes: React.Dispatch<React.SetStateAction<TapNode[]>>,
  setEdges: React.Dispatch<React.SetStateAction<TapEdge[]>>,
): TapHistory {
  const past = useRef<TapSnap[]>([])
  const future = useRef<TapSnap[]>([])
  // 上一次渲染的图：结构一变，入栈的是**它**（含此前所有拖动后的最新坐标）
  const prev = useRef<TapSnap>({ nodes, edges })
  const sig = useRef(sigOf({ nodes, edges }))
  // 撤销/重做自己引起的结构变化不能再走自动入栈——两个栈已经在下面手动倒好了
  const applying = useRef(false)

  useEffect(() => {
    const cur = { nodes, edges }
    const s = sigOf(cur)
    if (s !== sig.current) {
      if (applying.current) applying.current = false
      else {
        past.current = [...past.current, prev.current].slice(-LIMIT)
        // 撤销之后又动手编辑 = 历史分叉：原来那条「未来」已经接不回来了，清掉。
        // 留着它只会让 Ctrl+Shift+Z 跳到一张跟当前图无关的快照上
        future.current = []
      }
      sig.current = s
    }
    prev.current = cur
  }, [nodes, edges])

  /** 两个方向共用：把当前图倒进 to 栈，从 from 栈取一张回填 */
  const step = useCallback((from: TapSnap[], to: TapSnap[]) => {
    const target = from[from.length - 1]
    if (!target) return { from, to }
    applying.current = true
    // 快照只定「有哪些节点」；节点**内容**取现场那份，只有被删掉、现场已经没有的
    // 才用快照里的旧对象复活。否则撤销一次删除，会把这中间生成的图、改过的正文、
    // 拖过的位置连同快照一起盖回去——那不是撤销，那是回档。
    const liveById = new Map(prev.current.nodes.map(n => [n.id, n]))
    // 两个 setState 由 React 自动批处理合成一次渲染，上面的 effect 只会看到一次结构变化
    setNodes(target.nodes.map(n => liveById.get(n.id) ?? n))
    setEdges(target.edges)
    return { from: from.slice(0, -1), to: [...to, prev.current].slice(-LIMIT) }
  }, [setNodes, setEdges])

  const undo = useCallback(() => {
    const r = step(past.current, future.current)
    past.current = r.from; future.current = r.to
  }, [step])
  const redo = useCallback(() => {
    const r = step(future.current, past.current)
    future.current = r.from; past.current = r.to
  }, [step])

  return { undo, redo }
}
