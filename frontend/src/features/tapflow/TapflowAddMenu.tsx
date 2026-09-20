import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Icon, type IconName } from '../../components/Icon'
import type { TapNodeType } from '../../lib/tapflowData'

const ITEMS: Array<{ type: TapNodeType; label: string; refLabel: string; desc?: string; icon: IconName }> = [
  { type: 'text', label: '文本', refLabel: '文本生成', desc: '脚本、广告词、品牌文案', icon: 'text' },
  { type: 'image', label: '图片', refLabel: '图片生成', desc: '出一张图；卡上可挂参考图', icon: 'image' },
  { type: 'video', label: '视频', refLabel: '视频生成', icon: 'video' },
  { type: 'tool', label: '工具', refLabel: '工具调用', desc: '调用系统已注册工具', icon: 'tools' },
  { type: 'flow', label: '工作流', refLabel: '工作流生成', desc: '引用另一张已编排的流程', icon: 'workflow' },
  { type: 'condition', label: '选择器', refLabel: '选择器', desc: '按条件选择下游分支', icon: 'node' },
  { type: 'qc', label: '检查员', refLabel: '检查员', desc: '按判据校验上游产物', icon: 'check' },
  // 挂载点（2026-09-17）：独立声明产物归宿——连到它的产物就存进这个归宿
  { type: 'mount', label: '挂载点', refLabel: '挂载点', desc: '声明产物归宿（封面/角色图…）', icon: 'save' },
  // 开始 / next 是流程固定的首尾节点，不在此菜单里手动添加
]

/**
 * 节点类型菜单：+ 号 →「添加节点」（含 添加资源/上传）；从节点圆点拖出 →「引用该节点生成」。
 * 点菜单外任意处关闭。
 */
export function TapflowAddMenu({ refMode, x, y, onPick, onClose }: {
  refMode: boolean
  x: number; y: number
  onPick: (type: TapNodeType) => void
  onClose: () => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null)

  useLayoutEffect(() => {
    const menu = menuRef.current
    const host = menu?.offsetParent as HTMLElement | null
    if (!menu || !host) return
    const place = () => {
      const margin = 12
      const gap = 12
      const width = menu.offsetWidth
      const height = menu.offsetHeight
      const hostWidth = host.clientWidth
      const hostHeight = host.clientHeight
      let left = x + gap
      let top = y + gap
      if (left + width > hostWidth - margin) left = x - width - gap
      if (top + height > hostHeight - margin) top = y - height - gap
      left = Math.max(margin, Math.min(left, Math.max(margin, hostWidth - width - margin)))
      top = Math.max(margin, Math.min(top, Math.max(margin, hostHeight - height - margin)))
      setPosition({ left, top })
    }
    place()
    const ro = new ResizeObserver(place)
    ro.observe(menu)
    ro.observe(host)
    return () => ro.disconnect()
  }, [x, y])

  useEffect(() => {
    const close = (e: PointerEvent) => {
      if (!(e.target as Element | null)?.closest?.('.tap-add-menu')) onClose()
    }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [onClose])

  const item = (type: TapNodeType, icon: IconName, label: string, desc?: string) => (
    <button key={type} type="button" className="tap-add-item" onClick={() => onPick(type)}>
      <span className="tap-add-ico"><Icon name={icon} /></span>
      <span className="tap-add-text"><b>{label}</b>{desc && <em>{desc}</em>}</span>
    </button>
  )

  return (
    <div ref={menuRef} className="tap-add-menu"
      style={{ left: position?.left ?? x, top: position?.top ?? y, visibility: position ? 'visible' : 'hidden' }}
      onPointerDown={e => e.stopPropagation()}>
      <div className="tap-add-title">{refMode ? '引用该节点生成' : '添加节点'}</div>
      {ITEMS.map(it => item(it.type, it.icon, refMode ? it.refLabel : it.label, it.desc))}
    </div>
  )
}
