export type AnalysisType = 'tran' | 'ac' | 'dc' | 'op' | 'noise' | 'unknown'

export type JobStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type JobOrigin = 'ui_editor' | 'agent_tool'

export interface SimulationJobDto {
  job_id: string
  origin: JobOrigin
  status: JobStatus
  circuit_file: string
  session_id: string
  version: number
  submitted_at: string
  started_at: string | null
  finished_at: string | null
  cancel_requested: boolean
  result_id: string | null
  error_message: string | null
}

export interface SimulationResultSummaryDto {
  result_id: string
  result_path: string
  circuit_file: string
  analysis_type: AnalysisType
  success: boolean
  timestamp: string
  job_id: string | null
}

export interface SimulationsSnapshotResponse {
  project_id: string
  jobs: SimulationJobDto[]
  results: SimulationResultSummaryDto[]
}

export interface StartSimulationResponse {
  project_id: string
  job: SimulationJobDto
}

export interface SimulationJobResponse {
  project_id: string
  job: SimulationJobDto
}

export interface CancelSimulationResponse {
  project_id: string
  job_id: string
  cancel_requested: true
}

export interface ComplexSignal {
  _complex: true
  real: Array<number | null>
  imag: Array<number | null>
}

export type SimulationSignal = Array<number | null> | ComplexSignal

export type SignalKind =
  | 'voltage'
  | 'current'
  | 'other'

export interface NoiseTotals {
  output_rms: number
  input_referred_rms: number
}

export interface SimulationData {
  frequency: Array<number | null> | null
  time: Array<number | null> | null
  sweep: Array<number | null> | null
  signals: Record<string, SimulationSignal>
  signal_types: Record<string, SignalKind>
  noise_totals: NoiseTotals | null
}

export type MeasurementStatus = 'OK' | 'FAILED' | 'PARSE_ERROR'

export interface SimulationErrorPayload {
  code: string
  type: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  message: string
  file_path: string | null
  line_number: number | null
  context: string | null
  details: Record<string, unknown>
  recovery_attempted: boolean
  recovery_result: string | null
  recovery_suggestion: string | null
  raw_output: string | null
}

export interface SimulationMeasurement {
  name: string
  value: number | null
  status: MeasurementStatus
  statement: string
  raw_output: string
  error_message: string
}

export interface SimulationResult {
  schema_version: number
  executor: string
  file_path: string
  analysis_type: AnalysisType
  success: boolean
  source_digest: string | null
  data: SimulationData | null
  measurements: SimulationMeasurement[] | null
  error: SimulationErrorPayload | null
  raw_output: string
  timestamp: string
  duration_seconds: number
  version: number
  session_id: string
  analysis_command: string
}

export interface SimulationResultResponse {
  project_id: string
  result_id: string
  job_id: string | null
  result_path: string
  result: SimulationResult
}

export interface SurfaceMetricDto {
  name: string
  value: number | null
  status: MeasurementStatus
  statement: string
  raw_output: string
  error_message: string
}

export interface SchematicPinDto {
  name: string
  node_id: string
  role: string
}

export interface SchematicEditableFieldDto {
  field_key: string
  label: string
  raw_text: string
  display_text: string
  editable: boolean
  readonly_reason: string
  value_kind: string
}

export interface SchematicComponentDto {
  id: string
  instance_name: string
  kind: string
  symbol_kind: string
  display_name: string
  display_value: string
  pins: SchematicPinDto[]
  node_ids: string[]
  editable_fields: SchematicEditableFieldDto[]
  scope_path: string[]
  source_file: string
  symbol_variant: string
  primitive_kind: string
  primitive_source: string
  subckt_name: string
  resolved_model_name: string
  semantic_roles: string[]
  pin_roles: Record<string, string>
  port_side_hints: Record<string, 'left' | 'right' | 'top' | 'bottom'>
  label_slots: Record<string, string>
  polarity_marks: Record<string, string>
  render_hints: Record<string, unknown>
}

export interface SchematicConnectionDto {
  component_id: string
  instance_name: string
  pin_name: string
  pin_role: string
}

export interface SchematicNetDto {
  id: string
  name: string
  scope_path: string[]
  source_file: string
  connections: SchematicConnectionDto[]
}

export interface SchematicSubcircuitDto {
  name: string
  port_names: string[]
  scope_path: string[]
  source_file: string
  component_ids: string[]
  primitive_kind: string
}

export interface SchematicParseErrorDto {
  message: string
  source_file: string
  line_text: string
  line_index: number
  column_start: number
  column_end: number
}

export interface SchematicDocumentDto {
  document_id: string
  revision: string
  file_path: string
  file_name: string
  has_schematic: boolean
  title: string
  components: SchematicComponentDto[]
  nets: SchematicNetDto[]
  subcircuits: SchematicSubcircuitDto[]
  parse_errors: SchematicParseErrorDto[]
  readonly_reasons: string[]
}

export interface SurfaceDataResponse {
  project_id: string
  result_id: string
  job_id: string | null
  data: SimulationData | null
  metrics: SurfaceMetricDto[]
  output_log: string
  schematic: SchematicDocumentDto | null
}

export interface DeleteSimulationResultResponse {
  project_id: string
  result_id: string
  deleted: true
}

export interface SimulationJsonExportResponse {
  project_id: string
  job_id: string | null
  result_id: string
  download_url: string
  file_name: string
  mime_type: string
}

export interface SimulationEventPayload {
  status?: JobStatus
  message?: string
  error_message?: string
}

export interface SimulationBackendEvent {
  type: string
  sequence: number
  project_id: string | null
  payload?: SimulationEventPayload
  job_id?: string
  result_id?: string | null
  [key: string]: unknown
}

export interface ResultIdentity {
  projectId: string
  jobId: string | null
  resultId: string
}

export type AxisSide = 'left' | 'right'

export interface PlotSeries {
  id: string
  label: string
  color: string
  axis: AxisSide
  component: 'real' | 'magnitude' | 'phase' | 'density'
  unit: string
  x: Array<number | null>
  y: Array<number | null>
}

export interface PlotModel {
  analysisType: Exclude<AnalysisType, 'op'>
  title: string
  xLabel: string
  xUnit: string
  leftLabel: string
  rightLabel: string | null
  logX: boolean
  logLeftY: boolean
  logRightY: boolean
  series: PlotSeries[]
}

export interface OpRow {
  signal: string
  value: number | null
  unit: string
}

export interface ResultViewModel {
  identity: ResultIdentity
  resultPath: string
  result: SimulationResult
  data: SimulationData | null
  metrics: SurfaceMetricDto[]
  outputLog: string
  schematic: SchematicDocumentDto | null
  plot: PlotModel | null
  opRows: OpRow[]
}

export type SimulationTabId =
  | 'runs'
  | 'metrics'
  | 'chart'
  | 'waveform'
  | 'schematic'
  | 'analysis'
  | 'raw'
  | 'log'
  | 'export'

export interface SimulationFeatureProps {
  active: boolean
  projectId: string | null
  activeDocumentPath: string | null
}
