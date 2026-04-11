import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface OpResultTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function OpResultTab({ state, bridge }: OpResultTabProps) {
  const opView = state.op_result_view

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="工作点结果"
        description="局部动作区 + 结构化结果表；条件性 peer tab。"
        actions={
          <button type="button" className="toolbar-button" disabled={!opView.can_add_to_conversation} onClick={() => bridge?.addToConversation('op_result')}>
            添加至对话
          </button>
        }
      />
      <div className="content-card">
        <div className="op-stage">
          <div className="card-title">结构化结果表</div>
          <div className="card-subtitle">结果行数：{opView.row_count}</div>
          <div className="muted-text">仅当存在 OP 结果时显示该 tab；Phase 1 先固定结构位置和 peer-tab 语义。</div>
        </div>
      </div>
    </div>
  )
}
