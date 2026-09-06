import type { CapturedModel, ModelBinding } from './types'

type RangeKey = 'voltage_range' | 'frequency_range' | 'temperature_range'
type ModelRange = { min: number | null; max: number | null }

const ranges: Array<{ key: RangeKey; label: string; unit: string }> = [
  { key: 'voltage_range', label: 'Applicable voltage', unit: 'V' },
  { key: 'frequency_range', label: 'Applicable frequency', unit: 'Hz' },
  { key: 'temperature_range', label: 'Applicable temperature', unit: '°C' },
]

function rangeIsInvalid(range: ModelRange | null | undefined): boolean {
  return range?.min != null && range.max != null && range.min > range.max
}

function formatRange(range: ModelRange | null | undefined, unit: string): string {
  if (range?.min == null && range?.max == null) return 'Unknown / not declared'
  return `${range?.min ?? 'Unknown'} to ${range?.max ?? 'Unknown'} ${unit}`
}

function declared(value: string | null | undefined): string {
  return value?.trim() || 'Unknown / not declared'
}

export function ModelBindingsEditor({ bindings, onChange }: {
  bindings: ModelBinding[]
  onChange: (bindings: ModelBinding[]) => void
}) {
  const updateBinding = (index: number, patch: Partial<ModelBinding>) => {
    onChange(bindings.map((binding, itemIndex) => itemIndex === index ? { ...binding, ...patch } : binding))
  }

  return <section className="simulation-card">
    <div className="simulation-card__header">
      <div>
        <h2>Model metadata</h2>
        <p>Bind declared sources, versions and operating limits to a model or subcircuit name. These declarations are saved with each experiment.</p>
      </div>
      <button type="button" onClick={() => onChange([...bindings, { name: '', kind: 'model', simplified: null }])}>Add model metadata</button>
    </div>
    {!bindings.length ? <div className="simulation-empty">No metadata declared. Model definitions can still be captured, with unknown applicability shown explicitly.</div> : null}
    {bindings.map((binding, index) => <div key={index}>
      <div className="simulation-card__header">
        <strong>Model {index + 1}{binding.name ? ` · ${binding.name}` : ''}</strong>
        <button type="button" aria-label={`Remove model metadata ${index + 1}`} onClick={() => onChange(bindings.filter((_, itemIndex) => itemIndex !== index))}>Remove</button>
      </div>
      <div className="simulation-experiment-grid">
        <label className="simulation-field">
          <span>Definition name</span>
          <input value={binding.name} required placeholder="e.g. LM358" onChange={(event) => updateBinding(index, { name: event.target.value })} />
          <small>Use the exact .model or .subckt definition name.</small>
        </label>
        <label className="simulation-field">
          <span>Definition kind</span>
          <select value={binding.kind} onChange={(event) => updateBinding(index, { kind: event.target.value as ModelBinding['kind'] })}>
            <option value="model">.model</option>
            <option value="subcircuit">.subckt</option>
          </select>
        </label>
        <label className="simulation-field">
          <span>Source file ID (optional)</span>
          <input value={binding.source_id ?? ''} placeholder="Unknown / not declared" onChange={(event) => updateBinding(index, { source_id: event.target.value || undefined })} />
          <small>Use the captured source ID to distinguish definitions with the same name.</small>
        </label>
        <label className="simulation-field">
          <span>Model source (user declared)</span>
          <input value={binding.source ?? ''} placeholder="Vendor, publication or source URL" onChange={(event) => updateBinding(index, { source: event.target.value || undefined })} />
        </label>
        <label className="simulation-field">
          <span>Model version (user declared)</span>
          <input value={binding.version ?? ''} placeholder="Unknown / not declared" onChange={(event) => updateBinding(index, { version: event.target.value || undefined })} />
        </label>
        <label className="simulation-field">
          <span>Simplified model</span>
          <select value={binding.simplified == null ? 'unknown' : String(binding.simplified)} onChange={(event) => updateBinding(index, { simplified: event.target.value === 'unknown' ? null : event.target.value === 'true' })}>
            <option value="unknown">Unknown / not declared</option>
            <option value="true">Yes — simplified</option>
            <option value="false">No — declared not simplified</option>
          </select>
        </label>
        {ranges.map(({ key, label, unit }) => {
          const range = binding[key]
          const invalid = rangeIsInvalid(range)
          return <div className="simulation-field simulation-field--wide" key={key}>
            <span>{label} ({unit}, user declared)</span>
            <div className="simulation-button-row">
              {(['min', 'max'] as const).map((bound) => <label className="simulation-field" key={bound}>
                <span>{bound === 'min' ? 'Minimum' : 'Maximum'} ({unit})</span>
                <input type="number" step="any" value={range?.[bound] ?? ''} placeholder="Unknown" aria-invalid={invalid || undefined}
                  onChange={(event) => {
                    const value = event.target.value === '' ? null : event.target.valueAsNumber
                    if (value !== null && !Number.isFinite(value)) return
                    updateBinding(index, { [key]: { min: range?.min ?? null, max: range?.max ?? null, [bound]: value } })
                  }} />
              </label>)}
            </div>
            {invalid ? <small className="simulation-text-error" role="alert">Minimum must not exceed maximum. Correct this range before running.</small> : <small>Blank means unknown; zero is a declared value.</small>}
          </div>
        })}
        <label className="simulation-field simulation-field--wide">
          <span>Assumptions (user declared, one per line)</span>
          <textarea rows={3} value={(binding.assumptions ?? []).join('\n')} placeholder="Unknown / not declared" onChange={(event) => updateBinding(index, { assumptions: event.target.value.split('\n') })} />
        </label>
      </div>
    </div>)}
  </section>
}

export function CapturedModels({ models }: { models: CapturedModel[] }) {
  return <section className="simulation-card">
    <div className="simulation-card__header">
      <div>
        <h2>Captured model definitions</h2>
        <p>Definition identities and file digests identify this result’s saved inputs. Applicability and assumptions retain their recorded origin; they are not independently verified guarantees.</p>
      </div>
    </div>
    {!models.length ? <div className="simulation-empty">No captured model records available for this result.</div> : null}
    {models.map((model, index) => {
      const status = model.binding_status || 'Unknown / not recorded'
      const mismatch = /mismatch|unmatched|ambiguous|not.found|unresolved/i.test(status)
      const assumptions = (model.assumptions ?? []).filter((item) => item.trim())
      const metadataLabel = model.metadata_origin === 'user_declared' ? 'user declared' : model.metadata_origin === 'bundled_source' ? 'bundled source' : 'origin unspecified'
      return <details key={`${model.identity ?? model.name}-${index}`} open={mismatch}>
        <summary className="simulation-card__header">
          <strong>{model.kind === 'subcircuit' ? '.subckt' : '.model'} {model.name || 'Unknown name'}</strong>
          <span className={mismatch ? 'simulation-text-error' : undefined}>Binding: {status === 'none' ? 'none — no metadata binding' : status}</span>
        </summary>
        {mismatch ? <div className="simulation-inline-error" role="alert">Metadata binding requires attention ({status}). Do not treat this declaration as verified metadata for the captured definition.</div> : null}
        <dl className="simulation-detail-grid">
          <div><dt>Captured identity</dt><dd><code>{model.identity ?? 'Unknown / not recorded'}</code></dd></div>
          <div><dt>Captured source ID</dt><dd><code>{declared(model.source_id)}</code></dd></div>
          <div><dt>Definition file and line</dt><dd><code>{model.source_path || 'Unknown / not recorded'}{model.line_number != null ? `:${model.line_number}` : ' (line unknown)'}</code></dd></div>
          <div><dt>Library section</dt><dd>{declared(model.library_section)}</dd></div>
          <div><dt>Definition digest</dt><dd><code>{model.definition_digest ?? 'Unknown / not recorded'}</code></dd></div>
          <div><dt>File digest</dt><dd><code>{model.file_digest ?? 'Unknown / not recorded'}</code></dd></div>
          <div><dt>Metadata origin</dt><dd>{model.metadata_origin === 'unspecified' || !model.metadata_origin ? 'Unknown / not recorded' : metadataLabel}</dd></div>
          <div><dt>Source ({metadataLabel})</dt><dd>{declared(model.source)}</dd></div>
          <div><dt>Version ({metadataLabel})</dt><dd>{declared(model.version)}</dd></div>
          <div><dt>Simplified model ({metadataLabel})</dt><dd>{model.simplified == null ? 'Unknown / not declared' : model.simplified ? 'Yes — simplified' : 'No — declared not simplified'}</dd></div>
          {ranges.map(({ key, label, unit }) => <div key={key}><dt>{label} ({metadataLabel})</dt><dd>{formatRange(model[key], unit)}</dd></div>)}
          <div><dt>Assumptions ({metadataLabel})</dt><dd>{assumptions.length ? assumptions.map((assumption, assumptionIndex) => <div key={assumptionIndex}>{assumption}</div>) : 'Unknown / not declared'}</dd></div>
        </dl>
      </details>
    })}
  </section>
}
