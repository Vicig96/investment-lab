import { useState } from 'react'
import { runBacktest, getBacktestResults } from '../api.js'

const STRATEGIES = ['ma_crossover', 'relative_momentum', 'trend_filter']

const DEFAULT = {
  strategy_name:       'ma_crossover',
  instrument_tickers:  'SPY',
  date_from:           '2020-01-01',
  date_to:             '2024-12-31',
  initial_capital:     '10000',
  commission_bps:      '10',
  params:              '{}',
}

function fmt(v, dec = 2) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return isNaN(n) ? String(v) : n.toFixed(dec)
}

function pct(v) {
  if (v == null) return '—'
  const n = Number(v)
  return isNaN(n) ? '—' : `${(n * 100).toFixed(2)}%`
}

function validateForm(f) {
  const tickers = f.instrument_tickers.split(',').map(s => s.trim()).filter(Boolean)
  if (!tickers.length) return 'At least one ticker is required.'
  if (!f.date_from)    return '"From" date is required.'
  if (!f.date_to)      return '"To" date is required.'
  if (f.date_from >= f.date_to) return '"From" date must be before "To" date.'
  if (Number(f.initial_capital) <= 0) return 'Initial capital must be > 0.'
  try { JSON.parse(f.params) } catch { return 'Params must be a valid JSON object.' }
  return null
}

export default function Backtest() {
  const [f, setF]         = useState(DEFAULT)
  const [run,   setRun]   = useState(null)    // {run_id, status}
  const [result, setResult] = useState(null)  // BacktestResultRead
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)
  const [formError, setFormError] = useState(null)

  const set = (k, v) => { setF(prev => ({ ...prev, [k]: v })); setFormError(null) }

  const submit = async (e) => {
    e.preventDefault()
    const err = validateForm(f)
    if (err) { setFormError(err); return }

    setLoading(true)
    setError(null)
    setRun(null)
    setResult(null)
    try {
      const params = JSON.parse(f.params)
      const runResp = await runBacktest({
        strategy_name:       f.strategy_name,
        instrument_tickers:  f.instrument_tickers.split(',').map(s => s.trim().toUpperCase()).filter(Boolean),
        date_from:           f.date_from,
        date_to:             f.date_to,
        initial_capital:     Number(f.initial_capital),
        commission_bps:      Number(f.commission_bps),
        params,
      })
      setRun(runResp)

      // The run endpoint only returns {run_id, status}.
      // Metrics, trades and equity curve are at GET /backtest/{id}/results.
      if (runResp.run_id && runResp.status === 'complete') {
        const res = await getBacktestResults(runResp.run_id)
        setResult(res)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const m = result ?? {}
  // Trades shape: {date, ticker, action, shares, price, commission, pnl}
  const trades = result?.trades ?? []

  return (
    <>
      <h2 className="section-title">Backtest</h2>
      <div className="card">
        <div className="card-title">Configuration</div>
        <form className="form" onSubmit={submit}>
          <div className="form-row">
            <div className="field">
              <label>Strategy</label>
              <select value={f.strategy_name} onChange={e => set('strategy_name', e.target.value)}>
                {STRATEGIES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="field">
              <label>Tickers (comma-separated)</label>
              <input
                value={f.instrument_tickers}
                onChange={e => set('instrument_tickers', e.target.value.toUpperCase())}
                placeholder="SPY,QQQ"
              />
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>From *</label>
              <input type="date" value={f.date_from} onChange={e => set('date_from', e.target.value)} required />
            </div>
            <div className="field">
              <label>To *</label>
              <input type="date" value={f.date_to} onChange={e => set('date_to', e.target.value)} required />
            </div>
            <div className="field">
              <label>Initial capital ($)</label>
              <input type="number" value={f.initial_capital} min="1" onChange={e => set('initial_capital', e.target.value)} />
            </div>
            <div className="field">
              <label>Commission (bps)</label>
              <input type="number" value={f.commission_bps} min="0" onChange={e => set('commission_bps', e.target.value)} />
            </div>
          </div>
          <div className="field" style={{ maxWidth: 360 }}>
            <label>Strategy params (JSON)</label>
            <textarea value={f.params} onChange={e => set('params', e.target.value)} spellCheck={false} />
          </div>
          {formError && <div className="field-error">{formError}</div>}
          <div>
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? <span className="spinner" /> : null}
              Run backtest
            </button>
          </div>
        </form>
        {error && <div className="alert alert-error">{error}</div>}
      </div>

      {run && (
        <div className={`alert alert-${run.status === 'complete' ? 'success' : 'info'}`}
          style={{ marginBottom: 16 }}>
          Status: <strong>{run.status}</strong>
          <span style={{ marginLeft: 12, opacity: 0.6, fontFamily: 'monospace', fontSize: 12 }}>
            {run.run_id}
          </span>
        </div>
      )}

      {result && (
        <>
          {/* Metrics */}
          <div className="card">
            <div className="card-title">Metrics</div>
            <div className="metrics-grid">
              <div className="metric-box"><div className="metric-label">CAGR</div><div className="metric-value">{pct(m.cagr)}</div></div>
              <div className="metric-box"><div className="metric-label">Sharpe</div><div className="metric-value">{fmt(m.sharpe_ratio)}</div></div>
              <div className="metric-box"><div className="metric-label">Max drawdown</div><div className="metric-value">{pct(m.max_drawdown)}</div></div>
              <div className="metric-box"><div className="metric-label">Calmar</div><div className="metric-value">{fmt(m.calmar_ratio)}</div></div>
              <div className="metric-box"><div className="metric-label">Win rate</div><div className="metric-value">{pct(m.win_rate)}</div></div>
              <div className="metric-box"><div className="metric-label">Total trades</div><div className="metric-value">{m.total_trades ?? '—'}</div></div>
              <div className="metric-box"><div className="metric-label">Final equity</div><div className="metric-value">${fmt(m.final_equity)}</div></div>
            </div>
          </div>

          {/* Equity curve (last 20 points) */}
          {result.equity_curve?.length > 0 && (
            <div className="card">
              <div className="card-title">
                Equity curve — {result.equity_curve.length} points
                {result.equity_curve.length > 20 && ' (last 20 shown)'}
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Date</th><th>Equity ($)</th></tr></thead>
                  <tbody>
                    {result.equity_curve.slice(-20).map((pt, i) => (
                      <tr key={i}>
                        <td>{pt.date}</td>
                        <td style={{ fontFamily: 'monospace' }}>${fmt(pt.equity)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Trades — actual shape: {date, ticker, action, shares, price, commission, pnl} */}
          {trades.length > 0 && (
            <div className="card">
              <div className="card-title">Trades ({trades.length})</div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th><th>Ticker</th><th>Action</th>
                      <th>Shares</th><th>Price ($)</th><th>Commission ($)</th><th>P&L ($)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => {
                      const pnl = t.pnl ?? 0
                      return (
                        <tr key={i}>
                          <td>{t.date}</td>
                          <td><strong>{t.ticker}</strong></td>
                          <td>
                            <span className={`badge ${t.action === 'sell' ? 'badge-sell' : 'badge-long'}`}>
                              {t.action?.toUpperCase()}
                            </span>
                          </td>
                          <td style={{ fontFamily: 'monospace' }}>{fmt(t.shares)}</td>
                          <td style={{ fontFamily: 'monospace' }}>{fmt(t.price)}</td>
                          <td style={{ fontFamily: 'monospace', color: 'var(--muted)' }}>{fmt(t.commission)}</td>
                          <td style={{ fontFamily: 'monospace', color: pnl >= 0 ? 'var(--success)' : 'var(--error)' }}>
                            {pnl >= 0 ? '+' : ''}{fmt(pnl)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {trades.length === 0 && result && (
            <div className="empty">No trades were executed in this backtest run.</div>
          )}
        </>
      )}
    </>
  )
}
