import type { ChangeEvent } from 'react'
import type { ModelConfigBridge } from './modelConfigBridge'
import type { ModelConfigState } from './modelConfigTypes'

interface ModelConfigAppProps {
  state: ModelConfigState
  bridgeConnected: boolean
  bridge: ModelConfigBridge | null
}

function FieldLabel({ children }: { children: string }) {
  return <label className="model-config-field__label">{children}</label>
}

function TextInput(props: {
  label: string
  value: string
  placeholder?: string
  type?: string
  onChange: (nextValue: string) => void
}) {
  return (
    <input
      className="model-config-input"
      type={props.type ?? 'text'}
      value={props.value}
      placeholder={props.placeholder ?? ''}
      aria-label={props.label}
      title={props.label}
      onChange={(event) => props.onChange(event.target.value)}
    />
  )
}

function NumberInput(props: {
  label: string
  value: number
  min?: number
  max?: number
  onChange: (nextValue: number) => void
}) {
  return (
    <input
      className="model-config-input"
      type="number"
      value={Number.isFinite(props.value) ? props.value : 0}
      min={props.min}
      max={props.max}
      aria-label={props.label}
      title={props.label}
      onChange={(event) => props.onChange(Number(event.target.value || 0))}
    />
  )
}

function SelectInput(props: {
  label: string
  value: string
  options: Array<{ value: string; label: string }>
  onChange: (nextValue: string) => void
}) {
  return (
    <select
      className="model-config-select"
      value={props.value}
      aria-label={props.label}
      title={props.label}
      onChange={(event) => props.onChange(event.target.value)}
    >
      {props.options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

function ToggleInput(props: {
  checked: boolean
  disabled?: boolean
  onChange: (nextValue: boolean) => void
  label: string
}) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    props.onChange(event.target.checked)
  }

  return (
    <label className={`model-config-toggle${props.disabled ? ' model-config-toggle--disabled' : ''}`}>
      <input type="checkbox" checked={props.checked} disabled={props.disabled} onChange={handleChange} />
      <span className="model-config-toggle__track" />
      <span className="model-config-toggle__label">{props.label}</span>
    </label>
  )
}

function StatusBadge({ state, text }: ModelConfigState['dialog']['status']) {
  return <div className={`model-config-status model-config-status--${state}`}>{text}</div>
}

export function ModelConfigApp({ state, bridgeConnected, bridge }: ModelConfigAppProps) {
  const sendDraft = (section: 'chat' | 'embedding', field: string, value: unknown) => {
    bridge?.updateDraft?.(section, field, value)
  }

  return (
    <div className="model-config-shell">
      <div className="model-config-card">
        <div className="model-config-header">
          <div>
            <h1 className="model-config-title">{state.dialog.title}</h1>
            <p className="model-config-subtitle">
              {bridgeConnected ? '' : state.dialog.messages.bridgeUnavailable}
            </p>
          </div>
          <StatusBadge {...state.dialog.status} />
        </div>

        <div className="model-config-tabs" aria-label={state.dialog.title}>
          {state.dialog.tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`model-config-tab${state.dialog.activeTab === tab.id ? ' model-config-tab--active' : ''}`}
              onClick={() => bridge?.selectTab?.(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {state.dialog.activeTab === 'chat' ? (
          <div className="model-config-section">
            <div className="model-config-grid">
              <div className="model-config-field">
                <FieldLabel>{state.chat.labels.provider}</FieldLabel>
                <SelectInput
                  label={state.chat.labels.provider}
                  value={state.chat.provider}
                  options={state.chat.providerOptions}
                  onChange={(value) => sendDraft('chat', 'provider', value)}
                />
              </div>
              <div className="model-config-field">
                <FieldLabel>{state.chat.labels.model}</FieldLabel>
                <SelectInput
                  label={state.chat.labels.model}
                  value={state.chat.model}
                  options={state.chat.modelOptions}
                  onChange={(value) => sendDraft('chat', 'model', value)}
                />
              </div>
              <div className="model-config-field model-config-field--full">
                <FieldLabel>{state.chat.labels.apiKey}</FieldLabel>
                <TextInput
                  label={state.chat.labels.apiKey}
                  type="password"
                  value={state.chat.apiKey}
                  onChange={(value) => sendDraft('chat', 'apiKey', value)}
                />
              </div>
              <div className="model-config-field model-config-field--full">
                <FieldLabel>{state.chat.labels.baseUrl}</FieldLabel>
                <TextInput
                  label={state.chat.labels.baseUrl}
                  value={state.chat.baseUrl}
                  placeholder={state.chat.baseUrlPlaceholder}
                  onChange={(value) => sendDraft('chat', 'baseUrl', value)}
                />
              </div>
              <div className="model-config-field">
                <FieldLabel>{state.chat.labels.timeout}</FieldLabel>
                <NumberInput
                  label={state.chat.labels.timeout}
                  min={5}
                  max={300}
                  value={state.chat.timeout}
                  onChange={(value) => sendDraft('chat', 'timeout', value)}
                />
              </div>
              <div className="model-config-field model-config-field--toggle">
                <FieldLabel>{state.chat.labels.streaming}</FieldLabel>
                <ToggleInput
                  checked={state.chat.streaming}
                  onChange={(value) => sendDraft('chat', 'streaming', value)}
                  label={state.chat.streaming ? state.chat.labels.enabled : state.chat.labels.disabled}
                />
              </div>
            </div>

            <div className="model-config-subcard">
              <div className="model-config-subcard__title">{state.chat.labels.featuresTitle}</div>
              <div className="model-config-grid">
                <div className="model-config-field model-config-field--toggle">
                  <FieldLabel>{state.chat.labels.enableThinking}</FieldLabel>
                  <ToggleInput
                    checked={state.chat.enableThinking}
                    disabled={!state.chat.supportsThinking}
                    onChange={(value) => sendDraft('chat', 'enableThinking', value)}
                    label={state.chat.supportsThinking ? (state.chat.enableThinking ? state.chat.labels.enabled : state.chat.labels.disabled) : state.chat.labels.notSupported}
                  />
                </div>
                <div className="model-config-field">
                  <FieldLabel>{state.chat.labels.thinkingTimeout}</FieldLabel>
                  <NumberInput
                    label={state.chat.labels.thinkingTimeout}
                    min={5}
                    max={600}
                    value={state.chat.thinkingTimeout}
                    onChange={(value) => sendDraft('chat', 'thinkingTimeout', value)}
                  />
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="model-config-section">
            <div className="model-config-grid">
              <div className="model-config-field">
                <FieldLabel>{state.embedding.labels.provider}</FieldLabel>
                <SelectInput
                  label={state.embedding.labels.provider}
                  value={state.embedding.provider}
                  options={state.embedding.providerOptions}
                  onChange={(value) => sendDraft('embedding', 'provider', value)}
                />
              </div>
              <div className="model-config-field">
                <FieldLabel>{state.embedding.labels.model}</FieldLabel>
                <SelectInput
                  label={state.embedding.labels.model}
                  value={state.embedding.model}
                  options={state.embedding.modelOptions}
                  onChange={(value) => sendDraft('embedding', 'model', value)}
                />
              </div>
              <div className="model-config-field model-config-field--full">
                <FieldLabel>{state.embedding.labels.apiKey}</FieldLabel>
                <TextInput
                  label={state.embedding.labels.apiKey}
                  type="password"
                  value={state.embedding.apiKey}
                  onChange={(value) => sendDraft('embedding', 'apiKey', value)}
                />
              </div>
              <div className="model-config-field model-config-field--full">
                <FieldLabel>{state.embedding.labels.baseUrl}</FieldLabel>
                <TextInput
                  label={state.embedding.labels.baseUrl}
                  value={state.embedding.baseUrl}
                  placeholder={state.embedding.baseUrlPlaceholder}
                  onChange={(value) => sendDraft('embedding', 'baseUrl', value)}
                />
              </div>
              <div className="model-config-field">
                <FieldLabel>{state.embedding.labels.timeout}</FieldLabel>
                <NumberInput
                  label={state.embedding.labels.timeout}
                  min={5}
                  max={300}
                  value={state.embedding.timeout}
                  onChange={(value) => sendDraft('embedding', 'timeout', value)}
                />
              </div>
              <div className="model-config-field">
                <FieldLabel>{state.embedding.labels.batchSize}</FieldLabel>
                <NumberInput
                  label={state.embedding.labels.batchSize}
                  min={1}
                  max={256}
                  value={state.embedding.batchSize}
                  onChange={(value) => sendDraft('embedding', 'batchSize', value)}
                />
              </div>
            </div>
          </div>
        )}

        <div className="model-config-actions">
          <button
            type="button"
            className="model-config-button model-config-button--secondary"
            onClick={() => bridge?.requestTestConnection?.()}
            disabled={state.dialog.status.state === 'testing'}
          >
            {state.dialog.actions.test}
          </button>
          <button
            type="button"
            className="model-config-button model-config-button--ghost"
            onClick={() => bridge?.requestCancel?.()}
          >
            {state.dialog.actions.cancel}
          </button>
          <button
            type="button"
            className="model-config-button model-config-button--primary"
            onClick={() => bridge?.requestSave?.()}
          >
            {state.dialog.actions.save}
          </button>
        </div>
      </div>

      {state.confirmDialog.open ? (
        <div className="model-config-overlay">
          <div className="model-config-modal">
            <div className="model-config-modal__title">{state.confirmDialog.title}</div>
            <div className="model-config-modal__message">{state.confirmDialog.message}</div>
            <div className="model-config-modal__actions">
              <button
                type="button"
                className="model-config-button model-config-button--ghost"
                onClick={() => bridge?.resolveConfirmDialog?.(false)}
              >
                {state.confirmDialog.cancelText}
              </button>
              <button
                type="button"
                className="model-config-button model-config-button--primary"
                onClick={() => bridge?.resolveConfirmDialog?.(true)}
              >
                {state.confirmDialog.confirmText}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {state.noticeDialog.open ? (
        <div className="model-config-overlay">
          <div className={`model-config-modal model-config-modal--${state.noticeDialog.level}`}>
            <div className="model-config-modal__title">{state.noticeDialog.title}</div>
            <div className="model-config-modal__message">{state.noticeDialog.message}</div>
            <div className="model-config-modal__actions">
              <button
                type="button"
                className="model-config-button model-config-button--primary"
                onClick={() => bridge?.closeNoticeDialog?.()}
              >
                {state.noticeDialog.closeText}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
