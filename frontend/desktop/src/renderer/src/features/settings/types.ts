export type SettingsSection = 'general' | 'models' | 'about'
export type ModelSection = 'chat' | 'embedding'
export type Language = 'en_US' | 'zh_CN'
export type ThemePreference = 'light' | 'dark' | 'system'
export type ApiKeyAction = 'keep' | 'replace' | 'delete'

export interface Preferences {
  language: Language
  theme: ThemePreference
}

export interface ProtocolOption {
  id: string
  label: string
}

export interface ChatModelCapabilities {
  tools: boolean
  vision: boolean
  thinking: boolean
  streaming: boolean
}

export interface ChatModelOption {
  id: string
  label: string
  role: string
  generation: string
  status: string
  protocol: string
  capabilities: ChatModelCapabilities
  description: string
}

export interface EmbeddingModelOption {
  id: string
  label: string
}

export interface ChatProviderOption {
  id: string
  label: string
  default_model: string
  default_base_url: string
  allow_custom_model: boolean
  protocol_options: ProtocolOption[]
  has_api_key: boolean
  models: ChatModelOption[]
}

export interface EmbeddingProviderOption {
  id: string
  label: string
  default_model: string
  default_base_url: string
  requires_api_key: boolean
  has_api_key: boolean
  models: EmbeddingModelOption[]
}

export interface ChatModelConfig {
  provider: string
  model: string
  api_protocol: string
  base_url: string
  effective_base_url: string
  timeout: number
  enable_thinking: boolean
  has_api_key: boolean
}

export interface EmbeddingModelConfig {
  provider: string
  model: string
  base_url: string
  timeout: number
  batch_size: number
  has_api_key: boolean
}

export interface ModelConfig {
  providers: {
    chat: ChatProviderOption[]
    embedding: EmbeddingProviderOption[]
  }
  chat: ChatModelConfig
  embedding: EmbeddingModelConfig
}

export interface ChatModelDraft extends ChatModelConfig {
  api_key: string
  api_key_action: ApiKeyAction
}

export interface EmbeddingModelDraft extends EmbeddingModelConfig {
  api_key: string
  api_key_action: ApiKeyAction
}

export interface ModelConfigDraft {
  chat: ChatModelDraft
  embedding: EmbeddingModelDraft
}

export interface ChatModelRequest {
  provider: string
  model: string
  api_protocol: string
  base_url: string
  timeout: number
  enable_thinking: boolean
  api_key?: string | null
}

export interface EmbeddingModelRequest {
  provider: string
  model: string
  base_url: string
  timeout: number
  batch_size: number
  api_key?: string | null
}

export interface ModelTestResult {
  section?: ModelSection
  status: 'verified' | 'failed'
  message: string
  verified_at: string | null
}

export interface AboutInfo {
  name: string
  version: string
  api_version: string
  python_version: string
  platform: string
}

export interface SettingsFeatureProps {
  active: boolean
  onClose: () => void
  initialSection?: SettingsSection
}

export const defaultPreferences: Preferences = {
  language: 'en_US',
  theme: 'system',
}

export function createModelDraft(config: ModelConfig): ModelConfigDraft {
  const configuredChatProvider = config.providers.chat.find(
    (provider) => provider.id === config.chat.provider,
  )
  const chatProvider = configuredChatProvider ?? config.providers.chat[0]
  const configuredChatModel = chatProvider?.models.find(
    (model) => model.id === config.chat.model,
  )
  const chatModel = configuredChatModel
    ?? chatProvider?.models.find((model) => model.id === chatProvider.default_model)
    ?? chatProvider?.models[0]
  const chatModelId = chatProvider?.allow_custom_model
    ? configuredChatProvider ? config.chat.model : ''
    : chatModel?.id ?? ''
  const apiProtocol = chatProvider?.allow_custom_model
    ? chatProvider.protocol_options.length === 1
      ? chatProvider.protocol_options[0].id
      : configuredChatProvider ? config.chat.api_protocol : ''
    : chatModel?.protocol ?? ''

  const configuredEmbeddingProvider = config.providers.embedding.find(
    (provider) => provider.id === config.embedding.provider,
  )
  const embeddingProvider = configuredEmbeddingProvider ?? config.providers.embedding[0]
  const configuredEmbeddingModel = embeddingProvider?.models.find(
    (model) => model.id === config.embedding.model,
  )
  const embeddingModel = configuredEmbeddingModel
    ?? embeddingProvider?.models.find((model) => model.id === embeddingProvider.default_model)
    ?? embeddingProvider?.models[0]

  return {
    chat: {
      ...config.chat,
      provider: chatProvider?.id ?? '',
      model: chatModelId,
      api_protocol: apiProtocol,
      base_url: configuredChatProvider ? config.chat.base_url : '',
      effective_base_url: configuredChatProvider
        ? config.chat.effective_base_url
        : chatProvider?.default_base_url ?? '',
      enable_thinking: Boolean(
        configuredChatProvider
        && config.chat.enable_thinking
        && (chatProvider.allow_custom_model || chatModel?.capabilities.thinking),
      ),
      has_api_key: chatProvider?.has_api_key ?? config.chat.has_api_key,
      api_key: '',
      api_key_action: 'keep',
    },
    embedding: {
      ...config.embedding,
      provider: embeddingProvider?.id ?? '',
      model: embeddingModel?.id ?? '',
      base_url: configuredEmbeddingProvider ? config.embedding.base_url : '',
      has_api_key: embeddingProvider?.has_api_key ?? config.embedding.has_api_key,
      api_key: '',
      api_key_action: 'keep',
    },
  }
}
