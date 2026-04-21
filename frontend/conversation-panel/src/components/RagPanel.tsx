import { useEffect, useMemo, useRef, useState } from 'react'
import type { ConversationBridge } from '../bridge'
import type { ConversationMainState, RagFileState } from '../types'
import { getUiText } from '../uiText'

interface RagPanelProps {
  state: ConversationMainState
  bridge: ConversationBridge | null
  bridgeConnected: boolean
}

function formatStorageSize(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '0 MB'
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} GB`
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} MB`
}

function infoToneClass(tone: string): string {
  if (tone === 'error') {
    return 'danger'
  }
  if (tone === 'success') {
    return 'success'
  }
  if (tone === 'info') {
    return 'info'
  }
  return 'neutral'
}

function statusToneClass(tone: string): string {
  if (tone === 'error') {
    return 'danger'
  }
  if (tone === 'success') {
    return 'success'
  }
  if (tone === 'info') {
    return 'info'
  }
  return 'neutral'
}

function fileRowStatusClass(file: RagFileState): string {
  if (file.status === 'failed') {
    return 'danger'
  }
  if (file.status === 'processed') {
    return 'success'
  }
  if (file.status === 'processing') {
    return 'info'
  }
  if (file.status === 'excluded') {
    return 'warning'
  }
  return 'neutral'
}

export function RagPanel({ state, bridge, bridgeConnected }: RagPanelProps) {
  const [query, setQuery] = useState('')
  const [isSearchViewActive, setIsSearchViewActive] = useState(Boolean(state.rag.search.result_text))
  const rag = state.rag
  const uiText = state.ui_text
  const previousResultTextRef = useRef(state.rag.search.result_text)

  useEffect(() => {
    const nextResultText = rag.search.result_text
    const previousResultText = previousResultTextRef.current

    if (!nextResultText) {
      setIsSearchViewActive(false)
    } else if (nextResultText !== previousResultText) {
      setIsSearchViewActive(true)
    }

    previousResultTextRef.current = nextResultText
  }, [rag.search.result_text])

  const progressRatio = useMemo(() => {
    if (!rag.progress.total) {
      return 0
    }
    return Math.max(0, Math.min(100, (rag.progress.processed / rag.progress.total) * 100))
  }, [rag.progress.processed, rag.progress.total])

  const stats = [
    { label: getUiText(uiText, 'conversation.rag.stats.documents', 'Documents'), value: String(rag.stats.total_files) },
    { label: getUiText(uiText, 'common.chunks', 'Chunks'), value: String(rag.stats.total_chunks) },
    { label: getUiText(uiText, 'conversation.rag.stats.excluded', 'Excluded'), value: String(rag.stats.excluded) },
    { label: getUiText(uiText, 'conversation.rag.stats.failed', 'Failed'), value: String(rag.stats.failed) },
    { label: getUiText(uiText, 'common.storage', 'Storage'), value: formatStorageSize(rag.stats.storage_size_mb) },
  ]

  const canSearch = bridgeConnected && rag.actions.can_search && query.trim().length > 0 && !rag.search.is_running

  return (
    <div className="rag-shell">
      <div className="rag-header">
        <div className="rag-header__identity">
          <div className="rag-header__eyebrow">{getUiText(uiText, 'conversation.rag.header.eyebrow', 'Index Library')}</div>
          <div className="rag-header__title">{getUiText(uiText, 'panel.rag', 'Index Library')}</div>
          <div className="rag-header__subtitle">{getUiText(uiText, 'conversation.rag.header.subtitle', 'Manage project index status, retrieval validation, and file entry points in one place.')}</div>
        </div>
        <span className={`status-badge status-badge--${statusToneClass(rag.status.tone)}`}>
          {rag.status.label || getUiText(uiText, 'conversation.rag.status.waiting', 'Waiting for project')}
        </span>
      </div>

      <div className="rag-toolbar">
        <button
          type="button"
          className="secondary-button rag-toolbar__button"
          onClick={() => bridge?.requestReindexKnowledge?.()}
          disabled={!bridgeConnected || !rag.actions.can_reindex}
        >
          {getUiText(uiText, 'menu.knowledge.rebuild', 'Rebuild Index')}
        </button>
        <button
          type="button"
          className="secondary-button secondary-button--danger rag-toolbar__button"
          onClick={() => bridge?.requestClearKnowledge?.()}
          disabled={!bridgeConnected || !rag.actions.can_clear}
        >
          {getUiText(uiText, 'menu.knowledge.clear', 'Clear Index')}
        </button>
      </div>

      {rag.progress.is_visible ? (
        <div className="rag-progress-card">
          <div className="rag-progress-card__meta">
            <span>{getUiText(uiText, 'conversation.rag.progress', 'Index Progress')}</span>
            <span>
              {rag.progress.processed}/{rag.progress.total}
            </span>
          </div>
          <progress className="rag-progress-bar" max={100} value={progressRatio} />
          {rag.progress.current_file ? (
            <div className="rag-progress-card__file" title={rag.progress.current_file}>
              {getUiText(uiText, 'conversation.rag.processing_file', 'Processing: {path}', { path: rag.progress.current_file })}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="rag-stats-grid">
        {stats.map((stat) => (
          <div key={stat.label} className="rag-stat-card">
            <div className="rag-stat-card__label">{stat.label}</div>
            <div className="rag-stat-card__value">{stat.value}</div>
          </div>
        ))}
      </div>

      {rag.info.message ? (
        <div className={`rag-inline-notice rag-inline-notice--${infoToneClass(rag.info.tone)}`}>
          {rag.info.message}
        </div>
      ) : null}

      <div className="rag-search-card">
        <div className="rag-section-heading">{getUiText(uiText, 'conversation.rag.search_section', 'Retrieval Test')}</div>
        <div className="rag-search-row">
          <textarea
            className="rag-search-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={getUiText(uiText, 'conversation.rag.search_placeholder', 'Enter retrieval query...')}
          />
          {isSearchViewActive ? (
            <div className="rag-search-actions">
              <button
                type="button"
                className="primary-button rag-search-button rag-search-button--stacked"
                onClick={() => bridge?.requestRagSearch?.(query.trim())}
                disabled={!canSearch}
              >
                {rag.search.is_running
                  ? getUiText(uiText, 'conversation.rag.search_running', 'Searching...')
                  : getUiText(uiText, 'common.search', 'Search')}
              </button>
              <button
                type="button"
                className="secondary-button rag-search-button rag-search-button--stacked"
                onClick={() => setIsSearchViewActive(false)}
              >
                {getUiText(uiText, 'common.back', 'Back')}
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="primary-button rag-search-button"
              onClick={() => bridge?.requestRagSearch?.(query.trim())}
              disabled={!canSearch}
            >
              {rag.search.is_running
                ? getUiText(uiText, 'conversation.rag.search_running', 'Searching...')
                : getUiText(uiText, 'common.search', 'Search')}
            </button>
          )}
        </div>
        {isSearchViewActive ? (
          <div className="rag-search-result">{rag.search.result_text || getUiText(uiText, 'conversation.rag.search_empty_result', 'Retrieval results will appear here')}</div>
        ) : null}
      </div>

      <div className="rag-files-card">
        <div className="rag-section-heading">{getUiText(uiText, 'conversation.rag.indexed_documents', 'Indexed Documents')}</div>
        <div className="rag-file-table">
          <div className="rag-file-table__head">
            <span>{getUiText(uiText, 'common.file', 'File')}</span>
            <span>{getUiText(uiText, 'common.status', 'Status')}</span>
            <span>{getUiText(uiText, 'common.chunks', 'Chunks')}</span>
            <span>{getUiText(uiText, 'common.indexed_at', 'Indexed At')}</span>
          </div>
          <div className="rag-file-table__body">
            {rag.files.length ? (
              rag.files.map((file) => {
                const canOpen = Boolean(file.path)
                return (
                  <button
                    key={`${file.relative_path}-${file.indexed_at}`}
                    type="button"
                    className={`rag-file-row rag-file-row--${fileRowStatusClass(file)}${canOpen ? ' rag-file-row--clickable' : ''}`}
                    onClick={() => {
                      if (canOpen) {
                        bridge?.openFile?.(file.path)
                      }
                    }}
                    disabled={!canOpen}
                    title={file.tooltip || file.relative_path}
                  >
                    <span className="rag-file-row__path">{file.relative_path || getUiText(uiText, 'common.unnamed_file', 'Unnamed File')}</span>
                    <span className="rag-file-row__status">{file.status_label || file.status}</span>
                    <span>{file.chunks_count}</span>
                    <span>{file.indexed_at || '—'}</span>
                  </button>
                )
              })
            ) : (
              <div className="rag-file-empty">{getUiText(uiText, 'conversation.rag.empty_files', 'No indexed files are available to display yet.')}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
