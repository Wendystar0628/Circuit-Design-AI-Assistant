import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface MetricsTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function MetricsTab({ state, bridge }: MetricsTabProps) {
  const metrics = state.metrics_view.items
  const runtime = state.simulation_runtime

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="指标"
        description="局部动作区 + 指标卡区域 + 分组指标区"
        actions={
          <>
            <button
              type="button"
              className="toolbar-button"
              disabled={!state.metrics_view.can_add_to_conversation}
              onClick={() => bridge?.addToConversation('metrics')}
            >
              添加至对话
            </button>
          </>
        }
      />
      <div className="content-card content-card--scrollable">
        <div className="summary-grid">
          <div className="metric-card">
            <div className="metric-card__title">综合评分</div>
            <div className="metric-card__value">{state.metrics_view.has_goals ? state.metrics_view.overall_score.toFixed(1) : '无目标模式'}</div>
          </div>
          <div className="metric-card">
            <div className="metric-card__title">结果文件</div>
            <div className="metric-card__value">{runtime.current_result.file_name || '暂无结果'}</div>
          </div>
          <div className="metric-card">
            <div className="metric-card__title">分析类型</div>
            <div className="metric-card__value">{runtime.current_result.analysis_label || '未加载'}</div>
          </div>
        </div>
        <div className="metrics-grid">
          {metrics.length ? (
            metrics.map((metric) => (
              <div key={metric.name} className="metric-card">
                <div className="metric-card__header">
                  <span className="metric-card__title">{metric.display_name}</span>
                  <span className="muted-text">{metric.category || 'metric'}</span>
                </div>
                <div className="metric-card__value">{metric.value || '--'}</div>
                <div className="muted-text">目标：{metric.target || '未定义'}</div>
              </div>
            ))
          ) : (
            <div className="metric-card">
              <div className="metric-card__title">暂无指标</div>
              <div className="muted-text">指标卡区域已固定，后续只补真实数据与分组交互。</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
