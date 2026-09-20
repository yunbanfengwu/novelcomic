import { Icon } from '../Icon'
import type { IconName } from '../Icon'

/** 控制台内「功能待开发」占位面板：菜单已就位，内容区暂以此提示（用户信息管理/充值管理复用）。 */
export function ConsolePlaceholder({ icon, title }: { icon: IconName; title: string }) {
  return (
    <div className="console-empty">
      <Icon name={icon} />
      <b>{title}</b>
      <span className="dim">功能开发中，敬请期待</span>
    </div>
  )
}
