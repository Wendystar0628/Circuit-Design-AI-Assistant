import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { getUiText } from '../../uiText'
import { ResponsivePane } from '../layout/ResponsivePane'
import { CompactToolbar } from '../layout/CompactToolbar'

interface OpResultTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function OpResultTab({ state, bridge }: OpResultTabProps) {
  const opView = state.op_result_view
  const uiText = state.ui_text

  return (
    <div className="tab-surface">
      <CompactToolbar
        title={getUiText(uiText, 'simulation.op_result.title', 'Operating Point Result')}
        description={getUiText(uiText, 'simulation.op_result.description', 'Local action area plus a structured result table.')}
        actions={
          <button type="button" className="sim-compact-button sim-compact-button--accent" disabled={!opView.can_add_to_conversation} onClick={() => bridge?.addToConversation('op_result')}>
            {getUiText(uiText, 'common.add_to_conversation', 'Add to Conversation')}
          </button>
        }
      />
      <ResponsivePane
        sidebar={
          <div className="content-card content-card--scrollable">
            <div className="info-grid">
              <div className="info-row"><div className="card-title">{getUiText(uiText, 'simulation.op_result.result_file', 'Result File')}</div><div className="info-row__value">{opView.file_name || getUiText(uiText, 'simulation.op_result.unnamed_result', 'Unnamed Result')}</div></div>
              <div className="info-row"><div className="card-title">{getUiText(uiText, 'simulation.op_result.analysis_command', 'Analysis Command')}</div><div className="info-row__value">{opView.analysis_command || '.op'}</div></div>
              <div className="info-row"><div className="card-title">{getUiText(uiText, 'simulation.op_result.row_count', 'Row Count')}</div><div className="info-row__value">{opView.row_count}</div></div>
              <div className="info-row"><div className="card-title">{getUiText(uiText, 'simulation.op_result.section_count', 'Section Count')}</div><div className="info-row__value">{opView.section_count}</div></div>
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
                    <div className="card-subtitle">{getUiText(uiText, 'simulation.op_result.item_count', '{count} items', { count: section.row_count })}</div>
                  </div>
                  {section.rows.length ? (
                    <div className="op-row-list">
                      {section.rows.map((row) => (
                        <div key={`${section.id}:${row.name}`} className="op-row">
                          <div className="op-row__name">{row.name}</div>
                          <div className="op-row__value">{row.formatted_value || getUiText(uiText, 'simulation.op_result.invalid_value', 'Invalid Value')}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="muted-text">{getUiText(uiText, 'simulation.op_result.empty_section', 'No results are available for the current section.')}</div>
                  )}
                </section>
              )) : (
                <div className="muted-text">{getUiText(uiText, 'simulation.op_result.empty', 'The current result does not contain structured operating-point data.')}</div>
              )}
            </div>
          </div>
        }
      />
    </div>
  )
}
