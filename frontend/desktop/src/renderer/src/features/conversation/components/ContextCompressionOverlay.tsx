import type { ConversationActions } from '../actions'
import type { ConversationContextCompressionOverlayState } from '../types'
import { getUiText } from '../uiText'
import { useDialogFocus } from './dialogFocus'

interface ContextCompressionOverlayProps {
  overlay: ConversationContextCompressionOverlayState
  actions: ConversationActions | null
  available: boolean
  contextId: string
  uiText: Record<string, string>
}

function formatCount(value: number): string {
  return Math.max(0, value).toLocaleString()
}

function formatPercent(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}

export function ContextCompressionOverlay({
  overlay,
  actions,
  available,
  contextId,
  uiText,
}: ContextCompressionOverlayProps) {
  const canUseActions = available && Boolean(actions) && Boolean(contextId)
  const canClose = canUseActions && !overlay.is_loading
  const close = () => {
    if (canClose) {
      actions?.closeContextCompression(contextId)
    }
  }
  const dialogRef = useDialogFocus(overlay.is_open, close)
  const { budget, estimated } = overlay.preview
  const messageUnit = getUiText(uiText, 'dialog.compress.messages_unit', 'messages')
  const approxTokens = getUiText(uiText, 'dialog.compress.approx_tokens', 'approx. {tokens} tokens')
    .replace('{tokens}', formatCount(estimated.summary_tokens))
  const approxUsage = getUiText(uiText, 'dialog.compress.approx_usage', 'approx. {tokens} tokens ({percent}%)')
    .replace('{tokens}', formatCount(estimated.after_tokens))
    .replace('{percent}', String(Math.round(estimated.after_ratio * 100)))

  return (
    <div className="conversation-overlay conversation-overlay--modal">
      <button
        type="button"
        className="conversation-overlay__backdrop"
        onClick={close}
        disabled={!canClose}
        aria-label={getUiText(uiText, 'btn.close', 'Close')}
      />
      <div
        ref={dialogRef}
        className="conversation-modal conversation-modal--compression"
        role="dialog"
        aria-modal="true"
        aria-labelledby="context-compression-title"
        aria-busy={overlay.is_loading}
        tabIndex={-1}
      >
        <div className="conversation-modal__header">
          <div>
            <div id="context-compression-title" className="conversation-modal__title">
              {getUiText(uiText, 'dialog.compress.title', 'Compress Context')}
            </div>
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={close}
            disabled={!canClose}
            aria-label={getUiText(uiText, 'btn.close', 'Close')}
          >
            ×
          </button>
        </div>

        <div className="conversation-modal__content compression-overlay__content">
          {overlay.error_message ? (
            <div className="conversation-overlay-alert conversation-overlay-alert--error" role="alert">
              {overlay.error_message}
            </div>
          ) : null}

          <section className="conversation-section">
            <div className="conversation-section__title">
              {getUiText(uiText, 'dialog.compress.current_status', 'Current Status')}
            </div>
            <div className="conversation-overlay-stat-grid">
              <div className="conversation-overlay-stat">
                <span>{getUiText(uiText, 'dialog.compress.message_count', 'History message count:')}</span>
                <strong>{formatCount(budget.history_message_count)} {messageUnit}</strong>
              </div>
              <div className="conversation-overlay-stat">
                <span>{getUiText(uiText, 'dialog.compress.token_usage', 'Token usage:')}</span>
                <strong>{formatCount(budget.total_tokens)} / {formatCount(budget.input_limit)} · {formatPercent(budget.usage_ratio)}</strong>
              </div>
            </div>
            <div className="compression-overlay__usage-track" aria-hidden="true">
              <span style={{ width: formatPercent(budget.usage_ratio) }} />
            </div>
          </section>

          <section className="conversation-section">
            <div className="conversation-section__title">
              {getUiText(uiText, 'dialog.compress.estimate', 'Compression Estimate')}
            </div>
            <label className="compression-overlay__keep-row">
              <span>{getUiText(uiText, 'dialog.compress.keep_count', 'Keep recent messages:')}</span>
              <input
                data-dialog-initial-focus
                type="number"
                min={2}
                max={20}
                step={1}
                value={overlay.keep_recent}
                disabled={!canUseActions || overlay.is_loading}
                onChange={(event) => {
                  const nextValue = Number(event.currentTarget.value)
                  if (Number.isFinite(nextValue)) {
                    actions?.setContextCompressionKeepRecent(contextId, nextValue)
                  }
                }}
              />
            </label>
            <div className="conversation-overlay-stat-grid">
              <div className="conversation-overlay-stat">
                <span>{getUiText(uiText, 'dialog.compress.must_keep', 'Messages kept directly in working context:')}</span>
                <strong>{formatCount(estimated.direct_count)} {messageUnit}</strong>
              </div>
              <div className="conversation-overlay-stat">
                <span>{getUiText(uiText, 'dialog.compress.will_compress', 'History messages covered by summary:')}</span>
                <strong>{formatCount(estimated.summarized_count)} {messageUnit}</strong>
              </div>
              <div className="conversation-overlay-stat">
                <span>{getUiText(uiText, 'dialog.compress.estimated_summary', 'Estimated summary:')}</span>
                <strong>{approxTokens}</strong>
              </div>
              <div className="conversation-overlay-stat">
                <span>{getUiText(uiText, 'dialog.compress.estimated_after', 'After compression:')}</span>
                <strong>{approxUsage}</strong>
              </div>
            </div>
          </section>

          <section className="conversation-section compression-overlay__summary">
            <div className="conversation-section__title">
              {getUiText(uiText, 'dialog.compress.preview', 'Summary Preview')}
            </div>
            <div className="conversation-overlay-code">{overlay.preview.summary_preview}</div>
          </section>
        </div>

        <div className="conversation-modal__footer">
          <button type="button" className="secondary-button" onClick={close} disabled={!canClose}>
            {getUiText(uiText, 'btn.cancel', 'Cancel')}
          </button>
          <button
            type="button"
            className="primary-button"
            onClick={() => actions?.confirmContextCompression(contextId)}
            disabled={!canUseActions || overlay.is_loading || estimated.summarized_count <= 0}
          >
            {overlay.is_loading
              ? getUiText(uiText, 'status.running', 'Running...')
              : getUiText(uiText, 'dialog.compress.btn_confirm', 'Confirm Compression')}
          </button>
        </div>
      </div>
    </div>
  )
}
