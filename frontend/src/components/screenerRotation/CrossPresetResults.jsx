import {
  BEST_CELL_STYLE,
  PRESET_WINDOWS,
  WINNER_STYLE,
  absPct,
  colorVal,
  computeCrossPresetRanking,
  fmt,
  isBestMetric,
  numericValue,
  pct,
} from './utils.js'

export function CrossPresetResults({ crossPresetResult }) {
  if (!crossPresetResult) return null

  const { results, totalRuns } = crossPresetResult
  const failed = results.filter((row) => row.status === 'rejected')
  const success = results.filter((row) => row.status === 'fulfilled')

  const configKeys = []
  for (const row of results) {
    if (!configKeys.includes(row.configKey)) configKeys.push(row.configKey)
  }

  const resultsByConfig = new Map()
  for (const row of success) {
    if (!resultsByConfig.has(row.configKey)) resultsByConfig.set(row.configKey, new Map())
    resultsByConfig.get(row.configKey).set(row.presetLabel, row.result.metrics)
  }

  const scores = computeCrossPresetRanking(configKeys, resultsByConfig)

  const ranked = configKeys
    .map((configKey) => ({ configKey, score: scores.get(configKey)?.overall ?? 999 }))
    .sort((a, b) => a.score - b.score)

  const bestByPreset = new Map()
  for (const presetLabel of PRESET_WINDOWS.map((preset) => preset.label)) {
    let best = null
    let bestAvg = 999
    for (const configKey of configKeys) {
      const avg = scores.get(configKey)?.presetAvg?.get(presetLabel)
      if (avg != null && avg < bestAvg) {
        bestAvg = avg
        best = configKey
      }
    }
    if (best) bestByPreset.set(presetLabel, best)
  }

  // Best risk-adjusted: highest average Sharpe ratio across all presets
  let bestRiskAdj = null
  let bestRiskVal = 999
  for (const ck of configKeys) {
    const sharpes = PRESET_WINDOWS
      .map((p) => {
        const m = resultsByConfig.get(ck)?.get(p.label)
        return m ? numericValue(m.sharpe_ratio) : null
      })
      .filter((v) => v != null)
    if (sharpes.length > 0) {
      const avg = sharpes.reduce((a, b) => a + b, 0) / sharpes.length
      if (avg > bestRiskVal || bestRiskAdj === null) { bestRiskVal = avg; bestRiskAdj = ck }
    }
  }

  // Best drawdown control: lowest average |max_drawdown| across all presets
  let bestDD = null
  let bestDDVal = 999
  for (const ck of configKeys) {
    const dds = PRESET_WINDOWS
      .map((p) => {
        const m = resultsByConfig.get(ck)?.get(p.label)
        return m ? numericValue(m.max_drawdown) : null
      })
      .filter((v) => v != null)
      .map((v) => Math.abs(v))
    if (dds.length > 0) {
      const avg = dds.reduce((a, b) => a + b, 0) / dds.length
      if (avg < bestDDVal) { bestDDVal = avg; bestDD = ck }
    }
  }

  return (
    <>
      {failed.length > 0 && (
        <div className="card">
          <div className="alert alert-error" style={{ margin: 0 }}>
            <strong>{failed.length} of {totalRuns} experiment{failed.length !== 1 ? 's' : ''} failed:</strong>
            <ul style={{ margin: '6px 0 0 0', paddingLeft: 18 }}>
              {failed.map((row, index) => (
                <li key={index} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  [{row.presetLabel}] {row.configKey} — {row.error}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {success.length === 0 ? (
        <div className="empty">All {totalRuns} experiments failed. Check the errors above.</div>
      ) : (
        <>
          <div className="card">
            <div className="card-title">
              Global ranking — {totalRuns} experiments across {PRESET_WINDOWS.length} market regimes
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
              gap: 12,
              marginBottom: 20,
            }}>
              <div className="metric-box">
                <div className="metric-label">Overall winner</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{ranked[0]?.configKey ?? '—'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  avg rank {ranked[0]?.score?.toFixed(2) ?? '—'}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Best in bull market</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{bestByPreset.get('Bull run') ?? '—'}</span>
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Best in bear market</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{bestByPreset.get('Rate hike bear') ?? '—'}</span>
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Best risk-adjusted</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{bestRiskAdj ?? '—'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  avg Sharpe {bestRiskVal !== 999 ? bestRiskVal.toFixed(2) : '—'}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Best drawdown control</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{bestDD ?? '—'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  avg |DD| {bestDDVal !== 999 ? absPct(bestDDVal) : '—'}
                </div>
              </div>
            </div>

            <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>
              Overall ranking — lower average rank is better
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 28 }}>#</th>
                    <th>Configuration</th>
                    {PRESET_WINDOWS.map((p) => (
                      <th key={p.label} style={{ textAlign: 'right' }}>
                        {p.label}
                      </th>
                    ))}
                    <th style={{ textAlign: 'right' }}>Avg rank</th>
                  </tr>
                </thead>
                <tbody>
                  {ranked.map((row, i) => {
                    const s = scores.get(row.configKey)
                    const isWinner = i === 0
                    return (
                      <tr
                        key={row.configKey}
                        style={isWinner ? { background: 'rgba(34, 197, 94, 0.06)' } : undefined}
                      >
                        <td style={{ color: 'var(--muted)', fontSize: 12 }}>{i + 1}</td>
                        <td>
                          <strong style={{ color: isWinner ? 'var(--success)' : 'var(--text)' }}>
                            {row.configKey}
                          </strong>
                        </td>
                        {PRESET_WINDOWS.map((p) => {
                          const avg = s?.presetAvg?.get(p.label)
                          const isBest = bestByPreset.get(p.label) === row.configKey
                          return (
                            <td
                              key={p.label}
                              style={{
                                textAlign: 'right',
                                fontFamily: 'monospace',
                                ...(isBest ? BEST_CELL_STYLE : {}),
                              }}
                            >
                              {avg != null ? avg.toFixed(2) : '—'}
                            </td>
                          )
                        })}
                        <td style={{
                          textAlign: 'right',
                          fontFamily: 'monospace',
                          fontWeight: 700,
                          color: isWinner ? 'var(--success)' : 'var(--text)',
                        }}>
                          {row.score != null && row.score < 999 ? row.score.toFixed(2) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
              Each cell shows the average metric rank (across CAGR, Sharpe, Max DD, Calmar) within that preset window. Lower is better.
              Green highlights mark the best configuration per regime.
            </div>
          </div>

          {PRESET_WINDOWS.map((preset) => {
            const presetRows = configKeys
              .map((ck) => ({
                configKey: ck,
                metrics: resultsByConfig.get(ck)?.get(preset.label) ?? null,
              }))
              .filter((row) => row.metrics != null)
              .map((row) => ({
                key: row.configKey,
                label: row.configKey,
                isBenchmark: false,
                metrics: row.metrics,
              }))

            if (!presetRows.length) return null

            return (
              <div className="card" key={preset.label}>
                <div className="card-title">
                  {preset.label}
                  <span style={{ fontWeight: 400, color: 'var(--muted)', marginLeft: 8, fontFamily: 'monospace', fontSize: 12 }}>
                    {preset.date_from} → {preset.date_to}
                  </span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Configuration</th>
                        <th style={{ textAlign: 'right' }}>Final equity</th>
                        <th style={{ textAlign: 'right' }}>CAGR</th>
                        <th style={{ textAlign: 'right' }}>Sharpe</th>
                        <th style={{ textAlign: 'right' }}>Max DD</th>
                        <th style={{ textAlign: 'right' }}>Calmar</th>
                      </tr>
                    </thead>
                    <tbody>
                      {presetRows.map((row) => {
                        const m = row.metrics
                        const best = (key, pref, val) =>
                          isBestMetric(presetRows, key, pref, val) ? BEST_CELL_STYLE : {}
                        return (
                          <tr key={row.key}>
                            <td>
                              <strong>{row.label}</strong>
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', ...best('final_equity', 'higher', m.final_equity) }}>
                              ${fmt(m.final_equity)}
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(m.cagr), ...best('cagr', 'higher', m.cagr) }}>
                              {pct(m.cagr)}
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(m.sharpe_ratio), ...best('sharpe_ratio', 'higher', m.sharpe_ratio) }}>
                              {fmt(m.sharpe_ratio)}
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--error)', ...best('max_drawdown', 'lower', m.max_drawdown) }}>
                              {absPct(m.max_drawdown)}
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', ...best('calmar_ratio', 'higher', m.calmar_ratio) }}>
                              {fmt(m.calmar_ratio)}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          })}
        </>
      )}
    </>
  )
}
