export interface SelectOption {
  value: string
  label: string
}

export interface ModelConfigTabState {
  id: string
  label: string
}

export interface ModelConfigSurfaceState {
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

export interface ModelConfigState {
  surface: ModelConfigSurfaceState
  chat: ChatConfigState
  embedding: EmbeddingConfigState
}

const defaultOptions: SelectOption[] = []

export const emptyModelConfigState: ModelConfigState = {
  surface: {
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
  const surface = (payload.surface as Record<string, unknown> | undefined) ?? {}
  const chat = (payload.chat as Record<string, unknown> | undefined) ?? {}
  const embedding = (payload.embedding as Record<string, unknown> | undefined) ?? {}
  const normalizedSurfaceState = String(surface.status && typeof surface.status === 'object' ? (surface.status as Record<string, unknown>).state ?? 'not_verified' : 'not_verified')

  return {
    surface: {
      title: String(surface.title ?? emptyModelConfigState.surface.title),
      activeTab: surface.activeTab === 'embedding' ? 'embedding' : 'chat',
      tabs: Array.isArray(surface.tabs)
        ? surface.tabs
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
        : emptyModelConfigState.surface.tabs,
      actions: {
        test: String((surface.actions as Record<string, unknown> | undefined)?.test ?? emptyModelConfigState.surface.actions.test),
        save: String((surface.actions as Record<string, unknown> | undefined)?.save ?? emptyModelConfigState.surface.actions.save),
        cancel: String((surface.actions as Record<string, unknown> | undefined)?.cancel ?? emptyModelConfigState.surface.actions.cancel),
      },
      status: {
        state: normalizedSurfaceState === 'testing' || normalizedSurfaceState === 'verified' || normalizedSurfaceState === 'failed' ? normalizedSurfaceState : 'not_verified',
        text: String((surface.status as Record<string, unknown> | undefined)?.text ?? emptyModelConfigState.surface.status.text),
      },
      messages: {
        bridgeUnavailable: String((surface.messages as Record<string, unknown> | undefined)?.bridgeUnavailable ?? emptyModelConfigState.surface.messages.bridgeUnavailable),
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
  }
}
