import { useState, useEffect } from 'react'
import { listInstruments, ingestCsv } from '../api.js'

const instLabel = (i) => i.name ? `${i.ticker} — ${i.name}` : i.ticker

export default function PriceIngest() {
  const [instruments, setInstruments] = useState([])
  const [instrumentId, setInstrumentId] = useState('')
  const [file, setFile]     = useState(null)
  const [loading, setLoading] = useState(false)
  const [status, setStatus]   = useState(null)

  useEffect(() => {
    listInstruments().then(d => {
      const items = d.items ?? []
      setInstruments(items)
      if (items.length) setInstrumentId(items[0].id)
    }).catch(() => {})
  }, [])

  const selectedTicker = instruments.find(i => i.id === instrumentId)?.ticker ?? instrumentId.slice(0, 8)

  const submit = async (e) => {
    e.preventDefault()
    if (!file || !instrumentId) return
    setLoading(true)
    setStatus(null)
    try {
      const result = await ingestCsv(instrumentId, file)
      setStatus({
        type: 'success',
        msg: `✓ ${result.rows_upserted} rows upserted for ${selectedTicker}.`,
      })
    } catch (err) {
      setStatus({ type: 'error', msg: err.message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <h2 className="section-title">Ingest CSV Prices</h2>
      <div className="card">
        <div className="card-title">Upload OHLCV CSV</div>
        <form className="form" onSubmit={submit}>
          <div className="form-row">
            <div className="field">
              <label>Instrument</label>
              {instruments.length === 0 ? (
                <div className="alert alert-info" style={{ marginTop: 0 }}>
                  No instruments yet — create one first.
                </div>
              ) : (
                <select value={instrumentId} onChange={e => setInstrumentId(e.target.value)} required>
                  {instruments.map(i => (
                    <option key={i.id} value={i.id}>{instLabel(i)}</option>
                  ))}
                </select>
              )}
            </div>
          </div>

          <div className="field">
            <label>CSV file</label>
            <div className="file-input-wrap">
              <input
                type="file"
                accept=".csv"
                onChange={e => {
                  setFile(e.target.files[0] ?? null)
                  setStatus(null)
                }}
                required
              />
              <div className={`file-label${file ? ' has-file' : ''}`}>
                <span>📂</span>
                {file ? file.name : 'Choose a CSV file…'}
              </div>
            </div>
          </div>

          <div>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={loading || !file || !instrumentId || instruments.length === 0}
            >
              {loading ? <span className="spinner" /> : null}
              Ingest
            </button>
          </div>
        </form>
        {status && <div className={`alert alert-${status.type}`}>{status.msg}</div>}
      </div>

      <div className="card">
        <div className="card-title">Expected CSV format</div>
        <pre className="json-block">{`date,open,high,low,close,adj_close,volume
2024-01-02,476.0,478.1,474.5,477.3,477.3,82341200
2024-01-03,477.3,479.0,475.2,476.8,476.8,71209400
...`}</pre>
        <div style={{ marginTop: 10, color: 'var(--muted)', fontSize: 12 }}>
          <code>adj_close</code> and <code>volume</code> are optional.
          Dates must be in ISO format (YYYY-MM-DD). Duplicate rows are upserted.
        </div>
      </div>
    </>
  )
}
