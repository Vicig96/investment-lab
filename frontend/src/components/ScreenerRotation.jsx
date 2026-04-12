import { useState } from 'react'
import { runScreenerRotation } from '../api.js'

const DEFAULT = {
  run_mode: 'single',
  instrument_tickers: 'SPY, QQQ, IWM, TLT, GLD',
  date_from: '2021-01-01',
  date_to: '2023-12-31',
  top_n: '3',
  initial_capital: '10000',
  commission_bps: '10',
  rebalance_frequency: 'monthly',
  warmup_bars: '252',
  defensive_mode: 'cash',
  defensive_tickers: 'TLT, GLD',
}

const STRATEGY_COLOR = 'var(--success)'
const BENCHMARK_COLOR = '#60a5fa'
const CASH_COLOR = '#f59e0b'
const DEFENSIVE_COLOR = '#22c55e'
const BEST_CELL_STYLE = {
  background: 'rgba(34, 197, 94, 0.10)',
  color: 'var(--success)',
  fontWeight: 700,
}

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

function parseTickerList(value) {
  return value
    .split(',')
    .map((ticker) => ticker.trim().toUpperCase())
    .filter(Boolean)
}

function allocationLabel(mode) {
  if (mode === 'risk_on') return 'Risk-on'
  if (mode === 'defensive') return 'Defensive'
  return 'Cash'
}

function calcCalmar(cagr, maxDrawdown) {
  const c = Number(cagr)
  const md = Number(maxDrawdown)
  if (!Number.isFinite(c) || !Number.isFinite(md) || md === 0) return null
  return c / Math.abs(md)
}

function validate(form) {
  const tickers = parseTickerList(form.instrument_tickers)
  if (!tickers.length) return 'At least one ticker is required.'
  if (!form.date_from) return '"From" date is required.'
  if (!form.date_to) return '"To" date is required.'
  if (form.date_from >= form.date_to) return '"From" must be before "To".'
  if (Number(form.top_n) <= 0) return 'Top N must be > 0.'
  if (Number(form.initial_capital) <= 0) return 'Initial capital must be > 0.'
  if (Number(form.commission_bps) < 0) return 'Commission must be >= 0.'
  if (Number(form.warmup_bars) < 0) return 'Warm-up bars must be >= 0.'
  if (
    (form.run_mode === 'compare_variants' || form.defensive_mode === 'defensive_asset')
    && parseTickerList(form.defensive_tickers).length === 0
  ) {
    return 'Add at least one defensive ticker for defensive-asset comparisons.'
  }
  return null
}

function buildBasePayload(form) {
  return {
    instrument_tickers: parseTickerList(form.instrument_tickers),
    date_from: form.date_from,
    date_to: form.date_to,
    top_n: Math.max(1, Math.min(20, parseInt(form.top_n, 10) || 3)),
    initial_capital: Number(form.initial_capital),
    commission_bps: Number(form.commission_bps),
    rebalance_frequency: form.rebalance_frequency,
    warmup_bars: Math.max(0, Math.min(1000, parseInt(form.warmup_bars, 10) || 252)),
    defensive_tickers: parseTickerList(form.defensive_tickers),
  }
}

function numericValue(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function getBestValue(rows, metricKey, preference) {
  const values = rows
    .map((row) => {
      const value = numericValue(row.metrics[metricKey])
      if (value == null) return null
      return metricKey === 'max_drawdown' ? Math.abs(value) : value
    })
    .filter((value) => value != null)

  if (!values.length) return null
  return preference === 'lower' ? Math.min(...values) : Math.max(...values)
}

function isBestMetric(rows, metricKey, preference, candidate) {
  const bestValue = getBestValue(rows, metricKey, preference)
  const currentValue = numericValue(candidate)
  if (bestValue == null || currentValue == null) return false
  const comparable = metricKey === 'max_drawdown' ? Math.abs(currentValue) : currentValue
  return Math.abs(comparable - bestValue) < 1e-9
}

// ── Delta helpers ─────────────────────────────────────────────────────────────

// Compute signed deltas between two metrics objects (a minus b).
// Convention: positive always means "a is better than b" for that metric.
//   equity / cagr / sharpe: higher is better → a - b
//   max_drawdown:            lower abs is better → |b_dd| - |a_dd|
function calcDeltas(aMetrics, bMetrics) {
  const a = aMetrics ?? {}
  const b = bMetrics ?? {}
  const n = numericValue
  const av = (k) => n(a[k])
  const bv = (k) => n(b[k])

  const eq = av('final_equity') != null && bv('final_equity') != null
    ? av('final_equity') - bv('final_equity') : null
  const cagr = av('cagr') != null && bv('cagr') != null
    ? av('cagr') - bv('cagr') : null
  const sharpe = av('sharpe_ratio') != null && bv('sharpe_ratio') != null
    ? av('sharpe_ratio') - bv('sharpe_ratio') : null
  // Positive = a had smaller drawdown = improvement over b
  const dd = av('max_drawdown') != null && bv('max_drawdown') != null
    ? Math.abs(bv('max_drawdown')) - Math.abs(av('max_drawdown')) : null

  return { eq, cagr, sharpe, dd }
}

// Renders a single right-aligned delta cell with automatic sign + color.
function DeltaCell({ value, format }) {
  if (value == null) {
    return (
      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--muted)' }}>—</td>
    )
  }
  const color = value > 0 ? 'var(--success)' : value < 0 ? 'var(--error)' : 'var(--muted)'
  const prefix = value > 0 ? '+' : ''
  return (
    <td style={{ textAlign: 'right', fontFamily: 'monospace', color }}>
      {prefix}{format(value)}
    </td>
  )
}

export default function ScreenerRotation() {
  const [form, setForm] = useState(DEFAULT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [formError, setFormError] = useState(null)
  const [singleResult, setSingleResult] = useState(null)
  const [comparisonResult, setComparisonResult] = useState(null)

  const setField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setFormError(null)
  }

  const submit = async (event) => {
    event.preventDefault()
    if (loading) return

    const validationError = validate(form)
    if (validationError) {
      setFormError(validationError)
      return
    }

    setLoading(true)
    setError(null)
    setSingleResult(null)
    setComparisonResult(null)

    try {
      const basePayload = buildBasePayload(form)

      if (form.run_mode === 'compare_variants') {
        const [cashVariant, defensiveVariant] = await Promise.allSettled([
          runScreenerRotation({ ...basePayload, defensive_mode: 'cash' }),
          runScreenerRotation({ ...basePayload, defensive_mode: 'defensive_asset' }),
        ])

        if (cashVariant.status !== 'fulfilled' || defensiveVariant.status !== 'fulfilled') {
          const reasons = [
            cashVariant.status !== 'fulfilled' ? `cash variant: ${cashVariant.reason?.message ?? 'request failed'}` : null,
            defensiveVariant.status !== 'fulfilled' ? `defensive-asset variant: ${defensiveVariant.reason?.message ?? 'request failed'}` : null,
          ].filter(Boolean)

          throw new Error(`Comparison run failed. ${reasons.join(' | ')}`)
        }

        setComparisonResult({
          cashVariant: cashVariant.value,
          defensiveVariant: defensiveVariant.value,
          benchmark: cashVariant.value.benchmark,
        })
      } else {
        const data = await runScreenerRotation({
          ...basePayload,
          defensive_mode: form.defensive_mode,
        })
        setSingleResult(data)
      }
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const result = singleResult
  const metrics = result?.metrics ?? {}
  const benchmark = result?.benchmark ?? null
  const benchmarkCurve = benchmark?.equity_curve ?? []
  const equityCurve = result?.equity_curve ?? []
  const rebalanceLog = result?.rebalance_log ?? []
  const trades = result?.trades ?? []
  const universe = result?.universe ?? []
  const cashOnlyCount = rebalanceLog.filter((row) => row.cash_only).length
  const defensivePeriods = rebalanceLog.filter((row) => row.allocation_mode === 'defensive').length

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

  const comparisonRows = comparisonResult ? [
    {
      label: 'Rotation - cash',
      color: CASH_COLOR,
      metrics: comparisonResult.cashVariant.metrics,
    },
    {
      label: 'Rotation - defensive asset',
      color: DEFENSIVE_COLOR,
      metrics: comparisonResult.defensiveVariant.metrics,
    },
    {
      label: `${comparisonResult.benchmark?.ticker ?? 'SPY'} buy-and-hold`,
      color: BENCHMARK_COLOR,
      metrics: {
        final_equity: comparisonResult.benchmark?.final_equity,
        cagr: comparisonResult.benchmark?.cagr,
        sharpe_ratio: comparisonResult.benchmark?.sharpe_ratio,
        max_drawdown: comparisonResult.benchmark?.max_drawdown,
        calmar_ratio: calcCalmar(
          comparisonResult.benchmark?.cagr,
          comparisonResult.benchmark?.max_drawdown,
        ),
        total_trades: 0,
      },
    },
  ] : []

  // Delta rows: signed differences, positive = first variant is better
  const bmMetrics = comparisonResult ? {
    final_equity: comparisonResult.benchmark?.final_equity,
    cagr:         comparisonResult.benchmark?.cagr,
    sharpe_ratio: comparisonResult.benchmark?.sharpe_ratio,
    max_drawdown: comparisonResult.benchmark?.max_drawdown,
  } : null
  const deltaRows = comparisonResult ? [
    {
      label: 'Cash vs benchmark',
      color: CASH_COLOR,
      d: calcDeltas(comparisonResult.cashVariant.metrics, bmMetrics),
    },
    {
      label: 'Defensive vs benchmark',
      color: DEFENSIVE_COLOR,
      d: calcDeltas(comparisonResult.defensiveVariant.metrics, bmMetrics),
    },
    {
      label: 'Defensive vs cash',
      color: 'var(--muted)',
      d: calcDeltas(comparisonResult.defensiveVariant.metrics, comparisonResult.cashVariant.metrics),
    },
  ] : []

  return (
    <>
      <h2 className="section-title">Screener Rotation Backtest</h2>

      <div className="card">
        <div className="card-title">Configuration</div>
        <form className="form" onSubmit={submit}>
          <div className="form-row">
            <div className="field" style={{ maxWidth: 240 }}>
              <label>Run mode</label>
              <select
                value={form.run_mode}
                onChange={(event) => setField('run_mode', event.target.value)}
                disabled={loading}
              >
                <option value="single">Single run</option>
                <option value="compare_variants">Compare variants</option>
              </select>
            </div>
          </div>

          <div className="field">
            <label>Tickers (comma-separated)</label>
            <input
              type="text"
              value={form.instrument_tickers}
              onChange={(event) => setField('instrument_tickers', event.target.value.toUpperCase())}
              placeholder="SPY, QQQ, IWM, TLT, GLD"
              spellCheck={false}
              disabled={loading}
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
                disabled={loading}
              />
            </div>
            <div className="field">
              <label>To *</label>
              <input
                type="date"
                value={form.date_to}
                onChange={(event) => setField('date_to', event.target.value)}
                required
                disabled={loading}
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
                disabled={loading}
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
                disabled={loading}
              />
            </div>
            <div className="field" style={{ maxWidth: 160 }}>
              <label>Commission (bps)</label>
              <input
                type="number"
                min="0"
                value={form.commission_bps}
                onChange={(event) => setField('commission_bps', event.target.value)}
                disabled={loading}
              />
            </div>
            <div className="field" style={{ maxWidth: 180 }}>
              <label>Rebalance frequency</label>
              <select
                value={form.rebalance_frequency}
                onChange={(event) => setField('rebalance_frequency', event.target.value)}
                disabled={loading}
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
                disabled={loading}
              />
            </div>
          </div>

          <div className="form-row">
            <div className="field" style={{ maxWidth: 220 }}>
              <label>Defensive behavior</label>
              <select
                value={form.defensive_mode}
                onChange={(event) => setField('defensive_mode', event.target.value)}
                disabled={loading || form.run_mode === 'compare_variants'}
                style={form.run_mode === 'compare_variants' ? { opacity: 0.6 } : undefined}
              >
                <option value="cash">Stay in cash</option>
                <option value="defensive_asset">Use defensive asset</option>
              </select>
            </div>
            <div className="field">
              <label>Defensive tickers priority</label>
              <input
                type="text"
                value={form.defensive_tickers}
                onChange={(event) => setField('defensive_tickers', event.target.value.toUpperCase())}
                placeholder="TLT, GLD"
                spellCheck={false}
                disabled={loading}
              />
            </div>
          </div>

          {form.run_mode === 'compare_variants' && (
            <div
              style={{
                marginBottom: 12,
                color: 'var(--muted)',
                fontSize: 13,
              }}
            >
              Compare mode runs both rotation variants automatically: `cash` and `defensive_asset`.
            </div>
          )}

          {formError && <div className="field-error">{formError}</div>}

          <div>
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? <span className="spinner" /> : null}
              {form.run_mode === 'compare_variants' ? 'Run Comparison' : 'Run Backtest'}
            </button>
          </div>
        </form>

        {error && <div className="alert alert-error" style={{ marginTop: 12 }}>{error}</div>}
      </div>

      {!singleResult && !comparisonResult && !loading && !error && (
        <div className="empty" style={{ paddingTop: 40 }}>
          Configure the parameters above and run a single backtest or compare both variants.
        </div>
      )}

      {loading && (
        <div className="empty" style={{ paddingTop: 24 }}>
          {form.run_mode === 'compare_variants'
            ? 'Running both Screener Rotation variants. The comparison table will appear only after both finish successfully.'
            : 'Running screener rotation backtest...'}
        </div>
      )}

      {comparisonResult && (
        <div className="card">
          <div className="card-title">
            Variant comparison - {comparisonResult.cashVariant.date_from} to {comparisonResult.cashVariant.date_to}
          </div>
          <div
            style={{
              marginBottom: 12,
              color: 'var(--muted)',
              fontSize: 13,
            }}
          >
            Defensive tickers priority: <strong style={{ color: 'var(--text)' }}>{parseTickerList(form.defensive_tickers).join(', ')}</strong>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Variant</th>
                  <th style={{ textAlign: 'right' }}>Final equity</th>
                  <th style={{ textAlign: 'right' }}>CAGR</th>
                  <th style={{ textAlign: 'right' }}>Sharpe</th>
                  <th style={{ textAlign: 'right' }}>Max drawdown</th>
                  <th style={{ textAlign: 'right' }}>Calmar</th>
                  <th style={{ textAlign: 'right' }}>Total trades</th>
                </tr>
              </thead>
              <tbody>
                {comparisonRows.map((row) => (
                  <tr key={row.label}>
                    <td>
                      <strong style={{ color: row.color }}>{row.label}</strong>
                    </td>
                    <td
                      style={{
                        textAlign: 'right',
                        fontFamily: 'monospace',
                        ...(isBestMetric(comparisonRows, 'final_equity', 'higher', row.metrics.final_equity) ? BEST_CELL_STYLE : {}),
                      }}
                    >
                      ${fmt(row.metrics.final_equity)}
                    </td>
                    <td
                      style={{
                        textAlign: 'right',
                        fontFamily: 'monospace',
                        color: colorVal(row.metrics.cagr),
                        ...(isBestMetric(comparisonRows, 'cagr', 'higher', row.metrics.cagr) ? BEST_CELL_STYLE : {}),
                      }}
                    >
                      {pct(row.metrics.cagr)}
                    </td>
                    <td
                      style={{
                        textAlign: 'right',
                        fontFamily: 'monospace',
                        color: colorVal(row.metrics.sharpe_ratio),
                        ...(isBestMetric(comparisonRows, 'sharpe_ratio', 'higher', row.metrics.sharpe_ratio) ? BEST_CELL_STYLE : {}),
                      }}
                    >
                      {fmt(row.metrics.sharpe_ratio)}
                    </td>
                    <td
                      style={{
                        textAlign: 'right',
                        fontFamily: 'monospace',
                        color: 'var(--error)',
                        ...(isBestMetric(comparisonRows, 'max_drawdown', 'lower', row.metrics.max_drawdown) ? BEST_CELL_STYLE : {}),
                      }}
                    >
                      {absPct(row.metrics.max_drawdown)}
                    </td>
                    <td
                      style={{
                        textAlign: 'right',
                        fontFamily: 'monospace',
                        ...(isBestMetric(comparisonRows, 'calmar_ratio', 'higher', row.metrics.calmar_ratio) ? BEST_CELL_STYLE : {}),
                      }}
                    >
                      {fmt(row.metrics.calmar_ratio)}
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--muted)' }}>
                      {row.metrics.total_trades ?? '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div
            style={{
              marginTop: 12,
              color: 'var(--muted)',
              fontSize: 13,
            }}
          >
            Highlighted cells mark the best value in each metric column. `Total trades` stays neutral.
          </div>

          {/* ── Deltas sub-table ── */}
          <div style={{ marginTop: 24 }}>
            <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>
              Deltas — positive always means first variant is better
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Comparison</th>
                    <th style={{ textAlign: 'right' }}>Δ Equity ($)</th>
                    <th style={{ textAlign: 'right' }}>Δ CAGR (pp)</th>
                    <th style={{ textAlign: 'right' }}>Δ Sharpe</th>
                    <th style={{ textAlign: 'right' }}>Δ Max DD (pp)</th>
                  </tr>
                </thead>
                <tbody>
                  {deltaRows.map((row) => (
                    <tr key={row.label}>
                      <td>
                        <span style={{ color: row.color, fontWeight: 600 }}>{row.label}</span>
                      </td>
                      <DeltaCell
                        value={row.d.eq}
                        format={(v) => `$${v >= 0 ? '' : '-'}${Math.abs(v).toFixed(0)}`}
                      />
                      <DeltaCell
                        value={row.d.cagr != null ? row.d.cagr * 100 : null}
                        format={(v) => `${v.toFixed(2)}pp`}
                      />
                      <DeltaCell
                        value={row.d.sharpe}
                        format={(v) => v.toFixed(2)}
                      />
                      <DeltaCell
                        value={row.d.dd != null ? row.d.dd * 100 : null}
                        format={(v) => `${v.toFixed(2)}pp`}
                      />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
              Δ Max DD: positive = first variant had a smaller maximum drawdown.
              pp = percentage points.
            </div>
          </div>
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
                <div className="metric-label">Cash periods</div>
                <div className="metric-value" style={{ color: cashOnlyCount > 0 ? 'var(--warning)' : undefined }}>
                  {cashOnlyCount}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Defensive periods</div>
                <div className="metric-value" style={{ color: defensivePeriods > 0 ? BENCHMARK_COLOR : undefined }}>
                  {defensivePeriods}
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
              </span>
              <span>
                Defensive rule:{' '}
                <strong style={{ color: 'var(--text)' }}>
                  {result.defensive_mode === 'defensive_asset'
                    ? `first available of ${result.defensive_tickers.join(', ')}`
                    : 'stay in cash'}
                </strong>
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
                      <th>Mode</th>
                      <th style={{ textAlign: 'right' }}>Eligible</th>
                      <th>Allocation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rebalanceLog.map((row, index) => (
                      <tr key={index}>
                        <td style={{ fontFamily: 'monospace' }}>{row.date}</td>
                        <td>
                          <span style={{ color: row.allocation_mode === 'defensive' ? BENCHMARK_COLOR : 'var(--text)' }}>
                            {allocationLabel(row.allocation_mode)}
                          </span>
                        </td>
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
