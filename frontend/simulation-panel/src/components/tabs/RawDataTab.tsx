import type { SimulationMainState } from '../../types/state'

interface RawDataTabProps {
  state: SimulationMainState
}

export function RawDataTab({ state }: RawDataTabProps) {
  const rawData = state.raw_data_view

  return (
    <div className="tab-surface">
      <div className="content-card">
        <div className="data-table-shell">
          {rawData.columns.length ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th key="row-number">行号</th>
                  {rawData.columns.map((columnName) => (
                    <th key={columnName}>{columnName}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rawData.rows.length ? rawData.rows.map((row) => (
                  <tr key={row.row_number} className="data-table__row">
                    <td>{row.row_number}</td>
                    {row.values.map((value, index) => (
                      <td key={`${row.row_number}:${rawData.columns[index] ?? index}`}>{value || '--'}</td>
                    ))}
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={rawData.columns.length + 1} className="data-table__empty">当前没有可显示的原始数据。</td>
                  </tr>
                )}
              </tbody>
            </table>
          ) : (
            <div className="muted-text">当前没有可展示的原始数据列。</div>
          )}
        </div>
      </div>
    </div>
  )
}
