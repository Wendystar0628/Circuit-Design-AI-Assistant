import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface RawDataTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function RawDataTab({ state, bridge }: RawDataTabProps) {
  const rawData = state.raw_data_view
  const description = rawData.result_binding_text
    ? `结果绑定：${rawData.result_binding_text}`
    : rawData.x_axis_label
      ? `X 轴：${rawData.x_axis_label}`
      : '统一前端数据表格显示层，直接消费后端权威 snapshot。'

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="原始数据"
        description={description}
        actions={
          <>
            <button type="button" className="toolbar-button-secondary" disabled={!rawData.has_more_signal_columns_before} onClick={() => bridge?.shiftRawDataSignalWindow(-1)}>
              上一列组
            </button>
            <button type="button" className="toolbar-button-secondary" disabled={!rawData.has_more_signal_columns_after} onClick={() => bridge?.shiftRawDataSignalWindow(1)}>
              下一列组
            </button>
          </>
        }
      />
      <div className="content-card content-card--scrollable">
        <div className="info-grid info-grid--compact">
          <div className="info-row"><div className="card-title">结果绑定</div><div className="info-row__value">{rawData.result_binding_text || '--'}</div></div>
          <div className="info-row"><div className="card-title">行窗口</div><div className="info-row__value">{rawData.window_start} - {rawData.window_end}</div></div>
          <div className="info-row"><div className="card-title">列窗口</div><div className="info-row__value">{rawData.visible_signal_start} - {rawData.visible_signal_end}</div></div>
          <div className="info-row"><div className="card-title">选中行数</div><div className="info-row__value">{rawData.selection_count}</div></div>
          <div className="info-row"><div className="card-title">总信号列</div><div className="info-row__value">{rawData.signal_count}</div></div>
        </div>
        <div className="data-table-shell">
          {rawData.visible_columns.length ? (
            <table className="data-table">
              <thead>
                <tr>
                  {rawData.visible_columns.map((columnName) => (
                    <th key={columnName}>{columnName}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rawData.rows.length ? rawData.rows.map((row) => (
                  <tr key={row.row_number} className={row.selected ? 'data-table__row data-table__row--selected' : 'data-table__row'}>
                    {row.values.map((value, index) => (
                      <td key={`${row.row_number}:${rawData.visible_columns[index] ?? index}`}>{value || '--'}</td>
                    ))}
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={rawData.visible_columns.length} className="data-table__empty">当前窗口暂无可显示数据。</td>
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
