import { getUiText, type UiTextMap } from '../../uiText'

export interface MeasurementFloatingPanelSignalOption {
  id: string
  label: string
}

export interface MeasurementFloatingPanelRow {
  id: string
  label: string
  color: string
  valueA: string
  valueB: string
  delta: string
}

interface MeasurementFloatingPanelProps {
  title: string
  signalOptions: MeasurementFloatingPanelSignalOption[]
  selectedSignalId: string
  onSelectedSignalChange: (signalId: string) => void
  rows: MeasurementFloatingPanelRow[]
  emptyMessage: string
  uiText?: UiTextMap
}

export function MeasurementFloatingPanel({
  title,
  signalOptions,
  selectedSignalId,
  onSelectedSignalChange,
  rows,
  emptyMessage,
  uiText,
}: MeasurementFloatingPanelProps) {
  const selectedSignal = signalOptions.find((item) => item.id === selectedSignalId) ?? signalOptions[0] ?? null

  return (
    <div className="measurement-floating-panel">
      <div className="measurement-floating-panel__drag-bar" data-floating-panel-drag-handle="true">
        <div className="measurement-floating-panel__title">{title}</div>
        <div className="measurement-floating-panel__drag-hint">{getUiText(uiText, 'simulation.measurement.drag_hint', 'Drag to move')}</div>
      </div>
      <div className="measurement-floating-panel__header">
        {signalOptions.length > 1 ? (
          <label className="measurement-floating-panel__selector" aria-label={getUiText(uiText, 'simulation.measurement.select_signal_aria', 'Select measurement signal')} data-floating-panel-no-drag="true">
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
        <>
          <div className="measurement-floating-panel__columns" aria-hidden="true">
            <span>{getUiText(uiText, 'common.signal', 'Signal')}</span>
            <span>A</span>
            <span>B</span>
            <span>Δ</span>
          </div>
          <div className="measurement-floating-panel__rows">
            {rows.map((row) => (
              <div key={row.id} className="measurement-floating-panel__row">
                <div className="measurement-floating-panel__signal">
                  <svg className="measurement-floating-panel__swatch" viewBox="0 0 10 10" aria-hidden="true" focusable="false">
                    <circle cx="5" cy="5" r="4" fill={row.color} />
                  </svg>
                  <span className="measurement-floating-panel__signal-name">{row.label}</span>
                </div>
                <div className="measurement-floating-panel__value">{row.valueA}</div>
                <div className="measurement-floating-panel__value">{row.valueB}</div>
                <div className="measurement-floating-panel__value">{row.delta}</div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="measurement-floating-panel__empty muted-text">{emptyMessage}</div>
      )}
    </div>
  )
}
