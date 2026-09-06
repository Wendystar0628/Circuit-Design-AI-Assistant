import type { SimulationProvenance } from './types'
import { CapturedModels } from './ModelBindings'

export function RunProvenance({provenance}: {provenance: SimulationProvenance}) {
  const engine = provenance.engine
  const omitted = provenance.omitted_measurements ?? []
  return <div className="simulation-run-provenance">
    <dl className="simulation-detail-grid">
      <div><dt>Simulation engine</dt><dd>{engine ? `${engine.name} · ${engine.version ?? 'Version not reported'}` : 'Not recorded for this result'}</dd></div>
      {engine ? <div><dt>Execution</dt><dd>{engine.execution_mode}<small>{engine.platform}</small></dd></div> : null}
    </dl>
    <CapturedModels models={provenance.models ?? []} />
    {omitted.length ? <details className="simulation-omitted-measurements">
      <summary>Source measurements excluded by the selected analysis ({omitted.length})</summary>
      <div className="simulation-table-wrap"><table className="simulation-table"><thead><tr><th>Statement</th><th>Reason</th><th>Source</th></tr></thead><tbody>{omitted.map((item, index) => <tr key={index}><td><code>{item.statement}</code></td><td>{item.reason}</td><td>{item.source_id}:{item.line_number}</td></tr>)}</tbody></table></div>
    </details> : null}
  </div>
}
