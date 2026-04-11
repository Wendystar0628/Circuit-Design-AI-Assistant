import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface ExportTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function ExportTab({ state, bridge }: ExportTabProps) {
  const exportView = state.export_view

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="导出"
        description="导出项选择区 + 操作区 + 局部反馈区。"
        actions={
          <button
            type="button"
            className="toolbar-button"
            disabled={!exportView.has_result || !exportView.available_types.length}
            onClick={() => bridge?.requestExport(exportView.available_types)}
          >
            导出选中项
          </button>
        }
      />
      <div className="content-card content-card--scrollable">
        <div className="export-grid">
          {exportView.available_types.length ? exportView.available_types.map((item) => (
            <div key={item} className="export-item">
              <div className="card-title">{item}</div>
              <div className="muted-text">导出项骨架已固定，后续再补精细勾选状态。</div>
            </div>
          )) : <div className="export-item"><div className="muted-text">暂无可导出项。</div></div>}
        </div>
        <div className="info-row">
          <div className="card-title">最近项目导出目录</div>
          <div className="info-row__value">{exportView.latest_project_export_root || '暂无'}</div>
        </div>
      </div>
    </div>
  )
}
