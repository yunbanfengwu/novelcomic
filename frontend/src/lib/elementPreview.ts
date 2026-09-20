import type { ReactNode } from 'react'

// 预览/生成弹窗的模块级单例，支持**多层栈**：openElementPreview 重置为单层；pushElementPreview
// 在当前之上再叠一层（父层保持挂载→未存提示词等状态不丢）；closeElementPreview 出栈一层。
// <ElementPreviewModal /> 挂载时登记实现。
let _open: ((node: ReactNode) => void) | null = null
let _push: ((node: ReactNode) => void) | null = null
let _close: (() => void) | null = null

/** 弹出预览/生成弹窗（重置为单层栈）；node 一般是 <ElementPreview/> 或 <ImageGenModal/> */
export function openElementPreview(node: ReactNode) { _open?.(node) }

/** 在当前弹窗之上再叠一层（如生成弹框内「生成参考图」）；父层保留状态，出栈后回到父层 */
export function pushElementPreview(node: ReactNode) { (_push ?? _open)?.(node) }

/** 关闭栈顶一层（栈空则无副作用） */
export function closeElementPreview() { _close?.() }

/** 由 <ElementPreviewModal /> 在挂载/卸载时登记与注销实现 */
export function registerElementPreview(
  open: ((node: ReactNode) => void) | null,
  push: ((node: ReactNode) => void) | null,
  close: (() => void) | null,
) { _open = open; _push = push; _close = close }
