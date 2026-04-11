import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface ChartTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function ChartTab({ state, bridge }: ChartTabProps) {
  return (
    <div className="tab-surface">
      <CompactToolbar
        title="图表"
        description="紧凑工具栏 + 主画布区；不保留旧底部说明栏。"
        actions={
          <>
            <button type="button" className="toolbar-button-secondary" disabled={!state.analysis_chart_view.can_export} onClick={() => bridge?.requestExport(['charts'])}>
              导出图表
            </button>
            <button type="button" className="toolbar-button" disabled={!state.analysis_chart_view.can_add_to_conversation} onClick={() => bridge?.addToConversation('chart')}>
              添加至对话
            </button>
          </>
        }
      />
      <div className="content-card">
        <div className="canvas-stage">
          <div className="card-title">主画布区</div>
          <div className="card-subtitle">当前图表数量：{state.analysis_chart_view.chart_count}</div>
          <div className="muted-text">Phase 1 固定结构：工具栏在上，画布独占主内容区，不再额外保留底部图例/说明/反馈条。</div>
        </div>
      </div>
    </div>
  )
}
