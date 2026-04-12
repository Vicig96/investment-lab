import { useState, useEffect } from 'react'
import { listInstruments, runSignals, listSignals } from '../api.js'

const STRATEGIES = ['ma_crossover', 'relative_momentum', 'trend_filter']

const instLabel = (i) => i.name ? `${i.ticker} — ${i.name}` : i.ticker

function parseJsonField(raw, fieldName) {
  try {
    const v = JSON.parse(raw)
    if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new Error()
    return [v, null]
  } catch {
    return [null, `${fieldName} must be a valid JSON object (e.g. {} or {"fast":20})`]
  }
}

export default function Signals() {
  const [instruments, setInstruments] = useState([])
  const [instrumentId, setInstrumentId] = useState('')

  const [strategy, setStrategy]   = useState('ma_crossover')
  const [params,   setParams]     = useState('{}')
  const [persist,  setPersist]    = useState(true)
  const [running,  setRunning]    = useState(false)
  const [runResult, setRunResult] = useState(null)
  const [runError,  setRunError]  = useState(null)

  const [signals,   setSignals]   = useState(null)
  const [listing,   setListing]   = useState(false)
  const [listError, setListError] = useState(null)

  useEffect(() => {
    listInstruments().then(d => {
      const items = d.items ?? []
      setInstruments(items)
      if (items.length) setInstrumentId(items[0].id)
    }).catch(() => {})
  }, [])

  const loadSignals = async (id = instrumentId) => {
    if (!id) return
    setListing(true)
    setListError(null)
    try {
      const data = await listSignals(id)
      setSignals(data.items ?? data)
    } catch (err) {
      setListError(err.message)
    } finally {
      setListing(false)
    }
  }

  const execRun = async (e) => {
    e.preventDefault()
    const [parsedParams, jsonErr] = parseJsonField(params, 'Params')
    if (jsonErr) { setRunError(jsonErr); return }

    setRunning(true)
    setRunResult(null)
    setRunError(null)
    try {
      const data = await runSignals({
        strategy_name: strategy,
        instrument_ids: [instrumentId],
        persist,
        params: parsedParams,
      })
      setRunResult(data)
      // Auto-refresh persisted signals list after a persist run
      if (persist) loadSignals(instrumentId)
    } catch (err) {
      setRunError(err.message)
    } finally {
      setRunning(false)
    }
  }

  // Count signals generated from the last run
  const runSignalCount = runResult?.results
    ? Object.values(runResult.results).reduce((sum, arr) => sum + (arr?.length ?? 0), 0)
    : null

  const dirLabel = (d) => {
    if (d === 1)  return <span className="badge badge-long">LONG</span>
    if (d === -1) return <span className="badge badge-sell">SHORT</span>
    return <span className="badge badge-flat">FLAT</span>
  }

  return (
    <>
      <h2 className="section-title">Signals</h2>

      {/* Run */}
      <div className="card">
        <div className="card-title">Run Strategy</div>
        <form className="form" onSubmit={execRun}>
          <div className="form-row">
            <div className="field">
              <label>Instrument</label>
              <select value={instrumentId} onChange={e => setInstrumentId(e.target.value)}>
                {instruments.map(i => <option key={i.id} value={i.id}>{instLabel(i)}</option>)}
              </select>
            </div>
            <div className="field">
              <label>Strategy</label>
              <select value={strategy} onChange={e => setStrategy(e.target.value)}>
                {STRATEGIES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>
          <div className="field" style={{ maxWidth: 360 }}>
            <label>Params (JSON object)</label>
            <textarea
              value={params}
              onChange={e => { setParams(e.target.value); setRunError(null) }}
              spellCheck={false}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13, color: 'var(--text)' }}>
              <input type="checkbox" checked={persist} onChange={e => setPersist(e.target.checked)}
                style={{ width: 'auto', margin: 0 }} />
              Persist to DB
            </label>
            <button className="btn btn-primary" type="submit" disabled={running || !instrumentId}>
              {running ? <span className="spinner" /> : null}
              Run
            </button>
          </div>
        </form>
        {runError && <div className="alert alert-error">{runError}</div>}
        {runResult && (
          <div className="alert alert-success">
            ✓ Strategy ran — {runSignalCount} signal rows generated.
            {persist && ' Persisted signals refreshed below.'}
          </div>
        )}
      </div>

      {/* List persisted signals */}
      <div className="card">
        <div className="card-title">Persisted Signals</div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <select
            value={instrumentId}
            onChange={e => { setInstrumentId(e.target.value); setSignals(null) }}
            style={{ maxWidth: 260 }}
          >
            {instruments.map(i => <option key={i.id} value={i.id}>{instLabel(i)}</option>)}
          </select>
          <button className="btn btn-secondary" onClick={() => loadSignals()} disabled={listing || !instrumentId}>
            {listing ? <span className="spinner" /> : null}
            Load signals
          </button>
        </div>
        {listError && <div className="alert alert-error" style={{ marginTop: 10 }}>{listError}</div>}
        {signals === null && !listing && (
          <div className="empty">Click "Load signals" to view persisted signals for this instrument.</div>
        )}
        {signals !== null && (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            {signals.length === 0 ? (
              <div className="empty">No signals persisted for this instrument.</div>
            ) : (
              <>
                <table>
                  <thead>
                    <tr><th>Date</th><th>Strategy</th><th>Direction</th><th>Strength</th></tr>
                  </thead>
                  <tbody>
                    {signals.slice(-100).map((s, i) => (
                      <tr key={i}>
                        <td>{s.date}</td>
                        <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{s.strategy_name}</td>
                        <td>{dirLabel(s.direction)}</td>
                        <td style={{ fontFamily: 'monospace' }}>
                          {s.strength != null ? Number(s.strength).toFixed(4) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {signals.length > 100 && (
                  <div className="empty">Showing last 100 of {signals.length} signals</div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </>
  )
}
