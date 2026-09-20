import * as RSwitch from '@radix-ui/react-switch'
import type { ReactNode } from 'react'

/** 开关：基于 Radix Switch（与 Modal 同族）。
 *
 * 跟复选框的分工：**开关 = 立即生效的二态**（缺才跑 / 质检开启）；
 * 复选框 = 从多项里挑几项。别混用——读屏念出来的语义不一样。
 *
 * 两种外观，同一个组件：
 * - 不传 `children` = 裸轨道（34×20），文字标签由调用处写在外面；
 * - 传 `children` = 胶囊态（`.switch.labeled`），圆点与文字**都在框内**，
 *   整块可点；关时圆点在左、文字在右，开时两者互换（圆点始终指向"当前档"）。
 *
 * Radix 免费接管：role="switch" + aria-checked、空格/回车切换、焦点管理、
 * 受控/非受控、disabled 语义。外观全在 base.css 的 .switch / .switch-thumb。
 */
export function Switch({ checked, onChange, disabled, label, children }: {
  checked: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
  /** 无障碍名称。胶囊态下 children 本身就是可见名称，只在两者不一致时才需要传 */
  label?: string
  /** 显示在开关框内的文字；传了就切胶囊态 */
  children?: ReactNode
}) {
  return (
    <RSwitch.Root
      className={children == null ? 'switch' : 'switch labeled'}
      checked={checked} disabled={disabled}
      aria-label={label} onCheckedChange={onChange}>
      <RSwitch.Thumb className="switch-thumb" />
      {children != null && <span className="switch-label">{children}</span>}
    </RSwitch.Root>
  )
}
