import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface ExportTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function ExportTab({ state, bridge }: ExportTabProps) {
  const exportView = state.export_view
  const enabledItems = exportView.items.filter((item) => item.enabled)
  const selectedCount = enabledItems.filter((item) => item.selected).length

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="导出"
        actions={
          <button
            type="button"
            className="toolbar-button"
            disabled={!exportView.can_export}
            onClick={() => bridge?.requestExport()}
          >
            导出选中项
          </button>
        }
      />
      <div className="content-card content-card--scrollable">
        <div className="table-toolbar-grid">
          <label className="field-row field-row--grow">
            <span className="field-row__label">导出目录</span>
            <input className="field-input" value={exportView.selected_directory || '未选择'} readOnly />
          </label>
          <button type="button" className="toolbar-button-secondary" disabled={!exportView.has_result} onClick={() => bridge?.chooseExportDirectory()}>
            选择目录
          </button>
          <button type="button" className="toolbar-button-secondary" disabled={!exportView.selected_directory} onClick={() => bridge?.clearExportDirectory()}>
            清空目录
          </button>
          <button type="button" className="toolbar-button-secondary" disabled={!enabledItems.length} onClick={() => bridge?.setAllExportTypesSelected(true)}>
            全选
          </button>
          <button type="button" className="toolbar-button-secondary" disabled={!selectedCount} onClick={() => bridge?.setAllExportTypesSelected(false)}>
            清空选择
          </button>
        </div>
        <div className="export-grid">
          {exportView.items.length ? exportView.items.map((item) => (
            <label key={item.id} className={`export-item export-item--option${item.enabled ? '' : ' export-item--disabled'}`}>
              <input
                type="checkbox"
                className="export-item__checkbox"
                checked={item.selected}
                disabled={!item.enabled}
                onChange={(event: { target: { checked: boolean } }) => bridge?.setExportTypeSelected(item.id, event.target.checked)}
              />
              <span className="export-item__label">{item.label}</span>
            </label>
          )) : <div className="export-item"><div className="muted-text">暂无可导出项。</div></div>}
        </div>
        <div className="info-row">
          <div className="card-title">最近项目导出目录</div>
          <div className="info-row__value export-path-value">{exportView.latest_project_export_root || '暂无'}</div>
        </div>
      </div>
    </div>
  )
}
