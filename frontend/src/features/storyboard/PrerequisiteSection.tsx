import type { Shot } from '../../api'
import { Icon } from '../../components/Icon'
import { REF_ICON, type EditRef } from '../../lib/kinds'

/** 图块左上角胶囊（压在图上，与主预览「首帧图/尾帧图」同口径）：标明这一格是哪张图 */
const TILE_TAG: Record<string, string> = {
  keyframe: '首帧', lastframe: '尾帧', storyboard: '关键帧',
  scene_sheet: '场景光影站位锚定图', scene: '场景设定图',
}

/** 前置条件（不做卡片，与「本镜参考」同形：标题一行 + 图块一行）：
 * - 场景站位光影锚定 = 本镜所属场景组的场景空间站位图，右侧=空间布局/角色站位/光影文字；
 * - 分镜图 = 一张图。默认关联本镜首帧（无首帧取尾帧）→ 缩略图一行「已关联首帧」+ ✕ 解除；
 *   解除后 / 本镜自有关键帧时 → 大图块 + 右侧该图的定格文字（无图=虚线占位，点击进画布）。
 * 图块尺寸对齐首尾帧行——一行两格、方形自适应；胶囊压在图左上角标明是哪张图。
 * 两块都只留「画布」入口——生成一律在画布内确认提示词后完成，与视频生成同构。 */
export function PrerequisiteSection({ shot, sceneRef, sceneLines, boardLink, boardRef, boardLines,
  relinkName, onOpenGroup, onOpenRef, onSceneCanvas, onBoardCanvas, onBoardLink, boardBusy }: {
  shot: Shot
  sceneRef?: EditRef            // 本镜场景组的场景空间站位图（无图=占位）
  sceneLines: string[]          // 场景块右侧文字：空间布局 / 角色站位 / 光影
  boardLink?: EditRef           // 分镜图关联的本镜首/尾帧（有=走「已关联」紧凑行）
  boardRef?: EditRef            // 本镜自有关键帧（解除关联后的形态，无图=空占位）
  boardLines: string[]          // 关键帧形态右侧文字：该图的定格 + 状态
  relinkName?: string           // 已解除关联但本镜有首/尾帧时，给一个「关联首帧」回退入口
  onOpenGroup?: (seg: number) => void
  onOpenRef: (r: EditRef) => void
  onSceneCanvas?: () => void    // 场景图的来源画布（场景组·场景空间站位图画布）
  onBoardCanvas?: () => void    // 分镜图画布（章级宫格故事板·三区融合，画布内出图）
  onBoardLink?: (off: boolean) => void  // 解除/恢复「分镜图关联首尾帧」
  boardBusy?: boolean           // 章级故事板任务在跑
}) {
  const seg = shot.meta.scene_seg
  const sceneName = shot.meta.scene || shot.meta.scene_element ||
    (seg != null ? `场景${seg}` : '未指定场景')
  const openScene = seg != null && onOpenGroup ? () => onOpenGroup(seg) : undefined
  const tile = (url: string | undefined, kind: string, hint: string, onClick?: () => void) => (
    <button type="button" className={`pre-tile${url ? ' ready' : ''}`}
      disabled={!onClick} onClick={onClick} title={hint}>
      {url ? <img src={url} alt="" /> : <Icon name={REF_ICON[kind] ?? 'image'} />}
      {TILE_TAG[kind] && <span className="pre-tile-tag">{TILE_TAG[kind]}</span>}
    </button>
  )
  const note = (name: string, lines: string[]) => (
    <div className="pre-note">
      <b>{name}</b>
      {lines.map(l => <span key={l}>{l}</span>)}
    </div>
  )
  return (
    <div className="aux-block pre-block">
      <div className="aux-title"><Icon name="scene" /> 场景站位光影锚定
        {/* 组号标签（原详情头的独立标签行已撤）：点击进本镜所属场景组的设定面板 */}
        {seg != null && (
          <span className="tag accent sg-shot-tag" title="查看场景设定" onClick={openScene}>
            场景{seg}
          </span>
        )}
        {onSceneCanvas && (
          <button type="button" className="small ghost pre-canvas-btn" onClick={onSceneCanvas}
            title="进入场景图画布">
            <Icon name="workflow" /> 画布
          </button>
        )}
      </div>
      <div className="pre-grid">
        {tile(sceneRef?.url, sceneRef?.kind ?? 'scene_sheet', '查看场景设定', openScene)}
        {note(sceneName, sceneLines)}
      </div>
      <div className="aux-title"><Icon name="image" /> 分镜图
        {onBoardCanvas && (
          <button type="button" className="small ghost pre-canvas-btn" onClick={onBoardCanvas}
            title="进入分镜图画布">
            {boardBusy ? <Icon name="spinner" spin /> : <Icon name="workflow" />} 画布
          </button>
        )}
      </div>
      {boardLink ? (
        /* 关联首/尾帧：只一枚说明胶囊、缩略小图，右端 ✕ 解除关联（解除后本块变空占位关键帧） */
        <div className="pre-link">
          <button type="button" className="pre-link-thumb" title={`查看${boardLink.name}`}
            onClick={() => onOpenRef(boardLink)}>
            {boardLink.url ? <img src={boardLink.url} alt="" /> : <Icon name="image" />}
          </button>
          <span className="pre-link-text">已关联{boardLink.name}</span>
          {onBoardLink && (
            <button type="button" className="pre-link-x" title="解除关联"
              aria-label="解除关联" onClick={() => onBoardLink(true)}>
              <Icon name="cross" />
            </button>
          )}
        </div>
      ) : (
        <div className="pre-grid">
          {tile(boardRef?.url, boardRef?.kind ?? 'storyboard',
            boardRef?.url ? `查看${boardRef.name}` : '去画布出图',
            boardRef?.url ? () => onOpenRef(boardRef) : onBoardCanvas)}
          <div className="pre-note">
            <b>{boardRef?.name ?? '关键帧'}</b>
            {boardLines.map(l => <span key={l}>{l}</span>)}
            {relinkName && onBoardLink && (
              <button type="button" className="small ghost pre-relink"
                onClick={() => onBoardLink(false)} title="关联首尾帧">
                <Icon name="link" /> 关联{relinkName}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
