import { openBatchKeyframeCanvas } from '../../lib/tapflowEntries'

/** 打开批量首帧画布（总览「批量首帧」入口）：与分镜故事板同一入口形态。
 * 画布内整集分镜按场景切组——计划节点列批次、loop 逐批 gen_keyframes_group。
 * seg 给定时只装该场景（场景组面板「组内分镜 · 画布」入口）。 */
export function openBatchKeyframesCanvas(pid: number, chapterId: number, seg?: number) {
  openBatchKeyframeCanvas(pid, chapterId, seg)
}
