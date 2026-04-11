import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface OutputLogTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function OutputLogTab({ state, bridge }: OutputLogTabProps) {
  const logView = state.output_log_view

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="输出日志"
        description="搜索/过滤/跳错工具栏 + 日志区，并保持独立滚动。"
        actions={
          <>
            <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.searchOutputLog('error')}>
              搜索 error
            </button>
            <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.filterOutputLog('error')}>
              过滤 error
            </button>
            <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.jumpToOutputLogError()}>
              跳到错误
            </button>
            <button type="button" className="toolbar-button-secondary" disabled={!logView.can_refresh} onClick={() => bridge?.refreshOutputLog()}>
              局部刷新
            </button>
            <button type="button" className="toolbar-button" disabled={!logView.can_add_to_conversation} onClick={() => bridge?.addToConversation('output_log')}>
              添加至对话
            </button>
          </>
        }
      />
      <div className="content-card">
        <div className="log-summary-grid">
          <div className="info-row"><div className="card-title">日志行数</div><div className="info-row__value">{logView.line_count}</div></div>
          <div className="info-row"><div className="card-title">允许局部刷新</div><div className="info-row__value">{logView.can_refresh ? '是' : '否'}</div></div>
        </div>
        <div className="log-stage">
          <div className="card-title">日志区</div>
          <div className="muted-text">Phase 1 固定输出日志 tab 的局部工具栏与独立滚动边界，不再依赖全局刷新。</div>
        </div>
      </div>
    </div>
  )
}
