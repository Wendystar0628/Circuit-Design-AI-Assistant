import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { renderToStaticMarkup } from 'react-dom/server.browser'

/** The server owns trace transforms, branch boundaries, and sample reduction. */
export interface TraceChartData {
  x_axis: { label: string; unit: string; scale: 'linear' | 'log' }
  series: Array<{
    id: string
    label: string
    unit: string
    x: Array<number | null>
    y: Array<number | null>
    color?: string
    source_result_id?: string
  }>
}

export type ChartRange = [number, number]
type CursorId = 'a' | 'b'
type ChartIdentity = { projectId: string; resultId: string; jobId?: string | null }

export interface SeriesChartProps {
  data: TraceChartData
  identity?: ChartIdentity
  range: ChartRange | null
  onRangeChange(range: ChartRange | null): void
  cursorA: number | null
  cursorB: number | null
  cursorTarget: CursorId
  onCursorChange(which: CursorId, value: number | null): void
  readoutId?: string
}

const WIDTH = 1000
const LEFT = 86
const RIGHT = 30
const TOP = 26
const BOTTOM = 276
const PLOT_WIDTH = WIDTH - LEFT - RIGHT
const LEGEND_TOP = 352
const COLORS = ['#2563eb', '#dc2626', '#059669', '#9333ea', '#d97706', '#0891b2', '#db2777', '#4f46e5']

type Domain = { min: number; max: number }
type Point = { x: number; y: number }
type RenderTrace = { id: string; label: string; color: string; segments: Point[][] }
type UnitPlot = { unit: string; domain: Domain; traces: RenderTrace[]; height: number }
type Geometry = { xDomain: Domain; groups: UnitPlot[] }

function coordinate(value: number | null, log: boolean): number | null {
  if (value === null || !Number.isFinite(value) || (log && value <= 0)) return null
  return log ? Math.log10(value) : value
}

function physical(value: number, log: boolean): number {
  return log ? 10 ** value : value
}

function finiteRange(domain: Domain, log: boolean): ChartRange | null {
  const low = physical(domain.min, log)
  const high = physical(domain.max, log)
  return Number.isFinite(low) && Number.isFinite(high) && low < high && (!log || low > 0)
    ? [low, high]
    : null
}

function expandedDomain(min: number, max: number, padding = 0): Domain {
  const extra = min === max ? Math.max(Math.abs(min) * 0.04, 1e-12) : (max - min) * padding
  return { min: min - extra, max: max + extra }
}

function tickValues(domain: Domain, count: number): number[] {
  return Array.from({ length: count }, (_, index) => domain.min + (domain.max - domain.min) * index / (count - 1))
}

function formatTick(value: number): string {
  if (value === 0) return '0'
  const exponent = Math.floor(Math.log10(Math.abs(value)) / 3) * 3
  const prefixes: Record<number, string> = { [-15]: 'f', [-12]: 'p', [-9]: 'n', [-6]: 'µ', [-3]: 'm', 0: '', 3: 'k', 6: 'M', 9: 'G', 12: 'T' }
  if (!(exponent in prefixes)) return value.toExponential(2)
  return `${Number((value / 10 ** exponent).toPrecision(4))}${prefixes[exponent]}`
}

function legendLines(label: string): string[] {
  return label.match(/.{1,112}/gu) ?? ['']
}

function buildGeometry(data: TraceChartData, range: ChartRange | null): Geometry | null {
  const log = data.x_axis.scale === 'log'
  let xMin = Infinity
  let xMax = -Infinity
  const groups = new Map<string, { min: number; max: number; traces: RenderTrace[] }>()
  for (const [traceIndex, trace] of data.series.entries()) {
    let group = groups.get(trace.unit)
    if (!group) {
      group = { min: Infinity, max: -Infinity, traces: [] }
      groups.set(trace.unit, group)
    }
    const segments: Point[][] = []
    let segment: Point[] = []
    for (let index = 0; index < Math.min(trace.x.length, trace.y.length); index += 1) {
      const x = coordinate(trace.x[index], log)
      const y = coordinate(trace.y[index], false)
      if (x === null || y === null) {
        if (segment.length) segments.push(segment)
        segment = []
        continue
      }
      xMin = Math.min(xMin, x)
      xMax = Math.max(xMax, x)
      group.min = Math.min(group.min, y)
      group.max = Math.max(group.max, y)
      // Keep server order, including descending sweeps, and every supplied sample.
      segment.push({ x, y })
    }
    if (segment.length) segments.push(segment)
    group.traces.push({ id: trace.id, label: trace.label, color: trace.color ?? COLORS[traceIndex % COLORS.length], segments })
  }
  const low = range ? coordinate(range[0], log) : null
  const high = range ? coordinate(range[1], log) : null
  const xDomain = low !== null && high !== null && low < high
    ? { min: low, max: high }
    : Number.isFinite(xMin) ? expandedDomain(xMin, xMax) : null
  if (!xDomain || !groups.size) return null
  return {
    xDomain,
    groups: [...groups].map(([unit, group]) => ({
      unit,
      domain: Number.isFinite(group.min) ? expandedDomain(group.min, group.max, 0.06) : { min: -1, max: 1 },
      traces: group.traces,
      height: LEGEND_TOP + group.traces.reduce((rows, trace) => rows + legendLines(trace.label).length, 0) * 20 + 14,
    })),
  }
}

function projectX(x: number, domain: Domain): number {
  return LEFT + (x - domain.min) / (domain.max - domain.min) * PLOT_WIDTH
}

function projectY(y: number, domain: Domain): number {
  return BOTTOM - (y - domain.min) / (domain.max - domain.min) * (BOTTOM - TOP)
}

function cursorX(value: number | null, domain: Domain, log: boolean): number | null {
  const x = coordinate(value, log)
  return x === null || x < domain.min || x > domain.max ? null : projectX(x, domain)
}

/** Shared by the interactive view and standalone SVG export. */
function PlotArtwork({ data, group, xDomain, clipId, cursorA = null, cursorB = null, cursorTarget = 'a' }: {
  data: TraceChartData
  group: UnitPlot
  xDomain: Domain
  clipId: string
  cursorA?: number | null
  cursorB?: number | null
  cursorTarget?: CursorId
}) {
  const log = data.x_axis.scale === 'log'
  let legendRow = 0
  return (
    <g fontFamily="Segoe UI, Arial, sans-serif" fontSize={12}>
      <defs><clipPath id={clipId}><rect x={LEFT} y={TOP} width={PLOT_WIDTH} height={BOTTOM - TOP} /></clipPath></defs>
      <rect width={WIDTH} height={group.height} fill="#fff" />
      {tickValues(xDomain, 7).map((tick, index) => (
        <g key={`x-${index}`}>
          <line x1={projectX(tick, xDomain)} y1={TOP} x2={projectX(tick, xDomain)} y2={BOTTOM} stroke="#e8edf3" />
          <text x={projectX(tick, xDomain)} y={BOTTOM + 23} textAnchor="middle" fill="#475569">{formatTick(physical(tick, log))}</text>
        </g>
      ))}
      {tickValues(group.domain, 6).map((tick, index) => (
        <g key={`y-${index}`}>
          <line x1={LEFT} y1={projectY(tick, group.domain)} x2={WIDTH - RIGHT} y2={projectY(tick, group.domain)} stroke="#e8edf3" />
          <text x={LEFT - 10} y={projectY(tick, group.domain) + 4} textAnchor="end" fill="#475569">{formatTick(tick)}</text>
        </g>
      ))}
      <rect x={LEFT} y={TOP} width={PLOT_WIDTH} height={BOTTOM - TOP} fill="none" stroke="#94a3b8" />
      <g clipPath={`url(#${clipId})`}>
        {group.traces.map((trace) => (
          <g key={trace.id} data-trace-id={trace.id}>
            {trace.segments.map((segment, index) => segment.length === 1
              ? <circle key={index} cx={projectX(segment[0].x, xDomain)} cy={projectY(segment[0].y, group.domain)} r={3} fill={trace.color} />
              : <polyline key={index} points={segment.map((point) => `${projectX(point.x, xDomain).toFixed(3)},${projectY(point.y, group.domain).toFixed(3)}`).join(' ')} fill="none" stroke={trace.color} strokeWidth={1.8} vectorEffect="non-scaling-stroke" />)}
          </g>
        ))}
        {([['a', cursorA, '#7c3aed'], ['b', cursorB, '#ea580c']] as const).map(([cursor, value, color]) => {
          const x = cursorX(value, xDomain, log)
          return x === null ? null : (
            <g key={cursor}>
              <line x1={x} y1={TOP} x2={x} y2={BOTTOM} stroke={color} strokeWidth={cursorTarget === cursor ? 2 : 1.5} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
              <text x={Math.min(x + 6, WIDTH - RIGHT - 14)} y={TOP + (cursor === 'a' ? 16 : 32)} fill={color} fontWeight={700}>{cursor.toUpperCase()}</text>
            </g>
          )
        })}
      </g>
      {!group.traces.some((trace) => trace.segments.length) ? <text x={WIDTH / 2} y={(TOP + BOTTOM) / 2} textAnchor="middle" fill="#64748b">No finite samples in this range</text> : null}
      <text x={(LEFT + WIDTH - RIGHT) / 2} y={BOTTOM + 49} textAnchor="middle" fill="#334155" fontWeight={600}>
        {data.x_axis.label}{data.x_axis.unit ? ` (${data.x_axis.unit})` : ''}{log ? ' · log scale' : ''}
      </text>
      <text transform={`translate(20 ${(TOP + BOTTOM) / 2}) rotate(-90)`} textAnchor="middle" fill="#334155" fontWeight={600}>{group.unit || 'Dimensionless'}</text>
      {group.traces.map((trace) => {
        const lines = legendLines(trace.label)
        const top = LEGEND_TOP + legendRow * 20
        legendRow += lines.length
        return (
          <g key={trace.id}>
            <line x1={LEFT} y1={top - 4} x2={LEFT + 25} y2={top - 4} stroke={trace.color} strokeWidth={2} />
            <text x={LEFT + 35} y={top} fill="#334155">{lines.map((line, index) => <tspan key={index} x={LEFT + 35} dy={index ? 20 : 0}>{line}</tspan>)}</text>
          </g>
        )
      })}
    </g>
  )
}

export function buildPlotSvg(data: TraceChartData, identity: ChartIdentity, range: ChartRange | null = null): string {
  const geometry = buildGeometry(data, range)
  if (!geometry) throw new Error('There are no finite samples to export.')
  let top = 34
  const panels = geometry.groups.map((group, index) => {
    const offset = top
    top += group.height + 12
    return <g key={group.unit} transform={`translate(0 ${offset})`}><PlotArtwork data={data} group={group} xDomain={geometry.xDomain} clipId={`export-plot-${index}`} /></g>
  })
  const svg = renderToStaticMarkup(
    <svg xmlns="http://www.w3.org/2000/svg" width={WIDTH} height={top} viewBox={`0 0 ${WIDTH} ${top}`} role="img" aria-label="Simulation waveforms">
      <metadata>{JSON.stringify({ project_id: identity.projectId, result_id: identity.resultId, job_id: identity.jobId, range, axis: data.x_axis, series_sources: data.series.map((series) => ({id: series.id, result_id: series.source_result_id ?? identity.resultId})) })}</metadata>
      <rect width={WIDTH} height={top} fill="#fff" />
      <text x={LEFT} y={22} fontFamily="Segoe UI, Arial, sans-serif" fontSize={12} fill="#334155">{`Result ${identity.resultId} · Project ${identity.projectId}`}</text>
      {panels}
    </svg>,
  )
  return `<?xml version="1.0" encoding="UTF-8"?>${svg}`
}

function InteractivePlot({ data, group, xDomain, range, onRangeChange, onPreviewRange, cursorA, cursorB, cursorTarget, onCursorChange, readoutId }: SeriesChartProps & {
  group: UnitPlot
  xDomain: Domain
  onPreviewRange(range: ChartRange | null): void
}) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; domain: Domain; moved: boolean; range: ChartRange | null } | null>(null)
  const clipId = `trace-${useId().replaceAll(':', '')}`
  const log = data.x_axis.scale === 'log'
  const wheelState = useRef({ xDomain, onRangeChange, log })
  wheelState.current = { xDomain, onRangeChange, log }

  const localPoint = (clientX: number, clientY: number) => {
    const svg = svgRef.current
    const matrix = svg?.getScreenCTM()
    if (!svg || !matrix) return null
    const point = svg.createSVGPoint()
    point.x = clientX
    point.y = clientY
    return point.matrixTransform(matrix.inverse())
  }

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const wheel = (event: WheelEvent) => {
      const point = localPoint(event.clientX, event.clientY)
      if (!point || point.x < LEFT || point.x > WIDTH - RIGHT || point.y < TOP || point.y > BOTTOM) return
      event.preventDefault()
      const state = wheelState.current
      const domain = state.xDomain
      const center = domain.min + (point.x - LEFT) / PLOT_WIDTH * (domain.max - domain.min)
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 250 : 1)
      const factor = Math.exp(Math.max(-1, Math.min(1, delta * 0.002)))
      const next = { min: center + (domain.min - center) * factor, max: center + (domain.max - center) * factor }
      const nextRange = finiteRange(next, state.log)
      if (nextRange) {
        // Keep successive wheel events cumulative before React's next render.
        wheelState.current = { ...state, xDomain: next }
        state.onRangeChange(nextRange)
      }
    }
    svg.addEventListener('wheel', wheel, { passive: false })
    return () => svg.removeEventListener('wheel', wheel)
  }, [])

  const pointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return
    const point = localPoint(event.clientX, event.clientY)
    if (!point || point.x < LEFT || point.x > WIDTH - RIGHT || point.y < TOP || point.y > BOTTOM) return
    dragRef.current = { pointerId: event.pointerId, startX: point.x, domain: xDomain, moved: false, range }
    event.currentTarget.setPointerCapture(event.pointerId)
    event.currentTarget.focus({ preventScroll: true })
    event.preventDefault()
  }

  const pointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const point = localPoint(event.clientX, event.clientY)
    if (!point) return
    if (Math.abs(point.x - drag.startX) > 4) drag.moved = true
    if (!drag.moved) return
    const offset = (drag.startX - point.x) / PLOT_WIDTH * (drag.domain.max - drag.domain.min)
    const next = finiteRange({ min: drag.domain.min + offset, max: drag.domain.max + offset }, log)
    if (next) {
      drag.range = next
      onPreviewRange(next)
    }
    event.preventDefault()
  }

  const pointerEnd = (event: PointerEvent<SVGSVGElement>, cancelled = false) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (!cancelled) {
      if (drag.moved && drag.range) onRangeChange(drag.range)
      else if (!drag.moved) {
        const point = localPoint(event.clientX, event.clientY)
        if (point) {
          const fraction = Math.max(0, Math.min(1, (point.x - LEFT) / PLOT_WIDTH))
          onCursorChange(cursorTarget, physical(drag.domain.min + fraction * (drag.domain.max - drag.domain.min), log))
        }
      }
    }
    onPreviewRange(null)
  }

  const keyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key === 'Delete' || event.key === 'Backspace') {
      onCursorChange(cursorTarget, null)
    } else if (event.key === 'Home' || event.key === 'End') {
      onCursorChange(cursorTarget, physical(event.key === 'Home' ? xDomain.min : xDomain.max, log))
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      const current = coordinate(cursorTarget === 'a' ? cursorA : cursorB, log) ?? (xDomain.min + xDomain.max) / 2
      const direction = event.key === 'ArrowLeft' ? -1 : 1
      const next = current + direction * (xDomain.max - xDomain.min) * (event.shiftKey ? 0.1 : 0.01)
      onCursorChange(cursorTarget, physical(Math.max(xDomain.min, Math.min(xDomain.max, next)), log))
    } else if (event.key === 'Escape') {
      const pointerId = dragRef.current?.pointerId
      dragRef.current = null
      if (pointerId !== undefined && event.currentTarget.hasPointerCapture(pointerId)) event.currentTarget.releasePointerCapture(pointerId)
      onPreviewRange(null)
    } else return
    event.preventDefault()
  }

  return (
    <svg ref={svgRef} className="simulation-chart" style={{ height: 'auto' }} viewBox={`0 0 ${WIDTH} ${group.height}`} role="application" tabIndex={0}
      aria-describedby={readoutId}
      aria-label={`${group.unit || 'Dimensionless'} waveforms. Click to place cursor ${cursorTarget.toUpperCase()}; drag to pan; scroll to zoom. Arrow keys move the cursor by 1% of the view, Shift by 10%; Home and End move to the view limits; Delete clears the cursor.`}
      aria-keyshortcuts="ArrowLeft ArrowRight Shift+ArrowLeft Shift+ArrowRight Home End Delete Backspace Escape"
      onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={(event) => pointerEnd(event)} onPointerCancel={(event) => pointerEnd(event, true)}
      onLostPointerCapture={() => { if (dragRef.current) { dragRef.current = null; onPreviewRange(null) } }} onKeyDown={keyDown}>
      <PlotArtwork data={data} group={group} xDomain={xDomain} clipId={clipId} cursorA={cursorA} cursorB={cursorB} cursorTarget={cursorTarget} />
    </svg>
  )
}

export function SeriesChart(props: SeriesChartProps) {
  const [previewRange, setPreviewRange] = useState<ChartRange | null>(null)
  const geometry = useMemo(() => buildGeometry(props.data, previewRange ?? props.range), [props.data, props.range, previewRange])
  useEffect(() => { setPreviewRange(null) }, [props.data, props.range])
  if (!geometry) return <div className="simulation-empty simulation-empty--chart">No visible finite samples.</div>
  return (
    <div className="simulation-chart-stack">
      {geometry.groups.map((group) => <InteractivePlot key={group.unit} {...props} group={group} xDomain={geometry.xDomain} onPreviewRange={setPreviewRange} />)}
    </div>
  )
}
