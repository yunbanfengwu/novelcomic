import type { TaskInfo } from '../api'

// ═══════════ 任务展示口径：kind/status 的人话标签（任务队列面板等共用）═══════════

export const TASK_KIND_LABEL: Record<string, string> = {
  breakdown_chapter: '拆分镜',
  expand_shot_details: '详细分镜',
  scene_blocking: '场景空间规划',
  gen_scene_empty: '场景空场景基准图',
  gen_scene_sheet: '场景角色站位图',
  gen_prompts: '提示词+质检',
  gen_keyframe: '首帧图',
  gen_last_keyframe: '尾帧图',
  gen_video: '视频生成',
  gen_overview_grid: '总览宫格',
  gen_element_sheet: '要素设定图',
  gen_voice_samples: '音色样本',
  gen_outline_md: '架构大纲',
  gen_project_info: '基本信息初拟',
  gen_element_kinds: '要素类型判定',
}

export const TASK_STATUS_META: Record<string, { label: string; tone: 'wait' | 'run' | 'ok' | 'err' }> = {
  waiting_deps: { label: '等待前置', tone: 'wait' },
  pending: { label: '排队中', tone: 'wait' },
  running: { label: '执行中', tone: 'run' },
  waiting_external: { label: '云端生成中', tone: 'run' },
  done: { label: '完成', tone: 'ok' },
  failed: { label: '失败', tone: 'err' },
  canceled: { label: '已取消', tone: 'err' },
}

/** 任务的对象标注：镜N / 章节标题 / 要素（无节点任务只显示类型） */
export function taskTargetLabel(t: TaskInfo): string {
  if (t.node_kind === 'shot') return t.shot_no ? `镜${t.shot_no}` : (t.node_title ?? '')
  if (t.node_title) return t.node_title
  if (t.element_id) return `要素#${t.element_id}`
  return ''
}

export interface TaskNode { task: TaskInfo; children: TaskNode[] }

/** 依赖边（parents）→ 渲染树。多父子任务（如被首帧与视频共享的提示词任务）
 * 在每个父下各渲染一次——保住"谁在等它"的依赖语义，典型深度 ≤3 不会爆炸。 */
export function buildTaskForest(tasks: TaskInfo[]): TaskNode[] {
  const ids = new Set(tasks.map(t => t.id))
  const childrenOf = (id: number) => tasks.filter(t => t.parents.includes(id))
  const build = (t: TaskInfo, seen: Set<number>): TaskNode => ({
    task: t,
    // seen 防御后端意外成环（正常不可能）：环上节点只展开一次
    children: seen.has(t.id) ? [] : childrenOf(t.id).map(c => build(c, new Set(seen).add(t.id))),
  })
  return tasks
    .filter(t => !t.parents.some(p => ids.has(p)))
    .sort((a, b) => b.id - a.id)
    .map(t => build(t, new Set()))
}
