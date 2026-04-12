import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { useElementSize } from '../../hooks/useElementSize'
import { formatMeasurementNumber } from './chartValueFormatting'
import { buildSeriesSvgChartModel, type SeriesSvgChartDatum } from './seriesSvgChartModel'

type MeasurementCursorId = 'a' | 'b'

interface SeriesSvgChartMeasurementCursors {
  cursorAVisible: boolean
  cursorBVisible: boolean
  cursorAX: number | null
  cursorBX: number | null
  onCursorMove?: (cursorId: MeasurementCursorId, position: number) => void
}

interface SeriesSvgChartProps {
  title?: string
  headerActions?: ReactNode
  floatingPanel?: ReactNode
  measurementCursors?: SeriesSvgChartMeasurementCursors
  series: SeriesSvgChartDatum[]
  xLabel: string
  yLabel: string
  secondaryYLabel?: string
  logX?: boolean
  logY?: boolean
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

function toDisplayXValue(value: number, logX: boolean): number {
  return logX ? 10 ** value : value
}

export function SeriesSvgChart({
  title,
  headerActions,
  floatingPanel,
  measurementCursors,
  series,
  xLabel,
  yLabel,
  secondaryYLabel,
  logX = false,
  logY = false,
  emptyMessage,
}: SeriesSvgChartProps) {
  const { ref: chartFrameRef, width: chartWidth, height: chartHeight } = useElementSize<HTMLDivElement>()
  const svgElementRef = useRef<SVGSVGElement | null>(null)
  const cursorMoveHandlerRef = useRef<SeriesSvgChartMeasurementCursors['onCursorMove']>(measurementCursors?.onCursorMove)
  const activeDragCursorRef = useRef<MeasurementCursorId | null>(null)
  const [activeDragCursor, setActiveDragCursor] = useState<MeasurementCursorId | null>(null)
  const [dragDisplayX, setDragDisplayX] = useState<number | null>(null)
  const chartModel = useMemo(() => buildSeriesSvgChartModel({
    series,
    xLabel,
    yLabel,
    secondaryYLabel,
    logX,
    logY,
    width: chartWidth,
    height: chartHeight,
  }), [chartHeight, chartWidth, logX, logY, secondaryYLabel, series, xLabel, yLabel])

  const normalizedTitle = title?.trim() ?? ''
  const hasHeader = normalizedTitle.length > 0 || headerActions !== undefined

  useEffect(() => {
    cursorMoveHandlerRef.current = measurementCursors?.onCursorMove
  }, [measurementCursors?.onCursorMove])

  useEffect(() => {
    activeDragCursorRef.current = activeDragCursor
  }, [activeDragCursor])

  if (!chartModel) {
    return (
      <div className="svg-chart-shell">
        {hasHeader ? (
          <div className="svg-chart-header">
            {normalizedTitle ? <div className="svg-chart-title">{normalizedTitle}</div> : <div className="svg-chart-header__spacer" />}
            {headerActions ? <div className="svg-chart-header__actions">{headerActions}</div> : null}
          </div>
        ) : null}
        <div className="svg-chart-empty muted-text">{emptyMessage}</div>
      </div>
    )
  }

  const {
    viewport,
    xTicks,
    leftTicks,
    rightTicks,
    renderedSeries,
    hasRightAxis,
    xDomain,
    leftAxisLabel,
    rightAxisLabel,
  } = chartModel
  const { plotLeft, plotRight, plotTop, plotBottom, svgHeight, svgWidth } = viewport
  const yAxisCenter = (plotTop + plotBottom) / 2
  const xAxisCenter = (plotLeft + plotRight) / 2
  const xAxisTitleY = Math.min(svgHeight - 10, plotBottom + X_AXIS_TITLE_OFFSET)
  const leftAxisTitleX = SIDE_AXIS_TITLE_OFFSET
  const rightAxisTitleX = svgWidth - SIDE_AXIS_TITLE_OFFSET

  const resolveDisplayXFromClientX = (clientX: number): number | null => {
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

  const projectMeasurementCursorX = (displayX: number | null): number | null => {
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

  const startMeasurementCursorDrag = (cursorId: MeasurementCursorId, clientX: number) => {
    const nextDisplayX = resolveDisplayXFromClientX(clientX)
    if (nextDisplayX === null) {
      return
    }
    setActiveDragCursor(cursorId)
    setDragDisplayX(nextDisplayX)
    cursorMoveHandlerRef.current?.(cursorId, nextDisplayX)
  }

  useEffect(() => {
    if (activeDragCursor === null) {
      setDragDisplayX(null)
      return undefined
    }

    const handlePointerMove = (event: PointerEvent) => {
      const draggingCursor = activeDragCursorRef.current
      if (draggingCursor === null) {
        return
      }
      const nextDisplayX = resolveDisplayXFromClientX(event.clientX)
      if (nextDisplayX === null) {
        return
      }
      setDragDisplayX(nextDisplayX)
      cursorMoveHandlerRef.current?.(draggingCursor, nextDisplayX)
    }

    const handlePointerUp = () => {
      setActiveDragCursor(null)
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
  }, [activeDragCursor, logX, plotLeft, plotRight, svgWidth, xDomain.max, xDomain.min])

  const measurementCursorItems = [
    {
      id: 'a' as const,
      label: 'A',
      visible: measurementCursors?.cursorAVisible ?? false,
      displayX: activeDragCursor === 'a' && dragDisplayX !== null ? dragDisplayX : (measurementCursors?.cursorAX ?? null),
    },
    {
      id: 'b' as const,
      label: 'B',
      visible: measurementCursors?.cursorBVisible ?? false,
      displayX: activeDragCursor === 'b' && dragDisplayX !== null ? dragDisplayX : (measurementCursors?.cursorBX ?? null),
    },
  ].map((cursor) => ({
    ...cursor,
    plotX: cursor.visible ? projectMeasurementCursorX(cursor.displayX) : null,
    badgeText: `${cursor.label} ${formatMeasurementNumber(cursor.displayX)}`,
  })).filter((cursor) => cursor.visible && cursor.plotX !== null)

  return (
    <div className="svg-chart-shell">
      {hasHeader ? (
        <div className="svg-chart-header">
          {normalizedTitle ? <div className="svg-chart-title">{normalizedTitle}</div> : <div className="svg-chart-header__spacer" />}
          {headerActions ? <div className="svg-chart-header__actions">{headerActions}</div> : null}
        </div>
      ) : null}
      <div ref={chartFrameRef} className="svg-chart-frame">
        <svg ref={svgElementRef} viewBox={`0 0 ${svgWidth} ${svgHeight}`} className="svg-chart" aria-label="Simulation series chart">
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
                  className={`svg-chart__measurement-cursor svg-chart__measurement-cursor--${cursor.id}`}
                  onPointerDown={cursorMoveHandlerRef.current ? (event) => {
                    event.preventDefault()
                    startMeasurementCursorDrag(cursor.id, event.clientX)
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
        </svg>
        {floatingPanel ? <div className="svg-chart__floating-panel-shell">{floatingPanel}</div> : null}
      </div>
    </div>
  )
}
