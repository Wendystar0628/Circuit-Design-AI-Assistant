import type { AcceptanceConstraint, CornerAxis, ExperimentSpec, ModelBinding, NumericalConfiguration, ResultViewModel, TraceCatalog, TraceSpec, WorkbenchResponse } from './types'

const CIRCUIT_EXTENSIONS = new Set(['cir', 'sp', 'spice', 'net', 'ckt'])
export function isSupportedCircuitPath(path: string | null): boolean {
  return Boolean(path && CIRCUIT_EXTENSIONS.has((path.split('.').pop() ?? '').toLowerCase()))
}
export function buildResultViewModel(response: WorkbenchResponse): ResultViewModel {
  return {
    identity: { projectId: response.project_id, resultId: response.result_id, jobId: response.job_id },
    resultPath: response.result_path, result: response.result, catalog: response.catalog,
    metrics: response.metrics, schematic: response.schematic, provenance: response.provenance, noiseTotals: response.noise_totals,
  }
}
export function traceKey(trace: TraceSpec): string {
  return JSON.stringify([trace.signal, trace.reference || null, trace.component])
}
export function supportedTraces(traces: TraceSpec[], catalog: TraceCatalog): TraceSpec[] {
  return traces.filter((trace) => {
    const signal = catalog.signals.find((item) => item.name === trace.signal)
    const reference = trace.reference ? catalog.signals.find((item) => item.name === trace.reference) : null
    return signal?.components.includes(trace.component) && (!trace.reference || (
      reference && Boolean(reference.unit && signal.unit) && (trace.component !== 'db' || reference.unit === signal.unit)
    ))
  })
}
/** A selection transition must never send the previous result's trace state. */
export function tracesForSelectedResult(view: ResultViewModel | null, ownerResultId: string | null, traces: TraceSpec[]): TraceSpec[] {
  if (!view?.result.success || !view.catalog || view.identity.resultId !== ownerResultId) return []
  return supportedTraces(traces, view.catalog)
}
export function compatibleCatalogs(current: TraceCatalog, baseline: TraceCatalog): boolean {
  return current.x_axis.kind === baseline.x_axis.kind && current.x_axis.unit === baseline.x_axis.unit
    && current.x_axis.label === baseline.x_axis.label
}
export function parseAssignments(text: string, label: string): Record<string, string | number> {
  const values: Record<string, string | number> = {}
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue
    const match = /^\s*([A-Za-z_][\w.]*)\s*=\s*(\S.*?)\s*$/.exec(line)
    if (!match) throw new Error(`${label}: use one name=value assignment per line.`)
    if (Object.hasOwn(values, match[1])) throw new Error(`${label}: duplicate ${match[1]}.`)
    values[match[1]] = match[2]
  }
  return values
}
export interface ExperimentForm { analysis: string; parameters: string; temperature: string; solver: string; timeout: string; acceptance?: AcceptanceConstraint[]; models?: ModelBinding[] }
export function experimentFromForm(form: ExperimentForm): ExperimentSpec {
  const timeout = Number(form.timeout)
  const temperature = form.temperature.trim() ? Number(form.temperature) : null
  if (!Number.isFinite(timeout) || timeout <= 0) throw new Error('Timeout must be a positive number of seconds.')
  if (temperature !== null && !Number.isFinite(temperature)) throw new Error('Temperature must be a finite Celsius value.')
  const identifiers = new Set<string>()
  for (const constraint of form.acceptance ?? []) {
    const label = `Acceptance ${constraint.metric || 'constraint'}`
    if (!constraint.metric.trim() || !constraint.unit.trim()) throw new Error(`${label}: metric and unit are required.`)
    const id = (constraint.id || constraint.metric).trim().toLowerCase()
    if (identifiers.has(id)) throw new Error(`${label}: duplicate constraint identity.`)
    identifiers.add(id)
    if (constraint.lower == null && constraint.upper == null) throw new Error(`${label}: enter at least one bound.`)
    if ([constraint.lower, constraint.upper, constraint.conditions?.temperature].some((value) => value != null && !Number.isFinite(value))) throw new Error(`${label}: bounds and temperature must be finite numbers.`)
    if (constraint.lower != null && constraint.upper != null && constraint.lower > constraint.upper) throw new Error(`${label}: lower bound must not exceed upper bound.`)
    for (const [name, value] of Object.entries(constraint.conditions?.parameters ?? {})) {
      if (!/^[A-Za-z_][\w.]*$/.test(name) || !String(value).trim()) throw new Error(`${label}: condition parameters require a valid name and value.`)
    }
  }
  for (const model of form.models ?? []) {
    if (!model.name.trim()) throw new Error('Model metadata requires a model or subcircuit name.')
    for (const range of [model.voltage_range, model.frequency_range, model.temperature_range]) {
      if (range && [range.min, range.max].some((value) => value != null && !Number.isFinite(value))) throw new Error(`Model ${model.name}: range values must be finite.`)
      if (range?.min != null && range.max != null && range.min > range.max) throw new Error(`Model ${model.name}: minimum must not exceed maximum.`)
    }
  }
  return { analysis_command: form.analysis.trim(), parameters: parseAssignments(form.parameters, 'Parameters'),
    solver_options: parseAssignments(form.solver, 'Solver options'), temperature, timeout_seconds: timeout,
    ...(form.acceptance?.length ? {acceptance_constraints: structuredClone(form.acceptance)} : {}),
    ...(form.models?.length ? {model_bindings: structuredClone(form.models)} : {}) }
}
export function formFromExperiment(spec: ExperimentSpec): ExperimentForm {
  const assignments = (values: Record<string, string | number> | undefined) => Object.entries(values ?? {}).map(([key, value]) => `${key}=${value}`).join('\n')
  return { analysis: spec.analysis_command ?? '', parameters: assignments(spec.parameters),
    temperature: spec.temperature == null ? '' : String(spec.temperature), solver: assignments(spec.solver_options), timeout: String(spec.timeout_seconds ?? 120),
    ...(spec.acceptance_constraints?.length ? {acceptance: structuredClone(spec.acceptance_constraints)} : {}),
    ...(spec.model_bindings?.length ? {models: structuredClone(spec.model_bindings)} : {}) }
}

export interface CornerAxisForm {kind: CornerAxis['kind']; parameter: string; values: string}
export function cornerAxesFromForm(rows: CornerAxisForm[]): CornerAxis[] {
  if (!rows.length) throw new Error('Add at least one corner axis.')
  const names = new Set<string>()
  let cases = 1
  return rows.map((row) => {
    const parameter = row.parameter.trim()
    const name = row.kind === 'temperature' ? 'temperature' : parameter.toLowerCase()
    if (row.kind !== 'temperature' && !/^[A-Za-z_][\w.]*$/.test(parameter)) throw new Error('Each parameter, supply or load axis requires an existing .param name.')
    if (names.has(name)) throw new Error(`Duplicate corner axis: ${name}.`)
    names.add(name)
    const tokens = row.values.split(/[,\s]+/).filter(Boolean)
    if (!tokens.length) throw new Error('Each corner axis needs at least one value.')
    if (new Set(tokens.map((value) => value.toLowerCase())).size !== tokens.length) throw new Error(`Duplicate values in corner axis ${name}.`)
    const values = row.kind === 'temperature' ? tokens.map((value) => {
      const parsed = Number(value)
      if (!Number.isFinite(parsed)) throw new Error('Corner temperatures must be finite Celsius numbers.')
      return parsed
    }) : tokens
    cases *= values.length
    if (cases > 64) throw new Error('A corner matrix may contain at most 64 cases.')
    return {kind: row.kind, ...(row.kind !== 'temperature' ? {parameter} : {}), values}
  })
}
export interface NumericalForm {toleranceFactor: string; timestepFactor: string; metrics: Array<{name: string; unit: string; absolute: string; relative: string}>}
export function numericalFromForm(form: NumericalForm): NumericalConfiguration {
  const toleranceFactor = Number(form.toleranceFactor), timestepFactor = Number(form.timestepFactor)
  if (!(toleranceFactor > 0 && toleranceFactor < 1 && timestepFactor > 0 && timestepFactor < 1)) throw new Error('Refinement factors must be greater than 0 and less than 1.')
  if (!form.metrics.length) throw new Error('Add at least one numerical comparison metric.')
  const names = new Set<string>()
  const metrics = form.metrics.map((metric) => {
    const name = metric.name.trim(), unit = metric.unit.trim()
    if (!name || !unit) throw new Error('Each numerical metric requires a name and unit.')
    if (names.has(name.toLowerCase())) throw new Error(`Duplicate numerical metric: ${name}.`)
    names.add(name.toLowerCase())
    const absolute = Number(metric.absolute), relative = Number(metric.relative)
    if (!metric.absolute.trim() || !metric.relative.trim() || !Number.isFinite(absolute) || !Number.isFinite(relative) || absolute < 0 || relative < 0) throw new Error('Numerical thresholds must be explicit finite nonnegative numbers.')
    return {name, unit, absolute_tolerance: absolute, relative_tolerance: relative}
  })
  return {metrics, tolerance_factor: toleranceFactor, max_timestep_factor: timestepFactor}
}
/** Presentation formatting only. Circuit transforms and measurements belong to the backend. */
export function formatEngineering(value: number | null | undefined, unit = ''): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (unit.startsWith('dB') || unit === '°') return `${Number(value.toPrecision(6))}${unit ? ` ${unit}` : ''}`
  if (value === 0) return `0${unit ? ` ${unit}` : ''}`
  const prefixes: Record<number, string> = { [-15]: 'f', [-12]: 'p', [-9]: 'n', [-6]: 'µ', [-3]: 'm', 0: '', 3: 'k', 6: 'M', 9: 'G', 12: 'T' }
  const exponent = Math.floor(Math.log10(Math.abs(value)) / 3) * 3
  if (exponent in prefixes) return `${Number((value / 10 ** exponent).toPrecision(6))} ${prefixes[exponent]}${unit}`.trim()
  return `${value.toExponential(5)}${unit ? ` ${unit}` : ''}`
}
