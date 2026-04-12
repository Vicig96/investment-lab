import { useState } from 'react'
import { simulatePortfolio, rebalancePortfolio } from '../api.js'

const STRATEGIES = ['ma_crossover', 'relative_momentum', 'trend_filter']

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

function validateSimForm(f) {
  const tickers = f.instrument_tickers.split(',').map(s => s.trim()).filter(Boolean)
  if (!tickers.length) return 'At least one ticker is required.'
  if (!f.date_from)    return '"From" date is required.'
  if (!f.date_to)      return '"To" date is required.'
  if (f.date_from >= f.date_to) return '"From" must be before "To".'
  if (Number(f.initial_capital) <= 0) return 'Initial capital must be > 0.'
  try { JSON.parse(f.params) } catch { return 'Params must be a valid JSON object.' }
  return null
}

function validateRebForm(f) {
  if (Number(f.nav) <= 0) return 'NAV must be > 0.'
  let weights
  try { weights = JSON.parse(f.weights) } catch { return 'Weights must be a valid JSON object.' }
  if (typeof weights !== 'object' || weights === null || Array.isArray(weights))
    return 'Weights must be a JSON object (e.g. {"SPY": 0.6}).'
  const sum = Object.values(weights).reduce((a, b) => a + Number(b), 0)
  if (sum > 1.001) return `Weights sum to ${(sum * 100).toFixed(1)}% — must be ≤ 100%.`
  return null
}

export default function Portfolio() {
  // ── Simulate ─────────────────────────────────────────────────────────────
  const [sim, setSim] = useState({
    strategy_name:      'ma_crossover',
    instrument_tickers: 'SPY',
    date_from:          '2020-01-01',
    date_to:            '2024-12-31',
    initial_capital:    '10000',
    params:             '{}',
  })
  const [simResult,  setSimResult]  = useState(null)
  const [simLoading, setSimLoading] = useState(false)
  const [simError,   setSimError]   = useState(null)
  const [simFormErr, setSimFormErr] = useState(null)

  // ── Rebalance ─────────────────────────────────────────────────────────────
  const [reb, setReb] = useState({ nav: '10000', weights: '{"SPY": 1.0}' })
  const [rebResult,  setRebResult]  = useState(null)
  const [rebLoading, setRebLoading] = useState(false)
  const [rebError,   setRebError]   = useState(null)
  const [rebFormErr, setRebFormErr] = useState(null)

  const setSf = (k, v) => { setSim(p => ({ ...p, [k]: v })); setSimFormErr(null) }
  const setRf = (k, v) => { setReb(p => ({ ...p, [k]: v })); setRebFormErr(null) }

  const runSim = async (e) => {
    e.preventDefault()
    const err = validateSimForm(sim)
    if (err) { setSimFormErr(err); return }

    setSimLoading(true)
    setSimError(null)
    setSimResult(null)
    try {
      const params = JSON.parse(sim.params)
      const data = await simulatePortfolio({
        strategy_name:       sim.strategy_name,
        instrument_tickers:  sim.instrument_tickers.split(',').map(s => s.trim().toUpperCase()).filter(Boolean),
        date_from:           sim.date_from,
        date_to:             sim.date_to,
        initial_capital:     Number(sim.initial_capital),
        params,
      })
      setSimResult(data)
    } catch (err) {
      setSimError(err.message)
    } finally {
      setSimLoading(false)
    }
  }

  const runReb = async (e) => {
    e.preventDefault()
    const err = validateRebForm(reb)
    if (err) { setRebFormErr(err); return }

    setRebLoading(true)
    setRebError(null)
    setRebResult(null)
    try {
      const weights = JSON.parse(reb.weights)
      const data = await rebalancePortfolio(weights, Number(reb.nav))
      setRebResult(data)
    } catch (err) {
      setRebError(err.message)
    } finally {
      setRebLoading(false)
    }
  }

  const sm = simResult?.metrics ?? {}
  // Trades shape: {date, ticker, action, shares, price, commission, pnl}
  const simTrades = simResult?.trades ?? []

  return (
    <>
      <h2 className="section-title">Portfolio</h2>

      {/* ── Simulate ─────────────────────────────────────── */}
      <div className="card">
        <div className="card-title">Simulate</div>
        <form className="form" onSubmit={runSim}>
          <div className="form-row">
            <div className="field">
              <label>Strategy</label>
              <select value={sim.strategy_name} onChange={e => setSf('strategy_name', e.target.value)}>
                {STRATEGIES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="field">
              <label>Tickers (comma-separated)</label>
              <input
                value={sim.instrument_tickers}
                onChange={e => setSf('instrument_tickers', e.target.value.toUpperCase())}
                placeholder="SPY,QQQ"
              />
            </div>
            <div className="field">
              <label>Initial capital ($)</label>
              <input type="number" value={sim.initial_capital} min="1" onChange={e => setSf('initial_capital', e.target.value)} />
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>From *</label>
              <input type="date" value={sim.date_from} onChange={e => setSf('date_from', e.target.value)} required />
            </div>
            <div className="field">
              <label>To *</label>
              <input type="date" value={sim.date_to} onChange={e => setSf('date_to', e.target.value)} required />
            </div>
            <div className="field" style={{ flex: 2 }}>
              <label>Strategy params (JSON)</label>
              <input value={sim.params} onChange={e => setSf('params', e.target.value)} spellCheck={false} />
            </div>
          </div>
          {simFormErr && <div className="field-error">{simFormErr}</div>}
          <div>
            <button className="btn btn-primary" type="submit" disabled={simLoading}>
              {simLoading ? <span className="spinner" /> : null}
              Simulate
            </button>
          </div>
        </form>
        {simError && <div className="alert alert-error">{simError}</div>}
      </div>

      {simResult && (
        <div className="card">
          <div className="card-title">Simulation result — {simResult.snapshot_date}</div>
          <div className="metrics-grid">
            <div className="metric-box"><div className="metric-label">CAGR</div><div className="metric-value">{pct(sm.cagr)}</div></div>
            <div className="metric-box"><div className="metric-label">Sharpe</div><div className="metric-value">{fmt(sm.sharpe_ratio)}</div></div>
            <div className="metric-box"><div className="metric-label">Max drawdown</div><div className="metric-value">{pct(sm.max_drawdown)}</div></div>
            <div className="metric-box"><div className="metric-label">Win rate</div><div className="metric-value">{pct(sm.win_rate)}</div></div>
            <div className="metric-box"><div className="metric-label">Total trades</div><div className="metric-value">{sm.total_trades ?? '—'}</div></div>
            <div className="metric-box"><div className="metric-label">Final equity</div><div className="metric-value">${fmt(sm.final_equity)}</div></div>
          </div>

          {/* Equity curve */}
          {simResult.equity_curve?.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="card-title">
                Equity curve{simResult.equity_curve.length > 20 ? ' (last 20 points)' : ''}
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Date</th><th>Equity ($)</th></tr></thead>
                  <tbody>
                    {simResult.equity_curve.slice(-20).map((pt, i) => (
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
          {simTrades.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="card-title">Trades ({simTrades.length})</div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th><th>Ticker</th><th>Action</th>
                      <th>Shares</th><th>Price ($)</th><th>P&L ($)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {simTrades.map((t, i) => {
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
        </div>
      )}

      {/* ── Rebalance ────────────────────────────────────── */}
      <div className="card">
        <div className="card-title">Rebalance</div>
        <form className="form" onSubmit={runReb}>
          <div className="form-row">
            <div className="field">
              <label>NAV ($)</label>
              <input type="number" value={reb.nav} min="0.01" step="any" onChange={e => setRf('nav', e.target.value)} />
            </div>
            <div className="field" style={{ flex: 3 }}>
              <label>Target weights (JSON — fractions summing to ≤ 1.0)</label>
              <input
                value={reb.weights}
                onChange={e => setRf('weights', e.target.value)}
                placeholder='{"SPY": 0.6, "QQQ": 0.4}'
                spellCheck={false}
              />
            </div>
          </div>
          {rebFormErr && <div className="field-error">{rebFormErr}</div>}
          <div>
            <button className="btn btn-primary" type="submit" disabled={rebLoading}>
              {rebLoading ? <span className="spinner" /> : null}
              Compute rebalance
            </button>
          </div>
        </form>
        {rebError && <div className="alert alert-error">{rebError}</div>}
      </div>

      {rebResult && (
        <div className="card">
          <div className="card-title">
            Rebalance orders — NAV ${fmt(rebResult.nav)} — {rebResult.snapshot_date}
          </div>
          {(rebResult.orders ?? []).length === 0 ? (
            <div className="empty">No orders needed — already at target weights.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th><th>Action</th><th>Current</th><th>Target</th>
                    <th>Delta</th><th>Est. shares</th><th>Est. value ($)</th>
                  </tr>
                </thead>
                <tbody>
                  {rebResult.orders.map((o, i) => (
                    <tr key={i}>
                      <td><strong>{o.ticker}</strong></td>
                      <td>
                        <span className={`badge badge-${o.action}`}>{o.action.toUpperCase()}</span>
                      </td>
                      <td>{pct(o.current_weight)}</td>
                      <td>{pct(o.target_weight)}</td>
                      <td style={{ color: o.delta_weight >= 0 ? 'var(--success)' : 'var(--error)' }}>
                        {o.delta_weight >= 0 ? '+' : ''}{pct(o.delta_weight)}
                      </td>
                      <td style={{ fontFamily: 'monospace' }}>
                        {o.estimated_shares != null ? fmt(o.estimated_shares) : '—'}
                      </td>
                      <td style={{ fontFamily: 'monospace' }}>
                        {o.estimated_value != null ? `$${fmt(o.estimated_value)}` : '—'}
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
