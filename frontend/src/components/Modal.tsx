import { useEffect, type ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { popModal, pushModal } from '../lib/uiContext'
import './Modal.css'

/** 通用弹窗外壳：基于 Radix Dialog，复用项目现有 `.modal-card / .modal-head / .modal-x` 样式。
 * Radix 免费接管：焦点陷阱、Esc 关闭、点遮罩关闭、锁 body 滚动、ARIA 无障碍——
 * 各弹窗不必再各自手写这套样板。业务内容照旧写在 children 里（modal-label / modal-actions…）。 */
export function Modal({ open, onClose, title, children, footer, headExtra,
                        closeOnBackdrop = true, wide, full, topmost, cardClass }: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  /** 固定在弹窗底部的操作区；正文滚动时不会随之滚动。 */
  footer?: ReactNode
  /** 标题栏右侧、关闭按钮左边的附加控件（如模式开关） */
  headExtra?: ReactNode
  /** 点遮罩是否关闭（生成中等场景可置 false 锁死） */
  closeOnBackdrop?: boolean
  /** 宽卡片变体 */
  wide?: boolean
  /** 近全屏变体（画布/编排类内容） */
  full?: boolean
  /** 置顶：z-index 抬到抽屉/侧栏(z≈120)之上——从右侧任务队列抽屉里打开弹框时需要 */
  topmost?: boolean
  /** 追加到 `.modal-card` 上的 class：让某类弹窗（如画布）能定向改背景/内边距，不必用 :has() 猜结构 */
  cardClass?: string
}) {
  // 全站弹窗感知：open 时把标题上报到 uiContext 的 modalStack，对话面板据此
  // 知道「用户当前在哪个弹窗里」。只收字符串标题，JSX 标题归为泛称。
  const titleText = typeof title === 'string' ? title : '弹窗'
  useEffect(() => {
    if (!open) return
    pushModal(titleText)
    return () => popModal(titleText)
  }, [open, titleText])
  return (
    <Dialog.Root open={open} onOpenChange={o => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className={'modal-backdrop' + (topmost ? ' rx-top-backdrop' : '')} />
        <Dialog.Content
          className={'modal-card rx-modal' + (wide ? ' rx-modal-wide' : '')
            + (full ? ' rx-modal-full' : '') + (topmost ? ' rx-top' : '')
            + (cardClass ? ' ' + cardClass : '')}
          onInteractOutside={e => {
            // 全站对话浮窗（ChatFab/ChatDock，portal 到 body、z 3100）在 Dialog 树之外，
            // 但它是用户主动唤起的前台件：点它不算「点外面」，否则点浮窗任何地方
            // （切 tab、发消息、按钮）都会把画布/弹窗关掉——点击穿透弹窗，实测踩过。
            // preventDefault 后事件照常落在浮窗元素上，功能不受影响。
            const t = e.target as Element | null
            if (t?.closest?.('.chat-float, .chat-fab')) { e.preventDefault(); return }
            if (!closeOnBackdrop) e.preventDefault()
          }}
          onEscapeKeyDown={e => {
            // 焦点落在对话浮窗里时按 Esc（如收起 @ 菜单）不该冒泡成「关画布」
            const t = e.target as Element | null
            if (t?.closest?.('.chat-float, .chat-fab')) { e.preventDefault(); return }
            if (!closeOnBackdrop) e.preventDefault()
          }}>
          <div className="modal-head">
            <Dialog.Title asChild><b>{title}</b></Dialog.Title>
            {headExtra && <div className="modal-head-extra">{headExtra}</div>}
            <Dialog.Close asChild>
              <button className="modal-x" title="关闭 (Esc)" aria-label="关闭">✕</button>
            </Dialog.Close>
          </div>
          <div className="rx-modal-body">{children}</div>
          {footer && <div className="rx-modal-footer">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
