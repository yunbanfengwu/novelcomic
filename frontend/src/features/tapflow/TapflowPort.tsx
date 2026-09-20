import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { Icon } from '../../components/Icon'

const PORT_RADIUS = 11
const POINTER_OFFSET = 0
const FOLLOW_EASING = 0.09

/**
 * A permanent transparent activation area around a node edge. The visible port
 * follows the pointer inside this area, so connecting does not require aiming
 * at a small fixed target.
 */
export function TapflowPort({ side, onDrag }: {
  side: 'left' | 'right'
  onDrag?: (e: PointerEvent<HTMLDivElement>) => void
}) {
  const [active, setActive] = useState(false)
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null)
  const currentRef = useRef<{ x: number; y: number } | null>(null)
  const targetRef = useRef<{ x: number; y: number } | null>(null)
  const frameRef = useRef<number | null>(null)

  useEffect(() => () => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
  }, [])

  const animateTowardsPointer = () => {
    const target = targetRef.current
    const current = currentRef.current
    if (!target || !current) { frameRef.current = null; return }
    const next = {
      x: current.x + (target.x - current.x) * FOLLOW_EASING,
      y: current.y + (target.y - current.y) * FOLLOW_EASING,
    }
    currentRef.current = next
    setPosition(next)
    if (Math.abs(target.x - next.x) > 0.1 || Math.abs(target.y - next.y) > 0.1) {
      frameRef.current = requestAnimationFrame(animateTowardsPointer)
    } else {
      currentRef.current = target
      setPosition(target)
      frameRef.current = null
    }
  }

  const followPointer = (e: PointerEvent<HTMLDivElement>) => {
    const zone = e.currentTarget
    const rect = zone.getBoundingClientRect()
    // getBoundingClientRect uses screen pixels, while absolute positioning uses
    // the unscaled canvas coordinate system. Convert between the two explicitly.
    const scaleX = rect.width > 0 ? zone.offsetWidth / rect.width : 1
    const scaleY = rect.height > 0 ? zone.offsetHeight / rect.height : 1
    const x = (e.clientX - rect.left) * scaleX - POINTER_OFFSET
    const y = (e.clientY - rect.top) * scaleY - POINTER_OFFSET
    const target = {
      x: Math.max(PORT_RADIUS, Math.min(x, zone.offsetWidth - PORT_RADIUS)),
      y: Math.max(PORT_RADIUS, Math.min(y, zone.offsetHeight - PORT_RADIUS)),
    }
    targetRef.current = target
    currentRef.current ??= { x: zone.offsetWidth / 2, y: zone.offsetHeight / 2 }
    if (frameRef.current === null) frameRef.current = requestAnimationFrame(animateTowardsPointer)
  }

  return (
    <div
      className={`tap-port-zone ${side}${active ? ' active' : ''}`}
      onPointerEnter={() => setActive(true)}
      onPointerLeave={() => setActive(false)}
      onPointerMove={followPointer}
      onPointerDown={e => {
        e.stopPropagation()
        onDrag?.(e)
      }}>
      <span
        className="tap-port"
        style={position ? { left: position.x, top: position.y } : undefined}>
        <Icon name="plus" />
      </span>
    </div>
  )
}
