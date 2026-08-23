export interface ConversationUsageState {
  ratio: number
  current_tokens: number
  max_tokens: number
  input_limit: number
  output_reserve: number
  state: string
  message_count: number
}

export type ConversationActionMode =
  | 'send'
  | 'stop'
  | 'stopping'
  | 'unavailable'

export interface PendingWorkspaceEditSummaryFile {
  relative_path: string
  added_lines: number
  deleted_lines: number
}

export interface PendingWorkspaceEditSummaryState {
  file_count: number
  added_lines: number
  deleted_lines: number
  files: PendingWorkspaceEditSummaryFile[]
}

export interface ConversationToolCallState {
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  result_content: string
  status: 'running' | 'completed' | 'failed'
  details: Record<string, unknown>
}

export interface ConversationAgentStepState {
  step_index: number
  step_id: string
  content: string
  reasoning_content: string
  tool_calls: ConversationToolCallState[]
  web_search_query: string
  web_search_results: Array<Record<string, unknown>>
  web_search_message: string
  web_search_state: string
  is_complete: boolean
  is_partial: boolean
  stop_reason: string
}

export interface ConversationAttachmentState {
  type: string
  path: string
  name: string
  mime_type: string
  size: number
  placement: string
  reference_id: string
  inline_marker: string
}

export interface ConversationMessageState {
  id: string
  role: string
  content: string
  reasoning_content: string
  attachments: ConversationAttachmentState[]
  agent_steps: ConversationAgentStepState[]
  status_summary: string
  can_rollback: boolean
  is_partial: boolean
  stop_reason: string
}

export interface ConversationSessionInfoState {
  session_id: string
  name: string
  created_at: string
  updated_at: string
  message_count: number
  preview: string
  has_partial_response: boolean
}

export interface ConversationSessionMessageState {
  role: string
  content: string
  reasoning_content: string
  timestamp: string
  message_id: string
  attachments: ConversationAttachmentState[]
  is_partial: boolean
  stop_reason: string
}

export interface ConversationHistoryExportDialogState {
  is_open: boolean
  session_id: string
  export_format: string
  file_path: string
}

export interface ConversationHistoryOverlayState {
  is_open: boolean
  is_loading: boolean
  error_message: string
  current_session_id: string
  selected_session_id: string
  sessions: ConversationSessionInfoState[]
  preview_messages: ConversationSessionMessageState[]
  export_dialog: ConversationHistoryExportDialogState
}

export interface ConversationRollbackRemovedMessageState {
  message_id: string
  role: string
  timestamp: string
  content_preview: string
}

export interface ConversationRollbackFileChangeState {
  relative_path: string
  change_type: string
  summary: string
  added_lines: number
  deleted_lines: number
  diff_preview: string
  is_text: boolean
}

export interface ConversationRollbackPreviewState {
  session_id: string
  snapshot_id: string
  anchor_message_id: string
  anchor_timestamp: string
  anchor_label: string
  current_message_count: number
  target_message_count: number
  removed_message_count: number
  removed_messages: ConversationRollbackRemovedMessageState[]
  changed_files: ConversationRollbackFileChangeState[]
  changed_file_count: number
  total_added_lines: number
  total_deleted_lines: number
  operation_token: string
}

export interface ConversationRollbackOverlayState {
  is_open: boolean
  is_loading: boolean
  error_message: string
  target_message_id: string
  preview: ConversationRollbackPreviewState
}

export interface ConversationContextCompressionPreviewState {
  budget: {
    history_message_count: number
    total_tokens: number
    input_limit: number
    usage_ratio: number
  }
  summary_preview: string
  estimated: {
    summarized_count: number
    direct_count: number
    summary_tokens: number
    after_tokens: number
    after_ratio: number
  }
}

export interface ConversationContextCompressionOverlayState {
  is_open: boolean
  is_loading: boolean
  error_message: string
  keep_recent: number
  preview: ConversationContextCompressionPreviewState
}

export interface ConversationImagePreviewOverlayState {
  is_open: boolean
  file_name: string
  source_url: string
}

export interface ConversationConfirmDialogState {
  is_open: boolean
  dialog_id: string
  context_id: string
  kind: string
  title: string
  message: string
  confirm_label: string
  cancel_label: string
  tone: string
  payload: Record<string, unknown>
}

export interface ConversationNoticeDialogState {
  is_open: boolean
  title: string
  message: string
  tone: string
}

export interface RagStatusState {
  phase: 'idle' | 'unavailable' | 'indexing' | 'ready' | 'error'
  label: string
  tone: 'neutral' | 'info' | 'success' | 'error'
}

export interface RagStatsState {
  total_files: number
  processed: number
  failed: number
  excluded: number
  total_chunks: number
  total_entities: number
  total_relations: number
  storage_size_mb: number
}

export interface RagProgressState {
  is_visible: boolean
  processed: number
  total: number
  current_file: string
}

export interface RagActionsState {
  can_reindex: boolean
  can_clear: boolean
  can_search: boolean
  is_indexing: boolean
}

export interface RagFileState {
  relative_path: string
  status: string
  status_label: string
  chunks_count: number
  indexed_at: string
  tooltip: string
}

export interface RagSearchState {
  is_running: boolean
  result_text: string
}

export interface RagInfoState {
  message: string
  tone: 'neutral' | 'info' | 'success' | 'error'
}

export interface RagMainState {
  status: RagStatusState
  stats: RagStatsState
  progress: RagProgressState
  actions: RagActionsState
  files: RagFileState[]
  search: RagSearchState
  info: RagInfoState
}

export interface ConversationMainState {
  project_id: string
  context_id: string
  active_run_id: string
  ui_text: Record<string, string>
  session: {
    id: string
    name: string
  }
  conversation: {
    messages: ConversationMessageState[]
    runtime_steps: ConversationAgentStepState[]
    message_count: number
    is_loading: boolean
    can_send: boolean
  }
  composer: {
    usage: ConversationUsageState
    compress_button_state: string
    model_display_name: string
    action_mode: ConversationActionMode
    action_status: string
    pending_workspace_edit_summary: PendingWorkspaceEditSummaryState
  }
  view_flags: {
    has_messages: boolean
    has_runtime_steps: boolean
    has_pending_workspace_edits: boolean
    is_busy: boolean
    send_in_progress: boolean
    rollback_in_progress: boolean
  }
  overlays: {
    history: ConversationHistoryOverlayState
    rollback: ConversationRollbackOverlayState
    context_compression: ConversationContextCompressionOverlayState
    image_preview: ConversationImagePreviewOverlayState
    confirm: ConversationConfirmDialogState
    notice: ConversationNoticeDialogState
  }
  rag: RagMainState
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : String(value ?? fallback)
}

function asIdentity(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function asNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value ?? fallback)
  return Number.isFinite(parsed) ? parsed : fallback
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function normalizeActionMode(value: unknown): ConversationActionMode {
  switch (value) {
    case 'send':
    case 'stop':
    case 'stopping':
      return value
    default:
      return 'unavailable'
  }
}

function normalizeUiText(value: unknown): Record<string, string> {
  const incoming = asRecord(value)
  const result: Record<string, string> = {}
  Object.entries(incoming).forEach(([key, itemValue]) => {
    result[key] = asString(itemValue)
  })
  return result
}

function normalizeToolCallState(value: unknown): ConversationToolCallState {
  const toolCall = asRecord(value)
  const status = toolCall.status === 'running'
    || toolCall.status === 'completed'
    || toolCall.status === 'failed'
    ? toolCall.status
    : 'running'
  return {
    tool_call_id: asString(toolCall.tool_call_id),
    tool_name: asString(toolCall.tool_name),
    arguments: asRecord(toolCall.arguments),
    result_content: asString(toolCall.result_content),
    status,
    details: asRecord(toolCall.details),
  }
}

export function normalizeAttachmentState(value: unknown): ConversationAttachmentState {
  const attachment = asRecord(value)
  return {
    type: asString(attachment.type, 'file'),
    path: asString(attachment.path),
    name: asString(attachment.name),
    mime_type: asString(attachment.mime_type),
    size: asNumber(attachment.size),
    placement: asString(attachment.placement, 'gallery'),
    reference_id: asString(attachment.reference_id),
    inline_marker: asString(attachment.inline_marker),
  }
}

export function normalizeAttachmentList(value: unknown): ConversationAttachmentState[] {
  return Array.isArray(value) ? value.map((item) => normalizeAttachmentState(item)) : []
}

function normalizeAgentStepState(value: unknown): ConversationAgentStepState {
  const step = asRecord(value)
  return {
    step_index: Math.max(1, asNumber(step.step_index, 1)),
    step_id: asString(step.step_id),
    content: asString(step.content),
    reasoning_content: asString(step.reasoning_content),
    tool_calls: Array.isArray(step.tool_calls)
      ? step.tool_calls.map((toolCall) => normalizeToolCallState(toolCall))
      : [],
    web_search_query: asString(step.web_search_query),
    web_search_results: Array.isArray(step.web_search_results)
      ? step.web_search_results.map((result) => asRecord(result))
      : [],
    web_search_message: asString(step.web_search_message),
    web_search_state: asString(step.web_search_state, 'idle'),
    is_complete: Boolean(step.is_complete),
    is_partial: Boolean(step.is_partial),
    stop_reason: asString(step.stop_reason),
  }
}

function normalizeMessageState(value: unknown): ConversationMessageState {
  const message = asRecord(value)
  return {
    id: asString(message.id),
    role: asString(message.role, 'assistant'),
    content: asString(message.content),
    reasoning_content: asString(message.reasoning_content),
    attachments: normalizeAttachmentList(message.attachments),
    agent_steps: Array.isArray(message.agent_steps)
      ? message.agent_steps.map((step) => normalizeAgentStepState(step))
      : [],
    status_summary: asString(message.status_summary),
    can_rollback: Boolean(message.can_rollback),
    is_partial: Boolean(message.is_partial),
    stop_reason: asString(message.stop_reason),
  }
}

export function normalizePendingSummaryState(value: unknown): PendingWorkspaceEditSummaryState {
  const summary = asRecord(value)
  return {
    file_count: Math.max(0, asNumber(summary.file_count)),
    added_lines: Math.max(0, asNumber(summary.added_lines)),
    deleted_lines: Math.max(0, asNumber(summary.deleted_lines)),
    files: Array.isArray(summary.files)
      ? summary.files.map((item) => {
          const file = asRecord(item)
          return {
            relative_path: asString(file.relative_path),
            added_lines: Math.max(0, asNumber(file.added_lines)),
            deleted_lines: Math.max(0, asNumber(file.deleted_lines)),
          }
        })
      : [],
  }
}

function normalizeSessionInfoState(value: unknown): ConversationSessionInfoState {
  const session = asRecord(value)
  return {
    session_id: asString(session.session_id),
    name: asString(session.name),
    created_at: asString(session.created_at),
    updated_at: asString(session.updated_at),
    message_count: Math.max(0, asNumber(session.message_count)),
    preview: asString(session.preview),
    has_partial_response: Boolean(session.has_partial_response),
  }
}

function normalizeSessionMessageState(value: unknown): ConversationSessionMessageState {
  const message = asRecord(value)
  return {
    role: asString(message.role),
    content: asString(message.content),
    reasoning_content: asString(message.reasoning_content),
    timestamp: asString(message.timestamp),
    message_id: asString(message.message_id),
    attachments: normalizeAttachmentList(message.attachments),
    is_partial: Boolean(message.is_partial),
    stop_reason: asString(message.stop_reason),
  }
}

export function normalizeHistoryOverlayState(value: unknown): ConversationHistoryOverlayState {
  const overlay = asRecord(value)
  const exportDialog = asRecord(overlay.export_dialog)
  return {
    is_open: Boolean(overlay.is_open),
    is_loading: Boolean(overlay.is_loading),
    error_message: asString(overlay.error_message),
    current_session_id: asString(overlay.current_session_id),
    selected_session_id: asString(overlay.selected_session_id),
    sessions: Array.isArray(overlay.sessions)
      ? overlay.sessions.map((session) => normalizeSessionInfoState(session))
      : [],
    preview_messages: Array.isArray(overlay.preview_messages)
      ? overlay.preview_messages.map((message) => normalizeSessionMessageState(message))
      : [],
    export_dialog: {
      is_open: Boolean(exportDialog.is_open),
      session_id: asString(exportDialog.session_id),
      export_format: asString(exportDialog.export_format, 'md'),
      file_path: asString(exportDialog.file_path),
    },
  }
}

function normalizeRollbackRemovedMessageState(value: unknown): ConversationRollbackRemovedMessageState {
  const message = asRecord(value)
  return {
    message_id: asString(message.message_id),
    role: asString(message.role),
    timestamp: asString(message.timestamp),
    content_preview: asString(message.content_preview),
  }
}

function normalizeRollbackFileChangeState(value: unknown): ConversationRollbackFileChangeState {
  const fileChange = asRecord(value)
  return {
    relative_path: asString(fileChange.relative_path),
    change_type: asString(fileChange.change_type),
    summary: asString(fileChange.summary),
    added_lines: Math.max(0, asNumber(fileChange.added_lines)),
    deleted_lines: Math.max(0, asNumber(fileChange.deleted_lines)),
    diff_preview: asString(fileChange.diff_preview),
    is_text: Boolean(fileChange.is_text),
  }
}

function normalizeRollbackPreviewState(value: unknown): ConversationRollbackPreviewState {
  const preview = asRecord(value)
  return {
    session_id: asString(preview.session_id),
    snapshot_id: asString(preview.snapshot_id),
    anchor_message_id: asString(preview.anchor_message_id),
    anchor_timestamp: asString(preview.anchor_timestamp),
    anchor_label: asString(preview.anchor_label),
    current_message_count: Math.max(0, asNumber(preview.current_message_count)),
    target_message_count: Math.max(0, asNumber(preview.target_message_count)),
    removed_message_count: Math.max(0, asNumber(preview.removed_message_count)),
    removed_messages: Array.isArray(preview.removed_messages)
      ? preview.removed_messages.map((message) => normalizeRollbackRemovedMessageState(message))
      : [],
    changed_files: Array.isArray(preview.changed_files)
      ? preview.changed_files.map((fileChange) => normalizeRollbackFileChangeState(fileChange))
      : [],
    changed_file_count: Math.max(0, asNumber(preview.changed_file_count)),
    total_added_lines: Math.max(0, asNumber(preview.total_added_lines)),
    total_deleted_lines: Math.max(0, asNumber(preview.total_deleted_lines)),
    operation_token: asIdentity(preview.operation_token),
  }
}

export function normalizeRollbackOverlayState(value: unknown): ConversationRollbackOverlayState {
  const overlay = asRecord(value)
  return {
    is_open: Boolean(overlay.is_open),
    is_loading: Boolean(overlay.is_loading),
    error_message: asString(overlay.error_message),
    target_message_id: asString(overlay.target_message_id),
    preview: normalizeRollbackPreviewState(overlay.preview),
  }
}

export function normalizeContextCompressionOverlayState(value: unknown): ConversationContextCompressionOverlayState {
  const overlay = asRecord(value)
  const preview = asRecord(overlay.preview)
  const budget = asRecord(preview.budget)
  const estimated = asRecord(preview.estimated)
  return {
    is_open: Boolean(overlay.is_open),
    is_loading: Boolean(overlay.is_loading),
    error_message: asString(overlay.error_message),
    keep_recent: Math.max(2, Math.min(20, Math.round(asNumber(overlay.keep_recent, 3)))),
    preview: {
      budget: {
        history_message_count: Math.max(0, asNumber(budget.history_message_count)),
        total_tokens: Math.max(0, asNumber(budget.total_tokens)),
        input_limit: Math.max(0, asNumber(budget.input_limit)),
        usage_ratio: Math.max(0, Math.min(1, asNumber(budget.usage_ratio))),
      },
      summary_preview: asString(preview.summary_preview),
      estimated: {
        summarized_count: Math.max(0, asNumber(estimated.summarized_count)),
        direct_count: Math.max(0, asNumber(estimated.direct_count)),
        summary_tokens: Math.max(0, asNumber(estimated.summary_tokens)),
        after_tokens: Math.max(0, asNumber(estimated.after_tokens)),
        after_ratio: Math.max(0, Math.min(1, asNumber(estimated.after_ratio))),
      },
    },
  }
}

export function normalizeImagePreviewOverlayState(value: unknown): ConversationImagePreviewOverlayState {
  const overlay = asRecord(value)
  return {
    is_open: Boolean(overlay.is_open),
    file_name: asString(overlay.file_name),
    source_url: asString(overlay.source_url),
  }
}

function normalizeConfirmDialogState(value: unknown): ConversationConfirmDialogState {
  const dialog = asRecord(value)
  return {
    is_open: Boolean(dialog.is_open),
    dialog_id: asIdentity(dialog.dialog_id),
    context_id: asIdentity(dialog.context_id),
    kind: asString(dialog.kind),
    title: asString(dialog.title),
    message: asString(dialog.message),
    confirm_label: asString(dialog.confirm_label),
    cancel_label: asString(dialog.cancel_label),
    tone: asString(dialog.tone, 'normal'),
    payload: asRecord(dialog.payload),
  }
}

function normalizeNoticeDialogState(value: unknown): ConversationNoticeDialogState {
  const dialog = asRecord(value)
  return {
    is_open: Boolean(dialog.is_open),
    title: asString(dialog.title),
    message: asString(dialog.message),
    tone: asString(dialog.tone, 'info'),
  }
}

export const emptyConversationState: ConversationMainState = {
  project_id: '',
  context_id: '',
  active_run_id: '',
  ui_text: {},
  session: {
    id: '',
    name: '',
  },
  conversation: {
    messages: [],
    runtime_steps: [],
    message_count: 0,
    is_loading: false,
    can_send: false,
  },
  composer: {
    usage: {
      ratio: 0,
      current_tokens: 0,
      max_tokens: 0,
      input_limit: 0,
      output_reserve: 0,
      state: 'normal',
      message_count: 0,
    },
    compress_button_state: 'normal',
    model_display_name: '',
    action_mode: 'unavailable',
    action_status: '',
    pending_workspace_edit_summary: {
      file_count: 0,
      added_lines: 0,
      deleted_lines: 0,
      files: [],
    },
  },
  view_flags: {
    has_messages: false,
    has_runtime_steps: false,
    has_pending_workspace_edits: false,
    is_busy: false,
    send_in_progress: false,
    rollback_in_progress: false,
  },
  overlays: {
    history: {
      is_open: false,
      is_loading: false,
      error_message: '',
      current_session_id: '',
      selected_session_id: '',
      sessions: [],
      preview_messages: [],
      export_dialog: {
        is_open: false,
        session_id: '',
        export_format: 'md',
        file_path: '',
      },
    },
    rollback: {
      is_open: false,
      is_loading: false,
      error_message: '',
      target_message_id: '',
      preview: {
        session_id: '',
        snapshot_id: '',
        anchor_message_id: '',
        anchor_timestamp: '',
        anchor_label: '',
        current_message_count: 0,
        target_message_count: 0,
        removed_message_count: 0,
        removed_messages: [],
        changed_files: [],
        changed_file_count: 0,
        total_added_lines: 0,
        total_deleted_lines: 0,
        operation_token: '',
      },
    },
    context_compression: {
      is_open: false,
      is_loading: false,
      error_message: '',
      keep_recent: 3,
      preview: {
        budget: {
          history_message_count: 0,
          total_tokens: 0,
          input_limit: 0,
          usage_ratio: 0,
        },
        summary_preview: '',
        estimated: {
          summarized_count: 0,
          direct_count: 0,
          summary_tokens: 0,
          after_tokens: 0,
          after_ratio: 0,
        },
      },
    },
    image_preview: {
      is_open: false,
      file_name: '',
      source_url: '',
    },
    confirm: {
      is_open: false,
      dialog_id: '',
      context_id: '',
      kind: '',
      title: '',
      message: '',
      confirm_label: '',
      cancel_label: '',
      tone: 'normal',
      payload: {},
    },
    notice: {
      is_open: false,
      title: '',
      message: '',
      tone: 'info',
    },
  },
  rag: {
    status: {
      phase: 'idle',
      label: '',
      tone: 'neutral',
    },
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
    progress: {
      is_visible: false,
      processed: 0,
      total: 0,
      current_file: '',
    },
    actions: {
      can_reindex: false,
      can_clear: false,
      can_search: false,
      is_indexing: false,
    },
    files: [],
    search: {
      is_running: false,
      result_text: '',
    },
    info: {
      message: '',
      tone: 'neutral',
    },
  },
}

function normalizeRagFileState(value: unknown): RagFileState {
  const file = asRecord(value)
  return {
    relative_path: asString(file.relative_path),
    status: asString(file.status, 'pending'),
    status_label: asString(file.status_label),
    chunks_count: Math.max(0, asNumber(file.chunks_count)),
    indexed_at: asString(file.indexed_at),
    tooltip: asString(file.tooltip),
  }
}

function normalizeRagState(value: unknown, hasContext: boolean): RagMainState {
  const rag = asRecord(value)
  const status = asRecord(rag.status)
  const stats = asRecord(rag.stats)
  const progress = asRecord(rag.progress)
  const actions = asRecord(rag.actions)
  const search = asRecord(rag.search)
  const info = asRecord(rag.info)
  const rawPhase = asString(status.phase)
  const phase: RagStatusState['phase'] = (
    rawPhase === 'indexing' || rawPhase === 'ready' || rawPhase === 'error' || rawPhase === 'unavailable'
  ) ? rawPhase : 'unavailable'
  const rawStatusTone = asString(status.tone)
  const statusTone: RagStatusState['tone'] = (
    rawStatusTone === 'info' || rawStatusTone === 'success' || rawStatusTone === 'error' || rawStatusTone === 'neutral'
  ) ? rawStatusTone : 'neutral'
  const rawInfoTone = asString(info.tone)
  const infoTone: RagInfoState['tone'] = (
    rawInfoTone === 'info' || rawInfoTone === 'success' || rawInfoTone === 'error' || rawInfoTone === 'neutral'
  ) ? rawInfoTone : 'neutral'
  const isIndexing = asBoolean(actions.is_indexing)

  return {
    status: {
      phase,
      label: asString(status.label, 'Unavailable'),
      tone: statusTone,
    },
    stats: {
      total_files: Math.max(0, asNumber(stats.total_files)),
      processed: Math.max(0, asNumber(stats.processed)),
      failed: Math.max(0, asNumber(stats.failed)),
      excluded: Math.max(0, asNumber(stats.excluded)),
      total_chunks: Math.max(0, asNumber(stats.total_chunks)),
      total_entities: Math.max(0, asNumber(stats.total_entities)),
      total_relations: Math.max(0, asNumber(stats.total_relations)),
      storage_size_mb: Math.max(0, asNumber(stats.storage_size_mb)),
    },
    progress: {
      is_visible: asBoolean(progress.is_visible),
      processed: Math.max(0, asNumber(progress.processed)),
      total: Math.max(0, asNumber(progress.total)),
      current_file: asString(progress.current_file),
    },
    actions: {
      can_reindex: hasContext && asBoolean(actions.can_reindex),
      can_clear: hasContext && asBoolean(actions.can_clear),
      can_search: hasContext && asBoolean(actions.can_search),
      is_indexing: isIndexing,
    },
    files: Array.isArray(rag.files) ? rag.files.map((file) => normalizeRagFileState(file)) : [],
    search: {
      is_running: asBoolean(search.is_running),
      result_text: asString(search.result_text),
    },
    info: {
      message: asString(info.message),
      tone: infoTone,
    },
  }
}

export function normalizeConversationState(nextState: unknown): ConversationMainState {
  const incoming = asRecord(nextState)
  const contextId = asIdentity(incoming.context_id)
  const session = asRecord(incoming.session)
  const conversation = asRecord(incoming.conversation)
  const composer = asRecord(incoming.composer)
  const usage = asRecord(composer.usage)
  const viewFlags = asRecord(incoming.view_flags)

  return {
    project_id: asIdentity(incoming.project_id),
    context_id: contextId,
    active_run_id: asIdentity(incoming.active_run_id),
    ui_text: normalizeUiText(incoming.ui_text),
    session: {
      id: asString(session.id),
      name: asString(session.name),
    },
    conversation: {
      messages: Array.isArray(conversation.messages)
        ? conversation.messages.map((message) => normalizeMessageState(message))
        : [],
      runtime_steps: Array.isArray(conversation.runtime_steps)
        ? conversation.runtime_steps.map((step) => normalizeAgentStepState(step))
        : [],
      message_count: Math.max(0, asNumber(conversation.message_count)),
      is_loading: Boolean(conversation.is_loading),
      can_send: Boolean(contextId) && asBoolean(conversation.can_send),
    },
    composer: {
      usage: {
        ratio: Math.max(0, Math.min(1, asNumber(usage.ratio))),
        current_tokens: Math.max(0, asNumber(usage.current_tokens)),
        max_tokens: Math.max(0, asNumber(usage.max_tokens)),
        input_limit: Math.max(0, asNumber(usage.input_limit)),
        output_reserve: Math.max(0, asNumber(usage.output_reserve)),
        state: asString(usage.state, 'normal'),
        message_count: Math.max(0, asNumber(usage.message_count)),
      },
      compress_button_state: asString(composer.compress_button_state, 'normal'),
      model_display_name: asString(composer.model_display_name),
      action_mode: normalizeActionMode(composer.action_mode),
      action_status: asString(composer.action_status),
      pending_workspace_edit_summary: normalizePendingSummaryState(
        composer.pending_workspace_edit_summary,
      ),
    },
    view_flags: {
      has_messages: asBoolean(viewFlags.has_messages),
      has_runtime_steps: asBoolean(viewFlags.has_runtime_steps),
      has_pending_workspace_edits: asBoolean(viewFlags.has_pending_workspace_edits),
      is_busy: asBoolean(viewFlags.is_busy),
      send_in_progress: asBoolean(viewFlags.send_in_progress),
      rollback_in_progress: asBoolean(viewFlags.rollback_in_progress),
    },
    overlays: {
      history: normalizeHistoryOverlayState(incoming.overlays && asRecord(incoming.overlays).history),
      rollback: normalizeRollbackOverlayState(incoming.overlays && asRecord(incoming.overlays).rollback),
      context_compression: normalizeContextCompressionOverlayState(incoming.overlays && asRecord(incoming.overlays).context_compression),
      image_preview: normalizeImagePreviewOverlayState(incoming.overlays && asRecord(incoming.overlays).image_preview),
      confirm: normalizeConfirmDialogState(incoming.overlays && asRecord(incoming.overlays).confirm),
      notice: normalizeNoticeDialogState(incoming.overlays && asRecord(incoming.overlays).notice),
    },
    rag: normalizeRagState(incoming.rag, Boolean(contextId)),
  }
}
