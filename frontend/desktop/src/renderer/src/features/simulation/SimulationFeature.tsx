import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getWorkSession, sameProjectRoot, updateSimulationSession, type SimulationSession } from '../../lib/workSession'
import { buildPlotSvg, SeriesChart } from './SeriesChart'
import { TopologyInspector } from './TopologyInspector'
import { RunProvenance } from './RunProvenance'
import { OutputPanel } from './SimulationOutput'
import { downloadBlob, downloadContent } from './exportUtils'
import { buildResultViewModel, compatibleCatalogs, experimentFromForm, formFromExperiment, formatEngineering, supportedTraces, tracesForSelectedResult, traceKey, type ExperimentForm } from './simulationModel'
import { exportTraceCsv, fetchExperimentInputs, fetchWorkbench, queryTraceMeasurements, queryTraceTable, queryTraces } from './simulationApi'
import { useSimulationController } from './useSimulationController'
import type { ResultViewModel, SimulationFeatureProps, SimulationResultSummaryDto, SimulationTabId, TraceCatalog, TraceComponent, TraceMeasurements, TraceQuery, TraceSpec, TraceTable } from './types'
import './styles.css'

const TABS: Array<[SimulationTabId, string]> = [['experiment', 'Experiment'], ['waveforms', 'Waveforms'], ['measurements', 'Measurements'], ['topology', 'Topology'], ['raw', 'Raw samples'], ['log', 'Output']]
const COMPONENT_LABELS: Record<TraceComponent, string> = {real: 'Real', imaginary: 'Imaginary', magnitude: 'Magnitude', db: 'Decibels', phase: 'Unwrapped phase'}
const COLORS = ['#4f7cff', '#ec795d', '#34b6a3', '#b58bff', '#dfae47', '#6bb8e8']
const PAGE_SIZE = 100
const shortId = (id: string) => id.slice(0, 10)
const errorText = (error: unknown) => error instanceof Error ? error.message : 'The operation failed.'
const dateText = (value: string) => new Date(value).toLocaleString()

function Empty({children}: {children: React.ReactNode}) { return <div className="simulation-empty">{children}</div> }
function ErrorMessage({message}: {message: string | null}) { return message ? <div className="simulation-inline-error" role="alert">{message}</div> : null }

function TraceEditor({catalog, traces, onChange}: {catalog: TraceCatalog; traces: TraceSpec[]; onChange(value: TraceSpec[]): void}) {
  const update = (index: number, patch: Partial<TraceSpec>) => onChange(traces.map((item, position) => position === index ? {...item, ...patch} : item))
  return <section className="simulation-trace-editor" aria-label="Trace definitions">
    <div className="simulation-section-heading"><strong>Traces</strong><button type="button" disabled={!catalog.signals.length || traces.length >= 16} onClick={() => {
      const signal = catalog.signals.find((item) => !traces.some((trace) => trace.signal === item.name)) ?? catalog.signals[0]
      onChange([...traces, {signal: signal.name, component: signal.is_complex ? 'magnitude' : 'real'}])
    }}>+ Add trace</button></div>
    {traces.map((trace, index) => {
      const signal = catalog.signals.find((item) => item.name === trace.signal)
      return <div className="simulation-trace-row" key={index}>
        <span className="simulation-series-swatch" style={{backgroundColor: COLORS[index % COLORS.length]}} />
        <select aria-label={`Trace ${index + 1} signal`} value={trace.signal} onChange={(event) => {
          const next = catalog.signals.find((item) => item.name === event.target.value)
          update(index, {signal: event.target.value, reference: null, component: next?.is_complex ? 'magnitude' : 'real'})
        }}>{catalog.signals.map((item) => <option key={item.name} value={item.name}>{item.name} [{item.unit || '1'}]</option>)}</select>
        <select aria-label={`Trace ${index + 1} component`} value={trace.component} onChange={(event) => {
          const component = event.target.value as TraceComponent
          const reference = catalog.signals.find((item) => item.name === trace.reference)
          update(index, {component, ...(component === 'db' && reference?.unit !== signal?.unit ? {reference: null} : {})})
        }}>{signal?.components.map((component) => <option value={component} key={component}>{COMPONENT_LABELS[component]}</option>)}</select>
        <select aria-label={`Trace ${index + 1} reference`} value={trace.reference ?? ''} onChange={(event) => update(index, {reference: event.target.value || null})}>
          <option value="">Absolute signal</option>
          {catalog.signals.filter((item) => item.unit && signal?.unit && (trace.component !== 'db' || item.unit === signal.unit) && item.name !== signal.name).map((item) => <option key={item.name} value={item.name}>÷ {item.name} [{item.unit}]</option>)}
        </select>
        <button type="button" aria-label={`Remove trace ${index + 1}`} onClick={() => onChange(traces.filter((_, position) => position !== index))}>×</button>
      </div>
    })}
    <small>V/I gives impedance; I/V gives admittance. Decibels use dBV/dBA for absolute signals and require a reference with the same unit for a transfer ratio.</small>
  </section>
}

function ExperimentPanel({form, onChange, view, onReuse, onReplay, onInputs, disabled}: {
  form: ExperimentForm; onChange(value: ExperimentForm): void; view: ResultViewModel | null
  onReuse(): void; onReplay(): void; onInputs(): void; disabled: boolean
}) {
  const field = (name: keyof ExperimentForm, value: string) => onChange({...form, [name]: value})
  return <div className="simulation-panel-stack">
    <section className="simulation-card">
      <div className="simulation-card__header"><div><h2>Experiment configuration</h2><p>Run a saved circuit with explicit analysis and overrides. The run retains its own inputs.</p></div></div>
      <div className="simulation-experiment-grid">
        <label className="simulation-field simulation-field--wide"><span>Analysis command <small>blank uses the circuit's analysis</small></span><input value={form.analysis} onChange={(event) => field('analysis', event.target.value)} placeholder=".tran 1u 10m · .ac dec 100 10 1Meg · .op" /></label>
        <label className="simulation-field"><span>Parameter overrides <small>one name=value per line</small></span><textarea rows={4} value={form.parameters} onChange={(event) => field('parameters', event.target.value)} placeholder={'Rload=10k\nCfilter=100n'} /></label>
        <label className="simulation-field"><span>Solver options <small>one name=value per line</small></span><textarea rows={4} value={form.solver} onChange={(event) => field('solver', event.target.value)} placeholder={'reltol=1e-4\nmethod=gear'} /></label>
        <label className="simulation-field"><span>Temperature (°C)</span><input type="number" value={form.temperature} onChange={(event) => field('temperature', event.target.value)} placeholder="Use circuit default" /></label>
        <label className="simulation-field"><span>Timeout (seconds)</span><input type="number" min="1" step="1" value={form.timeout} onChange={(event) => field('timeout', event.target.value)} /></label>
      </div>
    </section>
    {view ? <section className="simulation-card">
      <div className="simulation-card__header"><div><h2>Selected run</h2><p>{view.result.analysis_command || view.result.analysis_type.toUpperCase()} · {dateText(view.result.timestamp)}</p></div><span className={`simulation-result-outcome simulation-result-outcome--${view.result.success ? 'success' : 'error'}`}>{view.result.success ? 'Completed' : 'Failed'}</span></div>
      <dl className="simulation-detail-grid">
        <div><dt>Circuit</dt><dd>{view.result.file_path}</dd></div><div><dt>Duration</dt><dd>{formatEngineering(view.result.duration_seconds, 's')}</dd></div>
        <div><dt>Result</dt><dd><code>{view.identity.resultId}</code></dd></div><div><dt>Input snapshot</dt><dd>{view.provenance.available ? view.provenance.execution_inputs_available === false ? 'Submitted inputs; worker did not return execution inputs' : `${view.provenance.files.length} execution input files` : 'Unavailable for this historical result'}</dd></div>
      </dl>
      <RunProvenance provenance={view.provenance} />
      <div className="simulation-button-row"><button type="button" disabled={!view.provenance.experiment} onClick={onReuse}>Use this configuration</button><button type="button" disabled={disabled || !view.provenance.available} onClick={onReplay}>Replay saved inputs</button><button type="button" disabled={disabled || !view.provenance.available} onClick={onInputs}>Download input bundle</button></div>
      {view.result.error ? <ErrorMessage message={`${view.result.error.code}: ${view.result.error.message}${view.result.error.recovery_suggestion ? ` ${view.result.error.recovery_suggestion}` : ''}`} /> : null}
    </section> : null}
  </div>
}

function RawTable({table, page, onPage}: {table: TraceTable | null; page: number; onPage(value: number): void}) {
  if (!table) return <Empty>Loading original samples…</Empty>
  return <section className="simulation-card simulation-card--fill">
    <div className="simulation-card__header"><div><h2>Original samples</h2><p>Full-resolution values for the selected traces. Display rounding does not affect CSV precision.</p></div><div className="simulation-button-row"><button type="button" disabled={!page} onClick={() => onPage(page - 1)}>Previous</button><span>{table.total_rows ? `${table.offset + 1}–${Math.min(table.offset + table.limit, table.total_rows)} / ${table.total_rows}` : '0 samples'}</span><button type="button" disabled={table.offset + table.limit >= table.total_rows} onClick={() => onPage(page + 1)}>Next</button></div></div>
    <div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Sample</th><th>Branch</th><th>{table.x_axis.label} {table.x_axis.unit ? `(${table.x_axis.unit})` : ''}</th>{table.columns.map((item) => <th key={item.id}>{item.label} ({item.unit || '1'})</th>)}</tr></thead><tbody>{table.rows.map((row) => <tr key={`${row.branch_id}-${row.index}`}><td>{row.index}</td><td>{row.branch_id}{row.outer_value === null ? '' : ` · ${formatEngineering(row.outer_value)}`}</td><td>{formatEngineering(row.x)}</td>{row.values.map((value, index) => <td key={index}>{formatEngineering(value)}</td>)}</tr>)}</tbody></table></div>
  </section>
}

function MeasurementTable({data, label}: {data: TraceMeasurements | null; label: string}) {
  if (!data) return null
  return <section className="simulation-card">
    <div className="simulation-card__header"><div><h2>{label}</h2><p>Measurements use original samples in the visible X range. Cursor interpolation stays within each sweep branch.</p></div></div>
    <div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Trace / branch</th><th>A: X / Y</th><th>B: X / Y</th><th>ΔX / ΔY</th><th>Min / Max</th><th>Peak-to-peak</th><th>Time mean / RMS</th><th>Samples</th></tr></thead><tbody>{data.measurements.map((row, index) => <tr key={index}>
      <td>{row.label}<small>Branch {row.branch_id}{row.outer_value == null ? '' : ` · ${formatEngineering(row.outer_value)}`}</small></td>
      <td>{row.cursor_a ? <>{formatEngineering(row.cursor_a.x, data.x_axis.unit)}<small>{formatEngineering(row.cursor_a.y, row.unit)}{row.cursor_a.interpolated ? ' (interpolated)' : ''}</small></> : '—'}</td>
      <td>{row.cursor_b ? <>{formatEngineering(row.cursor_b.x, data.x_axis.unit)}<small>{formatEngineering(row.cursor_b.y, row.unit)}{row.cursor_b.interpolated ? ' (interpolated)' : ''}</small></> : '—'}</td>
      <td>{formatEngineering(row.delta_x, data.x_axis.unit)}<small>{formatEngineering(row.delta_y, row.unit)}</small></td>
      <td>{formatEngineering(row.min, row.unit)}<small>{formatEngineering(row.max, row.unit)}</small></td><td>{formatEngineering(row.peak_to_peak, row.unit)}</td>
      <td title={row.statistics_basis}>{formatEngineering(row.time_mean, row.unit)}<small>{formatEngineering(row.time_rms, row.unit)}</small></td><td>{row.sample_count}</td>
    </tr>)}</tbody></table></div>
  </section>
}

function SourceMeasurements({view, baseline}: {view: ResultViewModel; baseline: ResultViewModel | null}) {
  return <section className="simulation-card"><div className="simulation-card__header"><div><h2>SPICE .measure results</h2><p>Source measurements retain failed and parse-error outcomes.</p></div></div>
    {view.metrics.length ? <div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Name</th><th>Current</th><th>Status</th>{baseline ? <><th>Baseline</th><th>Δ current − baseline</th></> : null}<th>Definition / error</th></tr></thead><tbody>{view.metrics.map((metric, index) => {
      const previous = baseline?.metrics.find((item) => item.name === metric.name && item.statement === metric.statement)
      return <tr key={index}><td>{metric.name}</td><td>{formatEngineering(metric.value)}</td><td className={metric.status === 'OK' ? '' : 'simulation-text-error'}>{metric.status}</td>{baseline ? <><td>{formatEngineering(previous?.value)}</td><td>{metric.status === 'OK' && previous?.status === 'OK' && metric.value !== null && previous.value !== null ? formatEngineering(metric.value - previous.value) : '—'}</td></> : null}<td><code>{metric.statement}</code>{metric.error_message ? <small className="simulation-text-error">{metric.error_message}</small> : null}</td></tr>
    })}</tbody></table></div> : <Empty>No source .measure statements were recorded.</Empty>}
  </section>
}

function Workbench(props: SimulationFeatureProps) {
  const controller = useSimulationController(props)
  const [tab, setTab] = useState<SimulationTabId>('experiment')
  const [form, setForm] = useState<ExperimentForm>(() => formFromExperiment({}))
  const [traces, setTraces] = useState<TraceSpec[]>([])
  const [traceResultId, setTraceResultId] = useState<string | null>(null)
  const [range, setRange] = useState<[number, number] | null>(null)
  const [cursorA, setCursorA] = useState<number | null>(null)
  const [cursorB, setCursorB] = useState<number | null>(null)
  const [cursorTarget, setCursorTarget] = useState<'a' | 'b'>('a')
  const [baseline, setBaseline] = useState<ResultViewModel | null>(null)
  const [baselineLoading, setBaselineLoading] = useState(false)
  const [query, setQuery] = useState<TraceQuery | null>(null)
  const [baselineQuery, setBaselineQuery] = useState<TraceQuery | null>(null)
  const [measurements, setMeasurements] = useState<TraceMeasurements | null>(null)
  const [baselineMeasurements, setBaselineMeasurements] = useState<TraceMeasurements | null>(null)
  const [table, setTable] = useState<TraceTable | null>(null)
  const [page, setPage] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [queryError, setQueryError] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [restored, setRestored] = useState(false)
  const restoreRef = useRef<SimulationSession | null>(null)
  const restoringRef = useRef(false)
  const handledRunRequest = useRef(props.runRequestId ?? 0)
  const baselineRequest = useRef(0)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false; baselineRequest.current += 1 } }, [])
  const selected = controller.selected
  const resultId = selected?.identity.resultId ?? null
  const catalog = selected?.catalog ?? null
  const activeTraces = useMemo(() => tracesForSelectedResult(selected, traceResultId, traces), [selected, traceResultId, traces])

  const loadBaseline = useCallback(async (summary: SimulationResultSummaryDto) => {
    if (!props.projectId) return
    const request = ++baselineRequest.current
    setBaseline(null); setBaselineLoading(true)
    try {
      const response = await fetchWorkbench(props.projectId, summary.result_id)
      if (response.job_id !== summary.job_id) throw new Error('Baseline history identity changed.')
      if (alive.current && request === baselineRequest.current) setBaseline(buildResultViewModel(response))
    } catch (caught) { if (alive.current && request === baselineRequest.current) setError(errorText(caught)) }
    finally { if (alive.current && request === baselineRequest.current) setBaselineLoading(false) }
  }, [props.projectId])

  useEffect(() => {
    if (!controller.snapshotReady || restoringRef.current) return
    restoringRef.current = true
    const stored = getWorkSession()
    const saved = props.projectRoot && sameProjectRoot(stored.projectRoot, props.projectRoot) ? stored.simulation : null
    restoreRef.current = saved
    const summary = controller.results.find((item) => item.result_path === saved?.selectedResultPath)
    const reference = controller.results.find((item) => item.result_path === saved?.baselineResultPath)
    if (reference) void loadBaseline(reference)
    if (summary) void controller.selectResult(summary.result_id, summary.job_id).finally(() => { if (alive.current) setRestored(true) })
    else setRestored(true)
  }, [controller.results, controller.selectResult, controller.snapshotReady, loadBaseline, props.projectRoot])

  useEffect(() => {
    setTraceResultId(selected?.identity.resultId ?? null)
    if (!selected) { setTraces([]); return }
    const saved = restoreRef.current?.selectedResultPath === selected.resultPath ? restoreRef.current : null
    restoreRef.current = null
    setTraces(saved && selected.catalog ? supportedTraces(saved.traces, selected.catalog) : selected.catalog?.default_traces.slice(0, 4) ?? [])
    setRange(saved?.xRange ?? null); setCursorA(saved?.cursorA ?? null); setCursorB(saved?.cursorB ?? null)
    setCursorTarget(saved?.cursorTarget ?? 'a')
    setTab(saved?.activeTab ?? (selected.result.success ? selected.result.analysis_type === 'op' ? 'measurements' : 'waveforms' : 'log'))
    setConfirmDelete(false); setPage(0); setError(null)
  }, [selected])

  useEffect(() => {
    if (!restored || !props.projectRoot || traceResultId !== resultId) return
    updateSimulationSession(props.projectRoot, {selectedResultPath: selected?.resultPath ?? null, baselineResultPath: baseline?.resultPath ?? null, activeTab: tab, traces, cursorA, cursorB, cursorTarget, xRange: range})
  }, [baseline?.resultPath, cursorA, cursorB, cursorTarget, props.projectRoot, range, restored, selected?.resultPath, tab, traces, traceResultId, resultId])

  const run = useCallback(async () => {
    try { setError(null); await controller.run(experimentFromForm(form)) }
    catch (caught) { setError(errorText(caught)); setTab('experiment') }
  }, [controller.run, form])
  const configurationError = useMemo(() => { try { experimentFromForm(form); return null } catch (caught) { return errorText(caught) } }, [form])
  const canRun = controller.canRun && !configurationError
  const runTitle = configurationError ?? (controller.activeJob ? 'A simulation is running.' : 'Run the saved active circuit with this experiment configuration.')
  useEffect(() => props.onRunControlChange?.({canRun, busy: controller.busyAction === 'run', title: runTitle}), [canRun, controller.busyAction, props.onRunControlChange, runTitle])
  useEffect(() => {
    const request = props.runRequestId ?? 0
    if (request === handledRunRequest.current) return
    handledRunRequest.current = request
    if (canRun) void run()
  }, [canRun, props.runRequestId, run])

  const baselineCompatible = Boolean(catalog && baseline?.catalog && resultId !== baseline.identity.resultId && selected?.result.analysis_type === baseline.result.analysis_type && compatibleCatalogs(catalog, baseline.catalog))
  const baselineTraces = useMemo(() => baselineCompatible && baseline?.catalog ? supportedTraces(activeTraces, baseline.catalog).filter((trace) => (
    catalog?.signals.find((signal) => signal.name === trace.signal)?.unit === baseline.catalog?.signals.find((signal) => signal.name === trace.signal)?.unit
    && (!trace.reference || catalog?.signals.find((signal) => signal.name === trace.reference)?.unit === baseline.catalog?.signals.find((signal) => signal.name === trace.reference)?.unit)
  )) : [], [activeTraces, baseline, baselineCompatible, catalog])
  const request = useMemo(() => ({traces: activeTraces, x_min: range?.[0] ?? null, x_max: range?.[1] ?? null, max_points: 1800}), [activeTraces, range])

  useEffect(() => {
    setQuery(null); setBaselineQuery(null); setQueryError(null)
    if (!selected?.result.success || !props.projectId || !resultId || !catalog || !activeTraces.length) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      void Promise.allSettled([
        queryTraces(props.projectId!, resultId, request),
        baseline && baselineTraces.length ? queryTraces(props.projectId!, baseline.identity.resultId, {...request, traces: baselineTraces}) : Promise.resolve(null),
      ]).then(([current, reference]) => {
        if (cancelled) return
        if (current.status === 'fulfilled') setQuery(current.value)
        else setQueryError(errorText(current.reason))
        if (reference.status === 'fulfilled') setBaselineQuery(reference.value)
        else setQueryError(`Baseline: ${errorText(reference.reason)}`)
      })
    }, 120)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [baseline, baselineTraces, catalog, props.projectId, request, resultId, activeTraces.length, selected?.result.success])

  useEffect(() => {
    setMeasurements(null); setBaselineMeasurements(null)
    if (!selected?.result.success || !props.projectId || !resultId || !catalog || !activeTraces.length || (tab !== 'waveforms' && tab !== 'measurements')) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      const measurementRequest = {...request, cursor_a: cursorA, cursor_b: cursorB}
      void Promise.allSettled([
        queryTraceMeasurements(props.projectId!, resultId, measurementRequest),
        baseline && baselineTraces.length ? queryTraceMeasurements(props.projectId!, baseline.identity.resultId, {...measurementRequest, traces: baselineTraces}) : Promise.resolve(null),
      ]).then(([current, reference]) => {
        if (cancelled) return
        if (current.status === 'fulfilled') setMeasurements(current.value)
        else setQueryError(errorText(current.reason))
        if (reference.status === 'fulfilled') setBaselineMeasurements(reference.value)
        else setQueryError(`Baseline measurements: ${errorText(reference.reason)}`)
      })
    }, 140)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [baseline, baselineTraces, catalog, cursorA, cursorB, props.projectId, request, resultId, tab, activeTraces.length, selected?.result.success])

  useEffect(() => setPage(0), [resultId, traces])
  useEffect(() => {
    setTable(null)
    if (!selected?.result.success || tab !== 'raw' || !props.projectId || !resultId || !activeTraces.length) return
    let cancelled = false
    void queryTraceTable(props.projectId, resultId, {traces: activeTraces, offset: page * PAGE_SIZE, limit: PAGE_SIZE}).then((value) => { if (!cancelled) setTable(value) }).catch((caught) => { if (!cancelled) setQueryError(errorText(caught)) })
    return () => { cancelled = true }
  }, [activeTraces, page, props.projectId, resultId, selected?.result.success, tab])

  const chartData = useMemo(() => query && traceResultId === resultId && selected?.result.success ? {x_axis: query.x_axis, series: [
    ...query.series.map((series, index) => ({...series, id: `current:${series.id}`, source_result_id: resultId!, label: `${series.label} · current`, color: COLORS[index % COLORS.length]})),
    ...(baselineQuery?.series.map((series, index) => ({...series, id: `baseline:${series.id}`, source_result_id: baseline!.identity.resultId, label: `${series.label} · baseline ${shortId(baseline!.identity.resultId)}`, color: COLORS[(index + 3) % COLORS.length]})) ?? []),
  ]} : null, [baseline, baselineQuery, query, resultId, traceResultId, selected?.result.success])

  const act = async (operation: () => Promise<void>) => {
    setActionBusy(true); setError(null)
    try { await operation() } catch (caught) { if (alive.current) setError(errorText(caught)) }
    finally { if (alive.current) setActionBusy(false) }
  }
  const exportCsv = () => act(async () => {
    if (!selected?.result.success || !activeTraces.length) return
    const blob = await exportTraceCsv(selected.identity.projectId, selected.identity.resultId, {traces: activeTraces})
    if (alive.current) downloadBlob(`${selected.identity.resultId}_traces.csv`, blob)
  })
  const exportJson = () => act(async () => { const result = await controller.exportCanonicalJson(); if (result && alive.current) downloadBlob(result.metadata.file_name, result.blob) })
  const inputs = () => act(async () => { if (!selected) return; const blob = await fetchExperimentInputs(selected.identity.projectId, selected.identity.resultId); if (alive.current) downloadBlob(`${selected.identity.resultId}_inputs.zip`, blob) })

  let content
  if (tab === 'experiment') content = <ExperimentPanel form={form} onChange={setForm} view={selected} disabled={controller.busyAction !== null || actionBusy || Boolean(controller.activeJob || controller.blockingJob)} onReuse={() => selected?.provenance.experiment && setForm(formFromExperiment(selected.provenance.experiment))} onReplay={() => void controller.replay()} onInputs={() => void inputs()} />
  else if (!selected) content = <Empty>Select a run from the history, or configure and run a circuit.</Empty>
  else if (controller.resultLoading || traceResultId !== resultId) content = <Empty>Loading selected run…</Empty>
  else if (tab === 'topology') content = <TopologyInspector schematic={selected.schematic} />
  else if (tab === 'log') content = <OutputPanel key={resultId} view={selected} />
  else content = <div className="simulation-panel-stack">
    {catalog ? <TraceEditor catalog={catalog} traces={traces} onChange={(next) => setTraces(next.filter((trace, index) => next.findIndex((item) => traceKey(item) === traceKey(trace)) === index))} /> : null}
    {baseline ? <div className="simulation-baseline-strip"><span>Baseline: {shortId(baseline.identity.resultId)} · {baseline.result.analysis_command}</span><span>{resultId === baseline.identity.resultId ? 'Pinned for comparison with the next run' : baselineCompatible ? `${baselineTraces.length}/${traces.length} matching traces` : 'Different analysis or axis: waveform overlay unavailable'}</span><button type="button" onClick={() => { ++baselineRequest.current; setBaseline(null) }}>Clear baseline</button></div> : null}
    {selected.noiseTotals.applicable ? <section className="simulation-card"><div className="simulation-card__header"><div><h2>Integrated noise</h2><p>Native ngspice RMS totals across the original noise-analysis frequency range.</p></div></div><dl className="simulation-detail-grid">{selected.noiseTotals.available ? selected.noiseTotals.items.map((item) => <div key={item.key}><dt>{item.key === 'output_rms' ? 'Output noise RMS' : 'Input-referred noise RMS'}</dt><dd>{formatEngineering(item.value, item.unit)}</dd></div>) : <div><dt>Noise totals</dt><dd>Unavailable for this result</dd></div>}</dl></section> : null}
    <ErrorMessage message={queryError} />
    {tab === 'raw' ? traces.length ? <RawTable table={table} page={page} onPage={setPage} /> : <Empty>Add a trace to inspect its original samples.</Empty> : <>
      {tab === 'waveforms' ? <section className="simulation-card">
        <div className="simulation-card__header"><div><h2>{selected.result.analysis_type.toUpperCase()} response</h2><p>Wheel to zoom · drag to pan · click to position a cursor · double-click to fit</p></div><div className="simulation-button-row"><button type="button" onClick={() => setRange(null)}>Fit all</button><button type="button" aria-pressed={cursorTarget === 'a'} onClick={() => setCursorTarget('a')}>Cursor A</button><button type="button" aria-pressed={cursorTarget === 'b'} onClick={() => setCursorTarget('b')}>Cursor B</button><button type="button" onClick={() => {setCursorA(null); setCursorB(null)}}>Clear cursors</button></div></div>
        <div className="simulation-cursor-inputs"><label>A ({catalog?.x_axis.unit || 'X'})<input type="number" step="any" value={cursorA ?? ''} onChange={(event) => setCursorA(event.target.value === '' ? null : Number(event.target.value))} /></label><label>B ({catalog?.x_axis.unit || 'X'})<input type="number" step="any" value={cursorB ?? ''} onChange={(event) => setCursorB(event.target.value === '' ? null : Number(event.target.value))} /></label><span>{query ? query.series.map((series) => `${series.point_count}/${series.visible_point_count} display samples`).join(' · ') : ''}</span></div>
        {chartData ? <SeriesChart data={chartData} range={range} onRangeChange={setRange} cursorA={cursorA} cursorB={cursorB} cursorTarget={cursorTarget} onCursorChange={(which, value) => which === 'a' ? setCursorA(value) : setCursorB(value)} /> : <Empty>{traces.length && catalog ? 'Loading waveform window…' : 'Add a trace to plot.'}</Empty>}
      </section> : <SourceMeasurements view={selected} baseline={baseline} />}
      <MeasurementTable data={measurements} label="Current run measurements" /><MeasurementTable data={baselineMeasurements} label="Baseline measurements" />
    </>}
  </div>

  return <section className="simulation-feature" hidden={!props.active} aria-label="Circuit simulation workbench">
    <header className="simulation-header"><div className="simulation-header__identity"><strong>Simulation workbench</strong><span className="simulation-header__file" title={props.activeDocumentPath ?? ''}>{props.activeDocumentPath?.split(/[\\/]/).pop() ?? 'Select a SPICE circuit'}</span></div><div className="simulation-button-row"><span className="simulation-run-state">{controller.activeJob?.status ?? controller.blockingJob?.status ?? 'Ready'}</span><button type="button" disabled={!canRun} title={runTitle} className="simulation-primary" onClick={() => void run()}>Run saved source</button>{controller.activeJob ? <button type="button" disabled={controller.activeJob.cancel_requested || controller.busyAction !== null} onClick={() => void controller.cancel()}>{controller.activeJob.cancel_requested ? 'Cancelling…' : 'Cancel'}</button> : null}</div></header>
    {controller.notice ? <div className={`simulation-notice simulation-notice--${controller.notice.level}`} role="status"><span>{controller.notice.message}</span><button type="button" aria-label="Dismiss notification" onClick={controller.clearNotice}>×</button></div> : null}
    <ErrorMessage message={error} />
    <div className="simulation-workbench-layout">
      <aside className="simulation-run-history" aria-label="Simulation run history"><div className="simulation-section-heading"><strong>Run history</strong><button type="button" disabled={controller.loading} onClick={() => void controller.refresh()}>Refresh</button></div>
        {controller.jobs.filter((job) => job.status === 'pending' || job.status === 'running').map((job) => <div className="simulation-live-job" key={job.job_id}><strong>{job.status} · {job.origin === 'ui_editor' ? 'Editor' : 'Agent'}</strong><small>{job.circuit_file}</small></div>)}
        {!controller.results.length ? <Empty>No completed runs yet.</Empty> : [...controller.results].sort((left, right) => right.timestamp.localeCompare(left.timestamp)).map((summary) => <article key={summary.result_id} className={`simulation-history-entry${resultId === summary.result_id ? ' is-selected' : ''}`}>
          <button type="button" className="simulation-history-select" disabled={controller.resultLoading} onClick={() => { restoreRef.current = null; void controller.selectResult(summary.result_id, summary.job_id) }}><strong>{summary.circuit_file.split(/[\\/]/).pop()}</strong><span>{summary.analysis_type.toUpperCase()} · <b className={summary.success ? '' : 'simulation-text-error'}>{summary.success ? 'Completed' : 'Failed'}</b></span><small>{dateText(summary.timestamp)}</small><code>{shortId(summary.result_id)}</code></button>
          <button type="button" className="simulation-baseline-button" disabled={!summary.success || baselineLoading} aria-pressed={baseline?.identity.resultId === summary.result_id} onClick={() => void loadBaseline(summary)}>{baseline?.identity.resultId === summary.result_id ? 'Pinned baseline' : 'Set baseline'}</button>
        </article>)}
      </aside>
      <div className="simulation-workbench-main"><nav className="simulation-tabs" aria-label="Simulation workbench sections">{TABS.map(([id, label]) => <button key={id} type="button" className={tab === id ? 'is-active' : ''} aria-current={tab === id ? 'page' : undefined} onClick={() => setTab(id)}>{label}</button>)}</nav>
        {selected ? <div className="simulation-result-toolbar"><span title={selected.identity.resultId}>{selected.result.analysis_command || selected.result.analysis_type.toUpperCase()} · {shortId(selected.identity.resultId)}</span><div className="simulation-button-row"><button type="button" disabled={actionBusy || !activeTraces.length || !catalog} onClick={() => void exportCsv()}>Full-resolution CSV</button><button type="button" disabled={!chartData || actionBusy} onClick={() => { try { if (chartData) downloadContent(`${resultId}_view.svg`, 'image/svg+xml', buildPlotSvg(chartData, selected.identity, range)) } catch (caught) { setError(errorText(caught)) } }}>View SVG</button><button type="button" disabled={actionBusy} onClick={() => void exportJson()}>Result JSON</button>{confirmDelete ? <><button type="button" onClick={() => setConfirmDelete(false)}>Keep</button><button type="button" className="simulation-text-error" disabled={controller.busyAction !== null} onClick={() => void controller.deleteSelected()}>Delete permanently</button></> : <button type="button" onClick={() => setConfirmDelete(true)}>Delete…</button>}</div></div> : null}
        <main className="simulation-content">{!props.projectId ? <Empty>Open a project to configure simulations.</Empty> : !restored ? <Empty>Loading simulation history…</Empty> : content}</main>
      </div>
    </div>
  </section>
}

export function SimulationFeature(props: SimulationFeatureProps) {
  return <Workbench key={`${props.projectId ?? ''}\u0000${props.projectRoot ?? ''}`} {...props} />
}
