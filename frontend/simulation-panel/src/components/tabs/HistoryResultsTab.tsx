import { useEffect, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { ResponsivePane } from '../layout/ResponsivePane'
import { CompactToolbar } from '../layout/CompactToolbar'

interface HistoryResultsTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function HistoryResultsTab({ state, bridge }: HistoryResultsTabProps) {
  const historyView = state.history_results_view
  const [previewResultPath, setPreviewResultPath] = useState(historyView.selected_result_path)

  useEffect(() => {
    setPreviewResultPath(historyView.selected_result_path)
  }, [historyView.selected_result_path])

  const selectedItem = historyView.items.find((item) => item.result_path === previewResultPath) ?? historyView.items[0] ?? null

  return (
    <div className="tab-surface">
      <CompactToolbar title="历史结果" description="筛选/排序区 + 列表区 + 当前选中项预览/加载区；作为 peer tab 存在。" />
      <ResponsivePane
        sidebar={
          <div className="content-card content-card--scrollable">
            <div className="history-filter-row">
              <div className="history-filter-chip">最近结果</div>
              <div className="history-filter-chip">按时间排序</div>
            </div>
            <div className="history-list">
              {historyView.items.length ? historyView.items.map((item) => (
                <button
                  key={item.id || item.result_path}
                  type="button"
                  className={`history-item history-item--button${item.result_path === (selectedItem?.result_path ?? '') ? ' history-item--active' : ''}`}
                  onClick={() => setPreviewResultPath(item.result_path)}
                >
                  <div>
                    <div className="history-item__title">{item.file_name || '未命名结果'}</div>
                    <div className="history-item__meta">{[item.analysis_type, item.timestamp].filter(Boolean).join(' · ') || '无元数据'}</div>
                  </div>
                  <div className="list-button-row">
                    {item.is_current ? <span className="muted-text">当前</span> : null}
                  </div>
                </button>
              )) : <div className="history-item"><span className="muted-text">暂无历史结果。</span></div>}
            </div>
          </div>
        }
        main={
          <div className="content-card">
            <div className="history-preview-grid">
              <div className="info-row"><div className="card-title">文件</div><div className="info-row__value">{selectedItem?.file_name || '未选择结果'}</div></div>
              <div className="info-row"><div className="card-title">分析类型</div><div className="info-row__value">{selectedItem?.analysis_type || '未定义'}</div></div>
              <div className="info-row"><div className="card-title">时间戳</div><div className="info-row__value">{selectedItem?.timestamp || '无'}</div></div>
              <div className="info-row"><div className="card-title">状态</div><div className="info-row__value">{selectedItem ? (selectedItem.success ? '成功' : '失败') : '无'}</div></div>
            </div>
            <div className="op-stage">
              <div className="card-title">当前选中项预览</div>
              <div className="card-subtitle">选择一条历史结果后，可以在这里查看概要并加载为当前权威结果。</div>
              <div className="muted-text">结果路径：{selectedItem?.result_path || '未选择结果'}</div>
            </div>
          </div>
        }
        footer={
          <div className="content-card">
            <div className="list-button-row">
              <div>
                <div className="card-title">加载历史结果</div>
                <div className="muted-text">加载后会替换当前 tab 面板使用的权威结果状态。</div>
              </div>
              <button
                type="button"
                className="toolbar-button"
                disabled={!selectedItem?.can_load}
                onClick={() => selectedItem?.result_path && bridge?.loadHistoryResult(selectedItem.result_path)}
              >
                加载选中结果
              </button>
            </div>
          </div>
        }
      />
    </div>
  )
}
