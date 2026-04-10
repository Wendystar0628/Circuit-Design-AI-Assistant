export interface SelectOption {
  value: string
  label: string
}

export interface ModelConfigTabState {
  id: string
  label: string
}

export interface ModelConfigDialogState {
  title: string
  activeTab: 'chat' | 'embedding'
  tabs: ModelConfigTabState[]
  actions: {
    test: string
    save: string
    cancel: string
  }
  status: {
    state: 'not_verified' | 'testing' | 'verified' | 'failed'
    text: string
  }
  messages: {
    bridgeUnavailable: string
  }
}

export interface ChatConfigState {
  provider: string
  providerOptions: SelectOption[]
  model: string
  modelOptions: SelectOption[]
  apiKey: string
  baseUrl: string
  baseUrlPlaceholder: string
  timeout: number
  streaming: boolean
  enableThinking: boolean
  thinkingTimeout: number
  supportsThinking: boolean
  labels: {
    provider: string
    model: string
    apiKey: string
    baseUrl: string
    timeout: string
    streaming: string
    enableThinking: string
    thinkingTimeout: string
    featuresTitle: string
    enabled: string
    disabled: string
    notSupported: string
  }
}

export interface EmbeddingConfigState {
  provider: string
  providerOptions: SelectOption[]
  model: string
  modelOptions: SelectOption[]
  apiKey: string
  baseUrl: string
  baseUrlPlaceholder: string
  timeout: number
  batchSize: number
  requiresApiKey: boolean
  labels: {
    provider: string
    model: string
    apiKey: string
    baseUrl: string
    timeout: string
    batchSize: string
  }
}

export interface ConfirmDialogState {
  open: boolean
  title: string
  message: string
  action: string
  confirmText: string
  cancelText: string
}

export interface NoticeDialogState {
  open: boolean
  title: string
  message: string
  level: 'info' | 'warning' | 'error' | 'success'
  closeText: string
}

export interface ModelConfigState {
  dialog: ModelConfigDialogState
  chat: ChatConfigState
  embedding: EmbeddingConfigState
  confirmDialog: ConfirmDialogState
  noticeDialog: NoticeDialogState
}

const defaultOptions: SelectOption[] = []

export const emptyModelConfigState: ModelConfigState = {
  dialog: {
    title: 'Model Configuration',
    activeTab: 'chat',
    tabs: [
      { id: 'chat', label: 'Chat Model' },
      { id: 'embedding', label: 'Embedding Model' },
    ],
    actions: {
      test: 'Test Connection',
      save: 'Save',
      cancel: 'Cancel',
    },
    status: {
      state: 'not_verified',
      text: 'Not verified',
    },
    messages: {
      bridgeUnavailable: 'Qt bridge unavailable',
    },
  },
  chat: {
    provider: '',
    providerOptions: defaultOptions,
    model: '',
    modelOptions: defaultOptions,
    apiKey: '',
    baseUrl: '',
    baseUrlPlaceholder: '',
    timeout: 60,
    streaming: true,
    enableThinking: false,
    thinkingTimeout: 300,
    supportsThinking: false,
    labels: {
      provider: 'Provider',
      model: 'Model',
      apiKey: 'API Key',
      baseUrl: 'Base URL',
      timeout: 'Timeout',
      streaming: 'Streaming',
      enableThinking: 'Deep Thinking',
      thinkingTimeout: 'Thinking Timeout',
      featuresTitle: 'Provider Features',
      enabled: 'Enabled',
      disabled: 'Disabled',
      notSupported: 'Not supported',
    },
  },
  embedding: {
    provider: '',
    providerOptions: defaultOptions,
    model: '',
    modelOptions: defaultOptions,
    apiKey: '',
    baseUrl: '',
    baseUrlPlaceholder: '',
    timeout: 60,
    batchSize: 8,
    requiresApiKey: false,
    labels: {
      provider: 'Provider',
      model: 'Model',
      apiKey: 'API Key',
      baseUrl: 'Base URL',
      timeout: 'Timeout',
      batchSize: 'Batch Size',
    },
  },
  confirmDialog: {
    open: false,
    title: '',
    message: '',
    action: '',
    confirmText: 'Save',
    cancelText: 'Cancel',
  },
  noticeDialog: {
    open: false,
    title: '',
    message: '',
    level: 'info',
    closeText: 'OK',
  },
}

function normalizeOptionList(value: unknown): SelectOption[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => {
      if (!item || typeof item !== 'object') {
        return null
      }
      const option = item as Record<string, unknown>
      return {
        value: String(option.value ?? ''),
        label: String(option.label ?? option.value ?? ''),
      }
    })
    .filter((item): item is SelectOption => Boolean(item && item.value))
}

export function normalizeModelConfigState(value: unknown): ModelConfigState {
  if (!value || typeof value !== 'object') {
    return emptyModelConfigState
  }

  const payload = value as Record<string, unknown>
  const dialog = (payload.dialog as Record<string, unknown> | undefined) ?? {}
  const chat = (payload.chat as Record<string, unknown> | undefined) ?? {}
  const embedding = (payload.embedding as Record<string, unknown> | undefined) ?? {}
  const confirmDialog = (payload.confirmDialog as Record<string, unknown> | undefined) ?? {}
  const noticeDialog = (payload.noticeDialog as Record<string, unknown> | undefined) ?? {}
  const normalizedDialogState = String(dialog.status && typeof dialog.status === 'object' ? (dialog.status as Record<string, unknown>).state ?? 'not_verified' : 'not_verified')

  return {
    dialog: {
      title: String(dialog.title ?? emptyModelConfigState.dialog.title),
      activeTab: dialog.activeTab === 'embedding' ? 'embedding' : 'chat',
      tabs: Array.isArray(dialog.tabs)
        ? dialog.tabs
            .map((item) => {
              if (!item || typeof item !== 'object') {
                return null
              }
              const tab = item as Record<string, unknown>
              const id = tab.id === 'embedding' ? 'embedding' : tab.id === 'chat' ? 'chat' : ''
              if (!id) {
                return null
              }
              return {
                id,
                label: String(tab.label ?? id),
              }
            })
            .filter((item): item is ModelConfigTabState => Boolean(item))
        : emptyModelConfigState.dialog.tabs,
      actions: {
        test: String((dialog.actions as Record<string, unknown> | undefined)?.test ?? emptyModelConfigState.dialog.actions.test),
        save: String((dialog.actions as Record<string, unknown> | undefined)?.save ?? emptyModelConfigState.dialog.actions.save),
        cancel: String((dialog.actions as Record<string, unknown> | undefined)?.cancel ?? emptyModelConfigState.dialog.actions.cancel),
      },
      status: {
        state: normalizedDialogState === 'testing' || normalizedDialogState === 'verified' || normalizedDialogState === 'failed' ? normalizedDialogState : 'not_verified',
        text: String((dialog.status as Record<string, unknown> | undefined)?.text ?? emptyModelConfigState.dialog.status.text),
      },
      messages: {
        bridgeUnavailable: String((dialog.messages as Record<string, unknown> | undefined)?.bridgeUnavailable ?? emptyModelConfigState.dialog.messages.bridgeUnavailable),
      },
    },
    chat: {
      provider: String(chat.provider ?? ''),
      providerOptions: normalizeOptionList(chat.providerOptions),
      model: String(chat.model ?? ''),
      modelOptions: normalizeOptionList(chat.modelOptions),
      apiKey: String(chat.apiKey ?? ''),
      baseUrl: String(chat.baseUrl ?? ''),
      baseUrlPlaceholder: String(chat.baseUrlPlaceholder ?? ''),
      timeout: Number(chat.timeout ?? emptyModelConfigState.chat.timeout) || emptyModelConfigState.chat.timeout,
      streaming: Boolean(chat.streaming),
      enableThinking: Boolean(chat.enableThinking),
      thinkingTimeout: Number(chat.thinkingTimeout ?? emptyModelConfigState.chat.thinkingTimeout) || emptyModelConfigState.chat.thinkingTimeout,
      supportsThinking: Boolean(chat.supportsThinking),
      labels: {
        provider: String((chat.labels as Record<string, unknown> | undefined)?.provider ?? emptyModelConfigState.chat.labels.provider),
        model: String((chat.labels as Record<string, unknown> | undefined)?.model ?? emptyModelConfigState.chat.labels.model),
        apiKey: String((chat.labels as Record<string, unknown> | undefined)?.apiKey ?? emptyModelConfigState.chat.labels.apiKey),
        baseUrl: String((chat.labels as Record<string, unknown> | undefined)?.baseUrl ?? emptyModelConfigState.chat.labels.baseUrl),
        timeout: String((chat.labels as Record<string, unknown> | undefined)?.timeout ?? emptyModelConfigState.chat.labels.timeout),
        streaming: String((chat.labels as Record<string, unknown> | undefined)?.streaming ?? emptyModelConfigState.chat.labels.streaming),
        enableThinking: String((chat.labels as Record<string, unknown> | undefined)?.enableThinking ?? emptyModelConfigState.chat.labels.enableThinking),
        thinkingTimeout: String((chat.labels as Record<string, unknown> | undefined)?.thinkingTimeout ?? emptyModelConfigState.chat.labels.thinkingTimeout),
        featuresTitle: String((chat.labels as Record<string, unknown> | undefined)?.featuresTitle ?? emptyModelConfigState.chat.labels.featuresTitle),
        enabled: String((chat.labels as Record<string, unknown> | undefined)?.enabled ?? emptyModelConfigState.chat.labels.enabled),
        disabled: String((chat.labels as Record<string, unknown> | undefined)?.disabled ?? emptyModelConfigState.chat.labels.disabled),
        notSupported: String((chat.labels as Record<string, unknown> | undefined)?.notSupported ?? emptyModelConfigState.chat.labels.notSupported),
      },
    },
    embedding: {
      provider: String(embedding.provider ?? ''),
      providerOptions: normalizeOptionList(embedding.providerOptions),
      model: String(embedding.model ?? ''),
      modelOptions: normalizeOptionList(embedding.modelOptions),
      apiKey: String(embedding.apiKey ?? ''),
      baseUrl: String(embedding.baseUrl ?? ''),
      baseUrlPlaceholder: String(embedding.baseUrlPlaceholder ?? ''),
      timeout: Number(embedding.timeout ?? emptyModelConfigState.embedding.timeout) || emptyModelConfigState.embedding.timeout,
      batchSize: Number(embedding.batchSize ?? emptyModelConfigState.embedding.batchSize) || emptyModelConfigState.embedding.batchSize,
      requiresApiKey: Boolean(embedding.requiresApiKey),
      labels: {
        provider: String((embedding.labels as Record<string, unknown> | undefined)?.provider ?? emptyModelConfigState.embedding.labels.provider),
        model: String((embedding.labels as Record<string, unknown> | undefined)?.model ?? emptyModelConfigState.embedding.labels.model),
        apiKey: String((embedding.labels as Record<string, unknown> | undefined)?.apiKey ?? emptyModelConfigState.embedding.labels.apiKey),
        baseUrl: String((embedding.labels as Record<string, unknown> | undefined)?.baseUrl ?? emptyModelConfigState.embedding.labels.baseUrl),
        timeout: String((embedding.labels as Record<string, unknown> | undefined)?.timeout ?? emptyModelConfigState.embedding.labels.timeout),
        batchSize: String((embedding.labels as Record<string, unknown> | undefined)?.batchSize ?? emptyModelConfigState.embedding.labels.batchSize),
      },
    },
    confirmDialog: {
      open: Boolean(confirmDialog.open),
      title: String(confirmDialog.title ?? ''),
      message: String(confirmDialog.message ?? ''),
      action: String(confirmDialog.action ?? ''),
      confirmText: String(confirmDialog.confirmText ?? emptyModelConfigState.confirmDialog.confirmText),
      cancelText: String(confirmDialog.cancelText ?? emptyModelConfigState.confirmDialog.cancelText),
    },
    noticeDialog: {
      open: Boolean(noticeDialog.open),
      title: String(noticeDialog.title ?? ''),
      message: String(noticeDialog.message ?? ''),
      level:
        noticeDialog.level === 'warning' ||
        noticeDialog.level === 'error' ||
        noticeDialog.level === 'success'
          ? noticeDialog.level
          : 'info',
      closeText: String(noticeDialog.closeText ?? emptyModelConfigState.noticeDialog.closeText),
    },
  }
}
