import type { SceneGroup, Shot } from '../../api'
import { Icon } from '../../components/Icon'
import type { SceneStage } from '../../lib/sceneSheet'
import { SceneSheetBlock } from './SceneSheetBlock'

/** 场景组右侧辅助区（场景设定面板）：空间布局 / 角色站位 / 场景参考图 / 生成参考 / 组内分镜。
 * 组内每个分镜的提示词装配都挂着这份场景设定（站位链+场景图参考）——此处是它的人读视图。 */
export function SceneGroupPane({
  group, shots, onOpenSheet, onGenSheet, busy,
  onSelectShot, onOpenBoard, onGenBoard, boardBusy,
}: {
  group: SceneGroup
  shots: Shot[]
  onOpenSheet: (stage: SceneStage) => void
  onGenSheet: (stage: SceneStage) => void
  busy?: boolean
  onSelectShot: (id: number) => void
  onOpenBoard: () => void
  onGenBoard: () => void
  boardBusy?: boolean
}) {
  const inGroup = shots.filter(s => s.meta.scene_seg === group.seg)
  const anchors = Object.entries(group.anchors ?? {})
  const name = (group.scene || '').split(/[/／]/)[0] || '未命名'
  return (
    <aside className="vt-aside">
      {/* 详情头对齐镜头详情：只留场景名和两个最高频入口，其余信息下沉到可滚动内容区。 */}
      <div className="vt-aside-head sg-head">
        <b className="sg-head-name" title={group.scene || name}>场景{group.seg} · {name}</b>
        <span className="seg card-actions">
          <button type="button" className="seg-btn" onClick={() => onOpenSheet('sheet')}
            title="进入场景图画布">
            <Icon name="workflow" /> 画布
          </button>
          <button type="button" className="seg-btn active" disabled={busy}
            onClick={() => onGenSheet('sheet')} title="生成场景图">
            {busy ? <Icon name="spinner" spin /> : <Icon name="zap" />} 生成
          </button>
        </span>
      </div>
      {/* 组内分镜小卡（紧贴详情头）：标题区=名称+镜数+本组分镜图入口，内容区=逐镜缩略格。
          「画布」进只装本场景的组图画布确认后出，「分镜生成」直接把本组各镜整批送去出图 */}
      <div className="sg-shots-card">
        <div className="sg-shots-head">
          <b>组内分镜</b>
          <span className="dim">共{inGroup.length}镜</span>
          <span className="seg card-actions">
            <button type="button" className="seg-btn" onClick={onOpenBoard} title="分镜画布">
              <Icon name="workflow" /> 分镜画布
            </button>
            <button type="button" className="seg-btn active" disabled={boardBusy || !inGroup.length}
              onClick={onGenBoard} title="整组出图">
              {boardBusy ? <Icon name="spinner" spin /> : <Icon name="zap" />} 分镜生成
            </button>
          </span>
        </div>
        <div className="sg-shots-grid">
          {inGroup.length ? inGroup.map(s => (
            <button type="button" key={s.id} className="sg-shot-cell"
              title="查看本镜" onClick={() => onSelectShot(s.id)}>
              {s.meta.keyframe_url
                ? <img src={s.meta.keyframe_url} alt="" />
                : <span className="sg-shot-blank"><Icon name="image" /></span>}
              <b>镜{s.meta.shot_no}</b>
            </button>
          )) : <span className="dim">本场景暂无分镜</span>}
        </div>
      </div>
      <div className="aux-block">
        <div className="aux-title"><Icon name="scene" /> 空间布局</div>
        <p>{group.space || '空间规划未完成——生成任一镜头时会自动补齐，或在拆镜后自动产出'}</p>
      </div>
      {anchors.length > 0 && (
        <div className="aux-block">
          <div className="aux-title"><Icon name="pin" /> 角色站位（组开场站位，逐镜站位链见各镜详情）</div>
          {anchors.map(([k, v]) => <div key={k} className="dim">「{k}」{v}</div>)}
        </div>
      )}
      {/* 产物只有一张场景空间站位图；空场景基准图是它的中间锚，在块内参考区里露出 */}
      <SceneSheetBlock group={group} onOpenSheet={onOpenSheet} onGenSheet={onGenSheet} busy={busy} />
    </aside>
  )
}
