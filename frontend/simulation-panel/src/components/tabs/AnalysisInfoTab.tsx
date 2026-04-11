import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface AnalysisInfoTabProps {
  state: SimulationMainState
}

export function AnalysisInfoTab({ state }: AnalysisInfoTabProps) {
  const info = state.analysis_info_view
  const parameterEntries = Object.entries(info.parameters ?? {})

  return (
    <div className="tab-surface">
      <CompactToolbar title="分析信息" description="结构化字段区；不承担全局摘要职责。" />
      <div className="content-card content-card--scrollable">
        <div className="info-grid">
          <div className="info-row"><div className="card-title">分析类型</div><div className="info-row__value">{info.analysis_type || '未加载'}</div></div>
          <div className="info-row"><div className="card-title">执行器</div><div className="info-row__value">{info.executor || '未加载'}</div></div>
          <div className="info-row"><div className="card-title">文件</div><div className="info-row__value">{info.file_name || '未加载'}</div></div>
          <div className="info-row"><div className="card-title">X 轴</div><div className="info-row__value">{info.x_axis_label || '未定义'}</div></div>
        </div>
        <div className="content-card content-card--scrollable">
          <div className="card-title">参数</div>
          <div className="parameter-list">
            {parameterEntries.length ? parameterEntries.map(([key, value]) => (
              <div key={key} className="parameter-row">
                <div className="parameter-row__key">{key}</div>
                <div className="parameter-row__value">{String(value ?? '')}</div>
              </div>
            )) : <div className="muted-text">暂无结构化参数。</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
