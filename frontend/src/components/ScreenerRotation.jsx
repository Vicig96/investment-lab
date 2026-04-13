import { useState } from 'react'
import { runScreenerRotation } from '../api.js'
import { CompareResults } from './screenerRotation/CompareResults.jsx'
import { CrossPresetResults } from './screenerRotation/CrossPresetResults.jsx'
import { ParameterSweepResults } from './screenerRotation/ParameterSweepResults.jsx'
import { ScreenerRotationForm } from './screenerRotation/ScreenerRotationForm.jsx'
import { SingleRunResults } from './screenerRotation/SingleRunResults.jsx'
import { WalkForwardResults } from './screenerRotation/WalkForwardResults.jsx'
import {
  DEFAULT,
  PRESET_WINDOWS,
  buildBasePayload,
  generateWalkForwardWindows,
  parseConfigKey,
  parseSweepTopN,
  pickBestConfig,
  validate,
} from './screenerRotation/utils.js'

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

        const experiments = topNValues.flatMap((topN) =>
          defensiveModes.map((defensiveMode) => ({
            label: `Top ${topN} \u00b7 ${defensiveMode === 'cash' ? 'Cash' : 'Defensive'}`,
            top_n: topN,
            defensive_mode: defensiveMode,
            payload: { ...basePayload, top_n: topN, defensive_mode: defensiveMode },
          })),
        )

        const settled = await Promise.allSettled(
          experiments.map((experiment) => runScreenerRotation(experiment.payload)),
        )

        const rows = experiments.map((experiment, index) => ({
          ...experiment,
          status: settled[index].status,
          result: settled[index].status === 'fulfilled' ? settled[index].value : null,
          error: settled[index].status === 'rejected'
            ? (settled[index].reason?.message ?? 'request failed')
            : null,
        }))

        const firstOk = rows.find((row) => row.status === 'fulfilled')
        const benchmark = firstOk?.result?.benchmark ?? null

        setSweepResult({ rows, benchmark, totalRuns: experiments.length })
      } else if (form.run_mode === 'cross_preset') {
        const topNValues = parseSweepTopN(form.sweep_top_n)
        const defensiveModes = ['cash', 'defensive_asset']

        const jobs = PRESET_WINDOWS.flatMap((preset) =>
          topNValues.flatMap((topN) =>
            defensiveModes.map((defensiveMode) => ({
              presetLabel: preset.label,
              configKey: `Top ${topN} \u00b7 ${defensiveMode === 'cash' ? 'Cash' : 'Defensive'}`,
              top_n: topN,
              defensive_mode: defensiveMode,
              payload: {
                ...basePayload,
                date_from: preset.date_from,
                date_to: preset.date_to,
                top_n: topN,
                defensive_mode: defensiveMode,
              },
            })),
          ),
        )

        const settled = await Promise.allSettled(
          jobs.map((job) => runScreenerRotation(job.payload)),
        )

        const results = jobs.map((job, index) => ({
          ...job,
          status: settled[index].status,
          result: settled[index].status === 'fulfilled' ? settled[index].value : null,
          error: settled[index].status === 'rejected'
            ? (settled[index].reason?.message ?? 'request failed')
            : null,
        }))

        setCrossPresetResult({ results, totalRuns: jobs.length })
      } else if (form.run_mode === 'walk_forward') {
        const trainYears = parseInt(form.wf_train_years, 10) || 2
        const testYears = parseInt(form.wf_test_years, 10) || 1
        const stepYears = parseInt(form.wf_step_years, 10) || 1
        const windows = generateWalkForwardWindows(
          form.wf_data_start,
          form.wf_data_end,
          trainYears,
          testYears,
          stepYears,
        )

        const topNValues = parseSweepTopN(form.sweep_top_n)
        const defensiveModes = ['cash', 'defensive_asset']
        const folds = []

        for (const window of windows) {
          const trainConfigs = topNValues.flatMap((topN) =>
            defensiveModes.map((defensiveMode) => ({
              configKey: `Top ${topN} \u00b7 ${defensiveMode === 'cash' ? 'Cash' : 'Defensive'}`,
              top_n: topN,
              defensive_mode: defensiveMode,
              payload: {
                ...basePayload,
                date_from: window.trainFrom,
                date_to: window.trainTo,
                top_n: topN,
                defensive_mode: defensiveMode,
              },
            })),
          )

          const trainSettled = await Promise.allSettled(
            trainConfigs.map((config) => runScreenerRotation(config.payload)),
          )

          const trainResults = trainConfigs
            .map((config, index) => ({
              configKey: config.configKey,
              metrics: trainSettled[index].status === 'fulfilled'
                ? trainSettled[index].value.metrics
                : null,
            }))
            .filter((row) => row.metrics != null)

          const bestPick = pickBestConfig(trainResults)

          if (!bestPick) {
            folds.push({
              fold: window.foldIndex,
              trainFrom: window.trainFrom,
              trainTo: window.trainTo,
              testFrom: window.testFrom,
              testTo: window.testTo,
              trainWinner: null,
              trainAvgRank: null,
              trainConfigCount: trainConfigs.length,
              testMetrics: null,
              benchmarkMetrics: null,
              error: 'All training configs failed.',
            })
            continue
          }

          const winnerParams = parseConfigKey(bestPick.configKey)
          const testPayload = {
            ...basePayload,
            date_from: window.testFrom,
            date_to: window.testTo,
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
          } catch (requestError) {
            foldError = requestError.message
          }

          folds.push({
            fold: window.foldIndex,
            trainFrom: window.trainFrom,
            trainTo: window.trainTo,
            testFrom: window.testFrom,
            testTo: window.testTo,
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

  const noResults = !singleResult && !comparisonResult && !sweepResult && !crossPresetResult && !walkForwardResult

  return (
    <>
      <h2 className="section-title">Screener Rotation Backtest</h2>

      <ScreenerRotationForm
        form={form}
        loading={loading}
        formError={formError}
        error={error}
        onSubmit={submit}
        setField={setField}
      />

      {noResults && !loading && !error && (
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
                  ? 'Running walk-forward folds sequentially (training sweep -> OOS test per fold). This may take a moment.'
                  : 'Running screener rotation backtest...'}
        </div>
      )}

      <CompareResults comparisonResult={comparisonResult} form={form} />
      <ParameterSweepResults sweepResult={sweepResult} form={form} />
      <CrossPresetResults
        crossPresetResult={crossPresetResult}
        form={form}
        getSectionMode={getSectionMode}
        setSectionMode={setSectionMode}
      />
      <WalkForwardResults
        walkForwardResult={walkForwardResult}
        form={form}
        getSectionMode={getSectionMode}
        setSectionMode={setSectionMode}
      />
      <SingleRunResults
        result={singleResult}
        getSectionMode={getSectionMode}
        setSectionMode={setSectionMode}
      />
    </>
  )
}
