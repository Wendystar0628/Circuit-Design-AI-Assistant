import { useEffect, useMemo, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { ResizableStack } from '../layout/ResizableStack'
import { ResponsivePane } from '../layout/ResponsivePane'
import { MeasurementFloatingPanel } from '../shared/MeasurementFloatingPanel'
import { SeriesSvgChart } from '../shared/SeriesSvgChart'
import { formatMeasurementNumber } from '../shared/chartValueFormatting'

interface ChartTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

interface ChartMeasurementGroupRow {
  id: string
  label: string
  color: string
  valueA: number | null
  valueB: number | null
}

interface ChartMeasurementGroup {
  id: string
  label: string
  rows: ChartMeasurementGroupRow[]
}

function formatMeasurementDelta(valueA: number | null, valueB: number | null): string {
  if (valueA === null || valueB === null) {
    return '--'
  }
  return formatMeasurementNumber(valueB - valueA)
}

function toChartMeasurementRowLabel(component: string | undefined, fallbackLabel: string): string {
  const normalizedComponent = component?.trim().toLowerCase() ?? ''
  if (normalizedComponent === 'magnitude') {
    return 'Mag'
  }
  if (normalizedComponent === 'phase') {
    return 'Phase'
  }
  return fallbackLabel
}

export function ChartTab({ state, bridge }: ChartTabProps) {
  const chart = state.analysis_chart_view
  const [selectedMeasurementSignalId, setSelectedMeasurementSignalId] = useState('')
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
  const measurementGroups = useMemo<ChartMeasurementGroup[]>(() => {
    const groups = new Map<string, { label: string; rows: Array<ChartMeasurementGroupRow & { shortLabel: string }> }>()
    const availableSeriesByName = new Map(chart.available_series.map((series) => [series.name, series]))
    const visibleSeriesByName = new Map(chart.visible_series.map((series) => [series.name, series]))

    for (const series of chart.visible_series) {
      const groupId = series.group_key?.trim() || series.name
      const groupMeta = availableSeriesByName.get(groupId)
      const groupLabel = groupMeta?.name || groupId
      const currentGroup = groups.get(groupId) ?? { label: groupLabel, rows: [] }
      currentGroup.rows.push({
        id: series.name,
        label: series.name,
        shortLabel: toChartMeasurementRowLabel(series.component, series.name),
        color: series.color,
        valueA: chart.measurement.values_a[series.name] ?? null,
        valueB: chart.measurement.values_b[series.name] ?? null,
      })
      groups.set(groupId, currentGroup)
    }

    const measuredNames = new Set([
      ...Object.keys(chart.measurement.values_a),
      ...Object.keys(chart.measurement.values_b),
    ])

    for (const measuredName of measuredNames) {
      if (visibleSeriesByName.has(measuredName)) {
        continue
      }
      const visibleMeta = chart.visible_series.find((series) => series.name === measuredName)
      const groupId = visibleMeta?.group_key?.trim() || measuredName
      const currentGroup = groups.get(groupId) ?? { label: groupId, rows: [] }
      currentGroup.rows.push({
        id: measuredName,
        label: measuredName,
        shortLabel: measuredName,
        color: visibleMeta?.color ?? availableSeriesByName.get(groupId)?.color ?? '#1f77b4',
        valueA: chart.measurement.values_a[measuredName] ?? null,
        valueB: chart.measurement.values_b[measuredName] ?? null,
      })
      groups.set(groupId, currentGroup)
    }

    return Array.from(groups.entries()).map(([groupId, group]) => ({
      id: groupId,
      label: group.label,
      rows: group.rows.map((row) => ({
        id: row.id,
        label: group.rows.length > 1 ? row.shortLabel : row.label,
        color: row.color,
        valueA: row.valueA,
        valueB: row.valueB,
      })),
    }))
  }, [chart.measurement.values_a, chart.measurement.values_b, chart.available_series, chart.visible_series])
  const measurementSignalOptions = useMemo(() => measurementGroups.map((group) => ({ id: group.id, label: group.label })), [measurementGroups])
  const preferredMeasurementSignalId = useMemo(() => {
    if (chart.data_cursor_target && measurementSignalOptions.some((option) => option.id === chart.data_cursor_target)) {
      return chart.data_cursor_target
    }
    return measurementSignalOptions[0]?.id ?? ''
  }, [chart.data_cursor_target, measurementSignalOptions])

  useEffect(() => {
    setSelectedMeasurementSignalId((current) => {
      if (measurementSignalOptions.some((option) => option.id === current)) {
        return current
      }
      return preferredMeasurementSignalId
    })
  }, [measurementSignalOptions, preferredMeasurementSignalId])

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
              floatingPanel={chart.measurement_enabled ? (
                <MeasurementFloatingPanel
                  title="测量"
                  signalOptions={measurementSignalOptions}
                  selectedSignalId={activeMeasurementGroup?.id ?? ''}
                  onSelectedSignalChange={setSelectedMeasurementSignalId}
                  rows={measurementPanelRows}
                  emptyMessage="当前所选信号没有可展示的测量值。"
                />
              ) : undefined}
              measurementCursors={{
                cursorAVisible: chart.measurement_enabled,
                cursorBVisible: chart.measurement_enabled,
                cursorAX: chart.measurement.cursor_a_x,
                cursorBX: chart.measurement.cursor_b_x,
                onCursorMove: (cursorId, position) => bridge?.moveChartMeasurementCursor(cursorId, position),
              }}
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
