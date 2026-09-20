// 画布上**手工新建的节点** → 后端能跑起来的 config（唯一实现）。
//
// 模板里的节点，执行语义是种子 SQL 写好的（assemble/step/skip_if/payload 一应俱全）；
// 从端口拖出来的那些没有底稿，画布必须自己把「跑起来需要的那几项」补齐，否则落下来
// 就是一张跑到它必报错的空壳卡——这正是「拖出来的节点毫无作用」的根因。
//
// 补的是三件事，缺一不可：
//   1. step      —— 入队哪个生成步骤（自由出图 gen_canvas_image）
//   2. payload   —— 带上节点 id 与标题，产物落附件时记得住"这是画布哪张卡出的"
//   3. skip_if   —— 「缺才跑」的探针。没有它，整图每跑一遍就重出一次这张图，真金白银。
//      探的是本节点自己上次出的那张（meta.node = 节点 id），与 gen_element_sheet 探
//      要素 sheet_url 是同一套语义，只是产物归属不同。
import type { TapNode } from './tapflowData'

/** 自由出图执行体（后端 steps.CanvasImageStep）：提示词 + 上游参考图 → 图 → 项目附件。
 * 刻意不复用 gen_element_sheet：那条会回写要素的正式设定图，
 * 用户拖出来试个构图就把正式设定图换掉，不可接受。 */
export const TAP_CANVAS_IMAGE_STEP = 'gen_canvas_image'

/** 自由出视频执行体（后端 steps.CanvasVideoStep，2026-09-18 补，与自由出图同构）：
 * 提示词 + 上游连线来的首/尾帧 → 一段视频 → 项目附件。刻意不复用 gen_video：
 * 那条焊在镜级上下文里（before 读镜 meta、next 回写镜头正式视频），
 * 画布上的视频卡没有镜可挂，随手绑只会跑一半才炸。 */
export const TAP_CANVAS_VIDEO_STEP = 'gen_canvas_video'

/** 本节点上次出的那张图（画布自由节点的「缺才跑」探针）。
 * project_id 取不到（这张画布的入参里没有项目）时，后端把 args 里的 null 当作
 * 「依赖值还没有」→ 视为缺 → 照常生成，退化成每次都跑，不会误跳过。 */
const LAST_IMAGE_SQL =
  "SELECT url FROM content_attachments WHERE project_id=$1 AND meta->>'node'=$2 "
  + "ORDER BY id DESC LIMIT 1"

/** 本节点上次出的那段视频。多一个 kind='video'：同一张卡历史上有过图（比如改过类型），
 * 不限定产物形态会把旧图当「已出片」误跳过。 */
const LAST_VIDEO_SQL =
  "SELECT url FROM content_attachments WHERE project_id=$1 AND kind='video' AND meta->>'node'=$2 "
  + "ORDER BY id DESC LIMIT 1"

/** 手工新建的生成节点要补的执行语义。base 里已经有的一律不覆盖——
 * 用户可能已经在属性面板里改过执行体，画布不该每次保存又把它按回默认值。 */
export function customGenConfig(node: TapNode, base: Record<string, unknown>,
                                projectKey: string): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (!base.payload) {
    out.payload = { node_key: node.id, title: node.title }
  }
  // 只有走画布自由生成（图/视频）的节点才配探针：换了别的执行体（比如用户挑了
  // gen_element_sheet），产物落点就不是"画布附件"了，拿这条 SQL 去探必然探空
  const step = node.bind?.step ?? base.step
  const probe = step === TAP_CANVAS_IMAGE_STEP ? LAST_IMAGE_SQL
    : step === TAP_CANVAS_VIDEO_STEP ? LAST_VIDEO_SQL : undefined
  if (!base.skip_if && probe) {
    out.skip_if = {
      sql: probe,
      args: [`{{input.${projectKey}}}`, node.id],
      reason: '这个节点已经生成过，跳过（选中它 → 生成条「发送」可强制重出）',
    }
  }
  return out
}
