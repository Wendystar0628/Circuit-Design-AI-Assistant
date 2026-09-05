import { useEffect, useMemo, useState } from 'react'
import type { ResultViewModel } from './types'

export function OutputPanel({view}: {view: ResultViewModel}) {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const output = view.result.raw_output ?? ''
  const lines = useMemo(() => output.split(/\r?\n/).map((text, index) => ({text, number: index + 1})).filter((line) => line.text.toLowerCase().includes(search.toLowerCase())), [output, search])
  useEffect(() => setPage(0), [search, view.identity.resultId])
  return <section className="simulation-card simulation-card--fill">
    <div className="simulation-card__header"><h2>Simulator output</h2><input aria-label="Search simulator output" placeholder="Search output" value={search} onChange={(event) => setSearch(event.target.value)} /><div className="simulation-button-row"><button type="button" disabled={!page} onClick={() => setPage(page - 1)}>Previous</button><span>{output ? lines.length : 0} lines</span><button type="button" disabled={(page + 1) * 300 >= lines.length} onClick={() => setPage(page + 1)}>Next</button></div></div>
    {view.result.error ? <div className="simulation-inline-error" role="alert"><strong>{view.result.error.code}: {view.result.error.message}</strong>{view.result.error.recovery_suggestion ? <span>{view.result.error.recovery_suggestion}</span> : null}</div> : null}
    {output ? <div className="simulation-log" role="log">{lines.slice(page * 300, (page + 1) * 300).map((line) => <div key={line.number}><span>{line.number}</span><code>{line.text || ' '}</code></div>)}</div> : <div className="simulation-empty">No simulator output was recorded for this run.</div>}
  </section>
}
