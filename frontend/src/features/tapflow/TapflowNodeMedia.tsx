import { Icon } from '../../components/Icon'
import type { TapNode } from '../../lib/tapflowData'

/** 媒体类节点的卡内容（图片/上传/生成/音频/视频）：纯展示，无状态。
 * 视频 hover 自动播放、移开暂停（静音循环）；play 角标播放时由 CSS 隐藏。 */
export function TapflowNodeMedia({ node }: { node: TapNode }) {
  const t = node.type
  // 通用 gen 节点配了视频 modality 时产物是 mp4：走视频卡（video 播放器），不进 img
  const videoNode = t === 'video' || (t === 'gen' && node.modality === 'video')
  if (t === 'image' || t === 'upload' || (t === 'gen' && !videoNode)) {
    return (
      <>
        {node.src
          ? <img src={node.src} alt={node.title} draggable={false} />
          : node.status === 'generating'
            ? <span className="tap-generating">生成中</span>
            : <span className="tap-empty"><Icon name="image" /></span>}
        {t === 'upload' && node.src && (
          <span className="tap-replace"><Icon name="upload" /> 替换</span>
        )}
      </>
    )
  }
  if (t === 'audio') return <span className="tap-empty"><Icon name="speaker" /></span>
  if (!videoNode) return null
  if (node.video) {
    return (
      <>
        <video
          src={node.video} poster={node.src} muted loop playsInline preload="metadata"
          onMouseOver={e => { e.currentTarget.play().catch(() => undefined) }}
          onMouseOut={e => e.currentTarget.pause()} />
        <span className="tap-play"><Icon name="play" /></span>
      </>
    )
  }
  return node.src
    ? (
      <>
        <img src={node.src} alt={node.title} draggable={false} />
        <span className="tap-play"><Icon name="play" /></span>
      </>
    )
    : <span className="tap-play big"><Icon name="play" /></span>
}
