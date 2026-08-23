import { useState, type KeyboardEvent, type PointerEvent } from 'react'

import './SplitHandle.css'

export type SplitHandleOrientation = 'vertical' | 'horizontal'

export interface SplitHandleProps {
  name: string
  orientation: SplitHandleOrientation
  label: string
  percent: number
  minPercent: number
  maxPercent: number
  defaultPercent: number
  onPointerPosition: (position: number) => number
  onChange: (percent: number) => void
}

function clampPercent(percent: number, minPercent: number, maxPercent: number): number {
  return Math.min(maxPercent, Math.max(minPercent, percent))
}

export function SplitHandle({
  name,
  orientation,
  label,
  percent,
  minPercent,
  maxPercent,
  defaultPercent,
  onPointerPosition,
  onChange,
}: SplitHandleProps) {
  const [dragging, setDragging] = useState(false)
  const lowerBound = Math.min(minPercent, maxPercent)
  const upperBound = Math.max(minPercent, maxPercent)
  const currentPercent = clampPercent(percent, lowerBound, upperBound)

  const change = (nextPercent: number) => {
    if (!Number.isFinite(nextPercent)) return
    onChange(clampPercent(nextPercent, lowerBound, upperBound))
  }

  const changeFromPointer = (event: PointerEvent<HTMLDivElement>) => {
    const position = orientation === 'vertical' ? event.clientX : event.clientY
    change(onPointerPosition(position))
  }

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (!event.isPrimary || event.button !== 0) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    setDragging(true)
    changeFromPointer(event)
  }

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
    changeFromPointer(event)
  }

  const finishPointerInteraction = (event: PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setDragging(false)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 5 : 1
    let nextPercent: number | null = null

    if (event.key === 'Home') nextPercent = lowerBound
    if (event.key === 'End') nextPercent = upperBound

    if (orientation === 'vertical') {
      if (event.key === 'ArrowLeft') nextPercent = currentPercent - step
      if (event.key === 'ArrowRight') nextPercent = currentPercent + step
    } else {
      if (event.key === 'ArrowUp') nextPercent = currentPercent - step
      if (event.key === 'ArrowDown') nextPercent = currentPercent + step
    }

    if (nextPercent === null) return
    event.preventDefault()
    change(nextPercent)
  }

  return (
    <div
      className={`split-handle split-handle--${orientation}`}
      data-dragging={dragging || undefined}
      data-layout-splitter={name}
      data-splitter-orientation={orientation}
      role="separator"
      aria-label={label}
      aria-orientation={orientation}
      aria-valuemin={lowerBound}
      aria-valuemax={upperBound}
      aria-valuenow={currentPercent}
      aria-valuetext={`${Math.round(currentPercent)}%`}
      tabIndex={0}
      onDoubleClick={() => change(defaultPercent)}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishPointerInteraction}
      onPointerCancel={finishPointerInteraction}
      onLostPointerCapture={() => setDragging(false)}
    />
  )
}
