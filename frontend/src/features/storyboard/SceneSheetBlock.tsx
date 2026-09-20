import type { SceneGroup } from '../../api'
import { Icon } from '../../components/Icon'
import { openLightbox } from '../../lib/lightbox'
import { sheetRefStatus, type SceneStage } from '../../lib/sceneSheet'

/** 场景组辅助区的「场景空间站位图」块：**产物只有一张**——组内各镜以它为空间与光影真值。
 *
 * 生成走两阶段（先出无人空场景基准图钉死几何与光，再以它为参考图把角色放进去），
 * 但基准图是中间锚不是并列产物：它跟角色设定图一样出现在下面的参考区里，
 * 带自己的重出入口（基准图不对时先修它——在错的空间里反复摆人没有意义）。
 *
 * 入口贴着图放（而不是只在详情头）：看到图不合理的那一刻就能重出，不用滚回顶部——
 * 未生成=同尺寸占位图，「画布/生成」两钮压在占位图上；已出图两钮改为划入图面才浮现，不挡画面。 */
export function SceneSheetBlock({ group, onOpenSheet, onGenSheet, busy }: {
  group: SceneGroup
  onOpenSheet: (stage: SceneStage) => void
  onGenSheet: (stage: SceneStage) => void
  busy?: boolean
}) {
  const url = group.sheet_url
  const versions = (group.sheet_versions ?? []).filter(v => v.url)
  const { refs, missing } = sheetRefStatus(group, 'sheet')
  return (
    <div className="aux-block">
      <div className="aux-title sg-sheet-title">
        <Icon name="image" /> 场景空间站位图
      </div>
      <div className="dim sg-stage-hint">
        组内各镜的空间与光影真值。出图分两步：先出无人空场景基准图钉死几何与光，再照搬它把角色放进去
      </div>
      {/* 图/占位图与两个入口合成一格：占位图上常显，成图上划入才浮现 */}
      <div className={`sg-sheet-tile${url ? ' ready' : ''}`}>
        {url ? (
          <img className="sg-sheet zoomable" src={url} alt=""
            onClick={() => openLightbox(url, `场景${group.seg} 空间站位图`)} />
        ) : (
          <span className="sg-sheet-ph"><Icon name="image" /></span>
        )}
        <span className="seg card-actions sg-sheet-acts">
          <button type="button" className="seg-btn" onClick={() => onOpenSheet('sheet')}
            title="进画布改词">
            <Icon name="workflow" /> 画布
          </button>
          <button type="button" className="seg-btn active" disabled={busy}
            onClick={() => onGenSheet('sheet')} title={url ? '重新出图' : '直接出图'}>
            {busy ? <Icon name="spinner" spin /> : <Icon name="zap" />} {url ? '重生成' : '生成'}
          </button>
        </span>
      </div>
      {!url && (
        <div className="dim">
          未生成——提示词已自动产出，点「生成」直接出图（会自动先出空场景基准图），或进画布确认后生成
        </div>
      )}
      {versions.length > 0 && (
        <div className="sg-versions">
          <span className="dim">历史 {versions.length} 版</span>
          {versions.map(v => (
            <img key={v.url} src={v.url} alt="" className="zoomable"
              onClick={() => openLightbox(v.url, `场景${group.seg} 旧版`)} />
          ))}
        </div>
      )}
      {/* 常显：不出图也要看得见"这张图到底参考了谁"，缺哪张设定图直接点名 */}
      <div className="sg-refs">
        <span className="dim"><Icon name="clip" /> 本图实际参考</span>
        {refs.length > 0 ? (
          <div className="aux-refs">
            {refs.map(r => (
              <img key={r.name} src={r.url} alt={r.name} title={r.name} className="zoomable"
                onClick={() => openLightbox(r.url!, r.name)} />
            ))}
          </div>
        ) : (
          <div className="dim">无参考图——本图全靠文字描述，空间与造型会自由发挥</div>
        )}
        {/* 基准图的次级入口：它决定空间与光，图不对先修它再重出站位图 */}
        <div className="sg-base">
          <span className="dim">
            空场景基准图{group.empty_url ? '（上面第1张参考）' : '：尚未生成'}——它决定空间与光线
          </span>
          <span className="seg card-actions">
            <button type="button" className="seg-btn" onClick={() => onOpenSheet('empty')}
              title="基准图画布">
              <Icon name="workflow" /> 画布
            </button>
            <button type="button" className="seg-btn" disabled={busy}
              onClick={() => onGenSheet('empty')} title="只重出基准图">
              {busy ? <Icon name="spinner" spin /> : <Icon name="zap" />}
              {group.empty_url ? ' 重出基准图' : ' 出基准图'}
            </button>
          </span>
        </div>
        {missing.length > 0 && (
          <div className="dim">缺设定图：{missing.join('、')}——这些角色的造型不受锚定，先去要素页出图</div>
        )}
      </div>
    </div>
  )
}
