import { ExportButton, PreviewControls, PreviewGapRow } from './PreviewControls.jsx'
import {
  PRESET_WINDOWS,
  BEST_CELL_STYLE,
  absPct,
  average,
  buildBaseExportMetadata,
  buildPreviewState,
  colorVal,
  computeCrossPresetRanking,
  denseRank,
  exportVisibleCsv,
  fmt,
  isBestMetric,
  numericValue,
  parseSweepTopN,
  pct,
  stdDeviation,
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

const RECOMMEND_STYLE = {
  ...WINNER_STYLE,
  background: 'rgba(79, 142, 247, 0.12)',
  color: 'var(--accent)',
  border: '1px solid rgba(79, 142, 247, 0.3)',
}

export function CrossPresetResults({ crossPresetResult, form, getSectionMode, setSectionMode }) {
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

  const presetPlacementRanks = new Map(configKeys.map((configKey) => [configKey, new Map()]))
  for (const preset of PRESET_WINDOWS) {
    const presetValues = configKeys.map((configKey) => scores.get(configKey)?.presetAvg?.get(preset.label) ?? null)
    const presetRanks = denseRank(presetValues, false)
    for (let i = 0; i < configKeys.length; i++) {
      if (presetRanks[i] != null) {
        presetPlacementRanks.get(configKeys[i]).set(preset.label, presetRanks[i])
      }
    }
  }

  const robustnessRows = ranked.map((row) => {
    const presetAverages = PRESET_WINDOWS
      .map((preset) => scores.get(row.configKey)?.presetAvg?.get(preset.label))
      .filter((value) => value != null)
    const placementRanks = PRESET_WINDOWS
      .map((preset) => presetPlacementRanks.get(row.configKey)?.get(preset.label))
      .filter((value) => value != null)
    const avgRank = row.score != null && row.score < 999 ? row.score : null
    const rankStdDev = stdDeviation(presetAverages)
    const timesRank1 = placementRanks.filter((rank) => rank === 1).length
    const timesTop2 = placementRanks.filter((rank) => rank <= 2).length
    const robustnessScore = avgRank != null && rankStdDev != null ? avgRank + rankStdDev : avgRank

    return {
      ...row,
      avgRank,
      rankStdDev,
      timesRank1,
      timesTop2,
      robustnessScore,
    }
  })

  const rankStdValues = robustnessRows.map((row) => row.rankStdDev).filter((value) => value != null)
  const top1Values = robustnessRows.map((row) => row.timesRank1).filter((value) => value != null)
  const top2Values = robustnessRows.map((row) => row.timesTop2).filter((value) => value != null)
  const bestRankStdDev = rankStdValues.length > 0 ? Math.min(...rankStdValues) : null
  const bestTop1Count = top1Values.length > 0 ? Math.max(...top1Values) : null
  const bestTop2Count = top2Values.length > 0 ? Math.max(...top2Values) : null
  const robustnessByConfig = new Map(robustnessRows.map((row) => [row.configKey, row]))

  const mostRobust = robustnessRows
    .filter((row) => row.robustnessScore != null)
    .sort((a, b) => {
      if (a.robustnessScore !== b.robustnessScore) return a.robustnessScore - b.robustnessScore
      if ((a.rankStdDev ?? Infinity) !== (b.rankStdDev ?? Infinity)) return (a.rankStdDev ?? Infinity) - (b.rankStdDev ?? Infinity)
      if ((a.avgRank ?? Infinity) !== (b.avgRank ?? Infinity)) return (a.avgRank ?? Infinity) - (b.avgRank ?? Infinity)
      return (b.timesRank1 ?? 0) - (a.timesRank1 ?? 0)
    })[0] ?? null

  const top1Leader = robustnessRows
    .slice()
    .sort((a, b) => {
      if ((b.timesRank1 ?? 0) !== (a.timesRank1 ?? 0)) return (b.timesRank1 ?? 0) - (a.timesRank1 ?? 0)
      return (a.avgRank ?? Infinity) - (b.avgRank ?? Infinity)
    })[0] ?? null

  const top2Leader = robustnessRows
    .slice()
    .sort((a, b) => {
      if ((b.timesTop2 ?? 0) !== (a.timesTop2 ?? 0)) return (b.timesTop2 ?? 0) - (a.timesTop2 ?? 0)
      return (a.avgRank ?? Infinity) - (b.avgRank ?? Infinity)
    })[0] ?? null

  const configProfiles = ranked.map((row) => {
    const metricsByPreset = PRESET_WINDOWS
      .map((preset) => resultsByConfig.get(row.configKey)?.get(preset.label) ?? null)
      .filter(Boolean)
    const fullCycleMetrics = resultsByConfig.get(row.configKey)?.get('Full cycle') ?? null
    const stats = robustnessByConfig.get(row.configKey)

    return {
      configKey: row.configKey,
      avgCagr: average(
        metricsByPreset
          .map((metrics) => numericValue(metrics.cagr))
          .filter((value) => value != null),
      ),
      avgFinalEquity: average(
        metricsByPreset
          .map((metrics) => numericValue(metrics.final_equity))
          .filter((value) => value != null),
      ),
      avgAbsDrawdown: average(
        metricsByPreset
          .map((metrics) => numericValue(metrics.max_drawdown))
          .filter((value) => value != null)
          .map((value) => Math.abs(value)),
      ),
      fullCycleAvgRank: scores.get(row.configKey)?.presetAvg?.get('Full cycle') ?? null,
      fullCycleCagr: numericValue(fullCycleMetrics?.cagr),
      avgRank: row.score != null && row.score < 999 ? row.score : null,
      rankStdDev: stats?.rankStdDev ?? null,
      timesRank1: stats?.timesRank1 ?? 0,
      timesTop2: stats?.timesTop2 ?? 0,
      robustnessScore: stats?.robustnessScore ?? null,
    }
  })

  const bestReturnConfig = configProfiles
    .filter((profile) => profile.avgCagr != null)
    .sort((a, b) => {
      if (b.avgCagr !== a.avgCagr) return b.avgCagr - a.avgCagr
      if ((b.avgFinalEquity ?? -Infinity) !== (a.avgFinalEquity ?? -Infinity)) {
        return (b.avgFinalEquity ?? -Infinity) - (a.avgFinalEquity ?? -Infinity)
      }
      return (a.avgRank ?? Infinity) - (b.avgRank ?? Infinity)
    })[0] ?? null

  const bestDrawdownControl = configProfiles
    .filter((profile) => profile.avgAbsDrawdown != null)
    .sort((a, b) => {
      if (a.avgAbsDrawdown !== b.avgAbsDrawdown) return a.avgAbsDrawdown - b.avgAbsDrawdown
      if ((a.rankStdDev ?? Infinity) !== (b.rankStdDev ?? Infinity)) {
        return (a.rankStdDev ?? Infinity) - (b.rankStdDev ?? Infinity)
      }
      return (a.avgRank ?? Infinity) - (b.avgRank ?? Infinity)
    })[0] ?? null

  const recommendedDefault = configProfiles
    .filter((profile) => profile.robustnessScore != null)
    .sort((a, b) => {
      if (a.robustnessScore !== b.robustnessScore) return a.robustnessScore - b.robustnessScore
      if ((a.fullCycleAvgRank ?? Infinity) !== (b.fullCycleAvgRank ?? Infinity)) {
        return (a.fullCycleAvgRank ?? Infinity) - (b.fullCycleAvgRank ?? Infinity)
      }
      if ((a.avgAbsDrawdown ?? Infinity) !== (b.avgAbsDrawdown ?? Infinity)) {
        return (a.avgAbsDrawdown ?? Infinity) - (b.avgAbsDrawdown ?? Infinity)
      }
      if ((b.timesRank1 ?? 0) !== (a.timesRank1 ?? 0)) return (b.timesRank1 ?? 0) - (a.timesRank1 ?? 0)
      return (a.avgRank ?? Infinity) - (b.avgRank ?? Infinity)
    })[0] ?? null

  const rankingPreview = buildPreviewState(ranked, getSectionMode('cross_preset_ranking'))
  const presetDetailCards = PRESET_WINDOWS
    .map((preset) => {
      const presetRows = configKeys
        .map((configKey) => ({
          configKey,
          metrics: resultsByConfig.get(configKey)?.get(preset.label) ?? null,
        }))
        .filter((row) => row.metrics != null)
        .map((row) => ({
          key: row.configKey,
          label: row.configKey,
          isBenchmark: false,
          metrics: row.metrics,
        }))

      if (!presetRows.length) return null
      return { preset, presetRows }
    })
    .filter(Boolean)
  const presetDetailPreview = buildPreviewState(
    presetDetailCards,
    getSectionMode('cross_preset_details'),
    { previewHead: 1, previewTail: 0, moreHead: 2, moreTail: 0 },
  )

  const visibleRankingRows = visiblePreviewItems(rankingPreview).map((row, index) => {
    const stats = robustnessByConfig.get(row.configKey)
    return {
      rank: ranked.findIndex((entry) => entry.configKey === row.configKey) + 1 || index + 1,
      config_key: row.configKey,
      bull_run_avg_rank: scores.get(row.configKey)?.presetAvg?.get('Bull run') ?? '',
      rate_hike_bear_avg_rank: scores.get(row.configKey)?.presetAvg?.get('Rate hike bear') ?? '',
      mixed_volatile_avg_rank: scores.get(row.configKey)?.presetAvg?.get('Mixed / volatile') ?? '',
      full_cycle_avg_rank: scores.get(row.configKey)?.presetAvg?.get('Full cycle') ?? '',
      average_rank: stats?.avgRank ?? '',
      rank_std_dev: stats?.rankStdDev ?? '',
      times_ranked_1: stats?.timesRank1 ?? '',
      times_ranked_top_2: stats?.timesTop2 ?? '',
      robustness_score: stats?.robustnessScore ?? '',
    }
  })

  const exportCrossPresetCsv = () => exportVisibleCsv({
    form,
    mode: 'cross-preset',
    suffix: 'visible-ranking',
    metadata: [
      ...buildBaseExportMetadata(form, 'cross_preset'),
      { key: 'preset_windows', value: PRESET_WINDOWS.map((preset) => `${preset.label}:${preset.date_from}->${preset.date_to}`).join('|') },
      { key: 'top_n_values', value: parseSweepTopN(form.sweep_top_n).join('|') },
      { key: 'defensive_modes', value: 'cash|defensive_asset' },
      { key: 'ranking_mode', value: 'lower average preset rank across cagr|sharpe|max_drawdown|calmar' },
      { key: 'visible_rows_exported', value: visibleRankingRows.length },
      { key: 'hidden_rows_omitted', value: rankingPreview.hiddenCount },
    ],
    columns: [
      { label: 'rank', value: (row) => row.rank },
      { label: 'config_key', value: (row) => row.config_key },
      { label: 'bull_run_avg_rank', value: (row) => row.bull_run_avg_rank },
      { label: 'rate_hike_bear_avg_rank', value: (row) => row.rate_hike_bear_avg_rank },
      { label: 'mixed_volatile_avg_rank', value: (row) => row.mixed_volatile_avg_rank },
      { label: 'full_cycle_avg_rank', value: (row) => row.full_cycle_avg_rank },
      { label: 'average_rank', value: (row) => row.average_rank },
      { label: 'rank_std_dev', value: (row) => row.rank_std_dev },
      { label: 'times_ranked_1', value: (row) => row.times_ranked_1 },
      { label: 'times_ranked_top_2', value: (row) => row.times_ranked_top_2 },
      { label: 'robustness_score', value: (row) => row.robustness_score },
    ],
    rows: visibleRankingRows,
  })

  return (
    <>
      {failed.length > 0 && (
        <div className="card">
          <div className="alert alert-error" style={{ margin: 0 }}>
            <strong>{failed.length} of {totalRuns} experiment{failed.length !== 1 ? 's' : ''} failed:</strong>
            <ul style={{ margin: '6px 0 0 0', paddingLeft: 18 }}>
              {failed.map((row, index) => (
                <li key={index} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  [{row.presetLabel}] {row.configKey} - {row.error}
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
              Global ranking - {totalRuns} experiments across {PRESET_WINDOWS.length} market regimes
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12, marginBottom: 20 }}>
              <div className="metric-box">
                <div className="metric-label">Overall winner</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{ranked[0]?.configKey ?? '-'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  avg rank {ranked[0]?.score?.toFixed(2) ?? '-'}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Most robust config</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{mostRobust?.configKey ?? '-'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  score {fmt(mostRobust?.robustnessScore)} = avg {fmt(mostRobust?.avgRank)} + std {fmt(mostRobust?.rankStdDev)}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Best in bull market</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{bestByPreset.get('Bull run') ?? '-'}</span>
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Best in bear market</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{bestByPreset.get('Rate hike bear') ?? '-'}</span>
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Most #1 finishes</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{top1Leader?.configKey ?? '-'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  {top1Leader?.timesRank1 ?? 0} preset win{top1Leader?.timesRank1 === 1 ? '' : 's'}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Most top-2 finishes</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{top2Leader?.configKey ?? '-'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  {top2Leader?.timesTop2 ?? 0} top-2 finish{top2Leader?.timesTop2 === 1 ? '' : 'es'}
                </div>
              </div>
            </div>

            <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>
              Overall ranking - lower average rank is better
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
              <ExportButton onClick={exportCrossPresetCsv} disabled={visibleRankingRows.length === 0} />
            </div>
            <PreviewControls
              preview={rankingPreview}
              itemLabel="ranked configs"
              onModeChange={(mode) => setSectionMode('cross_preset_ranking', mode)}
            />
            <div className="table-wrap">
              <table className="table-compact">
                <thead>
                  <tr>
                    <th style={{ width: 28 }}>#</th>
                    <th>Configuration</th>
                    {PRESET_WINDOWS.map((preset) => (
                      <th key={preset.label} style={{ textAlign: 'right' }}>
                        {preset.label}
                      </th>
                    ))}
                    <th style={{ textAlign: 'right' }}>Avg rank</th>
                    <th style={{ textAlign: 'right' }}>Std dev</th>
                    <th style={{ textAlign: 'right' }}>#1</th>
                    <th style={{ textAlign: 'right' }}>Top 2</th>
                  </tr>
                </thead>
                <tbody>
                  {rankingPreview.items.map((row, index) => {
                    if (row?.__preview_gap) {
                      return (
                        <PreviewGapRow
                          key={`cross-preset-gap-${row.hiddenCount}-${index}`}
                          colSpan={PRESET_WINDOWS.length + 6}
                          hiddenCount={row.hiddenCount}
                        />
                      )
                    }

                    const absoluteIndex = ranked.findIndex((entry) => entry.configKey === row.configKey)
                    const scoreRow = scores.get(row.configKey)
                    const stats = robustnessByConfig.get(row.configKey)
                    const isWinner = absoluteIndex === 0

                    return (
                      <tr
                        key={row.configKey}
                        style={isWinner ? { background: 'rgba(34, 197, 94, 0.06)' } : undefined}
                      >
                        <td style={{ color: 'var(--muted)', fontSize: 12 }}>{absoluteIndex + 1}</td>
                        <td>
                          <strong style={{ color: isWinner ? 'var(--success)' : 'var(--text)' }}>
                            {row.configKey}
                          </strong>
                        </td>
                        {PRESET_WINDOWS.map((preset) => {
                          const avgRank = scoreRow?.presetAvg?.get(preset.label)
                          const isBest = bestByPreset.get(preset.label) === row.configKey

                          return (
                            <td
                              key={preset.label}
                              style={{
                                textAlign: 'right',
                                fontFamily: 'monospace',
                                ...(isBest ? BEST_CELL_STYLE : {}),
                              }}
                            >
                              {avgRank != null ? avgRank.toFixed(2) : '-'}
                            </td>
                          )
                        })}
                        <td
                          style={{
                            textAlign: 'right',
                            fontFamily: 'monospace',
                            fontWeight: 700,
                            color: isWinner ? 'var(--success)' : 'var(--text)',
                          }}
                        >
                          {row.score != null && row.score < 999 ? row.score.toFixed(2) : '-'}
                        </td>
                        <td
                          style={{
                            textAlign: 'right',
                            fontFamily: 'monospace',
                            ...(stats?.rankStdDev != null && bestRankStdDev != null && Math.abs(stats.rankStdDev - bestRankStdDev) < 1e-9 ? BEST_CELL_STYLE : {}),
                          }}
                        >
                          {stats?.rankStdDev != null ? stats.rankStdDev.toFixed(2) : '-'}
                        </td>
                        <td
                          style={{
                            textAlign: 'right',
                            fontFamily: 'monospace',
                            ...(stats?.timesRank1 != null && bestTop1Count != null && stats.timesRank1 === bestTop1Count ? BEST_CELL_STYLE : {}),
                          }}
                        >
                          {stats?.timesRank1 ?? '-'}
                        </td>
                        <td
                          style={{
                            textAlign: 'right',
                            fontFamily: 'monospace',
                            ...(stats?.timesTop2 != null && bestTop2Count != null && stats.timesTop2 === bestTop2Count ? BEST_CELL_STYLE : {}),
                          }}
                        >
                          {stats?.timesTop2 ?? '-'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
              Each cell shows the average metric rank (across CAGR, Sharpe, Max DD, Calmar) within that preset window. Lower is better.
              Green highlights mark the best configuration per regime, the lowest rank variability, and the strongest #1 / top-2 consistency.
            </div>
          </div>

          {presetDetailCards.length > 0 && (
            <div className="card">
              <div className="card-title">Per-preset detail tables</div>
              <PreviewControls
                preview={presetDetailPreview}
                itemLabel="preset tables"
                onModeChange={(mode) => setSectionMode('cross_preset_details', mode)}
              />
            </div>
          )}

          <div className="card">
            <div className="card-title">Recommended configuration</div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12, marginBottom: 16 }}>
              <div className="metric-box">
                <div className="metric-label">Best return config</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{bestReturnConfig?.configKey ?? '-'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  highest average CAGR: {pct(bestReturnConfig?.avgCagr)}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Most robust config</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{mostRobust?.configKey ?? '-'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  lowest avg rank + std dev: {fmt(mostRobust?.robustnessScore)}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Best bear-market config</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{bestByPreset.get('Rate hike bear') ?? '-'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  best preset rank in Rate hike bear
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Best drawdown-control config</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={WINNER_STYLE}>{bestDrawdownControl?.configKey ?? '-'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  lowest average |max drawdown|: {absPct(bestDrawdownControl?.avgAbsDrawdown)}
                </div>
              </div>
              <div className="metric-box">
                <div className="metric-label">Recommended default config</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  <span style={RECOMMEND_STYLE}>{recommendedDefault?.configKey ?? '-'}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  robustness first, then Full cycle rank, then drawdown control, then tie-breaks
                </div>
              </div>
            </div>

            <div style={{ fontSize: 12, color: 'var(--muted)' }}>
              Recommendation logic is explicit in code: best return = highest average CAGR across preset windows; most robust = lowest average-rank-plus-std-dev score; drawdown control = lowest average absolute max drawdown; recommended default = robustness first, then Full cycle average rank, then lower average drawdown, then more #1 finishes, then lower overall average rank.
            </div>
          </div>

          {presetDetailPreview.items.map((detail, detailIndex) => {
            if (detail?.__preview_gap) {
              return (
                <div className="card" key={`preset-gap-${detail.hiddenCount}-${detailIndex}`}>
                  <div className="empty preset-gap-note" data-hidden={detail.hiddenCount}>
                    ... {detail.hiddenCount} preset table{detail.hiddenCount !== 1 ? 's' : ''} hidden ...
                  </div>
                </div>
              )
            }

            const { preset, presetRows } = detail

            return (
              <div className="card" key={preset.label}>
                <div className="card-title">
                  {preset.label}
                  <span style={{ fontWeight: 400, color: 'var(--muted)', marginLeft: 8, fontFamily: 'monospace', fontSize: 12 }}>
                    {preset.date_from} - {preset.date_to}
                  </span>
                </div>
                <div className="table-wrap">
                  <table className="table-compact">
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
                        const metrics = row.metrics
                        const best = (key, preference, value) => (
                          isBestMetric(presetRows, key, preference, value) ? BEST_CELL_STYLE : {}
                        )

                        return (
                          <tr key={row.key}>
                            <td>
                              <strong>{row.label}</strong>
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
