import { useEffect, useMemo, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { ResponsivePane } from '../layout/ResponsivePane'
import { MeasurementFloatingPanel } from '../shared/MeasurementFloatingPanel'
import { SignalSelectionSidebar } from '../shared/SignalSelectionSidebar'
import { SeriesSvgChart } from '../shared/SeriesSvgChart'
import { formatMeasurementNumber } from '../shared/chartValueFormatting'

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
      return '时域波形图'
    }
    if (normalizedAnalysisType === 'dc') {
      return '直流扫描波形图'
    }
    return '波形图'
  }, [normalizedAnalysisType, waveform.has_waveform])
  const waveformHeaderActions = waveform.has_waveform ? (
    <>
      <button
        type="button"
        className="chart-header-button"
        disabled={!waveform.has_waveform}
        onClick={() => bridge?.resetWaveformViewport()}
      >
        Fit
      </button>
      <button
        type="button"
        className="chart-header-button"
        disabled={!waveform.has_waveform}
        onClick={() => bridge?.setCursorVisible('a', !waveform.cursor_a_visible)}
      >
        {waveform.cursor_a_visible ? '隐藏 A' : '显示 A'}
      </button>
      <button
        type="button"
        className="chart-header-button"
        disabled={!waveform.has_waveform}
        onClick={() => bridge?.setCursorVisible('b', !waveform.cursor_b_visible)}
      >
        {waveform.cursor_b_visible ? '隐藏 B' : '显示 B'}
      </button>
      <button
        type="button"
        className="chart-header-button"
        disabled={!waveform.signal_catalog.length}
        onClick={() => bridge?.clearAllSignals()}
      >
        清空信号
      </button>
      <button
        type="button"
        className="chart-header-button chart-header-button--accent"
        disabled={!waveform.can_add_to_conversation}
        onClick={() => bridge?.addToConversation('waveform')}
      >
        添加至对话
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
            selectableTitle="选择信号"
            selectableItems={selectableSignalItems}
            emptySelectableMessage="当前结果没有可用波形信号。"
            visibleTitle="已显示"
            visibleItems={visibleSignalItems}
            emptyVisibleMessage="当前没有已显示信号。"
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
                      title="测量"
                      signalOptions={measurementSignals.map((signal) => ({ id: signal.id, label: signal.label }))}
                      selectedSignalId={activeMeasurementSignal?.id ?? ''}
                      onSelectedSignalChange={setSelectedMeasurementSignalId}
                      rows={measurementPanelRows}
                      emptyMessage="当前所选信号没有可展示的测量值。"
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
              emptyMessage={waveform.has_waveform ? '当前未显示任何波形，请在左侧勾选信号。' : '当前结果没有可用波形。'}
            />
          </div>
        }
      />
    </div>
  )
}
