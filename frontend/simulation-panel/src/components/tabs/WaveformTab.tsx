import { useEffect, useMemo, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'
import { ResponsivePane } from '../layout/ResponsivePane'
import { MeasurementFloatingPanel } from '../shared/MeasurementFloatingPanel'
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
      <CompactToolbar
        title="波形"
        description={waveform.x_axis_label ? `X 轴：${waveform.x_axis_label}` : '统一前端波形显示层，直接消费后端权威 snapshot。'}
        actions={
          <>
            <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.requestFit()}>
              Fit
            </button>
            <button type="button" className="toolbar-button-secondary" disabled={!waveform.has_waveform} onClick={() => bridge?.setCursorVisible('a', !waveform.cursor_a_visible)}>
              {waveform.cursor_a_visible ? '隐藏 A' : '显示 A'}
            </button>
            <button type="button" className="toolbar-button-secondary" disabled={!waveform.has_waveform} onClick={() => bridge?.setCursorVisible('b', !waveform.cursor_b_visible)}>
              {waveform.cursor_b_visible ? '隐藏 B' : '显示 B'}
            </button>
            <button type="button" className="toolbar-button-secondary" disabled={!waveform.signal_catalog.length} onClick={() => bridge?.clearAllSignals()}>
              清空信号
            </button>
            <button type="button" className="toolbar-button" disabled={!waveform.can_add_to_conversation} onClick={() => bridge?.addToConversation('waveform')}>
              添加至对话
            </button>
          </>
        }
      />
      <ResponsivePane
        sidebar={
          <div className="content-card content-card--scrollable">
            <div className="card-title">信号浏览区</div>
            <div className="card-subtitle">总信号 {waveform.signal_count} 条，当前显示 {waveform.displayed_signal_names.length} 条</div>
            <div className="signal-list">
              {waveform.signal_catalog.length ? waveform.signal_catalog.map((signal) => (
                <label key={signal.name} className="signal-item signal-item--checkbox">
                  <div className="signal-item__stack">
                    <span className="signal-item__name">{signal.name}</span>
                    <span className="signal-item__meta">{signal.signal_type || 'signal'}</span>
                  </div>
                  <input
                    type="checkbox"
                    checked={signal.visible}
                    onChange={() => bridge?.setSignalVisible(signal.name, !signal.visible)}
                  />
                </label>
              )) : <div className="signal-item"><span className="signal-item__meta">暂无信号</span></div>}
            </div>
          </div>
        }
        main={
          <div className="content-card content-card--canvas">
            <SeriesSvgChart
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
              series={waveform.visible_series}
              xLabel={waveform.x_axis_label}
              yLabel="Waveform"
              logX={waveform.log_x}
              emptyMessage={waveform.has_waveform ? '当前未显示任何波形，请在左侧勾选信号。' : '当前结果没有可用波形。'}
            />
          </div>
        }
      />
    </div>
  )
}
