import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { ResponsivePane } from '../layout/ResponsivePane'
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
          <button type="button" className="sim-compact-button sim-compact-button--accent" disabled={!opView.can_add_to_conversation} onClick={() => bridge?.addToConversation('op_result')}>
            添加至对话
          </button>
        }
      />
      <ResponsivePane
        sidebar={
          <div className="content-card content-card--scrollable">
            <div className="info-grid">
              <div className="info-row"><div className="card-title">结果文件</div><div className="info-row__value">{opView.file_name || '未命名结果'}</div></div>
              <div className="info-row"><div className="card-title">分析命令</div><div className="info-row__value">{opView.analysis_command || '.op'}</div></div>
              <div className="info-row"><div className="card-title">结果行数</div><div className="info-row__value">{opView.row_count}</div></div>
              <div className="info-row"><div className="card-title">分组数量</div><div className="info-row__value">{opView.section_count}</div></div>
            </div>
          </div>
        }
        main={
          <div className="content-card content-card--scrollable">
            <div className="op-stage op-stage--table">
              {opView.sections.length ? opView.sections.map((section) => (
                <section key={section.id} className="op-section">
                  <div className="op-section__header">
                    <div className="card-title">{section.title}</div>
                    <div className="card-subtitle">{section.row_count} 项</div>
                  </div>
                  {section.rows.length ? (
                    <div className="op-row-list">
                      {section.rows.map((row) => (
                        <div key={`${section.id}:${row.name}`} className="op-row">
                          <div className="op-row__name">{row.name}</div>
                          <div className="op-row__value">{row.formatted_value || '无效值'}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="muted-text">当前分组暂无可展示结果。</div>
                  )}
                </section>
              )) : (
                <div className="muted-text">当前结果不包含工作点结构化数据。</div>
              )}
            </div>
          </div>
        }
      />
    </div>
  )
}
