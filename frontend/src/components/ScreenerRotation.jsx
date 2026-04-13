import { useState } from 'react'
import { runScreenerRotation } from '../api.js'

const DEFAULT = {
  run_mode: 'single',
  instrument_tickers: 'SPY, QQQ, IWM, TLT, GLD',
  date_from: '2021-01-01',
  date_to: '2023-12-31',
  top_n: '3',
  sweep_top_n: '1,2,3',
  initial_capital: '10000',
  commission_bps: '10',
  rebalance_frequency: 'monthly',
  warmup_bars: '252',
  defensive_mode: 'cash',
  defensive_tickers: 'TLT, GLD',
  wf_data_start: '2018-01-01',
  wf_data_end: '2023-12-31',
  wf_train_years: '2',
  wf_test_years: '1',
  wf_step_years: '1',
}

// ── Predefined experiment windows ────────────────────────────────────────────
// Each entry represents a distinct market regime useful for systematic testing.
// Clicking a preset populates date_from and date_to in the form.
const PRESET_WINDOWS = [
  {
    label:     'Bull run',
    date_from: '2019-01-01',
    date_to:   '2021-12-31',
    note:      'Extended equity bull market with COVID dip and recovery',
  },
  {
    label:     'Rate hike bear',
    date_from: '2022-01-01',
    date_to:   '2023-12-31',
    note:      'Fed tightening cycle — tech selloff, bond stress, sector rotation',
  },
  {
    label:     'Mixed / volatile',
    date_from: '2020-01-01',
    date_to:   '2022-12-31',
    note:      'COVID crash, V-shaped recovery, inflation onset',
  },
  {
    label:     'Full cycle',
    date_from: '2019-01-01',
    date_to:   '2023-12-31',
    note:      'Bull + bear + recovery — broadest regime coverage',
  },
]

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

function parseSweepTopN(raw) {
  return raw
    .split(',')
    .map((s) => parseInt(s.trim(), 10))
    .filter((n) => Number.isFinite(n) && n >= 1 && n <= 20)
}

function validate(form) {
  const tickers = parseTickerList(form.instrument_tickers)
  if (!tickers.length) return 'At least one ticker is required.'
  if (Number(form.initial_capital) <= 0) return 'Initial capital must be > 0.'
  if (Number(form.commission_bps) < 0) return 'Commission must be >= 0.'
  if (Number(form.warmup_bars) < 0) return 'Warm-up bars must be >= 0.'

  if (form.run_mode === 'cross_preset') {
    const topNValues = parseSweepTopN(form.sweep_top_n)
    if (!topNValues.length) return 'Enter at least one valid Top N value (1–20).'
    if (parseTickerList(form.defensive_tickers).length === 0) {
      return 'Add at least one defensive ticker — cross-preset runs both cash and defensive_asset.'
    }
    return null  // dates not needed — presets provide them
  }

  if (form.run_mode === 'walk_forward') {
    if (!form.wf_data_start) return '"Data start" date is required.'
    if (!form.wf_data_end) return '"Data end" date is required.'
    if (form.wf_data_start >= form.wf_data_end) return '"Data start" must be before "Data end".'
    const topNValues = parseSweepTopN(form.sweep_top_n)
    if (!topNValues.length) return 'Enter at least one valid Top N value (1–20).'
    if (parseTickerList(form.defensive_tickers).length === 0) {
      return 'Add at least one defensive ticker — walk-forward runs both cash and defensive_asset.'
    }
    const trainYears = parseInt(form.wf_train_years, 10)
    const testYears = parseInt(form.wf_test_years, 10)
    const stepYears = parseInt(form.wf_step_years, 10)
    if (!trainYears || trainYears < 1) return 'Train years must be >= 1.'
    if (!testYears || testYears < 1) return 'Test years must be >= 1.'
    if (!stepYears || stepYears < 1) return 'Step years must be >= 1.'
    const windows = generateWalkForwardWindows(form.wf_data_start, form.wf_data_end, trainYears, testYears, stepYears)
    if (!windows.length) return 'No valid walk-forward windows fit within the data range. Increase the date range or decrease train/test years.'
    return null
  }

  if (!form.date_from) return '"From" date is required.'
  if (!form.date_to) return '"To" date is required.'
  if (form.date_from >= form.date_to) return '"From" must be before "To".'

  if (form.run_mode === 'parameter_sweep') {
    const topNValues = parseSweepTopN(form.sweep_top_n)
    if (!topNValues.length) return 'Enter at least one valid Top N value (1–20) for the sweep.'
    if (parseTickerList(form.defensive_tickers).length === 0) {
      return 'Add at least one defensive ticker — sweep runs both cash and defensive_asset modes.'
    }
  } else {
    if (Number(form.top_n) <= 0) return 'Top N must be > 0.'
    if (
      (form.run_mode === 'compare_variants' || form.defensive_mode === 'defensive_asset')
      && parseTickerList(form.defensive_tickers).length === 0
    ) {
      return 'Add at least one defensive ticker for defensive-asset comparisons.'
    }
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

// ── Cross-preset ranking helpers ──────────────────────────────────────────────

// Given an array of numeric values, return an array of 1-based dense ranks.
// Higher is better when higherIsBetter=true; ties get the same rank.
function denseRank(values, higherIsBetter) {
  const indexed = values.map((v, i) => ({ v: numericValue(v), i }))
  const valid   = indexed.filter((x) => x.v != null)
  if (!valid.length) return values.map(() => null)

  // Sort descending if higher is better, ascending otherwise
  valid.sort((a, b) => higherIsBetter ? b.v - a.v : a.v - b.v)

  const ranks = new Array(values.length).fill(null)
  let rank = 1
  for (let j = 0; j < valid.length; j++) {
    if (j > 0 && valid[j].v !== valid[j - 1].v) rank = j + 1
    ranks[valid[j].i] = rank
  }
  return ranks
}

// For a set of configs across multiple presets, compute the average rank
// across 4 metrics (cagr, sharpe, max_drawdown, calmar) within each preset,
// then average those per-preset average ranks into a single overall score.
// Lower score = better.
function computeCrossPresetRanking(configKeys, resultsByConfig) {
  // configKeys: string[], resultsByConfig: Map<configKey, Map<presetLabel, metrics>>
  const RANK_METRICS = [
    { key: 'cagr',         higher: true  },
    { key: 'sharpe_ratio', higher: true  },
    { key: 'max_drawdown', higher: false },  // lower |dd| is better
    { key: 'calmar_ratio', higher: true  },
  ]

  // presetLabels: all unique preset labels across all configs
  const presetLabels = []
  for (const configMap of resultsByConfig.values()) {
    for (const pLabel of configMap.keys()) {
      if (!presetLabels.includes(pLabel)) presetLabels.push(pLabel)
    }
  }

  // For each config, accumulate per-preset per-metric ranks
  // avgRanks[configKey] = { perPreset: { presetLabel: avgRank }, overall: number }
  const perPresetRanks = new Map() // configKey → Map<presetLabel, number[]>
  for (const ck of configKeys) perPresetRanks.set(ck, new Map())

  for (const pLabel of presetLabels) {
    for (const metric of RANK_METRICS) {
      const rawValues = configKeys.map((ck) => {
        const m = resultsByConfig.get(ck)?.get(pLabel)
        if (!m) return null
        return metric.key === 'max_drawdown'
          ? (numericValue(m.max_drawdown) != null ? Math.abs(numericValue(m.max_drawdown)) : null)
          : numericValue(m[metric.key])
      })
      // For max_drawdown (displayed as abs), lower abs is better → higherIsBetter=false
      const isHigher = metric.key === 'max_drawdown' ? false : metric.higher
      const ranks = denseRank(rawValues, isHigher)
      for (let i = 0; i < configKeys.length; i++) {
        const ck = configKeys[i]
        const map = perPresetRanks.get(ck)
        if (!map.has(pLabel)) map.set(pLabel, [])
        if (ranks[i] != null) map.get(pLabel).push(ranks[i])
      }
    }
  }

  // Compute per-preset average rank and overall average
  const scores = new Map() // configKey → { presetAvg: Map<label, number>, overall: number }
  for (const ck of configKeys) {
    const presetAvg = new Map()
    const allAvgs = []
    for (const pLabel of presetLabels) {
      const ranks = perPresetRanks.get(ck)?.get(pLabel) ?? []
      if (ranks.length > 0) {
        const avg = ranks.reduce((a, b) => a + b, 0) / ranks.length
        presetAvg.set(pLabel, avg)
        allAvgs.push(avg)
      }
    }
    const overall = allAvgs.length > 0
      ? allAvgs.reduce((a, b) => a + b, 0) / allAvgs.length
      : null
    scores.set(ck, { presetAvg, overall })
  }

  return scores
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

// ── Walk-forward helpers ─────────────────────────────────────────────────────

function toDateStr(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function generateWalkForwardWindows(dataStart, dataEnd, trainYears, testYears, stepYears) {
  const windows = []
  const endDate = new Date(dataEnd + 'T00:00:00')
  let cursor = new Date(dataStart + 'T00:00:00')
  let foldIndex = 1

  while (true) {
    const trainFrom = new Date(cursor)
    const testStart = new Date(cursor)
    testStart.setFullYear(testStart.getFullYear() + trainYears)

    const trainTo = new Date(testStart)
    trainTo.setDate(trainTo.getDate() - 1)

    const testEnd = new Date(testStart)
    testEnd.setFullYear(testEnd.getFullYear() + testYears)
    testEnd.setDate(testEnd.getDate() - 1)

    if (testEnd > endDate) break

    windows.push({
      foldIndex,
      trainFrom: toDateStr(trainFrom),
      trainTo: toDateStr(trainTo),
      testFrom: toDateStr(testStart),
      testTo: toDateStr(testEnd),
    })

    cursor.setFullYear(cursor.getFullYear() + stepYears)
    foldIndex++
  }

  return windows
}

// Rank configs within a single window by 4 metrics (same logic as cross-preset).
// Returns { configKey, avgRank } for the best config.
function pickBestConfig(configResults) {
  if (!configResults.length) return null
  const METRICS = [
    { key: 'cagr', higher: true },
    { key: 'sharpe_ratio', higher: true },
    { key: 'max_drawdown', higher: false },
    { key: 'calmar_ratio', higher: true },
  ]

  const n = configResults.length
  const totals = new Array(n).fill(0)
  let metricsUsed = 0

  for (const metric of METRICS) {
    const values = configResults.map((r) => {
      const v = numericValue(r.metrics[metric.key])
      if (v == null) return null
      return metric.key === 'max_drawdown' ? Math.abs(v) : v
    })
    const isHigher = metric.key === 'max_drawdown' ? false : metric.higher
    const ranks = denseRank(values, isHigher)
    let anyRank = false
    for (let i = 0; i < n; i++) {
      if (ranks[i] != null) { totals[i] += ranks[i]; anyRank = true }
    }
    if (anyRank) metricsUsed++
  }

  if (metricsUsed === 0) return { configKey: configResults[0].configKey, avgRank: null }

  let bestIdx = 0
  let bestScore = Infinity
  for (let i = 0; i < n; i++) {
    const avg = totals[i] / metricsUsed
    if (avg < bestScore) { bestScore = avg; bestIdx = i }
  }

  return { configKey: configResults[bestIdx].configKey, avgRank: bestScore }
}

// Parse a configKey like "Top 2 · Defensive" back into { top_n, defensive_mode }
function parseConfigKey(configKey) {
  const match = configKey.match(/Top\s+(\d+)\s+·\s+(Cash|Defensive)/)
  if (!match) return { top_n: 1, defensive_mode: 'cash' }
  return {
    top_n: parseInt(match[1], 10),
    defensive_mode: match[2] === 'Cash' ? 'cash' : 'defensive_asset',
  }
}

function summarizePreviewItems(items, headCount, tailCount = 0) {
  const total = Array.isArray(items) ? items.length : 0
  if (total === 0) return { items: [], shownCount: 0, hiddenCount: 0 }
  if (total <= headCount) return { items, shownCount: total, hiddenCount: 0 }
  if (tailCount <= 0 || total <= headCount + tailCount) {
    const visibleItems = items.slice(0, Math.min(total, headCount))
    return {
      items: visibleItems,
      shownCount: visibleItems.length,
      hiddenCount: total - visibleItems.length,
    }
  }

  const hiddenCount = total - headCount - tailCount
  return {
    items: [
      ...items.slice(0, headCount),
      { __preview_gap: true, hiddenCount },
      ...items.slice(-tailCount),
    ],
    shownCount: headCount + tailCount,
    hiddenCount,
  }
}

function buildPreviewState(items, mode, options = {}) {
  const total = Array.isArray(items) ? items.length : 0
  const currentMode = mode ?? 'preview'
  const previewHead = options.previewHead ?? 10
  const previewTail = options.previewTail ?? 10
  const moreHead = options.moreHead ?? 25
  const moreTail = options.moreTail ?? 25

  if (currentMode === 'all') {
    return {
      mode: currentMode,
      total,
      shownCount: total,
      hiddenCount: 0,
      items,
      canShowMore: false,
      canShowAll: false,
      canCollapse: total > previewHead,
    }
  }

  const summary = currentMode === 'more'
    ? summarizePreviewItems(items, moreHead, moreTail)
    : summarizePreviewItems(items, previewHead, previewTail)

  return {
    mode: currentMode,
    total,
    ...summary,
    canShowMore: currentMode === 'preview' && total > summary.shownCount,
    canShowAll: currentMode !== 'all' && total > summary.shownCount,
    canCollapse: currentMode !== 'preview' && total > previewHead,
  }
}

function PreviewControls({ preview, itemLabel = 'rows', onModeChange }) {
  if (!preview) return null
  if (!preview.canShowMore && !preview.canShowAll && !preview.canCollapse) return null

  return (
    <div className="section-controls">
      <span className="section-controls-note">
        {preview.mode === 'all'
          ? `Showing all ${preview.total} ${itemLabel}.`
          : `Showing ${preview.shownCount} of ${preview.total} ${itemLabel}.`}
      </span>
      <div className="section-controls-actions">
        {preview.canShowMore && (
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => onModeChange('more')}
          >
            Show more
          </button>
        )}
        {preview.canShowAll && (
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => onModeChange('all')}
          >
            Show all
          </button>
        )}
        {preview.canCollapse && (
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => onModeChange('preview')}
          >
            Collapse
          </button>
        )}
      </div>
    </div>
  )
}

function PreviewGapRow({ colSpan, hiddenCount }) {
  return (
    <tr>
      <td colSpan={colSpan} className="preview-gap-cell">
        â€¦ {hiddenCount} row{hiddenCount !== 1 ? 's' : ''} hidden â€¦
      </td>
    </tr>
  )
}

export default function ScreenerRotation() {
  const [form, setForm] = useState(DEFAULT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [formError, setFormError] = useState(null)
  const [singleResult, setSingleResult] = useState(null)
  const [comparisonResult, setComparisonResult] = useState(null)
  const [sweepResult, setSweepResult] = useState(null)
  const [crossPresetResult, setCrossPresetResult] = useState(null)
  const [walkForwardResult, setWalkForwardResult] = useState(null)
  const [sectionModes, setSectionModes] = useState({})

  const setField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setFormError(null)
  }

  const setSectionMode = (key, mode) => {
    setSectionModes((prev) => ({ ...prev, [key]: mode }))
  }

  const getSectionMode = (key) => sectionModes[key] ?? 'preview'

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
    setSweepResult(null)
    setCrossPresetResult(null)
    setWalkForwardResult(null)
    setSectionModes({})

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
      } else if (form.run_mode === 'parameter_sweep') {
        const topNValues = parseSweepTopN(form.sweep_top_n)
        const defensiveModes = ['cash', 'defensive_asset']

        // Build the full experiment grid: top_n × defensive_mode
        const experiments = topNValues.flatMap((topN) =>
          defensiveModes.map((defMode) => ({
            label: `Top ${topN} · ${defMode === 'cash' ? 'Cash' : 'Defensive'}`,
            top_n: topN,
            defensive_mode: defMode,
            payload: { ...basePayload, top_n: topN, defensive_mode: defMode },
          }))
        )

        const settled = await Promise.allSettled(
          experiments.map((exp) => runScreenerRotation(exp.payload))
        )

        const rows = experiments.map((exp, i) => ({
          ...exp,
          status: settled[i].status,
          result: settled[i].status === 'fulfilled' ? settled[i].value : null,
          error: settled[i].status === 'rejected'
            ? (settled[i].reason?.message ?? 'request failed')
            : null,
        }))

        // Benchmark from first successful run
        const firstOk = rows.find((r) => r.status === 'fulfilled')
        const benchmark = firstOk?.result?.benchmark ?? null

        setSweepResult({ rows, benchmark, totalRuns: experiments.length })
      } else if (form.run_mode === 'cross_preset') {
        const topNValues = parseSweepTopN(form.sweep_top_n)
        const defensiveModes = ['cash', 'defensive_asset']

        // Build all experiment jobs: preset × top_n × defensive_mode
        const jobs = PRESET_WINDOWS.flatMap((preset) =>
          topNValues.flatMap((topN) =>
            defensiveModes.map((defMode) => ({
              presetLabel: preset.label,
              configKey: `Top ${topN} · ${defMode === 'cash' ? 'Cash' : 'Defensive'}`,
              top_n: topN,
              defensive_mode: defMode,
              payload: {
                ...basePayload,
                date_from: preset.date_from,
                date_to: preset.date_to,
                top_n: topN,
                defensive_mode: defMode,
              },
            }))
          )
        )

        const settled = await Promise.allSettled(
          jobs.map((job) => runScreenerRotation(job.payload))
        )

        const results = jobs.map((job, i) => ({
          ...job,
          status: settled[i].status,
          result: settled[i].status === 'fulfilled' ? settled[i].value : null,
          error: settled[i].status === 'rejected'
            ? (settled[i].reason?.message ?? 'request failed')
            : null,
        }))

        setCrossPresetResult({ results, totalRuns: jobs.length })
      } else if (form.run_mode === 'walk_forward') {
        const trainYears = parseInt(form.wf_train_years, 10) || 2
        const testYears = parseInt(form.wf_test_years, 10) || 1
        const stepYears = parseInt(form.wf_step_years, 10) || 1
        const windows = generateWalkForwardWindows(
          form.wf_data_start, form.wf_data_end, trainYears, testYears, stepYears,
        )

        const topNValues = parseSweepTopN(form.sweep_top_n)
        const defensiveModes = ['cash', 'defensive_asset']
        const folds = []

        for (const win of windows) {
          // Phase 1: run all configs on the training window in parallel
          const trainConfigs = topNValues.flatMap((topN) =>
            defensiveModes.map((defMode) => ({
              configKey: `Top ${topN} · ${defMode === 'cash' ? 'Cash' : 'Defensive'}`,
              top_n: topN,
              defensive_mode: defMode,
              payload: {
                ...basePayload,
                date_from: win.trainFrom,
                date_to: win.trainTo,
                top_n: topN,
                defensive_mode: defMode,
              },
            })),
          )

          const trainSettled = await Promise.allSettled(
            trainConfigs.map((c) => runScreenerRotation(c.payload)),
          )

          const trainResults = trainConfigs
            .map((c, i) => ({
              configKey: c.configKey,
              metrics: trainSettled[i].status === 'fulfilled'
                ? trainSettled[i].value.metrics
                : null,
            }))
            .filter((r) => r.metrics != null)

          const bestPick = pickBestConfig(trainResults)

          if (!bestPick) {
            folds.push({
              fold: win.foldIndex,
              trainFrom: win.trainFrom,
              trainTo: win.trainTo,
              testFrom: win.testFrom,
              testTo: win.testTo,
              trainWinner: null,
              trainAvgRank: null,
              trainConfigCount: trainConfigs.length,
              testMetrics: null,
              benchmarkMetrics: null,
              error: 'All training configs failed.',
            })
            continue
          }

          // Phase 2: run winning config on the test window
          const winnerParams = parseConfigKey(bestPick.configKey)
          const testPayload = {
            ...basePayload,
            date_from: win.testFrom,
            date_to: win.testTo,
            top_n: winnerParams.top_n,
            defensive_mode: winnerParams.defensive_mode,
          }

          let testResult = null
          let benchmarkMetrics = null
          let foldError = null

          try {
            testResult = await runScreenerRotation(testPayload)
            benchmarkMetrics = testResult.benchmark
              ? {
                final_equity: testResult.benchmark.final_equity,
                cagr: testResult.benchmark.cagr,
                sharpe_ratio: testResult.benchmark.sharpe_ratio,
                max_drawdown: testResult.benchmark.max_drawdown,
              }
              : null
          } catch (err) {
            foldError = err.message
          }

          folds.push({
            fold: win.foldIndex,
            trainFrom: win.trainFrom,
            trainTo: win.trainTo,
            testFrom: win.testFrom,
            testTo: win.testTo,
            trainWinner: bestPick.configKey,
            trainAvgRank: bestPick.avgRank,
            trainConfigCount: trainConfigs.length,
            testMetrics: testResult?.metrics ?? null,
            benchmarkMetrics,
            error: foldError,
          })
        }

        setWalkForwardResult({ folds, totalFolds: windows.length })
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
  const rebalancePreview = buildPreviewState(rebalanceLog, getSectionMode('single_rebalance'))
  const tradesPreview = buildPreviewState(trades, getSectionMode('single_trades'))

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
                <option value="parameter_sweep">Parameter sweep</option>
                <option value="cross_preset">Cross-preset ranking</option>
                <option value="walk_forward">Walk-forward test</option>
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

          {/* ── Preset windows (hidden in cross-preset and walk-forward) ── */}
          {form.run_mode !== 'cross_preset' && form.run_mode !== 'walk_forward' && (
            <div className="field">
              <label>Preset windows</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
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
                {PRESET_WINDOWS.map((preset) => {
                  const active =
                    form.date_from === preset.date_from &&
                    form.date_to   === preset.date_to
                  return (
                    <button
                      key={preset.label}
                      type="button"
                      disabled={loading}
                      title={preset.note}
                      onClick={() => {
                        setField('date_from', preset.date_from)
                        setField('date_to',   preset.date_to)
                      }}
                      style={{
                        padding:       '4px 12px',
                        fontSize:      12,
                        fontWeight:    active ? 700 : 400,
                        borderRadius:  4,
                        border:        active
                          ? '1px solid var(--accent)'
                          : '1px solid var(--border)',
                        background:    active
                          ? 'rgba(79,142,247,0.15)'
                          : 'var(--surface)',
                        color:         active ? 'var(--accent)' : 'var(--muted)',
                        cursor:        loading ? 'not-allowed' : 'pointer',
                        whiteSpace:    'nowrap',
                      }}
                    >
                      {preset.label}
                      <span style={{ marginLeft: 6, opacity: 0.55, fontFamily: 'monospace' }}>
                        {preset.date_from.slice(0, 4)}–{preset.date_to.slice(0, 4)}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {form.run_mode !== 'cross_preset' && form.run_mode !== 'walk_forward' && (
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
              {form.run_mode !== 'parameter_sweep' ? (
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
              ) : (
                <div className="field" style={{ maxWidth: 220 }}>
                  <label>Top N values (comma-separated)</label>
                  <input
                    type="text"
                    value={form.sweep_top_n}
                    onChange={(event) => setField('sweep_top_n', event.target.value)}
                    placeholder="1,2,3"
                    spellCheck={false}
                    disabled={loading}
                  />
                </div>
              )}
            </div>
          )}
          {form.run_mode === 'cross_preset' && (
            <div className="form-row">
              <div className="field" style={{ maxWidth: 220 }}>
                <label>Top N values (comma-separated)</label>
                <input
                  type="text"
                  value={form.sweep_top_n}
                  onChange={(event) => setField('sweep_top_n', event.target.value)}
                  placeholder="1,2,3"
                  spellCheck={false}
                  disabled={loading}
                />
              </div>
            </div>
          )}
          {form.run_mode === 'walk_forward' && (
            <>
              <div className="form-row">
                <div className="field">
                  <label>Data start *</label>
                  <input
                    type="date"
                    value={form.wf_data_start}
                    onChange={(event) => setField('wf_data_start', event.target.value)}
                    required
                    disabled={loading}
                  />
                </div>
                <div className="field">
                  <label>Data end *</label>
                  <input
                    type="date"
                    value={form.wf_data_end}
                    onChange={(event) => setField('wf_data_end', event.target.value)}
                    required
                    disabled={loading}
                  />
                </div>
                <div className="field" style={{ maxWidth: 220 }}>
                  <label>Top N values (comma-separated)</label>
                  <input
                    type="text"
                    value={form.sweep_top_n}
                    onChange={(event) => setField('sweep_top_n', event.target.value)}
                    placeholder="1,2,3"
                    spellCheck={false}
                    disabled={loading}
                  />
                </div>
              </div>
              <div className="form-row">
                <div className="field" style={{ maxWidth: 140 }}>
                  <label>Train (years)</label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={form.wf_train_years}
                    onChange={(event) => setField('wf_train_years', event.target.value)}
                    disabled={loading}
                  />
                </div>
                <div className="field" style={{ maxWidth: 140 }}>
                  <label>Test (years)</label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={form.wf_test_years}
                    onChange={(event) => setField('wf_test_years', event.target.value)}
                    disabled={loading}
                  />
                </div>
                <div className="field" style={{ maxWidth: 140 }}>
                  <label>Step (years)</label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={form.wf_step_years}
                    onChange={(event) => setField('wf_step_years', event.target.value)}
                    disabled={loading}
                  />
                </div>
              </div>
            </>
          )}

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
            {form.run_mode !== 'parameter_sweep' && form.run_mode !== 'cross_preset' && form.run_mode !== 'walk_forward' && (
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
            )}
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
            <div style={{ marginBottom: 12, color: 'var(--muted)', fontSize: 13 }}>
              Compare mode runs both rotation variants automatically: cash and defensive_asset.
            </div>
          )}
          {form.run_mode === 'parameter_sweep' && (
            <div style={{ marginBottom: 12, color: 'var(--muted)', fontSize: 13 }}>
              Each Top N value is run twice — once with cash and once with defensive asset.
              {' '}<strong style={{ color: 'var(--text)' }}>
                {parseSweepTopN(form.sweep_top_n).length * 2} experiment{parseSweepTopN(form.sweep_top_n).length * 2 !== 1 ? 's' : ''} will run in parallel.
              </strong>
            </div>
          )}
          {form.run_mode === 'cross_preset' && (() => {
            const nConfigs = parseSweepTopN(form.sweep_top_n).length * 2
            const nTotal = PRESET_WINDOWS.length * nConfigs
            return (
              <div style={{ marginBottom: 12, color: 'var(--muted)', fontSize: 13 }}>
                Runs every Top N × defensive mode combination across all {PRESET_WINDOWS.length} preset windows
                ({PRESET_WINDOWS.map((p) => p.label).join(', ')}).
                {' '}<strong style={{ color: 'var(--text)' }}>
                  {nTotal} experiment{nTotal !== 1 ? 's' : ''} will run in parallel.
                </strong>
              </div>
            )
          })()}
          {form.run_mode === 'walk_forward' && (() => {
            const trainYears = parseInt(form.wf_train_years, 10) || 0
            const testYears = parseInt(form.wf_test_years, 10) || 0
            const stepYears = parseInt(form.wf_step_years, 10) || 0
            const nConfigs = parseSweepTopN(form.sweep_top_n).length * 2
            const wins = (trainYears >= 1 && testYears >= 1 && stepYears >= 1 && form.wf_data_start && form.wf_data_end)
              ? generateWalkForwardWindows(form.wf_data_start, form.wf_data_end, trainYears, testYears, stepYears)
              : []
            return (
              <div style={{ marginBottom: 12, color: 'var(--muted)', fontSize: 13 }}>
                Rolling walk-forward: {trainYears}y train → {testYears}y test, stepping {stepYears}y forward each fold.
                {' '}{wins.length > 0
                  ? <>
                      <strong style={{ color: 'var(--text)' }}>
                        {wins.length} fold{wins.length !== 1 ? 's' : ''}
                      </strong>
                      {' '}× {nConfigs} configs = {wins.length * nConfigs} training runs + {wins.length} OOS tests.
                    </>
                  : <span style={{ color: 'var(--warning)' }}>No valid folds for this date range.</span>
                }
              </div>
            )
          })()}

          {formError && <div className="field-error">{formError}</div>}

          <div>
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? <span className="spinner" /> : null}
              {form.run_mode === 'compare_variants'
                ? 'Run Comparison'
                : form.run_mode === 'parameter_sweep'
                  ? 'Run Sweep'
                  : form.run_mode === 'cross_preset'
                    ? 'Run Cross-Preset Ranking'
                    : form.run_mode === 'walk_forward'
                      ? 'Run Walk-Forward Test'
                      : 'Run Backtest'}
            </button>
          </div>
        </form>

        {error && <div className="alert alert-error" style={{ marginTop: 12 }}>{error}</div>}
      </div>

      {!singleResult && !comparisonResult && !sweepResult && !crossPresetResult && !walkForwardResult && !loading && !error && (
        <div className="empty" style={{ paddingTop: 40 }}>
          Configure the parameters above and choose a run mode.
        </div>
      )}

      {loading && (
        <div className="empty" style={{ paddingTop: 24 }}>
          {form.run_mode === 'compare_variants'
            ? 'Running both Screener Rotation variants. The comparison table will appear only after both finish successfully.'
            : form.run_mode === 'parameter_sweep'
              ? `Running ${parseSweepTopN(form.sweep_top_n).length * 2} sweep experiments in parallel. Results will appear after all runs complete.`
              : form.run_mode === 'cross_preset'
                ? `Running ${PRESET_WINDOWS.length * parseSweepTopN(form.sweep_top_n).length * 2} experiments across ${PRESET_WINDOWS.length} preset windows. This may take a moment.`
                : form.run_mode === 'walk_forward'
                  ? 'Running walk-forward folds sequentially (training sweep → OOS test per fold). This may take a moment.'
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

      {/* ── Parameter sweep results ────────────────────────────────────────── */}
      {sweepResult && (() => {
        const { rows, benchmark, totalRuns } = sweepResult
        const failedRows  = rows.filter((r) => r.status === 'rejected')
        const successRows = rows.filter((r) => r.status === 'fulfilled')

        // Build rows in the shape isBestMetric expects: { metrics: {...} }
        const tableRows = [
          ...successRows.map((r) => ({
            key:            r.label,
            label:          r.label,
            top_n:          r.top_n,
            defensive_mode: r.defensive_mode,
            isBenchmark:    false,
            metrics:        r.result.metrics,
          })),
          ...(benchmark ? [{
            key:            'benchmark',
            label:          `${benchmark.ticker ?? 'SPY'} buy-and-hold`,
            top_n:          null,
            defensive_mode: null,
            isBenchmark:    true,
            metrics: {
              final_equity: benchmark.final_equity,
              cagr:         benchmark.cagr,
              sharpe_ratio: benchmark.sharpe_ratio,
              max_drawdown: benchmark.max_drawdown,
              calmar_ratio: calcCalmar(benchmark.cagr, benchmark.max_drawdown),
              total_trades: 0,
            },
          }] : []),
        ]

        // Only strategy rows (not benchmark) participate in best-value highlights
        const strategyTableRows = tableRows.filter((r) => !r.isBenchmark)

        return (
          <div className="card">
            <div className="card-title">
              Parameter sweep — {totalRuns} experiments
              &nbsp;·&nbsp;{form.date_from} → {form.date_to}
            </div>

            {/* Failure summary */}
            {failedRows.length > 0 && (
              <div className="alert alert-error" style={{ marginBottom: 12 }}>
                <strong>{failedRows.length} experiment{failedRows.length !== 1 ? 's' : ''} failed:</strong>
                <ul style={{ margin: '6px 0 0 0', paddingLeft: 18 }}>
                  {failedRows.map((r) => (
                    <li key={r.label} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                      {r.label} — {r.error}
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
                        const m   = row.metrics
                        const ref = row.isBenchmark ? null : strategyTableRows
                        const best = (key, pref, val) =>
                          !row.isBenchmark && isBestMetric(ref, key, pref, val)
                            ? BEST_CELL_STYLE : {}

                        return (
                          <tr
                            key={row.key}
                            style={row.isBenchmark
                              ? { borderTop: '1px solid var(--border)', opacity: 0.75 }
                              : undefined}
                          >
                            <td>
                              <strong style={{ color: row.isBenchmark ? BENCHMARK_COLOR : 'var(--text)' }}>
                                {row.label}
                              </strong>
                            </td>
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--muted)' }}>
                              {row.top_n ?? '—'}
                            </td>
                            <td style={{ color: 'var(--muted)', fontSize: 12 }}>
                              {row.defensive_mode === 'cash'
                                ? 'cash'
                                : row.defensive_mode === 'defensive_asset'
                                  ? 'defensive'
                                  : '—'}
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
                            <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--muted)' }}>
                              {m.total_trades ?? '—'}
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
      })()}

      {/* ── Cross-preset ranking results ────────────────────────────────────── */}
      {crossPresetResult && (() => {
        const { results, totalRuns } = crossPresetResult
        const failed  = results.filter((r) => r.status === 'rejected')
        const success = results.filter((r) => r.status === 'fulfilled')

        // Unique config keys (e.g. "Top 1 · Cash") preserving grid order
        const configKeys = []
        for (const r of results) {
          if (!configKeys.includes(r.configKey)) configKeys.push(r.configKey)
        }

        // resultsByConfig: Map<configKey, Map<presetLabel, metrics>>
        const resultsByConfig = new Map()
        for (const r of success) {
          if (!resultsByConfig.has(r.configKey)) resultsByConfig.set(r.configKey, new Map())
          resultsByConfig.get(r.configKey).set(r.presetLabel, r.result.metrics)
        }

        const scores = computeCrossPresetRanking(configKeys, resultsByConfig)

        // Sort by overall score ascending (best first)
        const ranked = configKeys
          .map((ck) => ({ configKey: ck, score: scores.get(ck)?.overall ?? 999 }))
          .sort((a, b) => a.score - b.score)

        // Category winners
        const bestByPreset = new Map()
        for (const pLabel of PRESET_WINDOWS.map((p) => p.label)) {
          let best = null
          let bestAvg = 999
          for (const ck of configKeys) {
            const avg = scores.get(ck)?.presetAvg?.get(pLabel)
            if (avg != null && avg < bestAvg) { bestAvg = avg; best = ck }
          }
          if (best) bestByPreset.set(pLabel, best)
        }

        // Best risk-adjusted: best average sharpe rank across presets
        let bestRiskAdj = null
        let bestRiskVal = 999
        for (const ck of configKeys) {
          const sharpes = PRESET_WINDOWS.map((p) => {
            const m = resultsByConfig.get(ck)?.get(p.label)
            return m ? numericValue(m.sharpe_ratio) : null
          }).filter((v) => v != null)
          if (sharpes.length > 0) {
            const avg = sharpes.reduce((a, b) => a + b, 0) / sharpes.length
            if (avg > bestRiskVal || bestRiskAdj === null) { bestRiskVal = avg; bestRiskAdj = ck }
          }
        }

        // Best drawdown control: lowest average |max_drawdown| across presets
        let bestDD = null
        let bestDDVal = 999
        for (const ck of configKeys) {
          const dds = PRESET_WINDOWS.map((p) => {
            const m = resultsByConfig.get(ck)?.get(p.label)
            return m ? numericValue(m.max_drawdown) : null
          }).filter((v) => v != null).map((v) => Math.abs(v))
          if (dds.length > 0) {
            const avg = dds.reduce((a, b) => a + b, 0) / dds.length
            if (avg < bestDDVal) { bestDDVal = avg; bestDD = ck }
          }
        }

        const rankingPreview = buildPreviewState(ranked, getSectionMode('cross_preset_ranking'))
        const presetDetailCards = PRESET_WINDOWS
          .map((preset) => {
            const presetRows = configKeys
              .map((ck) => ({
                configKey: ck,
                metrics: resultsByConfig.get(ck)?.get(preset.label) ?? null,
              }))
              .filter((r) => r.metrics != null)
              .map((r) => ({
                key: r.configKey,
                label: r.configKey,
                isBenchmark: false,
                metrics: r.metrics,
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

        return (
          <>
            {/* Failures */}
            {failed.length > 0 && (
              <div className="card">
                <div className="alert alert-error" style={{ margin: 0 }}>
                  <strong>{failed.length} of {totalRuns} experiment{failed.length !== 1 ? 's' : ''} failed:</strong>
                  <ul style={{ margin: '6px 0 0 0', paddingLeft: 18 }}>
                    {failed.map((r, i) => (
                      <li key={i} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                        [{r.presetLabel}] {r.configKey} — {r.error}
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
                {/* ── Global ranking summary ── */}
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

                  {/* ── Overall ranking table (sorted by average rank) ── */}
                  <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>
                    Overall ranking — lower average rank is better
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
                          {PRESET_WINDOWS.map((p) => (
                            <th key={p.label} style={{ textAlign: 'right' }}>
                              {p.label}
                            </th>
                          ))}
                          <th style={{ textAlign: 'right' }}>Avg rank</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rankingPreview.items.map((row, i) => {
                          if (row?.__preview_gap) {
                            return (
                              <PreviewGapRow
                                key={`cross-preset-gap-${row.hiddenCount}-${i}`}
                                colSpan={PRESET_WINDOWS.length + 3}
                                hiddenCount={row.hiddenCount}
                              />
                            )
                          }

                          const absoluteIndex = ranked.findIndex((entry) => entry.configKey === row.configKey)
                          const s = scores.get(row.configKey)
                          const isWinner = absoluteIndex === 0
                          return (
                            <tr
                              key={row.configKey}
                              style={isWinner
                                ? { background: 'rgba(34, 197, 94, 0.06)' }
                                : undefined}
                            >
                              <td style={{ color: 'var(--muted)', fontSize: 12 }}>{absoluteIndex + 1}</td>
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

                {/* ── Detailed metrics per preset ── */}
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
                {presetDetailPreview.items.map((detail, detailIndex) => {
                  if (detail?.__preview_gap) {
                    return (
                      <div className="card" key={`preset-gap-${detail.hiddenCount}-${detailIndex}`}>
                        <div className="empty preset-gap-note" data-hidden={detail.hiddenCount}>
                          â€¦ {detail.hiddenCount} preset table{detail.hiddenCount !== 1 ? 's' : ''} hidden â€¦
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
                          {preset.date_from} → {preset.date_to}
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
      })()}

      {/* ── Walk-forward results ────────────────────────────────────────── */}
      {walkForwardResult && (() => {
        const { folds, totalFolds } = walkForwardResult
        const successFolds = folds.filter((f) => f.testMetrics != null)
        const failedFolds = folds.filter((f) => f.error != null)
        const foldsPreview = buildPreviewState(folds, getSectionMode('walk_forward_folds'))

        // Aggregate OOS metrics across successful folds
        const oosValues = {
          cagr: successFolds.map((f) => numericValue(f.testMetrics?.cagr)).filter((v) => v != null),
          sharpe: successFolds.map((f) => numericValue(f.testMetrics?.sharpe_ratio)).filter((v) => v != null),
          maxDD: successFolds.map((f) => numericValue(f.testMetrics?.max_drawdown)).filter((v) => v != null),
          calmar: successFolds.map((f) => numericValue(f.testMetrics?.calmar_ratio)).filter((v) => v != null),
        }
        const bmValues = {
          cagr: successFolds.map((f) => numericValue(f.benchmarkMetrics?.cagr)).filter((v) => v != null),
          sharpe: successFolds.map((f) => numericValue(f.benchmarkMetrics?.sharpe_ratio)).filter((v) => v != null),
          maxDD: successFolds.map((f) => numericValue(f.benchmarkMetrics?.max_drawdown)).filter((v) => v != null),
        }
        const avg = (arr) => arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null

        const oosAvg = {
          cagr: avg(oosValues.cagr),
          sharpe: avg(oosValues.sharpe),
          maxDD: avg(oosValues.maxDD),
          calmar: avg(oosValues.calmar),
        }
        const bmAvg = {
          cagr: avg(bmValues.cagr),
          sharpe: avg(bmValues.sharpe),
          maxDD: avg(bmValues.maxDD),
        }

        // Count which config was picked most frequently
        const winnerCounts = new Map()
        for (const f of successFolds) {
          if (f.trainWinner) {
            winnerCounts.set(f.trainWinner, (winnerCounts.get(f.trainWinner) || 0) + 1)
          }
        }
        let mostFrequentWinner = null
        let maxCount = 0
        for (const [ck, count] of winnerCounts) {
          if (count > maxCount) { maxCount = count; mostFrequentWinner = ck }
        }

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

        return (
          <>
            {/* ── OOS summary ── */}
            <div className="card">
              <div className="card-title">
                Walk-forward results — {totalFolds} fold{totalFolds !== 1 ? 's' : ''}
              </div>

              {failedFolds.length > 0 && (
                <div className="alert alert-error" style={{ marginBottom: 12 }}>
                  <strong>{failedFolds.length} fold{failedFolds.length !== 1 ? 's' : ''} failed:</strong>
                  <ul style={{ margin: '6px 0 0 0', paddingLeft: 18 }}>
                    {failedFolds.map((f) => (
                      <li key={f.fold} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                        Fold {f.fold} ({f.testFrom} → {f.testTo}) — {f.error}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {successFolds.length === 0 ? (
                <div className="empty">All folds failed. Check the errors above.</div>
              ) : (
                <>
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                    gap: 12,
                    marginBottom: 20,
                  }}>
                    <div className="metric-box">
                      <div className="metric-label">Most frequent winner</div>
                      <div className="metric-value" style={{ fontSize: 15 }}>
                        <span style={WINNER_STYLE}>{mostFrequentWinner ?? '—'}</span>
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
                        benchmark: {pct(bmAvg.cagr)}
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Avg OOS Sharpe</div>
                      <div className="metric-value" style={{ color: colorVal(oosAvg.sharpe) }}>
                        {fmt(oosAvg.sharpe)}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                        benchmark: {fmt(bmAvg.sharpe)}
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Avg OOS Max DD</div>
                      <div className="metric-value" style={{ color: 'var(--error)' }}>
                        {absPct(oosAvg.maxDD)}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                        benchmark: {absPct(bmAvg.maxDD)}
                      </div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Avg OOS Calmar</div>
                      <div className="metric-value">
                        {fmt(oosAvg.calmar)}
                      </div>
                    </div>
                  </div>

                  {/* ── Fold-by-fold table ── */}
                  <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>
                    Fold details — train winner → out-of-sample performance
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
                        {foldsPreview.items.map((f, index) => {
                          if (f?.__preview_gap) {
                            return (
                              <PreviewGapRow
                                key={`wf-gap-${f.hiddenCount}-${index}`}
                                colSpan={10}
                                hiddenCount={f.hiddenCount}
                              />
                            )
                          }
                          const tm = f.testMetrics
                          const bm = f.benchmarkMetrics
                          return (
                            <tr key={f.fold} style={f.error && !tm ? { opacity: 0.5 } : undefined}>
                              <td style={{ fontFamily: 'monospace', color: 'var(--muted)' }}>{f.fold}</td>
                              <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                                {f.trainFrom} → {f.trainTo}
                              </td>
                              <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                                {f.testFrom} → {f.testTo}
                              </td>
                              <td>
                                {f.trainWinner
                                  ? <strong style={{ color: 'var(--success)' }}>{f.trainWinner}</strong>
                                  : <span style={{ color: 'var(--error)', fontStyle: 'italic' }}>failed</span>
                                }
                              </td>
                              <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--muted)' }}>
                                {f.trainAvgRank != null ? f.trainAvgRank.toFixed(2) : '—'}
                              </td>
                              <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(tm?.cagr) }}>
                                {tm ? pct(tm.cagr) : '—'}
                              </td>
                              <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(tm?.sharpe_ratio) }}>
                                {tm ? fmt(tm.sharpe_ratio) : '—'}
                              </td>
                              <td style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--error)' }}>
                                {tm ? absPct(tm.max_drawdown) : '—'}
                              </td>
                              <td style={{ textAlign: 'right', fontFamily: 'monospace' }}>
                                {tm ? fmt(tm.calmar_ratio) : '—'}
                              </td>
                              <td style={{ textAlign: 'right', fontFamily: 'monospace', color: colorVal(bm?.cagr) }}>
                                {bm ? pct(bm.cagr) : '—'}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
                    Each fold: all configs compete on the training window → winner is tested on the subsequent out-of-sample window.
                    BM = SPY buy-and-hold benchmark over the same test period.
                  </div>
                </>
              )}
            </div>
          </>
        )
      })()}

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
              <>
                <PreviewControls
                  preview={rebalancePreview}
                  itemLabel="rebalance periods"
                  onModeChange={(mode) => setSectionMode('single_rebalance', mode)}
                />
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
                    {rebalancePreview.items.map((row, index) => (
                      row?.__preview_gap ? (
                        <PreviewGapRow
                          key={`rebalance-gap-${row.hiddenCount}-${index}`}
                          colSpan={4}
                          hiddenCount={row.hiddenCount}
                        />
                      ) : (
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
                      )
                    ))}
                  </tbody>
                </table>
              </div>
              </>
            ) : (
              <div className="empty">No rebalance periods were returned for this run.</div>
            )}
          </div>

          {trades.length > 0 ? (
            <div className="card">
              <div className="card-title">Trades ({trades.length})</div>
              <PreviewControls
                preview={tradesPreview}
                itemLabel="trades"
                onModeChange={(mode) => setSectionMode('single_trades', mode)}
              />
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
                    {tradesPreview.items.map((trade, index) => (
                      trade?.__preview_gap ? (
                        <PreviewGapRow
                          key={`trades-gap-${trade.hiddenCount}-${index}`}
                          colSpan={6}
                          hiddenCount={trade.hiddenCount}
                        />
                      ) : (
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
                      )
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
