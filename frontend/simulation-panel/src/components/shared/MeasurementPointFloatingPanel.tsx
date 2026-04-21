import type { MeasurementFloatingPanelSignalOption } from './MeasurementFloatingPanel'
import { getUiText, type UiTextMap } from '../../uiText'

export interface MeasurementPointFloatingPanelRow {
  id: string
  label: string
  valueText: string
}

interface MeasurementPointFloatingPanelProps {
  title: string
  signalOptions: MeasurementFloatingPanelSignalOption[]
  selectedSignalId: string
  onSelectedSignalChange: (signalId: string) => void
  rows: MeasurementPointFloatingPanelRow[]
  emptyMessage: string
  uiText?: UiTextMap
}

export function MeasurementPointFloatingPanel({
  title,
  signalOptions,
  selectedSignalId,
  onSelectedSignalChange,
  rows,
  emptyMessage,
  uiText,
}: MeasurementPointFloatingPanelProps) {
  const selectedSignal = signalOptions.find((item) => item.id === selectedSignalId) ?? signalOptions[0] ?? null

  return (
    <div className="measurement-floating-panel measurement-floating-panel--point">
      <div className="measurement-floating-panel__drag-bar" data-floating-panel-drag-handle="true">
        <div className="measurement-floating-panel__title">{title}</div>
        <div className="measurement-floating-panel__drag-hint">{getUiText(uiText, 'simulation.measurement.drag_hint', 'Drag to move')}</div>
      </div>
      <div className="measurement-floating-panel__header">
        {signalOptions.length > 1 ? (
          <label className="measurement-floating-panel__selector" aria-label={getUiText(uiText, 'simulation.measurement_point.select_signal_aria', 'Select measurement-point signal')} data-floating-panel-no-drag="true">
            <span className="measurement-floating-panel__selector-label">{getUiText(uiText, 'common.signal', 'Signal')}</span>
            <select
              className="measurement-floating-panel__select"
              value={selectedSignalId}
              onChange={(event) => onSelectedSignalChange(event.target.value)}
            >
              {signalOptions.map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </select>
          </label>
        ) : selectedSignal ? (
          <div className="measurement-floating-panel__chip">{selectedSignal.label}</div>
        ) : null}
      </div>
      {rows.length ? (
        <div className="measurement-point-floating-panel__rows">
          {rows.map((row) => (
            <div key={row.id} className="measurement-point-floating-panel__row">
              <div className="measurement-point-floating-panel__label">{row.label}</div>
              <div className="measurement-point-floating-panel__value">{row.valueText}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="measurement-floating-panel__empty muted-text">{emptyMessage}</div>
      )}
    </div>
  )
}
