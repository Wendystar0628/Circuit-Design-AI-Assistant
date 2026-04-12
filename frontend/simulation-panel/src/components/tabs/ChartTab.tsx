import { useMemo } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'
import { ResponsivePane } from '../layout/ResponsivePane'
import { SeriesSvgChart } from '../shared/SeriesSvgChart'

interface ChartTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

function formatNumber(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return '--'
  }
  return Number(value).toPrecision(6)
}

export function ChartTab({ state, bridge }: ChartTabProps) {
  const chart = state.analysis_chart_view
  const supportsDataCursor = chart.available_series.length > 0
  const cursorTargetOptions = useMemo(() => chart.available_series.map((series) => series.name), [chart.available_series])
  const measurementRows = useMemo(() => {
    const names = Array.from(new Set([
      ...Object.keys(chart.measurement.values_a),
      ...Object.keys(chart.measurement.values_b),
    ]))
    return names.map((name) => ({
      name,
      valueA: chart.measurement.values_a[name] ?? null,
      valueB: chart.measurement.values_b[name] ?? null,
    }))
  }, [chart.measurement.values_a, chart.measurement.values_b])

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="图表"
        description={chart.title ? `${chart.title} · ${chart.chart_type || 'chart'}` : '统一前端图表显示层，直接消费后端权威 snapshot。'}
        actions={
          <>
            <button
              type="button"
              className="toolbar-button-secondary"
              disabled={!chart.has_chart}
              onClick={() => bridge?.fitChart()}
            >
              Fit
            </button>
            <button
              type="button"
              className="toolbar-button-secondary"
              disabled={!chart.has_chart}
              onClick={() => bridge?.setChartMeasurementEnabled(!chart.measurement_enabled)}
            >
              {chart.measurement_enabled ? '关闭测量' : '开启测量'}
            </button>
            <button
              type="button"
              className="toolbar-button-secondary"
              disabled={!supportsDataCursor}
              onClick={() => bridge?.setChartDataCursorEnabled(!chart.data_cursor_enabled)}
            >
              {chart.data_cursor_enabled ? '关闭光标' : '开启光标'}
            </button>
            <button
              type="button"
              className="toolbar-button-secondary"
              disabled={!chart.available_series.length}
              onClick={() => bridge?.clearAllChartSeries()}
            >
              清空序列
            </button>
            <button
              type="button"
              className="toolbar-button-secondary"
              disabled={!chart.can_export}
              onClick={() => bridge?.requestExport(['charts'])}
            >
              导出图表
            </button>
            <button
              type="button"
              className="toolbar-button"
              disabled={!chart.can_add_to_conversation}
              onClick={() => bridge?.addToConversation('chart')}
            >
              添加至对话
            </button>
          </>
        }
      />
      <ResponsivePane
        sidebarConfig={{
          defaultSize: 176,
          minSize: 132,
          maxSize: 360,
          mainMinSize: 320,
          resizable: true,
        }}
        sidebar={
          <div className="content-card content-card--scrollable">
            <div className="card-title">序列列表</div>
            <div className="card-subtitle">共 {chart.available_series.length} 条序列，当前显示 {chart.visible_series_count} 条</div>
            <label className="field-row">
              <span className="field-row__label">数据光标目标</span>
              <select
                className="field-select"
                value={chart.data_cursor_target || ''}
                disabled={!supportsDataCursor}
                onChange={(event: { target: { value: string } }) => bridge?.setChartDataCursorTarget(event.target.value)}
              >
                <option value="">未选择</option>
                {cursorTargetOptions.map((seriesName) => (
                  <option key={seriesName} value={seriesName}>{seriesName}</option>
                ))}
              </select>
            </label>
            <div className="signal-list">
              {chart.available_series.length ? chart.available_series.map((series) => (
                <label key={series.name} className="signal-item signal-item--checkbox">
                  <div className="signal-item__stack">
                    <span className="signal-item__name">{series.name}</span>
                    <span className="signal-item__meta">
                      {[series.axis_key, series.component, `${series.point_count} 点`].filter(Boolean).join(' · ') || '无元数据'}
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    checked={series.visible}
                    onChange={() => bridge?.setChartSeriesVisible(series.name, !series.visible)}
                  />
                </label>
              )) : <div className="signal-item"><span className="signal-item__meta">当前结果没有可用图表序列。</span></div>}
            </div>
          </div>
        }
        main={
          <div className="content-card content-card--canvas">
            <div className="canvas-stage canvas-stage--chart">
              <div className="card-title">图表画布</div>
              <div className="card-subtitle">
                {[chart.x_label || 'X', chart.y_label || 'Y', chart.secondary_y_label].filter(Boolean).join(' / ')}
              </div>
              <SeriesSvgChart
                series={chart.visible_series}
                xLabel={chart.x_label}
                yLabel={chart.y_label}
                secondaryYLabel={chart.secondary_y_label}
                logX={chart.log_x}
                logY={chart.log_y}
                emptyMessage={chart.has_chart ? '当前未显示任何序列，请在左侧重新勾选。' : '当前结果没有可用图表。'}
              />
            </div>
          </div>
        }
        footer={
          <div className="content-card content-card--scrollable">
            <div className="info-grid info-grid--compact">
              <div className="info-row"><div className="card-title">图表类型</div><div className="info-row__value">{chart.chart_type || '未定义'}</div></div>
              <div className="info-row"><div className="card-title">数据光标</div><div className="info-row__value">{chart.data_cursor_enabled ? (chart.data_cursor_target || '已启用') : '未启用'}</div></div>
              <div className="info-row"><div className="card-title">测量状态</div><div className="info-row__value">{chart.measurement_enabled ? '已启用' : '未启用'}</div></div>
              <div className="info-row"><div className="card-title">ΔX / f</div><div className="info-row__value">{`${formatNumber(chart.measurement.delta_x)} / ${formatNumber(chart.measurement.frequency)}`}</div></div>
            </div>
            <div className="measurement-value-list">
              {measurementRows.length ? measurementRows.map((row) => (
                <div key={row.name} className="measurement-value-row">
                  <div className="measurement-value-row__name">{row.name}</div>
                  <div className="measurement-value-row__value">A: {formatNumber(row.valueA)}</div>
                  <div className="measurement-value-row__value">B: {formatNumber(row.valueB)}</div>
                </div>
              )) : <div className="muted-text">当前没有可展示的测量值。</div>}
            </div>
          </div>
        }
      />
    </div>
  )
}
