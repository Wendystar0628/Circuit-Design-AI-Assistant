import { useEffect, useMemo, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { ResponsivePane } from '../layout/ResponsivePane'
import { MeasurementFloatingPanel } from '../shared/MeasurementFloatingPanel'
import { SignalSelectionSidebar } from '../shared/SignalSelectionSidebar'
import { SeriesSvgChart } from '../shared/SeriesSvgChart'
import { formatMeasurementNumber } from '../shared/chartValueFormatting'
import { getUiText } from '../../uiText'

interface WaveformTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

function formatMeasurementDelta(valueA: number | null, valueB: number | null): string {
  if (valueA === null || valueB === null) {
    return '--'
  }
  return formatMeasurementNumber(valueB - valueA)
}

export function WaveformTab({ state, bridge }: WaveformTabProps) {
  const waveform = state.waveform_view
  const uiText = state.ui_text
  const [selectedMeasurementSignalId, setSelectedMeasurementSignalId] = useState('')
  const normalizedAnalysisType = (state.analysis_info_view.analysis_type || '').trim().toLowerCase()
  const viewWindow = useMemo(() => ({
    active: waveform.viewport.active,
    xMin: waveform.viewport.x_min,
    xMax: waveform.viewport.x_max,
    leftYMin: waveform.viewport.left_y_min,
    leftYMax: waveform.viewport.left_y_max,
    rightYMin: waveform.viewport.right_y_min,
    rightYMax: waveform.viewport.right_y_max,
  }), [waveform.viewport.active, waveform.viewport.left_y_max, waveform.viewport.left_y_min, waveform.viewport.right_y_max, waveform.viewport.right_y_min, waveform.viewport.x_max, waveform.viewport.x_min])

  const measurementSignals = useMemo(() => {
    const orderedNames = Array.from(new Set([
      ...waveform.visible_series.map((series) => series.name),
      ...Object.keys(waveform.measurement.values_a),
      ...Object.keys(waveform.measurement.values_b),
    ]))
    const visibleSeriesByName = new Map(waveform.visible_series.map((series) => [series.name, series]))
    return orderedNames.map((name) => ({
      id: name,
      label: name,
      color: visibleSeriesByName.get(name)?.color ?? '#1f77b4',
      valueA: waveform.measurement.values_a[name] ?? null,
      valueB: waveform.measurement.values_b[name] ?? null,
    }))
  }, [waveform.measurement.values_a, waveform.measurement.values_b, waveform.visible_series])
  const waveformTitle = useMemo(() => {
    if (!waveform.has_waveform) {
      return ''
    }
    if (normalizedAnalysisType === 'tran') {
      return getUiText(uiText, 'simulation.waveform.time_domain_title', 'Time-Domain Waveform')
    }
    if (normalizedAnalysisType === 'dc') {
      return getUiText(uiText, 'simulation.waveform.dc_sweep_title', 'DC Sweep Waveform')
    }
    return getUiText(uiText, 'simulation.waveform.default_title', 'Waveform')
  }, [normalizedAnalysisType, uiText, waveform.has_waveform])
  const waveformHeaderActions = waveform.has_waveform ? (
    <>
      <button
        type="button"
        className="sim-compact-button"
        disabled={!waveform.has_waveform}
        onClick={() => bridge?.resetWaveformViewport()}
      >
        {getUiText(uiText, 'common.fit', 'Fit')}
      </button>
      <button
        type="button"
        className="sim-compact-button"
        disabled={!waveform.has_waveform}
        onClick={() => bridge?.setCursorVisible('a', !waveform.cursor_a_visible)}
      >
        {waveform.cursor_a_visible
          ? getUiText(uiText, 'simulation.waveform.hide_cursor_a', 'Hide A')
          : getUiText(uiText, 'simulation.waveform.show_cursor_a', 'Show A')}
      </button>
      <button
        type="button"
        className="sim-compact-button"
        disabled={!waveform.has_waveform}
        onClick={() => bridge?.setCursorVisible('b', !waveform.cursor_b_visible)}
      >
        {waveform.cursor_b_visible
          ? getUiText(uiText, 'simulation.waveform.hide_cursor_b', 'Hide B')
          : getUiText(uiText, 'simulation.waveform.show_cursor_b', 'Show B')}
      </button>
      <button
        type="button"
        className="sim-compact-button"
        disabled={!waveform.signal_catalog.length}
        onClick={() => bridge?.clearAllSignals()}
      >
        {getUiText(uiText, 'simulation.waveform.clear_signals', 'Clear Signals')}
      </button>
      <button
        type="button"
        className="sim-compact-button sim-compact-button--accent"
        disabled={!waveform.can_add_to_conversation}
        onClick={() => bridge?.addToConversation('waveform')}
      >
        {getUiText(uiText, 'common.add_to_conversation', 'Add to Conversation')}
      </button>
    </>
  ) : undefined
  const selectableSignalItems = useMemo(() => waveform.signal_catalog.map((signal) => ({
    id: signal.name,
    label: signal.name,
    checked: signal.visible,
    onCheckedChange: (checked: boolean) => bridge?.setSignalVisible(signal.name, checked),
  })), [bridge, waveform.signal_catalog])
  const visibleSignalItems = useMemo(() => waveform.visible_series.map((series) => ({
    id: series.name,
    label: series.name,
    color: series.color,
  })), [waveform.signal_catalog, waveform.visible_series])

  const preferredMeasurementSignalId = measurementSignals[0]?.id ?? ''

  useEffect(() => {
    setSelectedMeasurementSignalId((current) => {
      if (measurementSignals.some((signal) => signal.id === current)) {
        return current
      }
      return preferredMeasurementSignalId
    })
  }, [measurementSignals, preferredMeasurementSignalId])

  const activeMeasurementSignal = useMemo(() => {
    if (!measurementSignals.length) {
      return null
    }
    return measurementSignals.find((signal) => signal.id === selectedMeasurementSignalId) ?? measurementSignals[0]
  }, [measurementSignals, selectedMeasurementSignalId])

  const measurementPanelRows = useMemo(() => {
    if (activeMeasurementSignal === null) {
      return []
    }
    return [{
      id: activeMeasurementSignal.id,
      label: activeMeasurementSignal.label,
      color: activeMeasurementSignal.color,
      valueA: formatMeasurementNumber(activeMeasurementSignal.valueA),
      valueB: formatMeasurementNumber(activeMeasurementSignal.valueB),
      delta: formatMeasurementDelta(activeMeasurementSignal.valueA, activeMeasurementSignal.valueB),
    }]
  }, [activeMeasurementSignal])

  return (
    <div className="tab-surface">
      <ResponsivePane
        sidebarConfig={{
          defaultSize: 176,
          minSize: 132,
          maxSize: 360,
          mainMinSize: 320,
          resizable: true,
        }}
        sidebar={
          <SignalSelectionSidebar
            selectableTitle={getUiText(uiText, 'simulation.waveform.select_signals', 'Select Signals')}
            selectableItems={selectableSignalItems}
            emptySelectableMessage={getUiText(uiText, 'simulation.waveform.no_selectable_signals', 'No waveform signals are available for the current result.')}
            visibleTitle={getUiText(uiText, 'simulation.waveform.visible_signals', 'Visible')}
            visibleItems={visibleSignalItems}
            emptyVisibleMessage={getUiText(uiText, 'simulation.waveform.no_visible_signals', 'No signals are currently visible.')}
            defaultPrimaryRatio={0.7}
          />
        }
        main={
          <div className="content-card content-card--canvas">
            <SeriesSvgChart
              title={waveformTitle}
              headerActions={waveformHeaderActions}
              floatingPanels={waveform.cursor_a_visible || waveform.cursor_b_visible ? [
                {
                  id: 'waveform-measurement',
                  defaultTop: 16,
                  defaultRight: 16,
                  content: (
                    <MeasurementFloatingPanel
                      title={getUiText(uiText, 'simulation.waveform.measurement', 'Measurement')}
                      signalOptions={measurementSignals.map((signal) => ({ id: signal.id, label: signal.label }))}
                      selectedSignalId={activeMeasurementSignal?.id ?? ''}
                      onSelectedSignalChange={setSelectedMeasurementSignalId}
                      rows={measurementPanelRows}
                      emptyMessage={getUiText(uiText, 'simulation.waveform.measurement_empty', 'No measurement values are available for the selected signal.')}
                      uiText={uiText}
                    />
                  ),
                },
              ] : []}
              measurementCursors={{
                cursorAVisible: waveform.cursor_a_visible,
                cursorBVisible: waveform.cursor_b_visible,
                cursorAX: waveform.measurement.cursor_a_x,
                cursorBX: waveform.measurement.cursor_b_x,
                onCursorMove: (cursorId, position) => bridge?.moveCursor(cursorId, position),
              }}
              viewWindow={viewWindow}
              onViewportChange={(nextViewWindow) => bridge?.setWaveformViewport(nextViewWindow)}
              series={waveform.visible_series}
              xLabel={waveform.x_axis_label}
              yLabel={waveform.y_label || 'Waveform'}
              secondaryYLabel={waveform.secondary_y_label}
              logX={waveform.log_x}
              emptyMessage={waveform.has_waveform
                ? getUiText(uiText, 'simulation.waveform.empty_hidden', 'No waveform is currently displayed. Select signals from the left sidebar.')
                : getUiText(uiText, 'simulation.waveform.empty_no_waveform', 'No waveform is available for the current result.')}
            />
          </div>
        }
      />
    </div>
  )
}
