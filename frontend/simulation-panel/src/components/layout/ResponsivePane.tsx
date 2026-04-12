import * as React from 'react'

import { useElementSize } from '../../hooks/useElementSize'

interface ResponsivePaneSidebarConfig {
  defaultSize?: number
  minSize?: number
  maxSize?: number
  mainMinSize?: number
  resizable?: boolean
}

interface ResponsivePaneProps {
  sidebar?: React.ReactNode
  sidebarConfig?: ResponsivePaneSidebarConfig
  main: React.ReactNode
  footer?: React.ReactNode
}

const DEFAULT_SIDEBAR_SIZE = 280
const DEFAULT_SIDEBAR_MIN_SIZE = 220
const DEFAULT_SIDEBAR_MAX_SIZE = 520
const DEFAULT_MAIN_MIN_SIZE = 320
const RESIZE_HANDLE_SIZE = 10
const RESIZE_KEYBOARD_STEP = 16

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

export function ResponsivePane({ sidebar, sidebarConfig, main, footer }: ResponsivePaneProps) {
  const hasSidebar = Boolean(sidebar)
  const resizable = Boolean(hasSidebar && sidebarConfig?.resizable)
  const defaultSidebarSize = sidebarConfig?.defaultSize ?? DEFAULT_SIDEBAR_SIZE
  const configuredMinSize = sidebarConfig?.minSize ?? DEFAULT_SIDEBAR_MIN_SIZE
  const configuredMaxSize = sidebarConfig?.maxSize ?? DEFAULT_SIDEBAR_MAX_SIZE
  const mainMinSize = sidebarConfig?.mainMinSize ?? DEFAULT_MAIN_MIN_SIZE
  const { ref: paneRef, width: paneWidth } = useElementSize<HTMLDivElement>()
  const paneElementRef = React.useRef<HTMLDivElement | null>(null)
  const [sidebarSize, setSidebarSize] = React.useState(defaultSidebarSize)
  const dragStateRef = React.useRef<{ startX: number; startSize: number } | null>(null)
  const [dragging, setDragging] = React.useState(false)

  const sidebarBounds = React.useMemo(() => {
    const containerBound = paneWidth > 0
      ? Math.max(96, paneWidth - mainMinSize - (resizable ? RESIZE_HANDLE_SIZE : 0))
      : configuredMaxSize
    const max = Math.max(96, Math.min(configuredMaxSize, containerBound))
    const min = Math.min(configuredMinSize, max)
    return { min, max }
  }, [configuredMaxSize, configuredMinSize, mainMinSize, paneWidth, resizable])

  React.useEffect(() => {
    if (!hasSidebar) {
      return
    }
    setSidebarSize((current) => clamp(current, sidebarBounds.min, sidebarBounds.max))
  }, [hasSidebar, sidebarBounds.max, sidebarBounds.min])

  React.useEffect(() => {
    if (!dragging) {
      return undefined
    }

    const handlePointerMove = (event: PointerEvent) => {
      const dragState = dragStateRef.current
      if (dragState === null) {
        return
      }
      const nextSize = dragState.startSize + event.clientX - dragState.startX
      setSidebarSize(clamp(nextSize, sidebarBounds.min, sidebarBounds.max))
    }

    const handlePointerStop = () => {
      dragStateRef.current = null
      setDragging(false)
    }

    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
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
  }, [dragging, sidebarBounds.max, sidebarBounds.min])

  const resolvedSidebarSize = hasSidebar ? clamp(sidebarSize, sidebarBounds.min, sidebarBounds.max) : 0
  const handlePaneRef = React.useMemo(() => (node: HTMLDivElement | null) => {
    paneElementRef.current = node
    paneRef(node)
  }, [paneRef])

  React.useEffect(() => {
    const paneElement = paneElementRef.current
    if (paneElement === null) {
      return
    }
    if (!hasSidebar) {
      paneElement.style.removeProperty('--responsive-pane-sidebar-size')
      return
    }
    paneElement.style.setProperty('--responsive-pane-sidebar-size', `${resolvedSidebarSize}px`)
  }, [hasSidebar, resolvedSidebarSize])

  const paneClassName = [
    'responsive-pane',
    hasSidebar ? 'responsive-pane--with-sidebar' : '',
    resizable ? 'responsive-pane--resizable' : '',
    dragging ? 'responsive-pane--dragging' : '',
  ].filter(Boolean).join(' ')

  const beginResize = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!resizable) {
      return
    }
    event.preventDefault()
    dragStateRef.current = {
      startX: event.clientX,
      startSize: resolvedSidebarSize,
    }
    setDragging(true)
  }

  const handleSeparatorKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!resizable) {
      return
    }

    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      setSidebarSize((current) => clamp(current - RESIZE_KEYBOARD_STEP, sidebarBounds.min, sidebarBounds.max))
      return
    }

    if (event.key === 'ArrowRight') {
      event.preventDefault()
      setSidebarSize((current) => clamp(current + RESIZE_KEYBOARD_STEP, sidebarBounds.min, sidebarBounds.max))
      return
    }

    if (event.key === 'Home') {
      event.preventDefault()
      setSidebarSize(sidebarBounds.min)
      return
    }

    if (event.key === 'End') {
      event.preventDefault()
      setSidebarSize(sidebarBounds.max)
    }
  }

  return (
    <div className="responsive-pane-shell">
      <div ref={handlePaneRef} className={paneClassName}>
        {hasSidebar ? <aside className="responsive-pane__sidebar">{sidebar}</aside> : null}
        {hasSidebar && resizable ? (
          <div
            role="separator"
            tabIndex={0}
            aria-label="Adjust sidebar width"
            aria-orientation="vertical"
            className={`responsive-pane__separator${dragging ? ' responsive-pane__separator--dragging' : ''}`}
            onPointerDown={beginResize}
            onKeyDown={handleSeparatorKeyDown}
          />
        ) : null}
        <section className="responsive-pane__main">{main}</section>
      </div>
      {footer ? <div className="responsive-pane__footer">{footer}</div> : null}
    </div>
  )
}
