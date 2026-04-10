import { useEffect, useMemo, useRef, useState } from 'react'
import type { ConversationBridge } from '../bridge'
import type { ConversationMainState, RagFileState } from '../types'

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
    { label: '文档', value: String(rag.stats.total_files) },
    { label: '分块', value: String(rag.stats.total_chunks) },
    { label: '排除', value: String(rag.stats.excluded) },
    { label: '失败', value: String(rag.stats.failed) },
    { label: '存储', value: formatStorageSize(rag.stats.storage_size_mb) },
  ]

  const canSearch = bridgeConnected && rag.actions.can_search && query.trim().length > 0 && !rag.search.is_running

  return (
    <div className="rag-shell">
      <div className="rag-header">
        <div className="rag-header__identity">
          <div className="rag-header__eyebrow">Index Library</div>
          <div className="rag-header__title">索引库</div>
          <div className="rag-header__subtitle">统一管理项目索引状态、检索验证与文件入口。</div>
        </div>
        <span className={`status-badge status-badge--${statusToneClass(rag.status.tone)}`}>
          {rag.status.label || '等待项目'}
        </span>
      </div>

      <div className="rag-toolbar">
        <button
          type="button"
          className="secondary-button rag-toolbar__button"
          onClick={() => bridge?.requestReindexKnowledge?.()}
          disabled={!bridgeConnected || !rag.actions.can_reindex}
        >
          索引项目文件
        </button>
        <button
          type="button"
          className="secondary-button secondary-button--danger rag-toolbar__button"
          onClick={() => bridge?.requestClearKnowledge?.()}
          disabled={!bridgeConnected || !rag.actions.can_clear}
        >
          清空索引库
        </button>
      </div>

      {rag.progress.is_visible ? (
        <div className="rag-progress-card">
          <div className="rag-progress-card__meta">
            <span>索引进度</span>
            <span>
              {rag.progress.processed}/{rag.progress.total}
            </span>
          </div>
          <progress className="rag-progress-bar" max={100} value={progressRatio} />
          {rag.progress.current_file ? (
            <div className="rag-progress-card__file" title={rag.progress.current_file}>
              正在处理：{rag.progress.current_file}
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
        <div className="rag-section-heading">检索测试</div>
        <div className="rag-search-row">
          <textarea
            className="rag-search-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="输入检索内容..."
          />
          {isSearchViewActive ? (
            <div className="rag-search-actions">
              <button
                type="button"
                className="primary-button rag-search-button rag-search-button--stacked"
                onClick={() => bridge?.requestRagSearch?.(query.trim())}
                disabled={!canSearch}
              >
                {rag.search.is_running ? '检索中...' : '检索'}
              </button>
              <button
                type="button"
                className="secondary-button rag-search-button rag-search-button--stacked"
                onClick={() => setIsSearchViewActive(false)}
              >
                返回
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="primary-button rag-search-button"
              onClick={() => bridge?.requestRagSearch?.(query.trim())}
              disabled={!canSearch}
            >
              {rag.search.is_running ? '检索中...' : '检索'}
            </button>
          )}
        </div>
        {isSearchViewActive ? (
          <div className="rag-search-result">{rag.search.result_text || '检索结果将显示在此处'}</div>
        ) : null}
      </div>

      <div className="rag-files-card">
        <div className="rag-section-heading">已索引文档</div>
        <div className="rag-file-table">
          <div className="rag-file-table__head">
            <span>文件</span>
            <span>状态</span>
            <span>分块</span>
            <span>索引时间</span>
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
                    <span className="rag-file-row__path">{file.relative_path || '未命名文件'}</span>
                    <span className="rag-file-row__status">{file.status_label || file.status}</span>
                    <span>{file.chunks_count}</span>
                    <span>{file.indexed_at || '—'}</span>
                  </button>
                )
              })
            ) : (
              <div className="rag-file-empty">当前还没有可展示的索引文件。</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
