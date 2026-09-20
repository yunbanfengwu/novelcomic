import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { SceneGroup } from '../../api'
import { openSceneGroupCanvas } from '../../lib/tapflowEntries'
import { type SceneStage } from '../../lib/sceneSheet'
import { noteEnqueued } from '../../lib/taskCenter'

/** 场景组（空间锚定）：分组数据加载 + 空间规划触发 + 两阶段场景图「人工确认→生成」。
 *
 * 分组与站位链由拆镜后 scene_blocking 任务自动产出（镜级生成前置也会兜底补齐）。
 * 两阶段各有自己的提示词与成图：① 空场景基准图（无人，钉死几何与光）→ ② 角色站位图
 * （以基准图为参考图，只加人）。出站位图时后端会自动先补基准图，不必手动按顺序点。 */
export function useSceneGroups(pid: number, chapterId: number) {
  const [groups, setGroups] = useState<SceneGroup[]>([])
  const reloadGroups = useCallback(() => {
    api.sceneGroups(pid, chapterId).then(r => setGroups(r.groups)).catch(console.error)
  }, [pid, chapterId])
  useEffect(() => { reloadGroups() }, [reloadGroups])

  // 手动（重）跑场景空间规划：指纹缓存命中的组自动跳过（剧本没改不重烧）。
  // force=true 忽略指纹强制重规划——旧单阶段数据补 empty_* 两阶段字段只能走这条。
  const runBlocking = async (force = false) => {
    try {
      const { task_id } = await api.runSceneBlocking(pid, chapterId, force)
      noteEnqueued(pid, { id: task_id, kind: 'scene_blocking', node_id: chapterId })
    } catch (e) { alert(String(e)) }
  }

  const taskKind = (stage: SceneStage) =>
    stage === 'empty' ? 'gen_scene_empty' : 'gen_scene_sheet'

  // 某一阶段的场景组画布（画布收编 2026-09-18）：scene-group-canvas 内先空场景基准图
  // 再站位图（缺前段后端自动补跑，subflow/missing_deps 原生支持），提示词在画布内改
  const openSheet = (g: SceneGroup, stage: SceneStage = 'sheet') => {
    void stage
    openSceneGroupCanvas(pid, chapterId, g.seg)
  }

  // 一键生成（图块上的高频入口）：不带提示词入参，后端用组条目已装配的提示词；
  // 要改提示词/换参考图走 openSheet 的画布
  const genSheet = async (g: SceneGroup, stage: SceneStage = 'sheet') => {
    try {
      const { task_id } = await api.genSceneSheet(pid, chapterId, g.seg, undefined, stage)
      noteEnqueued(pid, { id: task_id, kind: taskKind(stage), node_id: chapterId })
    } catch (e) { alert(String(e)) }
  }
  return { groups, reloadGroups, runBlocking, openSheet, genSheet }
}
