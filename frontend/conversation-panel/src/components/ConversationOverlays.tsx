import type { ConversationBridge } from '../bridge'
import { ModelConfigApp } from '../ModelConfigApp'
import type {
  ConversationHistoryOverlayState,
  ConversationMainState,
  ConversationModelConfigOverlayState,
  ConversationRollbackFileChangeState,
  ConversationRollbackPreviewState,
  ConversationSessionInfoState,
  ConversationSessionMessageState,
} from '../types'

interface ConversationOverlaysProps {
  state: ConversationMainState
  bridge: ConversationBridge | null
  bridgeConnected: boolean
}

const EXPORT_FORMATS = [
  { value: 'json', label: 'JSON' },
  { value: 'txt', label: 'TXT' },
  { value: 'md', label: 'Markdown' },
] as const

 function roleLabel(role: string): string {
   return {
     user: '用户',
     assistant: '助手',
     system: '系统',
   }[role] ?? '消息'
 }

function findSelectedSession(history: ConversationHistoryOverlayState): ConversationSessionInfoState | null {
  return history.sessions.find((session) => session.session_id === history.selected_session_id) ?? null
}

function renderSessionPreviewMessage(message: ConversationSessionMessageState) {
  return (
    <div key={message.message_id || `${message.role}-${message.timestamp}`} className="conversation-overlay-card">
      <div className="conversation-overlay-card__header">
        <span className="conversation-overlay-card__title">{roleLabel(message.role)}</span>
        <span className="conversation-overlay-card__subtitle">{message.timestamp || '未知时间'}</span>
      </div>
      <div className="conversation-overlay-card__body conversation-overlay-card__body--text">
        {message.content || '（空消息）'}
      </div>
      {message.attachments.length > 0 ? (
        <div className="conversation-overlay-chip-list">
          {message.attachments.map((attachment) => (
            <span
              key={attachment.reference_id || attachment.path || attachment.name}
              className="conversation-overlay-chip"
            >
              {attachment.name || attachment.path || '附件'}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function renderFileChangeList(fileChanges: ConversationRollbackFileChangeState[]) {
  if (fileChanges.length === 0) {
    return <div className="conversation-overlay-empty">暂无文件变更。</div>
  }

  return (
    <div className="conversation-overlay-card-list">
      {fileChanges.map((fileChange) => (
        <div
          key={`${fileChange.relative_path}-${fileChange.change_type}-${fileChange.added_lines}-${fileChange.deleted_lines}`}
          className="conversation-overlay-card"
        >
          <div className="conversation-overlay-card__header">
            <div>
              <div className="conversation-overlay-card__title">{fileChange.relative_path || '工作区文件'}</div>
              <div className="conversation-overlay-card__subtitle">{fileChange.summary || fileChange.change_type || '已变更'}</div>
            </div>
            <div className="conversation-overlay-stats">
              <span>+{fileChange.added_lines}</span>
              <span>-{fileChange.deleted_lines}</span>
            </div>
          </div>
          {fileChange.diff_preview ? (
            <pre className="conversation-overlay-code">{fileChange.diff_preview}</pre>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function HistorySessionRow({
  session,
  history,
  bridge,
}: {
  session: ConversationSessionInfoState
  history: ConversationHistoryOverlayState
  bridge: ConversationBridge | null
}) {
  const isCurrentSession = session.session_id === history.current_session_id

  return (
    <button
      type="button"
      className={[
        'conversation-session-row',
        session.session_id === history.selected_session_id ? 'conversation-session-row--active' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={() => bridge?.selectHistorySession?.(session.session_id)}
    >
      <div className="conversation-session-row__top">
        <div className="conversation-session-row__summary">
          <span
            className="conversation-session-row__title"
            title={session.name || session.session_id}
          >
            {session.name || session.session_id}
          </span>
          <div className="conversation-session-row__meta">
            <span className="conversation-session-row__meta-item conversation-session-row__meta-item--count">
              {session.message_count} 条消息
            </span>
            <span
              className="conversation-session-row__meta-item conversation-session-row__meta-item--timestamp"
              title={session.updated_at || session.created_at || ''}
            >
              {session.updated_at || session.created_at || ''}
            </span>
          </div>
        </div>
        {isCurrentSession ? (
          <span className="conversation-status-badge conversation-status-badge--session-current">当前</span>
        ) : null}
      </div>
      <div className="conversation-session-row__preview">{session.preview || '无摘要'}</div>
    </button>
  )
}

function HistoryExportDialog({
  history,
  selectedSession,
  bridge,
}: {
  history: ConversationHistoryOverlayState
  selectedSession: ConversationSessionInfoState
  bridge: ConversationBridge | null
}) {
  const exportDialog = history.export_dialog
  if (!exportDialog.is_open || exportDialog.session_id !== selectedSession.session_id) {
    return null
  }

  return (
    <div className="conversation-history-export-dialog" role="dialog" aria-label="导出会话">
      <div className="conversation-history-export-dialog__title">导出当前会话</div>
      <div className="conversation-history-export-dialog__section">
        <div className="conversation-history-export-dialog__label">导出格式</div>
        <div className="conversation-overlay-chip-list">
          {EXPORT_FORMATS.map((item) => (
            <button
              key={item.value}
              type="button"
              className={[
                'secondary-button',
                exportDialog.export_format === item.value ? 'conversation-history-export-dialog__format-button--active' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              onClick={() => bridge?.setHistoryExportFormat?.(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      <div className="conversation-history-export-dialog__section">
        <div className="conversation-history-export-dialog__label">导出路径</div>
        <div className="conversation-history-export-dialog__path" title={exportDialog.file_path || '未选择导出路径'}>
          {exportDialog.file_path || '请选择导出路径'}
        </div>
      </div>
      <div className="conversation-history-export-dialog__actions">
        <button type="button" className="secondary-button" onClick={() => bridge?.chooseHistoryExportPath?.()}>
          选择路径
        </button>
        <button type="button" className="secondary-button" onClick={() => bridge?.closeHistoryExportDialog?.()}>
          取消
        </button>
        <button
          type="button"
          className="primary-button"
          disabled={!exportDialog.file_path}
          onClick={() =>
            bridge?.requestExportHistorySession?.(
              selectedSession.session_id,
              exportDialog.export_format,
              exportDialog.file_path,
            )
          }
        >
          确认导出
        </button>
      </div>
    </div>
  )
}

function HistoryHeaderActions({
  history,
  selectedSession,
  bridge,
}: {
  history: ConversationHistoryOverlayState
  selectedSession: ConversationSessionInfoState | null
  bridge: ConversationBridge | null
}) {
  const selectedSessionId = selectedSession?.session_id ?? ''
  const hasSelectedSession = Boolean(selectedSessionId)

  return (
    <div className="conversation-history-header-actions">
      <button
        type="button"
        className="secondary-button"
        disabled={!hasSelectedSession}
        onClick={() => bridge?.openHistorySession?.(selectedSessionId)}
      >
        打开
      </button>
      <button
        type="button"
        className="secondary-button secondary-button--danger"
        disabled={!hasSelectedSession}
        onClick={() => bridge?.requestDeleteHistorySession?.(selectedSessionId)}
      >
        删除
      </button>
      <button
        type="button"
        className="secondary-button"
        disabled={!hasSelectedSession}
        onClick={() => bridge?.openHistoryExportDialog?.(selectedSessionId)}
      >
        导出
      </button>
      {selectedSession ? <HistoryExportDialog history={history} selectedSession={selectedSession} bridge={bridge} /> : null}
    </div>
  )
}

function HistoryHeaderInfo({
  history,
}: {
  history: ConversationHistoryOverlayState
}) {
  return (
    <div className="conversation-history-header-info-line">
      <div className="conversation-drawer__title">会话历史</div>
      <div className="conversation-drawer__subtitle conversation-history-header-info-line__subtitle">
        {history.sessions.length > 0 ? `共 ${history.sessions.length} 个会话` : '暂无历史会话'}
      </div>
    </div>
  )
}

function HistoryOverlay({
  history,
  bridge,
}: {
  history: ConversationHistoryOverlayState
  bridge: ConversationBridge | null
}) {
  const selectedSession = findSelectedSession(history)

  return (
    <div className="conversation-overlay conversation-overlay--sheet">
      <button
        type="button"
        className="conversation-overlay__backdrop"
        onClick={() => bridge?.closeHistory?.()}
        aria-label="关闭会话历史"
      />
      <div className="conversation-drawer" role="dialog" aria-modal="true" aria-label="会话历史">
        <div className="conversation-drawer__header conversation-drawer__header--history">
          <div className="conversation-drawer__header-info conversation-drawer__header-info--history">
            <HistoryHeaderInfo history={history} />
          </div>
          <HistoryHeaderActions history={history} selectedSession={selectedSession} bridge={bridge} />
        </div>
        <div className="conversation-drawer__content">
          <div className="conversation-drawer__list">
            {history.sessions.length > 0 ? (
              history.sessions.map((session) => (
                <HistorySessionRow
                  key={session.session_id}
                  session={session}
                  history={history}
                  bridge={bridge}
                />
              ))
            ) : (
              <div className="conversation-overlay-empty">暂无历史会话。</div>
            )}
          </div>
          <HistoryDetailPanel history={history} selectedSession={selectedSession} />
        </div>
      </div>
    </div>
  )
}

function HistoryDetailPanel({
  history,
  selectedSession,
}: {
  history: ConversationHistoryOverlayState
  selectedSession: ConversationSessionInfoState | null
}) {
  if (!selectedSession) {
    return (
      <div className="conversation-history-detail">
        <div className="conversation-overlay-empty">请选择一个会话查看详情。</div>
        {history.error_message ? (
          <div className="conversation-overlay-alert conversation-overlay-alert--error">
            {history.error_message}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="conversation-history-detail">

      <section className="conversation-history-preview">
        <div className="conversation-history-section__header">
          <div className="conversation-history-section__title">预览</div>
          <div className="conversation-history-section__subtitle">
            {history.is_loading
              ? '正在加载当前选中会话'
              : history.preview_messages.length > 0
                ? '当前选中会话的消息片段'
                : '当前会话暂无可预览内容'}
          </div>
        </div>
        <div className="conversation-history-preview__body">
          {history.is_loading ? (
            <div className="conversation-overlay-empty">正在加载会话预览。</div>
          ) : history.preview_messages.length > 0 ? (
            <div className="conversation-history-preview__list">
              {history.preview_messages.map((message) => renderSessionPreviewMessage(message))}
            </div>
          ) : (
            <div className="conversation-overlay-empty">暂无消息预览。</div>
          )}
        </div>
      </section>

      {history.error_message ? (
        <div className="conversation-overlay-alert conversation-overlay-alert--error">
          {history.error_message}
        </div>
      ) : null}
    </div>
  )
}

function RollbackOverlay({
  preview,
  bridge,
}: {
  preview: ConversationRollbackPreviewState
  bridge: ConversationBridge | null
}) {
  return (
    <div className="conversation-overlay conversation-overlay--modal">
      <button
        type="button"
        className="conversation-overlay__backdrop"
        onClick={() => bridge?.closeRollbackPreview?.()}
        aria-label="关闭撤回预览"
      />
      <div className="conversation-modal conversation-modal--wide" role="dialog" aria-modal="true" aria-label="撤回预览">
        <div className="conversation-modal__header">
          <div>
            <div className="conversation-modal__title">撤回预览</div>
            <div className="conversation-modal__subtitle">目标消息：{preview.anchor_label || preview.anchor_message_id || '未知消息'}</div>
          </div>
          <button type="button" className="ghost-button" onClick={() => bridge?.closeRollbackPreview?.()}>
            取消
          </button>
        </div>
        <div className="conversation-modal__content">
          <div className="conversation-overlay-stat-grid">
            <div className="conversation-overlay-stat-card">
              <span className="conversation-overlay-stat-card__label">当前消息数</span>
              <span className="conversation-overlay-stat-card__value">{preview.current_message_count}</span>
            </div>
            <div className="conversation-overlay-stat-card">
              <span className="conversation-overlay-stat-card__label">撤回后消息数</span>
              <span className="conversation-overlay-stat-card__value">{preview.target_message_count}</span>
            </div>
            <div className="conversation-overlay-stat-card">
              <span className="conversation-overlay-stat-card__label">移除消息</span>
              <span className="conversation-overlay-stat-card__value">{preview.removed_message_count}</span>
            </div>
            <div className="conversation-overlay-stat-card">
              <span className="conversation-overlay-stat-card__label">工作区变更文件</span>
              <span className="conversation-overlay-stat-card__value">{preview.changed_file_count}</span>
            </div>
          </div>
          <div className="conversation-section">
            <div className="conversation-section__header">
              <div className="conversation-section__title">将被移除的消息</div>
              <div className="conversation-section__subtitle">{preview.removed_message_count} 条</div>
            </div>
            <div className="conversation-overlay-card-list">
              {preview.removed_messages.length > 0 ? (
                preview.removed_messages.map((message) => (
                  <div key={message.message_id} className="conversation-overlay-card">
                    <div className="conversation-overlay-card__header">
                      <span className="conversation-overlay-card__title">{roleLabel(message.role)}</span>
                      <span className="conversation-overlay-card__subtitle">{message.timestamp || '未知时间'}</span>
                    </div>
                    <div className="conversation-overlay-card__body conversation-overlay-card__body--text">
                      {message.content_preview || '（空消息）'}
                    </div>
                  </div>
                ))
              ) : (
                <div className="conversation-overlay-empty">没有待移除消息。</div>
              )}
            </div>
          </div>
          <div className="conversation-section">
            <div className="conversation-section__header">
              <div className="conversation-section__title">工作区快照差异</div>
              <div className="conversation-section__subtitle">
                +{preview.total_added_lines} / -{preview.total_deleted_lines}
              </div>
            </div>
            {renderFileChangeList(preview.changed_files)}
          </div>
        </div>
        <div className="conversation-modal__footer">
          <button type="button" className="secondary-button" onClick={() => bridge?.closeRollbackPreview?.()}>
            取消
          </button>
          <button type="button" className="primary-button primary-button--stop" onClick={() => bridge?.confirmRollback?.()}>
            确认撤回
          </button>
        </div>
      </div>
    </div>
  )
}

function ModelConfigOverlay({
  overlay,
  bridge,
  bridgeConnected,
}: {
  overlay: ConversationModelConfigOverlayState
  bridge: ConversationBridge | null
  bridgeConnected: boolean
}) {
  return (
    <div className="conversation-overlay conversation-overlay--modal">
      <button
        type="button"
        className="conversation-overlay__backdrop"
        onClick={() => bridge?.closeModelConfig?.()}
        aria-label="关闭模型配置"
      />
      <div
        className="conversation-modal conversation-modal--model-config"
        role="dialog"
        aria-modal="true"
        aria-label={overlay.state.surface.title || '模型配置'}
      >
        <ModelConfigApp state={overlay.state} bridge={bridge} bridgeConnected={bridgeConnected} />
      </div>
    </div>
  )
}

export function ConversationOverlays({ state, bridge, bridgeConnected }: ConversationOverlaysProps) {
  const { history, rollback, model_config, confirm, notice } = state.overlays

  return (
    <>
      {history.is_open ? <HistoryOverlay history={history} bridge={bridge} /> : null}
      {rollback.is_open ? <RollbackOverlay preview={rollback.preview} bridge={bridge} /> : null}
      {model_config.is_open ? (
        <ModelConfigOverlay overlay={model_config} bridge={bridge} bridgeConnected={bridgeConnected} />
      ) : null}
      {confirm.is_open ? (
        <div className="conversation-overlay conversation-overlay--modal">
          <button
            type="button"
            className="conversation-overlay__backdrop"
            onClick={() => bridge?.resolveConfirmDialog?.(false)}
            aria-label="关闭确认对话框"
          />
          <div className="conversation-modal conversation-modal--compact" role="dialog" aria-modal="true" aria-label="确认操作">
            <div className="conversation-modal__header">
              <div>
                <div className="conversation-modal__title">{confirm.title || '确认操作'}</div>
              </div>
            </div>
            <div className="conversation-modal__content">
              <div
                className={[
                  'conversation-overlay-alert',
                  confirm.tone === 'danger' ? 'conversation-overlay-alert--error' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                {confirm.message}
              </div>
            </div>
            <div className="conversation-modal__footer">
              <button type="button" className="secondary-button" onClick={() => bridge?.resolveConfirmDialog?.(false)}>
                {confirm.cancel_label || '取消'}
              </button>
              <button
                type="button"
                className={[
                  'primary-button',
                  confirm.tone === 'danger' ? 'primary-button--stop' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => bridge?.resolveConfirmDialog?.(true)}
              >
                {confirm.confirm_label || '确认'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {notice.is_open ? (
        <div className="conversation-overlay conversation-overlay--modal">
          <button
            type="button"
            className="conversation-overlay__backdrop"
            onClick={() => bridge?.closeNoticeDialog?.()}
            aria-label="关闭提示对话框"
          />
          <div className="conversation-modal conversation-modal--compact" role="dialog" aria-modal="true" aria-label="提示">
            <div className="conversation-modal__header">
              <div>
                <div className="conversation-modal__title">{notice.title || '提示'}</div>
              </div>
            </div>
            <div className="conversation-modal__content">
              <div
                className={[
                  'conversation-overlay-alert',
                  notice.tone === 'error' ? 'conversation-overlay-alert--error' : '',
                  notice.tone === 'success' ? 'conversation-overlay-alert--success' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                {notice.message}
              </div>
            </div>
            <div className="conversation-modal__footer">
              <button type="button" className="primary-button" onClick={() => bridge?.closeNoticeDialog?.()}>
                知道了
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
