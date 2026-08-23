import { api } from '../../lib/api'
import {
  normalizeAttachmentList,
  normalizeContextCompressionOverlayState,
  normalizeHistoryOverlayState,
  normalizeImagePreviewOverlayState,
  normalizePendingSummaryState,
  normalizeConversationState,
  normalizeRollbackOverlayState,
  type ConversationAttachmentState,
  type ConversationMainState,
} from './types'

export interface ConversationActions {
  activateSurface(surfaceId: 'conversation' | 'rag'): void
  sendMessage(
    contextId: string,
    text: string,
    composerState: { attachments: ConversationAttachmentState[] },
  ): void
  requestStop(contextId: string, activeRunId: string): void
  requestNewConversation(contextId: string): void
  requestHistory(): void
  closeHistory(): void
  selectHistorySession(sessionId: string): void
  openHistorySession(contextId: string, sessionId: string): void
  openHistoryExportDialog(sessionId: string): void
  closeHistoryExportDialog(): void
  setHistoryExportFormat(exportFormat: string): void
  chooseHistoryExportPath(contextId: string): void
  requestExportHistorySession(
    contextId: string,
    sessionId: string,
    exportFormat: string,
    filePath: string,
  ): void
  requestDeleteHistorySession(contextId: string, sessionId: string): void
  resolveConfirmDialog(dialogId: string, ownerContextId: string, accepted: boolean): void
  closeNoticeDialog(): void
  requestCompressContext(contextId: string): void
  closeContextCompression(contextId: string): void
  setContextCompressionKeepRecent(contextId: string, keepRecent: number): void
  confirmContextCompression(contextId: string): void
  renameSession(contextId: string, name: string): void
  requestRollback(contextId: string, messageId: string): void
  closeRollbackPreview(contextId: string): void
  confirmRollback(contextId: string, operationToken: string): void
  acceptAllPendingEdits(contextId: string): void
  rejectAllPendingEdits(contextId: string): void
  openPendingEditFile(contextId: string, filePath: string): void
  openFile(contextId: string, filePath: string): void
  openLink(contextId: string, url: string): void
  previewImage(contextId: string, imagePath: string): void
  closeImagePreview(contextId: string): void
  selectAttachments(
    contextId: string,
    kind: 'image' | 'file',
  ): Promise<ConversationAttachmentState[]>
  openSettings(): void
  requestReindexKnowledge(contextId: string): void
  requestClearKnowledge(contextId: string): void
  requestRagSearch(contextId: string, query: string): void
}

interface StateResponse {
  state: unknown
}

interface ConversationCollectionResponse {
  active: unknown
  items: unknown[]
}

interface ConversationItemResponse {
  messages: unknown[]
}

interface RunAcceptedResponse {
  context_id: string
  run_id: string
}

interface AttachmentImportResponse {
  context_id: string
  attachments: unknown[]
}

interface OverlayResponse {
  context_id: string
  overlay: unknown
}

interface RagSearchResponse {
  context_id: string
  result_text: string
}

interface PendingEditResponse {
  project_id: string
  state: unknown
}

interface ConversationActionDependencies {
  projectId: string
  onOpenSettings(): void
  onOpenWorkspaceFile(path: string): void
  getState(): ConversationMainState
  updateState(updater: (current: ConversationMainState) => ConversationMainState): void
  applyServerState(payload: unknown, expectedContextId: string, allowContextTransition?: boolean): boolean
  reportError(error: unknown): void
}

function encodeSegment(value: string): string {
  return encodeURIComponent(value)
}

function stateFromResponse(response: StateResponse): unknown {
  return response.state
}

function isCurrentContext(dependencies: ConversationActionDependencies, contextId: string): boolean {
  return Boolean(contextId) && dependencies.getState().context_id === contextId
}

function runAction(
  dependencies: ConversationActionDependencies,
  action: () => Promise<void>,
  onError?: (error: unknown) => void,
): void {
  void action().catch((error: unknown) => {
    onError?.(error)
    dependencies.reportError(error)
  })
}

function actionErrorText(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'The requested action failed.'
}

export function createConversationActions(
  dependencies: ConversationActionDependencies,
): ConversationActions {
  const projectPath = `/api/v1/projects/${encodeSegment(dependencies.projectId)}`
  const conversationsPath = `${projectPath}/conversations`
  let imagePreviewRequestId = 0
  let sendRequestInFlight = false
  let stopRequestInFlight = false
  let sessionTransitionInFlight = false
  let rollbackApplyInFlight = false

  const sessionPath = (sessionId: string) => (
    `${conversationsPath}/${encodeSegment(sessionId)}`
  )

  const currentSession = (): { contextId: string; sessionId: string } | null => {
    const state = dependencies.getState()
    if (!state.context_id || !state.session.id) {
      return null
    }
    return { contextId: state.context_id, sessionId: state.session.id }
  }

  const patchHistory = (
    updater: (history: ConversationMainState['overlays']['history']) => ConversationMainState['overlays']['history'],
  ) => {
    dependencies.updateState((current) => ({
      ...current,
      overlays: {
        ...current.overlays,
        history: updater(current.overlays.history),
      },
    }))
  }

  const closeConfirm = () => {
    dependencies.updateState((current) => ({
      ...current,
      overlays: {
        ...current.overlays,
        confirm: {
          ...current.overlays.confirm,
          is_open: false,
          dialog_id: '',
          context_id: '',
          payload: {},
        },
      },
    }))
  }

  const deleteHistorySession = async (contextId: string, sessionId: string) => {
    if (!isCurrentContext(dependencies, contextId)) {
      return
    }
    const response = await api.delete<StateResponse>(sessionPath(sessionId), {
      context_id: contextId,
    })
    dependencies.applyServerState(stateFromResponse(response), contextId, true)
  }

  const clearKnowledge = async (contextId: string) => {
    if (!isCurrentContext(dependencies, contextId)) {
      return
    }
    await api.delete<void>(`${projectPath}/rag/index`, { context_id: contextId })
    if (!isCurrentContext(dependencies, contextId)) {
      return
    }
    dependencies.updateState((current) => ({
      ...current,
      rag: {
        ...current.rag,
        status: { phase: 'ready', label: 'Ready', tone: 'success' },
        stats: {
          total_files: 0,
          processed: 0,
          failed: 0,
          excluded: 0,
          total_chunks: 0,
          total_entities: 0,
          total_relations: 0,
          storage_size_mb: 0,
        },
        progress: { is_visible: false, processed: 0, total: 0, current_file: '' },
        files: [],
        info: { message: 'Index cleared.', tone: 'success' },
      },
    }))
  }

  const openWorkspaceFile = (contextId: string, filePath: string) => {
    if (!isCurrentContext(dependencies, contextId) || !filePath) {
      return
    }
    dependencies.onOpenWorkspaceFile(filePath)
  }

  const applyPendingEditResponse = (contextId: string, response: PendingEditResponse) => {
    if (
      response.project_id !== dependencies.projectId
      || !isCurrentContext(dependencies, contextId)
    ) {
      return
    }
    const summary = normalizePendingSummaryState(response.state)
    dependencies.updateState((current) => ({
      ...current,
      composer: {
        ...current.composer,
        pending_workspace_edit_summary: summary,
      },
      view_flags: {
        ...current.view_flags,
        has_pending_workspace_edits: summary.file_count > 0,
      },
    }))
  }

  return {
    activateSurface(surfaceId) {
      dependencies.updateState((current) => ({
        ...current,
        ui: { ...current.ui, active_surface: surfaceId },
      }))
    },

    sendMessage(contextId, text, composerState) {
      const session = currentSession()
      const submittedText = text.trim()
      if (!session || session.contextId !== contextId || !submittedText || sendRequestInFlight) {
        return
      }
      sendRequestInFlight = true
      runAction(dependencies, async () => {
        try {
          const attachmentIds = composerState.attachments
            .map((attachment) => attachment.reference_id.trim())
            .filter(Boolean)
          const accepted = await api.post<RunAcceptedResponse>(
            `${sessionPath(session.sessionId)}/runs`,
            {
              context_id: contextId,
              text: submittedText,
              attachment_ids: attachmentIds,
              client_request_id: crypto.randomUUID(),
            },
          )
          if (
            accepted.context_id !== contextId
            || !accepted.run_id
            || !isCurrentContext(dependencies, contextId)
          ) {
            return
          }
          dependencies.updateState((current) => {
            const lastMessage = current.conversation.messages.at(-1)
            const messages = lastMessage?.role === 'user' && lastMessage.content === submittedText
              ? current.conversation.messages
              : [
                  ...current.conversation.messages,
                  {
                    id: `local:${accepted.run_id}`,
                    role: 'user',
                    content: submittedText,
                    reasoning_content: '',
                    attachments: composerState.attachments,
                    agent_steps: [],
                    status_summary: '',
                    can_rollback: false,
                    is_partial: false,
                    stop_reason: '',
                  },
                ]
            return {
              ...current,
              active_run_id: accepted.run_id,
              conversation: {
                ...current.conversation,
                messages,
                message_count: messages.length,
                is_loading: true,
                can_send: false,
              },
              composer: {
                ...current.composer,
                action_mode: 'stop',
                clear_draft_nonce: current.composer.clear_draft_nonce + 1,
              },
              view_flags: {
                ...current.view_flags,
                has_messages: true,
                is_busy: true,
                send_in_progress: true,
              },
            }
          })
          let snapshot: ConversationCollectionResponse
          try {
            snapshot = await api.get<ConversationCollectionResponse>(conversationsPath)
          } catch {
            return
          }
          const settledState = normalizeConversationState(snapshot.active)
          if (
            settledState.project_id === dependencies.projectId
            && settledState.context_id === contextId
            && settledState.session.id === session.sessionId
            && !settledState.active_run_id
          ) {
            dependencies.applyServerState(snapshot.active, contextId)
          }
        } finally {
          sendRequestInFlight = false
        }
      })
    },

    requestStop(contextId, activeRunId) {
      const session = currentSession()
      if (
        !session
        || session.contextId !== contextId
        || dependencies.getState().active_run_id !== activeRunId
        || stopRequestInFlight
      ) {
        return
      }
      stopRequestInFlight = true
      runAction(dependencies, async () => {
        try {
          await api.post<void>(
            `${sessionPath(session.sessionId)}/runs/${encodeSegment(activeRunId)}/cancel`,
            { context_id: contextId },
          )
          if (
            !isCurrentContext(dependencies, contextId)
            || dependencies.getState().active_run_id !== activeRunId
          ) {
            return
          }
          dependencies.updateState((current) => ({
            ...current,
            composer: { ...current.composer, action_mode: 'stopping' },
          }))
        } finally {
          stopRequestInFlight = false
        }
      })
    },

    requestNewConversation(contextId) {
      if (!isCurrentContext(dependencies, contextId) || sessionTransitionInFlight) {
        return
      }
      sessionTransitionInFlight = true
      runAction(dependencies, async () => {
        try {
          const response = await api.post<StateResponse>(conversationsPath, {
            context_id: contextId,
          })
          dependencies.applyServerState(stateFromResponse(response), contextId, true)
        } finally {
          sessionTransitionInFlight = false
        }
      })
    },

    requestHistory() {
      const owner = currentSession()
      if (!owner) {
        return
      }
      patchHistory((history) => ({ ...history, is_open: true, is_loading: true, error_message: '' }))
      runAction(dependencies, async () => {
        const response = await api.get<ConversationCollectionResponse>(conversationsPath)
        if (!isCurrentContext(dependencies, owner.contextId)) {
          return
        }
        const current = dependencies.getState()
        if (!current.overlays.history.is_open) {
          return
        }
        const history = normalizeHistoryOverlayState({
          ...current.overlays.history,
          is_open: true,
          is_loading: false,
          current_session_id: current.session.id,
          selected_session_id: current.overlays.history.selected_session_id || current.session.id,
          sessions: response.items,
        })
        dependencies.updateState((state) => ({
          ...state,
          overlays: { ...state.overlays, history },
        }))
      }, (error) => {
        patchHistory((history) => ({
          ...history,
          is_loading: false,
          error_message: actionErrorText(error),
        }))
      })
    },

    closeHistory() {
      patchHistory((history) => ({
        ...history,
        is_open: false,
        is_loading: false,
        export_dialog: { ...history.export_dialog, is_open: false },
      }))
    },

    selectHistorySession(sessionId) {
      const owner = currentSession()
      if (!owner || !sessionId) {
        return
      }
      patchHistory((history) => ({
        ...history,
        selected_session_id: sessionId,
        is_loading: true,
        error_message: '',
      }))
      runAction(dependencies, async () => {
        const response = await api.get<ConversationItemResponse>(sessionPath(sessionId))
        if (
          !isCurrentContext(dependencies, owner.contextId)
          || dependencies.getState().overlays.history.selected_session_id !== sessionId
        ) {
          return
        }
        patchHistory((history) => normalizeHistoryOverlayState({
          ...history,
          selected_session_id: sessionId,
          is_loading: false,
          preview_messages: response.messages,
        }))
      }, (error) => {
        patchHistory((history) => ({
          ...history,
          ...(history.selected_session_id === sessionId
            ? { is_loading: false, error_message: actionErrorText(error) }
            : {}),
        }))
      })
    },

    openHistorySession(contextId, sessionId) {
      if (
        !isCurrentContext(dependencies, contextId)
        || !sessionId
        || sessionTransitionInFlight
      ) {
        return
      }
      sessionTransitionInFlight = true
      runAction(dependencies, async () => {
        try {
          const response = await api.post<StateResponse>(`${sessionPath(sessionId)}/activate`, {
            context_id: contextId,
          })
          dependencies.applyServerState(stateFromResponse(response), contextId, true)
        } finally {
          sessionTransitionInFlight = false
        }
      })
    },

    openHistoryExportDialog(sessionId) {
      patchHistory((history) => ({
        ...history,
        export_dialog: {
          ...history.export_dialog,
          is_open: true,
          session_id: sessionId,
          file_path: '',
        },
      }))
    },

    closeHistoryExportDialog() {
      patchHistory((history) => ({
        ...history,
        export_dialog: { ...history.export_dialog, is_open: false },
      }))
    },

    setHistoryExportFormat(exportFormat) {
      if (exportFormat !== 'md' && exportFormat !== 'json' && exportFormat !== 'txt') {
        return
      }
      patchHistory((history) => ({
        ...history,
        export_dialog: { ...history.export_dialog, export_format: exportFormat },
      }))
    },

    chooseHistoryExportPath(contextId) {
      if (!isCurrentContext(dependencies, contextId)) {
        return
      }
      const history = dependencies.getState().overlays.history
      const requestedSessionId = history.export_dialog.session_id
      const requestedFormat = history.export_dialog.export_format
      const format = requestedFormat === 'json' || requestedFormat === 'txt'
        ? requestedFormat
        : 'md'
      runAction(dependencies, async () => {
        const selectedPath = await window.circuitDesktop.saveFile({
          title: 'Export conversation',
          defaultPath: `conversation.${format}`,
          filters: [{
            name: format === 'json' ? 'JSON' : format === 'txt' ? 'Text' : 'Markdown',
            extensions: [format],
          }],
        })
        if (!selectedPath || !isCurrentContext(dependencies, contextId)) {
          return
        }
        patchHistory((current) => ({
          ...current,
          export_dialog: current.export_dialog.session_id === requestedSessionId
            ? { ...current.export_dialog, file_path: selectedPath }
            : current.export_dialog,
        }))
      })
    },

    requestExportHistorySession(contextId, sessionId, exportFormat, filePath) {
      if (!isCurrentContext(dependencies, contextId) || !sessionId || !filePath) {
        return
      }
      runAction(dependencies, async () => {
        await api.post<void>(`${sessionPath(sessionId)}/exports`, {
          context_id: contextId,
          format: exportFormat,
          path: filePath,
        })
        if (isCurrentContext(dependencies, contextId)) {
          patchHistory((history) => ({
            ...history,
            export_dialog: { ...history.export_dialog, is_open: false },
          }))
        }
      })
    },

    requestDeleteHistorySession(contextId, sessionId) {
      if (!isCurrentContext(dependencies, contextId) || !sessionId) {
        return
      }
      dependencies.updateState((current) => ({
        ...current,
        overlays: {
          ...current.overlays,
          confirm: {
            is_open: true,
            dialog_id: crypto.randomUUID(),
            context_id: contextId,
            kind: 'delete-conversation',
            title: 'Delete conversation',
            message: 'This conversation will be permanently deleted.',
            confirm_label: 'Delete',
            cancel_label: 'Cancel',
            tone: 'danger',
            payload: { session_id: sessionId },
          },
        },
      }))
    },

    resolveConfirmDialog(dialogId, ownerContextId, accepted) {
      const confirm = dependencies.getState().overlays.confirm
      if (
        !confirm.is_open
        || confirm.dialog_id !== dialogId
        || confirm.context_id !== ownerContextId
        || !isCurrentContext(dependencies, ownerContextId)
      ) {
        return
      }
      closeConfirm()
      if (confirm.kind === 'delete-conversation') {
        if (accepted) {
          const sessionId = String(confirm.payload.session_id ?? '')
          runAction(dependencies, () => deleteHistorySession(ownerContextId, sessionId))
        }
        return
      }
      if (confirm.kind === 'clear-rag-index') {
        if (accepted) {
          runAction(dependencies, () => clearKnowledge(ownerContextId))
        }
      }
    },

    closeNoticeDialog() {
      dependencies.updateState((current) => ({
        ...current,
        overlays: {
          ...current.overlays,
          notice: { ...current.overlays.notice, is_open: false },
        },
      }))
    },

    requestCompressContext(contextId) {
      const session = currentSession()
      if (!session || session.contextId !== contextId) {
        return
      }
      runAction(dependencies, async () => {
        const response = await api.post<OverlayResponse>(
          `${sessionPath(session.sessionId)}/compression-preview`,
          { context_id: contextId, keep_recent: 3 },
        )
        if (response.context_id !== contextId || !isCurrentContext(dependencies, contextId)) {
          return
        }
        const overlay = normalizeContextCompressionOverlayState(response.overlay)
        dependencies.updateState((current) => ({
          ...current,
          overlays: { ...current.overlays, context_compression: overlay },
        }))
      }, (error) => {
        if (!isCurrentContext(dependencies, contextId)) {
          return
        }
        dependencies.updateState((current) => ({
          ...current,
          overlays: {
            ...current.overlays,
            context_compression: {
              ...current.overlays.context_compression,
              is_loading: false,
              error_message: actionErrorText(error),
            },
          },
        }))
      })
    },

    closeContextCompression(contextId) {
      if (!isCurrentContext(dependencies, contextId)) {
        return
      }
      dependencies.updateState((current) => ({
        ...current,
        overlays: {
          ...current.overlays,
          context_compression: { ...current.overlays.context_compression, is_open: false },
        },
      }))
    },

    setContextCompressionKeepRecent(contextId, keepRecent) {
      const session = currentSession()
      if (!session || session.contextId !== contextId) {
        return
      }
      const normalizedKeepRecent = Math.max(2, Math.min(20, Math.round(keepRecent)))
      dependencies.updateState((current) => ({
        ...current,
        overlays: {
          ...current.overlays,
          context_compression: {
            ...current.overlays.context_compression,
            keep_recent: normalizedKeepRecent,
            is_loading: true,
          },
        },
      }))
      runAction(dependencies, async () => {
        const response = await api.post<OverlayResponse>(
          `${sessionPath(session.sessionId)}/compression-preview`,
          { context_id: contextId, keep_recent: normalizedKeepRecent },
        )
        if (
          response.context_id !== contextId
          || !isCurrentContext(dependencies, contextId)
          || !dependencies.getState().overlays.context_compression.is_open
          || dependencies.getState().overlays.context_compression.keep_recent !== normalizedKeepRecent
        ) {
          return
        }
        const overlay = normalizeContextCompressionOverlayState(response.overlay)
        dependencies.updateState((current) => ({
          ...current,
          overlays: { ...current.overlays, context_compression: overlay },
        }))
      }, (error) => {
        if (!isCurrentContext(dependencies, contextId)) {
          return
        }
        dependencies.updateState((current) => ({
          ...current,
          overlays: {
            ...current.overlays,
            context_compression: {
              ...current.overlays.context_compression,
              is_loading: false,
              error_message: actionErrorText(error),
            },
          },
        }))
      })
    },

    confirmContextCompression(contextId) {
      const session = currentSession()
      if (!session || session.contextId !== contextId) {
        return
      }
      const keepRecent = dependencies.getState().overlays.context_compression.keep_recent
      dependencies.updateState((current) => ({
        ...current,
        overlays: {
          ...current.overlays,
          context_compression: {
            ...current.overlays.context_compression,
            is_loading: true,
            error_message: '',
          },
        },
      }))
      runAction(dependencies, async () => {
        await api.post<void>(`${sessionPath(session.sessionId)}/compressions`, {
          context_id: contextId,
          keep_recent: keepRecent,
        })
        const response = await api.get<ConversationCollectionResponse>(conversationsPath)
        dependencies.applyServerState(response.active, contextId)
      }, (error) => {
        if (!isCurrentContext(dependencies, contextId)) {
          return
        }
        dependencies.updateState((current) => ({
          ...current,
          overlays: {
            ...current.overlays,
            context_compression: {
              ...current.overlays.context_compression,
              is_loading: false,
              error_message: actionErrorText(error),
            },
          },
        }))
      })
    },

    renameSession(contextId, name) {
      const session = currentSession()
      if (!session || session.contextId !== contextId || !name.trim()) {
        return
      }
      runAction(dependencies, async () => {
        const response = await api.put<StateResponse>(sessionPath(session.sessionId), {
          context_id: contextId,
          name: name.trim(),
        })
        dependencies.applyServerState(stateFromResponse(response), contextId)
      })
    },

    requestRollback(contextId, messageId) {
      const session = currentSession()
      if (!session || session.contextId !== contextId || !messageId) {
        return
      }
      runAction(dependencies, async () => {
        const response = await api.post<OverlayResponse>(
          `${sessionPath(session.sessionId)}/rollback-preview`,
          { context_id: contextId, message_id: messageId },
        )
        if (response.context_id !== contextId || !isCurrentContext(dependencies, contextId)) {
          return
        }
        const overlay = normalizeRollbackOverlayState(response.overlay)
        dependencies.updateState((current) => ({
          ...current,
          overlays: { ...current.overlays, rollback: overlay },
        }))
      })
    },

    closeRollbackPreview(contextId) {
      if (!isCurrentContext(dependencies, contextId)) {
        return
      }
      dependencies.updateState((current) => ({
        ...current,
        overlays: {
          ...current.overlays,
          rollback: { ...current.overlays.rollback, is_open: false },
        },
      }))
    },

    confirmRollback(contextId, operationToken) {
      const session = currentSession()
      const preview = dependencies.getState().overlays.rollback.preview
      if (
        !session
        || session.contextId !== contextId
        || !operationToken
        || preview.operation_token !== operationToken
        || rollbackApplyInFlight
      ) {
        return
      }
      rollbackApplyInFlight = true
      dependencies.updateState((current) => ({
        ...current,
        overlays: {
          ...current.overlays,
          rollback: { ...current.overlays.rollback, is_loading: true, error_message: '' },
        },
        view_flags: { ...current.view_flags, rollback_in_progress: true },
      }))
      runAction(dependencies, async () => {
        try {
          const response = await api.post<StateResponse>(`${sessionPath(session.sessionId)}/rollbacks`, {
            context_id: contextId,
            operation_token: operationToken,
          })
          dependencies.applyServerState(stateFromResponse(response), contextId, true)
        } finally {
          rollbackApplyInFlight = false
        }
      }, (error) => {
        if (!isCurrentContext(dependencies, contextId)) {
          return
        }
        dependencies.updateState((current) => ({
          ...current,
          overlays: {
            ...current.overlays,
            rollback: {
              ...current.overlays.rollback,
              is_loading: false,
              error_message: actionErrorText(error),
            },
          },
          view_flags: { ...current.view_flags, rollback_in_progress: false },
        }))
      })
    },

    acceptAllPendingEdits(contextId) {
      if (!isCurrentContext(dependencies, contextId)) {
        return
      }
      runAction(dependencies, async () => {
        const response = await api.post<PendingEditResponse>(`${projectPath}/pending-edits/accept`, {})
        applyPendingEditResponse(contextId, response)
      })
    },

    rejectAllPendingEdits(contextId) {
      if (!isCurrentContext(dependencies, contextId)) {
        return
      }
      runAction(dependencies, async () => {
        const response = await api.post<PendingEditResponse>(`${projectPath}/pending-edits/reject`, {})
        applyPendingEditResponse(contextId, response)
      })
    },

    openPendingEditFile(contextId, filePath) {
      openWorkspaceFile(contextId, filePath)
    },

    openFile(contextId, filePath) {
      openWorkspaceFile(contextId, filePath)
    },

    openLink(contextId, url) {
      if (!isCurrentContext(dependencies, contextId)) {
        return
      }
      let parsed: URL
      try {
        parsed = new URL(url)
      } catch {
        return
      }
      if (!['http:', 'https:', 'mailto:'].includes(parsed.protocol)) {
        return
      }
      runAction(dependencies, async () => {
        await window.circuitDesktop.openExternal(parsed.toString())
      })
    },

    previewImage(contextId, imagePath) {
      if (!isCurrentContext(dependencies, contextId) || !imagePath) {
        return
      }
      imagePreviewRequestId += 1
      const requestId = imagePreviewRequestId
      runAction(dependencies, async () => {
        const response = await api.post<OverlayResponse>(`${projectPath}/attachments/preview`, {
          context_id: contextId,
          path: imagePath,
        })
        if (
          requestId !== imagePreviewRequestId
          || response.context_id !== contextId
          || !isCurrentContext(dependencies, contextId)
        ) {
          return
        }
        const overlay = normalizeImagePreviewOverlayState(response.overlay)
        dependencies.updateState((current) => ({
          ...current,
          overlays: { ...current.overlays, image_preview: overlay },
        }))
      })
    },

    closeImagePreview(contextId) {
      if (!isCurrentContext(dependencies, contextId)) {
        return
      }
      imagePreviewRequestId += 1
      dependencies.updateState((current) => ({
        ...current,
        overlays: {
          ...current.overlays,
          image_preview: { ...current.overlays.image_preview, is_open: false },
        },
      }))
    },

    async selectAttachments(contextId, kind) {
      if (!isCurrentContext(dependencies, contextId)) {
        return []
      }
      try {
        const paths = await window.circuitDesktop.selectFiles({
          title: kind === 'image' ? 'Select images' : 'Select files',
          multiple: true,
          ...(kind === 'image' ? {
            filters: [{
              name: 'Images',
              extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'],
            }],
          } : {}),
        })
        if (!paths.length || !isCurrentContext(dependencies, contextId)) {
          return []
        }
        const response = await api.post<AttachmentImportResponse>(
          `${projectPath}/attachments/import`,
          { context_id: contextId, paths, kind },
        )
        if (response.context_id !== contextId || !isCurrentContext(dependencies, contextId)) {
          return []
        }
        return normalizeAttachmentList(response.attachments)
      } catch (error) {
        dependencies.reportError(error)
        return []
      }
    },

    openSettings() {
      dependencies.onOpenSettings()
    },

    requestReindexKnowledge(contextId) {
      if (!isCurrentContext(dependencies, contextId)) {
        return
      }
      dependencies.updateState((current) => ({
        ...current,
        rag: {
          ...current.rag,
          status: { phase: 'indexing', label: 'Indexing', tone: 'info' },
          progress: { is_visible: true, processed: 0, total: 0, current_file: '' },
          actions: {
            ...current.rag.actions,
            can_reindex: false,
            can_clear: false,
            can_search: false,
            is_indexing: true,
          },
          info: { message: 'Indexing started.', tone: 'info' },
        },
      }))
      runAction(dependencies, async () => {
        await api.post<void>(`${projectPath}/rag/indexes`, { context_id: contextId })
      }, (error) => {
        if (!isCurrentContext(dependencies, contextId)) {
          return
        }
        dependencies.updateState((current) => ({
          ...current,
          rag: {
            ...current.rag,
            status: { phase: 'error', label: 'Index failed', tone: 'error' },
            progress: { ...current.rag.progress, is_visible: false },
            actions: {
              ...current.rag.actions,
              can_reindex: true,
              can_clear: true,
              can_search: true,
              is_indexing: false,
            },
            info: { message: actionErrorText(error), tone: 'error' },
          },
        }))
      })
    },

    requestClearKnowledge(contextId) {
      if (!isCurrentContext(dependencies, contextId)) {
        return
      }
      dependencies.updateState((current) => ({
        ...current,
        overlays: {
          ...current.overlays,
          confirm: {
            is_open: true,
            dialog_id: crypto.randomUUID(),
            context_id: contextId,
            kind: 'clear-rag-index',
            title: 'Clear index library',
            message: 'All indexed project knowledge will be removed.',
            confirm_label: 'Clear',
            cancel_label: 'Cancel',
            tone: 'danger',
            payload: {},
          },
        },
      }))
    },

    requestRagSearch(contextId, query) {
      if (!isCurrentContext(dependencies, contextId) || !query.trim()) {
        return
      }
      dependencies.updateState((current) => ({
        ...current,
        rag: {
          ...current.rag,
          search: { ...current.rag.search, is_running: true, result_text: '' },
        },
      }))
      runAction(dependencies, async () => {
        const response = await api.post<RagSearchResponse>(`${projectPath}/rag/searches`, {
          context_id: contextId,
          query: query.trim(),
        })
        if (response.context_id !== contextId || !isCurrentContext(dependencies, contextId)) {
          return
        }
        dependencies.updateState((current) => ({
          ...current,
          rag: {
            ...current.rag,
            search: {
              ...current.rag.search,
              is_running: false,
              result_text: String(response.result_text ?? ''),
            },
          },
        }))
      }, (error) => {
        if (!isCurrentContext(dependencies, contextId)) {
          return
        }
        dependencies.updateState((current) => ({
          ...current,
          rag: {
            ...current.rag,
            search: {
              ...current.rag.search,
              is_running: false,
              result_text: actionErrorText(error),
            },
          },
        }))
      })
    },
  }
}
