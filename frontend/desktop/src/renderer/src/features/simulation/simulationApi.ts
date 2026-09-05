import { api } from '../../lib/api'
import type {
  CancelSimulationResponse,
  DeleteSimulationResultResponse,
  JobStatus,
  JobOrigin,
  SimulationBackendEvent,
  SimulationEventPayload,
  SimulationJobDto,
  SimulationJobResponse,
  SimulationJsonExportResponse,
  SimulationResultSummaryDto,
  SimulationsSnapshotResponse,
  StartSimulationResponse,
  SchematicDocumentDto,
  ExperimentSpec,
  WorkbenchResponse,
  TraceRequest,
  TraceQuery,
  TraceTable,
  TraceMeasurements,
} from './types'

const JOB_STATUSES = new Set<JobStatus>([
  'pending',
  'running',
  'completed',
  'failed',
  'cancelled',
])
const JOB_ORIGINS = new Set<JobOrigin>(['ui_editor', 'agent_tool'])
const ANALYSIS_TYPES = new Set(['tran', 'ac', 'dc', 'op', 'noise', 'unknown'])

const SIMULATION_EVENT_TYPES = new Set([
  'simulation.started',
  'simulation.completed',
  'simulation.failed',
  'simulation.cancelled',
])

export interface NormalizedSimulationEvent {
  type: 'simulation.started' | 'simulation.completed' | 'simulation.failed' | 'simulation.cancelled'
  sequence: number
  projectId: string
  jobId: string
  resultId: string | null
  message: string | null
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be an object`)
  }
  return value as Record<string, unknown>
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${label} must be a non-empty string`)
  }
  return value
}

function plainString(value: unknown, label: string): string {
  if (typeof value !== 'string') {
    throw new Error(`${label} must be a string`)
  }
  return value
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) {
    return null
  }
  return stringValue(value, label)
}

function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') {
    throw new Error(`${label} must be a boolean`)
  }
  return value
}

function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`)
  }
  return value.map((item, index) => stringValue(item, `${label}[${index}]`))
}

function stringRecord(value: unknown, label: string): Record<string, string> {
  const record = objectValue(value, label)
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [
    key,
    stringValue(item, `${label}.${key}`),
  ]))
}

function schematicValue(value: unknown): SchematicDocumentDto {
  const record = objectValue(value, 'surface data response.schematic')
  if (!Array.isArray(record.components) || !Array.isArray(record.nets)) {
    throw new Error('schematic must contain components and nets arrays')
  }
  const components = record.components.map((rawComponent, componentIndex) => {
    const label = `schematic.components[${componentIndex}]`
    const component = objectValue(rawComponent, label)
    if (!Array.isArray(component.pins) || !Array.isArray(component.editable_fields)) {
      throw new Error(`${label} must contain pins and editable_fields arrays`)
    }
    const portHints = stringRecord(component.port_side_hints, `${label}.port_side_hints`)
    for (const [pin, side] of Object.entries(portHints)) {
      if (side !== 'left' && side !== 'right' && side !== 'top' && side !== 'bottom') {
        throw new Error(`${label}.port_side_hints.${pin} is invalid`)
      }
    }
    return {
      id: stringValue(component.id, `${label}.id`),
      instance_name: stringValue(component.instance_name, `${label}.instance_name`),
      kind: stringValue(component.kind, `${label}.kind`),
      symbol_kind: stringValue(component.symbol_kind, `${label}.symbol_kind`),
      display_name: stringValue(component.display_name, `${label}.display_name`),
      display_value: plainString(component.display_value, `${label}.display_value`),
      pins: component.pins.map((rawPin, pinIndex) => {
        const pin = objectValue(rawPin, `${label}.pins[${pinIndex}]`)
        return {
          name: stringValue(pin.name, `${label}.pins[${pinIndex}].name`),
          node_id: stringValue(pin.node_id, `${label}.pins[${pinIndex}].node_id`),
          role: plainString(pin.role, `${label}.pins[${pinIndex}].role`),
        }
      }),
      node_ids: stringArray(component.node_ids, `${label}.node_ids`),
      editable_fields: component.editable_fields.map((rawField, fieldIndex) => {
        const field = objectValue(rawField, `${label}.editable_fields[${fieldIndex}]`)
        return {
          field_key: stringValue(field.field_key, `${label}.editable_fields[${fieldIndex}].field_key`),
          label: stringValue(field.label, `${label}.editable_fields[${fieldIndex}].label`),
          raw_text: plainString(field.raw_text, `${label}.editable_fields[${fieldIndex}].raw_text`),
          display_text: plainString(field.display_text, `${label}.editable_fields[${fieldIndex}].display_text`),
          editable: booleanValue(field.editable, `${label}.editable_fields[${fieldIndex}].editable`),
          readonly_reason: plainString(field.readonly_reason, `${label}.editable_fields[${fieldIndex}].readonly_reason`),
          value_kind: stringValue(field.value_kind, `${label}.editable_fields[${fieldIndex}].value_kind`),
        }
      }),
      scope_path: stringArray(component.scope_path, `${label}.scope_path`),
      source_file: plainString(component.source_file, `${label}.source_file`),
      symbol_variant: plainString(component.symbol_variant, `${label}.symbol_variant`),
      primitive_kind: plainString(component.primitive_kind, `${label}.primitive_kind`),
      primitive_source: plainString(component.primitive_source, `${label}.primitive_source`),
      subckt_name: plainString(component.subckt_name, `${label}.subckt_name`),
      resolved_model_name: plainString(component.resolved_model_name, `${label}.resolved_model_name`),
      semantic_roles: stringArray(component.semantic_roles, `${label}.semantic_roles`),
      pin_roles: stringRecord(component.pin_roles, `${label}.pin_roles`),
      port_side_hints: portHints as Record<string, 'left' | 'right' | 'top' | 'bottom'>,
      label_slots: stringRecord(component.label_slots, `${label}.label_slots`),
      polarity_marks: stringRecord(component.polarity_marks, `${label}.polarity_marks`),
      render_hints: objectValue(component.render_hints, `${label}.render_hints`),
    }
  })
  const nets = record.nets.map((rawNet, netIndex) => {
    const label = `schematic.nets[${netIndex}]`
    const net = objectValue(rawNet, label)
    if (!Array.isArray(net.connections)) throw new Error(`${label}.connections must be an array`)
    return {
      id: stringValue(net.id, `${label}.id`),
      name: stringValue(net.name, `${label}.name`),
      scope_path: stringArray(net.scope_path, `${label}.scope_path`),
      source_file: plainString(net.source_file, `${label}.source_file`),
      connections: net.connections.map((rawConnection, connectionIndex) => {
        const connection = objectValue(rawConnection, `${label}.connections[${connectionIndex}]`)
        return {
          component_id: stringValue(connection.component_id, `${label}.connections[${connectionIndex}].component_id`),
          instance_name: stringValue(connection.instance_name, `${label}.connections[${connectionIndex}].instance_name`),
          pin_name: stringValue(connection.pin_name, `${label}.connections[${connectionIndex}].pin_name`),
          pin_role: plainString(connection.pin_role, `${label}.connections[${connectionIndex}].pin_role`),
        }
      }),
    }
  })
  const subcircuits = Array.isArray(record.subcircuits) ? record.subcircuits.map((rawSubcircuit, index) => {
    const label = `schematic.subcircuits[${index}]`
    const subcircuit = objectValue(rawSubcircuit, label)
    return {
      name: stringValue(subcircuit.name, `${label}.name`),
      port_names: stringArray(subcircuit.port_names, `${label}.port_names`),
      scope_path: stringArray(subcircuit.scope_path, `${label}.scope_path`),
      source_file: plainString(subcircuit.source_file, `${label}.source_file`),
      component_ids: stringArray(subcircuit.component_ids, `${label}.component_ids`),
      primitive_kind: plainString(subcircuit.primitive_kind, `${label}.primitive_kind`),
    }
  }) : []
  const parseErrors = Array.isArray(record.parse_errors) ? record.parse_errors.map((rawError, index) => {
    const label = `schematic.parse_errors[${index}]`
    const error = objectValue(rawError, label)
    const integer = (item: unknown, itemLabel: string) => {
      if (typeof item !== 'number' || !Number.isSafeInteger(item)) throw new Error(`${itemLabel} must be an integer`)
      return item
    }
    return {
      message: stringValue(error.message, `${label}.message`),
      source_file: plainString(error.source_file, `${label}.source_file`),
      line_text: plainString(error.line_text, `${label}.line_text`),
      line_index: integer(error.line_index, `${label}.line_index`),
      column_start: integer(error.column_start, `${label}.column_start`),
      column_end: integer(error.column_end, `${label}.column_end`),
    }
  }) : []
  return {
    document_id: stringValue(record.document_id, 'schematic.document_id'),
    revision: stringValue(record.revision, 'schematic.revision'),
    file_path: plainString(record.file_path, 'schematic.file_path'),
    file_name: plainString(record.file_name, 'schematic.file_name'),
    has_schematic: booleanValue(record.has_schematic, 'schematic.has_schematic'),
    title: stringValue(record.title, 'schematic.title'),
    components,
    nets,
    subcircuits,
    parse_errors: parseErrors,
    readonly_reasons: stringArray(record.readonly_reasons, 'schematic.readonly_reasons'),
  }
}

function exactProject(record: Record<string, unknown>, projectId: string, label: string): void {
  if (record.project_id !== projectId) {
    throw new Error(`${label} belongs to another project`)
  }
}

function exactResult(record: Record<string, unknown>, resultId: string, label: string): void {
  if (record.result_id !== resultId) {
    throw new Error(`${label} belongs to another result`)
  }
}

function jobValue(value: unknown, label: string): SimulationJobDto {
  const record = objectValue(value, label)
  const origin = stringValue(record.origin, `${label}.origin`)
  if (!JOB_ORIGINS.has(origin as JobOrigin)) {
    throw new Error(`${label}.origin is invalid`)
  }
  const status = stringValue(record.status, `${label}.status`)
  if (!JOB_STATUSES.has(status as JobStatus)) {
    throw new Error(`${label}.status is invalid`)
  }
  const resultId = nullableString(record.result_id, `${label}.result_id`)
  const errorMessage = record.error_message === null
    ? null
    : plainString(record.error_message, `${label}.error_message`)
  const version = record.version
  if (typeof version !== 'number' || !Number.isSafeInteger(version) || version < 0) {
    throw new Error(`${label}.version must be a non-negative integer`)
  }
  return {
    job_id: stringValue(record.job_id, `${label}.job_id`),
    origin: origin as JobOrigin,
    status: status as JobStatus,
    circuit_file: stringValue(record.circuit_file, `${label}.circuit_file`),
    session_id: plainString(record.session_id, `${label}.session_id`),
    version,
    submitted_at: stringValue(record.submitted_at, `${label}.submitted_at`),
    started_at: record.started_at === null ? null : stringValue(record.started_at, `${label}.started_at`),
    finished_at: record.finished_at === null ? null : stringValue(record.finished_at, `${label}.finished_at`),
    cancel_requested: booleanValue(record.cancel_requested, `${label}.cancel_requested`),
    result_id: resultId,
    error_message: errorMessage,
  }
}

function resultSummaryValue(value: unknown, label: string): SimulationResultSummaryDto {
  const record = objectValue(value, label)
  const analysisType = stringValue(record.analysis_type, `${label}.analysis_type`)
  if (!ANALYSIS_TYPES.has(analysisType)) {
    throw new Error(`${label}.analysis_type is unsupported`)
  }
  const success = booleanValue(record.success, `${label}.success`)
  if (success && analysisType === 'unknown') {
    throw new Error(`${label} cannot be successful with unknown analysis type`)
  }
  return {
    result_id: stringValue(record.result_id, `${label}.result_id`),
    result_path: stringValue(record.result_path, `${label}.result_path`),
    circuit_file: stringValue(record.circuit_file, `${label}.circuit_file`),
    analysis_type: analysisType as SimulationResultSummaryDto['analysis_type'],
    success,
    timestamp: stringValue(record.timestamp, `${label}.timestamp`),
    job_id: nullableString(record.job_id, `${label}.job_id`),
  }
}

function projectPath(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}`
}

function simulationsPath(projectId: string): string {
  return `${projectPath(projectId)}/simulations`
}

function resultsPath(projectId: string): string {
  return `${projectPath(projectId)}/simulation-results`
}

function jobPath(projectId: string, jobId: string): string {
  return `${simulationsPath(projectId)}/jobs/${encodeURIComponent(jobId)}`
}

function resultPath(projectId: string, resultId: string): string {
  return `${resultsPath(projectId)}/${encodeURIComponent(resultId)}`
}

function verifyJobResponse(value: unknown, projectId: string, label: string): SimulationJobResponse {
  const record = objectValue(value, label)
  exactProject(record, projectId, label)
  return { project_id: projectId, job: jobValue(record.job, `${label}.job`) }
}

export async function fetchSimulationSnapshot(projectId: string): Promise<SimulationsSnapshotResponse> {
  const value: unknown = await api.get(simulationsPath(projectId))
  const record = objectValue(value, 'simulation snapshot')
  exactProject(record, projectId, 'simulation snapshot')
  if (!Array.isArray(record.jobs) || !Array.isArray(record.results)) {
    throw new Error('simulation snapshot must contain jobs and results arrays')
  }
  return {
    project_id: projectId,
    jobs: record.jobs.map((job, index) => jobValue(job, `simulation snapshot.jobs[${index}]`)),
    results: record.results.map((result, index) => resultSummaryValue(result, `simulation snapshot.results[${index}]`)),
  }
}

export async function startSimulation(
  projectId: string,
  circuitPath: string,
  experiment: ExperimentSpec,
): Promise<StartSimulationResponse> {
  return verifyJobResponse(
    await api.post(simulationsPath(projectId), { circuit_path: circuitPath, experiment }),
    projectId,
    'start simulation response',
  )
}

export async function fetchSimulationJob(projectId: string, jobId: string): Promise<SimulationJobResponse> {
  const response = verifyJobResponse(
    await api.get(jobPath(projectId, jobId)),
    projectId,
    'simulation job response',
  )
  if (response.job.job_id !== jobId) {
    throw new Error('simulation job response belongs to another job')
  }
  return response
}

export async function cancelSimulation(projectId: string, jobId: string): Promise<CancelSimulationResponse> {
  const value: unknown = await api.post(`${jobPath(projectId, jobId)}/cancel`, {})
  const record = objectValue(value, 'cancel simulation response')
  exactProject(record, projectId, 'cancel simulation response')
  if (record.job_id !== jobId || record.cancel_requested !== true) {
    throw new Error('cancel simulation acknowledgement has the wrong job identity')
  }
  return { project_id: projectId, job_id: jobId, cancel_requested: true }
}

export async function fetchWorkbench(projectId: string, resultId: string): Promise<WorkbenchResponse> {
  const value: unknown = await api.get(`${resultPath(projectId, resultId)}/workbench`)
  const record = objectValue(value, 'simulation workbench')
  exactProject(record, projectId, 'simulation workbench')
  exactResult(record, resultId, 'simulation workbench')
  const result = objectValue(record.result, 'workbench.result')
  if (typeof result.success !== 'boolean' || !ANALYSIS_TYPES.has(String(result.analysis_type))) throw new Error('Workbench has an invalid simulation outcome.')
  const catalog = record.catalog === null ? null : objectValue(record.catalog, 'workbench.catalog')
  if (catalog && (!Array.isArray(catalog.signals) || !Array.isArray(catalog.default_traces))) throw new Error('Workbench signal catalog is invalid.')
  if (!Array.isArray(record.metrics)) throw new Error('Workbench measurements are invalid.')
  return {
    project_id: projectId, result_id: resultId,
    job_id: nullableString(record.job_id, 'workbench.job_id'),
    result_path: stringValue(record.result_path, 'workbench.result_path'),
    result: result as unknown as WorkbenchResponse['result'],
    catalog: catalog as unknown as WorkbenchResponse['catalog'],
    metrics: record.metrics as WorkbenchResponse['metrics'],
    schematic: record.schematic === null ? null : schematicValue(record.schematic),
    provenance: objectValue(record.provenance, 'workbench.provenance') as unknown as WorkbenchResponse['provenance'],
    noise_totals: objectValue(record.noise_totals, 'workbench.noise_totals') as unknown as WorkbenchResponse['noise_totals'],
  }
}

export async function queryTraces(projectId: string, resultId: string, request: TraceRequest): Promise<TraceQuery> {
  const response = await api.post<TraceQuery>(`${resultPath(projectId, resultId)}/traces`, {traces: request.traces, x_min: request.x_min ?? null, x_max: request.x_max ?? null, max_points: request.max_points ?? 1800})
  if (!Array.isArray(response.series) || !response.x_axis) throw new Error('Invalid waveform query response.')
  for (const series of response.series) {
    if (!Array.isArray(series.x) || !Array.isArray(series.y) || series.x.length !== series.y.length) throw new Error('Waveform coordinate lengths disagree.')
    if (series.x.some((value) => value !== null && !Number.isFinite(value)) || series.y.some((value) => value !== null && !Number.isFinite(value))) throw new Error('Waveform contains nonfinite coordinates.')
  }
  return response
}
export function queryTraceTable(projectId: string, resultId: string, request: TraceRequest & {offset: number; limit: number}): Promise<TraceTable> {
  return api.post(`${resultPath(projectId, resultId)}/trace-table`, {traces: request.traces, offset: request.offset, limit: request.limit})
}
export function queryTraceMeasurements(projectId: string, resultId: string, request: TraceRequest & {cursor_a: number | null; cursor_b: number | null}): Promise<TraceMeasurements> {
  return api.post(`${resultPath(projectId, resultId)}/trace-measurements`, {traces: request.traces, x_min: request.x_min ?? null, x_max: request.x_max ?? null, cursor_a: request.cursor_a, cursor_b: request.cursor_b})
}
export async function exportTraceCsv(projectId: string, resultId: string, request: TraceRequest): Promise<Blob> {
  // This endpoint returns text/csv; the common API client preserves its body as a string.
  const csv = await api.post<string>(`${resultPath(projectId, resultId)}/trace-exports`, {traces: request.traces, format: 'csv'})
  return new Blob([csv], {type: 'text/csv;charset=utf-8'})
}
export function fetchExperimentInputs(projectId: string, resultId: string): Promise<Blob> {
  return api.getBlob(`${resultPath(projectId, resultId)}/inputs`)
}
export async function replaySimulation(projectId: string, resultId: string): Promise<StartSimulationResponse> {
  return verifyJobResponse(await api.post(`${resultPath(projectId, resultId)}/replay`, {}), projectId, 'replay simulation response')
}

export async function deleteSimulationResult(
  projectId: string,
  resultId: string,
): Promise<DeleteSimulationResultResponse> {
  const value: unknown = await api.delete(resultPath(projectId, resultId))
  const record = objectValue(value, 'delete simulation result response')
  exactProject(record, projectId, 'delete simulation result response')
  exactResult(record, resultId, 'delete simulation result response')
  if (record.deleted !== true) {
    throw new Error('backend did not confirm result deletion')
  }
  return { project_id: projectId, result_id: resultId, deleted: true }
}

export async function requestCanonicalJsonExport(
  projectId: string,
  resultId: string,
  expectedJobId: string | null,
): Promise<SimulationJsonExportResponse> {
  const value: unknown = await api.post(`${resultPath(projectId, resultId)}/exports`, {
    format: 'json',
    surface: 'data',
  })
  const record = objectValue(value, 'simulation export response')
  exactProject(record, projectId, 'simulation export response')
  exactResult(record, resultId, 'simulation export response')
  const jobId = nullableString(record.job_id, 'simulation export response.job_id')
  if (jobId !== expectedJobId) {
    throw new Error('simulation export response belongs to another job')
  }
  return {
    project_id: projectId,
    job_id: jobId,
    result_id: resultId,
    download_url: stringValue(record.download_url, 'simulation export response.download_url'),
    file_name: stringValue(record.file_name, 'simulation export response.file_name'),
    mime_type: stringValue(record.mime_type, 'simulation export response.mime_type'),
  }
}

export function fetchSimulationExportBlob(downloadUrl: string): Promise<Blob> {
  return api.getBlob(downloadUrl)
}

export function normalizeSimulationEvent(event: SimulationBackendEvent): NormalizedSimulationEvent | null {
  if (
    !SIMULATION_EVENT_TYPES.has(event.type)
    || typeof event.sequence !== 'number'
    || !Number.isSafeInteger(event.sequence)
    || typeof event.project_id !== 'string'
    || !event.project_id
  ) {
    return null
  }
  const payload = event.payload && typeof event.payload === 'object'
    ? event.payload as SimulationEventPayload
    : null
  if (!payload) {
    return null
  }
  const jobId = event.job_id
  if (typeof jobId !== 'string' || !jobId) {
    return null
  }
  const resultId = event.result_id === undefined ? null : event.result_id
  if (resultId !== null && (typeof resultId !== 'string' || !resultId)) {
    return null
  }
  const rawMessage = payload.error_message ?? payload.message
  return {
    type: event.type as NormalizedSimulationEvent['type'],
    sequence: event.sequence,
    projectId: event.project_id,
    jobId,
    resultId,
    message: typeof rawMessage === 'string' && rawMessage.trim() ? rawMessage : null,
  }
}

export function subscribeToSimulationEvents(
  handler: (event: NormalizedSimulationEvent) => void,
): () => void {
  return api.subscribe((event) => {
    const normalized = normalizeSimulationEvent(event as SimulationBackendEvent)
    if (normalized) {
      handler(normalized)
    }
  })
}
