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

export interface ExperimentSpec {
  analysis_command?: string
  parameters?: Record<string, string | number>
  temperature?: number | null
  solver_options?: Record<string, string | number>
  timeout_seconds?: number
}

export interface SimulationResult {
  schema_version: number
  executor: string
  file_path: string
  analysis_type: AnalysisType
  success: boolean
  source_digest: string | null
  error: SimulationErrorPayload | null
  raw_output: string | null
  timestamp: string
  duration_seconds: number
  version: number
  session_id: string
  analysis_command: string
}

export type TraceComponent = 'real' | 'imaginary' | 'magnitude' | 'db' | 'phase'
export interface TraceSpec { signal: string; reference?: string | null; component: TraceComponent }
export interface TraceAxis { kind: string; label: string; unit: string; scale: 'linear' | 'log' }
export interface TraceSignal { name: string; unit: string; signal_type: string; is_complex: boolean; components: TraceComponent[] }
export interface TraceBranch { id: number; label: string; outer_value: number | null; outer_unit: string }
export interface TraceCatalog { x_axis: TraceAxis; signals: TraceSignal[]; branches: TraceBranch[]; default_traces: TraceSpec[] }
export interface TraceSeries {
  id: string; label: string; unit: string; trace: TraceSpec
  x: Array<number | null>; y: Array<number | null>; branch_ids: Array<number | null>
  branches: TraceBranch[]; raw_point_count: number; visible_point_count: number; point_count: number; downsampled: boolean
}
export interface TraceQuery { x_axis: TraceAxis; series: TraceSeries[]; max_points: number }
export interface TraceRequest { traces: TraceSpec[]; x_min?: number | null; x_max?: number | null; max_points?: number }
export interface TraceTable {
  x_axis: TraceAxis
  columns: Array<{id: string; label: string; unit: string; trace: TraceSpec}>
  rows: Array<{index: number; x: number | null; branch_id: number; outer_value: number | null; values: Array<number | null>}>
  total_rows: number; offset: number; limit: number
}
export interface TraceCursor { x: number; y: number | null; interpolated: boolean; status?: string }
export interface TraceMeasurement {
  trace: TraceSpec; label: string; unit: string; branch_id: number; outer_value: number | null
  sample_count: number; min: number | null; max: number | null; peak_to_peak: number | null
  sample_mean: number | null; time_mean: number | null; time_rms: number | null; duration: number | null
  cursor_a: TraceCursor | null; cursor_b: TraceCursor | null
  delta_y: number | null; delta_x: number | null; slope: number | null; statistics_basis?: string
}
export interface TraceMeasurements { x_axis: TraceAxis; window: {x_min: number | null; x_max: number | null}; measurements: TraceMeasurement[]; method: string }
export interface SimulationProvenance {
  available: boolean; experiment: ExperimentSpec | null; source_digest: string | null
  engine?: {name: string; version: string | null; platform: string; execution_mode: string} | null
  omitted_measurements?: Array<{source_id: string; line_number: number; statement: string; reason: string}>
  files: Array<{path: string}>; [key: string]: unknown
}
export interface NoiseTotalsView { applicable: boolean; available: boolean; source: string; items: Array<{key: 'output_rms' | 'input_referred_rms'; value: number; unit: 'V' | 'A'}> }
export interface WorkbenchResponse {
  project_id: string; result_id: string; job_id: string | null; result_path: string
  result: SimulationResult; catalog: TraceCatalog | null; metrics: SimulationMeasurement[]
  schematic: SchematicDocumentDto | null; provenance: SimulationProvenance; noise_totals: NoiseTotalsView
}
export interface ResultViewModel {
  identity: ResultIdentity; resultPath: string; result: SimulationResult
  catalog: TraceCatalog | null; metrics: SimulationMeasurement[]
  schematic: SchematicDocumentDto | null; provenance: SimulationProvenance; noiseTotals: NoiseTotalsView
}
export type SimulationTabId = 'experiment' | 'waveforms' | 'measurements' | 'topology' | 'raw' | 'log'

export interface SimulationFeatureProps {
  active: boolean
  projectId: string | null
  projectRoot: string | null
  activeDocumentPath: string | null
  runRequestId?: number
  onRunControlChange?: (control: SimulationRunControlState) => void
}

export interface SimulationRunControlState {
  canRun: boolean
  busy: boolean
  title: string
}
