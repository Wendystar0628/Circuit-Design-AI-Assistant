import { useEffect, useMemo, useState } from 'react'

import { api } from '../../lib/api'
import './settings.css'
import type {
  AboutInfo,
  ChatProviderOption,
  EmbeddingProviderOption,
  ModelConfig,
  ModelConfigDraft,
  ModelSection,
  ModelTestResult,
  Preferences,
  SettingsFeatureProps,
  SettingsSection,
} from './types'
import { createModelDraft, defaultPreferences } from './types'
import { useDialogFocus } from './useDialogFocus'

const API_ROOT = '/api/v1'

const copy = {
  en_US: {
    title: 'Settings',
    subtitle: 'Application preferences and model connections',
    general: 'General',
    models: 'Models',
    about: 'About',
    close: 'Close',
    save: 'Save changes',
    saving: 'Saving…',
    loading: 'Loading settings…',
    retry: 'Retry',
    language: 'Language',
    languageHint: 'Changes the language used in this settings window.',
    theme: 'Theme',
    themeHint: 'Changes the appearance of this settings window.',
    english: 'English',
    chinese: '简体中文',
    system: 'System',
    light: 'Light',
    dark: 'Dark',
    preferencesSaved: 'Preferences saved.',
    chat: 'Chat model',
    embedding: 'Embedding model',
    provider: 'Provider',
    model: 'Model',
    apiKey: 'API key',
    apiKeyStored: 'A credential is stored. Leave blank to keep it.',
    apiKeyMissing: 'No credential is stored.',
    clearApiKey: 'Clear stored API key',
    baseUrl: 'Base URL',
    providerDefault: 'Provider default',
    timeout: 'Timeout (seconds)',
    streaming: 'Streaming responses',
    thinking: 'Deep thinking',
    thinkingTimeout: 'Thinking timeout (seconds)',
    batchSize: 'Batch size',
    test: 'Test connection',
    testing: 'Testing…',
    verified: 'Verified',
    notVerified: 'Not verified',
    modelSaved: 'Model configuration saved.',
    version: 'Version',
    desktopRuntime: 'Desktop runtime',
    backendRuntime: 'Backend runtime',
    apiVersion: 'API version',
    description: 'A provider-independent desktop workspace for AI-assisted circuit design, analysis, and simulation.',
    licenses: 'Core components include Electron, React, Python, and ngspice. Their respective licenses apply.',
  },
  zh_CN: {
    title: '设置',
    subtitle: '应用偏好与模型连接',
    general: '通用',
    models: '模型',
    about: '关于',
    close: '关闭',
    save: '保存更改',
    saving: '正在保存…',
    loading: '正在加载设置…',
    retry: '重试',
    language: '语言',
    languageHint: '切换当前设置窗口的语言。',
    theme: '主题',
    themeHint: '切换当前设置窗口的外观。',
    english: 'English',
    chinese: '简体中文',
    system: '跟随系统',
    light: '浅色',
    dark: '深色',
    preferencesSaved: '偏好设置已保存。',
    chat: '对话模型',
    embedding: '嵌入模型',
    provider: '服务商',
    model: '模型',
    apiKey: 'API 密钥',
    apiKeyStored: '已保存凭证；留空将保留现有密钥。',
    apiKeyMissing: '尚未保存凭证。',
    clearApiKey: '清除已保存的 API 密钥',
    baseUrl: '基础 URL',
    providerDefault: '使用服务商默认地址',
    timeout: '超时（秒）',
    streaming: '流式响应',
    thinking: '深度思考',
    thinkingTimeout: '思考超时（秒）',
    batchSize: '批大小',
    test: '测试连接',
    testing: '正在测试…',
    verified: '已验证',
    notVerified: '未验证',
    modelSaved: '模型配置已保存。',
    version: '版本',
    desktopRuntime: '桌面运行环境',
    backendRuntime: '后端运行环境',
    apiVersion: 'API 版本',
    description: '面向电路设计、分析与仿真的供应商无关 AI 桌面工作区。',
    licenses: '核心组件包括 Electron、React、Python 与 ngspice，并分别遵循其软件许可证。',
  },
} as const

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || 'Unknown error')
}

function providerById<T extends { id: string }>(providers: T[], id: string): T | undefined {
  return providers.find((provider) => provider.id === id)
}

function apiKeyPayload(value: string, clear: boolean): string | null | undefined {
  if (clear) {
    return null
  }
  const normalized = value.trim()
  return normalized || undefined
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="settings-state" role="status">
      <span className="settings-spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

function ErrorState({ message, retry, label }: { message: string; retry: () => void; label: string }) {
  return (
    <div className="settings-state settings-state--error" role="alert">
      <strong>{message}</strong>
      <button type="button" className="settings-button settings-button--secondary" onClick={retry}>
        {label}
      </button>
    </div>
  )
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

export function SettingsFeature({ active, onClose, initialSection = 'general' }: SettingsFeatureProps) {
  const [section, setSection] = useState<SettingsSection>(initialSection)
  const [modelSection, setModelSection] = useState<ModelSection>('chat')
  const [preferences, setPreferences] = useState<Preferences>(defaultPreferences)
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null)
  const [modelDraft, setModelDraft] = useState<ModelConfigDraft | null>(null)
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [testResults, setTestResults] = useState<Partial<Record<ModelSection, ModelTestResult>>>({})
  const [loading, setLoading] = useState(false)
  const [savingPreferences, setSavingPreferences] = useState(false)
  const [savingModels, setSavingModels] = useState(false)
  const [testing, setTesting] = useState<ModelSection | null>(null)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const language = preferences.language in copy ? preferences.language : 'en_US'
  const text = copy[language]
  const dialogRef = useDialogFocus(active, onClose)

  const load = async () => {
    setLoading(true)
    setLoadError('')
    setError('')
    setNotice('')
    try {
      const [nextPreferences, nextModelConfig, nextAbout] = await Promise.all([
        api.get<Preferences>(`${API_ROOT}/preferences`),
        api.get<ModelConfig>(`${API_ROOT}/model-config`),
        api.get<AboutInfo>(`${API_ROOT}/about`),
      ])
      setPreferences(nextPreferences)
      document.documentElement.dataset.theme = nextPreferences.theme
      setModelConfig(nextModelConfig)
      setModelDraft(createModelDraft(nextModelConfig))
      setAbout(nextAbout)
      setTestResults({})
    } catch (loadError) {
      setLoadError(errorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!active) {
      return
    }
    setSection(initialSection)
    void load()
  }, [active, initialSection])

  const chatProvider = useMemo(
    () => modelConfig && modelDraft
      ? providerById(modelConfig.providers.chat, modelDraft.chat.provider)
      : undefined,
    [modelConfig, modelDraft],
  )
  const embeddingProvider = useMemo(
    () => modelConfig && modelDraft
      ? providerById(modelConfig.providers.embedding, modelDraft.embedding.provider)
      : undefined,
    [modelConfig, modelDraft],
  )

  if (!active) {
    return null
  }

  const savePreferences = async () => {
    setSavingPreferences(true)
    setError('')
    setNotice('')
    try {
      const saved = await api.put<Preferences>(`${API_ROOT}/preferences`, preferences)
      setPreferences(saved)
      document.documentElement.dataset.theme = saved.theme
      setNotice(copy[saved.language].preferencesSaved)
    } catch (saveError) {
      setError(errorMessage(saveError))
    } finally {
      setSavingPreferences(false)
    }
  }

  const testConnection = async (target: ModelSection) => {
    if (!modelDraft) {
      return
    }
    setTesting(target)
    setError('')
    setNotice('')
    try {
      const current = modelDraft[target]
      const payload = target === 'chat'
        ? {
            section: target,
            config: {
              provider: current.provider,
              model: current.model,
              base_url: current.base_url,
              timeout: current.timeout,
              api_key: apiKeyPayload(current.api_key, current.clear_api_key),
              streaming: modelDraft.chat.streaming,
              enable_thinking: modelDraft.chat.enable_thinking,
              thinking_timeout: modelDraft.chat.thinking_timeout,
            },
          }
        : {
            section: target,
            config: {
              provider: current.provider,
              model: current.model,
              base_url: current.base_url,
              timeout: current.timeout,
              api_key: apiKeyPayload(current.api_key, current.clear_api_key),
              batch_size: modelDraft.embedding.batch_size,
            },
          }
      const result = await api.post<ModelTestResult>(`${API_ROOT}/model-config/test`, payload)
      setTestResults((currentResults) => ({ ...currentResults, [target]: result }))
      if (result.status === 'failed') {
        setError(result.message)
      } else {
        setNotice(result.message || text.verified)
      }
    } catch (testError) {
      setError(errorMessage(testError))
    } finally {
      setTesting(null)
    }
  }

  const saveModelConfig = async () => {
    if (!modelDraft) {
      return
    }
    setSavingModels(true)
    setError('')
      setNotice('')
    try {
      const saved = await api.put<ModelConfig>(`${API_ROOT}/model-config`, {
        chat: {
          provider: modelDraft.chat.provider,
          model: modelDraft.chat.model,
          base_url: modelDraft.chat.base_url,
          timeout: modelDraft.chat.timeout,
          streaming: modelDraft.chat.streaming,
          enable_thinking: modelDraft.chat.enable_thinking,
          thinking_timeout: modelDraft.chat.thinking_timeout,
          api_key: apiKeyPayload(modelDraft.chat.api_key, modelDraft.chat.clear_api_key),
        },
        embedding: {
          provider: modelDraft.embedding.provider,
          model: modelDraft.embedding.model,
          base_url: modelDraft.embedding.base_url,
          timeout: modelDraft.embedding.timeout,
          batch_size: modelDraft.embedding.batch_size,
          api_key: apiKeyPayload(modelDraft.embedding.api_key, modelDraft.embedding.clear_api_key),
        },
      })
      setModelConfig(saved)
      setModelDraft(createModelDraft(saved))
      setNotice(text.modelSaved)
    } catch (saveError) {
      setError(errorMessage(saveError))
    } finally {
      setSavingModels(false)
    }
  }

  return (
    <div className="settings-layer">
      <button type="button" className="settings-backdrop" onClick={onClose} aria-label={text.close} />
      <div ref={dialogRef} className="settings-shell" role="dialog" aria-modal="true" aria-labelledby="settings-title" tabIndex={-1}>
        <header className="settings-header">
          <div>
            <h1 id="settings-title">{text.title}</h1>
            <p>{text.subtitle}</p>
          </div>
          <button data-initial-focus type="button" className="settings-icon-button" onClick={onClose} aria-label={text.close}>×</button>
        </header>

        <div className="settings-body">
          <nav className="settings-nav" aria-label={text.title}>
            {(['general', 'models', 'about'] as SettingsSection[]).map((item) => (
              <button key={item} type="button" className={section === item ? 'is-active' : ''} onClick={() => { setSection(item); setError(''); setNotice('') }}>
                {text[item]}
              </button>
            ))}
          </nav>

          <main className="settings-content">
            {loading ? <LoadingState label={text.loading} /> : null}
            {!loading && loadError ? <ErrorState message={loadError} retry={() => void load()} label={text.retry} /> : null}
            {!loading && !loadError && modelConfig ? (
              <>
                {error ? <div className="settings-alert settings-alert--error" role="alert">{error}</div> : null}
                {notice ? <div className="settings-alert settings-alert--success" role="status">{notice}</div> : null}

                {section === 'general' ? (
                  <section className="settings-section" aria-labelledby="settings-general-title">
                    <div className="settings-section__heading">
                      <h2 id="settings-general-title">{text.general}</h2>
                    </div>
                    <label className="settings-field">
                      <span><strong>{text.language}</strong><small>{text.languageHint}</small></span>
                      <select value={preferences.language} onChange={(event) => setPreferences((current) => ({ ...current, language: event.target.value as Preferences['language'] }))}>
                        <option value="en_US">{text.english}</option>
                        <option value="zh_CN">{text.chinese}</option>
                      </select>
                    </label>
                    <label className="settings-field">
                      <span><strong>{text.theme}</strong><small>{text.themeHint}</small></span>
                      <select value={preferences.theme} onChange={(event) => setPreferences((current) => ({ ...current, theme: event.target.value as Preferences['theme'] }))}>
                        <option value="system">{text.system}</option>
                        <option value="light">{text.light}</option>
                        <option value="dark">{text.dark}</option>
                      </select>
                    </label>
                    <footer className="settings-actions">
                      <button type="button" className="settings-button settings-button--primary" disabled={savingPreferences} onClick={() => void savePreferences()}>{savingPreferences ? text.saving : text.save}</button>
                    </footer>
                  </section>
                ) : null}

                {section === 'models' && modelDraft ? (
                  <section className="settings-section settings-section--models" aria-labelledby="settings-models-title">
                    <div className="settings-section__heading settings-section__heading--tabs">
                      <h2 id="settings-models-title">{text.models}</h2>
                      <div className="settings-tabs" role="tablist">
                        <button type="button" role="tab" aria-selected={modelSection === 'chat'} className={modelSection === 'chat' ? 'is-active' : ''} onClick={() => setModelSection('chat')}>{text.chat}</button>
                        <button type="button" role="tab" aria-selected={modelSection === 'embedding'} className={modelSection === 'embedding' ? 'is-active' : ''} onClick={() => setModelSection('embedding')}>{text.embedding}</button>
                      </div>
                    </div>

                    {modelSection === 'chat' ? (
                      <div className="settings-model-grid" role="tabpanel">
                        <label><span>{text.provider}</span><select value={modelDraft.chat.provider} onChange={(event) => {
                          const provider = providerById(modelConfig.providers.chat, event.target.value)
                          if (!provider) return
                          setModelDraft((current) => current ? { ...current, chat: { ...current.chat, provider: provider.id, model: provider.default_model, base_url: '', enable_thinking: false } } : current)
                          setTestResults((current) => ({ ...current, chat: undefined }))
                        }}>{modelConfig.providers.chat.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></label>
                        <label><span>{text.model}</span><select value={modelDraft.chat.model} onChange={(event) => {
                          setModelDraft((current) => current ? { ...current, chat: { ...current.chat, model: event.target.value, enable_thinking: false } } : current)
                          setTestResults((current) => ({ ...current, chat: undefined }))
                        }}>{chatProvider?.models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}</select></label>
                        <label className="settings-model-grid__wide"><span>{text.apiKey}</span><input type="password" value={modelDraft.chat.api_key} disabled={modelDraft.chat.clear_api_key} placeholder={modelDraft.chat.has_api_key ? '••••••••••••' : ''} onChange={(event) => setModelDraft((current) => current ? { ...current, chat: { ...current.chat, api_key: event.target.value } } : current)} /><small>{modelDraft.chat.has_api_key ? text.apiKeyStored : text.apiKeyMissing}</small></label>
                        {modelDraft.chat.has_api_key ? <Toggle label={text.clearApiKey} checked={modelDraft.chat.clear_api_key} onChange={(value) => setModelDraft((current) => current ? { ...current, chat: { ...current.chat, clear_api_key: value, api_key: '' } } : current)} /> : null}
                        <label className="settings-model-grid__wide"><span>{text.baseUrl}</span><input type="url" value={modelDraft.chat.base_url} placeholder={chatProvider?.default_base_url || text.providerDefault} onChange={(event) => setModelDraft((current) => current ? { ...current, chat: { ...current.chat, base_url: event.target.value } } : current)} /></label>
                        <label><span>{text.timeout}</span><input type="number" min="1" max="600" value={modelDraft.chat.timeout} onChange={(event) => setModelDraft((current) => current ? { ...current, chat: { ...current.chat, timeout: Number(event.target.value) } } : current)} /></label>
                        <Toggle label={text.streaming} checked={modelDraft.chat.streaming} onChange={(value) => setModelDraft((current) => current ? { ...current, chat: { ...current.chat, streaming: value } } : current)} />
                        <Toggle label={text.thinking} checked={modelDraft.chat.enable_thinking} disabled={!chatProvider?.models.find((model) => model.id === modelDraft.chat.model)?.supports_thinking} onChange={(value) => setModelDraft((current) => current ? { ...current, chat: { ...current.chat, enable_thinking: value } } : current)} />
                        {modelDraft.chat.enable_thinking ? <label><span>{text.thinkingTimeout}</span><input type="number" min="1" max="3600" value={modelDraft.chat.thinking_timeout} onChange={(event) => setModelDraft((current) => current ? { ...current, chat: { ...current.chat, thinking_timeout: Number(event.target.value) } } : current)} /></label> : null}
                      </div>
                    ) : (
                      <div className="settings-model-grid" role="tabpanel">
                        <label><span>{text.provider}</span><select value={modelDraft.embedding.provider} onChange={(event) => {
                          const provider = providerById(modelConfig.providers.embedding, event.target.value)
                          if (!provider) return
                          setModelDraft((current) => current ? { ...current, embedding: { ...current.embedding, provider: provider.id, model: provider.default_model, base_url: '' } } : current)
                          setTestResults((current) => ({ ...current, embedding: undefined }))
                        }}>{modelConfig.providers.embedding.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></label>
                        <label><span>{text.model}</span><select value={modelDraft.embedding.model} onChange={(event) => {
                          setModelDraft((current) => current ? { ...current, embedding: { ...current.embedding, model: event.target.value } } : current)
                          setTestResults((current) => ({ ...current, embedding: undefined }))
                        }}>{embeddingProvider?.models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}</select></label>
                        <label className="settings-model-grid__wide"><span>{text.apiKey}</span><input type="password" value={modelDraft.embedding.api_key} disabled={modelDraft.embedding.clear_api_key} placeholder={modelDraft.embedding.has_api_key ? '••••••••••••' : ''} onChange={(event) => setModelDraft((current) => current ? { ...current, embedding: { ...current.embedding, api_key: event.target.value } } : current)} /><small>{modelDraft.embedding.has_api_key ? text.apiKeyStored : text.apiKeyMissing}</small></label>
                        {modelDraft.embedding.has_api_key ? <Toggle label={text.clearApiKey} checked={modelDraft.embedding.clear_api_key} onChange={(value) => setModelDraft((current) => current ? { ...current, embedding: { ...current.embedding, clear_api_key: value, api_key: '' } } : current)} /> : null}
                        <label className="settings-model-grid__wide"><span>{text.baseUrl}</span><input type="url" value={modelDraft.embedding.base_url} placeholder={embeddingProvider?.default_base_url || text.providerDefault} onChange={(event) => setModelDraft((current) => current ? { ...current, embedding: { ...current.embedding, base_url: event.target.value } } : current)} /></label>
                        <label><span>{text.timeout}</span><input type="number" min="1" max="600" value={modelDraft.embedding.timeout} onChange={(event) => setModelDraft((current) => current ? { ...current, embedding: { ...current.embedding, timeout: Number(event.target.value) } } : current)} /></label>
                        <label><span>{text.batchSize}</span><input type="number" min="1" max="256" value={modelDraft.embedding.batch_size} onChange={(event) => setModelDraft((current) => current ? { ...current, embedding: { ...current.embedding, batch_size: Number(event.target.value) } } : current)} /></label>
                      </div>
                    )}
                    <footer className="settings-actions settings-actions--split">
                      <div className={`settings-verification settings-verification--${testResults[modelSection]?.status ?? 'idle'}`}>
                        {testResults[modelSection]?.message || text.notVerified}
                      </div>
                      <div>
                        <button type="button" className="settings-button settings-button--secondary" disabled={Boolean(testing) || savingModels} onClick={() => void testConnection(modelSection)}>{testing === modelSection ? text.testing : text.test}</button>
                        <button type="button" className="settings-button settings-button--primary" disabled={Boolean(testing) || savingModels} onClick={() => void saveModelConfig()}>{savingModels ? text.saving : text.save}</button>
                      </div>
                    </footer>
                  </section>
                ) : null}

                {section === 'about' && about ? (
                  <section className="settings-section settings-about" aria-labelledby="settings-about-title">
                    <div className="settings-about__mark" aria-hidden="true">CA</div>
                    <div className="settings-about__body">
                      <h2 id="settings-about-title">{about.name}</h2>
                      <p>{text.description}</p>
                      <dl>
                        <div><dt>{text.version}</dt><dd>{about.version}</dd></div>
                        <div><dt>{text.apiVersion}</dt><dd>{about.api_version}</dd></div>
                        <div><dt>{text.backendRuntime}</dt><dd>Python {about.python_version}</dd></div>
                        <div><dt>{text.desktopRuntime}</dt><dd>{about.platform}</dd></div>
                      </dl>
                      <small>{text.licenses}</small>
                    </div>
                  </section>
                ) : null}
              </>
            ) : null}
          </main>
        </div>
      </div>
    </div>
  )
}
