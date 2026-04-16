import { useEffect, useMemo, useRef, useState } from 'react'

import { useElementSize } from '../../hooks/useElementSize'
import type { SchematicComponentState, SchematicDocumentState, SchematicNetState, SchematicPinState } from '../../types/state'
import { getSchematicSymbolDefinition, isSchematicComponentReadonly, type SchematicSymbolAppearance, type SchematicSymbolAnchor } from './symbolRegistry'
import { makeViewTargetWorldPoint, type SchematicCanvasViewState, type SchematicLayoutPin, type SchematicLayoutResult as ElkSchematicLayoutResult } from './schematicLayout'

interface SchematicCanvasProps {
  schematicDocument: SchematicDocumentState
  layoutResult: ElkSchematicLayoutResult | null
  layoutPending: boolean
  layoutError: string
  selectedComponentId: string | null
  fitSignal: number
  relayoutSignal: number
  viewState: SchematicCanvasViewState
  onViewStateChange(nextViewState: SchematicCanvasViewState): void
  onViewportSizeChange(size: { width: number; height: number }): void
  onSelectComponent(componentId: string | null): void
}

interface ViewState {
  scale: number
  offsetX: number
  offsetY: number
}

interface Point {
  x: number
  y: number
}

interface Bounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

interface PositionedPin {
  pin: SchematicPinState
  anchor: SchematicSymbolAnchor
  absolute: Point
}

interface PositionedComponent {
  component: SchematicComponentState
  definitionWidth: number
  definitionHeight: number
  x: number
  y: number
  center: Point
  pins: PositionedPin[]
}

interface NetPolyline {
  key: string
  points: string
}

interface PositionedNet {
  net: SchematicNetState
  segments: NetPolyline[]
  hub: Point | null
  label: string
  labelX: number
  labelY: number
}

interface SchematicLayoutResult {
  components: PositionedComponent[]
  nets: PositionedNet[]
  bounds: Bounds | null
}

const MIN_SCALE = 0.35
const MAX_SCALE = 2.6
const FIT_PADDING = 56
const GRID_COLUMN_WIDTH = 220
const GRID_ROW_HEIGHT = 172
const GRID_MARGIN = 52

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function createEmptyViewState(): ViewState {
  return {
    scale: 1,
    offsetX: 0,
    offsetY: 0,
  }
}

function createBounds(x: number, y: number): Bounds {
  return {
    minX: x,
    minY: y,
    maxX: x,
    maxY: y,
  }
}

function includePoint(bounds: Bounds | null, point: Point): Bounds {
  if (bounds === null) {
    return createBounds(point.x, point.y)
  }
  return {
    minX: Math.min(bounds.minX, point.x),
    minY: Math.min(bounds.minY, point.y),
    maxX: Math.max(bounds.maxX, point.x),
    maxY: Math.max(bounds.maxY, point.y),
  }
}

function includeRect(bounds: Bounds | null, x: number, y: number, width: number, height: number): Bounds {
  let nextBounds = includePoint(bounds, { x, y })
  nextBounds = includePoint(nextBounds, { x: x + width, y: y + height })
  return nextBounds
}

function getBoundsWidth(bounds: Bounds): number {
  return Math.max(1, bounds.maxX - bounds.minX)
}

function getBoundsHeight(bounds: Bounds): number {
  return Math.max(1, bounds.maxY - bounds.minY)
}

function buildPolylinePoints(points: Point[]): string {
  return points.map((point) => `${point.x},${point.y}`).join(' ')
}

function getComponentSortKey(component: SchematicComponentState): string {
  return [component.scope_path.join('/'), component.instance_name, component.display_name, component.id].join('|')
}

function rotateComponents(components: SchematicComponentState[], relayoutSignal: number): SchematicComponentState[] {
  if (components.length <= 1) {
    return components
  }
  const rotation = Math.abs(relayoutSignal) % components.length
  if (rotation === 0) {
    return components
  }
  return [...components.slice(rotation), ...components.slice(0, rotation)]
}

function buildLayout(document: SchematicDocumentState, relayoutSignal: number): SchematicLayoutResult {
  const orderedComponents = [...document.components].sort((left, right) => getComponentSortKey(left).localeCompare(getComponentSortKey(right)))
  const rotatedComponents = rotateComponents(orderedComponents, relayoutSignal)
  if (!rotatedComponents.length) {
    return {
      components: [],
      nets: [],
      bounds: null,
    }
  }

  const baseColumnCount = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(rotatedComponents.length))))
  const columnCount = Math.max(1, Math.min(5, baseColumnCount + (relayoutSignal % 2)))
  let bounds: Bounds | null = null

  const positionedComponents = rotatedComponents.map((component, index) => {
    const definition = getSchematicSymbolDefinition(component.symbol_kind)
    const columnIndex = index % columnCount
    const rowIndex = Math.floor(index / columnCount)
    const x = GRID_MARGIN + columnIndex * GRID_COLUMN_WIDTH + (GRID_COLUMN_WIDTH - definition.width) / 2
    const y = GRID_MARGIN + rowIndex * GRID_ROW_HEIGHT + (GRID_ROW_HEIGHT - definition.height) / 2
    const pins = component.pins.map((pin, pinIndex) => {
      const anchor = definition.getPinAnchor(component, pin, pinIndex)
      return {
        pin,
        anchor,
        absolute: {
          x: x + anchor.x,
          y: y + anchor.y,
        },
      }
    })
    bounds = includeRect(bounds, x - 24, y - 36, definition.width + 48, definition.height + 72)
    return {
      component,
      definitionWidth: definition.width,
      definitionHeight: definition.height,
      x,
      y,
      center: {
        x: x + definition.width / 2,
        y: y + definition.height / 2,
      },
      pins,
    }
  })

  const componentMap = new Map(positionedComponents.map((item) => [item.component.id, item]))
  const positionedNets: PositionedNet[] = []

  for (const net of document.nets) {
    const anchors = net.connections
      .map((connection) => {
        const component = componentMap.get(connection.component_id)
        if (!component) {
          return null
        }
        const pin = component.pins.find((item) => item.pin.name === connection.pin_name)
        if (!pin) {
          return null
        }
        return pin.absolute
      })
      .filter((item): item is Point => item !== null)

    if (!anchors.length) {
      continue
    }

    const label = net.name || net.id
    const hub = anchors.length >= 3
      ? {
          x: anchors.reduce((sum, point) => sum + point.x, 0) / anchors.length,
          y: anchors.reduce((sum, point) => sum + point.y, 0) / anchors.length,
        }
      : null

    const segments: NetPolyline[] = []

    if (anchors.length === 1) {
      const anchor = anchors[0]
      segments.push({
        key: `${net.id}-stub`,
        points: buildPolylinePoints([
          anchor,
          { x: anchor.x + 26, y: anchor.y },
        ]),
      })
    } else if (anchors.length === 2) {
      const [first, second] = anchors
      if (Math.abs(first.x - second.x) >= Math.abs(first.y - second.y)) {
        const middleX = (first.x + second.x) / 2
        segments.push({
          key: `${net.id}-pair`,
          points: buildPolylinePoints([
            first,
            { x: middleX, y: first.y },
            { x: middleX, y: second.y },
            second,
          ]),
        })
      } else {
        const middleY = (first.y + second.y) / 2
        segments.push({
          key: `${net.id}-pair`,
          points: buildPolylinePoints([
            first,
            { x: first.x, y: middleY },
            { x: second.x, y: middleY },
            second,
          ]),
        })
      }
    } else if (hub !== null) {
      for (const anchor of anchors) {
        const points: Point[] = [anchor]
        if (Math.abs(anchor.x - hub.x) >= Math.abs(anchor.y - hub.y)) {
          const elbowX = anchor.x < hub.x ? Math.min(anchor.x + 28, hub.x) : Math.max(anchor.x - 28, hub.x)
          points.push({ x: elbowX, y: anchor.y })
          points.push({ x: elbowX, y: hub.y })
        } else {
          const elbowY = anchor.y < hub.y ? Math.min(anchor.y + 28, hub.y) : Math.max(anchor.y - 28, hub.y)
          points.push({ x: anchor.x, y: elbowY })
          points.push({ x: hub.x, y: elbowY })
        }
        points.push(hub)
        segments.push({
          key: `${net.id}-${anchor.x}-${anchor.y}`,
          points: buildPolylinePoints(points),
        })
      }
    }

    for (const segment of segments) {
      for (const pointText of segment.points.split(' ')) {
        const [xText, yText] = pointText.split(',')
        bounds = includePoint(bounds, { x: Number(xText), y: Number(yText) })
      }
    }

    const labelPoint = hub ?? anchors[0]
    bounds = includeRect(bounds, labelPoint.x - 4, labelPoint.y - 28, Math.max(42, label.length * 7 + 14), 24)
    positionedNets.push({
      net,
      segments,
      hub,
      label,
      labelX: labelPoint.x + 6,
      labelY: labelPoint.y - 10,
    })
  }

  return {
    components: positionedComponents,
    nets: positionedNets,
    bounds,
  }
}

function fitToBounds(bounds: Bounds, width: number, height: number): ViewState {
  const paddedWidth = Math.max(1, width - FIT_PADDING * 2)
  const paddedHeight = Math.max(1, height - FIT_PADDING * 2)
  const scale = clamp(Math.min(paddedWidth / getBoundsWidth(bounds), paddedHeight / getBoundsHeight(bounds)), MIN_SCALE, MAX_SCALE)
  const centerX = (bounds.minX + bounds.maxX) / 2
  const centerY = (bounds.minY + bounds.maxY) / 2
  return {
    scale,
    offsetX: width / 2 - centerX * scale,
    offsetY: height / 2 - centerY * scale,
  }
}

function makeRequestTargetWorldPoint(clientX: number, clientY: number, rect: DOMRect, viewState: ViewState): Point {
  return {
    x: (clientX - rect.left - viewState.offsetX) / viewState.scale,
    y: (clientY - rect.top - viewState.offsetY) / viewState.scale,
  }
}

function isInteractiveComponentTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest('[data-schematic-component="true"]'))
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

function renderPinLabel(pin: PositionedPin, appearance: SchematicSymbolAppearance): JSX.Element {
  const { absolute, pin: pinState, anchor } = pin
  let textAnchor: 'start' | 'middle' | 'end' = 'start'
  let labelX = absolute.x + 10
  let labelY = absolute.y + 4

  if (anchor.side === 'left') {
    textAnchor = 'end'
    labelX = absolute.x - 10
  } else if (anchor.side === 'right') {
    textAnchor = 'start'
    labelX = absolute.x + 10
  } else if (anchor.side === 'top') {
    textAnchor = 'middle'
    labelX = absolute.x
    labelY = absolute.y - 10
  } else {
    textAnchor = 'middle'
    labelX = absolute.x
    labelY = absolute.y + 16
  }

  return (
    <text
      x={labelX}
      y={labelY}
      textAnchor={textAnchor}
      className="schematic-canvas__pin-label"
      fill={appearance.text}
    >
      {pinState.name}
    </text>
  )
}

export function SchematicCanvas({ schematicDocument, selectedComponentId, fitSignal, relayoutSignal, onSelectComponent }: SchematicCanvasProps) {
  const { ref, width, height } = useElementSize<HTMLDivElement>()
  const [hoveredComponentId, setHoveredComponentId] = useState('')
  const [viewState, setViewState] = useState<ViewState>(createEmptyViewState)
  const [panning, setPanning] = useState(false)
  const dragStateRef = useRef<{ startX: number; startY: number; offsetX: number; offsetY: number; moved: boolean } | null>(null)
  const panMovedRef = useRef(false)
  const lastFitKeyRef = useRef('')

  const layout = useMemo(() => buildLayout(schematicDocument, relayoutSignal), [relayoutSignal, schematicDocument])

  useEffect(() => {
    if (width <= 0 || height <= 0 || layout.bounds === null) {
      return
    }
    const fitKey = `${schematicDocument.document_id}:${schematicDocument.revision}:${fitSignal}`
    if (lastFitKeyRef.current === fitKey) {
      return
    }
    lastFitKeyRef.current = fitKey
    setViewState(fitToBounds(layout.bounds, width, height))
  }, [fitSignal, height, layout.bounds, schematicDocument.document_id, schematicDocument.revision, width])

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
      setViewState({
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
  }, [panning, viewState.scale])

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
      onSelectComponent(null)
    }
  }

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (width <= 0 || height <= 0) {
      return
    }
    event.preventDefault()
    const nextScale = clamp(viewState.scale * (event.deltaY < 0 ? 1.12 : 1 / 1.12), MIN_SCALE, MAX_SCALE)
    if (nextScale === viewState.scale) {
      return
    }
    const rect = event.currentTarget.getBoundingClientRect()
    const worldPoint = makeRequestTargetWorldPoint(event.clientX, event.clientY, rect, viewState)
    setViewState({
      scale: nextScale,
      offsetX: event.clientX - rect.left - worldPoint.x * nextScale,
      offsetY: event.clientY - rect.top - worldPoint.y * nextScale,
    })
  }

  const hasSourceFile = Boolean(schematicDocument.file_path)
  const hasSchematic = schematicDocument.has_schematic && layout.components.length > 0
  const svgWidth = Math.max(width, 320)
  const svgHeight = Math.max(height, 240)

  return (
    <div className="schematic-canvas">
      <div
        ref={ref}
        className={`schematic-canvas__viewport${panning ? ' schematic-canvas__viewport--dragging' : ''}`}
        onPointerDown={handleViewportPointerDown}
        onClick={handleViewportClick}
        onWheel={handleWheel}
      >
        {hasSourceFile && hasSchematic ? (
          <svg className="schematic-canvas__svg" width={svgWidth} height={svgHeight} viewBox={`0 0 ${svgWidth} ${svgHeight}`}>
            <defs>
              <pattern id="schematic-grid" width="28" height="28" patternUnits="userSpaceOnUse">
                <path d="M 28 0 L 0 0 0 28" fill="none" stroke="rgba(148, 163, 184, 0.18)" strokeWidth="1" />
              </pattern>
            </defs>
            <rect x={0} y={0} width={svgWidth} height={svgHeight} fill="url(#schematic-grid)" />
            <g transform={`translate(${viewState.offsetX} ${viewState.offsetY}) scale(${viewState.scale})`}>
              {layout.nets.map((net) => (
                <g className="schematic-canvas__net" key={net.net.id}>
                  {net.segments.map((segment) => (
                    <polyline
                      key={segment.key}
                      points={segment.points}
                      fill="none"
                      stroke="#94a3b8"
                      strokeWidth={2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  ))}
                  {net.hub ? <circle cx={net.hub.x} cy={net.hub.y} r={4.4} fill="#64748b" /> : null}
                  <g transform={`translate(${net.labelX} ${net.labelY})`}>
                    <rect className="schematic-canvas__net-label-backdrop" x={-4} y={-12} rx={8} width={Math.max(36, net.label.length * 7 + 12)} height={18} />
                    <text className="schematic-canvas__net-label" x={2} y={1} dominantBaseline="middle">
                      {net.label}
                    </text>
                  </g>
                </g>
              ))}
              {layout.components.map((item) => {
                const selected = item.component.id === selectedComponentId
                const hovered = item.component.id === hoveredComponentId
                const readonly = isSchematicComponentReadonly(item.component)
                const appearance = resolveAppearance(selected, hovered, readonly)
                const symbolDefinition = getSchematicSymbolDefinition(item.component.symbol_kind)
                const valueLabel = item.component.display_value || item.component.display_name
                return (
                  <g
                    key={item.component.id}
                    transform={`translate(${item.x} ${item.y})`}
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
                    aria-label={`选择器件 ${item.component.instance_name || item.component.display_name || item.component.id}`}
                  >
                    {symbolDefinition.render({
                      component: item.component,
                      width: item.definitionWidth,
                      height: item.definitionHeight,
                      appearance,
                    })}
                    {item.pins.map((pin) => (
                      <g key={`${item.component.id}-${pin.pin.name}`}>
                        <circle cx={pin.anchor.x} cy={pin.anchor.y} r={4.4} fill={appearance.pinFill} />
                        {renderPinLabel(pin, appearance)}
                      </g>
                    ))}
                    <text x={item.definitionWidth / 2} y={-12} textAnchor="middle" className="schematic-canvas__instance-label" fill={appearance.text}>
                      {item.component.instance_name || item.component.display_name || item.component.id}
                    </text>
                    {valueLabel ? (
                      <text x={item.definitionWidth / 2} y={item.definitionHeight + 18} textAnchor="middle" className="schematic-canvas__value-label" fill={appearance.accent}>
                        {valueLabel}
                      </text>
                    ) : null}
                  </g>
                )
              })}
            </g>
          </svg>
        ) : (
          <div className="schematic-canvas__empty-state">
            <div className={`surface-state-card ${hasSourceFile ? 'surface-state-card--warning' : 'surface-state-card--empty'}`}>
              <div className="card-title">{hasSourceFile ? '当前文档没有可渲染电路图' : '暂无可用电路文件'}</div>
              <div className="muted-text">{hasSourceFile ? schematicDocument.file_name || schematicDocument.title || '当前 schematic_document 未提供可绘制元件。' : '当前结果还没有可供电路页消费的源文件路径。'}</div>
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
        {hasSourceFile && hasSchematic && schematicDocument.parse_errors.length > 0 ? (
          <div className="schematic-canvas__floating-banner">
            <div className="surface-state-card surface-state-card--warning">
              <div className="card-title">解析提示</div>
              {schematicDocument.parse_errors.slice(0, 2).map((item, index) => (
                <div className="muted-text" key={`${item.source_file}-${item.line_index}-${index}`}>
                  {item.message}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
