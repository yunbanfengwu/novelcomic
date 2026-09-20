import { Icon } from '../../components/Icon'

/**
 * 图片放大 / 裁剪视图（画布内全幅遮罩）：
 * crop = 图片铺开 + 裁剪框（四角手柄）+ 底部「✕ / 宽高比 / ✓ 确认裁剪」；view = 纯放大预览，点任意处关闭。
 * 假数据阶段裁剪只做展示，确认/取消都只关闭。
 */
export function TapflowMediaOverlay({ src, video, mode, onClose }: {
  src: string
  /** 有视频源时放大视图播放视频（带原生控制条） */
  video?: string
  mode: 'crop' | 'view'
  onClose: () => void
}) {
  return (
    <div
      className="tap-media-overlay"
      onPointerDown={e => { e.stopPropagation(); if (mode === 'view') onClose() }}>
      <div
        className="tap-media-stage"
        onPointerDown={e => { e.stopPropagation(); if (mode === 'view' && !video) onClose() }}>
        {mode === 'view' && video
          ? <video src={video} poster={src} controls autoPlay loop playsInline />
          : <img src={src} alt="" draggable={false} />}
        {mode === 'crop' && (
          <div className="tap-crop-frame">
            <span className="c tl" /><span className="c tr" /><span className="c bl" /><span className="c br" />
          </div>
        )}
      </div>
      <div className="tap-media-bar" onPointerDown={e => e.stopPropagation()}>
        <button type="button" className="tap-tool" title="关闭" onClick={onClose}>✕</button>
        {mode === 'crop' && (
          <>
            <span className="tap-tool-sep" />
            <button type="button" className="tap-tool wide"><Icon name="image" /> 宽高比</button>
            <button type="button" className="tap-tool wide ok" onClick={onClose}><Icon name="check" /> 确认裁剪</button>
          </>
        )}
      </div>
    </div>
  )
}
