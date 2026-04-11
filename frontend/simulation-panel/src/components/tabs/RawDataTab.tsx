import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface RawDataTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function RawDataTab({ state, bridge }: RawDataTabProps) {
  const rawData = state.raw_data_view

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="原始数据"
        description="局部工具栏 + 大表格区，并保持独立滚动。"
        actions={
          <>
            <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.jumpRawDataToRow(0)}>
              跳到首行
            </button>
            <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.jumpRawDataToX(0)}>
              按 X 跳转
            </button>
            <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.searchRawDataValue(0, 0, 0)}>
              按值搜索
            </button>
          </>
        }
      />
      <div className="content-card">
        <div className="table-stage">
          <div className="card-title">大表格区</div>
          <div className="card-subtitle">总行数：{rawData.row_count}</div>
          <div className="muted-text">X 轴标签：{rawData.x_axis_label || '未定义'}，信号列数：{rawData.signal_count}</div>
        </div>
      </div>
    </div>
  )
}
