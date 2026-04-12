import { useState } from 'react'
import { runScreenerRotation } from '../api.js'

const DEFAULT = {
  instrument_tickers: 'SPY, QQQ, IWM, TLT, GLD',
  date_from: '2021-01-01',
  date_to: '2023-12-31',
  top_n: '3',
  initial_capital: '10000',
  commission_bps: '10',
  rebalance_frequency: 'monthly',
  warmup_bars: '252',
}

const STRATEGY_COLOR = 'var(--success)'
const BENCHMARK_COLOR = '#60a5fa'

function fmt(value, decimals = 2) {
  if (value == null || value === '') return '-'
  const num = Number(value)
  return Number.isNaN(num) ? String(value) : num.toFixed(decimals)
}

function pct(value, decimals = 2) {
  if (value == null) return '-'
  const num = Number(value)
  return Number.isNaN(num) ? '-' : `${(num * 100).toFixed(decimals)}%`
}

function absPct(value, decimals = 2) {
  if (value == null) return '-'
  const num = Number(value)
  return Number.isNaN(num) ? '-' : `${(Math.abs(num) * 100).toFixed(decimals)}%`
}

function colorVal(value) {
  if (value == null) return undefined
  return Number(value) >= 0 ? 'var(--success)' : 'var(--error)'
}

function buildDateIndex(pointsA, pointsB) {
  const dates = Array.from(
    new Set([
      ...pointsA.map((point) => point.date),
      ...pointsB.map((point) => point.date),
    ]),
  ).sort()

  return {
    count: dates.length,
    lookup: new Map(dates.map((date, index) => [date, index])),
  }
}

function buildEquityCurvePoints(points, width, height, padding, lookup, count, minValue, maxValue) {
  if (!Array.isArray(points) || points.length === 0 || count === 0) return ''

  const xSpan = Math.max(1, width - padding * 2)
  const ySpan = Math.max(1, height - padding * 2)
  const range = maxValue - minValue || 1

  return points
    .map((point) => {
      const xIndex = lookup.get(point?.date)
      const equity = Number(point?.equity)
      if (xIndex == null || !Number.isFinite(equity)) return null
      const x = padding + (xSpan * xIndex) / Math.max(1, count - 1)
      const y = height - padding - ((equity - minValue) / range) * ySpan
      return `${x},${y}`
    })
    .filter(Boolean)
    .join(' ')
}

function validate(form) {
  const tickers = form.instrument_tickers.split(',').map((value) => value.trim()).filter(Boolean)
  if (!tickers.length) return 'At least one ticker is required.'
  if (!form.date_from) return '"From" date is required.'
  if (!form.date_to) return '"To" date is required.'
  if (form.date_from >= form.date_to) return '"From" must be before "To".'
  if (Number(form.top_n) <= 0) return 'Top N must be > 0.'
  if (Number(form.initial_capital) <= 0) return 'Initial capital must be > 0.'
  if (Number(form.commission_bps) < 0) return 'Commission must be >= 0.'
  if (Number(form.warmup_bars) < 0) return 'Warm-up bars must be >= 0.'
  return null
}

export default function ScreenerRotation() {
  const [form, setForm] = useState(DEFAULT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [formError, setFormError] = useState(null)
  const [result, setResult] = useState(null)

  const setField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setFormError(null)
  }

  const submit = async (event) => {
    event.preventDefault()

    const validationError = validate(form)
    if (validationError) {
      setFormError(validationError)
      return
    }

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const payload = {
        instrument_tickers: form.instrument_tickers
          .split(',')
          .map((value) => value.trim().toUpperCase())
          .filter(Boolean),
        date_from: form.date_from,
        date_to: form.date_to,
        top_n: Math.max(1, Math.min(20, parseInt(form.top_n, 10) || 3)),
        initial_capital: Number(form.initial_capital),
        commission_bps: Number(form.commission_bps),
        rebalance_frequency: form.rebalance_frequency,
        warmup_bars: Math.max(0, Math.min(1000, parseInt(form.warmup_bars, 10) || 252)),
      }

      const data = await runScreenerRotation(payload)
      setResult(data)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const metrics = result?.metrics ?? {}
  const benchmark = result?.benchmark ?? null
  const benchmarkCurve = benchmark?.equity_curve ?? []
  const equityCurve = result?.equity_curve ?? []
  const rebalanceLog = result?.rebalance_log ?? []
  const trades = result?.trades ?? []
  const universe = result?.universe ?? []
  const cashOnlyCount = rebalanceLog.filter((row) => row.cash_only).length

  const chartWidth = 860
  const chartHeight = 260
  const chartPadding = 24
  const { lookup: chartDateIndex, count: chartDateCount } = buildDateIndex(equityCurve, benchmarkCurve)
  const chartValues = [...equityCurve, ...benchmarkCurve]
    .map((point) => Number(point?.equity))
    .filter((value) => Number.isFinite(value))
  const minChartEquity = chartValues.length ? Math.min(...chartValues) : 0
  const maxChartEquity = chartValues.length ? Math.max(...chartValues) : 1
  const strategyLine = buildEquityCurvePoints(
    equityCurve,
    chartWidth,
    chartHeight,
    chartPadding,
    chartDateIndex,
    chartDateCount,
    minChartEquity,
    maxChartEquity,
  )
  const benchmarkLine = buildEquityCurvePoints(
    benchmarkCurve,
    chartWidth,
    chartHeight,
    chartPadding,
    chartDateIndex,
    chartDateCount,
    minChartEquity,
    maxChartEquity,
  )

  return (
    <>
      <h2 className="section-title">Screener Rotation Backtest</h2>

      <div className="card">
        <div className="card-title">Configuration</div>
        <form className="form" onSubmit={submit}>
          <div className="field">
            <label>Tickers (comma-separated)</label>
            <input
              type="text"
              value={form.instrument_tickers}
              onChange={(event) => setField('instrument_tickers', event.target.value.toUpperCase())}
              placeholder="SPY, QQQ, IWM, TLT, GLD"
              spellCheck={false}
            />
          </div>

          <div className="form-row">
            <div className="field">
              <label>From *</label>
              <input
                type="date"
                value={form.date_from}
                onChange={(event) => setField('date_from', event.target.value)}
                required
              />
            </div>
            <div className="field">
              <label>To *</label>
              <input
                type="date"
                value={form.date_to}
                onChange={(event) => setField('date_to', event.target.value)}
                required
              />
            </div>
            <div className="field" style={{ maxWidth: 120 }}>
              <label>Top N</label>
              <input
                type="number"
                min="1"
                max="20"
                value={form.top_n}
                onChange={(event) => setField('top_n', event.target.value)}
              />
            </div>
          </div>

          <div className="form-row">
            <div className="field">
              <label>Initial capital ($)</label>
              <input
                type="number"
                min="1"
                value={form.initial_capital}
                onChange={(event) => setField('initial_capital', event.target.value)}
              />
            </div>
            <div className="field" style={{ maxWidth: 160 }}>
              <label>Commission (bps)</label>
              <input
                type="number"
                min="0"
                value={form.commission_bps}
                onChange={(event) => setField('commission_bps', event.target.value)}
              />
            </div>
            <div className="field" style={{ maxWidth: 180 }}>
              <label>Rebalance frequency</label>
              <select
                value={form.rebalance_frequency}
                onChange={(event) => setField('rebalance_frequency', event.target.value)}
              >
                <option value="monthly">monthly</option>
              </select>
            </div>
            <div className="field" style={{ maxWidth: 160 }}>
              <label>Warm-up bars</label>
              <input
                type="number"
                min="0"
                max="1000"
                value={form.warmup_bars}
                onChange={(event) => setField('warmup_bars', event.target.value)}
              />
            </div>
          </div>

          {formError && <div className="field-error">{formError}</div>}

          <div>
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? <span className="spinner" /> : null}
              Run Backtest
            </button>
          </div>
        </form>

        {error && <div className="alert alert-error" style={{ marginTop: 12 }}>{error}</div>}
      </div>

      {!result && !loading && !error && (
        <div className="empty" style={{ paddingTop: 40 }}>
          Configure the parameters above and click Run Backtest.
        </div>
      )}

      {loading && (
        <div className="empty" style={{ paddingTop: 24 }}>
          Running screener rotation backtest...
        </div>
      )}

      {result && (
        <>
          <div className="card">
            <div className="card-title">
              Strategy summary - {result.date_from} to {result.date_to}
              {universe.length > 0 ? ` - universe: ${universe.join(', ')}` : ''}
            </div>

            <div className="metrics-grid">
              <div className="metric-box">
                <div className="metric-label">Final equity</div>
                <div className="metric-value">${fmt(metrics.final_equity)}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">CAGR</div>
                <div className="metric-value" style={{ color: colorVal(metrics.cagr) }}>
                  {pct(metrics.cagr)}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Sharpe</div>
                <div className="metric-value" style={{ color: colorVal(metrics.sharpe_ratio) }}>
                  {fmt(metrics.sharpe_ratio)}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Max drawdown</div>
                <div className="metric-value" style={{ color: 'var(--error)' }}>
                  {absPct(metrics.max_drawdown)}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Calmar</div>
                <div className="metric-value">{fmt(metrics.calmar_ratio)}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Win rate</div>
                <div className="metric-value">{pct(metrics.win_rate)}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Total trades</div>
                <div className="metric-value">{metrics.total_trades ?? '-'}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Rebalances</div>
                <div className="metric-value">{rebalanceLog.length}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Cash-only periods</div>
                <div className="metric-value" style={{ color: cashOnlyCount > 0 ? 'var(--warning)' : undefined }}>
                  {cashOnlyCount}
                </div>
              </div>
            </div>

            <div
              style={{
                marginTop: 14,
                padding: '8px 14px',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                fontSize: 13,
                color: 'var(--muted)',
                display: 'flex',
                flexWrap: 'wrap',
                gap: 20,
              }}
            >
              <span>
                Warm-up requested: <strong style={{ color: 'var(--text)' }}>{result.warmup_bars_requested} bars</strong>
              </span>
              <span>
                Warm-up available:{' '}
                <strong
                  style={{
                    color:
                      result.warmup_bars_available >= result.warmup_bars_requested
                        ? 'var(--success)'
                        : 'var(--warning)',
                  }}
                >
                  {result.warmup_bars_available} bars
                </strong>
                {result.warmup_bars_available < result.warmup_bars_requested && (
                  <span style={{ color: 'var(--warning)', marginLeft: 8 }}>
                    less than requested, so early rebalance signals may be weaker
                  </span>
                )}
              </span>
            </div>
          </div>

          <div className="card">
            <div className="card-title">
              Benchmark summary - {benchmark?.ticker ?? 'SPY'} buy-and-hold
            </div>

            <div className="metrics-grid">
              <div className="metric-box">
                <div className="metric-label">Final equity</div>
                <div className="metric-value">${fmt(benchmark?.final_equity)}</div>
              </div>
              <div className="metric-box">
                <div className="metric-label">CAGR</div>
                <div className="metric-value" style={{ color: colorVal(benchmark?.cagr) }}>
                  {pct(benchmark?.cagr)}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Sharpe</div>
                <div className="metric-value" style={{ color: colorVal(benchmark?.sharpe_ratio) }}>
                  {fmt(benchmark?.sharpe_ratio)}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Max drawdown</div>
                <div className="metric-value" style={{ color: 'var(--error)' }}>
                  {absPct(benchmark?.max_drawdown)}
                </div>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-title">Strategy vs benchmark equity</div>

            {(equityCurve.length > 0 || benchmarkCurve.length > 0) ? (
              <>
                <div
                  style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 18,
                    marginBottom: 12,
                    color: 'var(--muted)',
                    fontSize: 13,
                  }}
                >
                  <span>
                    <span style={{ color: STRATEGY_COLOR, fontWeight: 700 }}>Strategy</span>
                    {' '}({equityCurve.length} points)
                  </span>
                  <span>
                    <span style={{ color: BENCHMARK_COLOR, fontWeight: 700 }}>{benchmark?.ticker ?? 'SPY'}</span>
                    {' '}buy-and-hold ({benchmarkCurve.length} points)
                  </span>
                </div>

                <div style={{ marginBottom: 12 }}>
                  <svg
                    viewBox={`0 0 ${chartWidth} ${chartHeight}`}
                    width="100%"
                    height="260"
                    role="img"
                    aria-label="Strategy and benchmark equity curve chart"
                    style={{
                      display: 'block',
                      border: '1px solid var(--border)',
                      borderRadius: 8,
                      background: 'linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0))',
                    }}
                  >
                    <line
                      x1={chartPadding}
                      y1={chartHeight - chartPadding}
                      x2={chartWidth - chartPadding}
                      y2={chartHeight - chartPadding}
                      stroke="var(--border)"
                      strokeWidth="1"
                    />
                    <line
                      x1={chartPadding}
                      y1={chartPadding}
                      x2={chartPadding}
                      y2={chartHeight - chartPadding}
                      stroke="var(--border)"
                      strokeWidth="1"
                    />
                    {benchmarkLine && (
                      <polyline
                        fill="none"
                        stroke={BENCHMARK_COLOR}
                        strokeWidth="3"
                        strokeLinejoin="round"
                        strokeLinecap="round"
                        points={benchmarkLine}
                      />
                    )}
                    {strategyLine && (
                      <polyline
                        fill="none"
                        stroke={STRATEGY_COLOR}
                        strokeWidth="3"
                        strokeLinejoin="round"
                        strokeLinecap="round"
                        points={strategyLine}
                      />
                    )}
                  </svg>
                </div>
              </>
            ) : (
              <div className="empty">No equity-curve data was returned for this run.</div>
            )}
          </div>

          <div className="card">
            <div className="card-title">
              Rebalance log
              {rebalanceLog.length > 0 ? ` - ${rebalanceLog.length} periods` : ''}
            </div>

            {rebalanceLog.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th style={{ textAlign: 'right' }}>Eligible</th>
                      <th>Allocation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rebalanceLog.map((row, index) => (
                      <tr key={index}>
                        <td style={{ fontFamily: 'monospace' }}>{row.date}</td>
                        <td
                          style={{
                            fontFamily: 'monospace',
                            textAlign: 'right',
                            color: 'var(--muted)',
                          }}
                        >
                          {row.eligible_count}
                        </td>
                        <td>
                          {row.cash_only ? (
                            <span style={{ color: 'var(--muted)', fontStyle: 'italic' }}>cash only</span>
                          ) : (
                            Object.entries(row.weights ?? {}).map(([ticker, weight]) => (
                              <span
                                key={ticker}
                                style={{
                                  display: 'inline-block',
                                  marginRight: 14,
                                  fontFamily: 'monospace',
                                  fontSize: 12,
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                <strong>{ticker}</strong>{' '}
                                <span style={{ color: 'var(--muted)' }}>{pct(weight)}</span>
                              </span>
                            ))
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty">No rebalance periods were returned for this run.</div>
            )}
          </div>

          {trades.length > 0 ? (
            <div className="card">
              <div className="card-title">Trades ({trades.length})</div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Ticker</th>
                      <th>Action</th>
                      <th style={{ textAlign: 'right' }}>Shares</th>
                      <th style={{ textAlign: 'right' }}>Price ($)</th>
                      <th style={{ textAlign: 'right' }}>Commission ($)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((trade, index) => (
                      <tr key={index}>
                        <td>{trade.date}</td>
                        <td>
                          <strong style={{ fontFamily: 'monospace' }}>{trade.ticker}</strong>
                        </td>
                        <td>
                          <span className={`badge ${trade.action === 'sell' ? 'badge-sell' : 'badge-long'}`}>
                            {trade.action?.toUpperCase()}
                          </span>
                        </td>
                        <td style={{ fontFamily: 'monospace', textAlign: 'right' }}>
                          {fmt(trade.shares, 4)}
                        </td>
                        <td style={{ fontFamily: 'monospace', textAlign: 'right' }}>
                          {fmt(trade.price)}
                        </td>
                        <td
                          style={{
                            fontFamily: 'monospace',
                            textAlign: 'right',
                            color: 'var(--muted)',
                          }}
                        >
                          {fmt(trade.commission)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="card">
              <div className="card-title">Trades</div>
              <div className="empty">No trades were executed in this backtest run.</div>
            </div>
          )}
        </>
      )}
    </>
  )
}
