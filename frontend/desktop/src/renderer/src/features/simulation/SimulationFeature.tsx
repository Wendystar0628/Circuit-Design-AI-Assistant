import { useEffect, useMemo, useState } from 'react'

import { buildPlotSvg, SeriesChart } from './SeriesChart'
import {
  buildPlotCsv,
  buildRawColumns,
  downloadBlob,
  downloadContent,
  resultFileName,
} from './exportUtils'
import {
  buildNoiseTotalRows,
  displayAnalysisType,
  formatEngineering,
  isSupportedCircuitPath,
  nearestSampleIndex,
} from './simulationModel'
import { buildSchematicLayout } from './schematicLayout'
import type {
  PlotModel,
  ResultViewModel,
  SchematicDocumentDto,
  SimulationFeatureProps,
  SimulationJobDto,
  SimulationResultSummaryDto,
  SimulationTabId,
} from './types'
import { useSimulationController } from './useSimulationController'
import './styles.css'

const PAGE_SIZE = 200
const LOG_PAGE_SIZE = 500

const TAB_LABELS: Record<SimulationTabId, string> = {
  runs: 'Runs',
  metrics: 'Metrics',
  chart: 'Chart',
  waveform: 'Waveform',
  schematic: 'Schematic',
  analysis: 'Analysis',
  raw: 'Raw data',
  log: 'Output log',
  export: 'Export',
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function fileName(path: string | null): string {
  if (!path) return 'No active circuit'
  const segments = path.split(/[\\/]/)
  return segments[segments.length - 1] || path
}

function StatusBadge({ status }: { status: SimulationJobDto['status'] }) {
  return <span className={`simulation-status simulation-status--${status}`}>{status}</span>
}

function Notice({
  level,
  message,
  onClose,
}: {
  level: string
  message: string
  onClose(): void
}) {
  return (
    <div className={`simulation-notice simulation-notice--${level}`} role="status" aria-live="polite">
      <span>{message}</span>
      <button type="button" className="simulation-icon-button" onClick={onClose} aria-label="Dismiss notification">×</button>
    </div>
  )
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="simulation-empty">
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  )
}

function RunHistory({
  jobs,
  results,
  selectedResultId,
  resultLoading,
  onSelectResult,
}: {
  jobs: SimulationJobDto[]
  results: SimulationResultSummaryDto[]
  selectedResultId: string | null
  resultLoading: boolean
  onSelectResult(result: SimulationResultSummaryDto): void
}) {
  const orderedJobs = useMemo(
    () => [...jobs].sort((left, right) => right.submitted_at.localeCompare(left.submitted_at)),
    [jobs],
  )
  const orderedResults = useMemo(
    () => [...results].sort((left, right) => right.timestamp.localeCompare(left.timestamp)),
    [results],
  )
  return (
    <div className="simulation-history-grid">
      <section className="simulation-card">
        <div className="simulation-card__header">
          <div>
            <h2>Jobs</h2>
            <p>Project-scoped execution lifecycle</p>
          </div>
          <span className="simulation-count">{orderedJobs.length}</span>
        </div>
        <div className="simulation-list">
          {orderedJobs.length ? orderedJobs.map((job) => (
            <article className="simulation-job-row" key={job.job_id}>
              <div className="simulation-row__primary">
                <span className="simulation-mono simulation-ellipsis" title={job.circuit_file}>{job.circuit_file}</span>
                <StatusBadge status={job.status} />
              </div>
              <div className="simulation-row__meta">
                <span title={job.job_id}>Job {job.job_id.slice(0, 10)} · {job.origin === 'ui_editor' ? 'Editor' : 'Agent'}</span>
                <span>{formatDate(job.submitted_at)}</span>
              </div>
              {job.error_message ? <div className="simulation-row__error">{job.error_message}</div> : null}
            </article>
          )) : <EmptyState title="No jobs" detail="Run the active circuit to create one." />}
        </div>
      </section>

      <section className="simulation-card">
        <div className="simulation-card__header">
          <div>
            <h2>Results</h2>
            <p>Immutable simulation history</p>
          </div>
          <span className="simulation-count">{orderedResults.length}</span>
        </div>
        <div className="simulation-list">
          {orderedResults.length ? orderedResults.map((result) => (
            <button
              type="button"
              key={result.result_id}
              className={`simulation-result-row${selectedResultId === result.result_id ? ' simulation-result-row--selected' : ''}`}
              disabled={resultLoading}
              onClick={() => onSelectResult(result)}
            >
              <span className="simulation-row__primary">
                <span className="simulation-mono simulation-ellipsis" title={result.circuit_file}>{result.circuit_file}</span>
                <span className={`simulation-result-outcome simulation-result-outcome--${result.success ? 'success' : 'error'}`}>
                  {result.success ? 'success' : 'failed'}
                </span>
              </span>
              <span className="simulation-row__meta">
                <span>{displayAnalysisType(result.analysis_type)}</span>
                <span>{formatDate(result.timestamp)}</span>
              </span>
              <span className="simulation-row__identity" title={result.result_id}>Result {result.result_id.slice(0, 12)}</span>
            </button>
          )) : <EmptyState title="No results" detail="Completed and failed result bundles appear here." />}
        </div>
      </section>
    </div>
  )
}

function MetricsPanel({ view }: { view: ResultViewModel }) {
  const noiseTotals = buildNoiseTotalRows(view)
  return (
    <div className="simulation-panel-stack">
      {noiseTotals.length ? (
        <section className="simulation-card">
          <div className="simulation-card__header">
            <div>
              <h2>Integrated noise</h2>
              <p>RMS integrated only across this .noise sweep range; density curves remain separate.</p>
            </div>
          </div>
          <div className="simulation-stat-grid">
            {noiseTotals.map((row) => (
              <div className="simulation-stat" key={row.label}>
                <span>{row.label}</span>
                <strong>{formatEngineering(row.value, row.unit)}</strong>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      <section className="simulation-card simulation-card--fill">
        <div className="simulation-card__header">
          <div>
            <h2>Measurements</h2>
            <p>Source .measure statements, including failed and parse-error outcomes</p>
          </div>
          <span className="simulation-count">{view.metrics.length}</span>
        </div>
        {view.metrics.length ? (
          <div className="simulation-table-wrap">
            <table className="simulation-table">
              <thead><tr><th>Name</th><th>Value</th><th>Status</th><th>Statement / error</th></tr></thead>
              <tbody>
                {view.metrics.map((metric, index) => (
                  <tr key={`${metric.name}-${index}`}>
                    <td className="simulation-mono">{metric.name}</td>
                    <td className="simulation-mono">{formatEngineering(metric.value)}</td>
                    <td><span className={`simulation-metric-status simulation-metric-status--${metric.status.toLowerCase()}`}>{metric.status.replace('_', ' ')}</span></td>
                    <td className="simulation-detail-cell">{metric.error_message || metric.statement || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="No .measure results" detail="This result contains no source measurements." />}
      </section>
    </div>
  )
}

interface CursorReadout {
  id: string
  label: string
  unit: string
  a: number | null
  b: number | null
}

function buildCursorReadouts(
  model: PlotModel,
  visibleSeriesIds: ReadonlySet<string>,
  cursorA: number | null,
  cursorB: number | null,
): CursorReadout[] {
  return model.series.filter((series) => visibleSeriesIds.has(series.id)).map((series) => {
    const indexA = cursorA === null ? null : nearestSampleIndex(series.x, cursorA)
    const indexB = cursorB === null ? null : nearestSampleIndex(series.x, cursorB)
    return {
      id: series.id,
      label: series.label,
      unit: series.unit,
      a: indexA === null ? null : (series.y[indexA] ?? null),
      b: indexB === null ? null : (series.y[indexB] ?? null),
    }
  })
}

function PlotPanel({
  view,
  mode,
  visibleSeriesIds,
  onToggleSeries,
  cursorA,
  cursorB,
  cursorTarget,
  onCursorTarget,
  onCursorChange,
}: {
  view: ResultViewModel
  mode: 'chart' | 'waveform'
  visibleSeriesIds: ReadonlySet<string>
  onToggleSeries(id: string): void
  cursorA: number | null
  cursorB: number | null
  cursorTarget: 'a' | 'b'
  onCursorTarget(cursor: 'a' | 'b'): void
  onCursorChange(cursor: 'a' | 'b', value: number): void
}) {
  const model = view.plot
  if (!model) return <EmptyState title="No plotted sweep" detail="Operating-point results are shown as scalar values." />
  const readouts = buildCursorReadouts(model, visibleSeriesIds, cursorA, cursorB)
  return (
    <div className={`simulation-plot-layout simulation-plot-layout--${mode}`}>
      <aside className="simulation-series-rail">
        <div className="simulation-series-rail__header">
          <strong>{mode === 'waveform' ? 'Signals' : 'Series'}</strong>
          <span>{visibleSeriesIds.size}/{model.series.length}</span>
        </div>
        <div className="simulation-series-list">
          {model.series.map((series) => (
            <label className="simulation-series-row" key={series.id}>
              <input
                type="checkbox"
                checked={visibleSeriesIds.has(series.id)}
                onChange={() => onToggleSeries(series.id)}
              />
              <span className="simulation-series-swatch" style={{ backgroundColor: series.color }} />
              <span className="simulation-series-name" title={series.label}>{series.label}</span>
              <span className="simulation-series-unit">{series.unit}</span>
            </label>
          ))}
        </div>
      </aside>
      <section className="simulation-chart-card">
        <div className="simulation-chart-toolbar">
          <div>
            <strong>{model.title}</strong>
            <span>{model.logX ? 'log X' : 'linear X'}{model.logLeftY ? ' · log Y' : ''}</span>
          </div>
          <div className="simulation-cursor-toggle" aria-label="Active measurement cursor">
            <button type="button" className={cursorTarget === 'a' ? 'is-active' : ''} onClick={() => onCursorTarget('a')}>Cursor A</button>
            <button type="button" className={cursorTarget === 'b' ? 'is-active' : ''} onClick={() => onCursorTarget('b')}>Cursor B</button>
          </div>
        </div>
        <SeriesChart
          model={model}
          identity={view.identity}
          visibleSeriesIds={visibleSeriesIds}
          cursorA={cursorA}
          cursorB={cursorB}
          cursorTarget={cursorTarget}
          onCursorChange={onCursorChange}
        />
        <div className="simulation-measurement-strip">
          <div className="simulation-measurement-axis">
            <span>A: {formatEngineering(cursorA, model.xUnit)}</span>
            <span>B: {formatEngineering(cursorB, model.xUnit)}</span>
            <strong>ΔX: {formatEngineering(cursorA === null || cursorB === null ? null : cursorB - cursorA, model.xUnit)}</strong>
          </div>
          <div className="simulation-measurement-values">
            {readouts.map((row) => (
              <div key={row.id}>
                <span title={row.label}>{row.label}</span>
                <code>{formatEngineering(row.a, row.unit)}</code>
                <code>{formatEngineering(row.b, row.unit)}</code>
                <strong>{formatEngineering(row.a === null || row.b === null ? null : row.b - row.a, row.unit)}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}

function SchematicIssues({ schematic }: { schematic: SchematicDocumentDto }) {
  if (!schematic.parse_errors.length) return null
  return (
    <div className="simulation-inline-error">
      <strong>{schematic.parse_errors.length} schematic parse issue(s)</strong>
      <span>{schematic.parse_errors.map((error) => {
        const location = error.line_index >= 0
          ? `${error.source_file}:${error.line_index + 1}`
          : error.source_file
        return `${location ? `${location} ` : ''}${error.message}`
      }).join('\n')}</span>
    </div>
  )
}

function SchematicPanel({ schematic }: { schematic: SchematicDocumentDto | null }) {
  const layout = useMemo(() => schematic ? buildSchematicLayout(schematic) : null, [schematic])
  if (!schematic) {
    return (
      <EmptyState
        title="No result-bound schematic snapshot"
        detail="This API result does not contain an immutable schematic document. The current editor file is not substituted because it may differ from the simulated source closure."
      />
    )
  }
  if (!layout || !schematic.has_schematic) {
    return (
      <div className="simulation-panel-stack">
        <EmptyState title="No drawable schematic components" detail="The verified semantic document contains no drawable components." />
        <SchematicIssues schematic={schematic} />
      </div>
    )
  }
  return (
    <section className="simulation-card simulation-card--schematic">
      <div className="simulation-card__header">
        <div><h2>{schematic.title || 'Schematic snapshot'}</h2><p>Deterministic React layout of result-bound SPICE semantics · read only</p></div>
        <span className="simulation-count">{schematic.components.length}</span>
      </div>
      <div className="simulation-schematic-frame">
        <svg viewBox={`${layout.viewBox.x} ${layout.viewBox.y} ${layout.viewBox.width} ${layout.viewBox.height}`} role="img" aria-label={schematic.title || 'Schematic snapshot'}>
          {layout.nets.map((net) => (
            <g key={net.id}>
              {net.paths.map((path, index) => <path key={index} d={path} className="simulation-schematic__net" />)}
              <circle cx={net.hub.x} cy={net.hub.y} r={2.7} className="simulation-schematic__junction" />
              <text x={net.hub.x + 5} y={net.hub.y - 5} className="simulation-schematic__net-label">{net.name}</text>
            </g>
          ))}
          {layout.components.map((item) => (
            <g key={item.component.id} data-symbol-kind={item.component.symbol_kind}>
              <rect x={item.x - item.width / 2} y={item.y - item.height / 2} width={item.width} height={item.height} rx={4} className="simulation-schematic__component" />
              <text x={item.x} y={item.y - 7} textAnchor="middle" className="simulation-schematic__reference">{item.component.instance_name}</text>
              <text x={item.x} y={item.y + 10} textAnchor="middle" className="simulation-schematic__value">{item.component.display_value || item.component.display_name || item.component.kind}</text>
              {item.pins.map((pin) => (
                <g key={pin.pin.name}>
                  <circle cx={pin.x} cy={pin.y} r={3} className="simulation-schematic__pin" />
                  <text
                    x={pin.x + (pin.side === 'left' ? 6 : pin.side === 'right' ? -6 : 0)}
                    y={pin.y + (pin.side === 'top' ? 11 : pin.side === 'bottom' ? -6 : 3)}
                    textAnchor={pin.side === 'left' ? 'start' : pin.side === 'right' ? 'end' : 'middle'}
                    className="simulation-schematic__pin-label"
                  >{pin.pin.name}</text>
                </g>
              ))}
            </g>
          ))}
        </svg>
      </div>
      <SchematicIssues schematic={schematic} />
    </section>
  )
}

function AnalysisPanel({ view }: { view: ResultViewModel }) {
  const noiseTotals = buildNoiseTotalRows(view)
  const rows = [
    ['Analysis', displayAnalysisType(view.result.analysis_type)],
    ['Command', view.result.analysis_command || '—'],
    ['Executor', view.result.executor],
    ['Circuit at run time', view.result.file_path],
    ['Timestamp', formatDate(view.result.timestamp)],
    ['Duration', formatEngineering(view.result.duration_seconds, 's')],
    ['Schema', String(view.result.schema_version)],
    ['Source closure digest', view.result.source_digest ?? 'Not available for failed result'],
    ['Result identity', view.identity.resultId],
    ['Job identity', view.identity.jobId ?? 'Historical result (no active job)'],
    ...noiseTotals.map((item) => [item.label, formatEngineering(item.value, item.unit)]),
  ]
  return (
    <section className="simulation-card simulation-card--fill">
      <div className="simulation-card__header"><div><h2>Analysis information</h2><p>Persisted provenance, not the current editor state</p></div></div>
      <dl className="simulation-detail-grid">
        {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd className={label.includes('identity') || label === 'Command' || label.includes('digest') ? 'simulation-mono' : ''}>{value}</dd></div>)}
      </dl>
      {view.result.error ? <div className="simulation-inline-error"><strong>{view.result.error.code} · {view.result.error.severity}</strong><span>{view.result.error.message}{view.result.error.recovery_suggestion ? ` ${view.result.error.recovery_suggestion}` : ''}</span></div> : null}
    </section>
  )
}

function OpPanel({ view }: { view: ResultViewModel }) {
  return (
    <section className="simulation-card simulation-card--fill">
      <div className="simulation-card__header"><div><h2>Operating point</h2><p>Scalar node voltages and branch currents</p></div><span className="simulation-count">{view.opRows.length}</span></div>
      {view.opRows.length ? (
        <div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Signal</th><th>Value</th></tr></thead><tbody>
          {view.opRows.map((row) => <tr key={row.signal}><td className="simulation-mono">{row.signal}</td><td className="simulation-mono">{formatEngineering(row.value, row.unit)}</td></tr>)}
        </tbody></table></div>
      ) : <EmptyState title="No operating-point values" detail="The persisted result contains no scalar signals." />}
    </section>
  )
}

function RawDataPanel({ view }: { view: ResultViewModel }) {
  const columns = useMemo(() => buildRawColumns(view), [view])
  const noiseTotals = buildNoiseTotalRows(view)
  const [page, setPage] = useState(0)
  useEffect(() => setPage(0), [view.identity.resultId])
  const rowCount = columns.reduce((maximum, column) => Math.max(maximum, column.values.length), 0)
  const pageCount = Math.max(1, Math.ceil(rowCount / PAGE_SIZE))
  const start = Math.min(page, pageCount - 1) * PAGE_SIZE
  const end = Math.min(rowCount, start + PAGE_SIZE)
  if (!columns.length) return <EmptyState title="No raw data" detail="This result has no canonical signal arrays." />
  return (
    <section className="simulation-card simulation-card--fill">
      <div className="simulation-card__header">
        <div><h2>Raw result data</h2><p>{rowCount.toLocaleString()} samples · {columns.length} columns</p></div>
        <div className="simulation-pagination">
          <button type="button" disabled={page <= 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button>
          <span>{start + 1}–{end}</span>
          <button type="button" disabled={end >= rowCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>Next</button>
        </div>
      </div>
      {noiseTotals.length ? (
        <div className="simulation-raw-scalars" aria-label="Integrated noise scalars">
          {noiseTotals.map((row) => <span key={row.label}><small>{row.label}</small><strong>{formatEngineering(row.value, row.unit)}</strong></span>)}
          <em>Integrated across the .noise sweep range; not an extra frequency sample.</em>
        </div>
      ) : null}
      <div className="simulation-table-wrap simulation-table-wrap--raw">
        <table className="simulation-table simulation-table--raw">
          <thead><tr><th>#</th>{columns.map((column) => <th key={column.id}>{column.label}{column.unit ? <small>{column.unit}</small> : null}</th>)}</tr></thead>
          <tbody>{Array.from({ length: Math.max(0, end - start) }, (_, offset) => start + offset).map((row) => (
            <tr key={row}><td>{row}</td>{columns.map((column) => <td className="simulation-mono" key={column.id}>{formatEngineering(column.values[row] ?? null)}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  )
}

function OutputLogPanel({ view }: { view: ResultViewModel }) {
  const [query, setQuery] = useState('')
  const [level, setLevel] = useState<'all' | 'error' | 'warning'>('all')
  const [page, setPage] = useState(0)
  useEffect(() => { setQuery(''); setLevel('all'); setPage(0) }, [view.identity.resultId])
  const lines = useMemo(() => view.outputLog.split(/\r?\n/).map((text, index) => ({ number: index + 1, text })), [view.outputLog])
  const filtered = useMemo(() => lines.filter((line) => {
    const normalized = line.text.toLowerCase()
    if (level === 'error' && !/error|fatal|failed/.test(normalized)) return false
    if (level === 'warning' && !/warn|caution/.test(normalized)) return false
    return !query || normalized.includes(query.toLowerCase())
  }), [level, lines, query])
  useEffect(() => setPage(0), [level, query])
  const pageCount = Math.max(1, Math.ceil(filtered.length / LOG_PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const visibleLines = filtered.slice(safePage * LOG_PAGE_SIZE, (safePage + 1) * LOG_PAGE_SIZE)
  return (
    <section className="simulation-card simulation-card--fill">
      <div className="simulation-log-toolbar">
        <div><strong>Simulator output</strong><span>{filtered.length}/{lines.length} lines</span></div>
        <select value={level} onChange={(event) => setLevel(event.target.value as typeof level)} aria-label="Log severity filter"><option value="all">All lines</option><option value="error">Errors</option><option value="warning">Warnings</option></select>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search output" aria-label="Search simulator output" />
        <div className="simulation-log-pagination">
          <button type="button" disabled={safePage <= 0} onClick={() => setPage((value) => Math.max(0, value - 1))} aria-label="Previous log page">‹</button>
          <span>{filtered.length ? `${safePage + 1}/${pageCount}` : '0/0'}</span>
          <button type="button" disabled={safePage >= pageCount - 1} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))} aria-label="Next log page">›</button>
        </div>
        <button type="button" disabled={!visibleLines.length} onClick={() => void navigator.clipboard.writeText(visibleLines.map((line) => line.text).join('\n'))}>Copy page</button>
      </div>
      {view.outputLog ? <div className="simulation-log" role="log">{visibleLines.map((line) => <div key={line.number}><span>{line.number}</span><code>{line.text || ' '}</code></div>)}</div> : <EmptyState title="No simulator output" detail="The exact result contains an empty output log." />}
    </section>
  )
}

function ExportPanel({
  view,
  visibleSeriesIds,
  busy,
  onCanonicalJson,
  onDelete,
}: {
  view: ResultViewModel
  visibleSeriesIds: ReadonlySet<string>
  busy: boolean
  onCanonicalJson(): Promise<void>
  onDelete(): Promise<void>
}) {
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  useEffect(() => { setError(null); setConfirmDelete(false) }, [view.identity.resultId])
  const execute = (action: () => void) => {
    try {
      setError(null)
      action()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Export failed.')
    }
  }
  return (
    <div className="simulation-panel-stack">
      <section className="simulation-card">
        <div className="simulation-card__header"><div><h2>Bound export identity</h2><p>Every export below is tied to this immutable result.</p></div></div>
        <div className="simulation-identity-grid">
          <div><span>Project</span><code>{view.identity.projectId}</code></div>
          <div><span>Job</span><code>{view.identity.jobId ?? 'historical / none'}</code></div>
          <div><span>Result</span><code>{view.identity.resultId}</code></div>
        </div>
      </section>
      <section className="simulation-card simulation-card--fill">
        <div className="simulation-card__header"><div><h2>Export result</h2><p>CSV and SVG use the same visible series arrays as this screen.</p></div></div>
        <div className="simulation-export-grid">
          <button type="button" className="simulation-export-option" disabled={busy || (!view.plot && !view.opRows.length)} onClick={() => execute(() => downloadContent(resultFileName(view, 'csv', 'data'), 'text/csv;charset=utf-8', buildPlotCsv(view, visibleSeriesIds)))}>
            <strong>Visible data CSV</strong><span>Current series selection, full sample precision</span>
          </button>
          <button type="button" className="simulation-export-option" disabled={busy || !view.plot || !visibleSeriesIds.size} onClick={() => execute(() => downloadContent(resultFileName(view, 'svg', 'chart'), 'image/svg+xml;charset=utf-8', buildPlotSvg(view.plot as PlotModel, view.identity, visibleSeriesIds)))}>
            <strong>Visible chart SVG</strong><span>Pure vector rendering with embedded identity</span>
          </button>
          <button type="button" className="simulation-export-option" disabled={busy} onClick={() => void onCanonicalJson()}>
            <strong>Canonical result-data JSON</strong><span>Backend-authoritative axes, signals, and noise totals</span>
          </button>
        </div>
        {error ? <div className="simulation-inline-error">{error}</div> : null}
      </section>
      <section className="simulation-card simulation-danger-zone">
        <div><strong>Delete this result</strong><span>This removes only result {view.identity.resultId} from the current project.</span></div>
        {confirmDelete ? (
          <div className="simulation-confirm-actions">
            <button type="button" onClick={() => setConfirmDelete(false)}>Keep result</button>
            <button type="button" className="simulation-button--danger" disabled={busy} onClick={() => void onDelete()}>Delete permanently</button>
          </div>
        ) : <button type="button" className="simulation-button--danger-ghost" onClick={() => setConfirmDelete(true)}>Delete result…</button>}
      </section>
    </div>
  )
}

export function SimulationFeature(props: SimulationFeatureProps) {
  const controller = useSimulationController(props)
  const activeDocumentIsCircuit = isSupportedCircuitPath(props.activeDocumentPath)
  const [activeTab, setActiveTab] = useState<SimulationTabId>('runs')
  const [visibleSeriesIds, setVisibleSeriesIds] = useState<Set<string>>(new Set())
  const [cursorA, setCursorA] = useState<number | null>(null)
  const [cursorB, setCursorB] = useState<number | null>(null)
  const [cursorTarget, setCursorTarget] = useState<'a' | 'b'>('a')
  const selectedId = controller.selected?.identity.resultId ?? null

  useEffect(() => {
    const plot = controller.selected?.plot
    setVisibleSeriesIds(new Set(plot?.series.map((series) => series.id) ?? []))
    if (plot?.series[0]) {
      const finiteX = plot.series[0].x.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
      setCursorA(finiteX.length ? finiteX[Math.floor((finiteX.length - 1) * 0.25)] : null)
      setCursorB(finiteX.length ? finiteX[Math.floor((finiteX.length - 1) * 0.75)] : null)
    } else {
      setCursorA(null)
      setCursorB(null)
    }
    setCursorTarget('a')
    if (controller.selected) {
      setActiveTab(
        !controller.selected.result.success
          ? (controller.selected.outputLog ? 'log' : 'analysis')
          : controller.selected.result.analysis_type === 'op'
            ? 'analysis'
            : 'metrics',
      )
    }
  }, [controller.selected])

  const availableTabs = useMemo<SimulationTabId[]>(() => {
    if (!controller.selected) return ['runs']
    const tabs: SimulationTabId[] = ['runs', 'metrics']
    if (controller.selected.plot) tabs.push('chart', 'waveform')
    tabs.push('schematic', 'analysis', 'raw', 'log', 'export')
    return tabs
  }, [controller.selected])

  useEffect(() => {
    if (!availableTabs.includes(activeTab)) setActiveTab(availableTabs[0])
  }, [activeTab, availableTabs])

  const toggleSeries = (id: string) => setVisibleSeriesIds((current) => {
    const next = new Set(current)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const runStatus = controller.activeJob
    ? controller.activeJob.status
    : controller.blockingJob
      ? controller.blockingJob.status
    : controller.selected
      ? (controller.selected.result.success ? 'completed' : 'failed')
      : 'idle'

  const exportCanonicalJson = async () => {
    const exported = await controller.exportCanonicalJson()
    if (exported) downloadBlob(exported.metadata.file_name, exported.blob)
  }

  let content
  if (!props.projectId) {
    content = <EmptyState title="Open a project" detail="Simulation history and execution are strictly project-scoped." />
  } else if (controller.resultLoading) {
    content = <EmptyState title="Loading exact result" detail="Result and surface identities are being verified." />
  } else if (activeTab === 'runs' || !controller.selected) {
    content = (
      <RunHistory
        jobs={controller.jobs}
        results={controller.results}
        selectedResultId={selectedId}
        resultLoading={controller.resultLoading}
        onSelectResult={(result) => {
          setActiveTab('metrics')
          void controller.selectResult(result.result_id, result.job_id)
        }}
      />
    )
  } else if (activeTab === 'metrics') {
    content = controller.selected.result.analysis_type === 'op'
      ? <div className="simulation-panel-stack"><OpPanel view={controller.selected} /><MetricsPanel view={controller.selected} /></div>
      : <MetricsPanel view={controller.selected} />
  } else if (activeTab === 'chart' || activeTab === 'waveform') {
    content = (
      <PlotPanel
        view={controller.selected}
        mode={activeTab}
        visibleSeriesIds={visibleSeriesIds}
        onToggleSeries={toggleSeries}
        cursorA={cursorA}
        cursorB={cursorB}
        cursorTarget={cursorTarget}
        onCursorTarget={setCursorTarget}
        onCursorChange={(cursor, value) => cursor === 'a' ? setCursorA(value) : setCursorB(value)}
      />
    )
  } else if (activeTab === 'schematic') {
    content = <SchematicPanel schematic={controller.selected.schematic} />
  } else if (activeTab === 'analysis') {
    content = controller.selected.result.analysis_type === 'op'
      ? <div className="simulation-panel-stack"><OpPanel view={controller.selected} /><AnalysisPanel view={controller.selected} /></div>
      : <AnalysisPanel view={controller.selected} />
  } else if (activeTab === 'raw') {
    content = <RawDataPanel view={controller.selected} />
  } else if (activeTab === 'log') {
    content = <OutputLogPanel view={controller.selected} />
  } else {
    content = (
      <ExportPanel
        view={controller.selected}
        visibleSeriesIds={visibleSeriesIds}
        busy={controller.busyAction !== null}
        onCanonicalJson={exportCanonicalJson}
        onDelete={controller.deleteSelected}
      />
    )
  }

  return (
    <section className="simulation-feature" hidden={!props.active} aria-label="Circuit simulation">
      <header className="simulation-header">
        <div className="simulation-header__identity">
          <span className="simulation-eyebrow">Circuit simulation</span>
          <div className="simulation-header__title-row">
            <h1>{fileName(props.activeDocumentPath)}</h1>
            <span className={`simulation-runtime-status simulation-runtime-status--${runStatus}`}>{runStatus}</span>
          </div>
          <span className="simulation-header__path simulation-mono" title={props.activeDocumentPath ?? undefined}>{props.activeDocumentPath ?? 'Select a SPICE circuit to run.'}</span>
          {props.activeDocumentPath ? (
            <span className={`simulation-header__run-source${activeDocumentIsCircuit ? '' : ' simulation-header__run-source--error'}`}>
              {controller.activeJob
                ? `Tracking editor job for ${controller.activeJob.circuit_file}; new runs wait for its exact terminal state.`
                : activeDocumentIsCircuit
                  ? controller.blockingJob
                    ? `An ${controller.blockingJob.origin === 'agent_tool' ? 'agent' : 'editor'} job already runs this circuit; it is observed read-only and a duplicate run is blocked.`
                    : 'Runs the saved project file; save editor changes before starting.'
                  : 'Choose a supported SPICE netlist (.cir, .sp, .spice, .net, or .ckt) before running.'}
            </span>
          ) : null}
        </div>
        <div className="simulation-header__actions">
          <button type="button" className="simulation-button simulation-button--secondary" disabled={!props.projectId || controller.loading} onClick={() => void controller.refresh()}>{controller.loading ? 'Refreshing…' : 'Refresh'}</button>
          {controller.activeJob ? (
            <button type="button" className="simulation-button simulation-button--danger-ghost" disabled={controller.activeJob.cancel_requested || controller.busyAction !== null} onClick={() => void controller.cancel()}>{controller.activeJob.cancel_requested ? 'Cancelling…' : 'Cancel'}</button>
          ) : null}
          <button type="button" className="simulation-button simulation-button--primary" title={!activeDocumentIsCircuit ? 'Select a supported SPICE netlist first' : controller.blockingJob ? 'A project job for this circuit is already active' : 'Run the saved project file'} disabled={!controller.canRun} onClick={() => void controller.run()}>{controller.busyAction === 'run' ? 'Starting…' : 'Run simulation'}</button>
        </div>
      </header>

      {controller.notice ? <Notice level={controller.notice.level} message={controller.notice.message} onClose={controller.clearNotice} /> : null}

      <nav className="simulation-tabs" aria-label="Simulation result sections">
        {availableTabs.map((tab) => (
          <button key={tab} type="button" className={activeTab === tab ? 'is-active' : ''} aria-current={activeTab === tab ? 'page' : undefined} onClick={() => setActiveTab(tab)}>{TAB_LABELS[tab]}</button>
        ))}
        {controller.selected ? (
          <span className="simulation-tabs__result" title={controller.selected.identity.resultId}>
            {displayAnalysisType(controller.selected.result.analysis_type)} · {controller.selected.identity.resultId.slice(0, 10)}
          </span>
        ) : null}
      </nav>

      <main className="simulation-content">{content}</main>
    </section>
  )
}
