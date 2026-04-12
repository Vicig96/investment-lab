import { useState, useEffect } from 'react'
import { listInstruments, getIndicator } from '../api.js'

const instLabel = (i) => i.name ? `${i.ticker} — ${i.name}` : i.ticker

/**
 * Single source of truth for each indicator's backend name, display label,
 * and query parameters — derived directly from the backend registry:
 *
 *   sma              → period
 *   ema              → period
 *   rsi              → period
 *   macd             → fast, slow, signal   (NOT period)
 *   atr              → period
 *   hvol             → period  (trading_days kept at backend default 252)
 *   daily_returns    → (no params)
 *   log_returns      → (no params)
 *   cumulative_returns → (no params)
 */
const INDICATOR_CONFIG = {
  sma: {
    label: 'SMA — Simple Moving Average',
    params: [{ key: 'period', label: 'Period', default: 20, min: 1, max: 500 }],
  },
  ema: {
    label: 'EMA — Exponential Moving Average',
    params: [{ key: 'period', label: 'Period', default: 20, min: 1, max: 500 }],
  },
  rsi: {
    label: 'RSI — Relative Strength Index',
    params: [{ key: 'period', label: 'Period', default: 14, min: 2, max: 500 }],
  },
  macd: {
    label: 'MACD — Moving Avg Convergence Divergence',
    params: [
      { key: 'fast',   label: 'Fast EMA',   default: 12, min: 1, max: 200 },
      { key: 'slow',   label: 'Slow EMA',   default: 26, min: 1, max: 500 },
      { key: 'signal', label: 'Signal EMA', default: 9,  min: 1, max: 100 },
    ],
  },
  atr: {
    label: 'ATR — Average True Range',
    params: [{ key: 'period', label: 'Period', default: 14, min: 1, max: 500 }],
  },
  hvol: {
    label: 'HVol — Historical Volatility (annualised)',
    params: [{ key: 'period', label: 'Period', default: 20, min: 2, max: 500 }],
  },
  daily_returns: {
    label: 'Daily Returns',
    params: [],
  },
  log_returns: {
    label: 'Log Returns',
    params: [],
  },
  cumulative_returns: {
    label: 'Cumulative Returns',
    params: [],
  },
}

function defaultValues(config) {
  return Object.fromEntries(config.params.map(p => [p.key, String(p.default)]))
}

export default function Indicators() {
  const [instruments,  setInstruments]  = useState([])
  const [instrumentId, setInstrumentId] = useState('')
  const [indicator,    setIndicator]    = useState('sma')
  const [paramValues,  setParamValues]  = useState(defaultValues(INDICATOR_CONFIG.sma))
  const [result,       setResult]       = useState(null)
  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState(null)

  useEffect(() => {
    listInstruments().then(d => {
      const items = d.items ?? []
      setInstruments(items)
      if (items.length) setInstrumentId(items[0].id)
    }).catch(() => {})
  }, [])

  const selectIndicator = (name) => {
    setIndicator(name)
    setParamValues(defaultValues(INDICATOR_CONFIG[name]))
    setResult(null)
    setError(null)
  }

  const setParam = (key, value) =>
    setParamValues(prev => ({ ...prev, [key]: value }))

  const config = INDICATOR_CONFIG[indicator]

  const run = async (e) => {
    e.preventDefault()
    if (!instrumentId) return

    // Validate all numeric params are positive integers
    for (const p of config.params) {
      const n = Number(paramValues[p.key])
      if (!Number.isInteger(n) || n < p.min) {
        setError(`"${p.label}" must be an integer ≥ ${p.min}.`)
        return
      }
    }

    setLoading(true)
    setError(null)
    setResult(null)
    try {
      // Build params dict with only the keys this indicator actually uses
      const params = Object.fromEntries(
        config.params.map(p => [p.key, paramValues[p.key]])
      )
      const data = await getIndicator(instrumentId, indicator, params)
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const series  = result?.data ?? []
  const nonNull = series.filter(r => r.value != null)

  return (
    <>
      <h2 className="section-title">Indicators</h2>
      <div className="card">
        <div className="card-title">Compute</div>
        <form className="form" onSubmit={run}>
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
              <label>Indicator</label>
              <select value={indicator} onChange={e => selectIndicator(e.target.value)}>
                {Object.entries(INDICATOR_CONFIG).map(([key, cfg]) => (
                  <option key={key} value={key}>{cfg.label}</option>
                ))}
              </select>
            </div>

            {/* Render only the params this indicator actually takes */}
            {config.params.map(p => (
              <div className="field" key={p.key} style={{ maxWidth: 110 }}>
                <label>{p.label}</label>
                <input
                  type="number"
                  value={paramValues[p.key]}
                  onChange={e => setParam(p.key, e.target.value)}
                  min={p.min}
                  max={p.max}
                />
              </div>
            ))}
          </div>

          <div>
            <button className="btn btn-primary" type="submit" disabled={loading || !instrumentId}>
              {loading ? <span className="spinner" /> : null}
              Compute
            </button>
          </div>
        </form>
        {error && <div className="alert alert-error">{error}</div>}
      </div>

      {!result && !loading && !error && (
        <div className="empty" style={{ paddingTop: 40 }}>
          Select an instrument and indicator, then click Compute.
        </div>
      )}

      {result && (
        <div className="card">
          <div className="card-title">
            {config.label}
            {config.params.length > 0 && (
              <span style={{ fontWeight: 400, color: 'var(--muted)', marginLeft: 8 }}>
                ({config.params.map(p => `${p.label.toLowerCase()} ${paramValues[p.key]}`).join(', ')})
              </span>
            )}
            <span style={{ marginLeft: 12 }}>
              — {nonNull.length} of {series.length} values computed
            </span>
          </div>

          {series.length === 0 ? (
            <div className="empty">
              No data returned. Ensure prices are ingested for this instrument.
            </div>
          ) : nonNull.length === 0 ? (
            <div className="alert alert-info">
              All values are null — not enough price rows for this period.
              RSI requires ≥ {paramValues.period ?? '14'} rows; MACD requires ≥ {paramValues.slow ?? '26'} rows.
            </div>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Date</th><th>Value</th></tr></thead>
                  <tbody>
                    {series.slice(-100).map((r, i) => (
                      <tr key={i}>
                        <td>{r.date}</td>
                        <td style={{ fontFamily: 'monospace' }}>
                          {r.value != null
                            ? Number(r.value).toFixed(4)
                            : <span style={{ color: 'var(--muted)' }}>—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {series.length > 100 && (
                <div className="empty">Showing last 100 rows of {series.length}</div>
              )}
            </>
          )}
        </div>
      )}
    </>
  )
}
