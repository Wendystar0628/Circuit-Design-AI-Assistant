export type SettingsSection = 'general' | 'models' | 'about'
export type ModelSection = 'chat' | 'embedding'
export type Language = 'en_US' | 'zh_CN'
export type ThemePreference = 'light' | 'dark' | 'system'

export interface Preferences {
  language: Language
  theme: ThemePreference
}

export interface ChatModelOption {
  id: string
  label: string
  supports_thinking: boolean
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
  requires_api_key: boolean
  models: ChatModelOption[]
}

export interface EmbeddingProviderOption {
  id: string
  label: string
  default_model: string
  default_base_url: string
  requires_api_key: boolean
  models: EmbeddingModelOption[]
}

export interface ChatModelConfig {
  provider: string
  model: string
  base_url: string
  timeout: number
  streaming: boolean
  enable_thinking: boolean
  thinking_timeout: number
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

export interface ModelConfigDraft {
  chat: ChatModelConfig & { api_key: string; clear_api_key: boolean }
  embedding: EmbeddingModelConfig & { api_key: string; clear_api_key: boolean }
}

export interface ModelTestResult {
  section: ModelSection
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
  return {
    chat: {
      ...config.chat,
      api_key: '',
      clear_api_key: false,
    },
    embedding: {
      ...config.embedding,
      api_key: '',
      clear_api_key: false,
    },
  }
}
