import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface HistoryResultsTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function HistoryResultsTab({ state, bridge }: HistoryResultsTabProps) {
  const historyView = state.history_results_view

  return (
    <div className="tab-surface">
      <CompactToolbar title="历史结果" description="筛选/排序区 + 列表区 + 当前选中项预览/加载区；作为 peer tab 存在。" />
      <div className="content-card content-card--scrollable">
        <div className="history-list">
          {historyView.items.length ? historyView.items.map((item) => (
            <div key={item.id || item.result_path} className="history-item">
              <div>
                <div className="history-item__title">{item.file_name || '未命名结果'}</div>
                <div className="history-item__meta">{[item.analysis_type, item.timestamp].filter(Boolean).join(' · ') || '无元数据'}</div>
              </div>
              <div className="list-button-row">
                {item.is_current ? <span className="muted-text">当前</span> : null}
                <button type="button" className="toolbar-button" disabled={!item.can_load} onClick={() => bridge?.loadHistoryResult(item.result_path)}>
                  加载
                </button>
              </div>
            </div>
          )) : <div className="history-item"><span className="muted-text">暂无历史结果。</span></div>}
        </div>
      </div>
    </div>
  )
}
