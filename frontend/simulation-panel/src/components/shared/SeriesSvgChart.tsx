import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'

import { useElementSize } from '../../hooks/useElementSize'
import { DraggableFloatingPanel } from './DraggableFloatingPanel'
import { formatMeasurementNumber } from './chartValueFormatting'
import { buildSeriesSvgChartModel, type SeriesSvgChartDatum, type SeriesSvgChartViewWindow } from './seriesSvgChartModel'

type MeasurementCursorId = 'a' | 'b'

type ActiveChartDragHandle =
  | { kind: 'measurement-cursor'; cursorId: MeasurementCursorId }
  | { kind: 'measurement-point' }

interface ActiveViewportSelection {
  anchorSvgX: number
  anchorSvgY: number
  currentSvgX: number
  currentSvgY: number
}

export interface SeriesSvgChartViewportSelection {
  active: true
  xMin: number
  xMax: number
  leftYMin: number
  leftYMax: number
  rightYMin?: number | null
  rightYMax?: number | null
}

interface SeriesSvgChartMeasurementCursors {
  cursorAVisible: boolean
  cursorBVisible: boolean
  cursorAX: number | null
  cursorBX: number | null
  onCursorMove?: (cursorId: MeasurementCursorId, position: number) => void
}

interface SeriesSvgChartMeasurementPoint {
  visible: boolean
  displayX: number | null
  valueY: number | null
  axisKey?: string
  onMove?: (position: number) => void
}

export interface SeriesSvgChartFloatingPanel {
  id: string
  content: ReactNode
  defaultTop?: number
  defaultRight?: number
}

interface SeriesSvgChartProps {
  title?: string
  headerActions?: ReactNode
  floatingPanels?: SeriesSvgChartFloatingPanel[]
  measurementCursors?: SeriesSvgChartMeasurementCursors
  measurementPoint?: SeriesSvgChartMeasurementPoint
  series: SeriesSvgChartDatum[]
  xLabel: string
  yLabel: string
  secondaryYLabel?: string
  logX?: boolean
  logY?: boolean
  rightLogY?: boolean
  viewWindow?: SeriesSvgChartViewWindow | null
  onViewportChange?: (viewWindow: SeriesSvgChartViewportSelection) => void
  emptyMessage: string
}

const AXIS_TICK_LENGTH = 5
const LEFT_TICK_LABEL_OFFSET = 9
const RIGHT_TICK_LABEL_OFFSET = 9
const X_TICK_LABEL_OFFSET = 19
const X_AXIS_TITLE_OFFSET = 34
const SIDE_AXIS_TITLE_OFFSET = 32
const MEASUREMENT_CURSOR_LABEL_Y_OFFSET = 14
const MEASUREMENT_CURSOR_LABEL_MIN_WIDTH = 24
const MEASUREMENT_CURSOR_LABEL_HEIGHT = 16
const MEASUREMENT_CURSOR_LABEL_HORIZONTAL_PADDING = 12
const VIEWPORT_SELECTION_MIN_SIZE = 8

function toAxisXValue(value: number, logX: boolean): number | null {
  if (!Number.isFinite(value)) {
    return null
  }
  if (!logX) {
    return value
  }
  if (value <= 0) {
    return null
  }
  const transformed = Math.log10(value)
  return Number.isFinite(transformed) ? transformed : null
}

function toAxisYValue(value: number, axisKey: string, logY: boolean): number | null {
  if (!Number.isFinite(value)) {
    return null
  }
  if (!logY) {
    return value
  }
  if (value <= 0) {
    return null
  }
  const transformed = Math.log10(value)
  return Number.isFinite(transformed) ? transformed : null
}

function toDisplayXValue(value: number, logX: boolean): number {
  return logX ? 10 ** value : value
}

function toDisplayYValue(value: number, axisKey: string, logY: boolean): number {
  if (!logY) {
    return value
  }
  return 10 ** value
}

function isAxisLogEnabled(axisKey: string, leftLogY: boolean, rightLogY: boolean): boolean {
  return axisKey === 'right' ? rightLogY : leftLogY
}

export function SeriesSvgChart({
  title,
  headerActions,
  floatingPanels = [],
  measurementCursors,
  measurementPoint,
  series,
  xLabel,
  yLabel,
  secondaryYLabel,
  logX = false,
  logY = false,
  rightLogY = false,
  viewWindow,
  onViewportChange,
  emptyMessage,
}: SeriesSvgChartProps) {
  const { ref: chartFrameRef, width: chartWidth, height: chartHeight } = useElementSize<HTMLDivElement>()
  const svgElementRef = useRef<SVGSVGElement | null>(null)
  const cursorMoveHandlerRef = useRef<SeriesSvgChartMeasurementCursors['onCursorMove']>(measurementCursors?.onCursorMove)
  const measurementPointMoveHandlerRef = useRef<SeriesSvgChartMeasurementPoint['onMove']>(measurementPoint?.onMove)
  const viewportChangeHandlerRef = useRef<SeriesSvgChartProps['onViewportChange']>(onViewportChange)
  const activeDragHandleRef = useRef<ActiveChartDragHandle | null>(null)
  const activeViewportSelectionRef = useRef<ActiveViewportSelection | null>(null)
  const [activeDragHandle, setActiveDragHandle] = useState<ActiveChartDragHandle | null>(null)
  const [dragDisplayX, setDragDisplayX] = useState<number | null>(null)
  const [activeViewportSelection, setActiveViewportSelection] = useState<ActiveViewportSelection | null>(null)
  const plotClipPathId = useId().replace(/[:]/g, '')
  const chartModel = useMemo(() => buildSeriesSvgChartModel({
    series,
    xLabel,
    yLabel,
    secondaryYLabel,
    logX,
    logY,
    rightLogY,
    width: chartWidth,
    height: chartHeight,
    viewWindow,
  }), [chartHeight, chartWidth, logX, logY, rightLogY, secondaryYLabel, series, viewWindow, xLabel, yLabel])

  const normalizedTitle = title?.trim() ?? ''
  const hasHeader = normalizedTitle.length > 0 || headerActions !== undefined
  const viewport = chartModel?.viewport ?? null
  const plotLeft = viewport?.plotLeft ?? 0
  const plotRight = viewport?.plotRight ?? 0
  const plotTop = viewport?.plotTop ?? 0
  const plotBottom = viewport?.plotBottom ?? 0
  const svgHeight = viewport?.svgHeight ?? 0
  const svgWidth = viewport?.svgWidth ?? 0
  const xDomain = chartModel?.xDomain ?? null
  const leftDomain = chartModel?.leftDomain ?? null
  const rightDomain = chartModel?.rightDomain ?? null
  const hasRightAxis = chartModel?.hasRightAxis ?? false
  const xTicks = chartModel?.xTicks ?? []
  const leftTicks = chartModel?.leftTicks ?? []
  const rightTicks = chartModel?.rightTicks ?? []
  const renderedSeries = chartModel?.renderedSeries ?? []
  const leftAxisLabel = chartModel?.leftAxisLabel ?? yLabel
  const rightAxisLabel = chartModel?.rightAxisLabel ?? (secondaryYLabel ?? '')
  const yAxisCenter = (plotTop + plotBottom) / 2
  const xAxisCenter = (plotLeft + plotRight) / 2
  const xAxisTitleY = Math.min(svgHeight - 10, plotBottom + X_AXIS_TITLE_OFFSET)
  const leftAxisTitleX = SIDE_AXIS_TITLE_OFFSET
  const rightAxisTitleX = svgWidth - SIDE_AXIS_TITLE_OFFSET

  useEffect(() => {
    cursorMoveHandlerRef.current = measurementCursors?.onCursorMove
  }, [measurementCursors?.onCursorMove])

  useEffect(() => {
    measurementPointMoveHandlerRef.current = measurementPoint?.onMove
  }, [measurementPoint?.onMove])

  useEffect(() => {
    viewportChangeHandlerRef.current = onViewportChange
  }, [onViewportChange])

  useEffect(() => {
    activeDragHandleRef.current = activeDragHandle
  }, [activeDragHandle])

  useEffect(() => {
    activeViewportSelectionRef.current = activeViewportSelection
  }, [activeViewportSelection])

  const resolveDisplayXFromClientX = (clientX: number): number | null => {
    if (xDomain === null) {
      return null
    }
    const svgElement = svgElementRef.current
    if (svgElement === null) {
      return null
    }
    const rect = svgElement.getBoundingClientRect()
    if (rect.width <= 0) {
      return null
    }
    const svgX = ((clientX - rect.left) / rect.width) * svgWidth
    const clampedSvgX = Math.min(Math.max(svgX, plotLeft), plotRight)
    const plotWidth = Math.max(plotRight - plotLeft, 1e-12)
    const axisX = xDomain.min + ((clampedSvgX - plotLeft) / plotWidth) * (xDomain.max - xDomain.min)
    return toDisplayXValue(axisX, logX)
  }

  const projectXValue = (displayX: number | null): number | null => {
    if (xDomain === null) {
      return null
    }
    if (displayX === null) {
      return null
    }
    const axisX = toAxisXValue(displayX, logX)
    if (axisX === null) {
      return null
    }
    const clampedAxisX = Math.min(Math.max(axisX, xDomain.min), xDomain.max)
    const domainSpan = Math.max(xDomain.max - xDomain.min, 1e-12)
    return plotLeft + ((clampedAxisX - xDomain.min) / domainSpan) * (plotRight - plotLeft)
  }

  const projectYValue = (valueY: number | null, axisKey: string): number | null => {
    if (valueY === null) {
      return null
    }
    const axisValue = toAxisYValue(valueY, axisKey, isAxisLogEnabled(axisKey, logY, rightLogY))
    if (axisValue === null) {
      return null
    }
    const domain = axisKey === 'right' && rightDomain !== null ? rightDomain : leftDomain
    if (domain === null) {
      return null
    }
    const clampedAxisY = Math.min(Math.max(axisValue, domain.min), domain.max)
    const domainSpan = Math.max(domain.max - domain.min, 1e-12)
    return plotBottom - ((clampedAxisY - domain.min) / domainSpan) * (plotBottom - plotTop)
  }

  const resolvePlotSelectionPointFromSvg = (svgX: number, svgY: number) => {
    if (xDomain === null || leftDomain === null) {
      return null
    }
    const clampedSvgX = Math.min(Math.max(svgX, plotLeft), plotRight)
    const clampedSvgY = Math.min(Math.max(svgY, plotTop), plotBottom)
    const plotWidth = Math.max(plotRight - plotLeft, 1e-12)
    const plotHeight = Math.max(plotBottom - plotTop, 1e-12)
    const xAxisValue = xDomain.min + ((clampedSvgX - plotLeft) / plotWidth) * (xDomain.max - xDomain.min)
    const leftAxisValue = leftDomain.min + ((plotBottom - clampedSvgY) / plotHeight) * (leftDomain.max - leftDomain.min)
    const rightAxisValue = rightDomain === null
      ? null
      : rightDomain.min + ((plotBottom - clampedSvgY) / plotHeight) * (rightDomain.max - rightDomain.min)
    return {
      svgX: clampedSvgX,
      svgY: clampedSvgY,
      displayX: toDisplayXValue(xAxisValue, logX),
      leftDisplayY: toDisplayYValue(leftAxisValue, 'left', logY),
      rightDisplayY: rightAxisValue === null ? null : toDisplayYValue(rightAxisValue, 'right', rightLogY),
    }
  }

  const resolvePlotSelectionPointFromClient = (clientX: number, clientY: number) => {
    const svgElement = svgElementRef.current
    if (svgElement === null) {
      return null
    }
    const rect = svgElement.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) {
      return null
    }
    const svgX = ((clientX - rect.left) / rect.width) * svgWidth
    const svgY = ((clientY - rect.top) / rect.height) * svgHeight
    return resolvePlotSelectionPointFromSvg(svgX, svgY)
  }

  const startDrag = (nextHandle: ActiveChartDragHandle, clientX: number) => {
    const nextDisplayX = resolveDisplayXFromClientX(clientX)
    if (nextDisplayX === null) {
      return
    }
    setActiveDragHandle(nextHandle)
    setDragDisplayX(nextDisplayX)
    if (nextHandle.kind === 'measurement-cursor') {
      cursorMoveHandlerRef.current?.(nextHandle.cursorId, nextDisplayX)
      return
    }
    measurementPointMoveHandlerRef.current?.(nextDisplayX)
  }

  const startViewportSelection = (clientX: number, clientY: number) => {
    if (viewportChangeHandlerRef.current === undefined || activeDragHandleRef.current !== null) {
      return
    }
    const startPoint = resolvePlotSelectionPointFromClient(clientX, clientY)
    if (startPoint === null) {
      return
    }
    setActiveViewportSelection({
      anchorSvgX: startPoint.svgX,
      anchorSvgY: startPoint.svgY,
      currentSvgX: startPoint.svgX,
      currentSvgY: startPoint.svgY,
    })
  }

  useEffect(() => {
    if (chartModel === null || activeDragHandle === null) {
      setDragDisplayX(null)
      return undefined
    }

    const handlePointerMove = (event: PointerEvent) => {
      const draggingHandle = activeDragHandleRef.current
      if (draggingHandle === null) {
        return
      }
      const nextDisplayX = resolveDisplayXFromClientX(event.clientX)
      if (nextDisplayX === null) {
        return
      }
      setDragDisplayX(nextDisplayX)
      if (draggingHandle.kind === 'measurement-cursor') {
        cursorMoveHandlerRef.current?.(draggingHandle.cursorId, nextDisplayX)
        return
      }
      measurementPointMoveHandlerRef.current?.(nextDisplayX)
    }

    const handlePointerUp = () => {
      setActiveDragHandle(null)
      setDragDisplayX(null)
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerUp)

    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [activeDragHandle, chartModel, logX, plotLeft, plotRight, svgWidth, xDomain?.max, xDomain?.min])

  useEffect(() => {
    if (chartModel === null || activeViewportSelection === null) {
      return undefined
    }

    const handlePointerMove = (event: PointerEvent) => {
      const currentSelection = activeViewportSelectionRef.current
      if (currentSelection === null) {
        return
      }
      const nextPoint = resolvePlotSelectionPointFromClient(event.clientX, event.clientY)
      if (nextPoint === null) {
        return
      }
      setActiveViewportSelection({
        ...currentSelection,
        currentSvgX: nextPoint.svgX,
        currentSvgY: nextPoint.svgY,
      })
    }

    const handlePointerUp = () => {
      const currentSelection = activeViewportSelectionRef.current
      setActiveViewportSelection(null)
      if (currentSelection === null) {
        return
      }
      const selectionWidth = Math.abs(currentSelection.currentSvgX - currentSelection.anchorSvgX)
      const selectionHeight = Math.abs(currentSelection.currentSvgY - currentSelection.anchorSvgY)
      if (selectionWidth < VIEWPORT_SELECTION_MIN_SIZE || selectionHeight < VIEWPORT_SELECTION_MIN_SIZE) {
        return
      }
      const topLeft = resolvePlotSelectionPointFromSvg(
        Math.min(currentSelection.anchorSvgX, currentSelection.currentSvgX),
        Math.min(currentSelection.anchorSvgY, currentSelection.currentSvgY),
      )
      const bottomRight = resolvePlotSelectionPointFromSvg(
        Math.max(currentSelection.anchorSvgX, currentSelection.currentSvgX),
        Math.max(currentSelection.anchorSvgY, currentSelection.currentSvgY),
      )
      if (topLeft === null || bottomRight === null) {
        return
      }
      viewportChangeHandlerRef.current?.({
        active: true,
        xMin: Math.min(topLeft.displayX, bottomRight.displayX),
        xMax: Math.max(topLeft.displayX, bottomRight.displayX),
        leftYMin: Math.min(topLeft.leftDisplayY, bottomRight.leftDisplayY),
        leftYMax: Math.max(topLeft.leftDisplayY, bottomRight.leftDisplayY),
        rightYMin: topLeft.rightDisplayY === null || bottomRight.rightDisplayY === null
          ? null
          : Math.min(topLeft.rightDisplayY, bottomRight.rightDisplayY),
        rightYMax: topLeft.rightDisplayY === null || bottomRight.rightDisplayY === null
          ? null
          : Math.max(topLeft.rightDisplayY, bottomRight.rightDisplayY),
      })
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerUp)

    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [activeViewportSelection, chartModel, leftDomain?.max, leftDomain?.min, logX, logY, plotBottom, plotLeft, plotRight, plotTop, rightDomain?.max, rightDomain?.min, rightLogY, svgHeight, svgWidth, xDomain?.max, xDomain?.min])

  const measurementCursorItems = [
    {
      id: 'a' as const,
      label: 'A',
      visible: measurementCursors?.cursorAVisible ?? false,
      displayX: activeDragHandle?.kind === 'measurement-cursor' && activeDragHandle.cursorId === 'a' && dragDisplayX !== null
        ? dragDisplayX
        : (measurementCursors?.cursorAX ?? null),
    },
    {
      id: 'b' as const,
      label: 'B',
      visible: measurementCursors?.cursorBVisible ?? false,
      displayX: activeDragHandle?.kind === 'measurement-cursor' && activeDragHandle.cursorId === 'b' && dragDisplayX !== null
        ? dragDisplayX
        : (measurementCursors?.cursorBX ?? null),
    },
  ].map((cursor) => ({
    ...cursor,
    plotX: cursor.visible ? projectXValue(cursor.displayX) : null,
    badgeText: `${cursor.label} ${formatMeasurementNumber(cursor.displayX)}`,
  })).filter((cursor) => cursor.visible && cursor.plotX !== null)

  const measurementPointDisplayX = activeDragHandle?.kind === 'measurement-point' && dragDisplayX !== null
    ? dragDisplayX
    : (measurementPoint?.displayX ?? null)
  const measurementPointItem = measurementPoint?.visible
    ? {
      plotX: projectXValue(measurementPointDisplayX),
      plotY: projectYValue(measurementPoint.valueY, measurementPoint.axisKey ?? 'left'),
    }
    : null
  const viewportSelectionRect = activeViewportSelection === null
    ? null
    : {
      x: Math.min(activeViewportSelection.anchorSvgX, activeViewportSelection.currentSvgX),
      y: Math.min(activeViewportSelection.anchorSvgY, activeViewportSelection.currentSvgY),
      width: Math.abs(activeViewportSelection.currentSvgX - activeViewportSelection.anchorSvgX),
      height: Math.abs(activeViewportSelection.currentSvgY - activeViewportSelection.anchorSvgY),
    }

  return (
    <div className="svg-chart-shell">
      {hasHeader ? (
        <div className="svg-chart-header">
          {normalizedTitle ? <div className="svg-chart-title">{normalizedTitle}</div> : <div className="svg-chart-header__spacer" />}
          {headerActions ? <div className="svg-chart-header__actions">{headerActions}</div> : null}
        </div>
      ) : null}
      {chartModel === null ? (
        <div className="svg-chart-empty muted-text">{emptyMessage}</div>
      ) : (
        <div ref={chartFrameRef} className="svg-chart-frame">
          <svg ref={svgElementRef} viewBox={`0 0 ${svgWidth} ${svgHeight}`} className="svg-chart" aria-label="Simulation series chart">
            <defs>
              <clipPath id={plotClipPathId}>
                <rect x={plotLeft} y={plotTop} width={plotRight - plotLeft} height={plotBottom - plotTop} />
              </clipPath>
            </defs>
            <rect x={plotLeft} y={plotTop} width={plotRight - plotLeft} height={plotBottom - plotTop} className="svg-chart__plot-bg" />
            {leftTicks.map((tick) => (
              <line key={`grid-y-${tick.value}`} x1={plotLeft} x2={plotRight} y1={tick.position} y2={tick.position} className="svg-chart__grid" />
            ))}
            {xTicks.map((tick) => (
              <line key={`grid-x-${tick.value}`} x1={tick.position} x2={tick.position} y1={plotTop} y2={plotBottom} className="svg-chart__grid" />
            ))}
            <line x1={plotLeft} x2={plotRight} y1={plotBottom} y2={plotBottom} className="svg-chart__axis" />
            <line x1={plotLeft} x2={plotLeft} y1={plotTop} y2={plotBottom} className="svg-chart__axis" />
            {hasRightAxis ? <line x1={plotRight} x2={plotRight} y1={plotTop} y2={plotBottom} className="svg-chart__axis" /> : null}
            <g clipPath={`url(#${plotClipPathId})`}>
              {renderedSeries.map((item) => (
                <polyline
                  key={item.name}
                  fill="none"
                  stroke={item.color}
                  strokeWidth={item.lineStyle === 'dash' ? '1.7' : '2'}
                  strokeDasharray={item.strokeDasharray}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  points={item.polylinePoints}
                  className="svg-chart__series"
                />
              ))}
            </g>
            <rect
              x={plotLeft}
              y={plotTop}
              width={plotRight - plotLeft}
              height={plotBottom - plotTop}
              className="svg-chart__interaction-hitbox"
              onPointerDown={onViewportChange ? (event) => {
                event.preventDefault()
                startViewportSelection(event.clientX, event.clientY)
              } : undefined}
            />
            {measurementPointItem && measurementPointItem.plotX !== null && measurementPointItem.plotY !== null ? (
              <g
                className="svg-chart__measurement-point"
                onPointerDown={measurementPointMoveHandlerRef.current ? (event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  startDrag({ kind: 'measurement-point' }, event.clientX)
                } : undefined}
              >
                <line x1={measurementPointItem.plotX} x2={measurementPointItem.plotX} y1={plotTop} y2={plotBottom} className="svg-chart__measurement-point-line" />
                <line x1={measurementPointItem.plotX} x2={measurementPointItem.plotX} y1={plotTop} y2={plotBottom} className="svg-chart__measurement-point-hitbox-line" />
                <circle cx={measurementPointItem.plotX} cy={measurementPointItem.plotY} r="10" className="svg-chart__measurement-point-hitbox-marker" />
                <circle cx={measurementPointItem.plotX} cy={measurementPointItem.plotY} r="4.5" className="svg-chart__measurement-point-marker" />
              </g>
            ) : null}
            {measurementCursorItems.map((cursor) => (
              (() => {
                const badgeWidth = Math.max(MEASUREMENT_CURSOR_LABEL_MIN_WIDTH, cursor.badgeText.length * 6.7 + MEASUREMENT_CURSOR_LABEL_HORIZONTAL_PADDING)
                const badgeCenterX = Math.min(
                  Math.max(cursor.plotX ?? 0, plotLeft + badgeWidth / 2 + 2),
                  plotRight - badgeWidth / 2 - 2,
                )
                return (
                  <g
                    key={`measurement-cursor-${cursor.id}`}
                    className="svg-chart__measurement-cursor"
                    onPointerDown={cursorMoveHandlerRef.current ? (event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      startDrag({ kind: 'measurement-cursor', cursorId: cursor.id }, event.clientX)
                    } : undefined}
                  >
                    <line x1={cursor.plotX ?? 0} x2={cursor.plotX ?? 0} y1={plotTop} y2={plotBottom} className="svg-chart__measurement-cursor-line" />
                    <line x1={cursor.plotX ?? 0} x2={cursor.plotX ?? 0} y1={plotTop} y2={plotBottom} className="svg-chart__measurement-cursor-hitbox" />
                    <rect
                      x={badgeCenterX - badgeWidth / 2}
                      y={plotTop + 2}
                      rx={MEASUREMENT_CURSOR_LABEL_HEIGHT / 2}
                      ry={MEASUREMENT_CURSOR_LABEL_HEIGHT / 2}
                      width={badgeWidth}
                      height={MEASUREMENT_CURSOR_LABEL_HEIGHT}
                      className="svg-chart__measurement-cursor-badge"
                    />
                    <text x={badgeCenterX} y={plotTop + MEASUREMENT_CURSOR_LABEL_Y_OFFSET} textAnchor="middle" className="svg-chart__measurement-cursor-label">{cursor.badgeText}</text>
                  </g>
                )
              })()
            ))}
            {leftTicks.map((tick) => (
              <g key={`left-tick-${tick.value}`}>
                <line x1={plotLeft} x2={plotLeft - AXIS_TICK_LENGTH} y1={tick.position} y2={tick.position} className="svg-chart__tick" />
                <text x={plotLeft - LEFT_TICK_LABEL_OFFSET} y={tick.position + 4} textAnchor="end" className="svg-chart__tick-label">{tick.label}</text>
              </g>
            ))}
            {rightTicks.map((tick) => (
              <g key={`right-tick-${tick.value}`}>
                <line x1={plotRight} x2={plotRight + AXIS_TICK_LENGTH} y1={tick.position} y2={tick.position} className="svg-chart__tick" />
                <text x={plotRight + RIGHT_TICK_LABEL_OFFSET} y={tick.position + 4} textAnchor="start" className="svg-chart__tick-label">{tick.label}</text>
              </g>
            ))}
            {xTicks.map((tick) => (
              <g key={`bottom-tick-${tick.value}`}>
                <line x1={tick.position} x2={tick.position} y1={plotBottom} y2={plotBottom + AXIS_TICK_LENGTH} className="svg-chart__tick" />
                <text x={tick.position} y={plotBottom + X_TICK_LABEL_OFFSET} textAnchor="middle" className="svg-chart__tick-label">{tick.label}</text>
              </g>
            ))}
            <text x={xAxisCenter} y={xAxisTitleY} textAnchor="middle" className="svg-chart__axis-title">{chartModel.xLabel}</text>
            <text x={leftAxisTitleX} y={yAxisCenter} textAnchor="middle" transform={`rotate(-90 ${leftAxisTitleX} ${yAxisCenter})`} className="svg-chart__axis-title">{leftAxisLabel}</text>
            {hasRightAxis ? (
              <text x={rightAxisTitleX} y={yAxisCenter} textAnchor="middle" transform={`rotate(90 ${rightAxisTitleX} ${yAxisCenter})`} className="svg-chart__axis-title">{rightAxisLabel}</text>
            ) : null}
            {viewportSelectionRect !== null ? (
              <rect
                x={viewportSelectionRect.x}
                y={viewportSelectionRect.y}
                width={viewportSelectionRect.width}
                height={viewportSelectionRect.height}
                className="svg-chart__viewport-selection"
              />
            ) : null}
          </svg>
          {floatingPanels.map((panel) => (
            <DraggableFloatingPanel
              key={panel.id}
              containerWidth={chartWidth}
              containerHeight={chartHeight}
              defaultTop={panel.defaultTop}
              defaultRight={panel.defaultRight}
            >
              {panel.content}
            </DraggableFloatingPanel>
          ))}
        </div>
      )}
    </div>
  )
}
