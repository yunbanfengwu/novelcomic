import { Icon } from '../../components/Icon'
import type { TapNode } from '../../lib/tapflowData'

export interface TapflowFolder {
  id: string
  nodeIds: string[]
  x: number
  y: number
  w: number
  h: number
  expanded?: boolean
}

const PREVIEW_LIMIT = 3

/**
 * Canvas-only folder preview. Its members remain in the workflow state, but
 * the folder itself is deliberately not a TapNode and is never persisted.
 */
export function TapflowFolderNode({ folder, members, selected, onSelect,
  onDrag, onDragEnd }: {
  folder: TapflowFolder
  members: TapNode[]
  selected: boolean
  onSelect: () => void
  onDrag: (dx: number, dy: number) => void
  onDragEnd?: () => void
}) {
  const previews = members.slice(0, PREVIEW_LIMIT)
  const layerStep = previews.length > 1 ? 24 : 0
  const layerInset = (previews.length - 1) * layerStep

  const onPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation()
    if (e.button !== 0) return
    onSelect()
    let lx = e.clientX
    let ly = e.clientY
    let moved = false
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - lx
      const dy = ev.clientY - ly
      if (Math.abs(dx) > 0 || Math.abs(dy) > 0) moved = true
      onDrag(dx, dy)
      lx = ev.clientX
      ly = ev.clientY
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      if (moved) onDragEnd?.()
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <div
      className={'tap-folder-node' + (selected ? ' selected' : '')}
      style={{ left: folder.x, top: folder.y, width: folder.w }}
      onPointerDown={onPointerDown}>
      <div className="tap-folder-title">
        <Icon name="folder" />
        <span>文件夹</span>
      </div>
      <div className="tap-folder-card" style={{ height: folder.h }}>
        <div className="tap-folder-stack" aria-label={`文件夹，共 ${members.length} 个要素`}>
          {previews.map((member, index) => (
            <div
              key={member.id}
              className="tap-folder-preview"
              style={{
                left: (previews.length - index - 1) * layerStep,
                top: index * layerStep,
                width: `calc(100% - ${layerInset}px)`,
                height: `calc(100% - ${layerInset}px)`,
                zIndex: index + 1,
              }}>
              {member.src
                ? <img src={member.src} alt={member.title} draggable={false} />
                : <span className="tap-folder-placeholder"><Icon name="image" /></span>}
            </div>
          ))}
          {!previews.length && (
            <span className="tap-folder-placeholder"><Icon name="folder" /></span>
          )}
        </div>
        <span className="tap-folder-count"><Icon name="layers" /> {members.length}</span>
        {folder.expanded && (
          <div className="tap-folder-popover" onPointerDown={e => e.stopPropagation()}>
            {members.map(member => (
              <div className="tap-folder-item" key={member.id}>
                {member.src
                  ? <img src={member.src} alt="" draggable={false} />
                  : <span className="tap-folder-item-placeholder"><Icon name="image" /></span>}
                <span>{member.title}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
