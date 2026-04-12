import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'

import { useElementSize } from '../../hooks/useElementSize'

const DEFAULT_MARGIN = 10
const DRAG_HANDLE_SELECTOR = '[data-floating-panel-drag-handle="true"]'
const DRAG_EXCLUDED_SELECTOR = [
  '[data-floating-panel-no-drag="true"]',
  'button',
  'input',
  'select',
  'textarea',
  'a',
].join(', ')

interface FloatingPanelPosition {
  left: number
  top: number
}

interface DraggableFloatingPanelProps {
  containerWidth: number
  containerHeight: number
  children: ReactNode
  margin?: number
  defaultTop?: number
  defaultRight?: number
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

export function DraggableFloatingPanel({
  containerWidth,
  containerHeight,
  children,
  margin = DEFAULT_MARGIN,
  defaultTop,
  defaultRight,
}: DraggableFloatingPanelProps) {
  const { ref: panelRef, width: panelWidth, height: panelHeight } = useElementSize<HTMLDivElement>()
  const panelElementRef = useRef<HTMLDivElement | null>(null)
  const dragStateRef = useRef<{
    pointerId: number
    startClientX: number
    startClientY: number
    originLeft: number
    originTop: number
  } | null>(null)
  const [position, setPosition] = useState<FloatingPanelPosition | null>(null)
  const [dragging, setDragging] = useState(false)
  const resolvedDefaultTop = Math.max(margin, defaultTop ?? margin)
  const resolvedDefaultRight = Math.max(margin, defaultRight ?? margin)

  const maxLeft = useMemo(() => Math.max(margin, containerWidth - panelWidth - margin), [containerWidth, margin, panelWidth])
  const maxTop = useMemo(() => Math.max(margin, containerHeight - panelHeight - margin), [containerHeight, margin, panelHeight])

  const clampPosition = useMemo(() => (
    (nextPosition: FloatingPanelPosition): FloatingPanelPosition => ({
      left: clamp(nextPosition.left, margin, maxLeft),
      top: clamp(nextPosition.top, margin, maxTop),
    })
  ), [margin, maxLeft, maxTop])

  useEffect(() => {
    setPosition((current) => {
      if (current === null) {
        return current
      }
      const nextPosition = clampPosition(current)
      if (nextPosition.left === current.left && nextPosition.top === current.top) {
        return current
      }
      return nextPosition
    })
  }, [clampPosition])

  useEffect(() => {
    if (!dragging) {
      return undefined
    }

    const handlePointerMove = (event: PointerEvent) => {
      const dragState = dragStateRef.current
      if (dragState === null || event.pointerId !== dragState.pointerId) {
        return
      }
      const deltaX = event.clientX - dragState.startClientX
      const deltaY = event.clientY - dragState.startClientY
      setPosition(clampPosition({
        left: dragState.originLeft + deltaX,
        top: dragState.originTop + deltaY,
      }))
    }

    const finishDrag = (pointerId: number) => {
      const dragState = dragStateRef.current
      if (dragState === null || pointerId !== dragState.pointerId) {
        return
      }
      dragStateRef.current = null
      setDragging(false)
    }

    const handlePointerUp = (event: PointerEvent) => {
      finishDrag(event.pointerId)
    }

    const handlePointerCancel = (event: PointerEvent) => {
      finishDrag(event.pointerId)
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerCancel)

    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerCancel)
    }
  }, [clampPosition, dragging])

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null
    if (target === null) {
      return
    }
    if (target.closest(DRAG_EXCLUDED_SELECTOR)) {
      return
    }
    if (!target.closest(DRAG_HANDLE_SELECTOR)) {
      return
    }

    const currentElement = panelElementRef.current
    const measuredWidth = panelWidth || currentElement?.offsetWidth || 0
    const defaultLeft = Math.max(margin, containerWidth - measuredWidth - resolvedDefaultRight)
    const currentPosition = position ?? {
      left: defaultLeft,
      top: clamp(resolvedDefaultTop, margin, maxTop),
    }

    event.preventDefault()
    dragStateRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originLeft: currentPosition.left,
      originTop: currentPosition.top,
    }
    setPosition(currentPosition)
    setDragging(true)
  }

  useLayoutEffect(() => {
    const element = panelElementRef.current
    if (element === null) {
      return
    }
    if (position === null) {
      element.style.top = `${clamp(resolvedDefaultTop, margin, maxTop)}px`
      element.style.left = 'auto'
      element.style.right = `${resolvedDefaultRight}px`
      return
    }
    element.style.left = `${position.left}px`
    element.style.top = `${position.top}px`
    element.style.right = 'auto'
  }, [margin, maxTop, position, resolvedDefaultRight, resolvedDefaultTop])

  return (
    <div
      ref={(node) => {
        panelRef(node)
        panelElementRef.current = node
      }}
      className={`svg-chart__floating-panel-shell${dragging ? ' svg-chart__floating-panel-shell--dragging' : ''}`}
      onPointerDown={handlePointerDown}
    >
      {children}
    </div>
  )
}
