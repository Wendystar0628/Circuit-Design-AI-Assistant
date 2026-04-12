import { formatCompactNumber, normalizeZero } from './chartValueFormatting'

export interface SeriesSvgChartDatum {
  name: string
  color: string
  x: number[]
  y: number[]
  axis_key?: string
  line_style?: string
  component?: string
}

export interface SeriesSvgChartViewport {
  svgWidth: number
  svgHeight: number
  plotLeft: number
  plotRight: number
  plotTop: number
  plotBottom: number
}

export interface SeriesSvgChartAxisDomain {
  min: number
  max: number
}

export interface SeriesSvgChartTick {
  value: number
  label: string
  position: number
}

export interface SeriesSvgChartRenderedSeries {
  name: string
  color: string
  axisKey: 'left' | 'right'
  lineStyle: 'solid' | 'dash'
  component: string
  polylinePoints: string
  strokeDasharray?: string
}

export interface SeriesSvgChartViewWindow {
  active: boolean
  xMin: number | null
  xMax: number | null
  leftYMin: number | null
  leftYMax: number | null
  rightYMin: number | null
  rightYMax: number | null
}

export interface SeriesSvgChartModel {
  viewport: SeriesSvgChartViewport
  xDomain: SeriesSvgChartAxisDomain
  leftDomain: SeriesSvgChartAxisDomain
  rightDomain: SeriesSvgChartAxisDomain | null
  xLabel: string
  leftAxisLabel: string
  rightAxisLabel: string
  hasRightAxis: boolean
  xTicks: SeriesSvgChartTick[]
  leftTicks: SeriesSvgChartTick[]
  rightTicks: SeriesSvgChartTick[]
  renderedSeries: SeriesSvgChartRenderedSeries[]
}

interface PointPair {
  x: number
  y: number
}

interface AxisDomain {
  min: number
  max: number
}

interface NormalizedSeries {
  name: string
  color: string
  axisKey: 'left' | 'right'
  lineStyle: 'solid' | 'dash'
  component: string
  points: PointPair[]
}

interface BuildSeriesSvgChartModelOptions {
  series: SeriesSvgChartDatum[]
  xLabel: string
  yLabel: string
  secondaryYLabel?: string
  logX: boolean
  logY: boolean
  width: number
  height: number
  viewWindow?: SeriesSvgChartViewWindow | null
}

const DEFAULT_VIEW_WIDTH = 900
const DEFAULT_VIEW_HEIGHT = 420
const ZERO_EPSILON = 1e-12
const DEFAULT_STROKE_DASHARRAY = '8 6'

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function niceTickSpacing(span: number, targetTicks: number): number {
  if (!Number.isFinite(span) || span <= 0) {
    return 1
  }

  const roughStep = span / Math.max(targetTicks, 1)
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const normalized = roughStep / magnitude

  if (normalized <= 1) {
    return 1 * magnitude
  }
  if (normalized <= 2) {
    return 2 * magnitude
  }
  if (normalized <= 2.5) {
    return 2.5 * magnitude
  }
  if (normalized <= 5) {
    return 5 * magnitude
  }
  return 10 * magnitude
}

function toAxisValue(value: number, logEnabled: boolean): number | null {
  if (!Number.isFinite(value)) {
    return null
  }
  if (!logEnabled) {
    return value
  }
  if (value <= 0) {
    return null
  }
  const transformed = Math.log10(value)
  return Number.isFinite(transformed) ? transformed : null
}

function normalizeAxisKey(value: string | undefined): 'left' | 'right' {
  return value === 'right' ? 'right' : 'left'
}

function normalizeLineStyle(value: string | undefined): 'solid' | 'dash' {
  return value === 'dash' ? 'dash' : 'solid'
}

function normalizeRequestedRange(minValue: number | null, maxValue: number | null, logEnabled: boolean): AxisDomain | null {
  if (minValue === null || maxValue === null || !Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
    return null
  }
  const minAxisValue = toAxisValue(minValue, logEnabled)
  const maxAxisValue = toAxisValue(maxValue, logEnabled)
  if (minAxisValue === null || maxAxisValue === null) {
    return null
  }
  return minAxisValue <= maxAxisValue
    ? { min: minAxisValue, max: maxAxisValue }
    : { min: maxAxisValue, max: minAxisValue }
}

function clampRequestedDomain(requested: AxisDomain | null, allowed: AxisDomain | null): AxisDomain | null {
  if (requested === null || allowed === null) {
    return null
  }
  const min = Math.max(requested.min, allowed.min)
  const max = Math.min(requested.max, allowed.max)
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
    return null
  }
  return { min, max }
}

function buildPointPairs(series: SeriesSvgChartDatum, logX: boolean, logY: boolean): PointPair[] {
  const totalPoints = Math.min(series.x.length, series.y.length)
  const points: PointPair[] = []
  for (let index = 0; index < totalPoints; index += 1) {
    const x = toAxisValue(series.x[index] ?? Number.NaN, logX)
    const y = toAxisValue(series.y[index] ?? Number.NaN, logY)
    if (x === null || y === null) {
      continue
    }
    points.push({ x, y })
  }
  return points
}

function resolveDomain(values: number[], paddingRatio: number, minimumPadding: number): AxisDomain | null {
  if (!values.length) {
    return null
  }

  const min = Math.min(...values)
  const max = Math.max(...values)
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return null
  }

  if (Math.abs(max - min) <= ZERO_EPSILON) {
    const fallback = Math.max(Math.abs(min), minimumPadding, 1)
    const padding = fallback * Math.max(paddingRatio, 0.08)
    return {
      min: min - padding,
      max: max + padding,
    }
  }

  const padding = Math.max((max - min) * paddingRatio, minimumPadding)
  return {
    min: min - padding,
    max: max + padding,
  }
}

function resolveViewport(width: number, height: number, hasRightAxis: boolean): SeriesSvgChartViewport {
  const svgWidth = Math.max(240, Math.round(width) || DEFAULT_VIEW_WIDTH)
  const svgHeight = Math.max(180, Math.round(height) || DEFAULT_VIEW_HEIGHT)

  const desiredLeft = hasRightAxis ? clamp(Math.round(svgWidth * 0.1), 58, 78) : clamp(Math.round(svgWidth * 0.078), 46, 62)
  const desiredRight = hasRightAxis ? clamp(Math.round(svgWidth * 0.1), 58, 78) : clamp(Math.round(svgWidth * 0.03), 18, 28)
  const desiredTop = clamp(Math.round(svgHeight * 0.045), 12, 20)
  const desiredBottom = clamp(Math.round(svgHeight * 0.15), 52, 76)

  const minPlotWidth = 120
  const minPlotHeight = 92
  const availableHorizontal = Math.max(minPlotWidth, svgWidth - minPlotWidth)
  const availableVertical = Math.max(minPlotHeight, svgHeight - minPlotHeight)
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

function projectHorizontal(value: number, domain: AxisDomain, viewport: SeriesSvgChartViewport): number {
  const span = Math.max(domain.max - domain.min, ZERO_EPSILON)
  const ratio = (value - domain.min) / span
  return viewport.plotLeft + ratio * (viewport.plotRight - viewport.plotLeft)
}

function projectVertical(value: number, domain: AxisDomain, viewport: SeriesSvgChartViewport): number {
  const span = Math.max(domain.max - domain.min, ZERO_EPSILON)
  const ratio = (value - domain.min) / span
  return viewport.plotBottom - ratio * (viewport.plotBottom - viewport.plotTop)
}

function buildTickValues(domain: AxisDomain, targetTicks: number): number[] {
  const span = domain.max - domain.min
  const step = niceTickSpacing(span, targetTicks)
  if (!Number.isFinite(step) || step <= 0) {
    return [domain.min, domain.max]
  }

  const start = Math.floor(domain.min / step) * step
  const stop = Math.ceil(domain.max / step) * step
  const tickCount = Math.min(128, Math.ceil((stop - start) / step) + 1)
  const ticks: number[] = []
  for (let index = 0; index < tickCount; index += 1) {
    const value = normalizeZero(start + step * index)
    if (value < domain.min - step * 0.35 || value > domain.max + step * 0.35) {
      continue
    }
    ticks.push(value)
  }

  if (!ticks.length) {
    ticks.push(domain.min, domain.max)
  }

  return ticks
}

function buildTicks(
  domain: AxisDomain,
  viewport: SeriesSvgChartViewport,
  targetTicks: number,
  orientation: 'horizontal' | 'vertical',
  logEnabled: boolean,
): SeriesSvgChartTick[] {
  return buildTickValues(domain, targetTicks).map((value) => ({
    value,
    label: formatCompactNumber(logEnabled ? 10 ** value : value),
    position: orientation === 'horizontal'
      ? projectHorizontal(value, domain, viewport)
      : projectVertical(value, domain, viewport),
  }))
}

function buildPath(points: PointPair[], xDomain: AxisDomain, yDomain: AxisDomain, viewport: SeriesSvgChartViewport): string {
  return points.map((point) => `${projectHorizontal(point.x, xDomain, viewport).toFixed(2)},${projectVertical(point.y, yDomain, viewport).toFixed(2)}`).join(' ')
}

function strokeDasharrayForStyle(lineStyle: 'solid' | 'dash'): string | undefined {
  return lineStyle === 'dash' ? DEFAULT_STROKE_DASHARRAY : undefined
}

export function buildSeriesSvgChartModel({
  series,
  xLabel,
  yLabel,
  secondaryYLabel,
  logX,
  logY,
  width,
  height,
  viewWindow,
}: BuildSeriesSvgChartModelOptions): SeriesSvgChartModel | null {
  const normalizedSeries: NormalizedSeries[] = series.map((item) => {
    const axisKey = normalizeAxisKey(item.axis_key)
    const lineStyle = normalizeLineStyle(item.line_style)
    const points = buildPointPairs(item, logX, axisKey === 'left' && logY)
    return {
      name: item.name,
      color: item.color || '#2563eb',
      axisKey,
      lineStyle,
      component: item.component || '',
      points,
    }
  }).filter((item) => item.points.length > 0)

  if (!normalizedSeries.length) {
    return null
  }

  const hasRightAxis = normalizedSeries.some((item) => item.axisKey === 'right')
  const viewport = resolveViewport(width, height, hasRightAxis)
  const xValues = normalizedSeries.flatMap((item) => item.points.map((point) => point.x))
  const leftSeries = normalizedSeries.filter((item) => item.axisKey === 'left')
  const rightSeries = normalizedSeries.filter((item) => item.axisKey === 'right')
  const leftValues = (leftSeries.length ? leftSeries : normalizedSeries).flatMap((item) => item.points.map((point) => point.y))
  const rightValues = rightSeries.flatMap((item) => item.points.map((point) => point.y))

  const xDomain = resolveDomain(xValues, 0.02, logX ? 0.05 : 0)
  const leftDomain = resolveDomain(leftValues, 0.08, 0)
  const rightDomain = hasRightAxis ? resolveDomain(rightValues, 0.08, 0) : null
  if (xDomain === null || leftDomain === null) {
    return null
  }

  const requestedXDomain = viewWindow?.active ? clampRequestedDomain(normalizeRequestedRange(viewWindow.xMin, viewWindow.xMax, logX), xDomain) : null
  const requestedLeftDomain = viewWindow?.active ? clampRequestedDomain(normalizeRequestedRange(viewWindow.leftYMin, viewWindow.leftYMax, logY), leftDomain) : null
  const requestedRightDomain = viewWindow?.active && rightDomain !== null
    ? clampRequestedDomain(normalizeRequestedRange(viewWindow.rightYMin, viewWindow.rightYMax, false), rightDomain)
    : null

  const effectiveXDomain = requestedXDomain ?? xDomain
  const effectiveLeftDomain = requestedLeftDomain ?? leftDomain
  const effectiveRightDomain = rightDomain === null ? null : (requestedRightDomain ?? rightDomain)

  const xTargetTicks = clamp(Math.round((viewport.plotRight - viewport.plotLeft) / 82), 6, 14)
  const yTargetTicks = clamp(Math.round((viewport.plotBottom - viewport.plotTop) / 40), 6, 12)
  const xTicks = buildTicks(effectiveXDomain, viewport, xTargetTicks, 'horizontal', logX)
  const leftTicks = buildTicks(effectiveLeftDomain, viewport, yTargetTicks, 'vertical', logY)
  const rightTicks = effectiveRightDomain === null ? [] : buildTicks(effectiveRightDomain, viewport, yTargetTicks, 'vertical', false)

  const renderedSeries = normalizedSeries.map((item) => {
    const yDomain = item.axisKey === 'right' && effectiveRightDomain !== null ? effectiveRightDomain : effectiveLeftDomain
    return {
      name: item.name,
      color: item.color,
      axisKey: item.axisKey,
      lineStyle: item.lineStyle,
      component: item.component,
      polylinePoints: buildPath(item.points, effectiveXDomain, yDomain, viewport),
      strokeDasharray: strokeDasharrayForStyle(item.lineStyle),
    }
  })

  return {
    viewport,
    xDomain: effectiveXDomain,
    leftDomain: effectiveLeftDomain,
    rightDomain: effectiveRightDomain,
    xLabel: xLabel || 'X',
    leftAxisLabel: yLabel || (hasRightAxis ? 'Left axis' : 'Y'),
    rightAxisLabel: hasRightAxis ? (secondaryYLabel || 'Right axis') : '',
    hasRightAxis,
    xTicks,
    leftTicks,
    rightTicks,
    renderedSeries,
  }
}
