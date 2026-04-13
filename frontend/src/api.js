const BASE = '/api/v1'

async function request(method, path, { body, form } = {}) {
  const opts = { method, headers: {} }

  if (form) {
    opts.body = form           // FormData — browser sets Content-Type automatically
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }

  const res = await fetch(`${BASE}${path}`, opts)
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = data?.detail
    const label  = detail
      ? (typeof detail === 'string' ? detail : JSON.stringify(detail))
      : null
    throw new Error(label ? `${label} (HTTP ${res.status})` : `HTTP ${res.status}`)
  }
  return data
}

const get  = (path)        => request('GET',    path)
const post = (path, body)  => request('POST',   path, { body })
const del  = (path)        => request('DELETE', path)
const postForm = (path, form) => request('POST', path, { form })

// ── Instruments ──────────────────────────────────────────────────────────────
export const listInstruments = ()     => get('/instruments')
export const createInstrument = (b)   => post('/instruments', b)
export const deleteInstrument = (id)  => del(`/instruments/${id}`)

// ── Prices ───────────────────────────────────────────────────────────────────
export const ingestCsv = (instrumentId, file) => {
  const form = new FormData()
  form.append('instrument_id', instrumentId)
  form.append('file', file)
  return postForm('/prices/ingest', form)
}
export const listPrices = (instrumentId, params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return get(`/instruments/${instrumentId}/prices${qs ? '?' + qs : ''}`)
}
export const priceSummary = (instrumentId) =>
  get(`/instruments/${instrumentId}/prices/summary`)

// ── Indicators ───────────────────────────────────────────────────────────────
export const getIndicator = (instrumentId, name, params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return get(`/instruments/${instrumentId}/indicators/${name}${qs ? '?' + qs : ''}`)
}

// ── Signals ───────────────────────────────────────────────────────────────────
export const runSignals    = (body)         => post('/signals/run', body)
export const listSignals   = (instrumentId) => get(`/instruments/${instrumentId}/signals`)

// ── Backtest ──────────────────────────────────────────────────────────────────
export const runBacktest        = (body) => post('/backtest/run', body)
export const getBacktestResults = (id)   => get(`/backtest/${id}/results`)

// ── Portfolio ─────────────────────────────────────────────────────────────────
export const simulatePortfolio  = (body)          => post('/portfolio/simulate', body)
export const rebalancePortfolio = (weights, nav)  => post(`/portfolio/rebalance?nav=${nav}`, { target_weights: weights })

// ── Screener ──────────────────────────────────────────────────────────────────
export const runScreener = (body) => post('/screener/run', body)

// ── Screener Rotation Backtest ────────────────────────────────────────────────
export const runScreenerRotation = (body) => post('/screener/rotation/run', body)
export const runCopilotChat = (body) => post('/copilot/chat', body)
