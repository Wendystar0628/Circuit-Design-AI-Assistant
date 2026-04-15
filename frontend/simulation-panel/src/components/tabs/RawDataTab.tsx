import { memo } from 'react'

import type { RawDataViewState } from '../../types/state'

interface RawDataTabProps {
  rawDataView: RawDataViewState
}

export const RawDataTab = memo(function RawDataTab({ rawDataView }: RawDataTabProps) {
  const rawData = rawDataView

  return (
    <div className="tab-surface">
      <div className="data-table-shell raw-data-table-shell">
        {rawData.visible_columns.length ? (
          <table className="data-table raw-data-table">
            <thead>
              <tr>
                {rawData.visible_columns.map((columnName) => (
                  <th key={columnName}>{columnName}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rawData.rows.length ? rawData.rows.map((row) => (
                <tr key={row.row_number} className="data-table__row">
                  {row.values.map((value, index) => (
                    <td key={`${row.row_number}:${rawData.visible_columns[index] ?? index}`}>{value || '--'}</td>
                  ))}
                </tr>
              )) : (
                <tr>
                  <td colSpan={rawData.visible_columns.length} className="data-table__empty">当前没有可显示的原始数据行。</td>
                </tr>
              )}
            </tbody>
          </table>
        ) : (
          <div className="muted-text">当前没有可展示的原始数据。</div>
        )}
      </div>
    </div>
  )
})
