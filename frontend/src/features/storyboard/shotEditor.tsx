import type { Element, Shot } from '../../api'
import { playAudio } from '../../lib/audioPlayer'
import { openLightbox } from '../../lib/lightbox'
import { openElementPreview, closeElementPreview } from '../../lib/elementPreview'
import { LightboxInfo } from '../../components/LightboxInfo'
import { ElementPreview } from '../projects/ElementPreview'
import type { EditRef } from '../../lib/kinds'
import type { useTapflowWindowReload } from '../../lib/tapflowEntries'

export type ShotEditor = {
  busy: boolean
  aiBusyImage: boolean
  aiBusyVideo: boolean
  aiBusyLast: boolean
  imageRefs: EditRef[]
  lastRefs: EditRef[]        // 尾帧卡参考池（要素+手选）
  videoFrameRefs: EditRef[]  // 视频卡首尾帧行：首帧+尾帧（未出图=空占位）
  videoOtherRefs: EditRef[]  // 视频卡其他参考容器：要素/音频/手选
  openRefInfo: (r: EditRef) => void
  openEditor: (target: 'image' | 'video' | 'last') => void
  // 首/尾帧「固定」勾选：切 ref_off.video 是否含「首帧」/「尾帧」——勾选=以首尾帧模式提交
  // Seedance（画面锁定该帧），取消=仅用提示词描述、不锁帧（后端 first/last_frame_url 置空）
  onToggleFrame: (name: string) => void
}

/** 镜头「参考池 + 生成入口」上下文：容器层（ShotBoard）按当前选中镜构建，纯闭包无状态。
 * 画布收编（2026-09-18）：查看/生成直达对应镜头 tapflow 窗口（首帧/视频/尾帧三画布），
 * 提示词与参考池在画布内管理（装配/质检/缺才跑都走同一后端 Step，不再双轨）；
 * windows（画布窗口句柄）由 ShotBoard 组件调用 useTapflowWindowReload 后传入，
 * 画布跑完关窗自动回刷镜头数据。 */
export function buildShotEditor({
  pid, sel, elements, pending, aiEditing, audioBusy, onElementsReload, windows,
  onToggleRef, onElemLink, onGenAudio,
}: {
  pid: number
  sel: Shot
  elements: Element[]
  pending: Record<number, number>
  aiEditing: Set<string>
  audioBusy: Set<string>  // `${shot_id}:${音频卡名}` 正在捏音色/补小样
  onElementsReload: () => void
  /** 画布窗口句柄：useTapflowWindowReload 的返回值（须在组件内调用后传入） */
  windows: ReturnType<typeof useTapflowWindowReload>
  onToggleRef: (s: Shot, target: 'image' | 'video' | 'last', name: string) => void
  onElemLink: (s: Shot, change: { add?: number; remove?: number }) => void
  onGenAudio: (s: Shot, r: EditRef) => void  // 音频卡未生成→按角色特征捏音色并补小样
}): ShotEditor {
  const busy = sel.id in pending
  const aiBusyImage = aiEditing.has(`${sel.id}:image`)
  const aiBusyVideo = aiEditing.has(`${sel.id}:video`)
  const aiBusyLast = aiEditing.has(`${sel.id}:last`)
  const sb = sel.meta.storyboard_ref
  const ids = sel.meta.element_ids ?? []
  const linked = elements.filter(e => ids.includes(e.id))
  // 要素参考（可删除=解除关联）；旧数据无 element_ids 时回落装配产物（不可删除）
  const elemChips: EditRef[] = linked.length
    ? linked.map(e => ({ name: e.name, kind: e.kind, url: e.meta.sheet_url, deletable: true }))
    : (sel.meta.reference_images ?? [])
  // 装配已产出 required_refs（本镜真实需要的要素：剧本无出场的角色已剔除，按首帧/视频
  // 分靶标注）时按清单渲染：图取要素库最新设定图；无图=占位胶囊（点击进要素预览可直接生成）
  const req = sel.meta.required_refs
  const reqChips = (target: 'image' | 'video'): EditRef[] => (req ?? [])
    .filter(r => r.kind !== 'character' || (r.targets ?? []).includes(target))
    .map(r => {
      const el = elements.find(e => e.id === r.element_id)
      // 无图=占位胶囊（ShotGenCard 按 !url 渲染虚线占位并自带"点击去生成"提示）
      return { name: r.name, kind: r.kind, url: el?.meta.sheet_url ?? r.url ?? undefined, deletable: true }
    })
  const imageElemChips = req ? reqChips('image') : elemChips
  const videoElemChips = req ? reqChips('video') : elemChips
  // 用户从资产面板手选的镜级额外参考（首帧/故事板/封面等任意项目图片资产）
  const extraChips: EditRef[] = (sel.meta.extra_refs ?? []).map(r => ({ ...r, deletable: true }))
  // 场景多景别空间图（场景组产物，装配自动挂载）：组内全镜共享的空间/站位参考，可按目标停用
  const sceneSheetChips: EditRef[] = (sel.meta.reference_images ?? [])
    .filter(r => r.kind === 'scene_sheet')
    .map(r => ({ name: r.name, kind: r.kind, url: r.url }))
  // 首帧参考池：要素 + 故事板整图 + 手选资产；尾帧参考池：要素 + 手选资产；
  // 本镜参考池分两组：首尾帧行（未出图=空占位）+ 其他参考容器（要素/音频/手选）
  const imageRefs: EditRef[] = [
    ...imageElemChips,
    ...sceneSheetChips,
    ...(sb?.url ? [{ name: '故事板', kind: 'storyboard', url: sb.url }] : []),
    ...extraChips,
  ]
  const lastRefs: EditRef[] = [...videoElemChips, ...extraChips]  // 尾帧=收束画面，按全镜口径
  const seam = sel.meta.last_frame_source === 'next_keyframe'
  const videoFrameRefs: EditRef[] = [
    { name: '首帧', kind: 'keyframe', url: sel.meta.keyframe_url },
    // 尾帧非必须：未出图渲染为虚线空占位，点击直达尾帧编辑弹框
    { name: '尾帧', kind: 'lastframe', url: sel.meta.last_frame_url,
      hint: seam ? '接缝帧：自动取下一镜首帧作本镜尾帧（连贯镜对共用一张图，跨镜无缝衔接）' : undefined },
  ]
  // 音频参考卡：优先按 speakers 全量渲染（含未捏音色/无小样者，供"未生成→点击生成"）；
  // 老数据无 speakers 时回落 audio_refs（仅已生成的）。call/silent（兽鸣/不发声）不入声线卡。
  const ap = sel.meta.audio_precheck
  const audioChips: EditRef[] = (ap?.speakers?.length
    ? ap.speakers
        .filter(s => (s.vocal_mode ?? 'speech') === 'speech' || s.vocal_mode === 'hybrid')
        .map(s => ({
          name: `音频·${s.speaker}`, kind: 'audio',
          audioUrl: s.sample_audio_url ?? undefined,
          elementId: s.element_id ?? undefined,
          voiceId: s.kb_voice_id ?? undefined,
          busy: audioBusy.has(`${sel.id}:音频·${s.speaker}`),
        }))
    : (ap?.audio_refs ?? []).map(a => ({
        name: `音频·${a.speaker}`, kind: 'audio', audioUrl: a.url,
        busy: audioBusy.has(`${sel.id}:音频·${a.speaker}`),
      })))
  const videoOtherRefs: EditRef[] = [
    ...videoElemChips,
    ...sceneSheetChips,
    ...audioChips,
    ...extraChips,
  ]
  // 卡上点参考胶囊 → 预览：要素=核心要素组件（可解除关联）；首帧/故事板=看图
  const openRefInfo = (r: EditRef) => {
    if (r.kind === 'storyboard' && sb) {
      openLightbox(r.url!, `分镜故事板 第${sb.board}张`, <LightboxInfo sections={[
        { label: '本镜格位', text: `镜${sel.meta.shot_no} 在第${sb.panel}格（「按本张出图」批量首帧时按格位引用作构图参考）` },
      ]} />)
      return
    }
    // 首帧/尾帧参考：无论是否出图都直达对应镜头画布（画布内可看图、编提示词、重生成）
    if (r.kind === 'keyframe' || r.kind === 'lastframe') {
      openEditor(r.kind === 'lastframe' ? 'last' : 'image')
      return
    }
    // 音频参考卡：有小样→试听；无小样→按角色特征/年龄捏音色并补小样（正在生成中忽略点击）
    if (r.kind === 'audio') {
      if (r.busy) return
      if (r.audioUrl) { playAudio(r.audioUrl); return }
      onGenAudio(sel, r)
      return
    }
    const el = elements.find(e => e.name === r.name)
    if (!el) { openLightbox(r.url || '', r.name); return }
    openElementPreview(
      <ElementPreview pid={pid} el={el} onReload={onElementsReload}
        actions={ids.includes(el.id) ? (
          <button className="small ghost"
            title="解除该要素与本镜的关联（提示词与参考图将不再包含它，自动重装配）"
            onClick={() => { onElemLink(sel, { remove: el.id }); closeElementPreview() }}>
            ✕ 解除与本镜的关联
          </button>
        ) : undefined} />
    )
  }
  // 查看/生成 → 镜头画布（画布收编 2026-09-18）：首帧/视频/尾帧各开对应 tapflow，
  // 提示词与参考池在画布内管理（装配/质检/缺才跑都走同一后端 Step，不再双轨）。
  const openEditor = (target: 'image' | 'video' | 'last') => {
    if (target === 'video') windows.open({ slug: 'shot-video-canvas', variant: 'production',
      inputs: { project_id: pid, shot_id: sel.id, target_ref: `content_node:${sel.id}`,
        asset_type: 'pro.shot.video' },
      subject: { kind: 'shot', id: sel.id,
        name: `镜头${sel.meta.shot_no ?? sel.id}`, canvasRole: 'shot.video' },
      productUrl: sel.meta.video_url || undefined })
    else if (target === 'last') windows.open({ slug: 'shot-lastframe-canvas', variant: 'production',
      inputs: { project_id: pid, shot_id: sel.id },
      subject: { kind: 'shot', id: sel.id,
        name: `镜头${sel.meta.shot_no ?? sel.id}`, canvasRole: 'shot.lastframe' },
      productUrl: sel.meta.last_frame_url || undefined })
    else windows.open({ slug: 'shot-keyframe-canvas', variant: 'production',
      inputs: { project_id: pid, shot_id: sel.id, target_ref: `content_node:${sel.id}`,
        asset_type: 'pro.shot.keyframe' },
      subject: { kind: 'shot', id: sel.id,
        name: `镜头${sel.meta.shot_no ?? sel.id}`, canvasRole: 'shot.keyframe' },
      productUrl: sel.meta.keyframe_url || undefined })
  }
  return {
    busy, aiBusyImage, aiBusyVideo, aiBusyLast,
    imageRefs, lastRefs, videoFrameRefs, videoOtherRefs, openRefInfo, openEditor,
    onToggleFrame: (name: string) => onToggleRef(sel, 'video', name),
  }
}
