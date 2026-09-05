import type { ExperimentSpec, ResultViewModel, TraceCatalog, TraceSpec, WorkbenchResponse } from './types'

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
export interface ExperimentForm { analysis: string; parameters: string; temperature: string; solver: string; timeout: string }
export function experimentFromForm(form: ExperimentForm): ExperimentSpec {
  const timeout = Number(form.timeout)
  const temperature = form.temperature.trim() ? Number(form.temperature) : null
  if (!Number.isFinite(timeout) || timeout <= 0) throw new Error('Timeout must be a positive number of seconds.')
  if (temperature !== null && !Number.isFinite(temperature)) throw new Error('Temperature must be a finite Celsius value.')
  return { analysis_command: form.analysis.trim(), parameters: parseAssignments(form.parameters, 'Parameters'),
    solver_options: parseAssignments(form.solver, 'Solver options'), temperature, timeout_seconds: timeout }
}
export function formFromExperiment(spec: ExperimentSpec): ExperimentForm {
  const assignments = (values: Record<string, string | number> | undefined) => Object.entries(values ?? {}).map(([key, value]) => `${key}=${value}`).join('\n')
  return { analysis: spec.analysis_command ?? '', parameters: assignments(spec.parameters),
    temperature: spec.temperature == null ? '' : String(spec.temperature), solver: assignments(spec.solver_options), timeout: String(spec.timeout_seconds ?? 120) }
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
