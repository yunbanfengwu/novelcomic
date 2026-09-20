import type { ReactNode } from 'react'

// 图片放大预览的模块级单例：任意组件调用 openLightbox() 打开，Lightbox 组件调用 registerLightbox 挂载实现。
// 统一左右布局：左边图/视频，右边信息面板（side 传提示词/基本信息/操作区的节点；不传则只显示标题）
export type LightboxOpts = { video?: boolean } // video=true 时左侧渲染 <video> 而非 <img>
let _open: ((src: string, alt?: string, side?: ReactNode, opts?: LightboxOpts) => void) | null = null
let _close: (() => void) | null = null

/** 打开左右布局放大预览（未挂载 Lightbox 时无副作用）；side=右侧信息面板内容；opts.video=放大视频 */
export function openLightbox(src: string, alt?: string, side?: ReactNode, opts?: LightboxOpts) {
  _open?.(src, alt, side, opts)
}

/** 关闭当前预览（供面板内操作按钮触发后收口，如"重新生成"） */
export function closeLightbox() { _close?.() }

/** 由 <Lightbox /> 在挂载/卸载时登记与注销实现 */
export function registerLightbox(
  open: ((src: string, alt?: string, side?: ReactNode, opts?: LightboxOpts) => void) | null,
  close: (() => void) | null,
) { _open = open; _close = close }
