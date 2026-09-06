import { useEffect, useState } from 'react'
import { formatEngineering } from './simulationModel'
import type { AcceptanceConstraint, AcceptanceResult } from './types'

type ConstraintConditions = NonNullable<AcceptanceConstraint['conditions']>

function optionalNumber(text: string): number | null {
  return text.trim() === '' ? null : Number(text)
}

function NumericInput({label, value, onChange, placeholder}: {
  label: string
  value: number | null | undefined
  onChange(value: number | null): void
  placeholder?: string
}) {
  const [text, setText] = useState(value == null ? '' : String(value))
  useEffect(() => {
    setText((current) => Object.is(optionalNumber(current), value ?? null) ? current : value == null ? '' : String(value))
  }, [value])
  const invalid = text.trim() !== '' && !Number.isFinite(optionalNumber(text))
  return <label className="simulation-field"><span>{label}</span><input
    inputMode="decimal"
    value={text}
    placeholder={placeholder}
    aria-invalid={invalid || undefined}
    onChange={(event) => {
      setText(event.target.value)
      onChange(optionalNumber(event.target.value))
    }}
  />{invalid ? <small className="simulation-text-error">Enter a finite number, for example 0.01 or 1e-3.</small> : null}</label>
}

function ConditionsEditor({conditions, onChange}: {
  conditions: ConstraintConditions | undefined
  onChange(value: ConstraintConditions): void
}) {
  const [nameError, setNameError] = useState('')
  const parameters = Object.entries(conditions?.parameters ?? {})
  const updateParameter = (index: number, name: string, value: string | number) => {
    if (parameters.some(([otherName], otherIndex) => otherIndex !== index && otherName === name)) {
      setNameError(`A parameter condition named "${name || '(blank)'}" already exists. Use a unique name.`)
      return
    }
    setNameError('')
    onChange({...conditions, parameters: Object.fromEntries(parameters.map((entry, rowIndex) => rowIndex === index ? [name, value] : entry))})
  }
  return <div className="simulation-panel-stack simulation-field--wide">
    <div className="simulation-section-heading"><strong>Applies at these operating conditions</strong><button type="button" disabled={parameters.some(([name]) => name === '')} onClick={() => {
      setNameError('')
      onChange({...conditions, parameters: {...conditions?.parameters, '': ''}})
    }}>Add parameter condition</button></div>
    <NumericInput label="Temperature condition (°C)" value={conditions?.temperature} placeholder="Any temperature" onChange={(temperature) => onChange({...conditions, temperature})} />
    {parameters.map(([name, value], index) => <div className="simulation-experiment-grid" key={index}>
      <label className="simulation-field"><span>Parameter name</span><input aria-label={`Condition parameter ${index + 1} name`} value={name} placeholder="VDD or Rload" aria-invalid={!name.trim() || undefined} onChange={(event) => updateParameter(index, event.target.value, value)} /></label>
      <label className="simulation-field"><span>Required value</span><input aria-label={`Condition parameter ${index + 1} value`} value={value} placeholder="3.3 or 10k" aria-invalid={String(value).trim() === '' || undefined} onChange={(event) => updateParameter(index, name, event.target.value)} /></label>
      <div className="simulation-button-row simulation-field--wide"><button type="button" onClick={() => {
        setNameError('')
        onChange({...conditions, parameters: Object.fromEntries(parameters.filter((_, rowIndex) => rowIndex !== index))})
      }}>Remove parameter condition</button></div>
    </div>)}
    {nameError ? <div className="simulation-inline-error" role="alert">{nameError}</div> : null}
    <small>Conditions select where this criterion applies. They do not change the experiment inputs. Leave them empty to apply to every case.</small>
  </div>
}

export function AcceptanceEditor({constraints, onChange}: {
  constraints: AcceptanceConstraint[]
  onChange(value: AcceptanceConstraint[]): void
}) {
  const update = (index: number, patch: Partial<AcceptanceConstraint>) => onChange(constraints.map((row, rowIndex) => rowIndex === index ? {...row, ...patch} : row))
  return <section className="simulation-card" aria-label="Acceptance constraints">
    <div className="simulation-card__header"><div><h2>Acceptance constraints</h2><p>Each run saves its own criteria. Failed or missing measurements remain NOT_MEASURED.</p></div><button type="button" onClick={() => onChange([...constraints, {id: crypto.randomUUID(), source: 'measurement', metric: '', unit: '', lower: null, upper: null}])}>Add criterion</button></div>
    {!constraints.length ? <div className="simulation-empty">No acceptance constraints. This run will not receive a PASS verdict.</div> : <div className="simulation-panel-stack">{constraints.map((constraint, index) => {
      const noBounds = constraint.lower == null && constraint.upper == null
      const reversed = constraint.lower != null && constraint.upper != null && constraint.lower > constraint.upper
      return <section key={constraint.id ?? index} aria-label={`Acceptance criterion ${index + 1}`}>
        <div className="simulation-section-heading"><strong>Criterion {index + 1}</strong><button type="button" onClick={() => onChange(constraints.filter((_, rowIndex) => rowIndex !== index))}>Remove criterion</button></div>
        <div className="simulation-experiment-grid">
          <label className="simulation-field"><span>Metric source</span><select value={constraint.source ?? 'measurement'} onChange={(event) => update(index, {source: event.target.value as AcceptanceConstraint['source']})}><option value="measurement">SPICE .measure</option><option value="op_signal">Operating-point signal</option></select></label>
          <label className="simulation-field"><span>Metric name</span><input value={constraint.metric} placeholder={constraint.source === 'op_signal' ? 'v(out)' : 'gain or settling_time'} aria-invalid={!constraint.metric.trim() || undefined} onChange={(event) => update(index, {metric: event.target.value})} /></label>
          <label className="simulation-field simulation-field--wide"><span>Unit <small>Required; use 1 for dimensionless values. Limits use this unit.</small></span><input value={constraint.unit} placeholder="V, A, s, Hz, dB, or 1" aria-invalid={!constraint.unit.trim() || undefined} onChange={(event) => update(index, {unit: event.target.value})} /></label>
          <NumericInput label="Lower limit (inclusive)" value={constraint.lower} placeholder="No lower limit" onChange={(lower) => update(index, {lower})} />
          <NumericInput label="Upper limit (inclusive)" value={constraint.upper} placeholder="No upper limit" onChange={(upper) => update(index, {upper})} />
          {noBounds || reversed ? <div className="simulation-text-error simulation-field--wide" role="status">{noBounds ? 'Set at least one limit. Empty limits are not zero.' : 'The lower limit must not exceed the upper limit.'}</div> : null}
          <ConditionsEditor conditions={constraint.conditions} onChange={(conditions) => update(index, {conditions})} />
        </div>
      </section>
    })}</div>}
  </section>
}

function conditionText(conditions: AcceptanceConstraint['conditions']): string {
  const values = Object.entries(conditions?.parameters ?? {}).map(([name, value]) => `${name} = ${value}`)
  if (conditions?.temperature != null) values.push(`Temperature = ${conditions.temperature} °C`)
  return values.join(' · ') || 'All conditions'
}

function limitsText(row: AcceptanceConstraint): string {
  const lower = row.lower == null ? null : formatEngineering(row.lower, row.unit)
  const upper = row.upper == null ? null : formatEngineering(row.upper, row.unit)
  if (lower !== null && upper !== null) return `${lower} ≤ value ≤ ${upper}`
  if (lower !== null) return `value ≥ ${lower}`
  if (upper !== null) return `value ≤ ${upper}`
  return 'No limits recorded'
}

function Verdict({status}: {status: AcceptanceResult['status']}) {
  const className = status === 'PASS' ? 'simulation-result-outcome simulation-result-outcome--success' : status === 'FAIL' ? 'simulation-result-outcome simulation-result-outcome--error' : 'simulation-result-outcome'
  return <span className={className}>{status}</span>
}

export function AcceptanceResults({acceptance}: {acceptance?: AcceptanceResult | null}) {
  return <section className="simulation-card" aria-label="Saved acceptance results">
    <div className="simulation-card__header"><div><h2>Acceptance results</h2><p>Verdicts use the criteria and operating conditions saved with this result.</p></div>{acceptance?.rows.length ? <Verdict status={acceptance.status} /> : null}</div>
    {!acceptance?.rows.length ? <div className="simulation-empty">No acceptance constraints were recorded for this result. No PASS verdict is assigned.</div> : <>
      <div className="simulation-section-heading"><span>PASS {acceptance.counts.PASS ?? 0} · FAIL {acceptance.counts.FAIL ?? 0} · NOT_MEASURED {acceptance.counts.NOT_MEASURED ?? 0}</span></div>
      <div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Metric / source</th><th>Verdict</th><th>Measured value</th><th>Saved limits</th><th>Saved conditions</th><th>Margin</th><th>Reason</th></tr></thead><tbody>{acceptance.rows.map((row, index) => <tr key={row.id ?? index}>
        <td><strong>{row.metric}</strong><small>{row.source === 'op_signal' ? 'Operating-point signal' : 'SPICE .measure'}</small></td>
        <td><Verdict status={row.status} /></td>
        <td>{row.value == null ? 'Not measured' : formatEngineering(row.value, row.observed_unit)}</td>
        <td>{limitsText(row)}</td>
        <td>{conditionText(row.conditions)}</td>
        <td>{row.margin == null ? '—' : formatEngineering(row.margin, row.unit)}</td>
        <td>{row.reason || '—'}</td>
      </tr>)}</tbody></table></div>
    </>}
  </section>
}
