import {
  WINNER_STYLE,
  absPct,
  average,
  colorVal,
  fmt,
  pct,
} from './utils.js'

export function WalkForwardResults({ walkForwardResult }) {
  if (!walkForwardResult) return null

  const { folds, totalFolds } = walkForwardResult
  const successFolds = folds.filter((fold) => fold.testMetrics != null)
  const failedFolds = folds.filter((fold) => fold.error != null)

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
                {folds.map((fold) => {
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
