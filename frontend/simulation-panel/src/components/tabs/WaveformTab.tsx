import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'
import { ResponsivePane } from '../layout/ResponsivePane'

interface WaveformTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function WaveformTab({ state, bridge }: WaveformTabProps) {
  const waveform = state.waveform_view

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="波形"
        description="低高度工具栏 + 信号浏览区 / 画布区 + 低高度测量栏"
        actions={
          <>
            <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.requestFit()}>
              Fit
            </button>
            <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.clearAllSignals()}>
              清空信号
            </button>
            <button type="button" className="toolbar-button" disabled={!waveform.can_add_to_conversation} onClick={() => bridge?.addToConversation('waveform')}>
              添加至对话
            </button>
          </>
        }
      />
      <ResponsivePane
        sidebar={
          <div className="content-card content-card--scrollable">
            <div className="card-title">信号浏览区</div>
            <div className="signal-list">
              {waveform.signal_names.length ? waveform.signal_names.map((signalName) => (
                <div key={signalName} className="signal-item">
                  <span className="signal-item__name">{signalName}</span>
                  <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.setSignalVisible(signalName, true)}>
                    显示
                  </button>
                </div>
              )) : <div className="signal-item"><span className="signal-item__meta">暂无信号</span></div>}
            </div>
          </div>
        }
        main={
          <div className="content-card">
            <div className="canvas-stage">
              <div className="card-title">波形画布区</div>
              <div className="card-subtitle">已发现信号：{waveform.signal_count}</div>
              <div className="muted-text">Phase 1 固定结构强调“画布优先”，不把工具栏或测量栏做成高占用块。</div>
            </div>
          </div>
        }
        footer={
          <div className="measurement-strip">
            <span>Cursor A</span>
            <span>Cursor B</span>
            <span>ΔX</span>
            <span>ΔY</span>
            <span>Slope</span>
          </div>
        }
      />
    </div>
  )
}
