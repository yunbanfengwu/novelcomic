import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { bezierPath } from '../../lib/canvasGeometry'
import {
  defaultGen, newTapNode, projectParams, syncMountSizes, upstreamVars, visibleFlow, withProjectParams,
  type TapEdge, type TapNode, type TapNodeType, type TapUpstreamVar,
} from '../../lib/tapflowData'
import { canConnect, edgeAnchors, edgeMid, nodeAt, segHitsBox } from '../../lib/tapflowEdges'
import { resolveTitle, titleVars } from '../../lib/tapflowGraphAdapter'
import {
  duplicateSelection, GROUP_PAD, newGroup, nodesInRect, pruneGroups, sameIds, selectable,
  selectionBounds, type TapGroup,
} from '../../lib/tapflowSelection'
import { upstreamNodes } from '../../lib/tapflowRunPlan'
import { wrapSelectionInLoop } from '../../lib/tapflowLoop'
import { TapPickMenu } from '../../components/tapflow/TapPickMenu'
import { COLUMN_STEP, COLUMN_WIDTH, LAYOUT_MARGIN, layoutPositions, snapColumnX } from '../../lib/tapflowLayout'
import { useTapflowMarquee } from '../../lib/useTapflowMarquee'
import { useTapflowView } from '../../lib/useTapflowView'
import { Icon } from '../../components/Icon'
import { CanvasAssetPanel } from '../../components/CanvasAssetPanel'
import { api, type ProjectAsset, type UnifiedReference } from '../../api'
import { TapflowAddMenu } from './TapflowAddMenu'
import { TapflowEdges } from './TapflowEdges'
import { TapflowGroupBox } from './TapflowGroupBox'
import { TapflowHelp } from './TapflowHelp'
import { TapflowMediaOverlay } from './TapflowMediaOverlay'
import { TapflowNode } from './TapflowNode'
import { TapflowNodeToolbar } from './TapflowNodeToolbar'
import { TapflowPromptBar, type TapPromptSendMode } from './TapflowPromptBar'
import { TapflowFolderNode, type TapflowFolder } from './TapflowFolderNode'
import type { TapFlowKind } from '../../lib/tapflowKind'
import { TapflowRail } from './TapflowRail'
import { TapflowSelectToolbar } from './TapflowSelectToolbar'
import { TapflowZoomBar } from './TapflowZoomBar'
import './tapflow.css'

const TITLE_H = 26 // 节点标题行高：连线锚点要落在卡片竖直中心
/** 标题轻微跟随画布缩放，最终屏幕观感限制在基准尺寸的 88%～112%。 */
const titleCounterScale = (canvasScale: number) => {
  const screenScale = Math.min(1.12, Math.max(0.88, canvasScale ** 0.12))
  return screenScale / canvasScale
}
/** 有实体媒体、能裁剪/放大的节点类型 */
const MEDIA_TYPES: TapNodeType[] = ['image', 'video', 'upload', 'gen', 'audio']
/** 运行态能炸开生成输入条的节点：媒体类 + 走 LLM 的文本/质检（查询取数的不炸开） */
// 运行态点开就有工具条的节点：媒体类 + 文本/质检。
// 查询取数的文本卡（场景介绍这类）以前被排除在外，可它同样需要「复制/编辑/重新生成」
// 引用型卡片（flow）只有在被引用的流程声明了「支持智能调用」时才炸开：
// 组合流程炸开后点生成，到底生成子图里的哪几个节点？没有这个声明就答不上来，
// 于是给个不知道会做什么的输入框反而更糟。声明了的，提示词交给规划器逐节点判。
const canExpand = (n: TapNode) =>
  MEDIA_TYPES.includes(n.type) || n.type === 'text' || n.type === 'qc'
  || (n.type === 'flow' && !!n.smart) || n.type === 'mount'
type PortSide = 'left' | 'right'
interface MenuState {
  kind: 'add' | 'ref'
  from?: string; side?: PortSide; branch?: string
  /** 多选「新建节点」：这些节点全部连到新节点上（它们即新节点的参考元素） */
  froms?: string[]
  sx: number; sy: number
}

/**
 * tapflow 画布（独立组件，受控）：黑色点阵背景 + 平移缩放 + 贝塞尔连线 + 内容直出节点。
 * 节点/连线状态由容器（TapflowModal）持有——属性面板/运行面板的编辑才能回写画布。
 * 扩展节点两条路：rail「新建最小集」弹「添加节点」；节点圆点拖出弹「引用该节点生成」并自动连线。
 */
export function TapflowCanvas({
  nodes, edges, onNodesChange, onEdgesChange, mode, autoLayout, canAdd,
  onSelectNode, onToggleInspector, inspectorOpen,
  onRun, onRunNow, onSend, onRegen, regenBusy, onInstruct,
  onReload, onBgClick, onUndo, onRedo, onRelayout, flows = [],
  projectId, businessRefs = [], onBusinessRefAdd, onBusinessRefRemove, entryMount, onMountWire,
}: {
  nodes: TapNode[]
  edges: TapEdge[]
  onNodesChange: React.Dispatch<React.SetStateAction<TapNode[]>>
  onEdgesChange: React.Dispatch<React.SetStateAction<TapEdge[]>>
  mode: 'edit' | 'run'
  /** 坐标自动排版（真实工作流；演示画布是手工摆位的视觉基准，不动它） */
  autoLayout?: boolean
  /** rail 的「新建节点」给不给。与「能不能配属性」是两回事：生产态能建（建出来
   * 存进本对象的专属画布），但只有自己建的那些才能配 */
  canAdd?: boolean
  /** 选中节点回传给外层（编排态据此展开右侧属性面板）；带上可引用的上游输出变量 */
  onSelectNode?: (node: TapNode | null, ctx: { upstream: TapUpstreamVar[] }) => void
  /** Retained for callers while the rail no longer exposes a manual inspector toggle. */
  onToggleInspector?: () => void
  /** 属性面板当前是否开着（给工具条上的属性 icon 激活态） */
  inspectorOpen?: boolean
  /** 底部条「运行」（编排台）：开右侧运行面板（由容器执行） */
  onRun?: () => void
  /** 底部条「运行」：直接跑，不开面板。生产态的主操作 */
  onRunNow?: () => void
  /** 真实工作流清单：subflow 节点靠它把 slug 显示成流程名 */
  flows?: { slug: string; version: number; name: string; kind?: TapFlowKind }[]
  /** 质检未通过时「重新生成」提示词（生成条里的按钮） */
  onRegen?: (nodeId: string) => void
  regenBusy?: boolean
  /** 生成条「发送」：**只重跑这一个节点**（默认全局是缺才跑，这是唯一的强制重跑入口） */
  onSend?: (nodeId: string, mode: TapPromptSendMode) => void
  /** 工具条「重新读取」：零副作用地重取该节点在库里的产物（不跑模型、不写库） */
  onReload?: (nodeId: string) => void
  /** 点画布空白：收起右侧停靠面板 */
  onBgClick?: () => void
  /** Ctrl/⌘+Z：撤销上一次结构变更（增删节点/连线）。由容器持有撤销栈——图的状态在它那儿 */
  onUndo?: () => void
  /** Ctrl/⌘+Shift+Z / Ctrl+Y：把撤销掉的那步再做回来 */
  onRedo?: () => void
  /** 用户显式要求整图重排；按钮位于左下角缩放控制之前。 */
  onRelayout?: () => void
  /** 底部条输入框的指令下发：交给 AI 编排（走对话面板规划链路），由容器实现 */
  onInstruct?: (text: string) => void
  projectId?: number
  businessRefs?: UnifiedReference[]
  onBusinessRefAdd?: (asset: ProjectAsset) => void | Promise<void>
  onBusinessRefRemove?: (id: number) => void | Promise<void>
  /** 入口业务对象的当前产物（如项目现有封面）：归宿匹配的挂载点进画布即回显它 */
  entryMount?: { target: string; url: string }
  /** 挂载点接上新上游后回调（容器据此「连线即落库」）；只在真的新建了指向挂载点的边时触发 */
  onMountWire?: (mountId: string, srcId: string) => void
}) {
  const { view, zoomMode, panMode, hostRef, tryPan, setScaleCentered } = useTapflowView(
    mode === 'edit' ? { x: 90, y: 70, scale: 0.4 } : { x: 40, y: 20, scale: 0.5 })
  const setNodes = onNodesChange
  const setEdges = onEdgesChange
  // 选中的节点（可多选：空白处拖出选框、或 Shift/⌘ 点选加减）。
  // 属性面板/生成条这些「针对一个对象」的浮层只在**恰好选中一个**时出现
  const [selIds, setSelIds] = useState<string[]>([])
  const selected = selIds.length === 1 ? selIds[0] : null
  // 组 = 画布上的视觉圈选，只活在画布里（不进图数据、不参与运行、不落库）
  const [groups, setGroups] = useState<TapGroup[]>([])
  // 文件夹是组的另一种画布形态：成员仍留在 nodes 里，但视觉上折叠成一个节点。
  // 不把它放进 TapNode，确保保存、运行和后端 graph 都完全不知道这个临时 UI 状态。
  const [folders, setFolders] = useState<TapflowFolder[]>([])
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null)
  const folderSeq = useRef(0)
  const foldersLive = useRef<TapflowFolder[]>([])
  foldersLive.current = folders
  // 选中的连线（可删，可多条：点选一条 / Shift 加选 / 框选把穿过框的线都选上）。
  // 两态都可选中：运行态拖端口也能建边，连错了必须能断——
  // 桥接边（隐藏节点替代边，id 含 ~）删除时会一并移除其源边（Ctrl+Z 可撤销）
  const [selEdges, setSelEdges] = useState<string[]>([])
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [media, setMedia] = useState<{ mode: 'crop' | 'view'; src: string; video?: string } | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  // 编排态参考线固定开启；运行/生产态由右下角按钮按需开启，参考线与吸附共用此开关。
  const [runGuidesOn, setRunGuidesOn] = useState(false)
  const [businessAssetsOpen, setBusinessAssetsOpen] = useState(false)
  // 文本卡：点工具条「编辑」进编辑态、点「重新生成」唤出生成条
  const [editId, setEditId] = useState<string | null>(null)
  const [regenId, setRegenId] = useState<string | null>(null)
  // 挂载点：正在重新选择归宿的节点 id（工具条「修改」触发；点选列表项后关闭）
  const [editingMountId, setEditingMountId] = useState<string | null>(null)
  const [refMenuOpen, setRefMenuOpen] = useState(false)
  const [tempEdge, setTempEdge] = useState<{
    from: string; side: PortSide; branch?: string
    originX: number; originY: number
    sx: number; sy: number
  } | null>(null)
  // 拖线正悬停、且能连上的目标节点：高亮提示「松手就连这里」
  const [dropId, setDropId] = useState<string | null>(null)
  // 节点实测高度（含标题行）：卡片高度由内容/图片撑开，声明的 node.h 只是占位，
  // 连线锚点必须用实测值才落在卡片竖直中线上
  const [heights, setHeights] = useState<Record<string, number>>({})
  const onMeasure = useCallback((id: string, h: number) =>
    setHeights(hs => hs[id] === h ? hs : { ...hs, [id]: h }), [])
  /** 连线锚点 = **卡片**竖直中线（跳过标题行），与 ⊕ 端口的位置一致：
   * 端口 CSS 是 top:calc(50% + 13px)，即卡片中心；若这里用整个节点中心，
   * 两者会差半个标题行，线看着就比 ⊕ 高一截 */
  const midY = useCallback((n: TapNode) => {
    const h = heights[n.id] ?? TITLE_H + n.h
    return n.y + (h + TITLE_H) / 2
  }, [heights])

  const byId = useMemo(() => new Map(nodes.map(n => [n.id, n])), [nodes])
  /** 运行态循环的真实子元素。它们是预检/执行按集合展开的瞬态节点，不是 loop.body 模板。 */
  const runtimeLoopChildren = useMemo(() => {
    const children = new Map<string, TapNode[]>()
    for (const node of nodes) {
      const owner = node.runtime?.loopOwner
      if (!owner) continue
      children.set(owner, [...(children.get(owner) ?? []), node])
    }
    for (const instances of children.values()) {
      instances.sort((a, b) => (a.runtime?.iteration ?? 0) - (b.runtime?.iteration ?? 0))
    }
    return children
  }, [nodes])
  // 标题里的 `{{input.x}}` 用的值：入参一填就替换,不用等运行(选完场景标题当场带出场景名)
  const titleVals = useMemo(() => titleVars(nodes), [nodes])
  // 运行视图：隐藏 hideInRun 节点（关联落库等，照常执行）并桥接其上下游连线
  const vis = useMemo(() => visibleFlow(nodes, edges, mode), [nodes, edges, mode])
  const folderMemberIds = useMemo(
    () => new Set(folders.flatMap(folder => folder.nodeIds)), [folders])
  // 文件夹只改变画布的可见层；底层 nodes/edges 仍完整保留，运行与保存不受影响。
  const displayNodes = useMemo(
    () => vis.nodes.filter(n => !folderMemberIds.has(n.id)), [vis.nodes, folderMemberIds])
  // 文件夹本身不是 TapNode，但连线需要一个可计算锚点；用同坐标的临时代理节点渲染，
  // 不会进入 nodes、保存或运行数据。
  const folderProxyNodes = useMemo<TapNode[]>(() => folders.map(folder => ({
    id: folder.id, type: 'image', title: '文件夹',
    x: folder.x, y: folder.y, w: folder.w, h: folder.h,
  })), [folders])
  const folderOfNode = useMemo(() => new Map(
    folders.flatMap(folder => folder.nodeIds.map(nodeId => [nodeId, folder.id] as const)),
  ), [folders])
  const displayById = useMemo(
    () => new Map([...displayNodes, ...folderProxyNodes].map(node => [node.id, node])),
    [displayNodes, folderProxyNodes])
  const { renderEdges, renderEdgeSources } = useMemo(() => {
    const merged = new Map<string, TapEdge>()
    const sources = new Map<string, string[]>()
    for (const edge of vis.edges) {
      const from = folderOfNode.get(edge.from) ?? edge.from
      const to = folderOfNode.get(edge.to) ?? edge.to
      // 文件夹内部的边已经被折叠在同一个节点里，不再画成自环。
      if (from === to || !displayById.has(from) || !displayById.has(to)) continue
      const key = `${from}->${to}`
      const existing = merged.get(key)
      if (existing) {
        sources.set(existing.id, [...(sources.get(existing.id) ?? []), edge.id])
        continue
      }
      const projected: TapEdge = {
        ...edge,
        id: from === edge.from && to === edge.to ? edge.id : `folder-edge:${from}->${to}`,
        from,
        to,
      }
      merged.set(key, projected)
      sources.set(projected.id, [edge.id])
    }
    return { renderEdges: [...merged.values()], renderEdgeSources: sources }
  }, [displayById, folderOfNode, vis.edges])
  const selectedFolder = folders.find(folder => folder.id === selectedFolderId) ?? null
  const sel = selected ? byId.get(selected) : null

  /** 该节点的直属上游（连线直接连过来的那些） */
  const directUp = useCallback((id: string) =>
    edges.filter(e => e.to === id).map(e => byId.get(e.from)).filter(Boolean) as TapNode[],
  [edges, byId])
  /** 当前生成条要显示的参考节点：没手选过就按直属上游自动带 */
  const refIdsOf = useCallback((n: TapNode) =>
    n.gen?.refNodes ?? directUp(n.id).map(u => u.id), [directUp])
  const setRefIds = useCallback((id: string, ids: string[]) =>
    setNodes(ns => ns.map(n => n.id === id
      ? { ...n, gen: { ...defaultGen(n.type), ...n.gen, refNodes: ids } } : n)), [setNodes])

  /** 上传参考图：本地文件 → OSS 直传 → url 写回节点。
   * 参考图节点（value）写到节点 src；出图节点追加进静态参考图清单 refImages。
   * uploadFile 只转存不落库：参考图是画布素材，不是项目附件 */
  const uploadRefImage = useCallback((id: string, file: File) => {
    void api.uploadFile(file).then(res => {
      if (!res.url) { window.alert('对象存储未配置，上传失败'); return }
      setNodes(ns => ns.map(n => (n.id === id
        ? (n.type === 'upload'
          ? { ...n, src: res.url! }
          : { ...n, refImages: [...(n.refImages ?? []), res.url!] })
        : n)))
    }).catch(() => window.alert('上传失败，请重试'))
  }, [setNodes])
  /** 从出图节点上移除一张静态参考图 */
  const removeRefImage = useCallback((id: string, url: string) => {
    setNodes(ns => ns.map(n => (n.id === id
      ? { ...n, refImages: (n.refImages ?? []).filter(u => u !== url) }
      : n)))
  }, [setNodes])
  useEffect(() => {
    onSelectNode?.(sel ?? null, {
      upstream: sel ? upstreamVars(sel.id, nodes, edges) : [],
    })
  }, [sel, nodes, edges, onSelectNode])
  /** 挂载点尺寸规范：始终比上游连线节点大一号（1.5 倍、中心不动，归宿胶囊见 css）。
   * 加载/连线/上游缩放后都重算；函数式更新——基于最新节点算补偿，不会回滚其他改动；
   * 无变化时返回原数组，React 直接 bail out 不重渲染。 */
  useEffect(() => {
    setNodes(cur => syncMountSizes(cur, edges) ?? cur)
  }, [nodes, edges, setNodes])
  /** 按 id 批量平移（屏幕位移 → 世界位移） */
  const moveBy = (ids: string[], dx: number, dy: number) =>
    setNodes(ns => ns.map(n => ids.includes(n.id)
      ? { ...n, x: n.x + dx / view.scale, y: n.y + dy / view.scale } : n))
  /** 拖动：拖的是多选里的某一个 → 整组一起挪；否则只挪它自己 */
  const drag = (id: string, dx: number, dy: number) =>
    moveBy(selIds.includes(id) ? selIds : [id], dx, dy)
  const resizeNode = (id: string, dx: number, dy: number) =>
    setNodes(ns => ns.map(n => n.id === id
      ? { ...n,
          w: Math.max(120, Math.round(n.w + dx / view.scale)),
          h: Math.max(80, Math.round(n.h + dy / view.scale)),
          manualSize: true }
      : n))
  const snapToColumn = (id: string) => {
    if (mode !== 'edit' && !runGuidesOn) return
    const ids = selIds.includes(id) ? selIds : [id]
    setNodes(ns => ns.map(n => {
      if (!ids.includes(n.id)) return n
      const center = n.x + n.w / 2
      return { ...n, x: snapColumnX(center, n.w) }
    }))
  }
  const snapFolderToColumn = (id: string) => {
    if (mode !== 'edit' && !runGuidesOn) return
    const folder = foldersLive.current.find(item => item.id === id)
    if (!folder) return
    const center = folder.x + folder.w / 2
    const targetX = snapColumnX(center, folder.w)
    const dx = targetX - folder.x
    if (Math.abs(dx) < 0.01) return
    setFolders(fs => fs.map(item => item.id === id
      ? { ...item, x: item.x + dx } : item))
    setNodes(ns => ns.map(node => folder.nodeIds.includes(node.id)
      ? { ...node, x: node.x + dx } : node))
  }
  /** 挂载点的实时产物：取最近一根入边上的媒体（图片/视频封面）。运行前就有——
   * 「连上谁就显示谁」；落库后的正式回显仍以 node.mount.url 为准。 */
  const mountUpstreamUrl = (id: string): string | undefined => {
    for (let i = edges.length - 1; i >= 0; i--) {
      const e = edges[i]
      if (e.to !== id) continue
      const u = byId.get(e.from)
      if (u?.src || u?.video) return u.src || u.video || undefined
    }
    return undefined
  }
  /** 挂载点的来源节点标题（同一根「最近入边」）：牌子与卡内信息栏显示「素材从哪来」。
   * 用展示层标题（模板变量已解析），与画布上看到的节点名一致。 */
  const mountUpstreamTitle = (id: string): string | undefined => {
    for (let i = edges.length - 1; i >= 0; i--) {
      const e = edges[i]
      if (e.to !== id) continue
      const u = byId.get(e.from)
      if (u?.src || u?.video) return resolveTitle(u.title, titleVals)
    }
    return undefined
  }
  /** 挂载点点选归宿：写回节点并退出选择态。同归宿唯一由列表禁用保证，后端校验兜底 */
  const pickMountTarget = (id: string, target: string) => {
    setNodes(ns => ns.map(x => x.id === id ? { ...x, mount: { ...x.mount, target } } : x))
    setEditingMountId(null)
  }
  /** 节点点选：additive=Shift/⌘ 时在集合里加减，否则重置为只选它 */
  const pickNode = (id: string, additive: boolean) => {
    setSelEdges([])
    setSelectedFolderId(null)
    // 选到别的节点上就把挂载点的归宿列表收起来（新选中待选挂载点时会再打开）
    setEditingMountId(null)
    setSelIds(ids => additive
      ? (ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id])
      : [id])
  }
  /** 组框点选：整组一起进选中集合 */
  const pickIds = (ids: string[], additive: boolean) => {
    setSelEdges([])
    setSelectedFolderId(null)
    setSelIds(cur => additive ? [...new Set([...cur, ...ids])] : ids)
  }

  // 自动排版：只在切换编排/运行时整图重算一次。运行态少了隐藏节点（关联落库），
  // 列要重新收匀——否则它原来占的那一列就是个 400 多 px 的洞。
  // 只跑一次而不是每次渲染：用户拖动过的位置、新加的节点都不会被挪走。
  const live = useRef({ nodes, edges, heights })
  live.current = { nodes, edges, heights }
  useEffect(() => {
    if (!autoLayout) return
    const { nodes: ns, edges: es, heights: hs } = live.current
    // 布局前先把挂载点尺寸规范到 1.5 倍，否则按 460 宽排好、放大后中心不动，
    // 会向左溢出压到上一列节点
    const sized = syncMountSizes(ns, es) ?? ns
    const v = visibleFlow(sized, es, mode)
    const pos = layoutPositions(v.nodes, v.edges, hs, TITLE_H)
    setNodes(cur => cur.map(n => {
      const s = sized.find(m => m.id === n.id)
      const p = pos.get(n.id)
      if (!s && !p) return n
      return {
        ...n,
        ...(s ? { w: s.w, h: s.h } : {}),
        ...(p ?? { x: n.x, y: n.y }),
      }
    }))
  }, [autoLayout, mode, setNodes])

  /** 一条拖线落到某节点时要新建的边（方向由拖出的是左口还是右口决定）；不能连则 null */
  const edgeFor = useCallback((from: string, side: PortSide, target: TapNode | null, branch?: string) => {
    if (!target) return null
    const [a, b] = side === 'left' ? [target.id, from] : [from, target.id]
    return canConnect(edges, a, b) ? { id: `e-${a}-${b}${branch ? `-${branch}` : ''}`, from: a, to: b, branch } : null
  }, [edges])

  /** 圆点拖出：跟手画临时虚线。松手落在别的节点上 = 直接连线；落在空白才弹「引用该节点生成」 */
  const startPortDrag = (id: string, side: PortSide, e: React.PointerEvent, branch?: string) => {
    e.stopPropagation()
    const host = hostRef.current?.getBoundingClientRect()
    if (!host) return
    const pt = (ev: { clientX: number; clientY: number }) =>
      ({ sx: ev.clientX - host.left, sy: ev.clientY - host.top })
    /** 落点下的节点（世界坐标命中，排除自己） */
    const hit = (p: { sx: number; sy: number }) => {
      const t = nodeAt(displayNodes, (p.sx - view.x) / view.scale, (p.sy - view.y) / view.scale, heights, TITLE_H)
      return t && t.id !== id ? t : null
    }
    const origin = pt(e)
    setTempEdge({ from: id, side, branch, originX: origin.sx, originY: origin.sy, ...origin })
    const move = (ev: PointerEvent) => {
      const p = pt(ev)
      setTempEdge({ from: id, side, branch, originX: origin.sx, originY: origin.sy, ...p })
      const t = hit(p)
      setDropId(t && edgeFor(id, side, t, branch) ? t.id : null)
    }
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setTempEdge(null)
      setDropId(null)
      const p = pt(ev)
      const link = edgeFor(id, side, hit(p), branch)
      if (link) {
        // 挂载点单输入（2026-09-18）：指向它的入边只有一条，连上新的就顶掉旧的——
        // 「当前指向哪张图」必须无歧义，双线会让预览与落库各挑各的
        const targetNode = byId.get(link.to)
        if (targetNode?.type === 'mount') {
          setEdges(es => es.filter(e => e.to !== link.to).concat(link))
          onMountWire?.(link.to, link.from)
        } else {
          setEdges(es => [...es, link])
        }
        setSelEdges([link.id])
        return
      }
      // 已连过/会成环的落点：不弹新建菜单（用户是想连线，不是想凭空多个节点）
      if (hit(p)) return
      setMenu({ kind: 'ref', from: id, side, branch, sx: p.sx, sy: p.sy })
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  /** 删连线（可一次删多条）：选中后按 Delete/Backspace，或点线中点的 ✕。
   * 桥接边要映射回它代表的那几条源边一起删——只删「看着断开的那条」，
   * 隐藏节点一显形线又回来了。 */
  const removeEdges = useCallback((ids: string[]) => {
    const drop = new Set<string>()
    for (const id of ids) {
      const src = renderEdgeSources.get(id)
      if (src?.length) src.forEach(x => drop.add(x))
      else drop.add(id)
    }
    setEdges(es => es.filter(e => !drop.has(e.id)))
    setSelEdges([])
  }, [renderEdgeSources, setEdges])
  /** 删选中的节点（可多个）：连它们的线一并删（留下悬空的边，画布画不出来、运行也接不上）。
   * 开始节点是整张流程的入口，删了就没有入参声明与运行起点，不给删。 */
  const removeSelected = useCallback(() => {
    const ids = selIds.filter(id => { const n = byId.get(id); return n && selectable(n) })
    if (!ids.length) return
    setNodes(ns => ns.filter(n => !ids.includes(n.id)).map(n => n.type === 'loop' && n.loop?.body
      ? { ...n, loop: { ...n.loop, body: n.loop.body.filter(id => !ids.includes(id)) } }
      : n))
    setEdges(es => es.filter(e => !ids.includes(e.from) && !ids.includes(e.to)))
    setSelIds([])
  }, [selIds, byId, setNodes, setEdges])
  /** 复制选中的节点：副本整体偏移，选区内部的连线一并复制，复制完选中副本 */
  const duplicateSelected = useCallback(() => {
    const dup = duplicateSelection(nodes, edges, selIds)
    if (!dup.nodes.length) return
    setNodes(ns => [...ns, ...dup.nodes])
    setEdges(es => [...es, ...dup.edges])
    setSelIds(dup.nodes.map(n => n.id))
  }, [nodes, edges, selIds, setNodes, setEdges])
  // 节点被删/运行态隐藏后修剪组，成员剩不到 2 个的组自动消失
  useEffect(() => {
    const alive = new Set(vis.nodes.map(n => n.id))
    setGroups(gs => {
      const next = pruneGroups(gs, alive)
      return next.length === gs.length && next.every((g, i) => g === gs[i]) ? gs : next
    })
  }, [vis.nodes])
  /** 当前选中恰好等于某个已有的组（→ 按钮切「解组」） */
  const selGroup = groups.find(g => sameIds(g.nodeIds, selIds)) ?? null
  const loopBodyIds = new Set(nodes.flatMap(n => n.type === 'loop' ? (n.loop?.body ?? []) : []))
  /** 打组 / 解组：只改画布视觉，不动图数据 */
  const toggleGroup = useCallback(() => {
    if (selGroup) { setGroups(gs => gs.filter(g => g.id !== selGroup.id)); return }
    if (selIds.length < 2) return
    // 一个节点只属于一个组：新组先把成员从旧组里摘掉
    setGroups(gs => {
      const kept = pruneGroups(
        gs.map(g => ({ ...g, nodeIds: g.nodeIds.filter(id => !selIds.includes(id)) })),
        new Set(vis.nodes.map(n => n.id)))
      return [...kept, newGroup(selIds, kept.length + 1)]
    })
  }, [selGroup, selIds, vis.nodes])

  /** 将当前多选折叠为一个画布文件夹；成员仍保留在底层图中，便于解散后回到原位置。 */
  const createFolder = useCallback(() => {
    const memberIds = selIds.filter(id => {
      const node = byId.get(id)
      return node && selectable(node) && !folderMemberIds.has(id)
    })
    if (memberIds.length < 2) return
    const box = selectionBounds(displayNodes, memberIds, heights, TITLE_H)
    if (!box) return
    const folder: TapflowFolder = {
      id: `folder-${++folderSeq.current}`,
      nodeIds: memberIds,
      x: box.x,
      y: box.y,
      w: Math.max(320, Math.min(520, box.w)),
      h: 273,
    }
    setFolders(fs => [...fs, folder])
    // 成员从视觉组中移出，避免组框继续盖在文件夹下面。
    setGroups(gs => gs
      .map(group => ({ ...group, nodeIds: group.nodeIds.filter(id => !memberIds.includes(id)) }))
      .filter(group => group.nodeIds.length > 1))
    setSelIds([])
    setSelectedFolderId(folder.id)
  }, [byId, displayNodes, folderMemberIds, heights, selIds])

  const moveFolder = (id: string, dx: number, dy: number) => {
    const folder = folders.find(item => item.id === id)
    if (!folder) return
    const wx = dx / view.scale
    const wy = dy / view.scale
    setFolders(fs => fs.map(item => item.id === id
      ? { ...item, x: item.x + wx, y: item.y + wy } : item))
    setNodes(ns => ns.map(node => folder.nodeIds.includes(node.id)
      ? { ...node, x: node.x + wx, y: node.y + wy } : node))
  }

  const toggleFolder = useCallback((id: string) => {
    setFolders(fs => fs.map(folder => folder.id === id
      ? { ...folder, expanded: !folder.expanded } : folder))
  }, [])

  const unpackFolder = useCallback((id: string) => {
    const folder = folders.find(item => item.id === id)
    if (!folder) return
    setFolders(fs => fs.filter(item => item.id !== id))
    setSelectedFolderId(null)
    setSelIds(folder.nodeIds.filter(nodeId => byId.has(nodeId)))
  }, [byId, folders])

  const removeFolder = useCallback((id: string) => {
    setFolders(fs => fs.filter(item => item.id !== id))
    setSelectedFolderId(null)
    setSelIds([])
  }, [])

  // 节点被外部运行投影或删除后，清掉已经不存在的文件夹成员。
  useEffect(() => {
    const alive = new Set(nodes.map(node => node.id))
    setFolders(fs => {
      const next = fs
        .map(folder => ({ ...folder, nodeIds: folder.nodeIds.filter(id => alive.has(id)) }))
        .filter(folder => folder.nodeIds.length > 1)
      return next.length === fs.length && next.every((folder, index) =>
        folder === fs[index] || (folder.id === fs[index].id && folder.nodeIds.length === fs[index].nodeIds.length
          && folder.nodeIds.every((id, i) => id === fs[index].nodeIds[i]))) ? fs : next
    })
  }, [nodes])

  useEffect(() => {
    if (selectedFolderId && !folders.some(folder => folder.id === selectedFolderId)) {
      setSelectedFolderId(null)
    }
  }, [folders, selectedFolderId])

  /** 框选的下游节点变成真实 loop：保存 body/source/each/collect，画布仍保留体内节点供配置。 */
  const makeLoop = useCallback(() => {
    if (mode !== 'edit' || selIds.length < 1) return
    const box = selectionBounds(nodes, selIds, heights, TITLE_H)
    if (!box) return
    const result = wrapSelectionInLoop(nodes, edges, selIds, box.x - 520, box.y + box.h / 2)
    if (!result) return
    setNodes(result.nodes)
    setEdges(result.edges)
    setSelIds([result.loop.id])
  }, [mode, selIds, nodes, edges, heights, setNodes, setEdges])
  // 键盘：Delete 删选中的连线/节点，Ctrl/⌘+Z 撤销、+Shift 重做结构变更。
  // 两态都挂：运行态本来就能从端口拖出「引用这个节点生成」新建节点，
  // 只让新建不让删，用户就会拉出一个删不掉的空卡片。撤销只还原结构，不覆盖已生成的产物
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const t = ev.target as HTMLElement | null
      if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return
      if (ev.ctrlKey || ev.metaKey) {
        const k = ev.key.toLowerCase()
        // Ctrl+Y 是 Windows 的重做习惯，与 Ctrl+Shift+Z 同义
        if (k === 'z' || k === 'y') {
          ev.preventDefault()
          if (k === 'y' || ev.shiftKey) onRedo?.()
          else onUndo?.()
        }
        return
      }
      if (ev.key !== 'Delete' && ev.key !== 'Backspace') return
      // 连线优先：选中连线时节点选中态已被清掉，两者不会同时有值
      if (selEdges.length) { ev.preventDefault(); removeEdges(selEdges); return }
      if (selectedFolderId) { ev.preventDefault(); removeFolder(selectedFolderId); return }
      if (selIds.length) { ev.preventDefault(); removeSelected() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selEdges, selIds, selectedFolderId, removeEdges, removeFolder, removeSelected, onUndo, onRedo])

  /** 菜单选型落节点：add=落在弹出点；ref=同时补上与源节点的连线（多选来的就每个源都连一条） */
  const addNode = (type: TapNodeType) => {
    if (!menu) return
    const n = newTapNode(type, (menu.sx - view.x) / view.scale, (menu.sy - view.y) / view.scale)
    // 同一个归宿在一张画布上只能有一个挂载点：两个挂载点抢着写同一个落点，
    // 先跑谁后跑谁就把结果变成随机的。已经有一个了就直接选中它（用户看得见），
    // 不再拖第二个出来。
    if (type === 'mount') {
      // 已经有「待选归宿」的挂载点就不再拖第二个：选中它并直接打开归宿列表
      const pending = nodes.find(x => x.type === 'mount' && !x.mount?.target)
      if (pending) { pickNode(pending.id, false); setEditingMountId(pending.id); setMenu(null); return }
    }
    setNodes(ns => [...ns, n])
    if (menu.kind === 'ref' && menu.froms?.length) {
      // 逐条判合法性：新节点没有任何入边，正常都连得上；成环/重复的直接跳过
      setEdges(es => menu.froms!.reduce((acc, from) =>
        canConnect(acc, from, n.id) ? [...acc, { id: `e-${from}-${n.id}`, from, to: n.id }] : acc,
      [...es]))
    } else if (menu.kind === 'ref' && menu.from) {
      setEdges(es => [...es, menu.side === 'left'
        ? { id: `e-${n.id}`, from: n.id, to: menu.from! }
        : { id: `e-${n.id}`, from: menu.from!, to: n.id, branch: menu.branch }])
    }
    setMenu(null)
    setSelIds([n.id])
  }

  const openAddMenu = () => {
    const host = hostRef.current
    if (!host) return
    const hb = host.getBoundingClientRect()
    // 锚点取 rail 上的加号按钮本身：菜单在按钮上方展开。
    // 水平对齐目标不是菜单边，而是菜单内每行的图标盒：menu padding 12 + item padding 8
    // 共 20px 缩进，再加展开 gap 12，共预扣 32 —— 行图标左缘正好贴齐加号左缘，
    // 菜单整体也随之比加号左移 20px。
    // y 取按钮顶缘，向上翻折后距按钮 12px。
    const bb = host.querySelector('.tap-rail .tap-rail-btn')?.getBoundingClientRect()
    setMenu({
      kind: 'add',
      sx: bb ? bb.left - hb.left - 32 : hb.width / 2,
      sy: bb ? bb.top - hb.top : hb.height - 96,
    })
  }

  // 空白处拖拽 = 框选（不再平移画布：平移交给滚轮 / 空格拖拽 / 中键）
  const { box: marquee, start: startMarquee } = useTapflowMarquee({
    hostRef,
    onSelect: useCallback((b, additive) => {
      const world = {
        x: (b.x - view.x) / view.scale, y: (b.y - view.y) / view.scale,
        w: b.w / view.scale, h: b.h / view.scale,
      }
      const hitIds = nodesInRect(displayNodes, world, heights, TITLE_H)
      // 框选也要能圈到连线：圈住的线同样可删（用户想删的往往就是那一根，
      // 但它的两端节点不该跟着消失）。只圈到线、没圈到节点时节点选中为空——
      // 删除优先级已定：有选中连线就删线。
      const hitEdges = renderEdges.filter(e => {
        const p = edgeAnchors(e, displayById, midY, renderEdges, TITLE_H)
        return !!p && segHitsBox(p.sx, p.sy, p.tx, p.ty, world)
      }).map(e => e.id)
      setSelectedFolderId(null)
      setSelEdges(ids => additive ? [...new Set([...ids, ...hitEdges])] : hitEdges)
      setSelIds(ids => additive ? [...new Set([...ids, ...hitIds])] : hitIds)
    }, [view, displayNodes, displayById, heights, renderEdges, midY]),
    // 拖不动（就是点了一下空白）：取消选中
    onClick: useCallback(() => { setSelectedFolderId(null); setSelIds([]); setSelEdges([]) }, []),
  })
  /** 多选时的选区包围盒（世界坐标）：半透明灰底框 + 工具条都锚在它上面 */
  const selBox = selIds.length > 1
    ? selectionBounds(displayNodes, selIds, heights, TITLE_H) : null
  /** 多选「新建节点」：在选区右侧弹「添加节点」，选完把这些节点全连过去当参考 */
  const openRefsMenu = () => {
    const host = hostRef.current?.getBoundingClientRect()
    if (!host || !selBox) return
    const sx = view.x + (selBox.x + selBox.w + 60) * view.scale
    const sy = view.y + (selBox.y + selBox.h / 2) * view.scale
    setMenu({
      kind: 'ref', froms: [...selIds],
      sx,
      sy,
    })
  }

  return (
    <div
      ref={hostRef}
      className={'tap-canvas' + (zoomMode ? ' zooming' : '') + (panMode ? ' panning' : '')}
      // 空白按下：先让「空格/中键平移」接管；否则起框选。
      // 收起右侧面板（面板是「针对选中节点/本次运行」的，没有对象就不该占地方）；
      // 选中态不在这里清——拖框要保留原选中做加选，纯点击才由 marquee 的 onClick 清掉
      onPointerDown={e => {
        setSelEdges([])
        setSelectedFolderId(null)
        onBgClick?.()
        if (tryPan(e) || e.button !== 0) return
        startMarquee(e)
      }}
      // 双击空白 = 就地弹「添加节点」（灵活添加：不依赖左侧 rail，点哪加哪）。
      // 只认画布背景层（host / world / 参考线）：节点内的双击（文本编辑等）不受影响。
      onDoubleClick={e => {
        if (!(canAdd ?? !!onToggleInspector)) return
        const t = e.target as Element
        if (t.closest('.tap-node, .tap-folder, .tap-add-menu, .tap-overlay, .tap-select-tb, button')) return
        const host = hostRef.current
        if (!host) return
        const r = host.getBoundingClientRect()
        setMenu({ kind: 'add', sx: e.clientX - r.left, sy: e.clientY - r.top })
      }}>
      {/* 列参考线：屏幕空间铺满**整个画布**。线的世界位置 = 每列竖直中线
          (LAYOUT_MARGIN + COLUMN_WIDTH/2)，间隔 = COLUMN_STEP；按当前视图换算成
          屏幕间隔与偏移——平移/缩放到哪儿，线就跟到哪儿，不再是一块固定大小的
          世界坐标布（以前只有 x∈[320, 30320] 那一条带有线，两边是空的）。
          画在 .tap-world 之前：纯背景层，不挡节点、不吃事件。 */}
      {(mode === 'edit' || runGuidesOn) && (
        <div className="tap-column-guides" style={{
          backgroundImage: `repeating-linear-gradient(to right,`
            + ` #7166a829 0, #7166a829 1px, transparent 1px, transparent ${COLUMN_STEP * view.scale}px)`,
          backgroundPosition: `${view.x + (LAYOUT_MARGIN + COLUMN_WIDTH / 2) * view.scale}px 0`,
        }} />
      )}
      <div className="tap-world" style={{
        transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
        '--tap-title-counter-scale': titleCounterScale(view.scale),
      } as CSSProperties}>
        {/* 组框（画在节点下面）：半透明灰底，按下选中整组、拖动整组挪 */}
        {[...groups, ...(mode === 'edit' ? nodes
          .filter(n => n.type === 'loop' && (n.loop?.body?.length ?? 0) > 0)
          .map(n => ({ id: `loop-body:${n.id}`, name: `循环体 · ${n.title}`, nodeIds: n.loop!.body! }))
          : [])].map(g => {
          const box = selectionBounds(displayNodes, g.nodeIds, heights, TITLE_H)
          return box && (
            <TapflowGroupBox
              key={g.id} group={g} box={box} selected={sameIds(g.nodeIds, selIds)}
              onPick={pickIds} onDrag={moveBy} />
          )
        })}

        {/* 连线画在组框**之上**、节点之下：组框是一整块带半透明底的矩形，它自己也要接
            指针事件（拖动整组）——排在它下面的话，组内那段连线永远点不到，用户看到的就是
            「点线没反应」。线只在 stroke 上命中（svg 本身 pointer-events: none），
            提到组框上层不会挡住拖组。 */}
        <TapflowEdges
          edges={renderEdges} byId={displayById} midY={midY} heights={heights} titleH={TITLE_H}
          selected={selEdges}
          onSelect={(id, additive) => {
            // 点线 = 只选它（Shift/⌘ 加选）；同时清掉节点选中，避免「到底删哪个」含糊
            setSelEdges(ids => additive ? [...new Set([...ids, id])] : [id])
            if (!additive) { setSelIds([]); setSelectedFolderId(null) }
          }} />

        {/* 当前选区的半透明灰框：框选完还看得见「圈住的是这一块」；打组后由组框接管 */}
        {selBox && !selGroup && (
          <div
            className="tap-sel-region"
            style={{
              left: selBox.x - GROUP_PAD, top: selBox.y - GROUP_PAD,
              width: selBox.w + GROUP_PAD * 2, height: selBox.h + GROUP_PAD * 2,
            }} />
        )}

        {displayNodes.map(n => (
          <TapflowNode
            key={n.id} node={n} title={resolveTitle(n.title, titleVals)}
            flowName={n.bind?.subflow?.slug
              ? flows.find(f => f.slug === n.bind!.subflow!.slug)?.name
              : undefined}
            mode={mode} selected={selIds.includes(n.id)}
            dropTarget={dropId === n.id}
            onSelect={pickNode} onMeasure={onMeasure}
            onDrag={drag} onDragEnd={snapToColumn} onResize={resizeNode} onPortDrag={startPortDrag}
            editing={editId === n.id} onEditDone={() => setEditId(null)}
            onUpload={uploadRefImage} onRemoveRefImage={removeRefImage}
            loopPreview={n.type === 'loop' || n.loop?.aggregate
              ? (mode === 'run'
                ? (runtimeLoopChildren.get(n.id) ?? [])
                : (n.loop?.body ?? []).map(id => byId.get(id)).filter(Boolean) as TapNode[])
                .slice(0, 3)
                .map(child => ({ id: child.id, src: child.src, title: child.title }))
              : undefined}
            loopChildCount={n.type === 'loop' || n.loop?.aggregate
              ? (mode === 'run'
                ? (runtimeLoopChildren.get(n.id) ?? [])
                  .filter(child => child.runtime?.childNodeKey !== 'pending').length
                : (n.loop?.body?.length ?? 0))
              : undefined}
            // 手改正文 → 打冻结标记：下次运行整段覆盖该节点产出并落库，
            // 模型不再跑（与生成条提示词的手编冻结同一套语义）
            onText={(id, text) => setNodes(ns => ns.map(x =>
              x.id === id ? { ...x, text, textEdited: true } : x))}
            // 挂载点：未选归宿/修改中显示归宿点选列表；上游产物实时回显；
            // 入口归宿的挂载点还吃一份「进画布就有的当前产物」初始回显
            upstreamUrl={n.type === 'mount' ? mountUpstreamUrl(n.id) : undefined}
            upstreamTitle={n.type === 'mount' ? mountUpstreamTitle(n.id) : undefined}
            initialUrl={n.type === 'mount' && n.mount?.target === entryMount?.target
              ? entryMount?.url : undefined}
            takenTargets={n.type === 'mount'
              ? nodes.filter(x => x.type === 'mount' && x.id !== n.id && x.mount?.target)
                  .map(x => x.mount!.target)
              : undefined}
            mountEditing={editingMountId === n.id}
            onMountPick={pickMountTarget}
            onMountEdit={id => setEditingMountId(id)} />
        ))}

        {folders.map(folder => (
          <TapflowFolderNode
            key={folder.id}
            folder={folder}
            members={folder.nodeIds.map(id => byId.get(id)).filter(Boolean) as TapNode[]}
            selected={selectedFolder?.id === folder.id}
            onSelect={() => {
              setSelEdges([])
              setSelIds([])
              setSelectedFolderId(folder.id)
            }}
            onDrag={(dx, dy) => moveFolder(folder.id, dx, dy)}
            onDragEnd={() => snapFolderToColumn(folder.id)}
          />
        ))}
      </div>

      {selectedFolder && (
        <div
          className="tap-overlay above"
          style={{
            left: view.x + (selectedFolder.x + selectedFolder.w / 2) * view.scale,
            top: view.y + (selectedFolder.y + TITLE_H) * view.scale,
          }}
          onPointerDown={e => e.stopPropagation()}>
          <div className="tap-node-toolbar tap-folder-toolbar">
            <button
              type="button"
              className="tap-tool"
              title={selectedFolder.expanded ? '收起文件夹内容' : '展开文件夹内容'}
              aria-label={selectedFolder.expanded ? '收起文件夹内容' : '展开文件夹内容'}
              onClick={() => toggleFolder(selectedFolder.id)}>
              <Icon name={selectedFolder.expanded ? 'collapse' : 'grid'} />
            </button>
            <button
              type="button"
              className="tap-tool"
              title="打散文件夹"
              aria-label="打散文件夹"
              onClick={() => unpackFolder(selectedFolder.id)}>
              <Icon name="ungroup" />
            </button>
          </div>
        </div>
      )}

      {/* 框选矩形（屏幕空间，不随缩放变粗） */}
      {marquee && (
        <div className="tap-marquee"
          style={{ left: marquee.x, top: marquee.y, width: marquee.w, height: marquee.h }} />
      )}

      {/* 选中连线的提示条：选中反馈必须看得见——「点线没反应」和
          「选中了但按钮没跳出来」在用户那边长得一模一样。 */}
      {selEdges.length > 0 && (
        <div className="tap-edge-tip">
          <Icon name="link" />
          已选中 {selEdges.length} 条连线
          <span className="k">Delete</span>
          或点线上的 ✕ 删除
        </div>
      )}

      {/* 多选工具条：锚在选区上边中点（屏幕空间，固定尺寸） */}
      {selBox && (
        <div
          className="tap-overlay above"
          // 锚在灰框上沿（选区外扩 GROUP_PAD），不压住框本身
          style={{
            left: view.x + (selBox.x + selBox.w / 2) * view.scale,
            top: view.y + (selBox.y - GROUP_PAD - (selGroup ? 18 : 0)) * view.scale,
          }}
          onPointerDown={e => e.stopPropagation()}>
          <TapflowSelectToolbar
            count={selIds.length}
            // 两态都给：运行态从端口就能拉出新节点，工具条这几个再挡着只会前后不一致
            grouped={!!selGroup} onGroup={toggleGroup}
            onFolder={createFolder}
            onLoop={mode === 'edit' && !selIds.some(id => byId.get(id)?.type === 'loop' || loopBodyIds.has(id))
              ? makeLoop : undefined}
            onNewNode={openRefsMenu}
            onDuplicate={duplicateSelected}
            onRemove={removeSelected}
            onClear={() => setSelIds([])} />
        </div>
      )}

      {/* 圆点拖出中的临时虚线（屏幕空间）；悬在可连节点上时实线化，示意「松手即连」 */}
      {tempEdge && byId.has(tempEdge.from) && (() => {
        return (
          <svg className={'tap-temp-edge' + (dropId ? ' will-link' : '')}>
            <path d={bezierPath(tempEdge.originX, tempEdge.originY, tempEdge.sx, tempEdge.sy)} />
          </svg>
        )
      })()}

      {/* 选中连线的删除按钮：锚在线中点（屏幕空间，不随缩放变大）。两态都可用。
          多选时每条线各一个 ✕；Delete 一次删光。 */}
      {selEdges.map(id => {
        const e = renderEdges.find(x => x.id === id)
        const a = e && displayById.get(e.from), b = e && displayById.get(e.to)
        if (!e || !a || !b) return null
        const m = edgeMid(a.x + a.w, midY(a), b.x, midY(b))
        return (
          <button
            key={id}
            type="button" className="tap-edge-del" title="删除连线"
            style={{ left: view.x + m.x * view.scale, top: view.y + m.y * view.scale }}
            onPointerDown={ev => ev.stopPropagation()}
            onClick={() => removeEdges([id])}>
            <Icon name="cross" />
          </button>
        )
      })}

      {/* 炸开浮层（运行态）：媒体/生成类节点，以及走 LLM 的文本、质检节点——
          它们同样是「给提示词让模型产出」，理应有生成输入条。
          屏幕空间固定尺寸，只按视图变换换算锚点，不随画布缩放 */}
      {mode === 'run' && sel && canExpand(sel) && (
        <div
          className="tap-overlay above"
          // 锚「卡片顶边」而不是节点顶边：标题用反向缩放保持屏幕尺寸，
          // 工具条也在屏幕空间固定尺寸，两者都只跟随卡片位置移动。
          style={{
            left: view.x + (sel.x + sel.w / 2) * view.scale,
            top: view.y + (sel.y + TITLE_H) * view.scale,
          }}
          onPointerDown={e => e.stopPropagation()}>
          <TapflowNodeToolbar
            onInspect={onToggleInspector} inspectorOpen={inspectorOpen}
            onRedit={sel.type === 'mount' ? () => setEditingMountId(sel.id) : undefined}
            onCopy={sel.type === 'mount' ? undefined : () => sel.text || sel.video || sel.src || ''}
            onEdit={sel.type === 'text' ? () => setEditId(sel.id) : undefined}
            // 重新读取 = 零副作用地把库里那份产物再取一次（连手改的也丢弃、以库为准），
            // 与「智能生成」分开：只查库不会产生任何费用
            onReload={onReload ? () => onReload(sel.id) : undefined}
            // 智能生成只是把下方生成条唤出来；真正重跑由生成条发起
            // （默认一律缺才跑，这是强制重跑单个节点的唯一入口）
            onRegen={sel.type === 'text' || MEDIA_TYPES.includes(sel.type)
              || (sel.type === 'flow' && sel.smart)
              ? () => setRegenId(sel.id) : undefined}
            onCrop={MEDIA_TYPES.includes(sel.type)
              ? () => sel.src && setMedia({ mode: 'crop', src: sel.src }) : undefined}
            onExpand={MEDIA_TYPES.includes(sel.type)
              ? () => (sel.src || sel.video) && setMedia({ mode: 'view', src: sel.src ?? '', video: sel.video })
              : undefined} />
        </div>
      )}
      {/* 编排态：选中节点上方只浮属性工具条——编排台的属性面板不再自动弹，
          点击这里才开（生产态运行态则在上方工具条里同享这个属性 icon） */}
      {mode === 'edit' && sel && canExpand(sel) && onToggleInspector && (
        <div
          className="tap-overlay above"
          style={{
            left: view.x + (sel.x + sel.w / 2) * view.scale,
            top: view.y + (sel.y + TITLE_H) * view.scale,
          }}
          onPointerDown={e => e.stopPropagation()}>
          <TapflowNodeToolbar
            onInspect={onToggleInspector} inspectorOpen={inspectorOpen}
            onRedit={sel.type === 'mount' ? () => setEditingMountId(sel.id) : undefined} />
        </div>
      )}
      {mode === 'run' && sel && canExpand(sel)
        && (MEDIA_TYPES.includes(sel.type) || regenId === sel.id) && (
        <div
          className="tap-overlay below"
          style={{ left: view.x + (sel.x + sel.w / 2) * view.scale, top: view.y + (sel.y + TITLE_H + (heights[sel.id] ? heights[sel.id] - TITLE_H : sel.h)) * view.scale }}
          onPointerDown={e => e.stopPropagation()}>
          <TapflowPromptBar
            modality={sel.modality}
            gen={withProjectParams(sel.gen ?? defaultGen(sel.type),
              nodes.find(n => n.type === 'start')?.project)}
            inherited={projectParams(nodes.find(n => n.type === 'start')?.project)}
            stage={sel.stage}
            onRegen={onRegen ? () => onRegen(sel.id) : undefined} regenBusy={regenBusy}
            refNodes={refIdsOf(sel).map(id => byId.get(id)).filter(Boolean)
              .map(u => ({ id: u!.id, title: u!.title, src: u!.src }))}
            mentionCandidates={(() => {
              const cur = refIdsOf(sel)
              return upstreamNodes(sel.id, nodes, edges).map(u => {
                const at = cur.indexOf(u.id)
                // 编号与参考图顺序一致：已挂的用现有位置，新选的排在尾部——
                // 选中后插入的 @图片N 才能对上「第 N 张参考图」
                return { id: u.id, title: u.title, src: u.src, no: at >= 0 ? at + 1 : cur.length + 1 }
              })
            })()}
            onMentionPick={id => { if (!refIdsOf(sel).includes(id)) setRefIds(sel.id, [...refIdsOf(sel), id]) }}
            onRefRemove={id => setRefIds(sel.id, refIdsOf(sel).filter(x => x !== id))}
            onRefAdd={() => setRefMenuOpen(v => !v)}
            businessRefs={businessRefs.map(r => ({ id: r.id, name: r.name, src: r.url }))}
            onBusinessRefAdd={projectId && onBusinessRefAdd
              ? () => setBusinessAssetsOpen(v => !v) : undefined}
            onBusinessRefRemove={onBusinessRefRemove
              ? id => void onBusinessRefRemove(id) : undefined}
            refMenu={refMenuOpen && (
              <TapPickMenu
                groups={[{
                  title: '上游节点',
                  items: upstreamNodes(sel.id, nodes, edges)
                    .filter(u => !refIdsOf(sel).includes(u.id))
                    .map(u => ({ value: u.id, label: u.title })),
                }]}
                onPick={v => setRefIds(sel.id, [...refIdsOf(sel), v])}
                onClose={() => setRefMenuOpen(false)} />
            )}
            onSend={r => { setRefMenuOpen(false); onSend?.(sel.id, r) }}
            textOnly={sel.type === 'text' || sel.type === 'qc' || sel.type === 'flow'}
            onIssueChange={(index, value) => setNodes(ns => ns.map(n => n.id === sel.id && n.stage
              ? {
                  ...n,
                  stage: {
                    ...n.stage,
                    issues: (n.stage.issues ?? []).map((issue, current) =>
                      current === index ? value : issue),
                  },
                }
              : n))}
            onPromptChange={v => setNodes(ns => ns.map(n => n.id === sel.id
              // 手改即冻结：此后装配/预检都不再覆盖这段（prompt_fields 的 *_edited 语义）
              ? { ...n, gen: { ...defaultGen(n.type), ...n.gen, prompt: v, edited: true } }
              : n))} />
        </div>
      )}

      {businessAssetsOpen && projectId && onBusinessRefAdd && (
        <CanvasAssetPanel pid={projectId} exclude={businessRefs.map(r => r.name)}
          onPick={asset => { void onBusinessRefAdd(asset); setBusinessAssetsOpen(false) }}
          onClose={() => setBusinessAssetsOpen(false)} />
      )}

      {menu && (
        <TapflowAddMenu
          refMode={menu.kind === 'ref'} x={menu.sx} y={menu.sy}
          onPick={addNode} onClose={() => setMenu(null)} />
      )}
      {media && <TapflowMediaOverlay src={media.src} video={media.video} mode={media.mode} onClose={() => setMedia(null)} />}

      {/* 「新建节点」由外层单独授权（canAdd）：生产态也能建——建出来的节点会存进
          本对象的专属画布、能配能跑。属性按钮则另有一套判据（只对自己建的节点开） */}
      <TapflowRail
        onAdd={(canAdd ?? !!onToggleInspector) ? openAddMenu : undefined}
        onAssets={projectId && onBusinessRefAdd ? () => setBusinessAssetsOpen(v => !v) : undefined}
        onInstruct={onInstruct}
        onRunNow={onRunNow}
        onRun={onRun} />
      <TapflowZoomBar
        helpOn={helpOpen} onHelp={() => setHelpOpen(v => !v)}
        onRelayout={() => onRelayout?.()}
        guidesOn={runGuidesOn}
        onToggleGuides={mode === 'run' ? () => setRunGuidesOn(v => !v) : undefined}
        onZoomIn={() => setScaleCentered(view.scale * 1.25)}
        onZoomOut={() => setScaleCentered(view.scale / 1.25)}
        onFullscreen={() => {
          // 整页全屏（不是只把画布容器全屏）
          if (document.fullscreenElement) void document.exitFullscreen()
          else void document.documentElement.requestFullscreen?.()
        }} />
      {helpOpen && <TapflowHelp onClose={() => setHelpOpen(false)} />}
    </div>
  )
}
