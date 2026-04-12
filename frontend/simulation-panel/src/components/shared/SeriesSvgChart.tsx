import { useMemo } from 'react'

import { useElementSize } from '../../hooks/useElementSize'

interface SeriesSvgChartSeries {
  name: string
  color: string
  x: number[]
  y: number[]
}

interface SeriesSvgChartProps {
  series: SeriesSvgChartSeries[]
  xLabel: string
  yLabel: string
  secondaryYLabel?: string
  logX?: boolean
  logY?: boolean
  emptyMessage: string
}

interface PointPair {
  x: number
  y: number
}

interface ChartViewport {
  svgWidth: number
  svgHeight: number
  plotLeft: number
  plotRight: number
  plotTop: number
  plotBottom: number
}

const DEFAULT_VIEW_WIDTH = 900
const DEFAULT_VIEW_HEIGHT = 420

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function resolveViewport(width: number, height: number): ChartViewport {
  const svgWidth = Math.max(160, Math.round(width) || DEFAULT_VIEW_WIDTH)
  const svgHeight = Math.max(120, Math.round(height) || DEFAULT_VIEW_HEIGHT)

  const desiredLeft = clamp(Math.round(svgWidth * 0.08), 28, 54)
  const desiredRight = clamp(Math.round(svgWidth * 0.025), 12, 22)
  const desiredTop = clamp(Math.round(svgHeight * 0.05), 10, 18)
  const desiredBottom = clamp(Math.round(svgHeight * 0.08), 18, 32)

  const availableHorizontal = Math.max(32, svgWidth - 32)
  const availableVertical = Math.max(32, svgHeight - 32)
  const horizontalScale = Math.min(1, availableHorizontal / Math.max(desiredLeft + desiredRight, 1))
  const verticalScale = Math.min(1, availableVertical / Math.max(desiredTop + desiredBottom, 1))

  const plotLeft = desiredLeft * horizontalScale
  const plotRight = svgWidth - desiredRight * horizontalScale
  const plotTop = desiredTop * verticalScale
  const plotBottom = svgHeight - desiredBottom * verticalScale

  return {
    svgWidth,
    svgHeight,
    plotLeft,
    plotRight,
    plotTop,
    plotBottom,
  }
}

function isFiniteNumber(value: number): boolean {
  return Number.isFinite(value)
}

function toAxisValue(value: number, logEnabled: boolean): number | null {
  if (!isFiniteNumber(value)) {
    return null
  }
  if (!logEnabled) {
    return value
  }
  if (value <= 0) {
    return null
  }
  const nextValue = Math.log10(value)
  return Number.isFinite(nextValue) ? nextValue : null
}

function buildPointPairs(series: SeriesSvgChartSeries, logX: boolean, logY: boolean): PointPair[] {
  const totalPoints = Math.min(series.x.length, series.y.length)
  const pairs: PointPair[] = []
  for (let index = 0; index < totalPoints; index += 1) {
    const x = toAxisValue(series.x[index] ?? NaN, logX)
    const y = toAxisValue(series.y[index] ?? NaN, logY)
    if (x === null || y === null) {
      continue
    }
    pairs.push({ x, y })
  }
  return pairs
}

function buildPath(points: PointPair[], xMin: number, xMax: number, yMin: number, yMax: number, viewport: ChartViewport): string {
  const plotWidth = Math.max(1, viewport.plotRight - viewport.plotLeft)
  const plotHeight = Math.max(1, viewport.plotBottom - viewport.plotTop)
  const xSpan = Math.max(1e-9, xMax - xMin)
  const ySpan = Math.max(1e-9, yMax - yMin)
  return points.map((point) => {
    const normalizedX = (point.x - xMin) / xSpan
    const normalizedY = (point.y - yMin) / ySpan
    const svgX = viewport.plotLeft + normalizedX * plotWidth
    const svgY = viewport.plotBottom - normalizedY * plotHeight
    return `${svgX.toFixed(2)},${svgY.toFixed(2)}`
  }).join(' ')
}

export function SeriesSvgChart({
  series,
  xLabel,
  yLabel,
  secondaryYLabel,
  logX = false,
  logY = false,
  emptyMessage,
}: SeriesSvgChartProps) {
  const { ref: chartFrameRef, width: chartWidth, height: chartHeight } = useElementSize<HTMLDivElement>()
  const chartData = useMemo(() => {
    const normalized = series.map((item) => ({
      name: item.name,
      color: item.color || '#2563eb',
      points: buildPointPairs(item, logX, logY),
    })).filter((item) => item.points.length > 0)

    const allX = normalized.flatMap((item) => item.points.map((point) => point.x))
    const allY = normalized.flatMap((item) => item.points.map((point) => point.y))
    if (!allX.length || !allY.length) {
      return null
    }

    const xMin = Math.min(...allX)
    const xMax = Math.max(...allX)
    const yMin = Math.min(...allY)
    const yMax = Math.max(...allY)

    return {
      xMin,
      xMax,
      yMin,
      yMax,
      series: normalized,
    }
  }, [logX, logY, series])

  const viewport = useMemo(() => resolveViewport(chartWidth, chartHeight), [chartHeight, chartWidth])

  const renderedSeries = useMemo(() => {
    if (!chartData) {
      return []
    }
    return chartData.series.map((item) => ({
      ...item,
      polylinePoints: buildPath(item.points, chartData.xMin, chartData.xMax, chartData.yMin, chartData.yMax, viewport),
    }))
  }, [chartData, viewport])

  if (!chartData) {
    return <div className="svg-chart-empty muted-text">{emptyMessage}</div>
  }

  const gridLines = [0, 0.25, 0.5, 0.75, 1]
  const { plotLeft, plotRight, plotTop, plotBottom, svgHeight, svgWidth } = viewport

  return (
    <div className="svg-chart-shell">
      <div className="svg-chart-meta-row muted-text">
        <span>{xLabel || 'X'}</span>
        <span>{yLabel || 'Y'}</span>
        {secondaryYLabel ? <span>{secondaryYLabel}</span> : null}
        {logX ? <span>Log X</span> : null}
        {logY ? <span>Log Y</span> : null}
      </div>
      <div ref={chartFrameRef} className="svg-chart-frame">
        <svg viewBox={`0 0 ${svgWidth} ${svgHeight}`} className="svg-chart" aria-label="Simulation series chart">
          <rect x={plotLeft} y={plotTop} width={plotRight - plotLeft} height={plotBottom - plotTop} className="svg-chart__plot-bg" />
          {gridLines.map((ratio) => {
            const y = plotTop + ratio * (plotBottom - plotTop)
            return <line key={`h-${ratio}`} x1={plotLeft} x2={plotRight} y1={y} y2={y} className="svg-chart__grid" />
          })}
          {gridLines.map((ratio) => {
            const x = plotLeft + ratio * (plotRight - plotLeft)
            return <line key={`v-${ratio}`} x1={x} x2={x} y1={plotTop} y2={plotBottom} className="svg-chart__grid" />
          })}
          <line x1={plotLeft} x2={plotRight} y1={plotBottom} y2={plotBottom} className="svg-chart__axis" />
          <line x1={plotLeft} x2={plotLeft} y1={plotTop} y2={plotBottom} className="svg-chart__axis" />
          {renderedSeries.map((item) => (
            <polyline key={item.name} fill="none" stroke={item.color} strokeWidth="2" points={item.polylinePoints} className="svg-chart__series" />
          ))}
        </svg>
      </div>
      <div className="svg-chart-legend">
        {renderedSeries.map((item) => (
          <div key={item.name} className="svg-chart-legend__item">
            <svg className="svg-chart-legend__swatch" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
              <circle cx="6" cy="6" r="5" fill={item.color} />
            </svg>
            <span className="svg-chart-legend__name">{item.name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
