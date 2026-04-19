import { useEffect, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'

interface OutputLogTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function OutputLogTab({ state, bridge }: OutputLogTabProps) {
  const logView = state.output_log_view
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
    // The copy pipeline is unified: ship plain text through the
    // Qt WebChannel bridge so the host process writes it to the
    // system clipboard via QClipboard. The frontend never touches
    // navigator.clipboard / document.execCommand because they are
    // not reliable inside the embedded QtWebEngine.
    if (!bridge || !logView.lines.length) {
      return
    }
    const text = logView.lines.map((line) => line.content).join('\n')
    bridge.copyTextToClipboard(text)
    setCopyStatus('copied')
    window.setTimeout(() => setCopyStatus('idle'), 1500)
  }

  const copyLabel = copyStatus === 'copied' ? '已复制' : '复制'

  return (
    <div className="tab-surface">
      <div className="content-card content-card--scrollable">
        <div className="table-toolbar-grid">
          <label className="field-row field-row--grow">
            <span className="field-row__label">关键词</span>
            <input className="field-input" value={searchKeyword} onChange={(event: { target: { value: string } }) => setSearchKeyword(event.target.value)} placeholder="输入搜索关键词" />
          </label>
          <button type="button" className="sim-compact-button" onClick={() => bridge?.searchOutputLog(searchKeyword)}>
            搜索
          </button>
          <label className="field-row">
            <span className="field-row__label">过滤</span>
            <select className="field-select" value={filterLevel} onChange={(event: { target: { value: string } }) => setFilterLevel(event.target.value)}>
              <option value="all">全部</option>
              <option value="error">错误</option>
              <option value="warning">警告</option>
              <option value="info">信息</option>
            </select>
          </label>
          <button type="button" className="sim-compact-button" onClick={() => bridge?.filterOutputLog(filterLevel)}>
            应用过滤
          </button>
          <button type="button" className="sim-compact-button sim-compact-button--accent" disabled={!logView.can_add_to_conversation} onClick={() => bridge?.addToConversation('output_log')}>
            添加至对话
          </button>
          <button type="button" className="sim-compact-button" disabled={!logView.lines.length} onClick={handleCopyLog}>
            {copyLabel}
          </button>
        </div>
        <div className="log-stage log-stage--lines">
          {logView.lines.length ? logView.lines.map((line) => (
            <div
              key={line.line_number}
              className={`log-line log-line--${line.level}${line.line_number === logView.selected_line_number ? ' log-line--selected' : ''}`}
            >
              <span className="log-line__number">{line.line_number}</span>
              <span className="log-line__content">{line.content}</span>
            </div>
          )) : <div className="muted-text">当前没有可显示的日志行。</div>}
        </div>
      </div>
    </div>
  )
}
