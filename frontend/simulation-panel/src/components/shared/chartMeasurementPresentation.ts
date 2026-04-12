import type { AnalysisChartViewState, ChartSeriesMetaState, ChartSeriesSnapshotState } from '../../types/state'

export interface ChartMeasurementPresentationRow {
  id: string
  label: string
  color: string
  valueA: number | null
  valueB: number | null
}

export interface ChartMeasurementPresentationGroup {
  id: string
  label: string
  rows: ChartMeasurementPresentationRow[]
}

function normalizeGroupId(groupKey: string | undefined, seriesName: string): string {
  const normalizedGroupKey = groupKey?.trim() ?? ''
  return normalizedGroupKey || seriesName
}

function toComponentLabel(component: string | undefined, fallbackLabel: string): string {
  const normalizedComponent = component?.trim().toLowerCase() ?? ''
  if (normalizedComponent === 'magnitude') {
    return 'Mag'
  }
  if (normalizedComponent === 'phase') {
    return 'Phase'
  }
  return fallbackLabel
}

function resolveGroupMeta(chart: AnalysisChartViewState): Map<string, ChartSeriesMetaState> {
  return new Map(
    chart.available_series.map((series) => [normalizeGroupId(series.group_key, series.name), series]),
  )
}

function buildGroupRows(
  groupLabel: string,
  groupSeries: ChartSeriesSnapshotState[],
  valuesA: Record<string, number>,
  valuesB: Record<string, number>,
): ChartMeasurementPresentationRow[] {
  return groupSeries.map((series) => ({
    id: series.name,
    label: groupSeries.length > 1 ? toComponentLabel(series.component, series.name) : groupLabel,
    color: series.color,
    valueA: valuesA[series.name] ?? null,
    valueB: valuesB[series.name] ?? null,
  }))
}

export function buildChartMeasurementPresentationGroups(chart: AnalysisChartViewState): ChartMeasurementPresentationGroup[] {
  const groupMetaById = resolveGroupMeta(chart)
  const groups = new Map<string, ChartSeriesSnapshotState[]>()

  for (const series of chart.visible_series) {
    const groupId = normalizeGroupId(series.group_key, series.name)
    const bucket = groups.get(groupId) ?? []
    bucket.push(series)
    groups.set(groupId, bucket)
  }

  return Array.from(groups.entries()).map(([groupId, groupSeries]) => {
    const groupMeta = groupMetaById.get(groupId)
    const groupLabel = groupMeta?.name || groupId
    return {
      id: groupId,
      label: groupLabel,
      rows: buildGroupRows(groupLabel, groupSeries, chart.measurement.values_a, chart.measurement.values_b),
    }
  })
}
