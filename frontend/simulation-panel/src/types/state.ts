export type SimulationTabId =
  | 'metrics'
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
}

export interface WaveformViewState {
  has_waveform: boolean
  signal_count: number
  signal_names: string[]
  can_export: boolean
  can_add_to_conversation: boolean
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

export interface RawDataViewState {
  has_data: boolean
  row_count: number
  signal_count: number
  x_axis_label: string
}

export interface OutputLogViewState {
  has_log: boolean
  line_count: number
  can_refresh: boolean
  can_add_to_conversation: boolean
}

export interface ExportViewState {
  has_result: boolean
  available_types: string[]
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
  raw_data_view: RawDataViewState
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
    available_tabs: ['metrics', 'chart', 'waveform', 'analysis_info', 'raw_data', 'output_log', 'export'],
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
  },
  waveform_view: {
    has_waveform: false,
    signal_count: 0,
    signal_names: [],
    can_export: false,
    can_add_to_conversation: false,
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
  raw_data_view: {
    has_data: false,
    row_count: 0,
    signal_count: 0,
    x_axis_label: '',
  },
  output_log_view: {
    has_log: false,
    line_count: 0,
    can_refresh: false,
    can_add_to_conversation: false,
  },
  export_view: {
    has_result: false,
    available_types: [],
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
  const runtime = asRecord(root.simulation_runtime)
  const currentResult = asRecord(runtime.current_result)
  const surfaceTabs = asRecord(root.surface_tabs)
  const metricsView = asRecord(root.metrics_view)
  const analysisChartView = asRecord(root.analysis_chart_view)
  const waveformView = asRecord(root.waveform_view)
  const analysisInfoView = asRecord(root.analysis_info_view)
  const rawDataView = asRecord(root.raw_data_view)
  const outputLogView = asRecord(root.output_log_view)
  const exportView = asRecord(root.export_view)
  const historyResultsView = asRecord(root.history_results_view)
  const opResultView = asRecord(root.op_result_view)

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
    },
    waveform_view: {
      has_waveform: asBoolean(waveformView.has_waveform),
      signal_count: asNumber(waveformView.signal_count),
      signal_names: asStringArray(waveformView.signal_names),
      can_export: asBoolean(waveformView.can_export),
      can_add_to_conversation: asBoolean(waveformView.can_add_to_conversation),
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
    raw_data_view: {
      has_data: asBoolean(rawDataView.has_data),
      row_count: asNumber(rawDataView.row_count),
      signal_count: asNumber(rawDataView.signal_count),
      x_axis_label: asString(rawDataView.x_axis_label),
    },
    output_log_view: {
      has_log: asBoolean(outputLogView.has_log),
      line_count: asNumber(outputLogView.line_count),
      can_refresh: asBoolean(outputLogView.can_refresh),
      can_add_to_conversation: asBoolean(outputLogView.can_add_to_conversation),
    },
    export_view: {
      has_result: asBoolean(exportView.has_result),
      available_types: asStringArray(exportView.available_types),
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
