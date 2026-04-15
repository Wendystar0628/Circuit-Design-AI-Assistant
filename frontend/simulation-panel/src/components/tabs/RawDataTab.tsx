import { useEffect, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface RawDataTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function RawDataTab({ state, bridge }: RawDataTabProps) {
  const rawData = state.raw_data_view
  const [rowInput, setRowInput] = useState('1')
  const [xInput, setXInput] = useState('')
  const [searchColumn, setSearchColumn] = useState('0')
  const [searchValue, setSearchValue] = useState('')
  const [searchTolerance, setSearchTolerance] = useState('0')
  const description = rawData.result_binding_text
    ? `结果绑定：${rawData.result_binding_text}`
    : rawData.x_axis_label
      ? `X 轴：${rawData.x_axis_label}`
      : '统一前端数据表格显示层，直接消费后端权威 snapshot。'

  useEffect(() => {
    setSearchColumn(rawData.search_columns.length ? '0' : '')
  }, [rawData.search_columns])

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
        <div className="table-toolbar-grid">
          <label className="field-row">
            <span className="field-row__label">行号</span>
            <input className="field-input" value={rowInput} onChange={(event: { target: { value: string } }) => setRowInput(event.target.value)} placeholder="1" />
          </label>
          <button
            type="button"
            className="toolbar-button-secondary"
            onClick={() => {
              const row = Number(rowInput)
              if (Number.isFinite(row)) {
                bridge?.jumpRawDataToRow(row)
              }
            }}
          >
            跳转行
          </button>
          <label className="field-row">
            <span className="field-row__label">X 值</span>
            <input className="field-input" value={xInput} onChange={(event: { target: { value: string } }) => setXInput(event.target.value)} placeholder="0" />
          </label>
          <button
            type="button"
            className="toolbar-button-secondary"
            onClick={() => {
              const xValue = Number(xInput)
              if (Number.isFinite(xValue)) {
                bridge?.jumpRawDataToX(xValue)
              }
            }}
          >
            按 X 跳转
          </button>
          <label className="field-row">
            <span className="field-row__label">列</span>
            <select className="field-select" value={searchColumn} onChange={(event: { target: { value: string } }) => setSearchColumn(event.target.value)}>
              {rawData.search_columns.map((columnName, index) => (
                <option key={`${columnName}:${index}`} value={String(index)}>{columnName}</option>
              ))}
            </select>
          </label>
          <label className="field-row">
            <span className="field-row__label">值</span>
            <input className="field-input" value={searchValue} onChange={(event: { target: { value: string } }) => setSearchValue(event.target.value)} placeholder="0" />
          </label>
          <label className="field-row">
            <span className="field-row__label">容差</span>
            <input className="field-input" value={searchTolerance} onChange={(event: { target: { value: string } }) => setSearchTolerance(event.target.value)} placeholder="0" />
          </label>
          <button
            type="button"
            className="toolbar-button-secondary"
            disabled={!rawData.search_columns.length}
            onClick={() => {
              const column = Number(searchColumn)
              const value = Number(searchValue)
              const tolerance = Number(searchTolerance)
              if (Number.isFinite(column) && Number.isFinite(value) && Number.isFinite(tolerance)) {
                bridge?.searchRawDataValue(column, value, tolerance)
              }
            }}
          >
            按值搜索
          </button>
        </div>
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
