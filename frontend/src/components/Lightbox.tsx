import { useEffect, useState, type ReactNode } from 'react'
import { registerLightbox } from '../lib/lightbox'
import './Lightbox.css'

// ═══════════ 图片放大预览（Lightbox，统一左右布局） ═══════════

/** 全屏放大预览：左边图（点击在适应⇄原始尺寸间切换），右边信息面板（标题+side 内容）。
 * 点遮罩/✕/Esc 关闭；side 由调用方传入（提示词/基本信息/操作按钮）。 */
export function Lightbox() {
  const [state, setState] = useState<{ src: string; alt?: string; side?: ReactNode; video?: boolean } | null>(null)
  const [zoomed, setZoomed] = useState(false)

  useEffect(() => {
    registerLightbox(
      (src, alt, side, opts) => { setState({ src, alt, side, video: opts?.video }); setZoomed(false) },
      () => setState(null),
    )
    return () => { registerLightbox(null, null) }
  }, [])

  useEffect(() => {
    if (!state) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setState(null) }
    window.addEventListener('keydown', onKey)
    // 打开时禁止背景滚动
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [state])

  if (!state) return null
  return (
    <div className="lightbox-overlay" onClick={() => setState(null)}>
      <button className="lightbox-close" title="关闭 (Esc)" onClick={() => setState(null)}>✕</button>
      <div className={'lightbox-body' + (state.src ? '' : ' no-img')} onClick={e => e.stopPropagation()}>
        {state.src && (
          <div className={'lightbox-main' + (zoomed && !state.video ? ' scroll' : '')}>
            {state.video ? (
              // ref 清理：关闭/卸载移除 <video> 时暂停，避免被移除后仍在后台播放
              <video src={state.src} className="lightbox-img" controls autoPlay
                ref={node => { return () => node?.pause() }} />
            ) : (
              <img
                src={state.src}
                alt={state.alt}
                className={'lightbox-img' + (zoomed ? ' zoomed' : '')}
                title={zoomed ? '点击缩小' : '点击查看原始尺寸'}
                onClick={() => setZoomed(z => !z)}
              />
            )}
          </div>
        )}
        <aside className="lightbox-side">
          {state.alt && <div className="lightbox-title">{state.alt}</div>}
          {state.side}
        </aside>
      </div>
    </div>
  )
}
