import {
  PRESET_WINDOWS,
  generateWalkForwardWindows,
  parseSweepTopN,
} from './utils.js'

export function ScreenerRotationForm({
  form,
  loading,
  formError,
  error,
  onSubmit,
  setField,
}) {
  const topNCount = parseSweepTopN(form.sweep_top_n).length

  return (
    <div className="card">
      <div className="card-title">Configuration</div>
      <form className="form" onSubmit={onSubmit}>
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

        {form.run_mode !== 'cross_preset' && form.run_mode !== 'walk_forward' && (
          <div className="field">
            <label>Preset windows</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {PRESET_WINDOWS.map((preset) => {
                const active =
                  form.date_from === preset.date_from &&
                  form.date_to === preset.date_to
                return (
                  <button
                    key={preset.label}
                    type="button"
                    disabled={loading}
                    title={preset.note}
                    onClick={() => {
                      setField('date_from', preset.date_from)
                      setField('date_to', preset.date_to)
                    }}
                    style={{
                      padding: '4px 12px',
                      fontSize: 12,
                      fontWeight: active ? 700 : 400,
                      borderRadius: 4,
                      border: active
                        ? '1px solid var(--accent)'
                        : '1px solid var(--border)',
                      background: active
                        ? 'rgba(79,142,247,0.15)'
                        : 'var(--surface)',
                      color: active ? 'var(--accent)' : 'var(--muted)',
                      cursor: loading ? 'not-allowed' : 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {preset.label}
                    <span style={{ marginLeft: 6, opacity: 0.55, fontFamily: 'monospace' }}>
                      {preset.date_from.slice(0, 4)}-{preset.date_to.slice(0, 4)}
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
            Each Top N value is run twice - once with cash and once with defensive asset.
            {' '}<strong style={{ color: 'var(--text)' }}>
              {topNCount * 2} experiment{topNCount * 2 !== 1 ? 's' : ''} will run in parallel.
            </strong>
          </div>
        )}
        {form.run_mode === 'cross_preset' && (() => {
          const nConfigs = topNCount * 2
          const nTotal = PRESET_WINDOWS.length * nConfigs
          return (
            <div style={{ marginBottom: 12, color: 'var(--muted)', fontSize: 13 }}>
              Runs every Top N x defensive mode combination across all {PRESET_WINDOWS.length} preset windows
              ({PRESET_WINDOWS.map((preset) => preset.label).join(', ')}).
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
          const nConfigs = topNCount * 2
          const wins = (trainYears >= 1 && testYears >= 1 && stepYears >= 1 && form.wf_data_start && form.wf_data_end)
            ? generateWalkForwardWindows(form.wf_data_start, form.wf_data_end, trainYears, testYears, stepYears)
            : []
          return (
            <div style={{ marginBottom: 12, color: 'var(--muted)', fontSize: 13 }}>
              Rolling walk-forward: {trainYears}y train -&gt; {testYears}y test, stepping {stepYears}y forward each fold.
              {' '}
              {wins.length > 0 ? (
                <>
                  <strong style={{ color: 'var(--text)' }}>
                    {wins.length} fold{wins.length !== 1 ? 's' : ''}
                  </strong>
                  {' '}x {nConfigs} configs = {wins.length * nConfigs} training runs + {wins.length} OOS tests.
                </>
              ) : (
                <span style={{ color: 'var(--warning)' }}>No valid folds for this date range.</span>
              )}
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
  )
}
