import { useState, useEffect } from 'react'
import { listInstruments, listPrices, priceSummary } from '../api.js'

const instLabel = (i) => i.name ? `${i.ticker} — ${i.name}` : i.ticker

export default function Prices() {
  const [instruments, setInstruments] = useState([])
  const [instrumentId, setInstrumentId] = useState('')
  const [fromDate, setFromDate] = useState('')
  const [toDate,   setToDate]   = useState('')
  const [prices,   setPrices]   = useState(null)
  const [summary,  setSummary]  = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [dateError, setDateError] = useState(null)

  useEffect(() => {
    listInstruments().then(d => {
      const items = d.items ?? []
      setInstruments(items)
      if (items.length) setInstrumentId(items[0].id)
    }).catch(() => {})
  }, [])

  const validateDates = () => {
    if (fromDate && toDate && fromDate > toDate) {
      setDateError('"From" must be before or equal to "To".')
      return false
    }
    setDateError(null)
    return true
  }

  const loadData = async (e) => {
    e.preventDefault()
    if (!instrumentId) return
    if (!validateDates()) return
    setLoading(true)
    setError(null)
    setPrices(null)
    setSummary(null)
    try {
      const params = {}
      if (fromDate) params.from_date = fromDate
      if (toDate)   params.to_date   = toDate
      const [p, s] = await Promise.all([
        listPrices(instrumentId, params),
        priceSummary(instrumentId),
      ])
      setPrices(p)
      setSummary(s)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <h2 className="section-title">Prices</h2>
      <div className="card">
        <div className="card-title">Query</div>
        <form className="form" onSubmit={loadData}>
          <div className="form-row">
            <div className="field">
              <label>Instrument</label>
              <select value={instrumentId} onChange={e => setInstrumentId(e.target.value)}>
                {instruments.map(i => (
                  <option key={i.id} value={i.id}>{instLabel(i)}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>From</label>
              <input
                type="date"
                value={fromDate}
                onChange={e => { setFromDate(e.target.value); setDateError(null) }}
              />
            </div>
            <div className="field">
              <label>To</label>
              <input
                type="date"
                value={toDate}
                onChange={e => { setToDate(e.target.value); setDateError(null) }}
              />
            </div>
          </div>
          {dateError && <div className="field-error">{dateError}</div>}
          <div>
            <button className="btn btn-primary" type="submit" disabled={loading || !instrumentId}>
              {loading ? <span className="spinner" /> : null}
              Load
            </button>
          </div>
        </form>
        {error && <div className="alert alert-error">{error}</div>}
      </div>

      {!prices && !loading && !error && (
        <div className="empty" style={{ paddingTop: 40 }}>
          Select an instrument and click Load to view price data.
        </div>
      )}

      {summary && (
        <div className="card">
          <div className="card-title">Summary — {summary.ticker}</div>
          <div className="metrics-grid">
            <div className="metric-box">
              <div className="metric-label">Total candles</div>
              <div className="metric-value">{summary.total_candles}</div>
            </div>
            <div className="metric-box">
              <div className="metric-label">From</div>
              <div className="metric-value" style={{ fontSize: 15 }}>{summary.date_from ?? '—'}</div>
            </div>
            <div className="metric-box">
              <div className="metric-label">To</div>
              <div className="metric-value" style={{ fontSize: 15 }}>{summary.date_to ?? '—'}</div>
            </div>
            <div className="metric-box">
              <div className="metric-label">Last close</div>
              <div className="metric-value">
                {summary.last_close != null ? `$${Number(summary.last_close).toFixed(2)}` : '—'}
              </div>
            </div>
          </div>
        </div>
      )}

      {prices && (
        <div className="card">
          <div className="card-title">
            Candles — {prices.total} total
            {fromDate || toDate
              ? ` (filtered${fromDate ? ` from ${fromDate}` : ''}${toDate ? ` to ${toDate}` : ''})`
              : ''}
            {prices.items.length < prices.total
              ? `, showing first ${prices.items.length}`
              : ''}
          </div>
          {prices.items.length === 0 ? (
            <div className="empty">No price data for this selection.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th><th>Open</th><th>High</th><th>Low</th>
                    <th>Close</th><th>Adj Close</th><th>Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {prices.items.map(c => (
                    <tr key={c.date}>
                      <td>{c.date}</td>
                      <td>{Number(c.open).toFixed(4)}</td>
                      <td style={{ color: 'var(--success)' }}>{Number(c.high).toFixed(4)}</td>
                      <td style={{ color: 'var(--error)' }}>{Number(c.low).toFixed(4)}</td>
                      <td><strong>{Number(c.close).toFixed(4)}</strong></td>
                      <td style={{ color: 'var(--muted)' }}>
                        {c.adj_close != null ? Number(c.adj_close).toFixed(4) : '—'}
                      </td>
                      <td style={{ color: 'var(--muted)' }}>
                        {c.volume != null ? Number(c.volume).toLocaleString() : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  )
}
