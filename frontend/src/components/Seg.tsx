import type { ReactNode } from 'react'

/**
 * 分段切换（正文/视频 样式）：浅底圆角容器 + 高亮选中项，通用于分区 tab、比例选择等。
 * 样式为 base.css 的 .seg/.seg-btn 原子类（全局加载，无需组件级 CSS）。
 */
export function Seg<K extends string>({ items, active, onSelect }: {
  items: { key: K; label: ReactNode; title?: string; disabled?: boolean }[]
  active?: string
  onSelect: (key: K) => void
}) {
  return (
    <div className="seg">
      {items.map(it => (
        // 禁用不用原生 disabled（部分浏览器不弹 title 提示），保持可 hover 出 tooltip
        <button key={it.key} type="button" title={it.title} aria-disabled={it.disabled}
          className={`seg-btn${active === it.key ? ' active' : ''}${it.disabled ? ' disabled' : ''}`}
          onClick={() => !it.disabled && onSelect(it.key)}>{it.label}</button>
      ))}
    </div>
  )
}
