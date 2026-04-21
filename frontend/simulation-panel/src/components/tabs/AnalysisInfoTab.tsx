import type { SimulationMainState } from '../../types/state'
import { getUiText } from '../../uiText'

interface AnalysisInfoTabProps {
  state: SimulationMainState
}

export function AnalysisInfoTab({ state }: AnalysisInfoTabProps) {
  const info = state.analysis_info_view
  const uiText = state.ui_text
  const parameterEntries = Object.entries(info.parameters ?? {})
  const normalizedAnalysisType = (info.analysis_type || '').trim().toLowerCase()
  const analysisTypeLabel = normalizedAnalysisType
    ? getUiText(uiText, `simulation.analysis_label.${normalizedAnalysisType}`, info.analysis_type)
    : ''

  return (
    <div className="tab-surface">
      <div className="content-card content-card--scrollable">
        <div className="info-grid">
          <div className="info-row"><div className="card-title">{getUiText(uiText, 'simulation.analysis_info.analysis_type', 'Analysis Type')}</div><div className="info-row__value">{analysisTypeLabel || getUiText(uiText, 'simulation.analysis_info.not_loaded', 'Not Loaded')}</div></div>
          <div className="info-row"><div className="card-title">{getUiText(uiText, 'simulation.analysis_info.executor', 'Executor')}</div><div className="info-row__value">{info.executor || getUiText(uiText, 'simulation.analysis_info.not_loaded', 'Not Loaded')}</div></div>
          <div className="info-row"><div className="card-title">{getUiText(uiText, 'simulation.analysis_info.file', 'File')}</div><div className="info-row__value">{info.file_name || getUiText(uiText, 'simulation.analysis_info.not_loaded', 'Not Loaded')}</div></div>
          <div className="info-row"><div className="card-title">{getUiText(uiText, 'simulation.analysis_info.x_axis', 'X Axis')}</div><div className="info-row__value">{info.x_axis_label || getUiText(uiText, 'simulation.analysis_info.undefined', 'Undefined')}</div></div>
        </div>
        <div className="content-card content-card--scrollable">
          <div className="card-title">{getUiText(uiText, 'simulation.analysis_info.parameters', 'Parameters')}</div>
          <div className="parameter-list">
            {parameterEntries.length ? parameterEntries.map(([key, value]) => (
              <div key={key} className="parameter-row">
                <div className="parameter-row__key">{key}</div>
                <div className="parameter-row__value">{String(value ?? '')}</div>
              </div>
            )) : <div className="muted-text">{getUiText(uiText, 'simulation.analysis_info.empty_parameters', 'No structured parameters are available.')}</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
