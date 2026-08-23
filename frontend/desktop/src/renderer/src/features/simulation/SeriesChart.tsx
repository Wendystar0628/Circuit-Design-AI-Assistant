import {
  useId,
  useMemo,
  useRef,
  type KeyboardEvent,
  type PointerEvent,
} from 'react'

import {
  collectCursorSamples,
  formatEngineering,
  snapCursorValue,
  stepCursorValue,
} from './simulationModel'
import type { AxisSide, PlotModel, PlotSeries, ResultIdentity } from './types'

const WIDTH = 1000
const HEIGHT = 480
const MARGIN = { top: 24, right: 76, bottom: 58, left: 76 }
const MAX_RENDER_POINTS_PER_SEGMENT = 4000
const CURSOR_HIT_RADIUS_PX = 10

type CursorId = 'a' | 'b'

interface Domain {
  min: number
  max: number
}

interface Point {
  x: number
  y: number
}

interface RenderSeries {
  series: PlotSeries
  segments: Point[][]
}

interface ChartGeometry {
  xDomain: Domain
  leftDomain: Domain
  rightDomain: Domain | null
  rendered: RenderSeries[]
  xTicks: number[]
  leftTicks: number[]
  rightTicks: number[]
}

interface SeriesChartProps {
  model: PlotModel
  identity: ResultIdentity
  visibleSeriesIds: ReadonlySet<string>
  cursorA: number | null
  cursorB: number | null
  cursorTarget: CursorId
  onCursorTarget(cursor: CursorId): void
  onCursorChange(cursor: CursorId, value: number | null): void
  readoutId?: string
}

function transform(value: number | null, logarithmic: boolean): number | null {
  if (value === null || !Number.isFinite(value)) return null
  if (!logarithmic) return value
  return value > 0 ? Math.log10(value) : null
}

function resolveDomain(values: Iterable<number>): Domain | null {
  let min = Number.POSITIVE_INFINITY
  let max = Number.NEGATIVE_INFINITY
  for (const value of values) {
    if (!Number.isFinite(value)) continue
    min = Math.min(min, value)
    max = Math.max(max, value)
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null
  if (min === max) {
    const padding = Math.max(Math.abs(min) * 0.08, 1e-12)
    return { min: min - padding, max: max + padding }
  }
  const padding = (max - min) * 0.04
  return { min: min - padding, max: max + padding }
}

function axisIsLog(model: PlotModel, axis: AxisSide): boolean {
  return axis === 'right' ? model.logRightY : model.logLeftY
}

function buildSegments(series: PlotSeries, model: PlotModel): Point[][] {
  const segments: Point[][] = []
  let active: Point[] = []
  const yLog = axisIsLog(model, series.axis)
  const count = Math.min(series.x.length, series.y.length)
  for (let index = 0; index < count; index += 1) {
    const x = transform(series.x[index], model.logX)
    const y = transform(series.y[index], yLog)
    if (x === null || y === null) {
      if (active.length) segments.push(reduceSegment(active))
      active = []
      continue
    }
    active.push({ x, y })
  }
  if (active.length) segments.push(reduceSegment(active))
  return segments
}

function reduceSegment(points: Point[]): Point[] {
  if (points.length <= MAX_RENDER_POINTS_PER_SEGMENT) return points
  const interior = points.length - 2
  const bucketCount = Math.max(1, Math.floor((MAX_RENDER_POINTS_PER_SEGMENT - 2) / 2))
  const bucketSize = interior / bucketCount
  const reduced: Point[] = [points[0]]
  for (let bucket = 0; bucket < bucketCount; bucket += 1) {
    const start = 1 + Math.floor(bucket * bucketSize)
    const end = Math.min(points.length - 1, 1 + Math.floor((bucket + 1) * bucketSize))
    if (end <= start) continue
    let minimum = points[start]
    let maximum = points[start]
    for (let index = start + 1; index < end; index += 1) {
      if (points[index].y < minimum.y) minimum = points[index]
      if (points[index].y > maximum.y) maximum = points[index]
    }
    if (minimum.x <= maximum.x) reduced.push(minimum, maximum)
    else reduced.push(maximum, minimum)
  }
  reduced.push(points[points.length - 1])
  return reduced
}

function ticks(domain: Domain, count = 7): number[] {
  return Array.from({ length: count }, (_, index) => (
    domain.min + (domain.max - domain.min) * index / (count - 1)
  ))
}

function buildGeometry(model: PlotModel, visible: ReadonlySet<string>): ChartGeometry | null {
  const rendered = model.series
    .filter((series) => visible.has(series.id))
    .map((series) => ({ series, segments: buildSegments(series, model) }))
    .filter((series) => series.segments.length)
  const xDomain = resolveDomain(rendered.flatMap((item) => item.segments.flatMap((segment) => segment.map((point) => point.x))))
  const leftDomain = resolveDomain(rendered
    .filter((item) => item.series.axis === 'left')
    .flatMap((item) => item.segments.flatMap((segment) => segment.map((point) => point.y))))
  const rightDomain = resolveDomain(rendered
    .filter((item) => item.series.axis === 'right')
    .flatMap((item) => item.segments.flatMap((segment) => segment.map((point) => point.y))))
  if (!xDomain || (!leftDomain && !rightDomain)) return null
  const effectiveLeft = leftDomain ?? rightDomain as Domain
  return {
    xDomain,
    leftDomain: effectiveLeft,
    rightDomain,
    rendered,
    xTicks: ticks(xDomain),
    leftTicks: ticks(effectiveLeft),
    rightTicks: rightDomain ? ticks(rightDomain) : [],
  }
}

function projectX(value: number, domain: Domain): number {
  return MARGIN.left + (value - domain.min) / (domain.max - domain.min) * (WIDTH - MARGIN.left - MARGIN.right)
}

function projectY(value: number, domain: Domain): number {
  return HEIGHT - MARGIN.bottom - (value - domain.min) / (domain.max - domain.min) * (HEIGHT - MARGIN.top - MARGIN.bottom)
}

function displayAxisValue(value: number, logarithmic: boolean): number {
  return logarithmic ? 10 ** value : value
}

function pointsAttribute(points: Point[], xDomain: Domain, yDomain: Domain): string {
  return points.map((point) => `${projectX(point.x, xDomain).toFixed(2)},${projectY(point.y, yDomain).toFixed(2)}`).join(' ')
}

function escapeXml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;')
}

function cursorPosition(value: number | null, model: PlotModel, geometry: ChartGeometry): number | null {
  const transformed = transform(value, model.logX)
  if (transformed === null || transformed < geometry.xDomain.min || transformed > geometry.xDomain.max) return null
  return projectX(transformed, geometry.xDomain)
}

export function buildPlotSvg(
  model: PlotModel,
  identity: ResultIdentity,
  visibleSeriesIds: ReadonlySet<string>,
): string {
  const geometry = buildGeometry(model, visibleSeriesIds)
  if (!geometry) throw new Error('There are no visible finite samples to export.')
  const metadata = escapeXml(JSON.stringify({
    project_id: identity.projectId,
    job_id: identity.jobId,
    result_id: identity.resultId,
    analysis_type: model.analysisType,
  }))
  const grid = geometry.xTicks.map((tick) => {
    const x = projectX(tick, geometry.xDomain)
    return `<line x1="${x}" y1="${MARGIN.top}" x2="${x}" y2="${HEIGHT - MARGIN.bottom}" stroke="#e5e7eb"/>`
  }).join('') + geometry.leftTicks.map((tick) => {
    const y = projectY(tick, geometry.leftDomain)
    return `<line x1="${MARGIN.left}" y1="${y}" x2="${WIDTH - MARGIN.right}" y2="${y}" stroke="#e5e7eb"/>`
  }).join('')
  const series = geometry.rendered.flatMap((item) => {
    const domain = item.series.axis === 'right' && geometry.rightDomain
      ? geometry.rightDomain
      : geometry.leftDomain
    return item.segments.map((segment) => `<polyline points="${pointsAttribute(segment, geometry.xDomain, domain)}" fill="none" stroke="${escapeXml(item.series.color)}" stroke-width="2" vector-effect="non-scaling-stroke"/>`)
  }).join('')
  return `<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}"><metadata>${metadata}</metadata><rect width="100%" height="100%" fill="#ffffff"/>${grid}<rect x="${MARGIN.left}" y="${MARGIN.top}" width="${WIDTH - MARGIN.left - MARGIN.right}" height="${HEIGHT - MARGIN.top - MARGIN.bottom}" fill="none" stroke="#94a3b8"/>${series}<text x="${WIDTH / 2}" y="${HEIGHT - 12}" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="14" fill="#334155">${escapeXml(`${model.xLabel}${model.xUnit ? ` (${model.xUnit})` : ''}`)}</text></svg>`
}

export function SeriesChart({
  model,
  identity,
  visibleSeriesIds,
  cursorA,
  cursorB,
  cursorTarget,
  onCursorTarget,
  onCursorChange,
  readoutId,
}: SeriesChartProps) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragRef = useRef<{ pointerId: number; cursor: CursorId } | null>(null)
  const clipId = useId().replaceAll(':', '')
  const geometry = useMemo(() => buildGeometry(model, visibleSeriesIds), [model, visibleSeriesIds])
  const cursorSamples = useMemo(
    () => collectCursorSamples(model, visibleSeriesIds),
    [model, visibleSeriesIds],
  )
  if (!geometry) {
    return <div className="simulation-empty simulation-empty--chart">No visible finite samples.</div>
  }
  const plotWidth = WIDTH - MARGIN.left - MARGIN.right
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
  const cursorAX = cursorPosition(cursorA, model, geometry)
  const cursorBX = cursorPosition(cursorB, model, geometry)
  const metadata = JSON.stringify({
    project_id: identity.projectId,
    job_id: identity.jobId,
    result_id: identity.resultId,
  })

  const eventPoint = (event: PointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current
    const matrix = svg?.getScreenCTM()
    if (!svg || !matrix) return null
    const point = svg.createSVGPoint()
    point.x = event.clientX
    point.y = event.clientY
    return {
      local: point.matrixTransform(matrix.inverse()),
      scaleX: Math.hypot(matrix.a, matrix.b),
    }
  }

  const moveCursor = (cursor: CursorId, svgX: number) => {
    const clampedX = Math.max(MARGIN.left, Math.min(WIDTH - MARGIN.right, svgX))
    const transformed = geometry.xDomain.min
      + (clampedX - MARGIN.left) / plotWidth * (geometry.xDomain.max - geometry.xDomain.min)
    const snapped = snapCursorValue(
      cursorSamples,
      displayAxisValue(transformed, model.logX),
      model.logX,
    )
    if (snapped !== null) onCursorChange(cursor, snapped)
  }

  const cursorAtPoint = (svgX: number, scaleX: number): CursorId => {
    const hitRadius = scaleX > 0 ? CURSOR_HIT_RADIUS_PX / scaleX : 0
    const candidates: Array<{ cursor: CursorId; distance: number }> = []
    if (cursorAX !== null) {
      candidates.push({ cursor: 'a', distance: Math.abs(cursorAX - svgX) })
    }
    if (cursorBX !== null) {
      candidates.push({ cursor: 'b', distance: Math.abs(cursorBX - svgX) })
    }
    candidates.sort((left, right) => {
      const distance = left.distance - right.distance
      if (distance !== 0) return distance
      if (left.cursor === cursorTarget) return -1
      if (right.cursor === cursorTarget) return 1
      return 0
    })
    const closest = candidates[0]
    return closest && closest.distance <= hitRadius ? closest.cursor : cursorTarget
  }

  const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
    const point = eventPoint(event)
    if (!point) return
    const { x, y } = point.local
    if (
      x < MARGIN.left
      || x > WIDTH - MARGIN.right
      || y < MARGIN.top
      || y > HEIGHT - MARGIN.bottom
    ) return

    const cursor = cursorAtPoint(x, point.scaleX)
    dragRef.current = { pointerId: event.pointerId, cursor }
    event.currentTarget.setPointerCapture(event.pointerId)
    event.currentTarget.focus({ preventScroll: true })
    onCursorTarget(cursor)
    moveCursor(cursor, x)
    event.preventDefault()
  }

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const point = eventPoint(event)
    if (!point) return
    moveCursor(drag.cursor, point.local.x)
    event.preventDefault()
  }

  const finishPointer = (event: PointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const handleKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key === 'Delete' || event.key === 'Backspace') {
      onCursorChange(cursorTarget, null)
      event.preventDefault()
      return
    }
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    const current = cursorTarget === 'a' ? cursorA : cursorB
    const next = stepCursorValue(
      cursorSamples,
      current,
      event.key === 'ArrowLeft' ? -1 : 1,
      model.logX,
      event.shiftKey,
    )
    if (next !== null) onCursorChange(cursorTarget, next)
    event.preventDefault()
  }

  return (
    <svg
      ref={svgRef}
      className="simulation-chart"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="application"
      tabIndex={0}
      aria-describedby={readoutId}
      aria-keyshortcuts="ArrowLeft ArrowRight Shift+ArrowLeft Shift+ArrowRight Delete Backspace"
      aria-label={`${model.title}. Click or drag to move active cursor ${cursorTarget.toUpperCase()}. Use Left and Right arrows to move by one sample, Shift with an arrow to move by ten samples, and Delete to clear it.`}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishPointer}
      onPointerCancel={finishPointer}
      onLostPointerCapture={() => { dragRef.current = null }}
    >
      <metadata>{metadata}</metadata>
      <defs>
        <clipPath id={clipId}>
          <rect x={MARGIN.left} y={MARGIN.top} width={plotWidth} height={plotHeight} />
        </clipPath>
      </defs>
      <rect width={WIDTH} height={HEIGHT} className="simulation-chart__background" />
      {geometry.xTicks.map((tick) => {
        const x = projectX(tick, geometry.xDomain)
        return (
          <g key={`x-${tick}`}>
            <line x1={x} y1={MARGIN.top} x2={x} y2={HEIGHT - MARGIN.bottom} className="simulation-chart__grid" />
            <text x={x} y={HEIGHT - MARGIN.bottom + 22} textAnchor="middle" className="simulation-chart__tick">
              {formatEngineering(displayAxisValue(tick, model.logX))}
            </text>
          </g>
        )
      })}
      {geometry.leftTicks.map((tick) => {
        const y = projectY(tick, geometry.leftDomain)
        return (
          <g key={`left-${tick}`}>
            <line x1={MARGIN.left} y1={y} x2={WIDTH - MARGIN.right} y2={y} className="simulation-chart__grid" />
            <text x={MARGIN.left - 10} y={y + 4} textAnchor="end" className="simulation-chart__tick">
              {formatEngineering(displayAxisValue(tick, model.logLeftY))}
            </text>
          </g>
        )
      })}
      {geometry.rightTicks.map((tick) => {
        const y = projectY(tick, geometry.rightDomain as Domain)
        return (
          <text key={`right-${tick}`} x={WIDTH - MARGIN.right + 10} y={y + 4} className="simulation-chart__tick">
            {formatEngineering(displayAxisValue(tick, model.logRightY))}
          </text>
        )
      })}
      <rect x={MARGIN.left} y={MARGIN.top} width={plotWidth} height={plotHeight} className="simulation-chart__frame" />
      <g clipPath={`url(#${clipId})`}>
        {geometry.rendered.flatMap((item) => {
          const domain = item.series.axis === 'right' && geometry.rightDomain
            ? geometry.rightDomain
            : geometry.leftDomain
          return item.segments.map((segment, index) => (
            <polyline
              key={`${item.series.id}-${index}`}
              points={pointsAttribute(segment, geometry.xDomain, domain)}
              fill="none"
              stroke={item.series.color}
              strokeWidth={2}
              strokeDasharray={item.series.component === 'phase' ? '7 5' : undefined}
              vectorEffect="non-scaling-stroke"
            />
          ))
        })}
        {cursorAX !== null ? <line x1={cursorAX} y1={MARGIN.top} x2={cursorAX} y2={HEIGHT - MARGIN.bottom} className={`simulation-chart__cursor simulation-chart__cursor--a${cursorTarget === 'a' ? ' is-active' : ''}`} /> : null}
        {cursorBX !== null ? <line x1={cursorBX} y1={MARGIN.top} x2={cursorBX} y2={HEIGHT - MARGIN.bottom} className={`simulation-chart__cursor simulation-chart__cursor--b${cursorTarget === 'b' ? ' is-active' : ''}`} /> : null}
      </g>
      {cursorAX !== null ? <text x={cursorAX + 5} y={MARGIN.top + 14} className={`simulation-chart__cursor-label simulation-chart__cursor-label--a${cursorTarget === 'a' ? ' is-active' : ''}`}>A</text> : null}
      {cursorBX !== null ? <text x={cursorBX + 5} y={MARGIN.top + 30} className={`simulation-chart__cursor-label simulation-chart__cursor-label--b${cursorTarget === 'b' ? ' is-active' : ''}`}>B</text> : null}
      <text x={WIDTH / 2} y={HEIGHT - 12} textAnchor="middle" className="simulation-chart__axis-title">
        {model.xLabel}{model.xUnit ? ` (${model.xUnit})` : ''}
      </text>
      <text transform={`translate(18 ${HEIGHT / 2}) rotate(-90)`} textAnchor="middle" className="simulation-chart__axis-title">
        {model.leftLabel}
      </text>
      {model.rightLabel ? (
        <text transform={`translate(${WIDTH - 16} ${HEIGHT / 2}) rotate(90)`} textAnchor="middle" className="simulation-chart__axis-title">
          {model.rightLabel}
        </text>
      ) : null}
    </svg>
  )
}
