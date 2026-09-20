import { Icon } from '../../components/Icon'

/** 画布左下角控制条：竖排，从上到下 全屏 / 放大 / 缩小 / 整理 / 辅助线 / 帮助 */
export function TapflowZoomBar({
  helpOn, guidesOn, onHelp, onRelayout, onToggleGuides, onZoomIn, onZoomOut, onFullscreen,
}: {
  helpOn?: boolean
  guidesOn?: boolean
  onHelp: () => void
  onRelayout: () => void
  onToggleGuides?: () => void
  onZoomIn: () => void
  onZoomOut: () => void
  onFullscreen: () => void
}) {
  return (
    <div className="tap-zoombar" onPointerDown={e => e.stopPropagation()}>
      <div className="tap-zoombar-box">
        <button type="button" className="tap-tool" title="全屏" onClick={onFullscreen}><Icon name="fullscreen" /></button>
        <button type="button" className="tap-tool" title="放大" onClick={onZoomIn}><Icon name="zoomin" /></button>
        <button type="button" className="tap-tool" title="缩小" onClick={onZoomOut}><Icon name="zoomout" /></button>
        <button type="button" className="tap-tool" title="智能重排" aria-label="智能重排"
          onClick={onRelayout}><Icon name="workflow" /></button>
        {onToggleGuides && (
          <button type="button" className={'tap-tool' + (guidesOn ? ' on' : '')}
            title={guidesOn ? '关闭参考线与吸附' : '开启参考线与吸附'}
            aria-label={guidesOn ? '关闭参考线与吸附' : '开启参考线与吸附'}
            onClick={onToggleGuides}><Icon name="blocks" /></button>
        )}
        <button type="button" className={'tap-tool' + (helpOn ? ' on' : '')} title="帮助" onClick={onHelp}>
          <Icon name="help" />
        </button>
      </div>
    </div>
  )
}
