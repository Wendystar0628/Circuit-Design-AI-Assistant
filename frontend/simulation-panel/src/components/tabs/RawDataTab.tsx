import { memo, useMemo } from 'react'

import type { RawDataViewState } from '../../types/state'

const RAW_DATA_COLUMN_WIDTH_PX = 136

function escapeHtml(value: string): string {
  return value
    .split('&').join('&amp;')
    .split('<').join('&lt;')
    .split('>').join('&gt;')
    .split('"').join('&quot;')
    .split("'").join('&#39;')
}

function buildRawDataTableMarkup(rawDataView: RawDataViewState): string {
  const tableWidth = Math.max(rawDataView.visible_columns.length * RAW_DATA_COLUMN_WIDTH_PX, 720)
  const colgroupMarkup = rawDataView.visible_columns
    .map(() => `<col style="width:${RAW_DATA_COLUMN_WIDTH_PX}px">`)
    .join('')
  const headerMarkup = rawDataView.visible_columns
    .map((columnName) => `<th>${escapeHtml(columnName)}</th>`)
    .join('')

  const bodyMarkup = rawDataView.rows.length
    ? rawDataView.rows.map((row) => {
      const cellsMarkup = row.values
        .map((value) => `<td>${escapeHtml(value || '--')}</td>`)
        .join('')
      return `<tr class="data-table__row">${cellsMarkup}</tr>`
    }).join('')
    : `<tr><td colSpan="${rawDataView.visible_columns.length}">当前没有可显示的原始数据行。</td></tr>`

  return `<table class="data-table raw-data-table" style="width:${tableWidth}px"><colgroup>${colgroupMarkup}</colgroup><thead><tr>${headerMarkup}</tr></thead><tbody>${bodyMarkup}</tbody></table>`
}

interface RawDataTabProps {
  rawDataView: RawDataViewState
}

export const RawDataTab = memo(function RawDataTab({ rawDataView }: RawDataTabProps) {
  const tableMarkup = useMemo(
    () => buildRawDataTableMarkup(rawDataView),
    [rawDataView],
  )

  return (
    <div className="tab-surface">
      <div className="data-table-shell raw-data-table-shell">
        {rawDataView.visible_columns.length ? (
          <div dangerouslySetInnerHTML={{ __html: tableMarkup }} />
        ) : (
          <div className="muted-text">当前没有可展示的原始数据。</div>
        )}
      </div>
    </div>
  )
})
