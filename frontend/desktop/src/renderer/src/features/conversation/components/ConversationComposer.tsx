import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'

import type { ConversationActions } from '../actions'
import type {
  ConversationAttachmentState,
  ConversationMainState,
  PendingWorkspaceEditSummaryState,
} from '../types'
import { getUiText } from '../uiText'

interface ConversationComposerProps {
  state: ConversationMainState
  actions: ConversationActions | null
  available: boolean
}

function attachmentKey(attachment: ConversationAttachmentState): string {
  return attachment.reference_id || attachment.path || attachment.name
}

function isInlineAttachment(attachment: ConversationAttachmentState): boolean {
  return attachment.placement === 'inline'
}

function mergeAttachments(
  current: ConversationAttachmentState[],
  incoming: ConversationAttachmentState[],
): ConversationAttachmentState[] {
  const seen = new Set(current.map((attachment) => attachmentKey(attachment)))
  const merged = [...current]
  for (const attachment of incoming) {
    const key = attachmentKey(attachment)
    if (!key || seen.has(key)) {
      continue
    }
    merged.push(attachment)
    seen.add(key)
  }
  return merged
}

function serializeDraft(
  draftText: string,
  attachments: ConversationAttachmentState[],
): string {
  const inlineMarkers = attachments
    .filter((attachment) => isInlineAttachment(attachment))
    .map((attachment) => attachment.inline_marker.trim())
    .filter(Boolean)

  if (!inlineMarkers.length) {
    return draftText
  }
  if (!draftText) {
    return inlineMarkers.join('\n')
  }
  const separator = draftText.endsWith('\n') ? '' : '\n'
  return `${draftText}${separator}${inlineMarkers.join('\n')}`
}

function formatCompactTokenCount(value: number): string {
  const normalized = Math.max(0, value)
  if (normalized >= 1_000_000) {
    const compact = normalized >= 10_000_000
      ? (normalized / 1_000_000).toFixed(0)
      : (normalized / 1_000_000).toFixed(1)
    return `${compact.replace(/\.0$/, '')}M`
  }
  if (normalized >= 1_000) {
    const compact = normalized >= 100_000
      ? (normalized / 1_000).toFixed(0)
      : (normalized / 1_000).toFixed(1)
    return `${compact.replace(/\.0$/, '')}K`
  }
  return `${Math.round(normalized)}`
}

function primaryActionLabel(mode: string, uiText: Record<string, string>): string {
  switch (mode) {
    case 'send':
      return getUiText(uiText, 'conversation.composer.action.send', 'Send')
    case 'stop':
      return getUiText(uiText, 'conversation.composer.action.stop', 'Stop')
    case 'stopping':
      return getUiText(uiText, 'conversation.composer.action.stopping', 'Stopping')
    default:
      return getUiText(uiText, 'conversation.composer.action.unavailable', 'Unavailable')
  }
}

function usageTone(state: string): string {
  if (state === 'critical') {
    return 'critical'
  }
  if (state === 'warning') {
    return 'warning'
  }
  return 'normal'
}

function PendingEditSummary({
  summary,
  actions,
  uiText,
  actionsDisabled,
  contextId,
}: {
  summary: PendingWorkspaceEditSummaryState
  actions: ConversationActions | null
  uiText: Record<string, string>
  actionsDisabled: boolean
  contextId: string
}) {
  const [expanded, setExpanded] = useState(false)
  if (!summary.file_count) {
    return null
  }

  return (
    <section className="composer-summary">
      <div className="composer-summary__header">
        <div className="composer-summary__stats">
          <span>{getUiText(uiText, 'conversation.composer.pending_files_count', '{count} pending files', { count: summary.file_count })}</span>
          <span>+{summary.added_lines}</span>
          <span>-{summary.deleted_lines}</span>
        </div>
        <div className="composer-summary__actions">
          <button
            type="button"
            className="secondary-button"
            onClick={() => actions?.acceptAllPendingEdits(contextId)}
            disabled={actionsDisabled}
          >
            {getUiText(uiText, 'conversation.composer.pending_accept_all', 'Accept All')}
          </button>
          <button
            type="button"
            className="secondary-button secondary-button--danger"
            onClick={() => actions?.rejectAllPendingEdits(contextId)}
            disabled={actionsDisabled}
          >
            {getUiText(uiText, 'conversation.composer.pending_reject_all', 'Reject All')}
          </button>
          <button type="button" className="ghost-button" onClick={() => setExpanded((current) => !current)}>
            {expanded
              ? getUiText(uiText, 'common.collapse', 'Collapse')
              : getUiText(uiText, 'common.expand', 'Expand')}
          </button>
        </div>
      </div>
      {expanded ? (
        <div className="composer-summary__files">
          {summary.files.map((file) => (
            <button
              key={file.relative_path}
              type="button"
              className="composer-summary__file"
              onClick={() => actions?.openPendingEditFile(contextId, file.relative_path)}
              disabled={actionsDisabled}
            >
              <span className="composer-summary__file-path">{file.relative_path}</span>
              <span className="composer-summary__file-stats">+{file.added_lines} / -{file.deleted_lines}</span>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  )
}

export function ConversationComposer({
  state,
  actions,
  available,
}: ConversationComposerProps) {
  const composingRef = useRef(false)
  const clearNonceRef = useRef(state.composer.clear_draft_nonce)
  const draftContextIdRef = useRef(state.context_id)
  const [draftText, setDraftText] = useState('')
  const [draftAttachments, setDraftAttachments] = useState<ConversationAttachmentState[]>([])
  const [isSelectingAttachments, setIsSelectingAttachments] = useState(false)

  const actionsReady = available && Boolean(actions)
  const uiText = state.ui_text
  const composerBusy = state.view_flags.is_busy
  const composerControlsDisabled = !actionsReady || !state.context_id || composerBusy || isSelectingAttachments

  const appendAttachments = useCallback((incoming: ConversationAttachmentState[]) => {
    setDraftAttachments((current) => mergeAttachments(current, incoming))
  }, [])

  const clearDraft = useCallback(() => {
    composingRef.current = false
    setDraftText('')
    setDraftAttachments([])
    setIsSelectingAttachments(false)
  }, [])

  useEffect(() => {
    if (state.composer.clear_draft_nonce === clearNonceRef.current) {
      return
    }
    clearNonceRef.current = state.composer.clear_draft_nonce
    clearDraft()
  }, [clearDraft, state.composer.clear_draft_nonce])

  useEffect(() => {
    if (state.context_id === draftContextIdRef.current) {
      return
    }
    draftContextIdRef.current = state.context_id
    clearDraft()
  }, [clearDraft, state.context_id])

  const serializedDraft = serializeDraft(draftText, draftAttachments)
  const hasSendPayload = Boolean(serializedDraft.trim())
  const actionMode = state.composer.action_mode
  const canSend = actionMode === 'send'
  const canStop = actionMode === 'stop'
  const primaryActionDisabled =
    !actionsReady
    || !state.context_id
    || (!canSend && !canStop)
    || (canStop && !state.active_run_id)
    || (canSend && (composerBusy || !state.conversation.can_send || !hasSendPayload))

  const removeAttachment = (key: string) => {
    setDraftAttachments((current) => current.filter((attachment) => attachmentKey(attachment) !== key))
  }

  const selectAttachments = async (kind: 'image' | 'file') => {
    if (composerControlsDisabled || !actions) {
      return
    }
    const requestedContextId = state.context_id
    setIsSelectingAttachments(true)
    try {
      const imported = await actions.selectAttachments(requestedContextId, kind)
      if (draftContextIdRef.current === requestedContextId) {
        appendAttachments(imported)
      }
    } finally {
      if (draftContextIdRef.current === requestedContextId) {
        setIsSelectingAttachments(false)
      }
    }
  }

  const runPrimaryAction = () => {
    if (primaryActionDisabled) {
      return
    }
    if (canSend) {
      actions?.sendMessage(state.context_id, serializedDraft, { attachments: draftAttachments })
      return
    }
    if (canStop) {
      actions?.requestStop(state.context_id, state.active_run_id)
    }
  }

  const handleDraftKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const nativeEvent = event.nativeEvent
    if (composingRef.current || nativeEvent.isComposing || nativeEvent.keyCode === 229) {
      return
    }
    if (event.key === 'Enter' && !event.shiftKey && canSend) {
      event.preventDefault()
      runPrimaryAction()
      return
    }
    if (event.key === 'Escape' && canStop && !primaryActionDisabled) {
      event.preventDefault()
      actions?.requestStop(state.context_id, state.active_run_id)
    }
  }

  return (
    <section className="composer-shell">
      <PendingEditSummary
        summary={state.composer.pending_workspace_edit_summary}
        actions={actions}
        uiText={uiText}
        actionsDisabled={composerControlsDisabled}
        contextId={state.context_id}
      />

      {draftAttachments.length ? (
        <div className="composer-gallery">
          {draftAttachments.map((attachment) => (
            <div key={attachmentKey(attachment)} className="composer-gallery__item">
              <div className="composer-gallery__meta">
                <span className="composer-gallery__name">
                  {attachment.name || getUiText(uiText, 'common.unnamed_attachment', 'Unnamed Attachment')}
                </span>
                <span className="composer-gallery__path">{attachment.path}</span>
              </div>
              <button
                type="button"
                className="ghost-button ghost-button--danger"
                onClick={() => removeAttachment(attachmentKey(attachment))}
                disabled={composerControlsDisabled}
              >
                {getUiText(uiText, 'common.remove', 'Remove')}
              </button>
            </div>
          ))}
        </div>
      ) : null}

      <div className="composer-body">
        <div className="composer-editor-frame">
          <textarea
            className="composer-editor"
            value={draftText}
            onChange={(event) => setDraftText(event.target.value)}
            onCompositionStart={() => {
              composingRef.current = true
            }}
            onCompositionEnd={() => {
              composingRef.current = false
            }}
            onKeyDown={handleDraftKeyDown}
            disabled={composerControlsDisabled}
            aria-label={getUiText(uiText, 'conversation.composer.input_aria_label', 'Message input')}
            aria-busy={composerBusy}
            placeholder={getUiText(uiText, 'conversation.composer.input_placeholder', 'Enter your message. Shift+Enter for newline, Enter to send.')}
          />
        </div>

        {state.composer.action_status ? (
          <div className="message-status composer-action-status" role="status" aria-live="polite">
            {state.composer.action_status}
          </div>
        ) : null}

        <div className="composer-footer">
          <div className="composer-controls">
            <button
              type="button"
              className="icon-button composer-control-button"
              onClick={() => void selectAttachments('image')}
              disabled={composerControlsDisabled}
              title={getUiText(uiText, 'btn.upload_image', 'Upload Image')}
            >
              {getUiText(uiText, 'conversation.composer.image', 'Image')}
            </button>
            <button
              type="button"
              className="icon-button composer-control-button"
              onClick={() => void selectAttachments('file')}
              disabled={composerControlsDisabled}
              title={getUiText(uiText, 'btn.select_file', 'Select File')}
            >
              {getUiText(uiText, 'conversation.composer.file', 'File')}
            </button>
            <div className={`usage-card composer-usage-pill usage-card--${usageTone(state.composer.compress_button_state)}`}>
              <span className="usage-card__tokens">
                {formatCompactTokenCount(state.composer.usage.current_tokens)} / {formatCompactTokenCount(state.composer.usage.max_tokens)}
              </span>
            </div>
            <button
              type="button"
              className="model-card composer-model-button"
              onClick={() => actions?.openSettings()}
              disabled={composerControlsDisabled}
            >
              {state.composer.model_display_name || getUiText(uiText, 'conversation.composer.model_fallback', 'Model')}
            </button>
          </div>
          <button
            type="button"
            className={`primary-button primary-button--${actionMode} composer-send-button`}
            disabled={primaryActionDisabled}
            onClick={runPrimaryAction}
          >
            {primaryActionLabel(actionMode, uiText)}
          </button>
        </div>
      </div>
    </section>
  )
}
