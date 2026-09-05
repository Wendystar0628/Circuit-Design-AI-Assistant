import { useMemo, useState } from 'react'
import type { SchematicComponentDto, SchematicDocumentDto, SchematicNetDto } from './types'

type Selection = { kind: 'net' | 'component'; id: string }

const scopeKey = (scope: string[]) => JSON.stringify(scope)
const scopeLabel = (scope: string[]) => scope.length ? scope.join(' / ') : 'Top level'
const pinKey = (componentId: string, pinName: string) => JSON.stringify([componentId, pinName])

/** Connectivity comes from the result snapshot, never from matching node labels. */
export function indexTopology(schematic: SchematicDocumentDto) {
  const components = new Map(schematic.components.map((component) => [component.id, component]))
  const nets = new Map(schematic.nets.map((net) => [net.id, net]))
  const pinNets = new Map<string, SchematicNetDto>()
  const scopes = new Map<string, string[]>()
  scopes.set(scopeKey([]), [])
  for (const item of [...schematic.components, ...schematic.nets, ...schematic.subcircuits]) {
    scopes.set(scopeKey(item.scope_path), item.scope_path)
  }
  for (const net of schematic.nets) {
    for (const connection of net.connections) {
      pinNets.set(pinKey(connection.component_id, connection.pin_name), net)
    }
  }
  return { components, nets, pinNets, scopes }
}

function SourceLocation({ source }: { source: string }) {
  return <span className="simulation-mono" title={source}>{source || 'Not recorded'}</span>
}

function TopologyIssues({ schematic }: { schematic: SchematicDocumentDto }) {
  if (!schematic.parse_errors.length && !schematic.readonly_reasons.length) return null
  return (
    <div className="simulation-topology-issues">
      {schematic.parse_errors.length ? (
        <details open className="simulation-inline-error">
          <summary>{schematic.parse_errors.length} topology parsing issue{schematic.parse_errors.length === 1 ? '' : 's'} — connectivity may be incomplete</summary>
          <ul>{schematic.parse_errors.map((error, index) => (
            <li key={`${error.source_file}:${error.line_index}:${index}`}>
              <strong>{error.message}</strong>
              <div className="simulation-mono">{error.source_file || 'Source not recorded'}{error.line_index >= 0 ? `:${error.line_index + 1}` : ''}{error.column_start >= 0 ? `:${error.column_start + 1}` : ''}</div>
              {error.line_text ? <pre>{error.line_text}</pre> : null}
            </li>
          ))}</ul>
        </details>
      ) : null}
      {schematic.readonly_reasons.length ? (
        <details><summary>Source interpretation notes ({schematic.readonly_reasons.length})</summary>
          <ul>{schematic.readonly_reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>
        </details>
      ) : null}
    </div>
  )
}

function ComponentDetails({ component, index, select }: {
  component: SchematicComponentDto
  index: ReturnType<typeof indexTopology>
  select: (selection: Selection) => void
}) {
  return (
    <section className="simulation-topology-detail" aria-label={`Component ${component.instance_name}`}>
      <div className="simulation-card__header"><div><h3>{component.instance_name}</h3><p>{component.display_name || component.kind}</p></div><span className="simulation-count">{component.pins.length} pins</span></div>
      <dl className="simulation-detail-grid">
        <div><dt>Value</dt><dd className="simulation-mono">{component.display_value || '—'}</dd></div>
        <div><dt>Device kind</dt><dd>{component.kind || '—'}{component.primitive_kind ? ` · ${component.primitive_kind}` : ''}</dd></div>
        <div><dt>Scope</dt><dd>{scopeLabel(component.scope_path)}</dd></div>
        <div><dt>Source file</dt><dd><SourceLocation source={component.source_file} /></dd></div>
        {component.resolved_model_name ? <div><dt>Resolved model</dt><dd className="simulation-mono">{component.resolved_model_name}</dd></div> : null}
        {component.subckt_name ? <div><dt>Subcircuit</dt><dd className="simulation-mono">{component.subckt_name}</dd></div> : null}
        {component.primitive_source ? <div><dt>Model source</dt><dd><SourceLocation source={component.primitive_source} /></dd></div> : null}
        {component.semantic_roles.length ? <div><dt>Semantic roles</dt><dd>{component.semantic_roles.join(', ')}</dd></div> : null}
      </dl>
      <div className="simulation-table-wrap">
        <table className="simulation-table"><caption>Pin connectivity</caption><thead><tr><th>Pin</th><th>Role</th><th>Network</th><th>Scope</th></tr></thead><tbody>
          {component.pins.map((pin, pinIndex) => {
            const net = index.pinNets.get(pinKey(component.id, pin.name))
            return <tr key={`${pin.name}:${pinIndex}`}>
              <td className="simulation-mono">{pin.name}</td><td>{pin.role || component.pin_roles[pin.name] || '—'}</td>
              <td>{net ? <button type="button" className="simulation-topology-link" onClick={() => select({ kind: 'net', id: net.id })}>{net.name}</button> : <span className="simulation-mono">{pin.node_id || 'Unassigned'} (connection not recorded)</span>}</td>
              <td>{net ? scopeLabel(net.scope_path) : '—'}</td>
            </tr>
          })}
          {!component.pins.length ? <tr><td colSpan={4}>No parsed pins.</td></tr> : null}
        </tbody></table>
      </div>
      {component.editable_fields.length ? (
        <div className="simulation-table-wrap"><table className="simulation-table"><caption>Source attributes</caption><thead><tr><th>Attribute</th><th>Value</th><th>SPICE text</th></tr></thead><tbody>
          {component.editable_fields.map((field, fieldIndex) => <tr key={`${field.field_key}:${fieldIndex}`}><td>{field.label || field.field_key}</td><td className="simulation-mono">{field.display_text || '—'}</td><td className="simulation-mono">{field.raw_text || '—'}</td></tr>)}
        </tbody></table></div>
      ) : null}
    </section>
  )
}

function NetDetails({ net, index, select }: {
  net: SchematicNetDto
  index: ReturnType<typeof indexTopology>
  select: (selection: Selection) => void
}) {
  const sources = [...new Set(net.connections.map((connection) => index.components.get(connection.component_id)?.source_file).filter((source): source is string => Boolean(source)))]
  return (
    <section className="simulation-topology-detail" aria-label={`Network ${net.name}`}>
      <div className="simulation-card__header"><div><h3>Network {net.name}</h3><p>{scopeLabel(net.scope_path)}</p></div><span className="simulation-count">{net.connections.length} connections</span></div>
      <dl className="simulation-detail-grid">
        <div><dt>Scope</dt><dd>{scopeLabel(net.scope_path)}</dd></div>
        <div><dt>Connected source files</dt><dd>{sources.length ? sources.map((source) => <div key={source}><SourceLocation source={source} /></div>) : <SourceLocation source={net.source_file} />}</dd></div>
      </dl>
      <div className="simulation-table-wrap"><table className="simulation-table"><caption>Connected component pins</caption><thead><tr><th>Component</th><th>Pin</th><th>Role</th><th>Value / model</th><th>Source file</th></tr></thead><tbody>
        {net.connections.map((connection, connectionIndex) => {
          const component = index.components.get(connection.component_id)
          return <tr key={`${connection.component_id}:${connection.pin_name}:${connectionIndex}`}>
            <td>{component ? <button type="button" className="simulation-topology-link" onClick={() => select({ kind: 'component', id: component.id })}>{component.instance_name}</button> : <span>{connection.instance_name} (component unavailable)</span>}</td>
            <td className="simulation-mono">{connection.pin_name}</td><td>{connection.pin_role || '—'}</td>
            <td className="simulation-mono">{component?.display_value || component?.resolved_model_name || '—'}</td>
            <td><SourceLocation source={component?.source_file || ''} /></td>
          </tr>
        })}
        {!net.connections.length ? <tr><td colSpan={5}>No parsed connections.</td></tr> : null}
      </tbody></table></div>
    </section>
  )
}

function TopologyDocument({ schematic }: { schematic: SchematicDocumentDto }) {
  const index = useMemo(() => indexTopology(schematic), [schematic])
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState('all')
  const [kind, setKind] = useState<Selection['kind']>('net')
  const [selection, setSelection] = useState<Selection | null>(null)
  const search = query.trim().toLocaleLowerCase()
  const nets = schematic.nets.filter((net) => (scope === 'all' || scopeKey(net.scope_path) === scope) && (!search || [net.name, scopeLabel(net.scope_path), net.source_file, ...net.connections.flatMap((connection) => [connection.instance_name, connection.pin_name])].join(' ').toLocaleLowerCase().includes(search)))
  const components = schematic.components.filter((component) => (scope === 'all' || scopeKey(component.scope_path) === scope) && (!search || [component.instance_name, component.kind, component.display_name, component.display_value, component.source_file, scopeLabel(component.scope_path), ...component.node_ids].join(' ').toLocaleLowerCase().includes(search)))
  const activeNet = kind === 'net' ? nets.find((net) => selection?.kind === 'net' && net.id === selection.id) ?? nets[0] : undefined
  const activeComponent = kind === 'component' ? components.find((component) => selection?.kind === 'component' && component.id === selection.id) ?? components[0] : undefined
  const definitions = schematic.subcircuits.filter((definition) => scope === 'all' || scopeKey(definition.scope_path) === scope)

  const select = (next: Selection) => {
    const item = next.kind === 'net' ? index.nets.get(next.id) : index.components.get(next.id)
    if (!item) return
    setQuery('')
    setScope(scopeKey(item.scope_path))
    setKind(next.kind)
    setSelection(next)
  }

  return (
    <section className="simulation-card simulation-card--fill simulation-topology">
      <div className="simulation-card__header"><div><h2>{schematic.title || 'Topology inspector'}</h2><p>Result source snapshot · {schematic.components.length} components · {schematic.nets.length} networks</p></div></div>
      <div className="simulation-topology-toolbar">
        <label>Search topology<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Network, component, value or source" /></label>
        <label>Scope<select value={scope} onChange={(event) => setScope(event.target.value)}><option value="all">All scopes</option>{[...index.scopes].map(([key, path]) => <option key={key} value={key}>{scopeLabel(path)}</option>)}</select></label>
      </div>
      <TopologyIssues schematic={schematic} />
      <div className="simulation-topology-body">
        <nav className="simulation-topology-browser" aria-label="Topology entries">
          <div className="simulation-topology-tabs"><button type="button" aria-pressed={kind === 'net'} onClick={() => setKind('net')}>Networks ({nets.length})</button><button type="button" aria-pressed={kind === 'component'} onClick={() => setKind('component')}>Components ({components.length})</button></div>
          <div className="simulation-topology-list">
            {kind === 'net' ? nets.map((net) => <button type="button" key={net.id} className="simulation-topology-row" aria-pressed={activeNet?.id === net.id} onClick={() => setSelection({ kind: 'net', id: net.id })}><strong>{net.name}</strong><span>{scopeLabel(net.scope_path)} · {net.connections.length} pins</span></button>) : components.map((component) => <button type="button" key={component.id} className="simulation-topology-row" aria-pressed={activeComponent?.id === component.id} onClick={() => setSelection({ kind: 'component', id: component.id })}><strong>{component.instance_name} <span>{component.display_value || component.kind}</span></strong><span>{scopeLabel(component.scope_path)}</span></button>)}
            {!(kind === 'net' ? nets.length : components.length) ? <div className="simulation-empty"><span>No {kind === 'net' ? 'networks' : 'components'} match this scope and search.</span></div> : null}
          </div>
        </nav>
        {activeNet ? <NetDetails net={activeNet} index={index} select={select} /> : activeComponent ? <ComponentDetails component={activeComponent} index={index} select={select} /> : <div className="simulation-empty"><span>Select a parsed network or component to inspect its connections.</span></div>}
      </div>
      {definitions.length ? <details className="simulation-topology-definitions"><summary>Subcircuit definitions ({definitions.length})</summary><p>Definition scopes and declared ports from the source snapshot.</p><div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Definition</th><th>Scope</th><th>Ports</th><th>Components</th><th>Source file</th></tr></thead><tbody>{definitions.map((definition, definitionIndex) => <tr key={`${scopeKey(definition.scope_path)}:${definition.name}:${definitionIndex}`}><td className="simulation-mono">{definition.name}</td><td><button type="button" className="simulation-topology-link" onClick={() => { setScope(scopeKey(definition.scope_path)); setQuery(''); setKind('component') }}>{scopeLabel(definition.scope_path)}</button></td><td className="simulation-mono">{definition.port_names.join(', ') || '—'}</td><td>{definition.component_ids.length}</td><td><SourceLocation source={definition.source_file} /></td></tr>)}</tbody></table></div></details> : null}
      <details className="simulation-topology-provenance"><summary>Snapshot source</summary><dl className="simulation-detail-grid"><div><dt>File</dt><dd><SourceLocation source={schematic.file_path} /></dd></div><div><dt>Revision</dt><dd className="simulation-mono">{schematic.revision}</dd></div></dl></details>
    </section>
  )
}

export function TopologyInspector({ schematic }: { schematic: SchematicDocumentDto | null }) {
  if (!schematic) return <div className="simulation-empty"><strong>No result-bound topology snapshot</strong><span>This run has no recorded topology document.</span></div>
  return <TopologyDocument key={`${schematic.document_id}:${schematic.revision}`} schematic={schematic} />
}
