import type { ResultViewModel } from './types'

function csvCell(value: string | number | null): string {
  if (value === null) return ''
  const text = String(value)
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function safeFilePart(value: string): string {
  return value.replace(/[^a-zA-Z0-9_.-]+/g, '_').replace(/^_+|_+$/g, '') || 'simulation'
}

export function resultFileName(view: ResultViewModel, extension: string, surface: string): string {
  const analysis = view.result.analysis_type
  return `${safeFilePart(view.identity.resultId)}_${analysis}_${surface}.${extension}`
}

export function buildPlotCsv(view: ResultViewModel, visibleSeriesIds: ReadonlySet<string>): string {
  const plot = view.plot
  if (!plot) {
    if (!view.opRows.length) throw new Error('This result has no tabular samples to export.')
    const rows = view.opRows.map((row) => [row.signal, row.value, row.unit].map(csvCell).join(','))
    return [
      `# project_id,${csvCell(view.identity.projectId)}`,
      `# job_id,${csvCell(view.identity.jobId)}`,
      `# result_id,${csvCell(view.identity.resultId)}`,
      'signal,value,unit',
      ...rows,
    ].join('\r\n')
  }
  const series = plot.series.filter((item) => visibleSeriesIds.has(item.id))
  if (!series.length) throw new Error('Select at least one series before exporting CSV.')
  const x = series[0].x
  if (series.some((item) => item.x.length !== x.length)) {
    throw new Error('Visible series do not share one export axis.')
  }
  const header = [
    `${plot.xLabel}${plot.xUnit ? ` (${plot.xUnit})` : ''}`,
    ...series.map((item) => `${item.label}${item.unit ? ` (${item.unit})` : ''}`),
  ].map(csvCell).join(',')
  const rows = x.map((xValue, index) => [
    xValue,
    ...series.map((item) => item.y[index] ?? null),
  ].map(csvCell).join(','))
  return [
    `# project_id,${csvCell(view.identity.projectId)}`,
    `# job_id,${csvCell(view.identity.jobId)}`,
    `# result_id,${csvCell(view.identity.resultId)}`,
    `# analysis_type,${csvCell(view.result.analysis_type)}`,
    header,
    ...rows,
  ].join('\r\n')
}

export function downloadContent(fileName: string, mimeType: string, content: string): void {
  downloadBlob(fileName, new Blob([content], { type: mimeType }))
}

export function downloadBlob(fileName: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.style.display = 'none'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export interface RawColumn {
  id: string
  label: string
  unit: string
  values: Array<number | null>
}

function rawSignalColumns(view: ResultViewModel): RawColumn[] {
  const data = view.data
  if (!data) return []
  return Object.entries(data.signals).flatMap(([name, signal]) => {
    if (Array.isArray(signal)) {
      const plotSeries = view.plot?.series.find((item) => item.id === name)
      return [{ id: name, label: name, unit: plotSeries?.unit ?? '', values: signal }]
    }
    return [
      { id: `${name}:real`, label: `${name} real`, unit: '', values: signal.real },
      { id: `${name}:imag`, label: `${name} imag`, unit: '', values: signal.imag },
    ]
  })
}

export function buildRawColumns(view: ResultViewModel): RawColumn[] {
  const data = view.data
  if (!data) return []
  const axis: RawColumn[] = data.time
    ? [{ id: 'time', label: 'Time', unit: 's', values: data.time }]
    : data.frequency
      ? [{ id: 'frequency', label: 'Frequency', unit: 'Hz', values: data.frequency }]
      : data.sweep
        ? [{ id: 'sweep', label: 'Sweep', unit: '', values: data.sweep }]
        : []
  return [...axis, ...rawSignalColumns(view)]
}
