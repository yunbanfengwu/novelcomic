// 生产态画布的自动保存：**任何结构改动都落进「这个对象的专属画布」**。
//
// 为什么是自动而不是给个保存按钮：业务用户是点着某个场景进来出图的，不是来编排的。
// 他拖出一个节点、挪一下位置，那就是他对**这个场景**的编排意图——关掉弹窗就没了
// 是纯粹的数据丢失（这正是改造前的行为：拖出来的节点毫无痕迹）。
//
// 只认**结构与配置**的变化，不认运行产物：跑完一轮，节点上会填进图片 url、正文、
// 质检徽标、生成条里装配出来的提示词……那些是运行结果，不是编排。把它们算进指纹，
// 每跑一步都会触发一次保存，白存几十个版本还把运行态的临时值焊进图里。
import { useEffect, useRef } from 'react'
import type { TapEdge, TapNode } from './tapflowData'

const DEBOUNCE_MS = 900
/** 开画后的「安顿期」：这段时间内的变化算自动布局，不算用户编辑。
 * 画布挂载后会按测得的卡片高度整图重排一次坐标（TapflowCanvas 的 autoLayout），
 * 那是渲染的一部分，不是"用户拖动了节点"——不豁免的话，光是打开画布就会
 * fork 出一份什么都没改的实例。人要看清画面再按住拖，远不止这点时间。 */
const SETTLE_MS = 1500

/** 结构指纹：id/类型/坐标/尺寸/标题/连线，加上「配得动的那几项」（执行体、缺才跑、
 * 手选参考、手编冻结的提示词与正文）。跑出来的 src/text/stage/status 一概不进指纹。 */
function signature(nodes: TapNode[], edges: TapEdge[]): string {
  const ns = nodes.map(n => [
    n.id, n.type, Math.round(n.x), Math.round(n.y), n.w, n.h, n.title,
    n.custom ? 1 : 0, n.hideInRun ? 1 : 0,
    n.bind?.step ?? '', n.bind?.subflow?.slug ?? '', n.bind?.onlyMissing ? 1 : 0,
    n.bind?.charter ?? '', (n.bind?.skills ?? []).join(','), (n.bind?.kb ?? []).join(','),
    (n.bind?.tools ?? []).join(','), JSON.stringify(n.bind?.qc ?? null),
    (n.gen?.refNodes ?? []).join(','),
    // 卡上上传的静态参考图是作者态（保存时落 config.reference_images + payload），
    // 不进指纹的话「只传了几张图、没动结构」就不触发保存，关窗即丢
    JSON.stringify(n.refImages ?? null),
    // 参考图节点（upload/value）的图本体也是作者态；出图节点的 src 是运行产物，不进指纹
    n.type === 'upload' ? (n.src ?? '') : '',
    // 手编冻结的那两段是编排意图（下次运行整段覆盖装配），要存
    n.gen?.edited ? n.gen.prompt : '', n.textEdited ? n.text ?? '' : '',
    JSON.stringify(n.params?.map(p => [p.k, p.label, p.required ? 1 : 0]) ?? null),
  ].join(''))
  return [...ns, '|', ...edges.map(e => `${e.from}>${e.to}`).sort()].join('')
}

/**
 * 画布结构一变就防抖保存。
 * @param enabled  生产态且是真实流程才开（演示画布没有 slug，存不了）
 * @param save     统一保存入口（useTapflowSave.save，内部按需先 fork 出实例）
 */
export function useTapflowAutosave(
  enabled: boolean, nodes: TapNode[], edges: TapEdge[],
  save: (nodes: TapNode[], edges: TapEdge[]) => Promise<void>,
) {
  const sig = signature(nodes, edges)
  // 打开画布时的形态是基线：它就是库里那份，不该一进来就存一遍（更不该因此 fork 出
  // 一堆「什么都没改」的实例）。自动布局也在首帧改坐标，一并被基线吸收。
  const opened = useRef(Date.now())
  const last = useRef<string | null>(null)
  const live = useRef({ nodes, edges, save })
  live.current = { nodes, edges, save }
  // 「人碰过没有」——安顿期之外的第二道闸。自动布局、热重载、预检回填这些都不带
  // 指针事件；没人按过就不可能是编辑，再怎么变都只更新基线。
  // （实测过一次反例：开着画布改代码触发 HMR，重排坐标把一份"什么都没改"的实例存了出来。）
  const touched = useRef(false)
  useEffect(() => {
    if (!enabled) return
    const on = () => { touched.current = true }
    window.addEventListener('pointerdown', on, true)
    return () => window.removeEventListener('pointerdown', on, true)
  }, [enabled])

  useEffect(() => {
    if (!enabled) return
    if (sig === last.current) return
    if (!touched.current || Date.now() - opened.current < SETTLE_MS) { last.current = sig; return }
    const t = setTimeout(() => {
      last.current = sig
      void live.current.save(live.current.nodes, live.current.edges)
    }, DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [enabled, sig])
}
