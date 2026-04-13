export const DEFAULT = {
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

export const PRESET_WINDOWS = [
  {
    label: 'Bull run',
    date_from: '2019-01-01',
    date_to: '2021-12-31',
    note: 'Extended equity bull market with COVID dip and recovery',
  },
  {
    label: 'Rate hike bear',
    date_from: '2022-01-01',
    date_to: '2023-12-31',
    note: 'Fed tightening cycle - tech selloff, bond stress, sector rotation',
  },
  {
    label: 'Mixed / volatile',
    date_from: '2020-01-01',
    date_to: '2022-12-31',
    note: 'COVID crash, V-shaped recovery, inflation onset',
  },
  {
    label: 'Full cycle',
    date_from: '2019-01-01',
    date_to: '2023-12-31',
    note: 'Bull + bear + recovery - broadest regime coverage',
  },
]

export const STRATEGY_COLOR = 'var(--success)'
export const BENCHMARK_COLOR = '#60a5fa'
export const CASH_COLOR = '#f59e0b'
export const DEFENSIVE_COLOR = '#22c55e'
export const BEST_CELL_STYLE = {
  background: 'rgba(34, 197, 94, 0.10)',
  color: 'var(--success)',
  fontWeight: 700,
}

export function fmt(value, decimals = 2) {
  if (value == null || value === '') return '-'
  const num = Number(value)
  return Number.isNaN(num) ? String(value) : num.toFixed(decimals)
}

export function pct(value, decimals = 2) {
  if (value == null) return '-'
  const num = Number(value)
  return Number.isNaN(num) ? '-' : `${(num * 100).toFixed(decimals)}%`
}

export function absPct(value, decimals = 2) {
  if (value == null) return '-'
  const num = Number(value)
  return Number.isNaN(num) ? '-' : `${(Math.abs(num) * 100).toFixed(decimals)}%`
}

export function colorVal(value) {
  if (value == null) return undefined
  return Number(value) >= 0 ? 'var(--success)' : 'var(--error)'
}

export function buildDateIndex(pointsA, pointsB) {
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

export function buildEquityCurvePoints(points, width, height, padding, lookup, count, minValue, maxValue) {
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

export function parseTickerList(value) {
  return value
    .split(',')
    .map((ticker) => ticker.trim().toUpperCase())
    .filter(Boolean)
}

export function allocationLabel(mode) {
  if (mode === 'risk_on') return 'Risk-on'
  if (mode === 'defensive') return 'Defensive'
  return 'Cash'
}

export function calcCalmar(cagr, maxDrawdown) {
  const c = Number(cagr)
  const md = Number(maxDrawdown)
  if (!Number.isFinite(c) || !Number.isFinite(md) || md === 0) return null
  return c / Math.abs(md)
}

export function parseSweepTopN(raw) {
  return raw
    .split(',')
    .map((s) => parseInt(s.trim(), 10))
    .filter((n) => Number.isFinite(n) && n >= 1 && n <= 20)
}

export function validate(form) {
  const tickers = parseTickerList(form.instrument_tickers)
  if (!tickers.length) return 'At least one ticker is required.'
  if (Number(form.initial_capital) <= 0) return 'Initial capital must be > 0.'
  if (Number(form.commission_bps) < 0) return 'Commission must be >= 0.'
  if (Number(form.warmup_bars) < 0) return 'Warm-up bars must be >= 0.'

  if (form.run_mode === 'cross_preset') {
    const topNValues = parseSweepTopN(form.sweep_top_n)
    if (!topNValues.length) return 'Enter at least one valid Top N value (1-20).'
    if (parseTickerList(form.defensive_tickers).length === 0) {
      return 'Add at least one defensive ticker - cross-preset runs both cash and defensive_asset.'
    }
    return null
  }

  if (form.run_mode === 'walk_forward') {
    if (!form.wf_data_start) return '"Data start" date is required.'
    if (!form.wf_data_end) return '"Data end" date is required.'
    if (form.wf_data_start >= form.wf_data_end) return '"Data start" must be before "Data end".'
    const topNValues = parseSweepTopN(form.sweep_top_n)
    if (!topNValues.length) return 'Enter at least one valid Top N value (1-20).'
    if (parseTickerList(form.defensive_tickers).length === 0) {
      return 'Add at least one defensive ticker - walk-forward runs both cash and defensive_asset.'
    }
    const trainYears = parseInt(form.wf_train_years, 10)
    const testYears = parseInt(form.wf_test_years, 10)
    const stepYears = parseInt(form.wf_step_years, 10)
    if (!trainYears || trainYears < 1) return 'Train years must be >= 1.'
    if (!testYears || testYears < 1) return 'Test years must be >= 1.'
    if (!stepYears || stepYears < 1) return 'Step years must be >= 1.'
    const windows = generateWalkForwardWindows(form.wf_data_start, form.wf_data_end, trainYears, testYears, stepYears)
    if (!windows.length) {
      return 'No valid walk-forward windows fit within the data range. Increase the date range or decrease train/test years.'
    }
    return null
  }

  if (!form.date_from) return '"From" date is required.'
  if (!form.date_to) return '"To" date is required.'
  if (form.date_from >= form.date_to) return '"From" must be before "To".'

  if (form.run_mode === 'parameter_sweep') {
    const topNValues = parseSweepTopN(form.sweep_top_n)
    if (!topNValues.length) return 'Enter at least one valid Top N value (1-20) for the sweep.'
    if (parseTickerList(form.defensive_tickers).length === 0) {
      return 'Add at least one defensive ticker - sweep runs both cash and defensive_asset modes.'
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

export function buildBasePayload(form) {
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

export function numericValue(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function getBestValue(rows, metricKey, preference) {
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

export function isBestMetric(rows, metricKey, preference, candidate) {
  const bestValue = getBestValue(rows, metricKey, preference)
  const currentValue = numericValue(candidate)
  if (bestValue == null || currentValue == null) return false
  const comparable = metricKey === 'max_drawdown' ? Math.abs(currentValue) : currentValue
  return Math.abs(comparable - bestValue) < 1e-9
}

export function calcDeltas(aMetrics, bMetrics) {
  const a = aMetrics ?? {}
  const b = bMetrics ?? {}
  const av = (key) => numericValue(a[key])
  const bv = (key) => numericValue(b[key])

  const eq = av('final_equity') != null && bv('final_equity') != null
    ? av('final_equity') - bv('final_equity')
    : null
  const cagr = av('cagr') != null && bv('cagr') != null
    ? av('cagr') - bv('cagr')
    : null
  const sharpe = av('sharpe_ratio') != null && bv('sharpe_ratio') != null
    ? av('sharpe_ratio') - bv('sharpe_ratio')
    : null
  const dd = av('max_drawdown') != null && bv('max_drawdown') != null
    ? Math.abs(bv('max_drawdown')) - Math.abs(av('max_drawdown'))
    : null

  return { eq, cagr, sharpe, dd }
}

export function denseRank(values, higherIsBetter) {
  const indexed = values.map((v, i) => ({ v: numericValue(v), i }))
  const valid = indexed.filter((x) => x.v != null)
  if (!valid.length) return values.map(() => null)

  valid.sort((a, b) => (higherIsBetter ? b.v - a.v : a.v - b.v))

  const ranks = new Array(values.length).fill(null)
  let rank = 1
  for (let j = 0; j < valid.length; j++) {
    if (j > 0 && valid[j].v !== valid[j - 1].v) rank = j + 1
    ranks[valid[j].i] = rank
  }
  return ranks
}

export function computeCrossPresetRanking(configKeys, resultsByConfig) {
  const rankMetrics = [
    { key: 'cagr', higher: true },
    { key: 'sharpe_ratio', higher: true },
    { key: 'max_drawdown', higher: false },
    { key: 'calmar_ratio', higher: true },
  ]

  const presetLabels = []
  for (const configMap of resultsByConfig.values()) {
    for (const presetLabel of configMap.keys()) {
      if (!presetLabels.includes(presetLabel)) presetLabels.push(presetLabel)
    }
  }

  const perPresetRanks = new Map()
  for (const configKey of configKeys) perPresetRanks.set(configKey, new Map())

  for (const presetLabel of presetLabels) {
    for (const metric of rankMetrics) {
      const rawValues = configKeys.map((configKey) => {
        const metrics = resultsByConfig.get(configKey)?.get(presetLabel)
        if (!metrics) return null
        return metric.key === 'max_drawdown'
          ? (numericValue(metrics.max_drawdown) != null ? Math.abs(numericValue(metrics.max_drawdown)) : null)
          : numericValue(metrics[metric.key])
      })
      const ranks = denseRank(rawValues, metric.key === 'max_drawdown' ? false : metric.higher)
      for (let i = 0; i < configKeys.length; i++) {
        const configKey = configKeys[i]
        const configMap = perPresetRanks.get(configKey)
        if (!configMap.has(presetLabel)) configMap.set(presetLabel, [])
        if (ranks[i] != null) configMap.get(presetLabel).push(ranks[i])
      }
    }
  }

  const scores = new Map()
  for (const configKey of configKeys) {
    const presetAvg = new Map()
    const allAvgs = []
    for (const presetLabel of presetLabels) {
      const ranks = perPresetRanks.get(configKey)?.get(presetLabel) ?? []
      if (ranks.length > 0) {
        const avg = ranks.reduce((a, b) => a + b, 0) / ranks.length
        presetAvg.set(presetLabel, avg)
        allAvgs.push(avg)
      }
    }
    const overall = allAvgs.length > 0
      ? allAvgs.reduce((a, b) => a + b, 0) / allAvgs.length
      : null
    scores.set(configKey, { presetAvg, overall })
  }

  return scores
}

export function toDateStr(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function generateWalkForwardWindows(dataStart, dataEnd, trainYears, testYears, stepYears) {
  const windows = []
  const endDate = new Date(`${dataEnd}T00:00:00`)
  let cursor = new Date(`${dataStart}T00:00:00`)
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
    foldIndex += 1
  }

  return windows
}

export function pickBestConfig(configResults) {
  if (!configResults.length) return null
  const metrics = [
    { key: 'cagr', higher: true },
    { key: 'sharpe_ratio', higher: true },
    { key: 'max_drawdown', higher: false },
    { key: 'calmar_ratio', higher: true },
  ]

  const totals = new Array(configResults.length).fill(0)
  let metricsUsed = 0

  for (const metric of metrics) {
    const values = configResults.map((result) => {
      const value = numericValue(result.metrics[metric.key])
      if (value == null) return null
      return metric.key === 'max_drawdown' ? Math.abs(value) : value
    })
    const ranks = denseRank(values, metric.key === 'max_drawdown' ? false : metric.higher)
    let anyRank = false
    for (let i = 0; i < configResults.length; i++) {
      if (ranks[i] != null) {
        totals[i] += ranks[i]
        anyRank = true
      }
    }
    if (anyRank) metricsUsed += 1
  }

  if (metricsUsed === 0) {
    return { configKey: configResults[0].configKey, avgRank: null }
  }

  let bestIndex = 0
  let bestScore = Infinity
  for (let i = 0; i < configResults.length; i++) {
    const avgRank = totals[i] / metricsUsed
    if (avgRank < bestScore) {
      bestScore = avgRank
      bestIndex = i
    }
  }

  return { configKey: configResults[bestIndex].configKey, avgRank: bestScore }
}

export function parseConfigKey(configKey) {
  const match = configKey.match(/Top\s+(\d+)\s+\u00b7\s+(Cash|Defensive)/)
  if (!match) return { top_n: 1, defensive_mode: 'cash' }
  return {
    top_n: parseInt(match[1], 10),
    defensive_mode: match[2] === 'Cash' ? 'cash' : 'defensive_asset',
  }
}

export function summarizePreviewItems(items, headCount, tailCount = 0) {
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

export function buildPreviewState(items, mode, options = {}) {
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

export function average(values) {
  if (!Array.isArray(values) || values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

export function stdDeviation(values) {
  if (!Array.isArray(values) || values.length === 0) return null
  const avg = average(values)
  if (avg == null) return null
  const variance = values.reduce((sum, value) => sum + (value - avg) ** 2, 0) / values.length
  return Math.sqrt(variance)
}

export function visiblePreviewItems(preview) {
  if (!Array.isArray(preview?.items)) return []
  return preview.items.filter((item) => item && !item.__preview_gap)
}

export function slugifyFilePart(value) {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'na'
}

export function toCsvCell(value) {
  if (value == null) return ''
  const stringValue = String(value)
  if (/[",\r\n]/.test(stringValue)) {
    return `"${stringValue.replace(/"/g, '""')}"`
  }
  return stringValue
}

export function buildCsvContent(metadata, columns, rows) {
  const lines = [
    ['meta_key', 'meta_value'],
    ...metadata.map((entry) => [entry.key, entry.value]),
    [],
    columns.map((column) => column.label),
    ...rows.map((row) => columns.map((column) => column.value(row))),
  ]

  return lines
    .map((line) => (line.length > 0 ? line.map(toCsvCell).join(',') : ''))
    .join('\r\n')
}

export function triggerCsvDownload(filename, content) {
  if (typeof document === 'undefined') return
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function buildExportFilename(form, mode, suffix = 'results') {
  const tickers = parseTickerList(form.instrument_tickers).slice(0, 5).join('-') || 'universe'
  const windowLabel = mode === 'walk-forward'
    ? `${form.wf_data_start}-to-${form.wf_data_end}`
    : mode === 'cross-preset'
      ? 'preset-windows'
      : `${form.date_from}-to-${form.date_to}`
  const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
  return [
    'screener-rotation',
    slugifyFilePart(mode),
    slugifyFilePart(tickers),
    slugifyFilePart(windowLabel),
    slugifyFilePart(suffix),
    timestamp,
  ].join('-') + '.csv'
}

export function buildBaseExportMetadata(form, mode) {
  return [
    { key: 'run_mode', value: mode },
    { key: 'tickers', value: parseTickerList(form.instrument_tickers).join('|') },
    { key: 'initial_capital', value: form.initial_capital },
    { key: 'commission_bps', value: form.commission_bps },
    { key: 'rebalance_frequency', value: form.rebalance_frequency },
    { key: 'warmup_bars', value: form.warmup_bars },
    { key: 'defensive_tickers', value: parseTickerList(form.defensive_tickers).join('|') },
  ]
}

export function exportVisibleCsv({ form, mode, suffix, metadata, columns, rows }) {
  const csv = buildCsvContent(metadata, columns, rows)
  const filename = buildExportFilename(form, mode, suffix)
  triggerCsvDownload(filename, csv)
}
