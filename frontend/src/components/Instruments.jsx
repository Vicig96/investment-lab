import { useState, useEffect, useCallback } from 'react'
import { listInstruments, createInstrument } from '../api.js'

const EMPTY = { ticker: '', name: '', asset_class: '', currency: 'USD' }

// Tickers that Swagger/FastAPI auto-fill as default placeholder values
const JUNK_VALUES = new Set(['string', 'ticker', 'test', 'undefined', 'null', 'example'])

const TICKER_RE = /^[A-Z0-9.\-]{1,20}$/

function validateForm(form) {
  const ticker = form.ticker.trim().toUpperCase()
  if (!ticker) return 'Ticker is required.'
  if (JUNK_VALUES.has(ticker.toLowerCase())) return `"${ticker}" looks like a placeholder — enter a real ticker.`
  if (!TICKER_RE.test(ticker)) return 'Ticker must be 1–20 uppercase letters, digits, dots or hyphens.'
  const currency = form.currency.trim().toUpperCase()
  if (currency && !/^[A-Z]{3}$/.test(currency)) return 'Currency must be a 3-letter ISO code (e.g. USD).'
  return null
}

export default function Instruments() {
  const [instruments, setInstruments] = useState([])
  const [form, setForm]       = useState(EMPTY)
  const [formError, setFormError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [listLoading, setListLoading] = useState(true)
  const [status, setStatus]   = useState(null)   // {type, msg}

  const load = useCallback(async () => {
    setListLoading(true)
    try {
      const data = await listInstruments()
      setInstruments(data.items ?? [])
    } catch (e) {
      setStatus({ type: 'error', msg: `Failed to load instruments: ${e.message}` })
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const set = (k, v) => {
    setFormError(null)
    setForm(f => ({ ...f, [k]: v }))
  }

  // Auto-uppercase ticker while typing
  const setTicker = (v) => set('ticker', v.toUpperCase().replace(/[^A-Z0-9.\-]/g, ''))

  const submit = async (e) => {
    e.preventDefault()
    const err = validateForm(form)
    if (err) { setFormError(err); return }

    setLoading(true)
    setStatus(null)
    const payload = {
      ...form,
      ticker:   form.ticker.trim().toUpperCase(),
      currency: form.currency.trim().toUpperCase() || 'USD',
    }
    try {
      await createInstrument(payload)
      setStatus({ type: 'success', msg: `Instrument "${payload.ticker}" created.` })
      setForm(EMPTY)
      load()
    } catch (err) {
      setStatus({ type: 'error', msg: err.message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <h2 className="section-title">Instruments</h2>

      <div className="card">
        <div className="card-title">Create Instrument</div>
        <form className="form" onSubmit={submit}>
          <div className="form-row">
            <div className="field">
              <label>Ticker *</label>
              <input
                value={form.ticker}
                onChange={e => setTicker(e.target.value)}
                placeholder="SPY"
                maxLength={20}
                required
              />
            </div>
            <div className="field">
              <label>Name</label>
              <input
                value={form.name}
                onChange={e => set('name', e.target.value)}
                placeholder="SPDR S&P 500 ETF"
              />
            </div>
            <div className="field">
              <label>Asset class</label>
              <input
                value={form.asset_class}
                onChange={e => set('asset_class', e.target.value)}
                placeholder="equity"
              />
            </div>
            <div className="field">
              <label>Currency</label>
              <input
                value={form.currency}
                onChange={e => set('currency', e.target.value.toUpperCase())}
                placeholder="USD"
                maxLength={3}
              />
            </div>
          </div>
          {formError && <div className="field-error">{formError}</div>}
          <div>
            <button className="btn btn-primary" type="submit" disabled={loading || !form.ticker}>
              {loading ? <span className="spinner" /> : null}
              Create
            </button>
          </div>
        </form>
        {status && <div className={`alert alert-${status.type}`}>{status.msg}</div>}
      </div>

      <div className="card">
        <div className="card-title">All instruments ({instruments.length})</div>
        {listLoading ? (
          <div className="empty"><span className="spinner" /></div>
        ) : instruments.length === 0 ? (
          <div className="empty">No instruments yet. Create one above.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th><th>Name</th><th>Asset class</th><th>Currency</th><th>ID</th>
                </tr>
              </thead>
              <tbody>
                {instruments.map(i => (
                  <tr key={i.id}>
                    <td><strong>{i.ticker}</strong></td>
                    <td>{i.name ?? <span style={{ color: 'var(--muted)' }}>—</span>}</td>
                    <td>{i.asset_class ?? <span style={{ color: 'var(--muted)' }}>—</span>}</td>
                    <td>{i.currency}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--muted)' }}>{i.id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
