import { useCallback, useEffect, useRef, useState } from 'react'

import { useElementSize } from '../../hooks/useElementSize'
import type { SchematicDocumentState } from '../../types/state'
import { getUiText, type UiTextMap } from '../../uiText'
import {
  getSchematicSymbolDefinition,
  isSchematicComponentReadonly,
  renderSchematicPinStub,
  type SchematicPinStubAppearance,
  type SchematicSymbolAppearance,
} from './symbolRegistry'
import { fitSchematicViewToBounds, makeViewTargetWorldPoint } from './schematicLayout'
import {
  SCHEMATIC_NET_LABEL_HEIGHT,
  computeSchematicLabelRect,
  getSchematicNetLabelWidth,
} from './schematicLabelPlanner'
import { getSchematicComponentDisplayName } from './schematicComponentName'
import type { SchematicCanvasViewState, SchematicLayoutResult } from './schematicLayoutTypes'

interface SchematicCanvasProps {
  schematicDocument: SchematicDocumentState
  layoutResult: SchematicLayoutResult | null
  layoutPending: boolean
  layoutError: string
  selectedComponentId: string | null
  uiText: UiTextMap
  viewState: SchematicCanvasViewState
  onViewStateChange(nextViewState: SchematicCanvasViewState): void
  onViewportSizeChange(size: { width: number; height: number }): void
  onSelectComponent(componentId: string | null): void
}

const MIN_SCALE = 0.35
const MAX_SCALE = 2.6

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function buildPolylinePoints(points: Array<{ x: number; y: number }>): string {
  return points.map((point) => `${point.x},${point.y}`).join(' ')
}

function isInteractiveComponentTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest('[data-schematic-component="true"]'))
}

function resolveGroupTone(depth: number): { stroke: string; fill: string; text: string } {
  const normalizedDepth = Math.min(Math.max(depth, 1), 4)
  const strokeOpacity = 0.16 + normalizedDepth * 0.04
  const fillOpacity = 0.06 + normalizedDepth * 0.025
  return {
    stroke: `rgba(37, 99, 235, ${strokeOpacity})`,
    fill: `rgba(219, 234, 254, ${fillOpacity})`,
    text: normalizedDepth >= 3 ? '#1d4ed8' : '#2563eb',
  }
}

function resolveAppearance(selected: boolean, hovered: boolean, readonly: boolean): SchematicSymbolAppearance {
  if (selected) {
    return {
      stroke: '#2563eb',
      fill: '#dbeafe',
      accent: '#1d4ed8',
      text: '#1e3a8a',
      pinFill: '#2563eb',
      readonly,
    }
  }
  if (hovered) {
    return {
      stroke: readonly ? '#64748b' : '#3b82f6',
      fill: readonly ? '#f1f5f9' : '#eff6ff',
      accent: readonly ? '#64748b' : '#2563eb',
      text: readonly ? '#475569' : '#1e3a8a',
      pinFill: readonly ? '#64748b' : '#2563eb',
      readonly,
    }
  }
  if (readonly) {
    return {
      stroke: '#94a3b8',
      fill: '#f8fafc',
      accent: '#64748b',
      text: '#475569',
      pinFill: '#94a3b8',
      readonly,
    }
  }
  return {
    stroke: '#0f172a',
    fill: '#ffffff',
    accent: '#1d4ed8',
    text: '#0f172a',
    pinFill: '#0f172a',
    readonly,
  }
}

export function SchematicCanvas({
  schematicDocument,
  layoutResult,
  layoutPending,
  layoutError,
  selectedComponentId,
  uiText,
  viewState,
  onViewStateChange,
  onViewportSizeChange,
  onSelectComponent,
}: SchematicCanvasProps) {
  const { ref: viewportSizeRefCallback, width, height } = useElementSize<HTMLDivElement>()
  const [hoveredComponentId, setHoveredComponentId] = useState('')
  const [panning, setPanning] = useState(false)
  const dragStateRef = useRef<{ startX: number; startY: number; offsetX: number; offsetY: number; moved: boolean } | null>(null)
  const panMovedRef = useRef(false)
  const viewportNodeRef = useRef<HTMLDivElement | null>(null)

  // Composed ref: delegates to `useElementSize`'s callback ref (which tracks
  // size via ResizeObserver) while also capturing the DOM node so the native
  // wheel listener below can target it directly. React accepts callback refs,
  // so we compose both handlers into one.
  const assignViewportNode = useCallback((node: HTMLDivElement | null) => {
    viewportNodeRef.current = node
    viewportSizeRefCallback(node)
  }, [viewportSizeRefCallback])

  useEffect(() => {
    onViewportSizeChange({ width, height })
  }, [height, onViewportSizeChange, width])

  useEffect(() => {
    if (!hoveredComponentId) {
      return
    }
    if (!(layoutResult?.components.some((item) => item.component.id === hoveredComponentId) ?? false)) {
      setHoveredComponentId('')
    }
  }, [hoveredComponentId, layoutResult])

  useEffect(() => {
    if (!panning) {
      return undefined
    }

    const handlePointerMove = (event: PointerEvent) => {
      const dragState = dragStateRef.current
      if (dragState === null) {
        return
      }
      const deltaX = event.clientX - dragState.startX
      const deltaY = event.clientY - dragState.startY
      if (!dragState.moved && (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3)) {
        dragState.moved = true
        panMovedRef.current = true
      }
      onViewStateChange({
        scale: viewState.scale,
        offsetX: dragState.offsetX + deltaX,
        offsetY: dragState.offsetY + deltaY,
      })
    }

    const handlePointerStop = () => {
      dragStateRef.current = null
      setPanning(false)
    }

    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'grabbing'
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
  }, [onViewStateChange, panning, viewState.scale])

  const handleViewportPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || isInteractiveComponentTarget(event.target)) {
      return
    }
    dragStateRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      offsetX: viewState.offsetX,
      offsetY: viewState.offsetY,
      moved: false,
    }
    panMovedRef.current = false
    setPanning(true)
  }

  const handleViewportClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (panMovedRef.current) {
      panMovedRef.current = false
      return
    }
    if (!isInteractiveComponentTarget(event.target)) {
      return
    }
  }

  // --------------------------------------------------------------------------
  // Native wheel listener, intentionally bypassing React's synthetic event
  // system. React 17+ attaches `wheel` / `touchstart` / `touchmove` delegated
  // listeners with `{ passive: true }` as a global performance policy; inside a
  // passive listener the browser silently drops `event.preventDefault()` and
  // emits a Chromium warning (elevated to `[Qt Critical]` inside Qt WebEngine).
  // Without `preventDefault` the default page scroll races with our zoom, so we
  // must register a non-passive listener via the native API. `useRef` shadows
  // capture the latest view-state so the listener itself is mounted exactly
  // once and never torn down per frame.
  // --------------------------------------------------------------------------
  const viewStateRef = useRef(viewState)
  const onViewStateChangeRef = useRef(onViewStateChange)
  const viewportSizeRef = useRef({ width, height })

  useEffect(() => {
    viewStateRef.current = viewState
  }, [viewState])
  useEffect(() => {
    onViewStateChangeRef.current = onViewStateChange
  }, [onViewStateChange])
  useEffect(() => {
    viewportSizeRef.current = { width, height }
  }, [width, height])

  useEffect(() => {
    const node = viewportNodeRef.current
    if (node === null) {
      return undefined
    }
    const handleNativeWheel = (event: WheelEvent) => {
      const { width: currentWidth, height: currentHeight } = viewportSizeRef.current
      if (currentWidth <= 0 || currentHeight <= 0) {
        return
      }
      // Must precede any early return so the browser also suppresses default
      // scroll for no-op zoom attempts (e.g. already at MIN/MAX scale).
      event.preventDefault()
      const currentViewState = viewStateRef.current
      const nextScale = clamp(
        currentViewState.scale * (event.deltaY < 0 ? 1.12 : 1 / 1.12),
        MIN_SCALE,
        MAX_SCALE,
      )
      if (nextScale === currentViewState.scale) {
        return
      }
      const rect = node.getBoundingClientRect()
      const worldPoint = makeViewTargetWorldPoint(event.clientX, event.clientY, rect, currentViewState)
      onViewStateChangeRef.current({
        scale: nextScale,
        offsetX: event.clientX - rect.left - worldPoint.x * nextScale,
        offsetY: event.clientY - rect.top - worldPoint.y * nextScale,
      })
    }
    node.addEventListener('wheel', handleNativeWheel, { passive: false })
    return () => {
      node.removeEventListener('wheel', handleNativeWheel)
    }
    // The viewport node becomes available after the first commit via the
    // composed ref callback; mounting the listener during that first effect
    // pass is sufficient because the ref target is stable for the component's
    // lifetime.
  }, [])

  // Fit viewport: recomputes view-state from the current layout bounds
  // and actual viewport size. The overlay button that calls this lives
  // inside the canvas (top-right corner) so fit is a canvas-local
  // capability; the tab shell never participates.
  const canFit = Boolean(layoutResult?.bounds) && width > 0 && height > 0
  const handleFit = useCallback(() => {
    const bounds = layoutResult?.bounds
    if (!bounds || width <= 0 || height <= 0) {
      return
    }
    onViewStateChange(fitSchematicViewToBounds(bounds, width, height))
  }, [height, layoutResult, onViewStateChange, width])

  const hasSourceFile = Boolean(schematicDocument.file_path)
  const layoutComponents = layoutResult?.components ?? []
  const layoutGroups = layoutResult?.groups ?? []
  const layoutNets = layoutResult?.nets ?? []
  const hasRenderableLayout = hasSourceFile && schematicDocument.has_schematic && layoutComponents.length > 0
  const svgWidth = Math.max(width, 320)
  const svgHeight = Math.max(height, 240)

  const emptyStateTitle = !hasSourceFile
    ? getUiText(uiText, 'simulation.schematic.empty_no_source_title', 'No schematic source file is available')
    : layoutPending && schematicDocument.has_schematic
      ? getUiText(uiText, 'simulation.schematic.empty_layout_pending_title', 'Computing schematic layout')
      : layoutError
        ? getUiText(uiText, 'simulation.schematic.empty_layout_failed_title', 'Schematic layout failed')
        : getUiText(uiText, 'simulation.schematic.empty_not_renderable_title', 'The current document has no renderable schematic')

  const emptyStateDescription = !hasSourceFile
    ? getUiText(uiText, 'simulation.schematic.empty_no_source_description', 'The current result does not yet provide a source file path that the schematic tab can consume.')
    : layoutPending && schematicDocument.has_schematic
      ? getUiText(uiText, 'simulation.schematic.empty_layout_pending_description', 'Computing the schematic layout from the latest schematic document.')
      : layoutError || schematicDocument.file_name || schematicDocument.title || getUiText(uiText, 'simulation.schematic.empty_not_renderable_description', 'The current schematic document did not provide drawable components.')

  return (
    <div className="schematic-canvas">
      <div
        ref={assignViewportNode}
        className={`schematic-canvas__viewport${panning ? ' schematic-canvas__viewport--dragging' : ''}`}
        onPointerDown={handleViewportPointerDown}
        onClick={handleViewportClick}
      >
        {hasRenderableLayout ? (
          <svg className="schematic-canvas__svg" width={svgWidth} height={svgHeight} viewBox={`0 0 ${svgWidth} ${svgHeight}`}>
            <defs>
              <pattern id="schematic-grid" width="28" height="28" patternUnits="userSpaceOnUse">
                <path d="M 28 0 L 0 0 0 28" fill="none" stroke="rgba(148, 163, 184, 0.18)" strokeWidth="1" />
              </pattern>
            </defs>
            <rect x={0} y={0} width={svgWidth} height={svgHeight} fill="url(#schematic-grid)" />
            <g transform={`translate(${viewState.offsetX} ${viewState.offsetY}) scale(${viewState.scale})`}>
              {layoutGroups.map((group) => {
                const tone = resolveGroupTone(group.depth)
                return (
                  <g className="schematic-canvas__group" key={group.id}>
                    <rect
                      x={group.bounds.x}
                      y={group.bounds.y}
                      width={group.bounds.width}
                      height={group.bounds.height}
                      rx={18}
                      fill={tone.fill}
                      stroke={tone.stroke}
                      strokeWidth={1.5}
                      strokeDasharray="7 5"
                    />
                    <text
                      x={group.bounds.x + 16}
                      y={group.bounds.y + 18}
                      className="schematic-canvas__group-label"
                      fill={tone.text}
                    >
                      {group.label}
                    </text>
                  </g>
                )
              })}
              {layoutNets.map((net) => {
                const labelWidth = net.label ? getSchematicNetLabelWidth(net.label.text) : 0
                const labelRect = net.label
                  ? computeSchematicLabelRect(net.label, labelWidth, SCHEMATIC_NET_LABEL_HEIGHT, 'middle')
                  : null
                return (
                  <g className="schematic-canvas__net" key={net.net.id}>
                    {net.segments.map((segment) => (
                      <polyline
                        key={segment.key}
                        points={buildPolylinePoints(segment.points)}
                        fill="none"
                        stroke="#94a3b8"
                        strokeWidth={2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    ))}
                    {net.label && labelRect ? (
                      <g>
                        <rect
                          className="schematic-canvas__net-label-backdrop"
                          x={labelRect.x}
                          y={labelRect.y}
                          rx={8}
                          width={labelRect.width}
                          height={labelRect.height}
                        />
                        <text
                          className="schematic-canvas__net-label"
                          x={net.label.x}
                          y={net.label.y}
                          textAnchor={net.label.textAnchor}
                          dominantBaseline="middle"
                        >
                          {net.label.text}
                        </text>
                      </g>
                    ) : null}
                  </g>
                )
              })}
              {layoutComponents.map((item) => {
                const selected = item.component.id === selectedComponentId
                const hovered = item.component.id === hoveredComponentId
                const readonly = isSchematicComponentReadonly(item.component)
                const appearance = resolveAppearance(selected, hovered, readonly)
                const symbolDefinition = getSchematicSymbolDefinition(item.component.symbol_kind)
                // The layout pipeline has already rotated every coordinate
                // (pins, stubs, labels, net endpoints) into the final world
                // position. What is still oriented the "original" way is the
                // symbol glyph itself — the path data inside
                // `symbolDefinition.render()` is drawn against the untouched
                // `symbolDefinition.width` × `symbolDefinition.height` local
                // space. When `item.rotation === 90`, we compose a 90°
                // clockwise rotation around the top-left of the local symbol
                // box so the glyph aligns with the already-rotated pin
                // anchors; the `translate` then re-anchors that rotated box
                // at the correct spot in world space.
                const symbolTransform =
                  item.rotation === 90
                    ? `translate(${item.symbolBounds.x + item.symbolBounds.width} ${item.symbolBounds.y}) rotate(90)`
                    : `translate(${item.symbolBounds.x} ${item.symbolBounds.y})`
                return (
                  <g
                    key={item.component.id}
                    data-schematic-component="true"
                    className={`schematic-canvas__component${selected ? ' schematic-canvas__component--selected' : ''}${hovered ? ' schematic-canvas__component--hovered' : ''}${readonly ? ' schematic-canvas__component--readonly' : ''}`}
                    onMouseEnter={() => setHoveredComponentId(item.component.id)}
                    onMouseLeave={() => setHoveredComponentId((current) => (current === item.component.id ? '' : current))}
                    onClick={(event) => {
                      event.stopPropagation()
                      onSelectComponent(item.component.id)
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onSelectComponent(item.component.id)
                      }
                    }}
                    tabIndex={0}
                    role="button"
                    aria-label={getUiText(uiText, 'simulation.schematic.select_component', 'Select component {name}', { name: getSchematicComponentDisplayName(item.component) || item.component.id })}
                  >
                    <rect
                      className="schematic-canvas__component-hit"
                      x={item.bounds.x}
                      y={item.bounds.y}
                      width={item.bounds.width}
                      height={item.bounds.height}
                      fill="transparent"
                      pointerEvents="all"
                    />
                    <g transform={symbolTransform}>
                      {(() => {
                        const dimensions = symbolDefinition.getDimensions(item.component)
                        return symbolDefinition.render({
                          component: item.component,
                          width: dimensions.width,
                          height: dimensions.height,
                          appearance,
                        })
                      })()}
                    </g>
                    {item.pins.map((pin) => {
                      const stubAppearance: SchematicPinStubAppearance = {
                        stroke: appearance.accent,
                        fill: appearance.fill,
                        text: appearance.text,
                      }
                      return (
                        <g key={pin.id}>
                          {pin.stub ? renderSchematicPinStub(pin.stub, stubAppearance) : null}
                          <circle
                            cx={pin.x}
                            cy={pin.y}
                            r={4.4}
                            fill={appearance.pinFill}
                          />
                        </g>
                      )
                    })}
                    {item.nameLabel ? (
                      <text
                        x={item.nameLabel.x}
                        y={item.nameLabel.y}
                        textAnchor={item.nameLabel.textAnchor}
                        className="schematic-canvas__instance-label"
                        fill={appearance.text}
                      >
                        {item.nameLabel.text}
                      </text>
                    ) : null}
                    {item.valueLabel ? (
                      <text
                        x={item.valueLabel.x}
                        y={item.valueLabel.y}
                        textAnchor={item.valueLabel.textAnchor}
                        className="schematic-canvas__value-label"
                        fill={appearance.accent}
                      >
                        {item.valueLabel.text}
                      </text>
                    ) : null}
                  </g>
                )
              })}
            </g>
          </svg>
        ) : (
          <div className="schematic-canvas__empty-state">
            <div className={`surface-state-card ${layoutError ? 'surface-state-card--warning' : hasSourceFile ? 'surface-state-card--warning' : 'surface-state-card--empty'}`}>
              <div className="card-title">{emptyStateTitle}</div>
              <div className="muted-text">{emptyStateDescription}</div>
              {schematicDocument.parse_errors.length > 0 ? (
                <div className="surface-state-stack">
                  {schematicDocument.parse_errors.slice(0, 3).map((item, index) => (
                    <div className="muted-text" key={`${item.source_file}-${item.line_index}-${index}`}>
                      {item.message}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        )}
        {(layoutPending || layoutError || (hasSourceFile && hasRenderableLayout && schematicDocument.parse_errors.length > 0)) ? (
          <div className="schematic-canvas__floating-banner">
            <div className="schematic-canvas__floating-banner-stack">
              {layoutPending ? (
                <div className="surface-state-card">
                  <div className="card-title">{getUiText(uiText, 'simulation.schematic.banner_layout_pending_title', 'Layout computation in progress')}</div>
                  <div className="muted-text">{getUiText(uiText, 'simulation.schematic.banner_layout_pending_description', 'Only the latest layout result for the current document and revision will be applied.')}</div>
                </div>
              ) : null}
              {layoutError ? (
                <div className="surface-state-card surface-state-card--warning">
                  <div className="card-title">{getUiText(uiText, 'simulation.schematic.banner_layout_failed_title', 'Layout failed')}</div>
                  <div className="muted-text">{layoutError}</div>
                </div>
              ) : null}
              {hasSourceFile && hasRenderableLayout && schematicDocument.parse_errors.length > 0 ? (
                <div className="surface-state-card surface-state-card--warning">
                  <div className="card-title">{getUiText(uiText, 'simulation.schematic.banner_parse_warnings_title', 'Parse Warnings')}</div>
                  {schematicDocument.parse_errors.slice(0, 2).map((item, index) => (
                    <div className="muted-text" key={`${item.source_file}-${item.line_index}-${index}`}>
                      {item.message}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
        <div className="schematic-canvas__fit-overlay">
          <button
            type="button"
            className="sim-compact-button"
            disabled={!canFit}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={handleFit}
          >
            {getUiText(uiText, 'common.fit', 'Fit')}
          </button>
        </div>
      </div>
    </div>
  )
}
