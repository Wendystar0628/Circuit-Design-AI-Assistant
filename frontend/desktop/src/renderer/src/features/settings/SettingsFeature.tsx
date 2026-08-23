import { useEffect, useState } from 'react'

import { api } from '../../lib/api'
import { ModelSettingsPanel } from './ModelSettingsPanel'
import './settings.css'
import type {
  AboutInfo,
  ModelConfig,
  Preferences,
  SettingsFeatureProps,
  SettingsSection,
} from './types'
import { defaultPreferences } from './types'
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
    loadingAbout: 'Loading application information…',
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
    loadingAbout: '正在加载应用信息…',
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

export function SettingsFeature({ active, onClose, initialSection = 'general' }: SettingsFeatureProps) {
  const [section, setSection] = useState<SettingsSection>(initialSection)
  const [preferences, setPreferences] = useState<Preferences>(defaultPreferences)
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null)
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingAbout, setLoadingAbout] = useState(false)
  const [savingPreferences, setSavingPreferences] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [aboutError, setAboutError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const language = preferences.language in copy ? preferences.language : 'en_US'
  const text = copy[language]
  const dialogRef = useDialogFocus(active, onClose)

  const loadAbout = async () => {
    setLoadingAbout(true)
    setAboutError('')
    try {
      setAbout(await api.get<AboutInfo>(`${API_ROOT}/about`))
    } catch (loadAboutError) {
      setAbout(null)
      setAboutError(errorMessage(loadAboutError))
    } finally {
      setLoadingAbout(false)
    }
  }

  const load = async () => {
    setLoading(true)
    setLoadError('')
    setError('')
    setNotice('')
    void loadAbout()
    try {
      const [nextPreferences, nextModelConfig] = await Promise.all([
        api.get<Preferences>(`${API_ROOT}/preferences`),
        api.get<ModelConfig>(`${API_ROOT}/model-config`),
      ])
      setPreferences(nextPreferences)
      document.documentElement.dataset.theme = nextPreferences.theme
      setModelConfig(nextModelConfig)
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

                {section === 'models' && modelConfig ? (
                  <ModelSettingsPanel
                    config={modelConfig}
                    language={language}
                    onConfigChange={setModelConfig}
                  />
                ) : null}

                {section === 'about' ? (
                  loadingAbout ? (
                    <LoadingState label={text.loadingAbout} />
                  ) : aboutError ? (
                    <ErrorState message={aboutError} retry={() => void loadAbout()} label={text.retry} />
                  ) : about ? (
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
                  ) : null
                ) : null}
              </>
            ) : null}
          </main>
        </div>
      </div>
    </div>
  )
}
