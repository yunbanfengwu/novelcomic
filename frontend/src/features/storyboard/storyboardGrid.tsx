import { openStoryboardGridCanvas as openWindow } from '../../lib/tapflowEntries'

/** 打开分镜故事板画布（画布收编 2026-09-18）：宫格生成迁入 tapflow
 * （storyboard-grid-canvas：board=N 单张重出，缺省整章全部）。
 * shotId 给定时换算成所在板号聚焦；「生成故事板」在画布内完成。 */
export function openStoryboardGridCanvas(
  pid: number, chapterId: number, focus?: { shotId?: number; board?: number },
) {
  void focus?.shotId   // 焦点镜不再单独定位：整章宫格同一张画布（单张重出传 board）
  openWindow(pid, chapterId, focus?.board)
}
