import { useEffect, useMemo, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { ResizableStack } from '../layout/ResizableStack'
import { ResponsivePane } from '../layout/ResponsivePane'
import { MeasurementFloatingPanel } from '../shared/MeasurementFloatingPanel'
import { MeasurementPointFloatingPanel } from '../shared/MeasurementPointFloatingPanel'
import { SeriesSvgChart, type SeriesSvgChartFloatingPanel } from '../shared/SeriesSvgChart'
import { buildChartMeasurementPresentationGroups } from '../shared/chartMeasurementPresentation'
import { formatMeasurementNumber } from '../shared/chartValueFormatting'

interface ChartTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

function formatMeasurementDelta(valueA: number | null, valueB: number | null): string {
  if (valueA === null || valueB === null) {
    return '--'
  }
  return formatMeasurementNumber(valueB - valueA)
}

export function ChartTab({ state, bridge }: ChartTabProps) {
  const chart = state.analysis_chart_view
  const [selectedMeasurementSignalId, setSelectedMeasurementSignalId] = useState('')
  const chartDisplayName = chart.chart_type_display_name || chart.title || chart.chart_type || '图表'
  const viewWindow = useMemo(() => ({
    active: chart.viewport.active,
    xMin: chart.viewport.x_min,
    xMax: chart.viewport.x_max,
    leftYMin: chart.viewport.left_y_min,
    leftYMax: chart.viewport.left_y_max,
    rightYMin: chart.viewport.right_y_min,
    rightYMax: chart.viewport.right_y_max,
  }), [chart.viewport.active, chart.viewport.left_y_max, chart.viewport.left_y_min, chart.viewport.right_y_max, chart.viewport.right_y_min, chart.viewport.x_max, chart.viewport.x_min])
  const measurementGroups = useMemo(() => buildChartMeasurementPresentationGroups(chart), [chart])
  const measurementSignalOptions = useMemo(() => measurementGroups.map((group) => ({ id: group.id, label: group.label })), [measurementGroups])
  const supportsMeasurementPoint = measurementSignalOptions.length > 0
  const canToggleMeasurementPoint = supportsMeasurementPoint || chart.measurement_point.enabled
  const chartHeaderActions = chart.has_chart ? (
    <>
      <button
        type="button"
        className="chart-header-button"
        disabled={!chart.has_chart}
        onClick={() => bridge?.resetChartViewport()}
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
        disabled={!canToggleMeasurementPoint}
        onClick={() => bridge?.setChartMeasurementPointEnabled(!chart.measurement_point.enabled)}
      >
        {chart.measurement_point.enabled ? '关闭测量点' : '开启测量点'}
      </button>
      <button
        type="button"
        className="chart-header-button"
        disabled={!chart.available_series.length}
        onClick={() => bridge?.clearAllChartSeries()}
      >
        清空信号
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
  const preferredMeasurementSignalId = useMemo(() => {
    if (chart.measurement_point.target_id && measurementSignalOptions.some((option) => option.id === chart.measurement_point.target_id)) {
      return chart.measurement_point.target_id
    }
    return measurementSignalOptions[0]?.id ?? ''
  }, [chart.measurement_point.target_id, measurementSignalOptions])

  useEffect(() => {
    setSelectedMeasurementSignalId((current) => {
      if (measurementSignalOptions.some((option) => option.id === current)) {
        return current
      }
      return preferredMeasurementSignalId
    })
  }, [measurementSignalOptions, preferredMeasurementSignalId])

  useEffect(() => {
    if (!selectedMeasurementSignalId) {
      return
    }
    if (selectedMeasurementSignalId === chart.measurement_point.target_id) {
      return
    }
    bridge?.setChartMeasurementPointTarget(selectedMeasurementSignalId)
  }, [bridge, chart.measurement_point.target_id, selectedMeasurementSignalId])

  const activeMeasurementGroup = useMemo(() => {
    if (!measurementGroups.length) {
      return null
    }
    return measurementGroups.find((group) => group.id === selectedMeasurementSignalId) ?? measurementGroups[0]
  }, [measurementGroups, selectedMeasurementSignalId])

  const measurementPanelRows = useMemo(() => (activeMeasurementGroup?.rows ?? []).map((row) => ({
    id: row.id,
    label: row.label,
    color: row.color,
    valueA: formatMeasurementNumber(row.valueA),
    valueB: formatMeasurementNumber(row.valueB),
    delta: formatMeasurementDelta(row.valueA, row.valueB),
  })), [activeMeasurementGroup])

  const measurementPointPanelRows = useMemo(() => chart.measurement_point.values.map((value, index) => ({
    id: `${value.label}-${index}`,
    label: value.label,
    valueText: value.value_text,
  })), [chart.measurement_point.values])

  const floatingPanels = useMemo(() => {
    const panels: SeriesSvgChartFloatingPanel[] = []
    if (chart.measurement_point.enabled) {
      panels.push({
        id: 'measurement-point',
        defaultTop: 16,
        defaultRight: 16,
        content: (
          <MeasurementPointFloatingPanel
            title="测量点"
            signalOptions={measurementSignalOptions}
            selectedSignalId={selectedMeasurementSignalId}
            onSelectedSignalChange={setSelectedMeasurementSignalId}
            rows={measurementPointPanelRows}
            emptyMessage="当前测量点没有可展示的采样值。"
          />
        ),
      })
    }
    if (chart.measurement_enabled) {
      panels.push({
        id: 'measurement',
        defaultTop: chart.measurement_point.enabled ? 204 : 16,
        defaultRight: 16,
        content: (
          <MeasurementFloatingPanel
            title="测量"
            signalOptions={measurementSignalOptions}
            selectedSignalId={activeMeasurementGroup?.id ?? ''}
            onSelectedSignalChange={setSelectedMeasurementSignalId}
            rows={measurementPanelRows}
            emptyMessage="当前所选信号没有可展示的测量值。"
          />
        ),
      })
    }
    return panels
  }, [activeMeasurementGroup?.id, chart.measurement_enabled, chart.measurement_point.enabled, measurementPanelRows, measurementPointPanelRows, measurementSignalOptions, selectedMeasurementSignalId])

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
                            onChange={(event) => bridge?.setChartSeriesVisible(series.name, event.target.checked)}
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
              floatingPanels={floatingPanels}
              measurementCursors={{
                cursorAVisible: chart.measurement_enabled,
                cursorBVisible: chart.measurement_enabled,
                cursorAX: chart.measurement.cursor_a_x,
                cursorBX: chart.measurement.cursor_b_x,
                onCursorMove: (cursorId, position) => bridge?.moveChartMeasurementCursor(cursorId, position),
              }}
              measurementPoint={{
                visible: chart.measurement_point.enabled,
                displayX: chart.measurement_point.point_x,
                valueY: chart.measurement_point.plot_y,
                axisKey: chart.measurement_point.plot_axis_key,
                onMove: (position) => bridge?.moveChartMeasurementPoint(position),
              }}
              viewWindow={viewWindow}
              onViewportChange={(nextViewWindow) => bridge?.setChartViewport(nextViewWindow)}
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
      />
    </div>
  )
}
