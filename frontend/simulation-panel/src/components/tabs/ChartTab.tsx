import { useMemo } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { ResizableStack } from '../layout/ResizableStack'
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
  const chartDisplayName = chart.chart_type_display_name || chart.title || chart.chart_type || '图表'
  const chartHeaderActions = chart.has_chart ? (
    <>
      <button
        type="button"
        className="chart-header-button"
        disabled={!chart.has_chart}
        onClick={() => bridge?.fitChart()}
      >
        Fit
      </button>
      <button
        type="button"
        className="chart-header-button"
        disabled={!chart.has_chart}
        onClick={() => bridge?.setChartMeasurementEnabled(!chart.measurement_enabled)}
      >
        {chart.measurement_enabled ? '关闭测量' : '开启测量'}
      </button>
      <button
        type="button"
        className="chart-header-button"
        disabled={!supportsDataCursor}
        onClick={() => bridge?.setChartDataCursorEnabled(!chart.data_cursor_enabled)}
      >
        {chart.data_cursor_enabled ? '关闭光标' : '开启光标'}
      </button>
      <button
        type="button"
        className="chart-header-button"
        disabled={!chart.available_series.length}
        onClick={() => bridge?.clearAllChartSeries()}
      >
        清空序列
      </button>
      <button
        type="button"
        className="chart-header-button"
        disabled={!chart.can_export}
        onClick={() => bridge?.requestExport(['charts'])}
      >
        导出图表
      </button>
      <button
        type="button"
        className="chart-header-button chart-header-button--accent"
        disabled={!chart.can_add_to_conversation}
        onClick={() => bridge?.addToConversation('chart')}
      >
        添加至对话
      </button>
    </>
  ) : undefined
  const visibleLegendSeries = useMemo(() => chart.available_series.filter((series) => series.visible), [chart.available_series])
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
      <ResponsivePane
        sidebarConfig={{
          defaultSize: 176,
          minSize: 132,
          maxSize: 360,
          mainMinSize: 320,
          resizable: true,
        }}
        sidebar={
          <div className="content-card chart-sidebar">
            <ResizableStack
              defaultPrimaryRatio={0.7}
              minPrimarySize={144}
              minSecondarySize={104}
              primary={
                <section className="chart-sidebar__panel">
                  <div className="chart-sidebar__panel-title">选择信号</div>
                  <div className="chart-sidebar__panel-body">
                    <div className="signal-list chart-sidebar__signal-list">
                      {chart.available_series.length ? chart.available_series.map((series) => (
                        <label key={series.name} className="signal-item signal-item--checkbox">
                          <span className="signal-item__name">{series.name}</span>
                          <input
                            type="checkbox"
                            checked={series.visible}
                            onChange={() => bridge?.setChartSeriesVisible(series.name, !series.visible)}
                          />
                        </label>
                      )) : <div className="signal-item"><span className="muted-text">当前结果没有可用图表序列。</span></div>}
                    </div>
                  </div>
                </section>
              }
              secondary={
                <section className="chart-sidebar__panel">
                  <div className="chart-sidebar__panel-title">已显示</div>
                  <div className="chart-sidebar__panel-body">
                    <div className="chart-sidebar-legend">
                      {visibleLegendSeries.length ? visibleLegendSeries.map((series) => (
                        <div key={series.name} className="chart-sidebar-legend__item">
                          <svg className="chart-sidebar-legend__swatch" viewBox="0 0 24 12" aria-hidden="true" focusable="false">
                            <line x1="1" x2="23" y1="6" y2="6" stroke={series.color} strokeWidth="2" strokeLinecap="round" className="chart-sidebar-legend__line" />
                          </svg>
                          <span className="chart-sidebar-legend__name">{series.name}</span>
                        </div>
                      )) : <div className="muted-text">当前没有已显示信号。</div>}
                    </div>
                  </div>
                </section>
              }
            />
          </div>
        }
        main={
          <div className="content-card content-card--canvas">
            <SeriesSvgChart
              title={chart.has_chart ? chartDisplayName : ''}
              headerActions={chartHeaderActions}
              series={chart.visible_series}
              xLabel={chart.x_label}
              yLabel={chart.y_label}
              secondaryYLabel={chart.secondary_y_label}
              logX={chart.log_x}
              logY={chart.log_y}
              emptyMessage={chart.has_chart ? '当前未显示任何序列，请在左侧重新勾选。' : '当前结果没有可用图表。'}
            />
          </div>
        }
        footer={
          <div className="content-card content-card--scrollable">
            <div className="info-grid info-grid--compact">
              <div className="info-row"><div className="card-title">图表类型</div><div className="info-row__value">{chart.has_chart ? chartDisplayName : '未定义'}</div></div>
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
