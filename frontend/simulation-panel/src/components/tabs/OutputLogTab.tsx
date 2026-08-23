import { useEffect, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { getUiText } from '../../uiText'

interface OutputLogTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function OutputLogTab({ state, bridge }: OutputLogTabProps) {
  const logView = state.output_log_view
  const uiText = state.ui_text
  const [searchKeyword, setSearchKeyword] = useState(logView.search_keyword)
  const [filterLevel, setFilterLevel] = useState(logView.current_filter || 'all')
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied'>('idle')

  useEffect(() => {
    setSearchKeyword(logView.search_keyword)
  }, [logView.search_keyword])

  useEffect(() => {
    setFilterLevel(logView.current_filter || 'all')
  }, [logView.current_filter])

  const handleCopyLog = () => {
    // Ask the backend to copy the complete filtered log. The rendered
    // WebChannel window is intentionally capped, so assembling text from
    // `lines` here used to copy only the first/selected 1000 rows.
    if (!bridge || logView.total_line_count <= 0) {
      return
    }
    bridge.copyOutputLog()
    setCopyStatus('copied')
    window.setTimeout(() => setCopyStatus('idle'), 1500)
  }

  const copyLabel = copyStatus === 'copied'
    ? getUiText(uiText, 'common.copied', 'Copied')
    : getUiText(uiText, 'common.copy', 'Copy')

  return (
    <div className="tab-surface">
      <div className="content-card content-card--scrollable">
        <div className="table-toolbar-grid">
          <label className="field-row field-row--grow">
            <span className="field-row__label">{getUiText(uiText, 'simulation.output_log.keyword', 'Keyword')}</span>
            <input className="field-input" value={searchKeyword} onChange={(event: { target: { value: string } }) => setSearchKeyword(event.target.value)} placeholder={getUiText(uiText, 'simulation.output_log.search_placeholder', 'Enter search keyword')} />
          </label>
          <button type="button" className="sim-compact-button" onClick={() => bridge?.searchOutputLog(searchKeyword)}>
            {getUiText(uiText, 'common.search', 'Search')}
          </button>
          <label className="field-row">
            <span className="field-row__label">{getUiText(uiText, 'common.filter', 'Filter')}</span>
            <select className="field-select" value={filterLevel} onChange={(event: { target: { value: string } }) => setFilterLevel(event.target.value)}>
              <option value="all">{getUiText(uiText, 'common.all', 'All')}</option>
              <option value="error">{getUiText(uiText, 'common.error', 'Error')}</option>
              <option value="warning">{getUiText(uiText, 'common.warning', 'Warning')}</option>
              <option value="info">{getUiText(uiText, 'common.info', 'Info')}</option>
            </select>
          </label>
          <button type="button" className="sim-compact-button" onClick={() => bridge?.filterOutputLog(filterLevel)}>
            {getUiText(uiText, 'simulation.output_log.apply_filter', 'Apply Filter')}
          </button>
          <button type="button" className="sim-compact-button sim-compact-button--accent" disabled={!logView.can_add_to_conversation} onClick={() => bridge?.addToConversation({ projectRoot: state.simulation_runtime.project_root, resultPath: state.simulation_runtime.current_result_path, target: 'output_log' })}>
            {getUiText(uiText, 'common.add_to_conversation', 'Add to Conversation')}
          </button>
          <button type="button" className="sim-compact-button" disabled={logView.total_line_count <= 0} onClick={handleCopyLog}>
            {copyLabel}
          </button>
        </div>
        {logView.is_truncated ? (
          <div className="muted-text">
            {getUiText(uiText, 'simulation.output_log.truncated', 'Showing {visible} of {total} filtered lines. Copy includes all filtered lines.', {
              visible: logView.visible_line_count,
              total: logView.total_line_count,
            })}
          </div>
        ) : null}
        <div className="log-stage log-stage--lines">
          {logView.lines.length ? logView.lines.map((line) => (
            <div
              key={line.line_number}
              className={`log-line log-line--${line.level}${line.line_number === logView.selected_line_number ? ' log-line--selected' : ''}`}
            >
              <span className="log-line__number">{line.line_number}</span>
              <span className="log-line__content">{line.content}</span>
            </div>
          )) : <div className="muted-text">{getUiText(uiText, 'simulation.output_log.empty', 'There are currently no log lines to display.')}</div>}
        </div>
      </div>
    </div>
  )
}
