import { GROUP_PAD, type Rect, type TapGroup } from '../../lib/tapflowSelection'

/**
 * 组框：圈住一批节点的半透明灰底圆角框（世界坐标，随画布缩放）。
 * 按下 = 选中整组（Shift 加选），拖动 = 整组一起挪；画在节点**下面**，不挡节点交互。
 */
export function TapflowGroupBox({ group, box, selected, onPick, onDrag }: {
  group: TapGroup
  /** 成员包围盒（世界坐标，未含内边距） */
  box: Rect
  selected: boolean
  onPick: (ids: string[], additive: boolean) => void
  onDrag: (ids: string[], dx: number, dy: number) => void
}) {
  const onPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation()
    if (e.button !== 0) return
    onPick(group.nodeIds, e.shiftKey || e.metaKey)
    let lx = e.clientX, ly = e.clientY
    const move = (ev: PointerEvent) => {
      onDrag(group.nodeIds, ev.clientX - lx, ev.clientY - ly)
      lx = ev.clientX; ly = ev.clientY
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <div
      className={'tap-group' + (selected ? ' selected' : '')}
      style={{
        left: box.x - GROUP_PAD, top: box.y - GROUP_PAD - 18,
        width: box.w + GROUP_PAD * 2, height: box.h + GROUP_PAD * 2 + 18,
      }}
      onPointerDown={onPointerDown}>
      <span className="tap-group-name">{group.name}</span>
    </div>
  )
}
