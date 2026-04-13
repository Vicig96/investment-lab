import {
  BENCHMARK_COLOR,
  STRATEGY_COLOR,
  absPct,
  allocationLabel,
  buildDateIndex,
  buildEquityCurvePoints,
  colorVal,
  fmt,
  pct,
} from './utils.js'

export function SingleRunResults({ result }) {
  if (!result) return null

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

  return (
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
            <table className="table-compact">
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
                  <tr key={`${row.date}-${index}`}>
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
            <table className="table-compact">
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
                  <tr key={`${trade.date}-${trade.ticker}-${trade.action}-${index}`}>
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
  )
}
