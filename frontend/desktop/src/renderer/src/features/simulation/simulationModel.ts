import type {
  AnalysisType,
  ComplexSignal,
  NoiseTotals,
  OpRow,
  PlotModel,
  PlotSeries,
  ResultIdentity,
  ResultViewModel,
  SignalKind,
  SimulationData,
  SimulationMeasurement,
  SimulationResult,
  SimulationErrorPayload,
  SimulationResultResponse,
  SimulationSignal,
  SurfaceDataResponse,
  SurfaceMetricDto,
} from './types'

const ANALYSIS_TYPES = new Set<AnalysisType>(['tran', 'ac', 'dc', 'op', 'noise', 'unknown'])
const SIGNAL_KINDS = new Set<SignalKind>([
  'voltage',
  'current',
  'other',
])
const SERIES_COLORS = [
  '#2563eb',
  '#dc2626',
  '#16a34a',
  '#9333ea',
  '#ea580c',
  '#0891b2',
  '#c026d3',
  '#4f46e5',
]
const SUPPORTED_CIRCUIT_EXTENSIONS = new Set(['.cir', '.sp', '.spice', '.net', '.ckt'])

export function isSupportedCircuitPath(path: string | null): boolean {
  if (!path) return false
  const fileName = path.split(/[\\/]/).pop() ?? ''
  const dot = fileName.lastIndexOf('.')
  return dot >= 0 && SUPPORTED_CIRCUIT_EXTENSIONS.has(fileName.slice(dot).toLowerCase())
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be an object`)
  }
  return value as Record<string, unknown>
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== 'string') {
    throw new Error(`${label} must be a string`)
  }
  return value
}

function finiteNumber(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${label} must be finite`)
  }
  return value
}

function nullableFiniteNumber(value: unknown, label: string): number | null {
  return value === null ? null : finiteNumber(value, label)
}

function numberArray(value: unknown, label: string): Array<number | null> {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`)
  }
  return value.map((item, index) => nullableFiniteNumber(item, `${label}[${index}]`))
}

function nullableNumberArray(value: unknown, label: string): Array<number | null> | null {
  return value === null ? null : numberArray(value, label)
}

function signalValue(value: unknown, label: string): SimulationSignal {
  if (Array.isArray(value)) {
    return numberArray(value, label)
  }
  const record = objectValue(value, label)
  if (record._complex !== true) {
    throw new Error(`${label} has an unsupported signal encoding`)
  }
  const real = numberArray(record.real, `${label}.real`)
  const imag = numberArray(record.imag, `${label}.imag`)
  if (real.length !== imag.length) {
    throw new Error(`${label} complex components have different lengths`)
  }
  return { _complex: true, real, imag }
}

function normalizeNoiseTotals(value: unknown, label: string): NoiseTotals | null {
  if (value === null) {
    return null
  }
  const record = objectValue(value, label)
  const outputRms = finiteNumber(record.output_rms, `${label}.output_rms`)
  const inputRms = finiteNumber(record.input_referred_rms, `${label}.input_referred_rms`)
  if (outputRms < 0 || inputRms < 0) {
    throw new Error(`${label} values must be non-negative`)
  }
  return { output_rms: outputRms, input_referred_rms: inputRms }
}

function normalizeData(value: unknown, label: string): SimulationData | null {
  if (value === null) {
    return null
  }
  const record = objectValue(value, label)
  const signalsRecord = objectValue(record.signals, `${label}.signals`)
  const typesRecord = objectValue(record.signal_types, `${label}.signal_types`)
  const signals: Record<string, SimulationSignal> = {}
  const signalTypes: Record<string, SignalKind> = {}
  for (const [name, rawSignal] of Object.entries(signalsRecord)) {
    if (!name) {
      throw new Error(`${label}.signals contains an empty name`)
    }
    signals[name] = signalValue(rawSignal, `${label}.signals.${name}`)
    const kind = typesRecord[name]
    if (typeof kind !== 'string' || !SIGNAL_KINDS.has(kind as SignalKind)) {
      throw new Error(`${label}.signal_types.${name} is invalid`)
    }
    signalTypes[name] = kind as SignalKind
  }
  if (Object.keys(typesRecord).some((name) => !(name in signals))) {
    throw new Error(`${label}.signal_types contains an unknown signal`)
  }
  return {
    frequency: nullableNumberArray(record.frequency, `${label}.frequency`),
    time: nullableNumberArray(record.time, `${label}.time`),
    sweep: nullableNumberArray(record.sweep, `${label}.sweep`),
    signals,
    signal_types: signalTypes,
    noise_totals: normalizeNoiseTotals(record.noise_totals, `${label}.noise_totals`),
  }
}

function normalizeMeasurement(value: unknown, label: string): SimulationMeasurement {
  const record = objectValue(value, label)
  const status = stringValue(record.status, `${label}.status`)
  if (status !== 'OK' && status !== 'FAILED' && status !== 'PARSE_ERROR') {
    throw new Error(`${label}.status is invalid`)
  }
  return {
    name: stringValue(record.name, `${label}.name`),
    value: nullableFiniteNumber(record.value, `${label}.value`),
    status,
    statement: stringValue(record.statement, `${label}.statement`),
    raw_output: stringValue(record.raw_output, `${label}.raw_output`),
    error_message: stringValue(record.error_message, `${label}.error_message`),
  }
}

function normalizeSimulationError(value: unknown): SimulationErrorPayload | null {
  if (value === null) return null
  const record = objectValue(value, 'simulation result.error')
  const severity = stringValue(record.severity, 'simulation result.error.severity')
  if (severity !== 'low' && severity !== 'medium' && severity !== 'high' && severity !== 'critical') {
    throw new Error('simulation result.error.severity is invalid')
  }
  const nullableString = (item: unknown, label: string) => item === null ? null : stringValue(item, label)
  const lineNumber = record.line_number === null ? null : finiteNumber(record.line_number, 'simulation result.error.line_number')
  if (lineNumber !== null && (!Number.isSafeInteger(lineNumber) || lineNumber < 1)) {
    throw new Error('simulation result.error.line_number must be a positive integer')
  }
  if (typeof record.recovery_attempted !== 'boolean') {
    throw new Error('simulation result.error.recovery_attempted must be a boolean')
  }
  return {
    code: stringValue(record.code, 'simulation result.error.code'),
    type: stringValue(record.type, 'simulation result.error.type'),
    severity,
    message: stringValue(record.message, 'simulation result.error.message'),
    file_path: nullableString(record.file_path, 'simulation result.error.file_path'),
    line_number: lineNumber,
    context: nullableString(record.context, 'simulation result.error.context'),
    details: objectValue(record.details, 'simulation result.error.details'),
    recovery_attempted: record.recovery_attempted,
    recovery_result: nullableString(record.recovery_result, 'simulation result.error.recovery_result'),
    recovery_suggestion: nullableString(record.recovery_suggestion, 'simulation result.error.recovery_suggestion'),
    raw_output: nullableString(record.raw_output, 'simulation result.error.raw_output'),
  }
}

function normalizeResult(value: unknown): SimulationResult {
  const record = objectValue(value, 'simulation result')
  const analysisType = stringValue(record.analysis_type, 'simulation result.analysis_type')
  if (!ANALYSIS_TYPES.has(analysisType as AnalysisType)) {
    throw new Error('simulation result.analysis_type is unsupported')
  }
  if (typeof record.success !== 'boolean') {
    throw new Error('simulation result.success must be a boolean')
  }
  if (record.success && analysisType === 'unknown') {
    throw new Error('successful simulation result cannot have unknown analysis type')
  }
  const schemaVersion = finiteNumber(record.schema_version, 'simulation result.schema_version')
  const version = finiteNumber(record.version, 'simulation result.version')
  if (!Number.isSafeInteger(schemaVersion) || schemaVersion < 1) {
    throw new Error('simulation result.schema_version must be a positive integer')
  }
  if (!Number.isSafeInteger(version) || version < 1) {
    throw new Error('simulation result.version must be a positive integer')
  }
  const measurements = record.measurements === null
    ? null
    : Array.isArray(record.measurements)
      ? record.measurements.map((item, index) => normalizeMeasurement(item, `simulation result.measurements[${index}]`))
      : (() => { throw new Error('simulation result.measurements must be an array or null') })()
  const data = normalizeData(record.data, 'simulation result.data')
  const structuredError = normalizeSimulationError(record.error)
  if (record.success && (data === null || structuredError !== null)) {
    throw new Error('successful simulation result must contain data and no error')
  }
  if (!record.success && (data !== null || measurements !== null || structuredError === null)) {
    throw new Error('failed simulation result must contain only a structured error')
  }
  const durationSeconds = finiteNumber(record.duration_seconds, 'simulation result.duration_seconds')
  if (durationSeconds < 0) throw new Error('simulation result.duration_seconds cannot be negative')
  const executor = stringValue(record.executor, 'simulation result.executor')
  if ((record.success && executor !== 'spice') || (!record.success && executor !== 'spice' && executor !== 'unknown')) {
    throw new Error('simulation result.executor is invalid for its outcome')
  }
  const sourceDigest = record.source_digest === null
    ? null
    : stringValue(record.source_digest, 'simulation result.source_digest')
  if (sourceDigest !== null && !/^[0-9a-f]{64}$/.test(sourceDigest)) {
    throw new Error('simulation result has an invalid source-closure digest')
  }
  if (record.success && sourceDigest === null) {
    throw new Error('successful simulation result has no canonical source-closure digest')
  }
  return {
    schema_version: schemaVersion,
    executor,
    file_path: stringValue(record.file_path, 'simulation result.file_path'),
    analysis_type: analysisType as AnalysisType,
    success: record.success,
    source_digest: sourceDigest,
    data,
    measurements,
    error: structuredError,
    raw_output: stringValue(record.raw_output, 'simulation result.raw_output'),
    timestamp: stringValue(record.timestamp, 'simulation result.timestamp'),
    duration_seconds: durationSeconds,
    version,
    session_id: stringValue(record.session_id, 'simulation result.session_id'),
    analysis_command: stringValue(record.analysis_command, 'simulation result.analysis_command'),
  }
}

function sameNumberArray(left: Array<number | null> | null, right: Array<number | null> | null): boolean {
  if (left === null || right === null) return left === right
  return left.length === right.length && left.every((value, index) => Object.is(value, right[index]))
}

function sameSignal(left: SimulationSignal, right: SimulationSignal): boolean {
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && sameNumberArray(left, right)
  }
  return sameNumberArray(left.real, right.real) && sameNumberArray(left.imag, right.imag)
}

function sameData(left: SimulationData | null, right: SimulationData | null): boolean {
  if (left === null || right === null) return left === right
  if (
    !sameNumberArray(left.frequency, right.frequency)
    || !sameNumberArray(left.time, right.time)
    || !sameNumberArray(left.sweep, right.sweep)
  ) return false
  const leftNames = Object.keys(left.signals).sort()
  const rightNames = Object.keys(right.signals).sort()
  if (leftNames.length !== rightNames.length || leftNames.some((name, index) => name !== rightNames[index])) return false
  if (leftNames.some((name) => left.signal_types[name] !== right.signal_types[name] || !sameSignal(left.signals[name], right.signals[name]))) return false
  if (left.noise_totals === null || right.noise_totals === null) return left.noise_totals === right.noise_totals
  return left.noise_totals.output_rms === right.noise_totals.output_rms
    && left.noise_totals.input_referred_rms === right.noise_totals.input_referred_rms
}

function isComplex(signal: SimulationSignal): signal is ComplexSignal {
  return !Array.isArray(signal)
}

function signalUnit(kind: SignalKind): string {
  if (kind === 'voltage') return 'V'
  if (kind === 'current') return 'A'
  return ''
}

function noiseDensityUnit(kind: SignalKind): string {
  if (kind === 'voltage') return 'V/√Hz'
  if (kind === 'current') return 'A/√Hz'
  return ''
}

function chooseAxis(unit: string, firstUnit: string): 'left' | 'right' {
  return !firstUnit || unit === firstUnit ? 'left' : 'right'
}

function ensureLength(signal: Array<number | null>, x: Array<number | null>, label: string): void {
  if (signal.length !== x.length) {
    throw new Error(`${label} length does not match the analysis axis`)
  }
}

function buildRealSeries(
  analysisType: 'tran' | 'dc',
  data: SimulationData,
  x: Array<number | null>,
): PlotSeries[] {
  const entries = Object.entries(data.signals)
  const firstUnit = entries.length ? signalUnit(data.signal_types[entries[0][0]]) : ''
  return entries.map(([name, signal], index) => {
    if (isComplex(signal)) {
      throw new Error(`${analysisType.toUpperCase()} signal ${name} cannot be complex`)
    }
    ensureLength(signal, x, name)
    const unit = signalUnit(data.signal_types[name])
    const plotted = analysisType === 'dc' ? insertDcSweepGaps(x, signal) : { x, y: signal }
    return {
      id: name,
      label: name,
      color: SERIES_COLORS[index % SERIES_COLORS.length],
      axis: chooseAxis(unit, firstUnit),
      component: 'real',
      unit,
      x: plotted.x,
      y: plotted.y,
    }
  })
}

function insertDcSweepGaps(
  x: Array<number | null>,
  y: Array<number | null>,
): { x: Array<number | null>; y: Array<number | null> } {
  let direction = 0
  for (let index = 1; index < x.length; index += 1) {
    if (x[index - 1] === null || x[index] === null) continue
    const delta = (x[index] as number) - (x[index - 1] as number)
    if (delta !== 0) {
      direction = Math.sign(delta)
      break
    }
  }
  if (!direction) return { x, y }
  const plottedX: Array<number | null> = []
  const plottedY: Array<number | null> = []
  for (let index = 0; index < x.length; index += 1) {
    if (index > 0 && x[index - 1] !== null && x[index] !== null) {
      const delta = (x[index] as number) - (x[index - 1] as number)
      if (delta === 0 || Math.sign(delta) !== direction) {
        plottedX.push(null)
        plottedY.push(null)
      }
    }
    plottedX.push(x[index])
    plottedY.push(y[index])
  }
  return { x: plottedX, y: plottedY }
}

function decibels(real: number | null, imag: number | null): number | null {
  if (real === null || imag === null) return null
  const magnitude = Math.hypot(real, imag)
  return magnitude > 0 ? 20 * Math.log10(magnitude) : null
}

function phaseDegrees(real: number | null, imag: number | null): number | null {
  if (real === null || imag === null) return null
  return Math.atan2(imag, real) * 180 / Math.PI
}

function buildAcSeries(data: SimulationData, x: Array<number | null>): PlotSeries[] {
  return Object.entries(data.signals).flatMap(([name, signal], index) => {
    if (!isComplex(signal)) {
      throw new Error(`AC signal ${name} must contain complex samples`)
    }
    ensureLength(signal.real, x, `${name}.real`)
    const magnitude = signal.real.map((real, sample) => decibels(real, signal.imag[sample]))
    const phase = signal.real.map((real, sample) => phaseDegrees(real, signal.imag[sample]))
    const color = SERIES_COLORS[index % SERIES_COLORS.length]
    return [
      {
        id: `${name}:magnitude`,
        label: `${name} magnitude`,
        color,
        axis: 'left' as const,
        component: 'magnitude' as const,
        unit: 'dB',
        x,
        y: magnitude,
      },
      {
        id: `${name}:phase`,
        label: `${name} phase`,
        color,
        axis: 'right' as const,
        component: 'phase' as const,
        unit: '°',
        x,
        y: phase,
      },
    ]
  })
}

function buildNoiseSeries(data: SimulationData, x: Array<number | null>): PlotSeries[] {
  const entries = Object.entries(data.signals)
  const firstUnit = entries.length ? noiseDensityUnit(data.signal_types[entries[0][0]]) : ''
  return entries.map(([name, signal], index) => {
    if (isComplex(signal)) {
      throw new Error(`NOISE signal ${name} cannot be complex`)
    }
    ensureLength(signal, x, name)
    const unit = noiseDensityUnit(data.signal_types[name])
    if (unit !== 'V/√Hz' && unit !== 'A/√Hz') {
      throw new Error(`NOISE signal ${name} has no density unit`)
    }
    return {
      id: name,
      label: name,
      color: SERIES_COLORS[index % SERIES_COLORS.length],
      axis: chooseAxis(unit, firstUnit),
      component: 'density',
      unit,
      x,
      y: signal,
    }
  })
}

export function buildPlotModel(analysisType: AnalysisType, data: SimulationData | null): PlotModel | null {
  if (!data || analysisType === 'op' || analysisType === 'unknown') return null
  if (analysisType === 'tran') {
    if (!data.time) throw new Error('TRAN result has no time axis')
    const series = buildRealSeries('tran', data, data.time)
    return {
      analysisType,
      title: 'Transient response',
      xLabel: 'Time',
      xUnit: 's',
      leftLabel: series.find((item) => item.axis === 'left')?.unit || 'Value',
      rightLabel: series.find((item) => item.axis === 'right')?.unit ?? null,
      logX: false,
      logLeftY: false,
      logRightY: false,
      series,
    }
  }
  if (analysisType === 'dc') {
    if (!data.sweep) throw new Error('DC result has no sweep axis')
    const series = buildRealSeries('dc', data, data.sweep)
    return {
      analysisType,
      title: 'DC sweep',
      xLabel: 'Sweep',
      xUnit: '',
      leftLabel: series.find((item) => item.axis === 'left')?.unit || 'Value',
      rightLabel: series.find((item) => item.axis === 'right')?.unit ?? null,
      logX: false,
      logLeftY: false,
      logRightY: false,
      series,
    }
  }
  if (analysisType === 'ac') {
    if (!data.frequency) throw new Error('AC result has no frequency axis')
    const series = buildAcSeries(data, data.frequency)
    return {
      analysisType,
      title: 'AC response',
      xLabel: 'Frequency',
      xUnit: 'Hz',
      leftLabel: 'Magnitude (dB re 1 base unit)',
      rightLabel: 'Phase (°)',
      logX: true,
      logLeftY: false,
      logRightY: false,
      series,
    }
  }
  if (!data.frequency) throw new Error('NOISE result has no frequency axis')
  const series = buildNoiseSeries(data, data.frequency)
  return {
    analysisType,
    title: 'Noise spectral density',
    xLabel: 'Frequency',
    xUnit: 'Hz',
    leftLabel: series.find((item) => item.axis === 'left')?.unit || 'Density',
    rightLabel: series.find((item) => item.axis === 'right')?.unit ?? null,
    logX: true,
    logLeftY: true,
    logRightY: true,
    series,
  }
}

function buildOpRows(data: SimulationData | null): OpRow[] {
  if (!data) return []
  return Object.entries(data.signals).map(([name, signal]) => {
    const kind = data.signal_types[name]
    const value = isComplex(signal)
      ? (signal.real[0] === null || signal.imag[0] === null
          ? null
          : Math.hypot(signal.real[0], signal.imag[0]))
      : (signal[0] ?? null)
    return { signal: name, value, unit: signalUnit(kind) }
  })
}

function normalizeSurfaceMetrics(metrics: SurfaceDataResponse['metrics']): SurfaceMetricDto[] {
  return metrics.map((metric, index) => {
    if (!metric || typeof metric !== 'object') {
      throw new Error(`surface metric ${index} is invalid`)
    }
    if (metric.status !== 'OK' && metric.status !== 'FAILED' && metric.status !== 'PARSE_ERROR') {
      throw new Error(`surface metric ${index} has an invalid status`)
    }
    return {
      name: stringValue(metric.name, `surface metric ${index}.name`),
      value: nullableFiniteNumber(metric.value, `surface metric ${index}.value`),
      status: metric.status,
      statement: stringValue(metric.statement, `surface metric ${index}.statement`),
      raw_output: stringValue(metric.raw_output, `surface metric ${index}.raw_output`),
      error_message: stringValue(metric.error_message, `surface metric ${index}.error_message`),
    }
  })
}

function sameMeasurements(
  persisted: SimulationMeasurement[] | null,
  surface: SurfaceMetricDto[],
): boolean {
  const expected = persisted ?? []
  return expected.length === surface.length && expected.every((item, index) => {
    const candidate = surface[index]
    return item.name === candidate.name
      && item.value === candidate.value
      && item.status === candidate.status
      && item.statement === candidate.statement
      && item.raw_output === candidate.raw_output
      && item.error_message === candidate.error_message
  })
}

export function buildResultViewModel(
  response: SimulationResultResponse,
  surface: SurfaceDataResponse,
): ResultViewModel {
  if (
    response.project_id !== surface.project_id
    || response.result_id !== surface.result_id
    || response.job_id !== surface.job_id
  ) {
    throw new Error('result and surface data identities do not match')
  }
  const result = normalizeResult(response.result)
  const surfaceData = normalizeData(surface.data, 'surface data')
  if (!sameData(result.data, surfaceData)) {
    throw new Error('result payload and surface data disagree')
  }
  const metrics = normalizeSurfaceMetrics(surface.metrics)
  if (!sameMeasurements(result.measurements, metrics)) {
    throw new Error('result payload and measurement surface disagree')
  }
  if (surface.output_log !== result.raw_output) {
    throw new Error('result payload and output-log surface disagree')
  }
  const identity: ResultIdentity = {
    projectId: response.project_id,
    jobId: response.job_id,
    resultId: response.result_id,
  }
  return {
    identity,
    resultPath: response.result_path,
    result,
    data: surfaceData,
    metrics,
    outputLog: surface.output_log,
    schematic: surface.schematic,
    plot: buildPlotModel(result.analysis_type, surfaceData),
    opRows: result.analysis_type === 'op' ? buildOpRows(surfaceData) : [],
  }
}

export interface NoiseTotalRow {
  label: string
  value: number
  unit: 'V' | 'A'
}

export function buildNoiseTotalRows(view: ResultViewModel): NoiseTotalRow[] {
  const totals = view.data?.noise_totals
  if (!totals) return []
  const types = view.data?.signal_types ?? {}
  if (types.onoise_spectrum !== 'voltage') {
    throw new Error('integrated output noise requires canonical voltage-density metadata')
  }
  const inputKind = types.inoise_spectrum
  if (inputKind !== 'voltage' && inputKind !== 'current') {
    throw new Error('integrated input-referred noise requires canonical density metadata')
  }
  return [
    { label: 'Integrated output noise', value: totals.output_rms, unit: 'V' },
    {
      label: 'Input-referred integrated noise',
      value: totals.input_referred_rms,
      unit: inputKind === 'voltage' ? 'V' : 'A',
    },
  ]
}

export function nearestSampleIndex(x: Array<number | null>, position: number): number | null {
  let bestIndex: number | null = null
  let bestDistance = Number.POSITIVE_INFINITY
  x.forEach((value, index) => {
    if (value === null) return
    const distance = Math.abs(value - position)
    if (distance < bestDistance) {
      bestDistance = distance
      bestIndex = index
    }
  })
  return bestIndex
}

export function formatEngineering(value: number | null, unit = ''): string {
  if (value === null || !Number.isFinite(value)) return '—'
  if (value === 0) return `0${unit ? ` ${unit}` : ''}`
  const absolute = Math.abs(value)
  const exponent = Math.floor(Math.log10(absolute) / 3) * 3
  const prefixes: Record<number, string> = {
    [-15]: 'f',
    [-12]: 'p',
    [-9]: 'n',
    [-6]: 'µ',
    [-3]: 'm',
    0: '',
    3: 'k',
    6: 'M',
    9: 'G',
  }
  if (exponent in prefixes) {
    const scaled = value / 10 ** exponent
    return `${Number(scaled.toPrecision(6))} ${prefixes[exponent]}${unit}`.trim()
  }
  return `${value.toExponential(5)}${unit ? ` ${unit}` : ''}`
}

export function displayAnalysisType(type: AnalysisType): string {
  const labels: Record<AnalysisType, string> = {
    tran: 'Transient',
    ac: 'AC',
    dc: 'DC sweep',
    op: 'Operating point',
    noise: 'Noise',
    unknown: 'Unknown (failed before analysis)',
  }
  return labels[type]
}
