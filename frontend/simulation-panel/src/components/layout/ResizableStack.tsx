import * as React from 'react'

import { useElementSize } from '../../hooks/useElementSize'

interface ResizableStackProps {
  primary: React.ReactNode
  secondary: React.ReactNode
  defaultPrimaryRatio?: number
  minPrimarySize?: number
  minSecondarySize?: number
  resizable?: boolean
}

const DEFAULT_PRIMARY_RATIO = 0.7
const DEFAULT_PRIMARY_MIN_SIZE = 140
const DEFAULT_SECONDARY_MIN_SIZE = 96
const DEFAULT_AUTO_PRIMARY_SIZE = 240
const RESIZE_HANDLE_SIZE = 10
const RESIZE_KEYBOARD_STEP = 16

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

export function ResizableStack({
  primary,
  secondary,
  defaultPrimaryRatio = DEFAULT_PRIMARY_RATIO,
  minPrimarySize = DEFAULT_PRIMARY_MIN_SIZE,
  minSecondarySize = DEFAULT_SECONDARY_MIN_SIZE,
  resizable = true,
}: ResizableStackProps) {
  const normalizedRatio = clamp(defaultPrimaryRatio, 0.15, 0.85)
  const { ref: stackRef, height: stackHeight } = useElementSize<HTMLDivElement>()
  const stackElementRef = React.useRef<HTMLDivElement | null>(null)
  const [primarySize, setPrimarySize] = React.useState<number | null>(null)
  const dragStateRef = React.useRef<{ startY: number; startSize: number } | null>(null)
  const [dragging, setDragging] = React.useState(false)

  const primaryBounds = React.useMemo(() => {
    const containerBound = stackHeight > 0
      ? Math.max(72, stackHeight - minSecondarySize - (resizable ? RESIZE_HANDLE_SIZE : 0))
      : Math.max(minPrimarySize, DEFAULT_AUTO_PRIMARY_SIZE)
    const max = Math.max(72, containerBound)
    const min = Math.min(minPrimarySize, max)
    return { min, max }
  }, [minPrimarySize, minSecondarySize, resizable, stackHeight])

  React.useEffect(() => {
    if (!dragging) {
      return undefined
    }

    const handlePointerMove = (event: PointerEvent) => {
      const dragState = dragStateRef.current
      if (dragState === null) {
        return
      }
      const nextSize = dragState.startSize + event.clientY - dragState.startY
      setPrimarySize(clamp(nextSize, primaryBounds.min, primaryBounds.max))
    }

    const handlePointerStop = () => {
      dragStateRef.current = null
      setDragging(false)
    }

    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerStop)
    window.addEventListener('pointercancel', handlePointerStop)

    return () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerStop)
      window.removeEventListener('pointercancel', handlePointerStop)
    }
  }, [dragging, primaryBounds.max, primaryBounds.min])

  const resolvedPrimarySize = clamp(
    primarySize ?? ((stackHeight > 0 ? stackHeight - (resizable ? RESIZE_HANDLE_SIZE : 0) : DEFAULT_AUTO_PRIMARY_SIZE) * normalizedRatio),
    primaryBounds.min,
    primaryBounds.max,
  )

  const handleStackRef = React.useMemo(() => (node: HTMLDivElement | null) => {
    stackElementRef.current = node
    stackRef(node)
  }, [stackRef])

  React.useEffect(() => {
    const stackElement = stackElementRef.current
    if (stackElement === null) {
      return
    }
    stackElement.style.setProperty('--resizable-stack-primary-size', `${resolvedPrimarySize}px`)
  }, [resolvedPrimarySize])

  const beginResize = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!resizable) {
      return
    }
    event.preventDefault()
    dragStateRef.current = {
      startY: event.clientY,
      startSize: resolvedPrimarySize,
    }
    setPrimarySize(resolvedPrimarySize)
    setDragging(true)
  }

  const handleSeparatorKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!resizable) {
      return
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setPrimarySize((current) => clamp((current ?? resolvedPrimarySize) - RESIZE_KEYBOARD_STEP, primaryBounds.min, primaryBounds.max))
      return
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setPrimarySize((current) => clamp((current ?? resolvedPrimarySize) + RESIZE_KEYBOARD_STEP, primaryBounds.min, primaryBounds.max))
      return
    }

    if (event.key === 'Home') {
      event.preventDefault()
      setPrimarySize(primaryBounds.min)
      return
    }

    if (event.key === 'End') {
      event.preventDefault()
      setPrimarySize(primaryBounds.max)
    }
  }

  return (
    <div
      ref={handleStackRef}
      className={`resizable-stack${dragging ? ' resizable-stack--dragging' : ''}`}
    >
      <section className="resizable-stack__primary">{primary}</section>
      {resizable ? (
        <div
          role="separator"
          tabIndex={0}
          aria-label="Adjust section heights"
          aria-orientation="horizontal"
          className={`resizable-stack__separator${dragging ? ' resizable-stack__separator--dragging' : ''}`}
          onPointerDown={beginResize}
          onKeyDown={handleSeparatorKeyDown}
        />
      ) : null}
      <section className="resizable-stack__secondary">{secondary}</section>
    </div>
  )
}
