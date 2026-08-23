import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../../lib/api'
import type {
  ChatModelDraft,
  ChatModelRequest,
  ChatProviderOption,
  EmbeddingModelDraft,
  EmbeddingModelRequest,
  EmbeddingProviderOption,
  Language,
  ModelConfig,
  ModelSection,
  ModelTestResult,
} from './types'
import { createModelDraft } from './types'

const API_ROOT = '/api/v1'

const modelCopy = {
  en_US: {
    models: 'Models',
    chat: 'Chat model',
    embedding: 'Embedding model',
    provider: 'Provider',
    model: 'Model',
    customModelHint: 'Enter the model ID supplied by this aggregation platform.',
    openCodeModelHint: 'Enter the API model ID without the opencode/ prefix.',
    curatedModelHint: 'This list contains the supported current models for this provider.',
    protocol: 'API protocol',
    fixedProtocol: 'API protocol: {protocol}',
    selectProtocol: 'Select a protocol',
    apiKey: 'API key',
    apiKeyStored: 'A credential is stored. Leave blank to keep it.',
    apiKeyMissing: 'No credential is stored. Enter a key to add one.',
    apiKeyReplace: 'A new credential will replace the stored key when saved.',
    apiKeyDeletePending: 'The stored credential will be deleted when saved.',
    deleteApiKey: 'Delete stored key',
    undoDelete: 'Undo deletion',
    advanced: 'Advanced connection',
    baseUrl: 'Base URL override',
    providerDefault: 'Leave blank to use the provider default.',
    effectiveBaseUrl: 'Effective URL: {url}',
    timeout: 'Timeout (seconds)',
    batchSize: 'Batch size',
    thinking: 'Deep thinking',
    customThinkingHint: 'Availability depends on the model and selected protocol.',
    capabilities: 'Capabilities',
    capabilitiesUnknown: 'Custom model capabilities are unknown. The connection test checks only basic availability.',
    tools: 'Tools',
    vision: 'Vision',
    reasoning: 'Thinking',
    streaming: 'Streaming',
    noTools: 'No tools',
    noVision: 'No vision',
    noReasoning: 'No thinking',
    noStreaming: 'No streaming',
    test: 'Test connection',
    testing: 'Testing…',
    saveChat: 'Save chat model',
    saveEmbedding: 'Save embedding model',
    saving: 'Saving…',
    notVerified: 'Basic connection not tested.',
    verified: 'Basic connection verified.',
    failed: 'Basic connection failed.',
    chatSaved: 'Chat model configuration saved.',
    embeddingSaved: 'Embedding model configuration saved.',
    modelMeta: {
      current_performance: 'Current performance flagship',
      current_speed: 'Current speed flagship',
      previous_performance: 'Previous-generation performance flagship',
      previous_speed: 'Previous-generation speed flagship',
      current: 'Current generation',
      previous: 'Previous generation',
      stable: 'Stable',
      preview: 'Preview',
    },
  },
  zh_CN: {
    models: '模型',
    chat: '对话模型',
    embedding: '嵌入模型',
    provider: '服务商',
    model: '模型',
    customModelHint: '请输入聚合平台提供的模型 ID。',
    openCodeModelHint: '请输入 API 模型 ID，不要带 opencode/ 前缀。',
    curatedModelHint: '列表仅包含该服务商当前受支持的模型。',
    protocol: 'API 协议',
    fixedProtocol: 'API 协议：{protocol}',
    selectProtocol: '请选择协议',
    apiKey: 'API 密钥',
    apiKeyStored: '已保存凭证；留空将保留现有密钥。',
    apiKeyMissing: '尚未保存凭证；输入密钥即可新增。',
    apiKeyReplace: '保存时将使用新凭证替换现有密钥。',
    apiKeyDeletePending: '保存时将删除现有凭证。',
    deleteApiKey: '删除已保存密钥',
    undoDelete: '撤销删除',
    advanced: '高级连接设置',
    baseUrl: '基础 URL 覆盖值',
    providerDefault: '留空将使用服务商默认地址。',
    effectiveBaseUrl: '实际地址：{url}',
    timeout: '超时（秒）',
    batchSize: '批大小',
    thinking: '深度思考',
    customThinkingHint: '是否可用取决于模型和所选协议。',
    capabilities: '能力',
    capabilitiesUnknown: '自定义模型的能力信息未知；连接测试只验证基础可用性。',
    tools: '工具调用',
    vision: '视觉',
    reasoning: '深度思考',
    streaming: '流式输出',
    noTools: '无工具调用',
    noVision: '无视觉',
    noReasoning: '无深度思考',
    noStreaming: '无流式输出',
    test: '测试连接',
    testing: '正在测试…',
    saveChat: '保存对话模型',
    saveEmbedding: '保存嵌入模型',
    saving: '正在保存…',
    notVerified: '尚未测试基础连接。',
    verified: '基础连接已验证。',
    failed: '基础连接失败。',
    chatSaved: '对话模型配置已保存。',
    embeddingSaved: '嵌入模型配置已保存。',
    modelMeta: {
      current_performance: '当代性能旗舰',
      current_speed: '当代速度旗舰',
      previous_performance: '上代性能旗舰',
      previous_speed: '上代速度旗舰',
      current: '当代',
      previous: '上代',
      stable: '稳定版',
      preview: '预览版',
    },
  },
} as const

interface ModelSettingsPanelProps {
  config: ModelConfig
  language: Language
  onConfigChange: (config: ModelConfig) => void
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || 'Unknown error')
}

function providerById<T extends { id: string }>(providers: T[], id: string): T | undefined {
  return providers.find((provider) => provider.id === id)
}

function isModelConfig(value: unknown): value is ModelConfig {
  if (!value || typeof value !== 'object') return false
  const record = value as Record<string, unknown>
  return Boolean(record.providers && record.chat && record.embedding)
}

function chatRequest(draft: ChatModelDraft): ChatModelRequest {
  const request: ChatModelRequest = {
    provider: draft.provider,
    model: draft.model.trim(),
    api_protocol: draft.api_protocol,
    base_url: draft.base_url.trim(),
    timeout: draft.timeout,
    enable_thinking: draft.enable_thinking,
  }
  const apiKey = draft.api_key.trim()
  if (draft.api_key_action === 'delete') request.api_key = null
  if (draft.api_key_action === 'replace' && apiKey) request.api_key = apiKey
  return request
}

function embeddingRequest(draft: EmbeddingModelDraft): EmbeddingModelRequest {
  const request: EmbeddingModelRequest = {
    provider: draft.provider,
    model: draft.model,
    base_url: draft.base_url.trim(),
    timeout: draft.timeout,
    batch_size: draft.batch_size,
  }
  const apiKey = draft.api_key.trim()
  if (draft.api_key_action === 'delete') request.api_key = null
  if (draft.api_key_action === 'replace' && apiKey) request.api_key = apiKey
  return request
}

function Toggle({ checked, disabled, label, onChange }: {
  checked: boolean
  disabled?: boolean
  label: string
  onChange: (value: boolean) => void
}) {
  return (
    <label className={`settings-toggle${disabled ? ' settings-toggle--disabled' : ''}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span aria-hidden="true" />
      <strong>{label}</strong>
    </label>
  )
}

export function ModelSettingsPanel({
  config,
  language,
  onConfigChange,
}: ModelSettingsPanelProps) {
  const text = modelCopy[language]
  const [section, setSection] = useState<ModelSection>('chat')
  const [draft, setDraft] = useState(() => createModelDraft(config))
  const [testResults, setTestResults] = useState<Partial<Record<ModelSection, ModelTestResult>>>({})
  const [errors, setErrors] = useState<Record<ModelSection, string>>({ chat: '', embedding: '' })
  const [notices, setNotices] = useState<Record<ModelSection, string>>({ chat: '', embedding: '' })
  const [testing, setTesting] = useState<ModelSection | null>(null)
  const [saving, setSaving] = useState<ModelSection | null>(null)
  const preserveDraftSection = useRef<ModelSection | null>(null)

  useEffect(() => {
    setDraft((current) => {
      const next = createModelDraft(config)
      const preserved = preserveDraftSection.current
      preserveDraftSection.current = null
      if (preserved === 'chat') return { ...next, chat: current.chat }
      if (preserved === 'embedding') return { ...next, embedding: current.embedding }
      return next
    })
  }, [config])

  const chatProvider = useMemo(
    () => providerById(config.providers.chat, draft.chat.provider),
    [config.providers.chat, draft.chat.provider],
  )
  const chatModel = useMemo(
    () => chatProvider?.models.find((model) => model.id === draft.chat.model),
    [chatProvider, draft.chat.model],
  )
  const embeddingProvider = useMemo(
    () => providerById(config.providers.embedding, draft.embedding.provider),
    [config.providers.embedding, draft.embedding.provider],
  )

  const invalidate = (target: ModelSection) => {
    setTestResults((current) => ({ ...current, [target]: undefined }))
    setErrors((current) => ({ ...current, [target]: '' }))
    setNotices((current) => ({ ...current, [target]: '' }))
  }

  const updateChat = (change: Partial<ChatModelDraft>) => {
    setDraft((current) => ({ ...current, chat: { ...current.chat, ...change } }))
    invalidate('chat')
  }

  const updateEmbedding = (change: Partial<EmbeddingModelDraft>) => {
    setDraft((current) => ({ ...current, embedding: { ...current.embedding, ...change } }))
    invalidate('embedding')
  }

  const selectChatProvider = (provider: ChatProviderOption) => {
    const savedProvider = provider.id === config.chat.provider
    const model = provider.allow_custom_model
      ? savedProvider ? config.chat.model : ''
      : savedProvider && provider.models.some((candidate) => candidate.id === config.chat.model)
        ? config.chat.model
        : provider.default_model || provider.models[0]?.id || ''
    const modelOption = provider.models.find((candidate) => candidate.id === model)
    const apiProtocol = modelOption?.protocol
      || (provider.protocol_options.length === 1
        ? provider.protocol_options[0].id
        : savedProvider ? config.chat.api_protocol : '')
    setDraft((current) => ({
      ...current,
      chat: {
        ...current.chat,
        provider: provider.id,
        model,
        api_protocol: apiProtocol,
        base_url: savedProvider ? config.chat.base_url : '',
        effective_base_url: savedProvider
          ? config.chat.effective_base_url
          : provider.default_base_url,
        enable_thinking: savedProvider ? config.chat.enable_thinking : false,
        has_api_key: provider.has_api_key,
        api_key: '',
        api_key_action: 'keep',
      },
    }))
    invalidate('chat')
  }

  const selectEmbeddingProvider = (provider: EmbeddingProviderOption) => {
    const savedProvider = provider.id === config.embedding.provider
    setDraft((current) => ({
      ...current,
      embedding: {
        ...current.embedding,
        provider: provider.id,
        model: savedProvider
          && provider.models.some((candidate) => candidate.id === config.embedding.model)
          ? config.embedding.model
          : provider.default_model || provider.models[0]?.id || '',
        base_url: savedProvider ? config.embedding.base_url : '',
        has_api_key: provider.has_api_key,
        api_key: '',
        api_key_action: 'keep',
      },
    }))
    invalidate('embedding')
  }

  const selectChatModel = (modelId: string) => {
    const model = chatProvider?.models.find((candidate) => candidate.id === modelId)
    updateChat({
      model: modelId,
      api_protocol: model?.protocol || draft.chat.api_protocol,
      enable_thinking: model?.capabilities.thinking ? draft.chat.enable_thinking : false,
    })
  }

  const changeChatApiKey = (value: string) => {
    updateChat({
      api_key: value,
      api_key_action: value.trim() ? 'replace' : 'keep',
    })
  }

  const changeEmbeddingApiKey = (value: string) => {
    updateEmbedding({
      api_key: value,
      api_key_action: value.trim() ? 'replace' : 'keep',
    })
  }

  const testConnection = async (target: ModelSection) => {
    setTesting(target)
    setErrors((current) => ({ ...current, [target]: '' }))
    setNotices((current) => ({ ...current, [target]: '' }))
    setTestResults((current) => ({ ...current, [target]: undefined }))
    try {
      const payload = target === 'chat'
        ? chatRequest(draft.chat)
        : embeddingRequest(draft.embedding)
      const result = await api.post<ModelTestResult>(
        `${API_ROOT}/model-config/${target}/test`,
        payload,
      )
      setTestResults((current) => ({ ...current, [target]: result }))
    } catch (testError) {
      setTestResults((current) => ({
        ...current,
        [target]: {
          section: target,
          status: 'failed',
          message: errorMessage(testError),
          verified_at: null,
        },
      }))
    } finally {
      setTesting(null)
    }
  }

  const saveModel = async (target: ModelSection) => {
    setSaving(target)
    setErrors((current) => ({ ...current, [target]: '' }))
    setNotices((current) => ({ ...current, [target]: '' }))
    try {
      const payload = target === 'chat'
        ? chatRequest(draft.chat)
        : embeddingRequest(draft.embedding)
      const response = await api.put<unknown>(`${API_ROOT}/model-config/${target}`, payload)
      const saved = isModelConfig(response)
        ? response
        : await api.get<ModelConfig>(`${API_ROOT}/model-config`)
      preserveDraftSection.current = target === 'chat' ? 'embedding' : 'chat'
      onConfigChange(saved)
      setNotices((current) => ({
        ...current,
        [target]: target === 'chat' ? text.chatSaved : text.embeddingSaved,
      }))
    } catch (saveError) {
      setErrors((current) => ({ ...current, [target]: errorMessage(saveError) }))
    } finally {
      setSaving(null)
    }
  }

  const chatProtocolOptions = chatProvider?.protocol_options ?? []
  const customChatModel = Boolean(chatProvider?.allow_custom_model)
  const showProtocolSelect = customChatModel && chatProtocolOptions.length > 1
  const fixedProtocol = customChatModel && chatProtocolOptions.length === 1
    ? chatProtocolOptions[0]
    : undefined
  const thinkingAvailable = customChatModel || Boolean(chatModel?.capabilities.thinking)
  const modelMetadata = chatModel
    ? [chatModel.role, chatModel.generation, chatModel.status]
      .map((value) => text.modelMeta[value as keyof typeof text.modelMeta])
      .filter(Boolean)
    : []
  const chatEffectiveBaseUrl = draft.chat.base_url.trim()
    || chatProvider?.default_base_url
    || ''
  const chatValid = Boolean(
    chatProvider
    && draft.chat.model.trim()
    && draft.chat.api_protocol
    && draft.chat.timeout >= 1
    && draft.chat.timeout <= 600,
  )
  const embeddingValid = Boolean(
    embeddingProvider
    && draft.embedding.model
    && draft.embedding.timeout >= 1
    && draft.embedding.timeout <= 600
    && draft.embedding.batch_size >= 1
    && draft.embedding.batch_size <= 256,
  )
  const chatHasCredential = draft.chat.api_key_action === 'replace'
    ? Boolean(draft.chat.api_key.trim())
    : draft.chat.api_key_action === 'keep' && draft.chat.has_api_key
  const embeddingHasCredential = !embeddingProvider?.requires_api_key
    || (draft.embedding.api_key_action === 'replace'
      ? Boolean(draft.embedding.api_key.trim())
      : draft.embedding.api_key_action === 'keep' && draft.embedding.has_api_key)
  const currentResult = testResults[section]
  const currentError = errors[section]
  const currentNotice = notices[section]
  const currentValid = section === 'chat' ? chatValid : embeddingValid
  const currentConnectionValid = section === 'chat'
    ? chatValid && chatHasCredential
    : embeddingValid && embeddingHasCredential
  const busy = Boolean(testing || saving)

  return (
    <section className="settings-section settings-section--models" aria-labelledby="settings-models-title">
      <div className="settings-section__heading settings-section__heading--tabs">
        <h2 id="settings-models-title">{text.models}</h2>
        <div className="settings-tabs" role="tablist">
          <button
            id="settings-chat-tab"
            type="button"
            role="tab"
            aria-selected={section === 'chat'}
            aria-controls="settings-chat-panel"
            className={section === 'chat' ? 'is-active' : ''}
            disabled={busy}
            onClick={() => setSection('chat')}
          >
            {text.chat}
          </button>
          <button
            id="settings-embedding-tab"
            type="button"
            role="tab"
            aria-selected={section === 'embedding'}
            aria-controls="settings-embedding-panel"
            className={section === 'embedding' ? 'is-active' : ''}
            disabled={busy}
            onClick={() => setSection('embedding')}
          >
            {text.embedding}
          </button>
        </div>
      </div>

      <fieldset className="settings-model-form" disabled={busy} aria-busy={busy}>
        {section === 'chat' ? (
          <div
            id="settings-chat-panel"
            className="settings-model-panel"
            role="tabpanel"
            aria-labelledby="settings-chat-tab"
          >
          <div className="settings-model-grid">
            <label className="settings-model-field">
              <span>{text.provider}</span>
              <select
                value={draft.chat.provider}
                onChange={(event) => {
                  const provider = providerById(config.providers.chat, event.target.value)
                  if (provider) selectChatProvider(provider)
                }}
              >
                {config.providers.chat.map((provider) => (
                  <option key={provider.id} value={provider.id}>{provider.label}</option>
                ))}
              </select>
            </label>

            <label className="settings-model-field">
              <span>{text.model}</span>
              {customChatModel ? (
                <input
                  type="text"
                  value={draft.chat.model}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(event) => updateChat({ model: event.target.value })}
                />
              ) : (
                <select value={draft.chat.model} onChange={(event) => selectChatModel(event.target.value)}>
                  {chatProvider?.models.map((model) => (
                    <option key={model.id} value={model.id}>{model.label}</option>
                  ))}
                </select>
              )}
              <small>
                {customChatModel
                  ? chatProvider?.id === 'opencode'
                    ? text.openCodeModelHint
                    : text.customModelHint
                  : text.curatedModelHint}
              </small>
            </label>

            {showProtocolSelect ? (
              <label className="settings-model-field settings-model-grid__wide">
                <span>{text.protocol}</span>
                <select
                  value={draft.chat.api_protocol}
                  onChange={(event) => updateChat({ api_protocol: event.target.value })}
                >
                  <option value="" disabled>{text.selectProtocol}</option>
                  {chatProtocolOptions.map((protocol) => (
                    <option key={protocol.id} value={protocol.id}>{protocol.label}</option>
                  ))}
                </select>
              </label>
            ) : null}

            {fixedProtocol ? (
              <div className="settings-model-protocol-note settings-model-grid__wide">
                {text.fixedProtocol.replace('{protocol}', fixedProtocol.label)}
              </div>
            ) : null}

            <div className="settings-model-capabilities settings-model-grid__wide">
              <strong>{text.capabilities}</strong>
              {chatModel ? (
                <>
                  <div className="settings-capability-list" aria-label={text.capabilities}>
                    <span data-supported={chatModel.capabilities.tools}>{chatModel.capabilities.tools ? text.tools : text.noTools}</span>
                    <span data-supported={chatModel.capabilities.vision}>{chatModel.capabilities.vision ? text.vision : text.noVision}</span>
                    <span data-supported={chatModel.capabilities.thinking}>{chatModel.capabilities.thinking ? text.reasoning : text.noReasoning}</span>
                    <span data-supported={chatModel.capabilities.streaming}>{chatModel.capabilities.streaming ? text.streaming : text.noStreaming}</span>
                  </div>
                  {chatModel.description ? <small>{chatModel.description}</small> : null}
                  {modelMetadata.length ? (
                    <small className="settings-model-meta">
                      {modelMetadata.join(' · ')}
                    </small>
                  ) : null}
                </>
              ) : (
                <small>{text.capabilitiesUnknown}</small>
              )}
            </div>

            <div className="settings-model-field settings-model-grid__wide">
              <label htmlFor="settings-chat-api-key">{text.apiKey}</label>
              <div className="settings-api-key-row">
                <input
                  id="settings-chat-api-key"
                  type="password"
                  value={draft.chat.api_key}
                  disabled={draft.chat.api_key_action === 'delete'}
                  placeholder={draft.chat.has_api_key ? '••••••••••••' : ''}
                  autoComplete="new-password"
                  spellCheck={false}
                  onChange={(event) => changeChatApiKey(event.target.value)}
                />
                {draft.chat.has_api_key ? (
                  <button
                    type="button"
                    className={draft.chat.api_key_action === 'delete' ? 'settings-text-button' : 'settings-text-button settings-text-button--danger'}
                    onClick={() => updateChat({
                      api_key: '',
                      api_key_action: draft.chat.api_key_action === 'delete' ? 'keep' : 'delete',
                    })}
                  >
                    {draft.chat.api_key_action === 'delete' ? text.undoDelete : text.deleteApiKey}
                  </button>
                ) : null}
              </div>
              <small>
                {draft.chat.api_key_action === 'delete'
                  ? text.apiKeyDeletePending
                  : draft.chat.api_key_action === 'replace'
                    ? text.apiKeyReplace
                    : draft.chat.has_api_key
                      ? text.apiKeyStored
                      : text.apiKeyMissing}
              </small>
            </div>

            <div className="settings-model-toggle settings-model-grid__wide">
              <Toggle
                label={text.thinking}
                checked={draft.chat.enable_thinking}
                disabled={!thinkingAvailable}
                onChange={(value) => updateChat({ enable_thinking: value })}
              />
              {customChatModel ? <small>{text.customThinkingHint}</small> : null}
            </div>
          </div>

          <details className="settings-advanced">
            <summary>{text.advanced}</summary>
            <div className="settings-advanced__grid">
              <label className="settings-model-field settings-model-grid__wide">
                <span>{text.baseUrl}</span>
                <input
                  type="url"
                  value={draft.chat.base_url}
                  placeholder={chatProvider?.default_base_url || text.providerDefault}
                  onChange={(event) => updateChat({ base_url: event.target.value })}
                />
                <small>
                  {chatEffectiveBaseUrl
                    ? text.effectiveBaseUrl.replace('{url}', chatEffectiveBaseUrl)
                    : text.providerDefault}
                </small>
              </label>
              <label className="settings-model-field">
                <span>{text.timeout}</span>
                <input
                  type="number"
                  min="1"
                  max="600"
                  value={draft.chat.timeout}
                  onChange={(event) => updateChat({ timeout: Number(event.target.value) })}
                />
              </label>
            </div>
          </details>
          </div>
        ) : (
          <div
            id="settings-embedding-panel"
            className="settings-model-panel"
            role="tabpanel"
            aria-labelledby="settings-embedding-tab"
          >
          <div className="settings-model-grid">
            <label className="settings-model-field">
              <span>{text.provider}</span>
              <select
                value={draft.embedding.provider}
                onChange={(event) => {
                  const provider = providerById(config.providers.embedding, event.target.value)
                  if (provider) selectEmbeddingProvider(provider)
                }}
              >
                {config.providers.embedding.map((provider) => (
                  <option key={provider.id} value={provider.id}>{provider.label}</option>
                ))}
              </select>
            </label>
            <label className="settings-model-field">
              <span>{text.model}</span>
              <select
                value={draft.embedding.model}
                onChange={(event) => updateEmbedding({ model: event.target.value })}
              >
                {embeddingProvider?.models.map((model) => (
                  <option key={model.id} value={model.id}>{model.label}</option>
                ))}
              </select>
            </label>

            <div className="settings-model-field settings-model-grid__wide">
              <label htmlFor="settings-embedding-api-key">{text.apiKey}</label>
              <div className="settings-api-key-row">
                <input
                  id="settings-embedding-api-key"
                  type="password"
                  value={draft.embedding.api_key}
                  disabled={draft.embedding.api_key_action === 'delete'}
                  placeholder={draft.embedding.has_api_key ? '••••••••••••' : ''}
                  autoComplete="new-password"
                  spellCheck={false}
                  onChange={(event) => changeEmbeddingApiKey(event.target.value)}
                />
                {draft.embedding.has_api_key ? (
                  <button
                    type="button"
                    className={draft.embedding.api_key_action === 'delete' ? 'settings-text-button' : 'settings-text-button settings-text-button--danger'}
                    onClick={() => updateEmbedding({
                      api_key: '',
                      api_key_action: draft.embedding.api_key_action === 'delete' ? 'keep' : 'delete',
                    })}
                  >
                    {draft.embedding.api_key_action === 'delete' ? text.undoDelete : text.deleteApiKey}
                  </button>
                ) : null}
              </div>
              <small>
                {draft.embedding.api_key_action === 'delete'
                  ? text.apiKeyDeletePending
                  : draft.embedding.api_key_action === 'replace'
                    ? text.apiKeyReplace
                    : draft.embedding.has_api_key
                      ? text.apiKeyStored
                      : text.apiKeyMissing}
              </small>
            </div>
          </div>

          <details className="settings-advanced">
            <summary>{text.advanced}</summary>
            <div className="settings-advanced__grid">
              <label className="settings-model-field settings-model-grid__wide">
                <span>{text.baseUrl}</span>
                <input
                  type="url"
                  value={draft.embedding.base_url}
                  placeholder={embeddingProvider?.default_base_url || text.providerDefault}
                  onChange={(event) => updateEmbedding({ base_url: event.target.value })}
                />
                <small>{draft.embedding.base_url || embeddingProvider?.default_base_url || text.providerDefault}</small>
              </label>
              <label className="settings-model-field">
                <span>{text.timeout}</span>
                <input
                  type="number"
                  min="1"
                  max="600"
                  value={draft.embedding.timeout}
                  onChange={(event) => updateEmbedding({ timeout: Number(event.target.value) })}
                />
              </label>
              <label className="settings-model-field">
                <span>{text.batchSize}</span>
                <input
                  type="number"
                  min="1"
                  max="256"
                  value={draft.embedding.batch_size}
                  onChange={(event) => updateEmbedding({ batch_size: Number(event.target.value) })}
                />
              </label>
            </div>
          </details>
          </div>
        )}
      </fieldset>

      {currentError ? (
        <div className="settings-model-message settings-model-message--error" role="alert">
          {currentError}
        </div>
      ) : null}
      {currentNotice ? (
        <div className="settings-model-message settings-model-message--success" role="status">
          {currentNotice}
        </div>
      ) : null}

      <footer className="settings-actions settings-actions--split">
        <div
          className={`settings-verification settings-verification--${currentResult?.status ?? 'idle'}`}
          role={currentResult?.status === 'failed' ? 'alert' : 'status'}
        >
          {currentResult?.message
            || (currentResult?.status === 'verified'
              ? text.verified
              : currentResult?.status === 'failed'
                ? text.failed
                : text.notVerified)}
        </div>
        <div>
          <button
            type="button"
            className="settings-button settings-button--secondary"
            disabled={busy || !currentConnectionValid}
            onClick={() => void testConnection(section)}
          >
            {testing === section ? text.testing : text.test}
          </button>
          <button
            type="button"
            className="settings-button settings-button--primary"
            disabled={busy || !currentValid}
            onClick={() => void saveModel(section)}
          >
            {saving === section
              ? text.saving
              : section === 'chat'
                ? text.saveChat
                : text.saveEmbedding}
          </button>
        </div>
      </footer>
    </section>
  )
}
