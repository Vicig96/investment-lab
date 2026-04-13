import {
  BENCHMARK_COLOR,
  BEST_CELL_STYLE,
  CASH_COLOR,
  DEFENSIVE_COLOR,
  absPct,
  calcCalmar,
  calcDeltas,
  colorVal,
  fmt,
  isBestMetric,
  parseTickerList,
  pct,
} from './utils.js'

function DeltaCell({ value, format }) {
  if (value == null) {
    return (
      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--muted)' }}>-</td>
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

export function CompareResults({ comparisonResult, form }) {
  if (!comparisonResult) return null

  const comparisonRows = [
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
  ]

  const benchmarkMetrics = {
    final_equity: comparisonResult.benchmark?.final_equity,
    cagr: comparisonResult.benchmark?.cagr,
    sharpe_ratio: comparisonResult.benchmark?.sharpe_ratio,
    max_drawdown: comparisonResult.benchmark?.max_drawdown,
  }

  const deltaRows = [
    {
      label: 'Cash vs benchmark',
      color: CASH_COLOR,
      d: calcDeltas(comparisonResult.cashVariant.metrics, benchmarkMetrics),
    },
    {
      label: 'Defensive vs benchmark',
      color: DEFENSIVE_COLOR,
      d: calcDeltas(comparisonResult.defensiveVariant.metrics, benchmarkMetrics),
    },
    {
      label: 'Defensive vs cash',
      color: 'var(--muted)',
      d: calcDeltas(comparisonResult.defensiveVariant.metrics, comparisonResult.cashVariant.metrics),
    },
  ]

  return (
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
        Defensive tickers priority:{' '}
        <strong style={{ color: 'var(--text)' }}>{parseTickerList(form.defensive_tickers).join(', ')}</strong>
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

      <div style={{ marginTop: 24 }}>
        <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>
          Deltas - positive always means first variant is better
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Comparison</th>
                <th style={{ textAlign: 'right' }}>Delta Equity ($)</th>
                <th style={{ textAlign: 'right' }}>Delta CAGR (pp)</th>
                <th style={{ textAlign: 'right' }}>Delta Sharpe</th>
                <th style={{ textAlign: 'right' }}>Delta Max DD (pp)</th>
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
                    format={(value) => `$${value >= 0 ? '' : '-'}${Math.abs(value).toFixed(0)}`}
                  />
                  <DeltaCell
                    value={row.d.cagr != null ? row.d.cagr * 100 : null}
                    format={(value) => `${value.toFixed(2)}pp`}
                  />
                  <DeltaCell
                    value={row.d.sharpe}
                    format={(value) => value.toFixed(2)}
                  />
                  <DeltaCell
                    value={row.d.dd != null ? row.d.dd * 100 : null}
                    format={(value) => `${value.toFixed(2)}pp`}
                  />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
          Delta Max DD: positive = first variant had a smaller maximum drawdown.
          pp = percentage points.
        </div>
      </div>
    </div>
  )
}
