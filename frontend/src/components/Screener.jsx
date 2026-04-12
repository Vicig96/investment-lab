import { useState } from 'react'
import { runScreener } from '../api.js'

const DEFAULT_TICKERS = 'SPY, QQQ, IWM, TLT, GLD'
const DEFAULT_FROM    = '2023-01-01'

// ── Badge style maps ──────────────────────────────────────────────────────────

const LABEL_STYLE = {
  BUY:   { background: '#1a4731', color: '#4ade80', border: '1px solid #166534' },
  WATCH: { background: '#422006', color: '#fb923c', border: '1px solid #92400e' },
  AVOID: { background: '#3b1219', color: '#f87171', border: '1px solid #7f1d1d' },
}

const QUALITY_STYLE = {
  GOOD:         { background: '#1a2e1a', color: '#86efac', border: '1px solid #166534' },
  LIMITED:      { background: '#2d1f00', color: '#fcd34d', border: '1px solid #78350f' },
  INSUFFICIENT: { background: '#1c1c1c', color: '#6b7280', border: '1px solid #374151' },
}

function Badge({ label, styleMap, title }) {
  return (
    <span
      title={title}
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.04em',
        cursor: title ? 'help' : 'default',
        ...(styleMap[label] ?? {}),
      }}
    >
      {label}
    </span>
  )
}

// ── Formatters ────────────────────────────────────────────────────────────────

function pct(v, dec = 2) {
  if (v == null) return <span style={{ color: 'var(--muted)' }}>—</span>
  return `${(v * 100).toFixed(dec)}%`
}

function colorRet(v) {
  if (v == null) return undefined
  return v >= 0 ? 'var(--success)' : 'var(--error)'
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Screener() {
  const [tickers,  setTickers]  = useState(DEFAULT_TICKERS)
  const [dateFrom, setDateFrom] = useState(DEFAULT_FROM)
  const [dateTo,   setDateTo]   = useState('')
  const [topN,     setTopN]     = useState('5')

  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)
  const [result,  setResult]  = useState(null)

  const handleRun = async (e) => {
    e.preventDefault()
    const parsed = tickers.split(',').map(t => t.trim()).filter(Boolean)
    if (parsed.length === 0) {
      setError('Enter at least one ticker.')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const parsedTopN = parseInt(topN, 10)
      const body = {
        instrument_tickers: parsed,
        top_n: Math.max(1, Math.min(50, Number.isNaN(parsedTopN) ? 5 : parsedTopN)),
      }
      if (dateFrom) body.date_from = dateFrom
      if (dateTo)   body.date_to   = dateTo
      const data = await runScreener(body)
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Derived counts from result
  const counts = result ? {
    buy:          result.ranked_assets.filter(a => a.label === 'BUY').length,
    watch:        result.ranked_assets.filter(a => a.label === 'WATCH').length,
    avoid:        result.ranked_assets.filter(a => a.label === 'AVOID').length,
    good:         result.ranked_assets.filter(a => a.data_quality === 'GOOD').length,
    limited:      result.ranked_assets.filter(a => a.data_quality === 'LIMITED').length,
    insufficient: result.ranked_assets.filter(a => a.data_quality === 'INSUFFICIENT').length,
  } : null

  // True if every asset has poor data — show a prominent banner
  const allDataPoor = result && counts.good === 0

  return (
    <>
      <h2 className="section-title">Market Screener</h2>

      {/* ── Config form ── */}
      <div className="card">
        <div className="card-title">Configure</div>
        <form className="form" onSubmit={handleRun}>
          <div className="field">
            <label>Tickers (comma-separated)</label>
            <input
              type="text"
              value={tickers}
              onChange={e => { setTickers(e.target.value); setError(null) }}
              placeholder="SPY, QQQ, IWM, TLT, GLD"
              spellCheck={false}
            />
          </div>
          <div className="form-row">
            <div className="field">
              <label>From date</label>
              <input
                type="date"
                value={dateFrom}
                onChange={e => setDateFrom(e.target.value)}
              />
            </div>
            <div className="field">
              <label>To date</label>
              <input
                type="date"
                value={dateTo}
                onChange={e => setDateTo(e.target.value)}
              />
            </div>
            <div className="field" style={{ maxWidth: 140 }}>
              <label>Top N for weights</label>
              <input
                type="number"
                min={1}
                max={50}
                value={topN}
                onChange={e => setTopN(e.target.value)}
              />
            </div>
          </div>
          <div>
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? <span className="spinner" /> : null}
              Run Screener
            </button>
          </div>
        </form>
        {error && <div className="alert alert-error">{error}</div>}
      </div>

      {!result && !loading && !error && (
        <div className="empty" style={{ paddingTop: 40 }}>
          Enter tickers and click Run Screener to rank your universe.
        </div>
      )}

      {result && (
        <>
          {/* ── Data quality warning banner ── */}
          {allDataPoor && (
            <div className="alert alert-error" style={{ marginBottom: 0 }}>
              ⚠ No asset has sufficient history for reliable scoring (all LIMITED or INSUFFICIENT).
              Extend <strong>From date</strong> to provide at least 200 bars per instrument.
            </div>
          )}
          {!allDataPoor && (counts.limited + counts.insufficient) > 0 && (
            <div className="alert" style={{
              marginBottom: 0,
              background: '#2d1f00',
              color: '#fcd34d',
              border: '1px solid #78350f',
            }}>
              ⚠ {counts.limited + counts.insufficient} instrument{(counts.limited + counts.insufficient) !== 1 ? 's' : ''} have
              limited history — hover the Quality badge to see which metrics are null.
            </div>
          )}

          {/* ── Summary cards ── */}
          <div className="card">
            <div className="card-title">
              Snapshot — {result.snapshot_date}
              &nbsp;·&nbsp;
              {result.universe_size} instrument{result.universe_size !== 1 ? 's' : ''}
            </div>
            <div className="metrics-grid">
              <div className="metric-box">
                <div className="metric-label">Universe</div>
                <div className="metric-value">{result.universe_size}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">BUY</div>
                <div className="metric-value" style={{ color: '#4ade80' }}>{counts.buy}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">WATCH</div>
                <div className="metric-value" style={{ color: '#fb923c' }}>{counts.watch}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">AVOID</div>
                <div className="metric-value" style={{ color: '#f87171' }}>{counts.avoid}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Data OK</div>
                <div className="metric-value" style={{ color: '#86efac' }}>{counts.good}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Limited</div>
                <div className="metric-value" style={{ color: '#fcd34d' }}>{counts.limited}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Insuff.</div>
                <div className="metric-value" style={{ color: '#6b7280' }}>{counts.insufficient}</div>
              </div>
            </div>
          </div>

          {/* ── Ranked table ── */}
          <div className="card">
            <div className="card-title">Ranked Assets</div>
            {result.ranked_assets.length === 0 ? (
              <div className="empty">No assets to display.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 28 }}>#</th>
                      <th>Ticker</th>
                      <th>Score</th>
                      <th>Label</th>
                      <th>Quality</th>
                      <th>Bars</th>
                      <th>Ret 20d</th>
                      <th>Ret 60d</th>
                      <th>Ret 120d</th>
                      <th>vs SMA50</th>
                      <th>vs SMA200</th>
                      <th>Vol 20d</th>
                      <th>DD 60d</th>
                      <th>Weight</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.ranked_assets.map((a, i) => {
                      const isInsuff = a.data_quality === 'INSUFFICIENT'
                      const rowStyle = isInsuff ? { opacity: 0.55 } : undefined
                      return (
                        <tr key={a.ticker} style={rowStyle}>
                          <td style={{ color: 'var(--muted)', fontSize: 12 }}>{i + 1}</td>
                          <td>
                            <strong style={{ fontFamily: 'monospace' }}>{a.ticker}</strong>
                          </td>
                          <td style={{ fontFamily: 'monospace' }}>
                            {a.score.toFixed(4)}
                          </td>
                          <td>
                            <Badge label={a.label} styleMap={LABEL_STYLE} />
                          </td>
                          <td>
                            <Badge
                              label={a.data_quality}
                              styleMap={QUALITY_STYLE}
                              title={a.insufficient_history_reason ?? undefined}
                            />
                          </td>
                          <td style={{ fontFamily: 'monospace', color: 'var(--muted)', textAlign: 'right' }}>
                            {a.history_bars}
                          </td>
                          <td style={{ fontFamily: 'monospace', color: colorRet(a.ret_20d) }}>
                            {pct(a.ret_20d)}
                          </td>
                          <td style={{ fontFamily: 'monospace', color: colorRet(a.ret_60d) }}>
                            {pct(a.ret_60d)}
                          </td>
                          <td style={{ fontFamily: 'monospace', color: colorRet(a.ret_120d) }}>
                            {pct(a.ret_120d)}
                          </td>
                          <td style={{ fontFamily: 'monospace', color: colorRet(a.dist_sma_50) }}>
                            {pct(a.dist_sma_50)}
                          </td>
                          <td style={{ fontFamily: 'monospace', color: colorRet(a.dist_sma_200) }}>
                            {pct(a.dist_sma_200)}
                          </td>
                          <td style={{ fontFamily: 'monospace', color: 'var(--muted)' }}>
                            {pct(a.vol_20d)}
                          </td>
                          <td style={{ fontFamily: 'monospace', color: 'var(--error)' }}>
                            {pct(a.drawdown_60d)}
                          </td>
                          <td style={{ fontFamily: 'monospace', fontWeight: a.suggested_weight != null ? 600 : 'normal' }}>
                            {a.suggested_weight != null
                              ? <span style={{ color: '#4ade80' }}>{pct(a.suggested_weight)}</span>
                              : <span style={{ color: 'var(--muted)' }}>—</span>
                            }
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  )
}
