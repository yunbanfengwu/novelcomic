import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api'
import type {
  Chapter, Element, EpisodeFlashMode, EpisodeFlashStatus, PreviewScriptBand,
  PreviewTimelineSegment, Shot,
} from '../../api'
import { noteEnqueued } from '../../lib/taskCenter'
import { useShotTasks } from './useShotTasks'
import { usePlayAll } from './usePlayAll'
import { useHorizontalResize } from '../../lib/useHorizontalResize'
import { ShotStage } from './ShotStage'
import { ShotInspector } from './ShotInspector'
import { buildShotEditor, type ShotEditor } from './shotEditor'
import { useTapflowWindowReload } from '../../lib/tapflowEntries'
import { openBatchKeyframesCanvas } from './batchKeyframes'
import { useSceneGroups } from './sceneGroups'
import { openStoryboardGridCanvas } from './storyboardGrid'
import { SceneGroupPane } from './SceneGroupPane'
import { SceneGroupStage } from './SceneGroupStage'
import { OVERVIEW_ID, ShotTimeline } from './ShotTimeline'
import { OverviewStage } from './OverviewStage'
import { OverviewInspector } from './OverviewInspector'
import { useAutoPlay, useSoundOn } from '../../lib/useAutoPlay'
import { Icon } from '../../components/Icon'
import './storyboard.css'

const flashModeLabel: Record<EpisodeFlashMode, string> = {
  flash20: '20镜闪回',
  sampled_story: '抽帧式超级加速',
  timeline_supercut: '分镜时间轴合并',
  adaptive_groups: '自动分组（每组≤15次）',
  adaptive_duration: '切换数自适应整数秒',
  slate_marked: '单帧黑场镜号板',
}

const flashSourceMinutes = (mode: EpisodeFlashMode) => {
  if (mode === 'sampled_story') return 10
  if (mode === 'flash20') return 8
  return 6
}

// ═══════════ 分镜工作台（内嵌于视频分区，撑满无滚动） ═══════════

/** 容器：持有分镜/任务状态，舞台·详情·时间轴各自成件。头部动作 portal 到视频分区头右侧。 */
export function ShotBoard({ pid, chapter, elements, onElementsReload, headSlot, playSlot }: {
  pid: number; chapter: Chapter; elements: Element[]; onElementsReload: () => void
  headSlot?: HTMLElement | null; playSlot?: HTMLElement | null
}) {
  const [shots, setShots] = useState<Shot[]>([])
  const [aiEditing] = useState<Set<string>>(new Set())  // AI 改写已迁进画布（占位：保留装配位）
  const [audioBusy, setAudioBusy] = useState<Set<string>>(new Set())  // `${shot_id}:${音频卡名}` 捏音色/补小样在途
  // 进页面先落在总览（分镜故事板）；本集分镜全部生成时由落地判定改选首镜（见 landedRef 处）
  const [selId, setSelId] = useState<number | null>(OVERVIEW_ID)
  const [flashPromptBusy, setFlashPromptBusy] = useState(false)
  const [flashVideoBusy, setFlashVideoBusy] = useState(false)
  const [flashFrameBusy, setFlashFrameBusy] = useState<Set<number>>(new Set())
  const [timelineActions, setTimelineActions] =
    useState<Map<number, 'analyze' | 'save' | 'convert'>>(new Map())
  const [episodeFlash, setEpisodeFlash] = useState<EpisodeFlashStatus | null>(null)

  // 场景组（空间锚定）：分组/站位链/场景空间站位图确认生成入口。
  // selGroupSeg=时间轴组竖条选中的场景组——主区换场景图大图、右侧换场景设定面板
  const { groups, reloadGroups, runBlocking, openSheet, genSheet } = useSceneGroups(pid, chapter.id)
  const [selGroupSeg, setSelGroupSeg] = useState<number | null>(null)
  // 章级组条目可能滞后于镜上的 scene_seg（空间规划未跑完/重拆镜后组号重算）——
  // 找不到时从镜数据合成兜底组，保证时间轴竖条点击必定能进场景组视图（面板自带未规划空态）
  const selGroup = (() => {
    if (selGroupSeg == null) return null
    const g = groups.find(x => x.seg === selGroupSeg)
    if (g) return g
    const s = shots.find(x => x.meta.scene_seg === selGroupSeg)
    return s ? { seg: selGroupSeg, scene: s.meta.scene || '' } : null
  })()

  const reload = useCallback(() => {
    api.listShots(pid, chapter.id).then(setShots).catch(console.error)
    api.getEpisodeFlash(pid, chapter.id).then(setEpisodeFlash).catch(console.error)
    reloadGroups()  // 任务结束（拆镜/空间规划/场景图）同步刷新组数据
  }, [pid, chapter.id, reloadGroups])
  useEffect(() => { reload() }, [reload])

  // 全局任务中心（SSE 实时推送，取代 4s 轮询）：镜级在途/拆镜忙/结束与流式逐镜自动重载
  const { pending, bdBusy, groupBusy, boardBusy, sheetBusy, blockingBusy, track } =
    useShotTasks(pid, chapter.id, reload)

  // 拆分镜：异步任务（流式逐镜落库；拆完后端自动串出详细分镜+逐镜提示词）
  const breakdown = async () => {
    try {
      const { task_id } = await api.breakdown(pid, chapter.id)
      noteEnqueued(pid, { id: task_id, kind: 'breakdown_chapter', node_id: chapter.id })
    } catch (e) { alert(String(e)) }
  }
  // 章级宫格故事板不再一键派发：改为「分镜图画布」内确认提示词后单张重出
  //（openStoryboardGridCanvas；出图后各镜 meta.storyboard_ref 指向自己所在的格位）
  const generateEpisodeFlashPrompt = async (mode: EpisodeFlashMode = 'flash20') => {
    if (flashPromptBusy || flashVideoBusy) return
    setFlashPromptBusy(true)
    try {
      const draft = await api.episodeFlashPrompt(pid, chapter.id, {
        mode, source_minutes: flashSourceMinutes(mode),
      })
      setEpisodeFlash(prev => ({ batches: prev?.batches ?? [], latest: prev?.latest, draft,
        drafts: [...(prev?.drafts ?? []), draft] }))
    } catch (e) { alert(`${flashModeLabel[mode]}提示词生成失败：${String(e)}`) }
    finally { setFlashPromptBusy(false) }
  }
  const generateFromEpisodeFlash = async () => {
    if (flashPromptBusy || flashVideoBusy) return
    const draft = episodeFlash?.draft
    if (!draft) { alert('请先生成并检查本次实验的母带提示词'); return }
    if (draft.mode === 'slate_marked') {
      alert('黑屏镜号板实验已停止；历史草稿与产物仅保留查看')
      return
    }
    setFlashVideoBusy(true)
    try {
      await api.generateEpisodeFlashMaster(pid, chapter.id, { draft_id: draft.id })
      const status = await api.getEpisodeFlash(pid, chapter.id)
      setEpisodeFlash(status)
      reload()
    } catch (e) {
      const mode = draft.mode ?? 'flash20'
      alert(`${flashModeLabel[mode]}母带生成失败：${String(e)}`)
    }
    finally { setFlashVideoBusy(false) }
  }
  const extractEpisodeFlashFrames = async (attachmentId: number) => {
    if (flashFrameBusy.has(attachmentId)) return
    setFlashFrameBusy(prev => new Set(prev).add(attachmentId))
    try {
      await api.extractEpisodeFlashFrames(pid, chapter.id, attachmentId)
      const status = await api.getEpisodeFlash(pid, chapter.id)
      setEpisodeFlash(status)
    } catch (e) { alert(`母带抽帧失败：${String(e)}`) }
    finally {
      setFlashFrameBusy(prev => {
        const next = new Set(prev)
        next.delete(attachmentId)
        return next
      })
    }
  }
  const runTimelineAction = async (
    attachmentId: number,
    action: 'analyze' | 'save' | 'convert',
    operation: () => Promise<unknown>,
  ) => {
    if (timelineActions.has(attachmentId)) return
    setTimelineActions(previous => new Map(previous).set(attachmentId, action))
    try {
      await operation()
      const status = await api.getEpisodeFlash(pid, chapter.id)
      setEpisodeFlash(status)
      if (action === 'convert') {
        const freshShots = await api.listShots(pid, chapter.id)
        setShots(freshShots)
        setSelId(OVERVIEW_ID)
      }
    } catch (e) {
      const labels = { analyze: '建立双时间线', save: '保存时间线版本', convert: '转为草稿分镜' }
      alert(`${labels[action]}失败：${String(e)}`)
    } finally {
      setTimelineActions(previous => {
        const next = new Map(previous)
        next.delete(attachmentId)
        return next
      })
    }
  }
  const analyzePreviewTimeline = (attachmentId: number) =>
    runTimelineAction(attachmentId, 'analyze',
      () => api.createEpisodePreviewTimeline(pid, chapter.id, attachmentId))
  const savePreviewTimeline = (
    attachmentId: number,
    segments: PreviewTimelineSegment[],
    scriptBands: PreviewScriptBand[],
  ) => {
    const timeline = (episodeFlash?.batches ?? [])
      .find(batch => batch.attachment_id === attachmentId)?.timeline
    if (!timeline) return Promise.resolve()
    return runTimelineAction(attachmentId, 'save', () =>
      api.saveEpisodePreviewTimeline(pid, chapter.id, attachmentId, {
        base_attachment_id: timeline.attachment_id,
        segments: segments.map(segment => ({
          id: segment.id,
          script_event_ids: segment.script_event_ids,
          preview_start_s: segment.preview_start_s,
          preview_end_s: segment.preview_end_s,
          selected_frame_attachment_id: segment.selected_frame_attachment_id,
          locked: !!segment.locked,
        })),
        script_bands: scriptBands,
      }))
  }
  const convertPreviewTimeline = (attachmentId: number) =>
    runTimelineAction(attachmentId, 'convert',
      () => api.convertEpisodePreviewTimeline(pid, chapter.id, attachmentId))
  // 批量首帧=组图画布（2026-07-28）：整集分镜在画布内按场景切组，每组一个大框，
  // 可「生成本组」或「全部生成」（每场景各派一个章级任务——跨场景绝不合批，禁止继承光线）。
  // 不再按总览宫格的分页切目标：分页只是展示分页，与场景边界无关。
  const batchKeyframes = () => openBatchKeyframesCanvas(pid, chapter.id)
  // 场景组「组内分镜 · 生成」（画布收编 2026-09-18）：打开批量首帧画布（本场景）——
  // 画布内 scene.batch_plan 按场景合同切批（跨场景绝不合批），loop 逐批 gen_keyframes_group
  const genGroupBoard = (seg: number) => openBatchKeyframesCanvas(pid, chapter.id, seg)
  // 批量场景（总览常驻钮）：本集所有缺场景图的场景组一次派发（各派一个章级任务，
  // 用组条目已装配的 sheet_prompt；要改提示词/换参考图仍走场景组画布 openSheet）。
  // 组还没分（拆镜后 scene_blocking 未跑/重拆后组号待重算）→ 先跑空间规划，规划完再来批量出图。
  // 常驻的「重跑场景空间规划」入口（更多章级操作菜单）：force 忽略指纹缓存，
  // 让旧版提示词规划出来的组按当前版本重来一遍——已生成的场景图不作废。
  const replanScenes = () => {
    if (sheetBusy || blockingBusy) return
    if (!confirm('将按当前版本重跑本章的场景分组与站位规划（已生成的场景图不会作废）。继续？')) return
    runBlocking(true)
  }
  const batchScenes = async () => {
    if (sheetBusy || blockingBusy) return
    if (!groups.length) {
      if (!confirm('本集还没有场景分组（空间规划未跑）。先跑场景空间规划？完成后再点「批量场景」出图。')) return
      runBlocking()
      return
    }
    // 旧单阶段数据（只有 sheet_*、没有 empty_prompt）直接出图必被 gen_scene_empty 判
    // Blocked「空场景图提示词为空」——错误提示让人去跑空间规划，而这里以前是唯一入口且
    // 只在无分组时才跑，等于死循环。先强制重规划补齐两阶段字段。
    const legacy = groups.filter(g => !g.empty_prompt)
    if (legacy.length) {
      if (!confirm(`本集 ${legacy.length}/${groups.length} 个场景还是旧单阶段数据（缺空场景基准图提示词），`
        + '直接出图会失败。先重跑场景空间规划补齐？完成后再点「批量场景」。')) return
      runBlocking(true)
      return
    }
    // 全都有图时不再空转——改为二次确认后整章重出（口径同「组内分镜·生成」的覆盖确认）
    const missing = groups.filter(g => !g.sheet_url)
    const todo = missing.length ? missing : groups
    if (!confirm(missing.length
      ? `将为 ${missing.length} 个缺图场景生成场景图（各派一个章级任务）。继续？`
      : `本集 ${groups.length} 个场景都已有场景图，将全部重新生成并覆盖旧图。继续？`)) return
    for (const g of todo) await genSheet(g)
  }
  const genVideo = async (s: Shot) => {
    try { track(s.id, (await api.genVideo(pid, s.id)).task_id, 'gen_video') }
    catch (e) { alert(String(e)) }
  }
  // 提示词生成（含质检）：装配→九维评审→不合格自动重构→复审，异步任务；only 可单独重生成一侧
  const genPrompts = async (s: Shot, only?: 'image' | 'video', redesignCuts = false) => {
    try { track(s.id, (await api.genPrompts(pid, s.id, only, redesignCuts)).task_id, 'gen_prompts') } catch (e) { alert(String(e)) }
  }
  // 音频参考卡「未生成→生成」：无绑定音色的角色先按角色特征/年龄捏音色（LLM 选角+补小样），
  // 已绑音色只是缺小样的直接重跑音频预检补样；两者都以重跑预检把新小样刷进本镜 audio_precheck。
  const genAudio = async (s: Shot, r: { name: string; elementId?: number; voiceId?: number }) => {
    const key = `${s.id}:${r.name}`
    if (audioBusy.has(key)) return
    if (!r.elementId && !r.voiceId) { alert('该说话人不是项目角色，无法自动生成音色'); return }
    setAudioBusy(prev => new Set(prev).add(key))
    try {
      if (!r.voiceId && r.elementId) await api.designVoice(pid, r.elementId)
      await api.audioPrecheck(pid, s.id)
      reload()
    } catch (e) { alert(String(e)) }
    finally { setAudioBusy(prev => { const n = new Set(prev); n.delete(key); return n }) }
  }
  // 手动增删本镜关联要素（后端改绑定后自动重装配提示词）
  const elemLink = async (s: Shot, change: { add?: number; remove?: number }) => {
    try { await api.updateShotElements(pid, s.id, change); reload() }
    catch (e) { alert(String(e)) }
  }
  // 参考图按目标启停（提示词卡片上的要素 chip）：改 ref_off 后重载；视频侧涉及身份层回退，提示重生成
  const toggleRef = async (s: Shot, target: 'image' | 'video' | 'last', name: string) => {
    const cur = new Set(s.meta.ref_off?.[target] ?? [])
    if (cur.has(name)) cur.delete(name)
    else cur.add(name)
    try {
      await api.updateShotRefs(pid, s.id,
        target === 'image' ? { image_off: [...cur] }
          : target === 'video' ? { video_off: [...cur] } : { last_off: [...cur] })
      reload()
    } catch (e) { alert(String(e)) }
  }

  // 前置条件·分镜图「解除/恢复关联首尾帧」：落 meta.board_link_off，解除后那块变空占位关键帧
  const toggleBoardLink = async (s: Shot, off: boolean) => {
    try { await api.updateShotRefs(pid, s.id, { board_link_off: off }); reload() }
    catch (e) { alert(String(e)) }
  }
  // 「在本镜之前插入」换算：取本镜前一镜的 id 作 afterId；本镜为首镜则 null（插到最前）
  const prevShotId = (s: Shot): number | null => {
    const idx = shots.findIndex(x => x.id === s.id)
    return idx > 0 ? shots[idx - 1].id : null
  }
  // 在两镜之间插入空白镜：afterId=null 插到最前；插完选中新镜（用户随即填脚本）
  const insertShot = async (afterId: number | null) => {
    try {
      const ns = await api.insertShot(pid, chapter.id, afterId)
      await api.listShots(pid, chapter.id).then(setShots)
      setSelId(ns.id)
    } catch (e) { alert(String(e)) }
  }
  // 删除本镜（右侧详情末尾隐蔽入口）：确认后删，选中转移到邻镜；镜号永久保留、不复用
  const deleteShot = async (s: Shot) => {
    if (!confirm(`确认删除 镜${s.meta.shot_no}？删除后此镜号永久保留、不再复用。`)) return
    const idx = shots.findIndex(x => x.id === s.id)
    const nb = shots[idx + 1] ?? shots[idx - 1]
    try {
      await api.deleteShot(pid, s.id)
      await api.listShots(pid, chapter.id).then(setShots)
      setSelId(nb ? nb.id : OVERVIEW_ID)
    } catch (e) { alert(String(e)) }
  }

  // 选中镜（时间轴→预览联动）；sel=null 表示选中总览首帧卡（预览区换总览宫格视图）。
  // 未生成分镜时停在总览卡——布局（主预览/辅助/时间轴）照常，不塌成空态占位
  const sel = selId === OVERVIEW_ID || shots.length === 0
    ? null : shots.find(x => x.id === selId) ?? shots[0]
  // 相邻镜视频 URL（供首/尾帧「打开视频抽取」在 <video> 上拖轴选帧）：首帧看上一镜、尾帧看下一镜
  const selIdx = sel ? shots.findIndex(x => x.id === sel.id) : -1
  const prevVideoUrl = selIdx > 0 ? shots[selIdx - 1].meta.video_url : undefined
  const nextVideoUrl = selIdx >= 0 && selIdx < shots.length - 1 ? shots[selIdx + 1].meta.video_url : undefined

  // 「自动播放」「声音」全局偏好（持久化，跨剧集/进出页面保持）；声音在自动播放钮的下拉里切换
  const [autoPlay, setAutoPlay] = useAutoPlay()
  const [soundOn, setSoundOn] = useSoundOn()
  // 播放会话时钟：playMode（顺序/单镜循环，页面级）+ playing（会话在播）；有视频交给 <video>，无视频按时长停留
  const { playMode, setPlayMode, playing, setPlaying, elapsed, setRemain, setElapsed, nextShot } =
    usePlayAll(shots, selId, setSelId, sel, autoPlay)
  // 进页面落地判定（首次拿到本集分镜时只跑一次；换剧集/项目由 ShotBoard 重挂载重置）：
  // 分镜（首帧）已全部生成 → 选中首镜，按「自动播放」偏好起播；
  // 未全部生成 → 停在总览（分镜故事板）且不自动播放——先看生成进度，别把半成品播一遍。
  const landedRef = useRef(false)
  useEffect(() => {
    if (landedRef.current || !shots.length) return
    landedRef.current = true
    if (shots.every(s => s.meta.keyframe_url)) setSelId(shots[0].id)
    else setPlaying(false)
  }, [shots, setPlaying])
  // 手动点时间轴选镜 → 自动切「单镜循环」（用户是来看这一镜的）。
  // 顺序播放只有两个入口：进页面默认、点「顺序播放」按钮；自动推进走 nextShot（内部 setSelId），不经此处。
  const selectShot = (id: number) => {
    setSelGroupSeg(null)  // 点镜/总览即退出场景组视图
    if (id !== OVERVIEW_ID) {
      setPlayMode('loop')
      // 点选无视频镜（仅首/尾帧）：不自动播放，完整看图；若此前在播视频则停下
      //（usePlayAll 的切镜自动起播已只对有视频镜生效，这里再显式收停旧的播放会话）
      const t = shots.find(s => s.id === id)
      if (t && !t.meta.video_url) setPlaying(false)
    }
    setSelId(id)
  }
  // 从头顺序播放：总览宫格的悬浮播放钮 / 最后一镜的「从头播放」共用（跳回第一镜连续播）
  const playFromStart = () => {
    if (!shots.length) return
    setPlayMode('sequence')
    setSelId(shots[0].id)
    setPlaying(true)
  }

  // 画幅比例（项目基本信息里配置）：预览舞台与视频生成统一按此执行
  const [ratio, setRatio] = useState<'16:9' | '9:16'>('16:9')
  useEffect(() => {
    api.getProject(pid).then(p => setRatio(p.config.aspect_ratio || '16:9')).catch(console.error)
  }, [pid])

  // 舞台 | 详情 之间的可拖动分割线（详情面板宽度可调，持久化）
  const { width: asideW, resizing, onResizeDown } = useHorizontalResize('vt-aside-w')

  // 窄屏（≤1100px CSS 接管）辅助区变悬浮抽屉：默认收起，把手展开/收回；宽屏下该类与把手均无效果
  const [asideOpen, setAsideOpen] = useState(false)
  const vtTopCls = `vt-top${asideOpen ? ' aside-open' : ''}`
  const asideToggle = (
    <button className="vt-aside-toggle" onClick={() => setAsideOpen(v => !v)}
      aria-label={asideOpen ? '收起详情' : '展开详情'} title={asideOpen ? '收起详情' : '展开详情'}>
      {asideOpen ? '›' : '‹'}
    </button>
  )

  // 选中镜的「参考池 + 生成编辑弹窗」上下文：舞台空态常驻钮与右侧详情卡共用同一 openEditor
  // 画布窗口句柄：镜头画布跑完关窗后自动回刷镜头数据（hook 须在组件内调用）
  const canvasWindows = useTapflowWindowReload(reload)
  const editor: ShotEditor | null = sel ? buildShotEditor({
    pid, sel, elements, pending, aiEditing, audioBusy, onElementsReload,
    windows: canvasWindows, onToggleRef: toggleRef, onElemLink: elemLink, onGenAudio: genAudio,
  }) : null

  return (
    <div className="vt-board">
      {/* 头部右侧动作组（tab 风格）：自动播放（开=高亮 / 关=置灰），划入下拉切换声音开关；
          全屏/收起为框架级常驻，见 WorkbenchTabs */}
      {headSlot && shots.length > 0 && createPortal(
        <div className="seg wb-action-seg">
          <div className="autoplay-wrap">
            <button className={'seg-btn' + (autoPlay ? ' active' : '')}
              onClick={() => setAutoPlay(v => !v)}>
              自动播放 <span className="autoplay-caret" title={soundOn ? '声音已开启' : '已静音'}>
                <Icon name={soundOn ? 'speaker' : 'mute'} />
              </span>
            </button>
            {/* 下拉只给一个反向动作：当前开着 → 「关闭声音」；关着 → 「开启声音」（文字在前、图标在后，单行） */}
            <div className="autoplay-menu">
              <button className="autoplay-item" onClick={() => setSoundOn(v => !v)}>
                {soundOn ? <>关闭声音 <Icon name="mute" /></> : <>开启声音 <Icon name="speaker" /></>}
              </button>
            </div>
          </div>
        </div>, headSlot)}
      {/* 左下角（分页行）播放/停止钮：圆形黑底。未在顺序播放=播放本集（从头逐镜）；
          顺序播放中=停止（与主预览停止钮同图标同功能：暂停当前会话） */}
      {playSlot && shots.length > 0 && createPortal(
        (() => {
          const seqPlaying = playing && playMode === 'sequence'
          return (
            <button className="vt-playall-fab" onClick={() => seqPlaying ? setPlaying(false) : playFromStart()}
              aria-label={seqPlaying ? '停止' : '播放本集'}>
              <Icon name={seqPlaying ? 'pause' : 'playnext'} />
            </button>
          )
        })(), playSlot)}
      <div className="card-body vt-shell">
        {/* 布局恒定：主预览 + 辅助 + 时间轴始终在。未生成分镜=默认选中总览卡（sel 为空即总览视图）；
            时间轴组竖条选中场景组 → 主区=场景空间站位图，右侧=场景设定面板（空间/占位/生成入口） */}
        <div className="vt-editor">
          {selGroup ? (
            <div className={vtTopCls} style={{ '--aside-w': `${asideW}px` } as CSSProperties}>
              <SceneGroupStage group={selGroup} onOpenSheet={() => openSheet(selGroup)} />
              <div className={`vt-resizer${resizing ? ' dragging' : ''}`} onMouseDown={onResizeDown}
                role="separator" aria-orientation="vertical" title="拖动调整详情面板宽度" />
              <SceneGroupPane group={selGroup} shots={shots}
                onOpenSheet={() => openSheet(selGroup)} onGenSheet={() => genSheet(selGroup)}
                busy={sheetBusy} onSelectShot={selectShot}
                onOpenBoard={() => openBatchKeyframesCanvas(pid, chapter.id, selGroup.seg)}
                onGenBoard={() => genGroupBoard(selGroup.seg)}
                boardBusy={groupBusy} />
              {asideToggle}
            </div>
          ) : sel && editor ? (
            <div className={vtTopCls} style={{ '--aside-w': `${asideW}px` } as CSSProperties}>
              <ShotStage
                sel={sel} ratio={ratio} elapsed={elapsed} soundOn={soundOn}
                playMode={playMode} playing={playing} setPlayMode={setPlayMode} setPlaying={setPlaying}
                onNext={nextShot} setRemain={setRemain} setElapsed={setElapsed}
                isLast={sel.id === shots[shots.length - 1]?.id} onRestart={playFromStart}
                onOpenEditor={editor.openEditor}
                busy={editor.busy} onGenVideo={() => genVideo(sel)} />
              <div className={`vt-resizer${resizing ? ' dragging' : ''}`} onMouseDown={onResizeDown}
                role="separator" aria-orientation="vertical" title="拖动调整详情面板宽度" />
              <ShotInspector pid={pid} sel={sel} editor={editor}
                onGenPrompts={genPrompts} onGenVideo={genVideo} onReload={reload}
                onDelete={deleteShot} onOpenGroup={setSelGroupSeg}
                onInsertBefore={s => insertShot(prevShotId(s))} onInsertAfter={s => insertShot(s.id)}
                prevVideoUrl={prevVideoUrl} nextVideoUrl={nextVideoUrl}
                sceneGroup={groups.find(g => g.seg === sel.meta.scene_seg)}
                onBoardLink={off => toggleBoardLink(sel, off)}
                onSceneCanvas={sel.meta.scene_seg == null ? undefined : () => {
                  const seg = sel.meta.scene_seg!
                  // 组条目可能滞后于镜（空间规划未跑完）→ 同 selGroup 的兜底：按镜数据合成
                  openSheet(groups.find(g => g.seg === seg) ?? { seg, scene: sel.meta.scene || '' })
                }}
                onBoardCanvas={() => openStoryboardGridCanvas(pid, chapter.id, { shotId: sel.id })}
                boardBusy={boardBusy} />
              {asideToggle}
            </div>
          ) : (
            /* 总览视图同构复用 vt-top 双栏：主区=每镜首帧宫格，右侧辅助区=关联要素 */
            <div className={vtTopCls} style={{ '--aside-w': `${asideW}px` } as CSSProperties}>
              <OverviewStage shots={shots} ratio={ratio}
                pendingCount={Object.keys(pending).length} bdBusy={bdBusy} groupBusy={groupBusy}
                sceneBusy={sheetBusy || blockingBusy}
                flashPromptBusy={flashPromptBusy} flashVideoBusy={flashVideoBusy}
                hasFlashDraft={!!episodeFlash?.draft && episodeFlash.draft.mode !== 'slate_marked'}
                onEpisodeFlashPrompt={generateEpisodeFlashPrompt} onEpisodeFlash={generateFromEpisodeFlash}
                onBreakdown={breakdown} onBatchScenes={batchScenes} onBatchKeyframes={batchKeyframes}
                onReplanScenes={replanScenes}
                onPlayAll={playFromStart} />
              <div className={`vt-resizer${resizing ? ' dragging' : ''}`} onMouseDown={onResizeDown}
                role="separator" aria-orientation="vertical" title="拖动调整详情面板宽度" />
              <OverviewInspector pid={pid} chapter={chapter}
                shots={shots} groups={groups} onOpenSheet={openSheet}
                episodeFlash={episodeFlash}
                extractingAttachmentIds={flashFrameBusy}
                timelineActions={timelineActions}
                onExtractFrames={extractEpisodeFlashFrames}
                onTimelineAnalyze={analyzePreviewTimeline}
                onTimelineSave={savePreviewTimeline}
                onTimelineConvert={convertPreviewTimeline} />
              {asideToggle}
            </div>
          )}
          <ShotTimeline shots={shots} selId={sel ? sel.id : OVERVIEW_ID} selGroup={selGroupSeg}
            pending={pending} overview={{ busy: bdBusy }} groups={groups} onSelect={selectShot}
            onSelectGroup={setSelGroupSeg} />
        </div>
      </div>
    </div>
  )
}
