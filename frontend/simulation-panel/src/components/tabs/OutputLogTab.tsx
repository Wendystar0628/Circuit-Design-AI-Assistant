import { useEffect, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface OutputLogTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function OutputLogTab({ state, bridge }: OutputLogTabProps) {
  const logView = state.output_log_view
  const [searchKeyword, setSearchKeyword] = useState(logView.search_keyword)
  const [filterLevel, setFilterLevel] = useState(logView.current_filter || 'all')

  useEffect(() => {
    setSearchKeyword(logView.search_keyword)
  }, [logView.search_keyword])

  useEffect(() => {
    setFilterLevel(logView.current_filter || 'all')
  }, [logView.current_filter])

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="输出日志"
        description="搜索 / 过滤 / 跳错 / 刷新全部走统一 bridge 动作。"
        actions={
          <>
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
      <div className="content-card content-card--scrollable">
        <div className="table-toolbar-grid">
          <label className="field-row field-row--grow">
            <span className="field-row__label">关键词</span>
            <input className="field-input" value={searchKeyword} onChange={(event: { target: { value: string } }) => setSearchKeyword(event.target.value)} placeholder="输入搜索关键词" />
          </label>
          <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.searchOutputLog(searchKeyword)}>
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
          <button type="button" className="toolbar-button-secondary" onClick={() => bridge?.filterOutputLog(filterLevel)}>
            应用过滤
          </button>
        </div>
        <div className="log-summary-grid">
          <div className="info-row"><div className="card-title">总行数</div><div className="info-row__value">{logView.summary.total_lines}</div></div>
          <div className="info-row"><div className="card-title">过滤后</div><div className="info-row__value">{logView.filtered_line_count}</div></div>
          <div className="info-row"><div className="card-title">错误</div><div className="info-row__value">{logView.summary.error_count}</div></div>
          <div className="info-row"><div className="card-title">警告</div><div className="info-row__value">{logView.summary.warning_count}</div></div>
        </div>
        <div className="log-window-meta muted-text">
          窗口：{logView.window_start} - {logView.window_end} · 当前过滤：{logView.current_filter || 'all'}
        </div>
        <div className="log-stage log-stage--lines">
          {logView.lines.length ? logView.lines.map((line) => (
            <div
              key={line.line_number}
              className={`log-line log-line--${line.level}${line.line_number === logView.selected_line_number ? ' log-line--selected' : ''}`}
            >
              <span className="log-line__number">{line.line_number}</span>
              <span className="log-line__level">{line.level}</span>
              <span className="log-line__content">{line.content}</span>
            </div>
          )) : <div className="muted-text">当前没有可显示的日志行。</div>}
        </div>
        {logView.summary.first_error ? (
          <div className="surface-state-card surface-state-card--error">
            <div className="card-title">首条错误</div>
            <div className="muted-text">{logView.summary.first_error}</div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
