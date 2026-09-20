import type { SceneGroup } from '../../api'
import { Icon } from '../../components/Icon'
import { openLightbox } from '../../lib/lightbox'

/** 场景组主预览：单幅空间站位图（点击放大）；未生成=空态常驻「生成场景图」入口 */
export function SceneGroupStage({ group, onOpenSheet }: {
  group: SceneGroup
  onOpenSheet: () => void
}) {
  const name = (group.scene || '').split(/[/／]/)[0] || `场景${group.seg}`
  return (
    <div className="vt-main">
      <div className="vt-stage">
        {group.sheet_url ? (
          <img className="vt-video zoomable" src={group.sheet_url} alt={name}
            onClick={() => openLightbox(group.sheet_url!, `场景${group.seg} · ${name}`)} />
        ) : (
          <div className="vt-empty">
            <div className="vt-empty-title">场景{group.seg} · {name}</div>
            <div className="vt-empty-ctrls">
              <div className="vt-ctrl-item">
                <button className="vt-ctrl" onClick={onOpenSheet} aria-label="生成场景图">
                  <Icon name="image" />
                </button>
                <span className="vt-ctrl-label">生成场景图</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
