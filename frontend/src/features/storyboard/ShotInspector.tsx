import type { SceneGroup, Shot } from '../../api'
import type { EditRef } from '../../lib/kinds'
import { sceneNoteLines } from '../../lib/sceneSheet'
import { Icon } from '../../components/Icon'
import { ShotGenCard } from './ShotGenCard'
import { NeighborFramePane } from './NeighborFramePane'
import { CutScriptSection } from './CutScriptSection'
import type { ShotEditor } from './shotEditor'

import { PrerequisiteSection } from './PrerequisiteSection'

/** 分镜右侧详情，固定顺序：分镜脚本区 → 前置条件区 → ①本镜参考区 ②首帧卡 ③尾帧卡（可选）。
 * 技术提示词（image/video/last_image_prompt）不在卡上直接展示——只在各卡「画布」内可见可编辑
 * （避免长提示词占满辅助区）；拆镜阶段不再预生成提示词，改由生成图片/视频时按需装配+质检。
 * 参考池与生成画布由容器层 buildShotEditor 构建（与主预览空态常驻钮共用同一入口）；
 * 各卡标题栏「画布」按钮打开无限画布：参考启停/删除、提示词编辑、AI 按要求修改、保存/开始生成。 */
export function ShotInspector({ pid, sel, editor, onGenPrompts, onGenVideo, onReload, onDelete, onOpenGroup, onInsertBefore, onInsertAfter, prevVideoUrl, nextVideoUrl, sceneGroup, onBoardLink, onSceneCanvas, onBoardCanvas, boardBusy }: {
  pid: number
  sel: Shot
  editor: ShotEditor
  onGenPrompts: (s: Shot, only?: 'image' | 'video', redesignCuts?: boolean) => void
  onGenVideo: (s: Shot) => void
  onReload: () => void  // 取邻镜帧抽取成功后重载分镜列表（刷新卡片与主预览）
  onDelete: (s: Shot) => void  // 删除本镜（末尾动作组）
  onOpenGroup?: (seg: number) => void  // 跳到本镜所属场景组的设定面板
  onInsertBefore: (s: Shot) => void  // 在本镜之前插入空白镜
  onInsertAfter: (s: Shot) => void  // 在本镜之后插入空白镜
  prevVideoUrl?: string  // 上一镜视频 URL（供首帧「打开视频抽取」拖轴选帧）
  nextVideoUrl?: string  // 下一镜视频 URL（供尾帧「打开视频抽取」拖轴选帧）
  sceneGroup?: SceneGroup  // 本镜所属场景组（空间规划产物：站位图/空间布局/角色站位/光影）
  onBoardLink?: (off: boolean) => void  // 解除/恢复「分镜图关联本镜首尾帧」
  onSceneCanvas?: () => void  // 前置条件·场景块「画布」：本镜场景组的场景图画布
  onBoardCanvas?: () => void  // 前置条件·分镜图块「画布」：章级宫格故事板画布（画布内出图）
  boardBusy?: boolean         // 章级故事板任务在跑
}) {
  const { busy, aiBusyImage, aiBusyVideo, aiBusyLast, imageRefs, lastRefs,
    videoFrameRefs, videoOtherRefs, openRefInfo, openEditor, onToggleFrame } = editor
  // 明示"不需要的角色不关联"（装配产物）：整镜剔除的角色 + 仅视频出场（首帧不含）的角色
  const excChars = (sel.meta.excluded_refs ?? []).filter(r => r.kind === 'character').map(r => r.name)
  const videoOnly = (sel.meta.required_refs ?? [])
    .filter(r => r.kind === 'character' && !(r.targets ?? []).includes('image')).map(r => r.name)
  const videoNote = excChars.length
    ? `已剔除角色：${excChars.join('、')}（本镜剧本无出场，不织外貌、不传设定图）` : undefined
  const imageNote = [
    ...(videoOnly.length ? [`首帧不含：${videoOnly.join('、')}（首帧画面无此角色）`] : []),
    ...(excChars.length ? [`已剔除：${excChars.join('、')}（剧本无出场）`] : []),
  ].join('；') || undefined
  // 首/尾帧「画面提示词」（拆镜产物，非技术提示词）：首切=首帧定格、末切=尾帧收尾（仅多切时）。
  // 技术提示词按需装配，收进各卡「编辑」弹框，不在卡上直显。
  const cuts = sel.meta.cuts ?? []
  const cutLine = (c: NonNullable<Shot['meta']['cuts']>[number]) =>
    `${c.scale ? `(${c.scale})` : ''}${c.subject || ''}${c.action ? '：' + c.action : ''}`.trim()
  const firstCut = cuts[0]
  const lastCut = cuts.length > 1 ? cuts[cuts.length - 1] : undefined
  // 前置条件区·场景站位光影锚定：本镜场景组的场景空间站位图（组产物，时间轴组竖条显示的就是它）。
  // 组产物优先——装配挂到镜上的 scene_sheet 参考、场景要素设定图依次兜底（老数据/组产物未同步时）。
  const sceneRef: EditRef | undefined = sceneGroup?.sheet_url
    ? { name: '场景光影站位锚定图', kind: 'scene_sheet', url: sceneGroup.sheet_url }
    : imageRefs.find(r => r.kind === 'scene_sheet') ?? imageRefs.find(r => r.kind === 'scene')
  // 场景块右侧文字：空间布局 + 本镜站位/移动 + 光影（空间规划产物，纯逻辑在 lib/sceneSheet）。
  // 站位原来挂在分镜脚本末尾，空间信息集中到场景卡看。
  // 「有没有图」按组产物判定，不按 sceneRef——兜底显示的是场景要素设定图（胶囊写「场景设定图」），
  // 拿它当已就绪会把「设定图待生成」这行吞掉，镜里看着有图、时间轴组竖条却是空的（口径打架）
  const sceneLines = sceneNoteLines(sceneGroup, !!sceneGroup?.sheet_url, sel.meta.blocking)
  // 前置条件区·分镜图：只一张。默认关联本镜首帧（无首帧取尾帧）→ 紧凑行「已关联首帧」+ ✕；
  // 本镜自有关键帧（章级宫格故事板 storyboard_ref）以自己为准；解除关联=空占位关键帧，
  // 可在分镜图画布里单独出一张。
  const storyboardRef = imageRefs.find(r => r.kind === 'storyboard')
  const frameRef: EditRef | undefined =
    sel.meta.keyframe_url ? { name: '首帧', kind: 'keyframe', url: sel.meta.keyframe_url }
      : sel.meta.last_frame_url ? { name: '尾帧', kind: 'lastframe', url: sel.meta.last_frame_url }
      : undefined
  const linkOff = !!sel.meta.board_link_off
  const boardLink = !storyboardRef && !linkOff ? frameRef : undefined
  const boardRef: EditRef | undefined = boardLink ? undefined
    : storyboardRef ? { ...storyboardRef, name: '关键帧' }
    : { name: '关键帧', kind: 'storyboard', url: undefined }
  // 关键帧形态右侧文字：该图对应的定格（首切=首帧口径）+ 就绪/待生成状态
  const boardLines = boardRef ? [
    boardRef.url && sel.meta.storyboard_ref
      ? `宫格故事板 第${sel.meta.storyboard_ref.board}张 第${sel.meta.storyboard_ref.panel}格`
      : firstCut && (firstCut.subject || firstCut.action)
        ? `定格：${cutLine(firstCut)}`
        : '定格按本镜脚本装配',
    boardRef.url ? '已就绪' : boardBusy ? '出图中' : '待生成——点图块进画布确认提示词',
  ] : []
  return (
    <aside className="vt-aside">
      {/* 详情头只保留镜号和两个最高频入口；其余信息下沉到可滚动内容区。 */}
      <div className="vt-aside-head">
        <b>镜头{sel.meta.shot_no}</b>
        <span className="seg card-actions">
          <button type="button" className="seg-btn" disabled={busy} onClick={() => openEditor('video')}
            title="进入本镜头的无限画布编辑模式">
            <Icon name="workflow" /> 画布
          </button>
          <button type="button" className="seg-btn active" disabled={busy} onClick={() => onGenVideo(sel)}
            title="一键生成视频：自动补齐首帧、关联要素、提示词并派发，无需逐步确认">
            {busy ? <Icon name="spinner" spin /> : <Icon name="zap" />} 生成视频
          </button>
        </span>
      </div>
      {/* 原详情头下的参数标签行（时长/场景组/承接上一镜）已撤：时长落分镜脚本标题、
          场景组落场景站位光影锚定标题、「承接上一镜」由首切的切入方式标签表达，不再单列一行 */}
      {/* ① 分镜脚本区，末尾嵌本镜参考（要素/音频/手选 + ＋添加）——参考池跟着脚本看。
          首尾帧行不跟上来，仍留在场景站位光影锚定下方、首帧卡上方（连线要对接首帧/尾帧卡） */}
      <CutScriptSection shot={sel} busy={busy} onRedesign={() => onGenPrompts(sel, undefined, true)}
        footer={
          <ShotGenCard title="本镜参考" icon="video" review={sel.meta.prompt_review} variant="video"
            edited={sel.meta.video_prompt_edited} busy={busy || aiBusyVideo}
            refs={videoOtherRefs} off={sel.meta.ref_off?.video ?? []}
            onAdd={() => openEditor('video')} note={videoNote}
            onOpen={() => openEditor('video')} onOpenRef={openRefInfo} />
        } />
      {/* ② 前置条件（原视频卡内）：场景站位光影锚定 + 分镜图，不做卡片、与本镜参考同形 */}
      <PrerequisiteSection shot={sel} sceneRef={sceneRef} sceneLines={sceneLines}
        boardLink={boardLink} boardRef={boardRef} boardLines={boardLines}
        relinkName={linkOff && frameRef ? frameRef.name : undefined}
        onOpenGroup={onOpenGroup} onOpenRef={openRefInfo} onBoardLink={onBoardLink}
        onSceneCanvas={onSceneCanvas} onBoardCanvas={onBoardCanvas} boardBusy={boardBusy} />
      {/* ③ 首尾帧行（原视频卡下半块，位置不动）：紧贴首帧卡上方，两格各自向下连线对接首帧卡/尾帧卡。
          首尾帧不走 I2V 首尾帧通道——提交时折算为参考图 + 提示词「开始参考@首帧/结尾落在@尾帧」引用句 */}
      <ShotGenCard title="首尾帧" icon="palette" variant="video" busy={busy || aiBusyVideo}
        refs={[]} frames={videoFrameRefs} off={sel.meta.ref_off?.video ?? []}
        onToggleFrame={onToggleFrame}
        onOpen={() => openEditor('video')} onOpenRef={openRefInfo} />
      {/* ④ 首帧卡：画面提示词（拆镜产物）+ 关联要素（首帧图本身在首尾帧行大图 + 主预览展示，此处不重复）。
          页签「取前镜尾帧」：直接从上一镜视频抽最后一帧作本镜首帧（画面无缝衔接） */}
      <ShotGenCard title="首帧" icon="palette" review={sel.meta.prompt_review_image}
        edited={sel.meta.image_prompt_edited} busy={busy || aiBusyImage}
        body={firstCut && (firstCut.subject || firstCut.action)
          ? <div className="dim"><Icon name="camera" /> 定格：{cutLine(firstCut)}</div>
          : <div className="dim">首帧画面按本镜首个 cut 装配——点「画布」可确认参考与提示词后生成</div>}
        refs={imageRefs} off={sel.meta.ref_off?.image ?? []} note={imageNote}
        altTab={{
          alt: '取前镜尾帧', main: '新生成首帧',
          pane: <NeighborFramePane pid={pid} shot={sel} target="first" onDone={onReload}
            ownVideoUrl={sel.meta.video_url} neighborVideoUrl={prevVideoUrl} />,
        }}
        onOpen={() => openEditor('image')} onOpenRef={openRefInfo} />
      {/* ⑤ 尾帧卡（可选）：需要精确控制结尾画面时才用——「编辑」弹框内 AI 生成/手写定格提示词后出图。
          页签「取后镜首帧」：直接从下一镜视频抽第一帧作本镜尾帧（收束到下镜开场） */}
      <ShotGenCard title="尾帧" icon="palette" variant="last"
        edited={sel.meta.last_image_prompt_edited} busy={busy || aiBusyLast}
        body={lastCut && (lastCut.subject || lastCut.action)
          ? <div><Icon name="camera" /> 收尾：{cutLine(lastCut)}</div>
          : <div className="dim">尾帧为可选（留空则本镜不带尾帧）——点「画布」在画布内 AI 生成或手写结尾定格画面</div>}
        refs={lastRefs} off={sel.meta.ref_off?.last ?? []}
        altTab={{
          alt: '取后镜首帧', main: '新生成尾帧',
          pane: <NeighborFramePane pid={pid} shot={sel} target="last" onDone={onReload}
            ownVideoUrl={sel.meta.video_url} neighborVideoUrl={nextVideoUrl} />,
        }}
        onOpen={() => openEditor('last')} onOpenRef={openRefInfo} />
      {/* 末尾动作组：与「正文/视频」同款 tab 组（.seg）——前插 / 删除 / 后插；删除按钮悬停转危险色 */}
      <div className="vt-aside-ops">
        <span className="seg">
          <button type="button" className="seg-btn" onClick={() => onInsertBefore(sel)} title="在本镜之前插入">
            ‹ 插入分镜
          </button>
          <button type="button" className="seg-btn seg-btn-danger" onClick={() => onDelete(sel)}>
            <Icon name="trash" /> 删除本镜
          </button>
          <button type="button" className="seg-btn" onClick={() => onInsertAfter(sel)} title="在本镜之后插入">
            插入分镜 ›
          </button>
        </span>
      </div>
    </aside>
  )
}
