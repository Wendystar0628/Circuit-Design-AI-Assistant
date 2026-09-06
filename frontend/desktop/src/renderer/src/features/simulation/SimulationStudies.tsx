import { useEffect, useMemo, useRef, useState } from 'react'
import { cancelSimulationStudy, createSimulationStudy, fetchSimulationStudies } from './simulationApi'
import { cornerAxesFromForm, experimentFromForm, formatEngineering, isSupportedCircuitPath, numericalFromForm, type CornerAxisForm, type ExperimentForm, type NumericalForm } from './simulationModel'
import type { NumericalComparison, SimulationStudy, StudyCase } from './types'

const active = (status: string) => status === 'pending' || status === 'running'
const message = (error: unknown) => error instanceof Error ? error.message : 'Study operation failed.'
const initialNumerical: NumericalForm = {toleranceFactor: '0.1', timestepFactor: '0.5', metrics: [{name: '', unit: 'V', absolute: '0.001', relative: '0.01'}]}

function CornerEditor({axes, onChange}: {axes: CornerAxisForm[]; onChange(axes: CornerAxisForm[]): void}) {
  const update = (index: number, patch: Partial<CornerAxisForm>) => onChange(axes.map((axis, position) => position === index ? {...axis, ...patch} : axis))
  const count = axes.length ? axes.reduce((total, axis) => total * axis.values.split(/[,\s]+/).filter(Boolean).length, 1) : 0
  return <>
    <div className="simulation-experiment-grid">
      <p className="simulation-field--wide">Each combination gets an independent input snapshot and result. Supply and load axes override an existing top-level .param referenced by the source or load, for example VDD or Rload.</p>
      {axes.map((axis, index) => <fieldset className="simulation-study-axis simulation-field--wide" key={index}><legend>Axis {index + 1}</legend>
        <label className="simulation-field"><span>Kind</span><select value={axis.kind} onChange={(event) => update(index, {kind: event.target.value as CornerAxisForm['kind']})}><option value="parameter">Parameter</option><option value="temperature">Temperature</option><option value="supply">Supply</option><option value="load">Load</option></select></label>
        {axis.kind !== 'temperature' ? <label className="simulation-field"><span>Existing .param name</span><input value={axis.parameter} placeholder={axis.kind === 'load' ? 'Rload' : axis.kind === 'supply' ? 'VDD' : 'Cfilter'} onChange={(event) => update(index, {parameter: event.target.value})} /></label> : <span className="simulation-study-note">Temperature values are in °C.</span>}
        <label className="simulation-field simulation-field--wide"><span>Values <small>Separate with commas or spaces; SPICE suffixes are allowed for parameters.</small></span><input value={axis.values} placeholder={axis.kind === 'temperature' ? '-40, 25, 85' : axis.kind === 'load' ? '1k, 10k, 100k' : '3.0, 3.3, 3.6'} onChange={(event) => update(index, {values: event.target.value})} /></label>
        <button type="button" onClick={() => onChange(axes.filter((_, position) => index !== position))}>Remove axis</button>
      </fieldset>)}
    </div>
    <div className="simulation-button-row"><button type="button" onClick={() => onChange([...axes, {kind: 'parameter', parameter: '', values: ''}])}>Add axis</button><span>{count} cases · maximum 64</span></div>
  </>
}

function NumericalEditor({form, onChange}: {form: NumericalForm; onChange(form: NumericalForm): void}) {
  const update = (index: number, patch: Partial<NumericalForm['metrics'][number]>) => onChange({...form, metrics: form.metrics.map((metric, position) => position === index ? {...metric, ...patch} : metric)})
  return <>
    <div className="simulation-experiment-grid">
      <label className="simulation-field"><span>Solver tolerance multiplier</span><input type="number" step="any" min="0" max="1" value={form.toleranceFactor} onChange={(event) => onChange({...form, toleranceFactor: event.target.value})} /><small>Refine reltol, abstol and vntol; 0.1 is ten times tighter.</small></label>
      <label className="simulation-field"><span>Maximum time-step multiplier</span><input type="number" step="any" min="0" max="1" value={form.timestepFactor} onChange={(event) => onChange({...form, timestepFactor: event.target.value})} /><small>Transient analysis only; 0.5 halves the actual maximum step.</small></label>
      <p className="simulation-field--wide">The study saves a baseline and a refined run from the current experiment. Stability requires |refined − baseline| ≤ absolute threshold + relative threshold × |baseline| for every metric. This measures numerical sensitivity, not physical model accuracy.</p>
      {form.metrics.map((metric, index) => <fieldset key={index} className="simulation-study-axis simulation-field--wide"><legend>Comparison metric {index + 1}</legend>
        <label className="simulation-field"><span>SPICE .measure name</span><input value={metric.name} placeholder="vout_mean" onChange={(event) => update(index, {name: event.target.value})} /></label>
        <label className="simulation-field"><span>Unit</span><input value={metric.unit} placeholder="V, A, s, Hz, dB or 1" onChange={(event) => update(index, {unit: event.target.value})} /></label>
        <label className="simulation-field"><span>Absolute threshold ({metric.unit || 'metric unit'})</span><input type="number" min="0" step="any" value={metric.absolute} onChange={(event) => update(index, {absolute: event.target.value})} /></label>
        <label className="simulation-field"><span>Relative threshold (fraction)</span><input type="number" min="0" step="any" value={metric.relative} onChange={(event) => update(index, {relative: event.target.value})} /><small>0.01 means 1%; zero baseline uses the absolute threshold.</small></label>
        <button type="button" onClick={() => onChange({...form, metrics: form.metrics.filter((_, position) => position !== index)})}>Remove metric</button>
      </fieldset>)}
    </div><div className="simulation-button-row"><button type="button" onClick={() => onChange({...form, metrics: [...form.metrics, {name: '', unit: '', absolute: '0', relative: '0.01'}]})}>Add comparison metric</button></div>
  </>
}

function StabilitySummary({comparison}: {comparison: NumericalComparison}) {
  return <section className="simulation-card" aria-label="Numerical stability results">
    <div className="simulation-card__header"><div><h2>Numerical stability: {comparison.status}</h2><p>{comparison.reason}</p></div><strong className={`simulation-verdict simulation-verdict--${comparison.status === 'stable' ? 'pass' : comparison.status === 'unstable' ? 'fail' : 'unknown'}`}>{comparison.status.toUpperCase()}</strong></div>
    <div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Metric</th><th>Baseline</th><th>Refined</th><th>|Δ| / allowed</th><th>Relative Δ</th><th>Status / reason</th></tr></thead><tbody>{comparison.metrics.map((metric) => <tr key={metric.name}><td>{metric.name}</td><td>{formatEngineering(metric.baseline_value, metric.unit)}</td><td>{formatEngineering(metric.refined_value, metric.unit)}</td><td>{formatEngineering(metric.absolute_delta, metric.unit)} / {formatEngineering(metric.allowed_delta, metric.unit)}</td><td>{metric.relative_delta == null ? '—' : `${(100 * metric.relative_delta).toPrecision(4)}%`}</td><td>{metric.status}<small>{metric.reason}</small></td></tr>)}</tbody></table></div>
    <dl className="simulation-detail-grid"><div><dt>Baseline duration</dt><dd>{formatEngineering(comparison.cost.baseline_seconds, 's')}</dd></div><div><dt>Refined duration</dt><dd>{formatEngineering(comparison.cost.refined_seconds, 's')}</dd></div><div><dt>Total duration</dt><dd>{formatEngineering(comparison.cost.total_seconds, 's')}</dd></div><div><dt>Refined / baseline cost</dt><dd>{comparison.cost.ratio == null ? '—' : `${comparison.cost.ratio.toFixed(2)}×`}</dd></div></dl>
  </section>
}

function StudyResults({study, busy, onCancel, onSelect}: {study: SimulationStudy; busy: boolean; onCancel(caseId?: string): void; onSelect(item: StudyCase): void}) {
  const comparison = study.summary.numerical
  const metrics = study.summary.metrics ?? []
  const worst = study.summary.worst_constraints ?? []
  const chooseCase = (caseId: string | null) => { const item = study.cases.find((entry) => entry.case_id === caseId); if (item?.result_id) onSelect(item) }
  return <div className="simulation-panel-stack">
    <section className="simulation-card"><div className="simulation-card__header"><div><h2>{study.kind === 'corner' ? 'Corner matrix' : 'Numerical refinement'} · {study.status}</h2><p><code>{study.study_id}</code>{study.circuit_file ? ` · ${study.circuit_file}` : ''}</p></div>{active(study.status) ? <button type="button" disabled={busy} onClick={() => onCancel()}>Cancel study</button> : null}</div>
      <div className="simulation-study-counts"><span>Acceptance: <strong>{study.summary.acceptance_status ?? 'NOT_MEASURED'}</strong></span>{Object.entries(study.summary.counts ?? {}).map(([status, count]) => <span key={status}>{status}: <strong>{count}</strong></span>)}</div>
      <div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Case / independent identity</th><th>Inputs</th><th>Execution</th><th>Acceptance</th><th>Duration</th><th>Result / action</th></tr></thead><tbody>{study.cases.map((item) => <tr key={item.case_id}>
        <td>{item.label}<small><code>{item.case_id}</code></small><small>Job: {item.job_id ?? 'Not started'}</small></td>
        <td>{Object.entries(item.coordinates ?? {}).map(([name, value]) => <small key={name}>{name} = {value}</small>)}<details><summary>Saved experiment</summary><span>{item.experiment.analysis_command || 'Circuit analysis'}</span><small>Temperature: {item.experiment.temperature == null ? 'Circuit default' : `${item.experiment.temperature} °C`}</small>{Object.entries(item.experiment.parameters ?? {}).map(([name, value]) => <small key={name}>{name} = {value}</small>)}{Object.entries(item.experiment.solver_options ?? {}).map(([name, value]) => <small key={name}>{name} = {value}</small>)}</details></td>
        <td>{item.status}{item.error ? <small className="simulation-text-error">{item.error}</small> : null}</td><td>{item.acceptance?.status ?? 'NOT_MEASURED'}</td><td>{formatEngineering(item.duration_seconds, 's')}</td>
        <td><div className="simulation-button-row">{item.result_id ? <button type="button" onClick={() => onSelect(item)}>Open result</button> : <span>No result</span>}{active(item.status) ? <button type="button" disabled={busy} onClick={() => onCancel(item.case_id)}>Cancel case</button> : null}</div>{item.result_id ? <small><code>{item.result_id}</code></small> : null}</td>
      </tr>)}</tbody></table></div>
    </section>
    {metrics.length ? <section className="simulation-card"><div className="simulation-card__header"><div><h2>Metric extrema across cases</h2><p>Minimum, maximum and full range identify the worst case for either bound. Unmeasured cases never contribute zero.</p></div></div><div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Metric</th><th>Minimum / case</th><th>Maximum / case</th><th>Max − min</th><th>Measured / unmeasured</th></tr></thead><tbody>{metrics.map((metric, index) => <tr key={`${metric.name}:${index}`}><td>{metric.name} [{metric.unit || 'unknown unit'}]</td><td>{formatEngineering(metric.min, metric.unit)}{metric.min_case_id ? <button type="button" className="simulation-case-link" onClick={() => chooseCase(metric.min_case_id)}>{metric.min_case_id}</button> : null}</td><td>{formatEngineering(metric.max, metric.unit)}{metric.max_case_id ? <button type="button" className="simulation-case-link" onClick={() => chooseCase(metric.max_case_id)}>{metric.max_case_id}</button> : null}</td><td>{formatEngineering(metric.delta, metric.unit)}</td><td>{metric.measured_cases} / {metric.unmeasured_cases}</td></tr>)}</tbody></table></div></section> : null}
    {worst.length ? <section className="simulation-card"><div className="simulation-card__header"><div><h2>Worst acceptance margins</h2><p>Negative margin fails a limit. A missing margin is unmeasured.</p></div></div><div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Criterion</th><th>Limits</th><th>Minimum margin / worst case</th><th>PASS / FAIL / NOT_MEASURED</th></tr></thead><tbody>{worst.map((row) => <tr key={row.id}><td>{row.metric}</td><td>{formatEngineering(row.lower, row.unit)} to {formatEngineering(row.upper, row.unit)}</td><td>{formatEngineering(row.minimum_margin, row.unit)}{row.worst_case_id ? <button type="button" className="simulation-case-link" onClick={() => chooseCase(row.worst_case_id)}>{row.worst_case_id}</button> : null}</td><td>{row.counts.PASS ?? 0} / {row.counts.FAIL ?? 0} / {row.counts.NOT_MEASURED ?? 0}</td></tr>)}</tbody></table></div></section> : null}
    {comparison ? <StabilitySummary comparison={comparison} /> : null}
  </div>
}

export function SimulationStudies({projectId, circuitPath, experimentForm, visible, onSelectResult}: {projectId: string | null; circuitPath: string | null; experimentForm: ExperimentForm; visible: boolean; onSelectResult(resultId: string, jobId: string | null): Promise<unknown>}) {
  const [kind, setKind] = useState<'corner' | 'numerical'>('corner')
  const [axes, setAxes] = useState<CornerAxisForm[]>([{kind: 'temperature', parameter: '', values: '-40, 25, 85'}])
  const [numerical, setNumerical] = useState<NumericalForm>(initialNumerical)
  const [studies, setStudies] = useState<SimulationStudy[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const alive = useRef(true)
  const polling = useRef(false)
  const selected = studies.find((study) => study.study_id === selectedId) ?? studies[0]
  const configuration = useMemo(() => {
    try {
      const experiment = experimentFromForm(experimentForm)
      if (!isSupportedCircuitPath(circuitPath)) throw new Error('Select a saved SPICE circuit in the editor.')
      return {request: {circuit_path: circuitPath!, experiment, kind, ...(kind === 'corner' ? {axes: cornerAxesFromForm(axes)} : {numerical: numericalFromForm(numerical)})}, error: null}
    } catch (caught) { return {request: null, error: message(caught)} }
  }, [axes, circuitPath, experimentForm, kind, numerical])
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    if (!projectId || !visible) return
    let cancelled = false
    const refresh = async () => {
      if (polling.current) return
      polling.current = true
      try { const next = await fetchSimulationStudies(projectId); if (!cancelled) { setStudies(next); setError(null) } }
      catch (caught) { if (!cancelled) setError(message(caught)) }
      finally { polling.current = false }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 1500)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [projectId, visible])
  const storeStudy = (study: SimulationStudy) => setStudies((previous) => [study, ...previous.filter((item) => item.study_id !== study.study_id)])
  const submit = async () => {
    if (!projectId || !configuration.request) return
    setBusy(true); setError(null)
    try { const study = await createSimulationStudy(projectId, configuration.request); if (alive.current) {storeStudy(study); setSelectedId(study.study_id)} }
    catch (caught) { if (alive.current) setError(message(caught)) }
    finally { if (alive.current) setBusy(false) }
  }
  const cancel = async (caseId?: string) => {
    if (!projectId || !selected) return
    setBusy(true); setError(null)
    try { const study = await cancelSimulationStudy(projectId, selected.study_id, caseId); if (alive.current) storeStudy(study) }
    catch (caught) { if (alive.current) setError(message(caught)) }
    finally { if (alive.current) setBusy(false) }
  }
  return <div className="simulation-panel-stack" hidden={!visible}>
    <section className="simulation-card"><div className="simulation-card__header"><div><h2>Simulation studies</h2><p>Uses the saved active circuit and the current Experiment configuration, including acceptance criteria and model metadata.</p></div><select aria-label="Study kind" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="corner">Corner matrix</option><option value="numerical">Numerical stability</option></select></div>
      {kind === 'corner' ? <CornerEditor axes={axes} onChange={setAxes} /> : <NumericalEditor form={numerical} onChange={setNumerical} />}
      {configuration.error ? <div className="simulation-study-note" role="status">{configuration.error}</div> : null}
      <div className="simulation-button-row"><button type="button" className="simulation-primary" disabled={busy || !projectId || !configuration.request} onClick={() => void submit()}>{busy ? 'Submitting…' : kind === 'corner' ? 'Run corner matrix' : 'Run baseline + refinement'}</button></div>
    </section>
    {error ? <div className="simulation-inline-error" role="alert">{error}</div> : null}
    <section className="simulation-card"><div className="simulation-card__header"><h2>Study history</h2><select aria-label="Selected study" value={selected?.study_id ?? ''} onChange={(event) => setSelectedId(event.target.value)}>{!studies.length ? <option value="">No studies yet</option> : studies.map((study) => <option key={study.study_id} value={study.study_id}>{study.kind} · {study.status} · {study.study_id.slice(0, 12)}</option>)}</select></div></section>
    {selected ? <StudyResults study={selected} busy={busy} onCancel={(caseId) => void cancel(caseId)} onSelect={(item) => { if (item.result_id) void onSelectResult(item.result_id, item.job_id).catch((caught) => setError(message(caught))) }} /> : null}
  </div>
}
