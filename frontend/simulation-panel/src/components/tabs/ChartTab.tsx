import { useEffect, useMemo, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { ResponsivePane } from '../layout/ResponsivePane'
import { MeasurementFloatingPanel } from '../shared/MeasurementFloatingPanel'
import { MeasurementPointFloatingPanel } from '../shared/MeasurementPointFloatingPanel'
import { SignalSelectionSidebar } from '../shared/SignalSelectionSidebar'
import { SeriesSvgChart, type SeriesSvgChartFloatingPanel } from '../shared/SeriesSvgChart'
import { buildChartMeasurementPresentationGroups } from '../shared/chartMeasurementPresentation'
import { formatMeasurementNumber } from '../shared/chartValueFormatting'
import { getUiText } from '../../uiText'

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
  const uiText = state.ui_text
  const [selectedMeasurementGroupId, setSelectedMeasurementGroupId] = useState('')
  const chartDisplayName = chart.chart_type_display_name || chart.title || chart.chart_type || getUiText(uiText, 'simulation.chart.default_title', 'Chart')
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
        className="sim-compact-button"
        disabled={!chart.has_chart}
        onClick={() => bridge?.resetChartViewport()}
      >
        {getUiText(uiText, 'common.fit', 'Fit')}
      </button>
      <button
        type="button"
        className="sim-compact-button"
        disabled={!chart.has_chart}
        onClick={() => bridge?.setChartMeasurementEnabled(!chart.measurement_enabled)}
      >
        {chart.measurement_enabled
          ? getUiText(uiText, 'simulation.chart.disable_measurement', 'Disable Measurement')
          : getUiText(uiText, 'simulation.chart.enable_measurement', 'Enable Measurement')}
      </button>
      <button
        type="button"
        className="sim-compact-button"
        disabled={!canToggleMeasurementPoint}
        onClick={() => bridge?.setChartMeasurementPointEnabled(!chart.measurement_point.enabled)}
      >
        {chart.measurement_point.enabled
          ? getUiText(uiText, 'simulation.chart.disable_measurement_point', 'Disable Measurement Point')
          : getUiText(uiText, 'simulation.chart.enable_measurement_point', 'Enable Measurement Point')}
      </button>
      <button
        type="button"
        className="sim-compact-button"
        disabled={!chart.available_series.length}
        onClick={() => bridge?.clearAllChartSeries()}
      >
        {getUiText(uiText, 'simulation.chart.clear_signals', 'Clear Signals')}
      </button>
      <button
        type="button"
        className="sim-compact-button sim-compact-button--accent"
        disabled={!chart.can_add_to_conversation}
        onClick={() => bridge?.addToConversation('chart')}
      >
        {getUiText(uiText, 'common.add_to_conversation', 'Add to Conversation')}
      </button>
    </>
  ) : undefined
  const visibleLegendSeries = useMemo(() => chart.available_series.filter((series) => series.visible), [chart.available_series])
  const selectableSeriesItems = useMemo(() => chart.available_series.map((series) => ({
    id: series.name,
    label: series.name,
    checked: series.visible,
    onCheckedChange: (checked: boolean) => bridge?.setChartSeriesVisible(series.name, checked),
  })), [bridge, chart.available_series])
  const visibleSeriesItems = useMemo(() => visibleLegendSeries.map((series) => ({
    id: series.name,
    label: series.name,
    color: series.color,
    lineStyle: series.line_style === 'dash' ? 'dash' as const : 'solid' as const,
  })), [visibleLegendSeries])
  const preferredMeasurementGroupId = useMemo(() => {
    if (chart.measurement_point.target_id && measurementSignalOptions.some((option) => option.id === chart.measurement_point.target_id)) {
      return chart.measurement_point.target_id
    }
    return measurementSignalOptions[0]?.id ?? ''
  }, [chart.measurement_point.target_id, measurementSignalOptions])
  const measurementPointTargetId = useMemo(() => {
    if (chart.measurement_point.target_id && measurementSignalOptions.some((option) => option.id === chart.measurement_point.target_id)) {
      return chart.measurement_point.target_id
    }
    return measurementSignalOptions[0]?.id ?? ''
  }, [chart.measurement_point.target_id, measurementSignalOptions])

  useEffect(() => {
    setSelectedMeasurementGroupId((current) => {
      if (measurementSignalOptions.some((option) => option.id === current)) {
        return current
      }
      return preferredMeasurementGroupId
    })
  }, [measurementSignalOptions, preferredMeasurementGroupId])

  const activeMeasurementGroup = useMemo(() => {
    if (!measurementGroups.length) {
      return null
    }
    return measurementGroups.find((group) => group.id === selectedMeasurementGroupId) ?? measurementGroups[0]
  }, [measurementGroups, selectedMeasurementGroupId])

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
            title={getUiText(uiText, 'simulation.chart.measurement_point', 'Measurement Point')}
            signalOptions={measurementSignalOptions}
            selectedSignalId={measurementPointTargetId}
            onSelectedSignalChange={(signalId) => bridge?.setChartMeasurementPointTarget(signalId)}
            rows={measurementPointPanelRows}
            emptyMessage={getUiText(uiText, 'simulation.chart.measurement_point_empty', 'No sampled values are available for the current measurement point.')}
            uiText={uiText}
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
            title={getUiText(uiText, 'simulation.chart.measurement', 'Measurement')}
            signalOptions={measurementSignalOptions}
            selectedSignalId={activeMeasurementGroup?.id ?? ''}
            onSelectedSignalChange={setSelectedMeasurementGroupId}
            rows={measurementPanelRows}
            emptyMessage={getUiText(uiText, 'simulation.chart.measurement_empty', 'No measurement values are available for the selected signal.')}
            uiText={uiText}
          />
        ),
      })
    }
    return panels
  }, [activeMeasurementGroup?.id, bridge, chart.measurement_enabled, chart.measurement_point.enabled, measurementPanelRows, measurementPointPanelRows, measurementPointTargetId, measurementSignalOptions, uiText])

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
            selectableTitle={getUiText(uiText, 'simulation.chart.select_signals', 'Select Signals')}
            selectableItems={selectableSeriesItems}
            emptySelectableMessage={getUiText(uiText, 'simulation.chart.no_selectable_series', 'No chart series are available for the current result.')}
            visibleTitle={getUiText(uiText, 'simulation.chart.visible_series', 'Visible')}
            visibleItems={visibleSeriesItems}
            emptyVisibleMessage={getUiText(uiText, 'simulation.chart.no_visible_series', 'No signals are currently visible.')}
            defaultPrimaryRatio={0.7}
          />
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
              rightLogY={chart.right_log_y}
              emptyMessage={chart.has_chart
                ? getUiText(uiText, 'simulation.chart.empty_hidden', 'No series are currently displayed. Re-select them from the left sidebar.')
                : getUiText(uiText, 'simulation.chart.empty_no_chart', 'No chart is available for the current result.')}
            />
          </div>
        }
      />
    </div>
  )
}
