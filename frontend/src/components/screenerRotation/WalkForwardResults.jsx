import { ExportButton, PreviewControls, PreviewGapRow } from './PreviewControls.jsx'
import {
  absPct,
  buildBaseExportMetadata,
  buildPreviewState,
  colorVal,
  exportVisibleCsv,
  fmt,
  parseSweepTopN,
  pct,
  visiblePreviewItems,
} from './utils.js'

const WINNER_STYLE = {
  display: 'inline-block',
  padding: '3px 10px',
  borderRadius: 4,
  fontSize: 12,
  fontWeight: 700,
  background: 'rgba(34, 197, 94, 0.12)',
  color: 'var(--success)',
  border: '1px solid rgba(34, 197, 94, 0.3)',
}

export function WalkForwardResults({ walkForwardResult, form, getSectionMode, setSectionMode }) {
  if (!walkForwardResult) return null

  const { folds, totalFolds } = walkForwardResult
  const successFolds = folds.filter((fold) => fold.testMetrics != null)
  const failedFolds = folds.filter((fold) => fold.error != null)
  const foldsPreview = buildPreviewState(folds, getSectionMode('walk_forward_folds'))

  const oosValues = {
    cagr: successFolds.map((fold) => Number(fold.testMetrics?.cagr)).filter((value) => Number.isFinite(value)),
    sharpe: successFolds.map((fold) => Number(fold.testMetrics?.sharpe_ratio)).filter((value) => Number.isFinite(value)),
    maxDD: successFolds.map((fold) => Number(fold.testMetrics?.max_drawdown)).filter((value) => Number.isFinite(value)),
    calmar: successFolds.map((fold) => Number(fold.testMetrics?.calmar_ratio)).filter((value) => Number.isFinite(value)),
  }
  const benchmarkValues = {
    cagr: successFolds.map((fold) => Number(fold.benchmarkMetrics?.cagr)).filter((value) => Number.isFinite(value)),
    sharpe: successFolds.map((fold) => Number(fold.benchmarkMetrics?.sharpe_ratio)).filter((value) => Number.isFinite(value)),
    maxDD: successFolds.map((fold) => Number(fold.benchmarkMetrics?.max_drawdown)).filter((value) => Number.isFinite(value)),
  }
  const average = (values) => (values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : null)

  const oosAvg = {
    cagr: average(oosValues.cagr),
    sharpe: average(oosValues.sharpe),
    maxDD: average(oosValues.maxDD),
    calmar: average(oosValues.calmar),
  }
  const benchmarkAvg = {
    cagr: average(benchmarkValues.cagr),
    sharpe: average(benchmarkValues.sharpe),
    maxDD: average(benchmarkValues.maxDD),
  }

  const winnerCounts = new Map()
  for (const fold of successFolds) {
    if (fold.trainWinner) {
      winnerCounts.set(fold.trainWinner, (winnerCounts.get(fold.trainWinner) || 0) + 1)
    }
  }

  let mostFrequentWinner = null
  let maxCount = 0
  for (const [configKey, count] of winnerCounts) {
    if (count > maxCount) {
      maxCount = count
      mostFrequentWinner = configKey
    }
  }

  const visibleFoldRows = visiblePreviewItems(foldsPreview).map((fold) => ({
    fold: fold.fold,
    train_from: fold.trainFrom,
    train_to: fold.trainTo,
    test_from: fold.testFrom,
    test_to: fold.testTo,
    train_winner: fold.trainWinner ?? '',
    train_avg_rank: fold.trainAvgRank ?? '',
    oos_final_equity: fold.testMetrics?.final_equity ?? '',
    oos_cagr: fold.testMetrics?.cagr ?? '',
    oos_sharpe_ratio: fold.testMetrics?.sharpe_ratio ?? '',
    oos_max_drawdown: fold.testMetrics?.max_drawdown ?? '',
    oos_calmar_ratio: fold.testMetrics?.calmar_ratio ?? '',
    benchmark_ticker: 'SPY',
    benchmark_final_equity: fold.benchmarkMetrics?.final_equity ?? '',
    benchmark_cagr: fold.benchmarkMetrics?.cagr ?? '',
    benchmark_sharpe_ratio: fold.benchmarkMetrics?.sharpe_ratio ?? '',
    benchmark_max_drawdown: fold.benchmarkMetrics?.max_drawdown ?? '',
    error: fold.error ?? '',
  }))

  const exportWalkForwardCsv = () => exportVisibleCsv({
    form,
    mode: 'walk-forward',
    suffix: 'visible-folds',
    metadata: [
      ...buildBaseExportMetadata(form, 'walk_forward'),
      { key: 'data_start', value: form.wf_data_start },
      { key: 'data_end', value: form.wf_data_end },
      { key: 'train_years', value: form.wf_train_years },
      { key: 'test_years', value: form.wf_test_years },
      { key: 'step_years', value: form.wf_step_years },
      { key: 'top_n_values', value: parseSweepTopN(form.sweep_top_n).join('|') },
      { key: 'defensive_modes', value: 'cash|defensive_asset' },
      { key: 'ranking_mode', value: 'winner chosen on training-window avg rank across cagr|sharpe|max_drawdown|calmar' },
      { key: 'visible_rows_exported', value: visibleFoldRows.length },
      { key: 'hidden_rows_omitted', value: foldsPreview.hiddenCount },
    ],
    columns: [
      { label: 'fold', value: (row) => row.fold },
      { label: 'train_from', value: (row) => row.train_from },
      { label: 'train_to', value: (row) => row.train_to },
      { label: 'test_from', value: (row) => row.test_from },
      { label: 'test_to', value: (row) => row.test_to },
      { label: 'train_winner', value: (row) => row.train_winner },
      { label: 'train_avg_rank', value: (row) => row.train_avg_rank },
      { label: 'oos_final_equity', value: (row) => row.oos_final_equity },
      { label: 'oos_cagr', value: (row) => row.oos_cagr },
      { label: 'oos_sharpe_ratio', value: (row) => row.oos_sharpe_ratio },
      { label: 'oos_max_drawdown', value: (row) => row.oos_max_drawdown },
      { label: 'oos_calmar_ratio', value: (row) => row.oos_calmar_ratio },
      { label: 'benchmark_ticker', value: (row) => row.benchmark_ticker },
      { label: 'benchmark_final_equity', value: (row) => row.benchmark_final_equity },
      { label: 'benchmark_cagr', value: (row) => row.benchmark_cagr },
      { label: 'benchmark_sharpe_ratio', value: (row) => row.benchmark_sharpe_ratio },
      { label: 'benchmark_max_drawdown', value: (row) => row.benchmark_max_drawdown },
      { label: 'error', value: (row) => row.error },
    ],
    rows: visibleFoldRows,
  })

  return (
    <div className="card">
      <div className="card-title">
        Walk-forward results - {totalFolds} fold{totalFolds !== 1 ? 's' : ''}
      </div>

      {failedFolds.length > 0 && (
        <div className="alert alert-error" style={{ marginBottom: 12 }}>
          <strong>{failedFolds.length} fold{failedFolds.length !== 1 ? 's' : ''} failed:</strong>
          <ul style={{ margin: '6px 0 0 0', paddingLeft: 18 }}>
            {failedFolds.map((fold) => (
              <li key={fold.fold} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                Fold {fold.fold} ({fold.testFrom} to {fold.testTo}) - {fold.error}
              </li>
            ))}
          </ul>
        </div>
      )}

      {successFolds.length === 0 ? (
        <div className="empty">All folds failed. Check the errors above.</div>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 20 }}>
            <div className="metric-box">
              <div className="metric-label">Most frequent winner</div>
              <div className="metric-value" style={{ fontSize: 15 }}>
                <span style={WINNER_STYLE}>{mostFrequentWinner ?? '-'}</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                picked in {maxCount} of {successFolds.length} fold{successFolds.length !== 1 ? 's' : ''}
              </div>
            </div>
            <div className="metric-box">
              <div className="metric-label">Avg OOS CAGR</div>
              <div className="metric-value" style={{ color: colorVal(oosAvg.cagr) }}>
                {pct(oosAvg.cagr)}
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                benchmark: {pct(benchmarkAvg.cagr)}
              </div>
            </div>
            <div className="metric-box">
              <div className="metric-label">Avg OOS Sharpe</div>
              <div className="metric-value" style={{ color: colorVal(oosAvg.sharpe) }}>
                {fmt(oosAvg.sharpe)}
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                benchmark: {fmt(benchmarkAvg.sharpe)}
              </div>
            </div>
            <div className="metric-box">
              <div className="metric-label">Avg OOS Max DD</div>
              <div className="metric-value" style={{ color: 'var(--error)' }}>
                {absPct(oosAvg.maxDD)}
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                benchmark: {absPct(benchmarkAvg.maxDD)}
              </div>
            </div>
            <div className="metric-box">
              <div className="metric-label">Avg OOS Calmar</div>
              <div className="metric-value">
                {fmt(oosAvg.calmar)}
              </div>
            </div>
          </div>

          <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>
            Fold details - train winner to out-of-sample performance
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
            <ExportButton onClick={exportWalkForwardCsv} disabled={visibleFoldRows.length === 0} />
          </div>
          <PreviewControls
            preview={foldsPreview}
            itemLabel="folds"
            onModeChange={(mode) => setSectionMode('walk_forward_folds', mode)}
          />
          <div className="table-wrap">
            <table className="table-compact">
              <thead>
                <tr>
                  <th>Fold</th>
                  <th>Train window</th>
                  <th>Test window</th>
                  <th>Winner (train)</th>
                  <th style={{ textAlign: 'right' }}>Avg rank</th>
                  <th style={{ textAlign: 'right' }}>OOS CAGR</th>
                  <th style={{ textAlign: 'right' }}>OOS Sharpe</th>
                  <th style={{ textAlign: 'right' }}>OOS Max DD</th>
                  <th style={{ textAlign: 'right' }}>OOS Calmar</th>
                  <th style={{ textAlign: 'right' }}>BM CAGR</th>
                </tr>
              </thead>
              <tbody>
                {foldsPreview.items.map((fold, index) => {
                  if (fold?.__preview_gap) {
                    return (
                      <PreviewGapRow
                        key={`wf-gap-${fold.hiddenCount}-${index}`}
                        colSpan={10}
                        hiddenCount={fold.hiddenCount}
                      />
                    )
                  }

                  const testMetrics = fold.testMetrics
                  const benchmarkMetrics = fold.benchmarkMetrics

                  return (
                    <tr key={fold.fold} style={fold.error && !testMetrics ? { opacity: 0.5 } : undefined}>
                      <td style={{ fontFamily: 'monospace', color: 'var(--muted)' }}>{fold.fold}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                        {fold.trainFrom} to {fold.trainTo}
                      </td>
                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                        {fold.testFrom} to {fold.testTo}
                      </td>
                      <td>
                        {fold.trainWinner
                          ? <strong style={{ color: 'var(--success)' }}>{fold.trainWinner}</strong>
                          : <span style={{ color: 'var(--error)', fontStyle: 'italic' }}>failed</span>}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--muted)' }}>
                        {fold.trainAvgRank != null ? fold.trainAvgRank.toFixed(2) : '-'}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(testMetrics?.cagr) }}>
                        {testMetrics ? pct(testMetrics.cagr) : '-'}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(testMetrics?.sharpe_ratio) }}>
                        {testMetrics ? fmt(testMetrics.sharpe_ratio) : '-'}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--error)' }}>
                        {testMetrics ? absPct(testMetrics.max_drawdown) : '-'}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>
                        {testMetrics ? fmt(testMetrics.calmar_ratio) : '-'}
                      </td>
                      <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(benchmarkMetrics?.cagr) }}>
                        {benchmarkMetrics ? pct(benchmarkMetrics.cagr) : '-'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
            Each fold: all configs compete on the training window - winner is tested on the subsequent out-of-sample window.
            BM = SPY buy-and-hold benchmark over the same test period.
          </div>
        </>
      )}
    </div>
  )
}
