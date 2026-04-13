import { ExportButton } from './PreviewControls.jsx'
import {
  BENCHMARK_COLOR,
  BEST_CELL_STYLE,
  absPct,
  buildBaseExportMetadata,
  calcCalmar,
  colorVal,
  exportVisibleCsv,
  fmt,
  isBestMetric,
  parseSweepTopN,
  pct,
} from './utils.js'

export function ParameterSweepResults({ sweepResult, form }) {
  if (!sweepResult) return null

  const { rows, benchmark, totalRuns } = sweepResult
  const failedRows = rows.filter((row) => row.status === 'rejected')
  const successRows = rows.filter((row) => row.status === 'fulfilled')

  const tableRows = [
    ...successRows.map((row) => ({
      key: row.label,
      label: row.label,
      top_n: row.top_n,
      defensive_mode: row.defensive_mode,
      isBenchmark: false,
      metrics: row.result.metrics,
    })),
    ...(benchmark ? [{
      key: 'benchmark',
      label: `${benchmark.ticker ?? 'SPY'} buy-and-hold`,
      top_n: null,
      defensive_mode: null,
      isBenchmark: true,
      metrics: {
        final_equity: benchmark.final_equity,
        cagr: benchmark.cagr,
        sharpe_ratio: benchmark.sharpe_ratio,
        max_drawdown: benchmark.max_drawdown,
        calmar_ratio: calcCalmar(benchmark.cagr, benchmark.max_drawdown),
        total_trades: 0,
      },
    }] : []),
  ]

  const strategyTableRows = tableRows.filter((row) => !row.isBenchmark)
  const exportRows = tableRows.map((row) => ({
    experiment: row.label,
    row_type: row.isBenchmark ? 'benchmark' : 'strategy',
    top_n: row.top_n ?? '',
    defensive_mode: row.defensive_mode ?? '',
    final_equity: row.metrics.final_equity,
    cagr: row.metrics.cagr,
    sharpe_ratio: row.metrics.sharpe_ratio,
    max_drawdown: row.metrics.max_drawdown,
    calmar_ratio: row.metrics.calmar_ratio,
    total_trades: row.metrics.total_trades ?? '',
  }))

  const exportSweepCsv = () => exportVisibleCsv({
    form,
    mode: 'parameter-sweep',
    suffix: 'visible-results',
    metadata: [
      ...buildBaseExportMetadata(form, 'parameter_sweep'),
      { key: 'date_from', value: form.date_from },
      { key: 'date_to', value: form.date_to },
      { key: 'top_n_values', value: parseSweepTopN(form.sweep_top_n).join('|') },
      { key: 'defensive_modes', value: 'cash|defensive_asset' },
      { key: 'ranking_mode', value: 'none' },
      { key: 'visible_rows_exported', value: exportRows.length },
    ],
    columns: [
      { label: 'experiment', value: (row) => row.experiment },
      { label: 'row_type', value: (row) => row.row_type },
      { label: 'top_n', value: (row) => row.top_n },
      { label: 'defensive_mode', value: (row) => row.defensive_mode },
      { label: 'final_equity', value: (row) => row.final_equity },
      { label: 'cagr', value: (row) => row.cagr },
      { label: 'sharpe_ratio', value: (row) => row.sharpe_ratio },
      { label: 'max_drawdown', value: (row) => row.max_drawdown },
      { label: 'calmar_ratio', value: (row) => row.calmar_ratio },
      { label: 'total_trades', value: (row) => row.total_trades },
    ],
    rows: exportRows,
  })

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
        <div className="card-title" style={{ marginBottom: 0 }}>
          Parameter sweep - {totalRuns} experiments
          &nbsp;-&nbsp;{form.date_from} to {form.date_to}
        </div>
        {successRows.length > 0 && <ExportButton onClick={exportSweepCsv} />}
      </div>

      {failedRows.length > 0 && (
        <div className="alert alert-error" style={{ marginBottom: 12 }}>
          <strong>{failedRows.length} experiment{failedRows.length !== 1 ? 's' : ''} failed:</strong>
          <ul style={{ margin: '6px 0 0 0', paddingLeft: 18 }}>
            {failedRows.map((row) => (
              <li key={row.label} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                {row.label} - {row.error}
              </li>
            ))}
          </ul>
        </div>
      )}

      {successRows.length === 0 ? (
        <div className="empty">All experiments failed. Check the errors above.</div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Experiment</th>
                  <th style={{ textAlign: 'right' }}>Top N</th>
                  <th>Def. mode</th>
                  <th style={{ textAlign: 'right' }}>Final equity</th>
                  <th style={{ textAlign: 'right' }}>CAGR</th>
                  <th style={{ textAlign: 'right' }}>Sharpe</th>
                  <th style={{ textAlign: 'right' }}>Max DD</th>
                  <th style={{ textAlign: 'right' }}>Calmar</th>
                  <th style={{ textAlign: 'right' }}>Trades</th>
                </tr>
              </thead>
              <tbody>
                {tableRows.map((row) => {
                  const metrics = row.metrics
                  const referenceRows = row.isBenchmark ? null : strategyTableRows
                  const best = (key, preference, value) => (
                    !row.isBenchmark && isBestMetric(referenceRows, key, preference, value) ? BEST_CELL_STYLE : {}
                  )

                  return (
                    <tr
                      key={row.key}
                      style={row.isBenchmark ? { borderTop: '1px solid var(--border)', opacity: 0.75 } : undefined}
                    >
                      <td>
                        <strong style={{ color: row.isBenchmark ? BENCHMARK_COLOR : 'var(--text)' }}>
                          {row.label}
                        </strong>
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--muted)' }}>
                        {row.top_n ?? '-'}
                      </td>
                      <td style={{ color: 'var(--muted)', fontSize: 12 }}>
                        {row.defensive_mode === 'cash'
                          ? 'cash'
                          : row.defensive_mode === 'defensive_asset'
                            ? 'defensive'
                            : '-'}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', ...best('final_equity', 'higher', metrics.final_equity) }}>
                        ${fmt(metrics.final_equity)}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(metrics.cagr), ...best('cagr', 'higher', metrics.cagr) }}>
                        {pct(metrics.cagr)}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(metrics.sharpe_ratio), ...best('sharpe_ratio', 'higher', metrics.sharpe_ratio) }}>
                        {fmt(metrics.sharpe_ratio)}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--error)', ...best('max_drawdown', 'lower', metrics.max_drawdown) }}>
                        {absPct(metrics.max_drawdown)}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', ...best('calmar_ratio', 'higher', metrics.calmar_ratio) }}>
                        {fmt(metrics.calmar_ratio)}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--muted)' }}>
                        {metrics.total_trades ?? '-'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>
            Highlighted cells mark the best strategy value per column. Benchmark row is shown for reference only and does not compete for highlights.
          </div>
        </>
      )}
    </div>
  )
}
