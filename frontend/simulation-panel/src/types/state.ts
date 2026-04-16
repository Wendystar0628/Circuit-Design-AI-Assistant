export type SimulationTabId =
  | 'metrics'
  | 'schematic'
  | 'chart'
  | 'waveform'
  | 'analysis_info'
  | 'raw_data'
  | 'output_log'
  | 'export'
  | 'history'
  | 'op_result'

export interface SimulationResultSummary {
  has_result: boolean
  result_path: string
  file_path: string
  file_name: string
  analysis_type: string
  analysis_label: string
  executor: string
  success: boolean
  timestamp: string
  duration_seconds: number
  version: number
  session_id: string
  x_axis_kind: string
  x_axis_label: string
  x_axis_scale: string
  requested_x_range: number[] | null
  actual_x_range: number[] | null
  has_raw_output: boolean
}

export interface SimulationRuntimeState {
  status: string
  status_message: string
  error_message: string
  project_root: string
  has_project: boolean
  current_result_path: string
  is_empty: boolean
  has_result: boolean
  has_error: boolean
  awaiting_confirmation: boolean
  current_result: SimulationResultSummary
}

export interface SurfaceTabsState {
  active_tab: SimulationTabId
  available_tabs: SimulationTabId[]
  has_history: boolean
  has_op_result: boolean
}

export interface MetricItemState {
  name: string
  display_name: string
  value: string
  unit: string
  target: string
  is_met: boolean | null
  trend: string
  category: string
  raw_value: number | null
  confidence: number
  error_message: string | null
}

export interface MetricsViewState {
  items: MetricItemState[]
  total: number
  overall_score: number
  has_goals: boolean
  can_add_to_conversation: boolean
}

export interface AnalysisChartViewState {
  has_chart: boolean
  chart_count: number
  can_export: boolean
  can_add_to_conversation: boolean
  title: string
  chart_type: string
  chart_type_display_name: string
  x_label: string
  y_label: string
  secondary_y_label: string
  log_x: boolean
  log_y: boolean
  right_log_y: boolean
  available_series: ChartSeriesMetaState[]
  visible_series: ChartSeriesSnapshotState[]
  visible_series_count: number
  viewport: SimulationSurfaceViewportState
  measurement_point: ChartMeasurementPointState
  measurement_enabled: boolean
  measurement: ChartMeasurementState
}

export interface SimulationSurfaceViewportState {
  active: boolean
  x_min: number | null
  x_max: number | null
  left_y_min: number | null
  left_y_max: number | null
  right_y_min: number | null
  right_y_max: number | null
}

export interface ChartSeriesMetaState {
  name: string
  color: string
  axis_key: string
  line_style: string
  group_key: string
  component: string
  visible: boolean
  point_count: number
}

export interface ChartSeriesSnapshotState {
  name: string
  color: string
  axis_key: string
  line_style: string
  group_key: string
  component: string
  x: number[]
  y: number[]
  point_count: number
  sampled_point_count: number
}

export interface ChartMeasurementState {
  cursor_a_x: number | null
  cursor_b_x: number | null
  values_a: Record<string, number>
  values_b: Record<string, number>
}

export interface ChartMeasurementPointValueState {
  label: string
  value_text: string
}

export interface ChartMeasurementPointState {
  enabled: boolean
  target_id: string
  point_x: number | null
  title: string
  plot_series_name: string
  plot_axis_key: string
  plot_y: number | null
  values: ChartMeasurementPointValueState[]
}

export interface WaveformViewState {
  has_waveform: boolean
  signal_count: number
  signal_names: string[]
  can_export: boolean
  can_add_to_conversation: boolean
  displayed_signal_names: string[]
  signal_catalog: WaveformSignalCatalogItemState[]
  visible_series: WaveformSeriesSnapshotState[]
  x_axis_label: string
  y_label: string
  secondary_y_label: string
  log_x: boolean
  viewport: SimulationSurfaceViewportState
  cursor_a_visible: boolean
  cursor_b_visible: boolean
  measurement: WaveformMeasurementState
}

export interface WaveformSignalCatalogItemState {
  name: string
  visible: boolean
}

export interface WaveformSeriesSnapshotState {
  name: string
  color: string
  axis_key: string
  x: number[]
  y: number[]
  point_count: number
  sampled_point_count: number
}

export interface WaveformMeasurementState {
  cursor_a_x: number | null
  cursor_b_x: number | null
  values_a: Record<string, number>
  values_b: Record<string, number>
}

export interface AnalysisInfoViewState {
  analysis_type: string
  analysis_command: string
  executor: string
  file_name: string
  x_axis_kind: string
  x_axis_label: string
  x_axis_scale: string
  requested_x_range: number[] | null
  actual_x_range: number[] | null
  parameters: Record<string, unknown>
}

export interface RawDataColumnState {
  key: string
  label: string
  width_px: number
}

export interface RawDataDocumentState {
  dataset_id: string
  version: number
  has_data: boolean
  row_count: number
  column_count: number
  row_header_width_px: number
  row_height_px: number
  column_header_height_px: number
  columns: RawDataColumnState[]
}

export interface RawDataViewportRowState {
  row_index: number
  values: string[]
}

export interface RawDataViewportState {
  dataset_id: string
  version: number
  row_start: number
  row_end: number
  col_start: number
  col_end: number
  rows: RawDataViewportRowState[]
}

export interface RawDataCopyResultState {
  dataset_id: string
  version: number
  sequence: number
  success: boolean
  row_count: number
  col_count: number
}

export interface SchematicPinState {
  name: string
  node_id: string
  role: string
}

export interface SchematicEditableFieldState {
  field_key: string
  label: string
  raw_text: string
  display_text: string
  editable: boolean
  readonly_reason: string
  value_kind: string
}

export interface SchematicComponentState {
  id: string
  instance_name: string
  kind: string
  symbol_kind: string
  display_name: string
  display_value: string
  pins: SchematicPinState[]
  node_ids: string[]
  editable_fields: SchematicEditableFieldState[]
  scope_path: string[]
  source_file: string
  symbol_variant: string
  pin_roles: Record<string, string>
  port_side_hints: Record<string, string>
  label_slots: Record<string, string>
  polarity_marks: Record<string, string>
  render_hints: Record<string, string>
}

export interface SchematicNetConnectionState {
  component_id: string
  instance_name: string
  pin_name: string
  pin_role: string
}

export interface SchematicNetState {
  id: string
  name: string
  scope_path: string[]
  source_file: string
  connections: SchematicNetConnectionState[]
}

export interface SchematicSubcircuitState {
  name: string
  port_names: string[]
  scope_path: string[]
  source_file: string
  component_ids: string[]
}

export interface SchematicParseErrorState {
  message: string
  source_file: string
  line_text: string
  line_index: number
  column_start: number
  column_end: number
}

export interface SchematicDocumentState {
  document_id: string
  revision: string
  file_path: string
  file_name: string
  has_schematic: boolean
  title: string
  components: SchematicComponentState[]
  nets: SchematicNetState[]
  subcircuits: SchematicSubcircuitState[]
  parse_errors: SchematicParseErrorState[]
  readonly_reasons: string[]
}

export interface SchematicWriteResultState {
  document_id: string
  revision: string
  request_id: string
  success: boolean
  component_id: string
  field_key: string
  result_type: string
  error_message: string
}

export interface OutputLogViewState {
  has_log: boolean
  can_add_to_conversation: boolean
  current_filter: string
  search_keyword: string
  lines: OutputLogLineState[]
  selected_line_number: number | null
}

export interface OutputLogLineState {
  line_number: number
  content: string
  level: string
}

export interface ExportItemState {
  id: string
  label: string
  selected: boolean
  enabled: boolean
}

export interface ExportViewState {
  has_result: boolean
  can_export: boolean
  items: ExportItemState[]
  selected_directory: string
  latest_project_export_root: string
}

export interface HistoryResultItemState {
  id: string
  result_path: string
  file_path: string
  file_name: string
  analysis_type: string
  success: boolean
  timestamp: string
  is_current: boolean
  can_load: boolean
}

export interface HistoryResultsViewState {
  items: HistoryResultItemState[]
  selected_result_path: string
  can_load: boolean
}

export interface OpResultRowState {
  name: string
  formatted_value: string
  raw_value: number | null
  unit: string
}

export interface OpResultSectionState {
  id: string
  title: string
  row_count: number
  rows: OpResultRowState[]
}

export interface OpResultViewState {
  is_available: boolean
  file_name: string
  analysis_command: string
  row_count: number
  section_count: number
  sections: OpResultSectionState[]
  can_add_to_conversation: boolean
}

export interface SimulationMainState {
  simulation_runtime: SimulationRuntimeState
  surface_tabs: SurfaceTabsState
  metrics_view: MetricsViewState
  analysis_chart_view: AnalysisChartViewState
  waveform_view: WaveformViewState
  analysis_info_view: AnalysisInfoViewState
  output_log_view: OutputLogViewState
  export_view: ExportViewState
  history_results_view: HistoryResultsViewState
  op_result_view: OpResultViewState
}

const EMPTY_RESULT: SimulationResultSummary = {
  has_result: false,
  result_path: '',
  file_path: '',
  file_name: '',
  analysis_type: '',
  analysis_label: '',
  executor: '',
  success: false,
  timestamp: '',
  duration_seconds: 0,
  version: 0,
  session_id: '',
  x_axis_kind: '',
  x_axis_label: '',
  x_axis_scale: '',
  requested_x_range: null,
  actual_x_range: null,
  has_raw_output: false,
}

const EMPTY_CHART_MEASUREMENT: ChartMeasurementState = {
  cursor_a_x: null,
  cursor_b_x: null,
  values_a: {},
  values_b: {},
}

const EMPTY_CHART_MEASUREMENT_POINT: ChartMeasurementPointState = {
  enabled: false,
  target_id: '',
  point_x: null,
  title: '',
  plot_series_name: '',
  plot_axis_key: 'left',
  plot_y: null,
  values: [],
}

const EMPTY_SURFACE_VIEWPORT: SimulationSurfaceViewportState = {
  active: false,
  x_min: null,
  x_max: null,
  left_y_min: null,
  left_y_max: null,
  right_y_min: null,
  right_y_max: null,
}

const EMPTY_WAVEFORM_MEASUREMENT: WaveformMeasurementState = {
  cursor_a_x: null,
  cursor_b_x: null,
  values_a: {},
  values_b: {},
}

export const EMPTY_RAW_DATA_DOCUMENT: RawDataDocumentState = {
  dataset_id: '',
  version: 0,
  has_data: false,
  row_count: 0,
  column_count: 0,
  row_header_width_px: 0,
  row_height_px: 0,
  column_header_height_px: 0,
  columns: [],
}

export const EMPTY_RAW_DATA_VIEWPORT: RawDataViewportState = {
  dataset_id: '',
  version: 0,
  row_start: 0,
  row_end: 0,
  col_start: 0,
  col_end: 0,
  rows: [],
}

export const EMPTY_RAW_DATA_COPY_RESULT: RawDataCopyResultState = {
  dataset_id: '',
  version: 0,
  sequence: 0,
  success: false,
  row_count: 0,
  col_count: 0,
}

export const EMPTY_SCHEMATIC_DOCUMENT: SchematicDocumentState = {
  document_id: '',
  revision: '',
  file_path: '',
  file_name: '',
  has_schematic: false,
  title: '',
  components: [],
  nets: [],
  subcircuits: [],
  parse_errors: [],
  readonly_reasons: [],
}

export const EMPTY_SCHEMATIC_WRITE_RESULT: SchematicWriteResultState = {
  document_id: '',
  revision: '',
  request_id: '',
  success: false,
  component_id: '',
  field_key: '',
  result_type: '',
  error_message: '',
}

export const EMPTY_SIMULATION_STATE: SimulationMainState = {
  simulation_runtime: {
    status: 'idle',
    status_message: '',
    error_message: '',
    project_root: '',
    has_project: false,
    current_result_path: '',
    is_empty: true,
    has_result: false,
    has_error: false,
    awaiting_confirmation: false,
    current_result: EMPTY_RESULT,
  },
  surface_tabs: {
    active_tab: 'metrics',
    available_tabs: ['metrics', 'schematic', 'chart', 'waveform', 'analysis_info', 'raw_data', 'output_log', 'export'],
    has_history: false,
    has_op_result: false,
  },
  metrics_view: {
    items: [],
    total: 0,
    overall_score: 0,
    has_goals: false,
    can_add_to_conversation: false,
  },
  analysis_chart_view: {
    has_chart: false,
    chart_count: 0,
    can_export: false,
    can_add_to_conversation: false,
    title: '',
    chart_type: '',
    chart_type_display_name: '',
    x_label: '',
    y_label: '',
    secondary_y_label: '',
    log_x: false,
    log_y: false,
    right_log_y: false,
    available_series: [],
    visible_series: [],
    visible_series_count: 0,
    viewport: EMPTY_SURFACE_VIEWPORT,
    measurement_point: EMPTY_CHART_MEASUREMENT_POINT,
    measurement_enabled: false,
    measurement: EMPTY_CHART_MEASUREMENT,
  },
  waveform_view: {
    has_waveform: false,
    signal_count: 0,
    signal_names: [],
    can_export: false,
    can_add_to_conversation: false,
    displayed_signal_names: [],
    signal_catalog: [],
    visible_series: [],
    x_axis_label: '',
    y_label: '',
    secondary_y_label: '',
    log_x: false,
    viewport: EMPTY_SURFACE_VIEWPORT,
    cursor_a_visible: false,
    cursor_b_visible: false,
    measurement: EMPTY_WAVEFORM_MEASUREMENT,
  },
  analysis_info_view: {
    analysis_type: '',
    analysis_command: '',
    executor: '',
    file_name: '',
    x_axis_kind: '',
    x_axis_label: '',
    x_axis_scale: '',
    requested_x_range: null,
    actual_x_range: null,
    parameters: {},
  },
  output_log_view: {
    has_log: false,
    can_add_to_conversation: false,
    current_filter: 'all',
    search_keyword: '',
    lines: [],
    selected_line_number: null,
  },
  export_view: {
    has_result: false,
    can_export: false,
    items: [],
    selected_directory: '',
    latest_project_export_root: '',
  },
  history_results_view: {
    items: [],
    selected_result_path: '',
    can_load: false,
  },
  op_result_view: {
    is_available: false,
    file_name: '',
    analysis_command: '',
    row_count: 0,
    section_count: 0,
    sections: [],
    can_add_to_conversation: false,
  },
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function asBoolean(value: unknown): boolean {
  return typeof value === 'boolean' ? value : false
}

function asNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => String(item ?? '')).filter(Boolean)
}

function asRange(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length !== 2) {
    return null
  }
  const [start, end] = value
  return [asNumber(start), asNumber(end)]
}

function asNullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function asNumberArray(value: unknown): number[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => asNumber(item))
}

function asNumberRecord(value: unknown): Record<string, number> {
  const record = asRecord(value)
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, asNumber(item)]))
}

function asStringRecord(value: unknown): Record<string, string> {
  const record = asRecord(value)
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, asString(item)]))
}

function normalizeSurfaceViewport(value: unknown): SimulationSurfaceViewportState {
  const record = asRecord(value)
  return {
    active: asBoolean(record.active),
    x_min: asNullableNumber(record.x_min),
    x_max: asNullableNumber(record.x_max),
    left_y_min: asNullableNumber(record.left_y_min),
    left_y_max: asNullableNumber(record.left_y_max),
    right_y_min: asNullableNumber(record.right_y_min),
    right_y_max: asNullableNumber(record.right_y_max),
  }
}

function normalizeChartSeriesMeta(value: unknown): ChartSeriesMetaState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      name: asString(record.name),
      color: asString(record.color),
      axis_key: asString(record.axis_key),
      line_style: asString(record.line_style),
      group_key: asString(record.group_key),
      component: asString(record.component),
      visible: asBoolean(record.visible),
      point_count: asNumber(record.point_count),
    }
  })
}

function normalizeSchematicPins(value: unknown): SchematicPinState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      name: asString(record.name),
      node_id: asString(record.node_id),
      role: asString(record.role),
    }
  })
}

function normalizeSchematicEditableFields(value: unknown): SchematicEditableFieldState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      field_key: asString(record.field_key),
      label: asString(record.label),
      raw_text: asString(record.raw_text),
      display_text: asString(record.display_text),
      editable: asBoolean(record.editable),
      readonly_reason: asString(record.readonly_reason),
      value_kind: asString(record.value_kind),
    }
  })
}

function normalizeSchematicComponents(value: unknown): SchematicComponentState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      id: asString(record.id),
      instance_name: asString(record.instance_name),
      kind: asString(record.kind),
      symbol_kind: asString(record.symbol_kind) || 'unknown',
      display_name: asString(record.display_name),
      display_value: asString(record.display_value),
      pins: normalizeSchematicPins(record.pins),
      node_ids: asStringArray(record.node_ids),
      editable_fields: normalizeSchematicEditableFields(record.editable_fields),
      scope_path: asStringArray(record.scope_path),
      source_file: asString(record.source_file),
      symbol_variant: asString(record.symbol_variant),
      pin_roles: asStringRecord(record.pin_roles),
      port_side_hints: asStringRecord(record.port_side_hints),
      label_slots: asStringRecord(record.label_slots),
      polarity_marks: asStringRecord(record.polarity_marks),
      render_hints: asStringRecord(record.render_hints),
    }
  })
}

function normalizeSchematicNets(value: unknown): SchematicNetState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    const connections = Array.isArray(record.connections)
      ? record.connections.map((connection) => {
          const entry = asRecord(connection)
          return {
            component_id: asString(entry.component_id),
            instance_name: asString(entry.instance_name),
            pin_name: asString(entry.pin_name),
            pin_role: asString(entry.pin_role),
          }
        })
      : []
    return {
      id: asString(record.id),
      name: asString(record.name),
      scope_path: asStringArray(record.scope_path),
      source_file: asString(record.source_file),
      connections,
    }
  })
}

function normalizeSchematicSubcircuits(value: unknown): SchematicSubcircuitState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      name: asString(record.name),
      port_names: asStringArray(record.port_names),
      scope_path: asStringArray(record.scope_path),
      source_file: asString(record.source_file),
      component_ids: asStringArray(record.component_ids),
    }
  })
}

function normalizeSchematicParseErrors(value: unknown): SchematicParseErrorState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      message: asString(record.message),
      source_file: asString(record.source_file),
      line_text: asString(record.line_text),
      line_index: asNumber(record.line_index),
      column_start: asNumber(record.column_start),
      column_end: asNumber(record.column_end),
    }
  })
}

function normalizeChartSeriesSnapshots(value: unknown): ChartSeriesSnapshotState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      name: asString(record.name),
      color: asString(record.color),
      axis_key: asString(record.axis_key),
      line_style: asString(record.line_style),
      group_key: asString(record.group_key),
      component: asString(record.component),
      x: asNumberArray(record.x),
      y: asNumberArray(record.y),
      point_count: asNumber(record.point_count),
      sampled_point_count: asNumber(record.sampled_point_count),
    }
  })
}

function normalizeChartMeasurement(value: unknown): ChartMeasurementState {
  const record = asRecord(value)
  return {
    cursor_a_x: asNullableNumber(record.cursor_a_x),
    cursor_b_x: asNullableNumber(record.cursor_b_x),
    values_a: asNumberRecord(record.values_a),
    values_b: asNumberRecord(record.values_b),
  }
}

function normalizeChartMeasurementPoint(value: unknown): ChartMeasurementPointState {
  const record = asRecord(value)
  const values = Array.isArray(record.values)
    ? record.values.map((item) => {
      const entry = asRecord(item)
      return {
        label: asString(entry.label),
        value_text: asString(entry.value_text),
      }
    })
    : []
  return {
    enabled: asBoolean(record.enabled),
    target_id: asString(record.target_id),
    point_x: asNullableNumber(record.point_x),
    title: asString(record.title),
    plot_series_name: asString(record.plot_series_name),
    plot_axis_key: asString(record.plot_axis_key) || 'left',
    plot_y: asNullableNumber(record.plot_y),
    values,
  }
}

function normalizeWaveformSignalCatalog(value: unknown): WaveformSignalCatalogItemState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      name: asString(record.name),
      visible: asBoolean(record.visible),
    }
  })
}

function normalizeWaveformSeriesSnapshots(value: unknown): WaveformSeriesSnapshotState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      name: asString(record.name),
      color: asString(record.color),
      axis_key: asString(record.axis_key),
      x: asNumberArray(record.x),
      y: asNumberArray(record.y),
      point_count: asNumber(record.point_count),
      sampled_point_count: asNumber(record.sampled_point_count),
    }
  })
}

function normalizeWaveformMeasurement(value: unknown): WaveformMeasurementState {
  const record = asRecord(value)
  return {
    cursor_a_x: asNullableNumber(record.cursor_a_x),
    cursor_b_x: asNullableNumber(record.cursor_b_x),
    values_a: asNumberRecord(record.values_a),
    values_b: asNumberRecord(record.values_b),
  }
}

function normalizeRawDataColumns(value: unknown): RawDataColumnState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      key: asString(record.key),
      label: asString(record.label),
      width_px: asNumber(record.width_px),
    }
  })
}

function normalizeRawDataViewportRows(value: unknown): RawDataViewportRowState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      row_index: asNumber(record.row_index),
      values: asStringArray(record.values),
    }
  })
}

function normalizeOutputLogLines(value: unknown): OutputLogLineState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      line_number: asNumber(record.line_number),
      content: asString(record.content),
      level: asString(record.level),
    }
  })
}

function normalizeExportItems(value: unknown): ExportItemState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = asRecord(item)
    return {
      id: asString(record.id),
      label: asString(record.label),
      selected: asBoolean(record.selected),
      enabled: asBoolean(record.enabled),
    }
  })
}

function normalizeOpResultSections(value: unknown): OpResultSectionState[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const section = asRecord(item)
    const rows = Array.isArray(section.rows) ? section.rows.map((row) => {
      const rowRecord = asRecord(row)
      return {
        name: asString(rowRecord.name),
        formatted_value: asString(rowRecord.formatted_value),
        raw_value: asNullableNumber(rowRecord.raw_value),
        unit: asString(rowRecord.unit),
      }
    }) : []
    return {
      id: asString(section.id),
      title: asString(section.title),
      row_count: asNumber(section.row_count),
      rows,
    }
  })
}

export function normalizeSimulationState(input: unknown): SimulationMainState {
  const root = asRecord(input)
  const simulationRuntime = asRecord(root.simulation_runtime)
  const surfaceTabs = asRecord(root.surface_tabs)
  const metricsView = asRecord(root.metrics_view)
  const analysisChartView = asRecord(root.analysis_chart_view)
  const waveformView = asRecord(root.waveform_view)
  const analysisInfoView = asRecord(root.analysis_info_view)
  const outputLogView = asRecord(root.output_log_view)
  const exportView = asRecord(root.export_view)
  const historyResultsView = asRecord(root.history_results_view)
  const opResultView = asRecord(root.op_result_view)
  const runtime = simulationRuntime
  const currentResult = asRecord(simulationRuntime.current_result)

  return {
    simulation_runtime: {
      status: asString(runtime.status) || EMPTY_SIMULATION_STATE.simulation_runtime.status,
      status_message: asString(runtime.status_message),
      error_message: asString(runtime.error_message),
      project_root: asString(runtime.project_root),
      has_project: asBoolean(runtime.has_project),
      current_result_path: asString(runtime.current_result_path),
      is_empty: asBoolean(runtime.is_empty),
      has_result: asBoolean(runtime.has_result),
      has_error: asBoolean(runtime.has_error),
      awaiting_confirmation: asBoolean(runtime.awaiting_confirmation),
      current_result: {
        has_result: asBoolean(currentResult.has_result),
        result_path: asString(currentResult.result_path),
        file_path: asString(currentResult.file_path),
        file_name: asString(currentResult.file_name),
        analysis_type: asString(currentResult.analysis_type),
        analysis_label: asString(currentResult.analysis_label),
        executor: asString(currentResult.executor),
        success: asBoolean(currentResult.success),
        timestamp: asString(currentResult.timestamp),
        duration_seconds: asNumber(currentResult.duration_seconds),
        version: asNumber(currentResult.version),
        session_id: asString(currentResult.session_id),
        x_axis_kind: asString(currentResult.x_axis_kind),
        x_axis_label: asString(currentResult.x_axis_label),
        x_axis_scale: asString(currentResult.x_axis_scale),
        requested_x_range: asRange(currentResult.requested_x_range),
        actual_x_range: asRange(currentResult.actual_x_range),
        has_raw_output: asBoolean(currentResult.has_raw_output),
      },
    },
    surface_tabs: {
      active_tab: (asString(surfaceTabs.active_tab) as SimulationTabId) || EMPTY_SIMULATION_STATE.surface_tabs.active_tab,
      available_tabs: asStringArray(surfaceTabs.available_tabs) as SimulationTabId[],
      has_history: asBoolean(surfaceTabs.has_history),
      has_op_result: asBoolean(surfaceTabs.has_op_result),
    },
    metrics_view: {
      items: Array.isArray(metricsView.items) ? (metricsView.items as MetricItemState[]) : [],
      total: asNumber(metricsView.total),
      overall_score: asNumber(metricsView.overall_score),
      has_goals: asBoolean(metricsView.has_goals),
      can_add_to_conversation: asBoolean(metricsView.can_add_to_conversation),
    },
    analysis_chart_view: {
      has_chart: asBoolean(analysisChartView.has_chart),
      chart_count: asNumber(analysisChartView.chart_count),
      can_export: asBoolean(analysisChartView.can_export),
      can_add_to_conversation: asBoolean(analysisChartView.can_add_to_conversation),
      title: asString(analysisChartView.title),
      chart_type: asString(analysisChartView.chart_type),
      chart_type_display_name: asString(analysisChartView.chart_type_display_name),
      x_label: asString(analysisChartView.x_label),
      y_label: asString(analysisChartView.y_label),
      secondary_y_label: asString(analysisChartView.secondary_y_label),
      log_x: asBoolean(analysisChartView.log_x),
      log_y: asBoolean(analysisChartView.log_y),
      right_log_y: asBoolean(analysisChartView.right_log_y),
      available_series: normalizeChartSeriesMeta(analysisChartView.available_series),
      visible_series: normalizeChartSeriesSnapshots(analysisChartView.visible_series),
      visible_series_count: asNumber(analysisChartView.visible_series_count),
      viewport: normalizeSurfaceViewport(analysisChartView.viewport),
      measurement_point: normalizeChartMeasurementPoint(analysisChartView.measurement_point),
      measurement_enabled: asBoolean(analysisChartView.measurement_enabled),
      measurement: normalizeChartMeasurement(analysisChartView.measurement),
    },
    waveform_view: {
      has_waveform: asBoolean(waveformView.has_waveform),
      signal_count: asNumber(waveformView.signal_count),
      signal_names: asStringArray(waveformView.signal_names),
      can_export: asBoolean(waveformView.can_export),
      can_add_to_conversation: asBoolean(waveformView.can_add_to_conversation),
      displayed_signal_names: asStringArray(waveformView.displayed_signal_names),
      signal_catalog: normalizeWaveformSignalCatalog(waveformView.signal_catalog),
      visible_series: normalizeWaveformSeriesSnapshots(waveformView.visible_series),
      x_axis_label: asString(waveformView.x_axis_label),
      y_label: asString(waveformView.y_label),
      secondary_y_label: asString(waveformView.secondary_y_label),
      log_x: asBoolean(waveformView.log_x),
      viewport: normalizeSurfaceViewport(waveformView.viewport),
      cursor_a_visible: asBoolean(waveformView.cursor_a_visible),
      cursor_b_visible: asBoolean(waveformView.cursor_b_visible),
      measurement: normalizeWaveformMeasurement(waveformView.measurement),
    },
    analysis_info_view: {
      analysis_type: asString(analysisInfoView.analysis_type),
      analysis_command: asString(analysisInfoView.analysis_command),
      executor: asString(analysisInfoView.executor),
      file_name: asString(analysisInfoView.file_name),
      x_axis_kind: asString(analysisInfoView.x_axis_kind),
      x_axis_label: asString(analysisInfoView.x_axis_label),
      x_axis_scale: asString(analysisInfoView.x_axis_scale),
      requested_x_range: asRange(analysisInfoView.requested_x_range),
      actual_x_range: asRange(analysisInfoView.actual_x_range),
      parameters: asRecord(analysisInfoView.parameters),
    },
    output_log_view: {
      has_log: asBoolean(outputLogView.has_log),
      can_add_to_conversation: asBoolean(outputLogView.can_add_to_conversation),
      current_filter: asString(outputLogView.current_filter) || 'all',
      search_keyword: asString(outputLogView.search_keyword),
      lines: normalizeOutputLogLines(outputLogView.lines),
      selected_line_number: asNullableNumber(outputLogView.selected_line_number),
    },
    export_view: {
      has_result: asBoolean(exportView.has_result),
      can_export: asBoolean(exportView.can_export),
      items: normalizeExportItems(exportView.items),
      selected_directory: asString(exportView.selected_directory),
      latest_project_export_root: asString(exportView.latest_project_export_root),
    },
    history_results_view: {
      items: Array.isArray(historyResultsView.items) ? (historyResultsView.items as HistoryResultItemState[]) : [],
      selected_result_path: asString(historyResultsView.selected_result_path),
      can_load: asBoolean(historyResultsView.can_load),
    },
    op_result_view: {
      is_available: asBoolean(opResultView.is_available),
      file_name: asString(opResultView.file_name),
      analysis_command: asString(opResultView.analysis_command),
      row_count: asNumber(opResultView.row_count),
      section_count: asNumber(opResultView.section_count),
      sections: normalizeOpResultSections(opResultView.sections),
      can_add_to_conversation: asBoolean(opResultView.can_add_to_conversation),
    },
  }
}

export function normalizeRawDataDocument(input: unknown): RawDataDocumentState {
  const rawDataDocument = asRecord(input)
  return {
    dataset_id: asString(rawDataDocument.dataset_id),
    version: asNumber(rawDataDocument.version),
    has_data: asBoolean(rawDataDocument.has_data),
    row_count: asNumber(rawDataDocument.row_count),
    column_count: asNumber(rawDataDocument.column_count),
    row_header_width_px: asNumber(rawDataDocument.row_header_width_px),
    row_height_px: asNumber(rawDataDocument.row_height_px),
    column_header_height_px: asNumber(rawDataDocument.column_header_height_px),
    columns: normalizeRawDataColumns(rawDataDocument.columns),
  }
}

export function normalizeSchematicDocument(input: unknown): SchematicDocumentState {
  const schematicDocument = asRecord(input)
  return {
    document_id: asString(schematicDocument.document_id),
    revision: asString(schematicDocument.revision),
    file_path: asString(schematicDocument.file_path),
    file_name: asString(schematicDocument.file_name),
    has_schematic: asBoolean(schematicDocument.has_schematic),
    title: asString(schematicDocument.title),
    components: normalizeSchematicComponents(schematicDocument.components),
    nets: normalizeSchematicNets(schematicDocument.nets),
    subcircuits: normalizeSchematicSubcircuits(schematicDocument.subcircuits),
    parse_errors: normalizeSchematicParseErrors(schematicDocument.parse_errors),
    readonly_reasons: asStringArray(schematicDocument.readonly_reasons),
  }
}

export function normalizeSchematicWriteResult(input: unknown): SchematicWriteResultState {
  const schematicWriteResult = asRecord(input)
  return {
    document_id: asString(schematicWriteResult.document_id),
    revision: asString(schematicWriteResult.revision),
    request_id: asString(schematicWriteResult.request_id),
    success: asBoolean(schematicWriteResult.success),
    component_id: asString(schematicWriteResult.component_id),
    field_key: asString(schematicWriteResult.field_key),
    result_type: asString(schematicWriteResult.result_type),
    error_message: asString(schematicWriteResult.error_message),
  }
}

export function normalizeRawDataViewport(input: unknown): RawDataViewportState {
  const rawDataViewport = asRecord(input)
  return {
    dataset_id: asString(rawDataViewport.dataset_id),
    version: asNumber(rawDataViewport.version),
    row_start: asNumber(rawDataViewport.row_start),
    row_end: asNumber(rawDataViewport.row_end),
    col_start: asNumber(rawDataViewport.col_start),
    col_end: asNumber(rawDataViewport.col_end),
    rows: normalizeRawDataViewportRows(rawDataViewport.rows),
  }
}

export function normalizeRawDataCopyResult(input: unknown): RawDataCopyResultState {
  const rawDataCopyResult = asRecord(input)
  return {
    dataset_id: asString(rawDataCopyResult.dataset_id),
    version: asNumber(rawDataCopyResult.version),
    sequence: asNumber(rawDataCopyResult.sequence),
    success: asBoolean(rawDataCopyResult.success),
    row_count: asNumber(rawDataCopyResult.row_count),
    col_count: asNumber(rawDataCopyResult.col_count),
  }
}
