import { useEffect, useMemo, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'
import { ResponsivePane } from '../layout/ResponsivePane'
import { SeriesSvgChart } from '../shared/SeriesSvgChart'

interface WaveformTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

function formatNumber(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return '--'
  }
  return Number(value).toPrecision(6)
}

export function WaveformTab({ state, bridge }: WaveformTabProps) {
  const waveform = state.waveform_view
  const [cursorAInput, setCursorAInput] = useState('')
  const [cursorBInput, setCursorBInput] = useState('')

  useEffect(() => {
    setCursorAInput(waveform.measurement.cursor_a_x === null ? '' : String(waveform.measurement.cursor_a_x))
  }, [waveform.measurement.cursor_a_x])

  useEffect(() => {
    setCursorBInput(waveform.measurement.cursor_b_x === null ? '' : String(waveform.measurement.cursor_b_x))
  }, [waveform.measurement.cursor_b_x])

  const measurementRows = useMemo(() => {
    const names = Array.from(new Set([
      ...Object.keys(waveform.measurement.values_a),
      ...Object.keys(waveform.measurement.values_b),
    ]))
    return names.map((name) => ({
      name,
      valueA: waveform.measurement.values_a[name] ?? null,
      valueB: waveform.measurement.values_b[name] ?? null,
    }))
  }, [waveform.measurement.values_a, waveform.measurement.values_b])

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
          <div className="content-card">
            <div className="canvas-stage canvas-stage--chart">
              <div className="card-title">波形画布区</div>
              <div className="card-subtitle">显示序列：{waveform.visible_series.length}</div>
              <SeriesSvgChart
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
          </div>
        }
        footer={
          <div className="content-card content-card--scrollable">
            <div className="waveform-control-row">
              <label className="field-row">
                <span className="field-row__label">Cursor A</span>
                <input className="field-input" value={cursorAInput} onChange={(event: { target: { value: string } }) => setCursorAInput(event.target.value)} placeholder="X 值" />
              </label>
              <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.setCursorVisible('a', !waveform.cursor_a_visible)}>
                {waveform.cursor_a_visible ? '隐藏 A' : '显示 A'}
              </button>
              <button
                type="button"
                className="toolbar-button-secondary"
                onClick={() => {
                  const value = Number(cursorAInput)
                  if (Number.isFinite(value)) {
                    bridge?.moveCursor('a', value)
                  }
                }}
              >
                设置 A
              </button>
              <label className="field-row">
                <span className="field-row__label">Cursor B</span>
                <input className="field-input" value={cursorBInput} onChange={(event: { target: { value: string } }) => setCursorBInput(event.target.value)} placeholder="X 值" />
              </label>
              <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.setCursorVisible('b', !waveform.cursor_b_visible)}>
                {waveform.cursor_b_visible ? '隐藏 B' : '显示 B'}
              </button>
              <button
                type="button"
                className="toolbar-button-secondary"
                onClick={() => {
                  const value = Number(cursorBInput)
                  if (Number.isFinite(value)) {
                    bridge?.moveCursor('b', value)
                  }
                }}
              >
                设置 B
              </button>
            </div>
            <div className="info-grid info-grid--compact">
              <div className="info-row"><div className="card-title">A / B</div><div className="info-row__value">{`${formatNumber(waveform.measurement.cursor_a_x)} / ${formatNumber(waveform.measurement.cursor_b_x)}`}</div></div>
              <div className="info-row"><div className="card-title">ΔX / ΔY</div><div className="info-row__value">{`${formatNumber(waveform.measurement.delta_x)} / ${formatNumber(waveform.measurement.delta_y)}`}</div></div>
              <div className="info-row"><div className="card-title">Slope</div><div className="info-row__value">{formatNumber(waveform.measurement.slope)}</div></div>
              <div className="info-row"><div className="card-title">Frequency</div><div className="info-row__value">{formatNumber(waveform.measurement.frequency)}</div></div>
            </div>
            <div className="measurement-value-list">
              {measurementRows.length ? measurementRows.map((row) => (
                <div key={row.name} className="measurement-value-row">
                  <div className="measurement-value-row__name">{row.name}</div>
                  <div className="measurement-value-row__value">A: {formatNumber(row.valueA)}</div>
                  <div className="measurement-value-row__value">B: {formatNumber(row.valueB)}</div>
                </div>
              )) : <div className="muted-text">当前没有可展示的测量结果。</div>}
            </div>
          </div>
        }
      />
    </div>
  )
}
