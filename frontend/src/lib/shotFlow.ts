// 单镜生产链路投影：从 Shot 数据推导各环节状态（空/在途/完成/异常）。
// 纯推导、零存储——画布/状态条每次渲染直接由生产数据算出，永不与真实状态脱节。
import type { GenState, PromptReview, Shot } from '../api'

export type ShotFlowStatus = 'empty' | 'running' | 'done' | 'warn'

/** 环节动作：由挂载方映射到既有生成入口（重做设计/装配提示词/编辑弹框/一键视频）。 */
export type ShotFlowAction =
  | { kind: 'redesign' }
  | { kind: 'prompts'; only: 'image' | 'video' }
  | { kind: 'editor'; target: 'image' | 'video' | 'last' }
  | { kind: 'video' }

export interface ShotFlowNode {
  id: string
  label: string
  status: ShotFlowStatus
  detail: string
  optional?: boolean
  action?: ShotFlowAction
}

const genOf = (shot: Shot, key: string): GenState | undefined => shot.meta.gen?.[key]

const isBusy = (state?: GenState) =>
  !!state && ['waiting_deps', 'pending', 'running'].includes(state.state)

const reviewFailed = (review?: PromptReview) => !!review && review.合格 === false

function promptNode(
  shot: Shot, id: string, label: string, text: string | undefined,
  review: PromptReview | undefined, only: 'image' | 'video',
): ShotFlowNode {
  const gen = genOf(shot, 'prompts')
  if (isBusy(gen)) return { id, label, status: 'running', detail: '装配质检中', action: { kind: 'prompts', only } }
  if (reviewFailed(review)) {
    return {
      id, label, status: 'warn',
      detail: `质检不合格：${(review?.问题 ?? []).join('；') || '未达标'}`,
      action: { kind: 'prompts', only },
    }
  }
  if (text?.trim()) return { id, label, status: 'done', detail: '已装配', action: { kind: 'prompts', only } }
  return { id, label, status: 'empty', detail: '未装配（点击生成）', action: { kind: 'prompts', only } }
}

function mediaNode(
  shot: Shot, id: string, label: string, url: string | undefined,
  genKey: string, action: ShotFlowAction, optional = false,
): ShotFlowNode {
  const gen = genOf(shot, genKey)
  if (isBusy(gen)) return { id, label, status: 'running', detail: '生成中', action, optional }
  if (gen?.state === 'failed') {
    return { id, label, status: 'warn', detail: `生成失败：${gen.error || '未知原因'}`, action, optional }
  }
  if (url) return { id, label, status: 'done', detail: '已生成', action, optional }
  return { id, label, status: 'empty', detail: optional ? '可选（未生成）' : '未生成（点击补齐）', action, optional }
}

/** 推导单镜的固定生产链路节点（顺序即依赖顺序）。 */
export function deriveShotFlow(shot: Shot): ShotFlowNode[] {
  const meta = shot.meta
  const cuts = meta.cuts ?? []
  const refs = meta.required_refs ?? []
  const missingRefs = refs.filter(r => !r.url)
  const script: ShotFlowNode = (shot.summary?.trim() || meta.action?.trim())
    ? { id: 'script', label: '分镜脚本', status: 'done', detail: '拆镜完成', action: { kind: 'redesign' } }
    : { id: 'script', label: '分镜脚本', status: 'empty', detail: '无脚本（点击重做设计）', action: { kind: 'redesign' } }
  const cutNode: ShotFlowNode = cuts.length
    ? {
        id: 'cuts', label: '镜头切分', status: 'done',
        detail: cuts.length > 1 ? `组内 ${cuts.length} 切` : '连续单镜',
        action: { kind: 'redesign' },
      }
    : { id: 'cuts', label: '镜头切分', status: 'empty', detail: '未设计切分', action: { kind: 'redesign' } }
  const refNode: ShotFlowNode = !refs.length
    ? { id: 'refs', label: '参考图', status: 'empty', detail: '未装配要素', action: { kind: 'editor', target: 'image' } }
    : missingRefs.length
      ? {
          id: 'refs', label: '参考图', status: 'warn',
          detail: `缺 ${missingRefs.length} 张：${missingRefs.map(r => r.name).join('、')}`,
          action: { kind: 'editor', target: 'image' },
        }
      : { id: 'refs', label: '参考图', status: 'done', detail: `${refs.length} 项要素齐备`, action: { kind: 'editor', target: 'image' } }
  return [
    script,
    cutNode,
    refNode,
    promptNode(shot, 'image_prompt', '首帧提示词',
      meta.image_prompt || meta.image_prompt_user, meta.prompt_review_image, 'image'),
    mediaNode(shot, 'keyframe', '首帧', meta.keyframe_url, 'keyframe', { kind: 'editor', target: 'image' }),
    promptNode(shot, 'video_prompt', '视频提示词',
      meta.video_prompt || meta.video_prompt_user, meta.prompt_review, 'video'),
    mediaNode(shot, 'last_frame', '尾帧', meta.last_frame_url, 'last_keyframe',
      { kind: 'editor', target: 'last' }, true),
    mediaNode(shot, 'video', '视频', meta.video_url, 'video', { kind: 'video' }),
  ]
}
