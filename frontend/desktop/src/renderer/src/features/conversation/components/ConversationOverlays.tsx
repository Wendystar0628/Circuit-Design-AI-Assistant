import type { ConversationActions } from '../actions'
import { getUiText } from '../uiText'
import { ContextCompressionOverlay } from './ContextCompressionOverlay'
import { ImagePreviewOverlay } from './ImagePreviewOverlay'
import { SafeMarkdown } from './SafeMarkdown'
import { useDialogFocus } from './dialogFocus'
import type {
  ConversationHistoryOverlayState,
  ConversationMainState,
  ConversationRollbackFileChangeState,
  ConversationRollbackPreviewState,
  ConversationSessionInfoState,
  ConversationSessionMessageState,
} from '../types'

interface ConversationOverlaysProps {
  state: ConversationMainState
  actions: ConversationActions | null
  available: boolean
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

function renderSessionPreviewMessage(
  message: ConversationSessionMessageState,
  actions: ConversationActions | null,
  contextId: string,
) {
  return (
    <div key={message.message_id || `${message.role}-${message.timestamp}`} className="conversation-overlay-card">
      <div className="conversation-overlay-card__header">
        <span className="conversation-overlay-card__title">{roleLabel(message.role)}</span>
        <span className="conversation-overlay-card__subtitle">{message.timestamp || '未知时间'}</span>
      </div>
      {message.reasoning_content ? (
        <details className="conversation-history-reasoning">
          <summary>思考过程</summary>
          <SafeMarkdown
            content={message.reasoning_content}
            actions={actions}
            contextId={contextId}
            className="conversation-overlay-card__body conversation-overlay-card__body--text"
          />
        </details>
      ) : null}
      {message.content ? (
        <SafeMarkdown
          content={message.content}
          actions={actions}
          contextId={contextId}
          className="conversation-overlay-card__body conversation-overlay-card__body--text"
        />
      ) : (
        <div className="conversation-overlay-card__body conversation-overlay-card__body--text">（空消息）</div>
      )}
      {message.is_partial ? (
        <div className="partial-badge">{message.stop_reason || '消息未完整生成'}</div>
      ) : null}
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
  actions,
  disabled,
}: {
  session: ConversationSessionInfoState
  history: ConversationHistoryOverlayState
  actions: ConversationActions | null
  disabled: boolean
}) {
  const isCurrentSession = session.session_id === history.current_session_id
  const isSelectedSession = session.session_id === history.selected_session_id

  return (
    <button
      type="button"
      className={[
        'conversation-session-row',
        isSelectedSession ? 'conversation-session-row--active' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      disabled={disabled}
      aria-pressed={isSelectedSession}
      aria-current={isCurrentSession ? 'true' : undefined}
      onClick={() => actions?.selectHistorySession?.(session.session_id)}
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
  actions,
  contextId,
  actionsDisabled,
}: {
  history: ConversationHistoryOverlayState
  selectedSession: ConversationSessionInfoState
  actions: ConversationActions | null
  contextId: string
  actionsDisabled: boolean
}) {
  const exportDialog = history.export_dialog
  const isOpen = exportDialog.is_open && exportDialog.session_id === selectedSession.session_id
  const dialogRef = useDialogFocus(isOpen, () => actions?.closeHistoryExportDialog?.())
  if (!isOpen) {
    return null
  }

  return (
    <div
      ref={dialogRef}
      className="conversation-history-export-dialog"
      role="dialog"
      aria-labelledby="conversation-history-export-title"
      tabIndex={-1}
    >
      <div id="conversation-history-export-title" className="conversation-history-export-dialog__title">导出当前会话</div>
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
              disabled={actionsDisabled}
              aria-pressed={exportDialog.export_format === item.value}
              onClick={() => actions?.setHistoryExportFormat?.(item.value)}
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
        <button
          type="button"
          className="secondary-button"
          disabled={actionsDisabled}
          onClick={() => actions?.chooseHistoryExportPath(contextId)}
        >
          选择路径
        </button>
        <button type="button" className="secondary-button" onClick={() => actions?.closeHistoryExportDialog?.()}>
          取消
        </button>
        <button
          type="button"
          className="primary-button"
          disabled={actionsDisabled || !exportDialog.file_path}
          onClick={() =>
            actions?.requestExportHistorySession?.(
              contextId,
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
  actions,
  sessionActionsDisabled,
  contextId,
}: {
  history: ConversationHistoryOverlayState
  selectedSession: ConversationSessionInfoState | null
  actions: ConversationActions | null
  sessionActionsDisabled: boolean
  contextId: string
}) {
  const selectedSessionId = selectedSession?.session_id ?? ''
  const hasSelectedSession = Boolean(selectedSessionId)

  return (
    <div className="conversation-history-header-actions">
      <button
        type="button"
        className="secondary-button"
        disabled={!hasSelectedSession || sessionActionsDisabled}
        onClick={() => actions?.openHistorySession?.(contextId, selectedSessionId)}
      >
        打开
      </button>
      <button
        type="button"
        className="secondary-button secondary-button--danger"
        disabled={!hasSelectedSession || sessionActionsDisabled}
        onClick={() => actions?.requestDeleteHistorySession?.(contextId, selectedSessionId)}
      >
        删除
      </button>
      <button
        type="button"
        className="secondary-button"
        disabled={!hasSelectedSession || sessionActionsDisabled}
        onClick={() => actions?.openHistoryExportDialog?.(selectedSessionId)}
      >
        导出
      </button>
      {selectedSession ? (
        <HistoryExportDialog
          history={history}
          selectedSession={selectedSession}
          actions={actions}
          contextId={contextId}
          actionsDisabled={sessionActionsDisabled}
        />
      ) : null}
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
      <div id="conversation-history-title" className="conversation-drawer__title">会话历史</div>
      <div className="conversation-drawer__subtitle conversation-history-header-info-line__subtitle">
        {history.sessions.length > 0 ? `共 ${history.sessions.length} 个会话` : '暂无历史会话'}
      </div>
    </div>
  )
}

function HistoryOverlay({
  history,
  actions,
  sessionActionsDisabled,
  contextId,
}: {
  history: ConversationHistoryOverlayState
  actions: ConversationActions | null
  sessionActionsDisabled: boolean
  contextId: string
}) {
  const selectedSession = findSelectedSession(history)
  const dialogRef = useDialogFocus(true, () => actions?.closeHistory?.())

  return (
    <div className="conversation-overlay conversation-overlay--sheet">
      <button
        type="button"
        className="conversation-overlay__backdrop"
        onClick={() => actions?.closeHistory?.()}
        aria-label="关闭会话历史"
      />
      <div
        ref={dialogRef}
        className="conversation-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="conversation-history-title"
        tabIndex={-1}
      >
        <div className="conversation-drawer__header conversation-drawer__header--history">
          <div className="conversation-drawer__header-info conversation-drawer__header-info--history">
            <HistoryHeaderInfo history={history} />
          </div>
          <HistoryHeaderActions
            history={history}
            selectedSession={selectedSession}
            actions={actions}
            sessionActionsDisabled={sessionActionsDisabled}
            contextId={contextId}
          />
        </div>
        <div className="conversation-drawer__content">
          <div className="conversation-drawer__list">
            {history.sessions.length > 0 ? (
              history.sessions.map((session) => (
                <HistorySessionRow
                  key={session.session_id}
                  session={session}
                  history={history}
                  actions={actions}
                  disabled={sessionActionsDisabled}
                />
              ))
            ) : (
              <div className="conversation-overlay-empty">暂无历史会话。</div>
            )}
          </div>
          <HistoryDetailPanel
            history={history}
            selectedSession={selectedSession}
            actions={actions}
            contextId={contextId}
          />
        </div>
      </div>
    </div>
  )
}

function HistoryDetailPanel({
  history,
  selectedSession,
  actions,
  contextId,
}: {
  history: ConversationHistoryOverlayState
  selectedSession: ConversationSessionInfoState | null
  actions: ConversationActions | null
  contextId: string
}) {
  if (!selectedSession) {
    return (
      <div className="conversation-history-detail">
        <div className="conversation-overlay-empty">请选择一个会话查看详情。</div>
        {history.error_message ? (
          <div className="conversation-overlay-alert conversation-overlay-alert--error" role="alert">
            {history.error_message}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="conversation-history-detail">

      <section className="conversation-history-preview" aria-busy={history.is_loading}>
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
              {history.preview_messages.map((message) => renderSessionPreviewMessage(message, actions, contextId))}
            </div>
          ) : (
            <div className="conversation-overlay-empty">暂无消息预览。</div>
          )}
        </div>
      </section>

      {history.error_message ? (
        <div className="conversation-overlay-alert conversation-overlay-alert--error" role="alert">
          {history.error_message}
        </div>
      ) : null}
    </div>
  )
}

function RollbackOverlay({
  preview,
  actions,
  contextId,
  loading,
  errorMessage,
}: {
  preview: ConversationRollbackPreviewState
  actions: ConversationActions | null
  contextId: string
  loading: boolean
  errorMessage: string
}) {
  const close = () => {
    if (!loading) {
      actions?.closeRollbackPreview(contextId)
    }
  }
  const dialogRef = useDialogFocus(true, close)

  return (
    <div className="conversation-overlay conversation-overlay--modal">
      <button
        type="button"
        className="conversation-overlay__backdrop"
        onClick={close}
        disabled={loading}
        aria-label="关闭撤回预览"
      />
      <div
        ref={dialogRef}
        className="conversation-modal conversation-modal--wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="conversation-rollback-title"
        aria-busy={loading}
        tabIndex={-1}
      >
        <div className="conversation-modal__header">
          <div>
            <div id="conversation-rollback-title" className="conversation-modal__title">撤回预览</div>
            <div className="conversation-modal__subtitle">目标消息：{preview.anchor_label || preview.anchor_message_id || '未知消息'}</div>
          </div>
          <button type="button" className="ghost-button" onClick={close} disabled={loading}>
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
          {errorMessage ? (
            <div className="conversation-overlay-alert conversation-overlay-alert--error" role="alert">
              {errorMessage}
            </div>
          ) : null}
        </div>
        <div className="conversation-modal__footer">
          <button type="button" className="secondary-button" onClick={close} disabled={loading}>
            取消
          </button>
          <button
            type="button"
            className="primary-button primary-button--stop"
            disabled={!actions || !contextId || !preview.operation_token || loading}
            onClick={() => actions?.confirmRollback?.(contextId, preview.operation_token)}
          >
            {loading ? '正在撤回…' : '确认撤回'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function ConversationOverlays({ state, actions, available }: ConversationOverlaysProps) {
  const { history, rollback, context_compression, image_preview, confirm, notice } = state.overlays
  const confirmDialogRef = useDialogFocus(
    confirm.is_open,
    () => actions?.resolveConfirmDialog?.(confirm.dialog_id, confirm.context_id, false),
  )
  const noticeDialogRef = useDialogFocus(notice.is_open, () => actions?.closeNoticeDialog?.())

  return (
    <>
      {history.is_open ? (
        <HistoryOverlay
          history={history}
          actions={actions}
          sessionActionsDisabled={!available || !state.context_id || state.view_flags.is_busy}
          contextId={state.context_id}
        />
      ) : null}
      {rollback.is_open ? (
        <RollbackOverlay
          preview={rollback.preview}
          actions={actions}
          contextId={state.context_id}
          loading={rollback.is_loading}
          errorMessage={rollback.error_message}
        />
      ) : null}
      {context_compression.is_open ? (
        <ContextCompressionOverlay
          overlay={context_compression}
          actions={actions}
          available={available}
          contextId={state.context_id}
          uiText={state.ui_text}
        />
      ) : null}
      {image_preview.is_open ? (
        <ImagePreviewOverlay
          overlay={image_preview}
          actions={actions}
          available={available}
          contextId={state.context_id}
          uiText={state.ui_text}
        />
      ) : null}
      {confirm.is_open ? (
        <div className="conversation-overlay conversation-overlay--modal">
          <button
            type="button"
            className="conversation-overlay__backdrop"
            onClick={() => actions?.resolveConfirmDialog?.(confirm.dialog_id, confirm.context_id, false)}
            aria-label="关闭确认对话框"
          />
          <div
            ref={confirmDialogRef}
            className="conversation-modal conversation-modal--compact"
            role="dialog"
            aria-modal="true"
            aria-labelledby="conversation-confirm-title"
            aria-describedby="conversation-confirm-message"
            tabIndex={-1}
          >
            <div className="conversation-modal__header">
              <div>
                <div id="conversation-confirm-title" className="conversation-modal__title">{confirm.title || '确认操作'}</div>
              </div>
            </div>
            <div className="conversation-modal__content">
              <div
                id="conversation-confirm-message"
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
              <button
                type="button"
                className="secondary-button"
                disabled={!available || !confirm.dialog_id}
                onClick={() => actions?.resolveConfirmDialog?.(confirm.dialog_id, confirm.context_id, false)}
              >
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
                disabled={!available || !confirm.dialog_id}
                onClick={() => actions?.resolveConfirmDialog?.(confirm.dialog_id, confirm.context_id, true)}
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
            onClick={() => actions?.closeNoticeDialog?.()}
            aria-label="关闭提示对话框"
          />
          <div
            ref={noticeDialogRef}
            className="conversation-modal conversation-modal--compact"
            role="dialog"
            aria-modal="true"
            aria-labelledby="conversation-notice-title"
            aria-describedby="conversation-notice-message"
            tabIndex={-1}
          >
            <div className="conversation-modal__header">
              <div>
                <div id="conversation-notice-title" className="conversation-modal__title">{notice.title || '提示'}</div>
              </div>
            </div>
            <div className="conversation-modal__content">
              <div
                id="conversation-notice-message"
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
              <button type="button" className="primary-button" onClick={() => actions?.closeNoticeDialog?.()}>
                {getUiText(state.ui_text, 'btn.close', 'Close')}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
