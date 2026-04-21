import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { getUiText } from '../../uiText'
import { CompactToolbar } from '../layout/CompactToolbar'

interface ExportTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

const EXPORT_ITEM_LABELS: Record<string, { key: string; fallback: string }> = {
  metrics: { key: 'simulation.export.metrics', fallback: 'Metrics' },
  charts: { key: 'simulation.export.charts', fallback: 'Charts' },
  waveforms: { key: 'simulation.export.waveforms', fallback: 'Waveforms' },
  analysis_info: { key: 'simulation.export.analysis_info', fallback: 'Analysis Info' },
  raw_data: { key: 'simulation.export.raw_data', fallback: 'Raw Data' },
  output_log: { key: 'simulation.export.output_log', fallback: 'Output Log' },
  op_result: { key: 'simulation.export.op_result', fallback: 'Operating Point Result' },
}

export function ExportTab({ state, bridge }: ExportTabProps) {
  const exportView = state.export_view
  const uiText = state.ui_text
  const enabledItems = exportView.items.filter((item) => item.enabled)
  const selectedCount = enabledItems.filter((item) => item.selected).length

  return (
    <div className="tab-surface">
      <CompactToolbar
        title={getUiText(uiText, 'simulation.export.title', 'Export')}
        actions={
          <button
            type="button"
            className="sim-compact-button sim-compact-button--accent"
            disabled={!exportView.can_export}
            onClick={() => bridge?.requestExport()}
          >
            {getUiText(uiText, 'simulation.export.export_selected', 'Export Selected Items')}
          </button>
        }
      />
      <div className="content-card content-card--scrollable">
        <div className="table-toolbar-grid">
          <label className="field-row field-row--grow">
            <span className="field-row__label">{getUiText(uiText, 'simulation.export.directory', 'Export Directory')}</span>
            <input className="field-input" value={exportView.selected_directory || getUiText(uiText, 'simulation.export.not_selected', 'Not Selected')} readOnly />
          </label>
          <button type="button" className="sim-compact-button" disabled={!exportView.has_result} onClick={() => bridge?.chooseExportDirectory()}>
            {getUiText(uiText, 'simulation.export.choose_directory', 'Choose Directory')}
          </button>
          <button type="button" className="sim-compact-button" disabled={!exportView.selected_directory} onClick={() => bridge?.clearExportDirectory()}>
            {getUiText(uiText, 'simulation.export.clear_directory', 'Clear Directory')}
          </button>
          <button type="button" className="sim-compact-button" disabled={!enabledItems.length} onClick={() => bridge?.setAllExportTypesSelected(true)}>
            {getUiText(uiText, 'simulation.export.select_all', 'Select All')}
          </button>
          <button type="button" className="sim-compact-button" disabled={!selectedCount} onClick={() => bridge?.setAllExportTypesSelected(false)}>
            {getUiText(uiText, 'simulation.export.clear_selection', 'Clear Selection')}
          </button>
        </div>
        <div className="export-grid">
          {exportView.items.length ? exportView.items.map((item) => (
            <label key={item.id} className={`export-item export-item--option${item.enabled ? '' : ' export-item--disabled'}`}>
              <input
                type="checkbox"
                className="export-item__checkbox"
                checked={item.selected}
                disabled={!item.enabled}
                onChange={(event: { target: { checked: boolean } }) => bridge?.setExportTypeSelected(item.id, event.target.checked)}
              />
              <span className="export-item__label">{getUiText(uiText, EXPORT_ITEM_LABELS[item.id]?.key ?? '', EXPORT_ITEM_LABELS[item.id]?.fallback ?? (item.label || item.id))}</span>
            </label>
          )) : <div className="export-item"><div className="muted-text">{getUiText(uiText, 'simulation.export.empty', 'There are no exportable items yet.')}</div></div>}
        </div>
        <div className="info-row">
          <div className="card-title">{getUiText(uiText, 'simulation.export.recent_project_directory', 'Recent Project Export Directory')}</div>
          <div className="info-row__value export-path-value">{exportView.latest_project_export_root || getUiText(uiText, 'simulation.export.none', 'None')}</div>
        </div>
      </div>
    </div>
  )
}
