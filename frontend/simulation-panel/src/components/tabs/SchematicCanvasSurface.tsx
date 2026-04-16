import { useEffect, useRef, useState } from 'react'

import { useElementSize } from '../../hooks/useElementSize'
import type { SchematicDocumentState } from '../../types/state'
import { getSchematicSymbolDefinition, isSchematicComponentReadonly, type SchematicSymbolAppearance } from './symbolRegistry'
import { SCHEMATIC_NET_LABEL_HEIGHT, getSchematicNetLabelWidth, makeViewTargetWorldPoint, type SchematicCanvasViewState, type SchematicLayoutResult } from './schematicLayout'

interface SchematicCanvasProps {
  schematicDocument: SchematicDocumentState
  layoutResult: SchematicLayoutResult | null
  layoutPending: boolean
  layoutError: string
  selectedComponentId: string | null
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

function getNetLabelBackdropX(textAnchor: 'start' | 'middle' | 'end', width: number): number {
  if (textAnchor === 'middle') {
    return -width / 2
  }
  if (textAnchor === 'end') {
    return -width + 4
  }
  return -4
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
  viewState,
  onViewStateChange,
  onViewportSizeChange,
  onSelectComponent,
}: SchematicCanvasProps) {
  const { ref, width, height } = useElementSize<HTMLDivElement>()
  const [hoveredComponentId, setHoveredComponentId] = useState('')
  const [panning, setPanning] = useState(false)
  const dragStateRef = useRef<{ startX: number; startY: number; offsetX: number; offsetY: number; moved: boolean } | null>(null)
  const panMovedRef = useRef(false)

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
    const worldPoint = makeViewTargetWorldPoint(event.clientX, event.clientY, rect, viewState)
    onViewStateChange({
      scale: nextScale,
      offsetX: event.clientX - rect.left - worldPoint.x * nextScale,
      offsetY: event.clientY - rect.top - worldPoint.y * nextScale,
    })
  }

  const hasSourceFile = Boolean(schematicDocument.file_path)
  const layoutComponents = layoutResult?.components ?? []
  const layoutGroups = layoutResult?.groups ?? []
  const layoutNets = layoutResult?.nets ?? []
  const hasRenderableLayout = hasSourceFile && schematicDocument.has_schematic && layoutComponents.length > 0
  const svgWidth = Math.max(width, 320)
  const svgHeight = Math.max(height, 240)

  const emptyStateTitle = !hasSourceFile
    ? '暂无可用电路文件'
    : layoutPending && schematicDocument.has_schematic
      ? '正在计算电路布局'
      : layoutError
        ? '电路布局失败'
        : '当前文档没有可渲染电路图'

  const emptyStateDescription = !hasSourceFile
    ? '当前结果还没有可供电路页消费的源文件路径。'
    : layoutPending && schematicDocument.has_schematic
      ? '正在基于最新 schematic_document 计算 ELK 自动布局。'
      : layoutError || schematicDocument.file_name || schematicDocument.title || '当前 schematic_document 未提供可绘制元件。'

  return (
    <div className="schematic-canvas">
      <div
        ref={ref}
        className={`schematic-canvas__viewport${panning ? ' schematic-canvas__viewport--dragging' : ''}`}
        onPointerDown={handleViewportPointerDown}
        onClick={handleViewportClick}
        onWheel={handleWheel}
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
                      x={group.x}
                      y={group.y}
                      width={group.width}
                      height={group.height}
                      rx={18}
                      fill={tone.fill}
                      stroke={tone.stroke}
                      strokeWidth={1.5}
                      strokeDasharray="7 5"
                    />
                    <text
                      x={group.x + 16}
                      y={group.y + 18}
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
                    {net.label ? (
                      <g transform={`translate(${net.label.x} ${net.label.y})`}>
                        <rect
                          className="schematic-canvas__net-label-backdrop"
                          x={getNetLabelBackdropX(net.label.textAnchor, labelWidth)}
                          y={-SCHEMATIC_NET_LABEL_HEIGHT / 2}
                          rx={8}
                          width={labelWidth}
                          height={SCHEMATIC_NET_LABEL_HEIGHT}
                        />
                        <text
                          className="schematic-canvas__net-label"
                          x={0}
                          y={1}
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
                    <g transform={`translate(${item.symbolX} ${item.symbolY})`}>
                      {symbolDefinition.render({
                        component: item.component,
                        width: item.symbolWidth,
                        height: item.symbolHeight,
                        appearance,
                      })}
                    </g>
                    {item.pins.map((pin) => (
                      <g key={`${item.component.id}-${pin.pin.name}`}>
                        <circle cx={pin.x - item.x} cy={pin.y - item.y} r={4.4} fill={appearance.pinFill} />
                      </g>
                    ))}
                    {item.nameLabel ? (
                      <text
                        x={item.nameLabel.x - item.x}
                        y={item.nameLabel.y - item.y}
                        textAnchor={item.nameLabel.textAnchor}
                        className="schematic-canvas__instance-label"
                        fill={appearance.text}
                      >
                        {item.nameLabel.text}
                      </text>
                    ) : null}
                    {item.valueLabel ? (
                      <text
                        x={item.valueLabel.x - item.x}
                        y={item.valueLabel.y - item.y}
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
                  <div className="card-title">布局计算中</div>
                  <div className="muted-text">只会采纳当前最新 `document_id + revision` 的 ELK 结果。</div>
                </div>
              ) : null}
              {layoutError ? (
                <div className="surface-state-card surface-state-card--warning">
                  <div className="card-title">布局失败</div>
                  <div className="muted-text">{layoutError}</div>
                </div>
              ) : null}
              {hasSourceFile && hasRenderableLayout && schematicDocument.parse_errors.length > 0 ? (
                <div className="surface-state-card surface-state-card--warning">
                  <div className="card-title">解析提示</div>
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
      </div>
    </div>
  )
}
