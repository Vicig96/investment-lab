import { useState } from 'react'
import {
  listCopilotFindings,
  listJournalDecisions,
  runCopilotChat,
  runCopilotComparativeValidation,
  runCopilotForwardValidationPilot,
  runCopilotMonitoring,
  runCopilotOutcomes,
  runCopilotPaperPortfolioNav,
  runCopilotShadowPortfolio,
  runCopilotScorecard,
  saveJournalDecision,
  updateJournalDecision,
} from '../api.js'

const ACTION_LABELS = {
  accepted: 'Accepted',
  rejected: 'Rejected',
  watchlist: 'Watchlist',
  paper_only: 'Paper only',
  pending: 'Pending',
}

function extractTopResult(response) {
  const data = response.supporting_data || {}
  return (
    data.monitoring?.current_snapshot?.top_deterministic_result
    || data.monitoring?.current_snapshot?.best_eligible_asset
    || data.recommendation?.top_deterministic_result
    || data.ranking?.ranked_assets?.[0]?.ticker
    || data.recommendation?.recommended_entity
    || data.strategy_evaluation?.cross_preset?.recommended_default_config
    || data.strategy_evaluation?.walk_forward?.most_frequent_winner
    || data.strategy_evaluation?.single_run?.config_key
    || null
  )
}

function buildRecommendationSnapshot(response) {
  const recommendation = response.supporting_data?.recommendation || {}
  const monitoring = response.supporting_data?.monitoring?.current_snapshot || {}
  const snapshot = {
    headline: response.answer.headline ?? null,
    summary: response.answer.summary ?? null,
    deterministic_evidence_summary: response.answer.deterministic_evidence_summary ?? null,
    profile_decision_summary: response.answer.profile_decision_summary ?? null,
    portfolio_decision_summary: response.answer.portfolio_decision_summary ?? null,
    final_recommendation_summary: response.answer.final_recommendation_summary ?? null,
    why_this_is_or_is_not_actionable: response.answer.why_this_is_or_is_not_actionable ?? null,
    recommended_entity: recommendation.recommended_entity ?? monitoring.best_eligible_asset ?? null,
    recommended_entity_type: recommendation.recommended_entity_type ?? (monitoring.best_eligible_asset ? 'asset' : null),
    why_preferred: recommendation.why_preferred ?? [],
    invalidation_conditions: recommendation.invalidation_conditions ?? [],
    risks: recommendation.risks ?? [],
    caveats: recommendation.caveats ?? [],
  }
  return Object.values(snapshot).some((value) => Array.isArray(value) ? value.length > 0 : value != null && value !== '')
    ? snapshot
    : null
}

function buildReviewState(entry) {
  return {
    action_taken: entry?.action_taken ?? '',
    review_date: entry?.review_date ?? '',
    outcome_notes: entry?.outcome_notes ?? '',
  }
}

function Section({ title, children }) {
  if (!children) return null
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function BulletList({ items, renderItem, keyFn }) {
  if (!items?.length) return null
  return (
    <ul style={{ paddingLeft: 18, marginBottom: 0 }}>
      {items.map((item, index) => <li key={keyFn ? keyFn(item, index) : index}>{renderItem ? renderItem(item, index) : item}</li>)}
    </ul>
  )
}

function CountList({ items }) {
  if (!items?.length) return <div style={{ fontSize: 12, color: 'var(--muted)' }}>No data yet.</div>
  return (
    <ul style={{ paddingLeft: 18, marginBottom: 0 }}>
      {items.map((item) => <li key={item.item}><strong>{item.item}</strong>: {item.count}</li>)}
    </ul>
  )
}

export default function CopilotChat() {
  const [query, setQuery] = useState('Show me a market snapshot for SPY, QQQ, TLT, GLD')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [sessionState, setSessionState] = useState(null)
  const [messages, setMessages] = useState([])
  const [savedMessages, setSavedMessages] = useState({})
  const [journalSaving, setJournalSaving] = useState(new Set())
  const [journalError, setJournalError] = useState(null)
  const [recentDecisions, setRecentDecisions] = useState([])
  const [showRecent, setShowRecent] = useState(false)
  const [recentLoading, setRecentLoading] = useState(false)
  const [reviewSaving, setReviewSaving] = useState(false)
  const [recentFilters, setRecentFilters] = useState({ ticker: '', recommendation_status: '', action_taken: '', date_from: '', date_to: '' })
  const [selectedDecisionId, setSelectedDecisionId] = useState(null)
  const [reviewDraft, setReviewDraft] = useState(buildReviewState(null))
  const [findings, setFindings] = useState([])
  const [findingsLoading, setFindingsLoading] = useState(false)
  const [monitoringLoading, setMonitoringLoading] = useState(false)
  const [monitoringError, setMonitoringError] = useState(null)
  const [monitoringSummary, setMonitoringSummary] = useState(null)
  const [outcomes, setOutcomes] = useState(null)
  const [outcomesLoading, setOutcomesLoading] = useState(false)
  const [outcomesError, setOutcomesError] = useState(null)
  const [forwardPilot, setForwardPilot] = useState(null)
  const [forwardPilotLoading, setForwardPilotLoading] = useState(false)
  const [forwardPilotError, setForwardPilotError] = useState(null)
  const [paperPortfolioNav, setPaperPortfolioNav] = useState(null)
  const [paperPortfolioLoading, setPaperPortfolioLoading] = useState(false)
  const [paperPortfolioError, setPaperPortfolioError] = useState(null)
  const [shadowPortfolio, setShadowPortfolio] = useState(null)
  const [shadowLoading, setShadowLoading] = useState(false)
  const [shadowError, setShadowError] = useState(null)
  const [comparativeValidation, setComparativeValidation] = useState(null)
  const [comparativeLoading, setComparativeLoading] = useState(false)
  const [comparativeError, setComparativeError] = useState(null)
  const [scorecard, setScorecard] = useState(null)
  const [scorecardLoading, setScorecardLoading] = useState(false)
  const [scorecardError, setScorecardError] = useState(null)

  const loadFindings = async () => {
    setFindingsLoading(true)
    setMonitoringError(null)
    try {
      const result = await listCopilotFindings({ limit: 10 })
      setFindings(result.entries ?? [])
    } catch (requestError) {
      setMonitoringError(requestError.message)
    } finally {
      setFindingsLoading(false)
    }
  }

  const handleRunMonitoring = async () => {
    if (monitoringLoading) return
    setMonitoringLoading(true)
    setMonitoringError(null)
    try {
      const result = await runCopilotMonitoring({})
      setMonitoringSummary(result.summary ?? 'Monitoring run completed.')
      await loadFindings()
    } catch (requestError) {
      setMonitoringError(requestError.message)
    } finally {
      setMonitoringLoading(false)
    }
  }

  const handleRunScorecard = async () => {
    if (scorecardLoading) return
    setScorecardLoading(true)
    setScorecardError(null)
    try {
      const result = await runCopilotScorecard({})
      setScorecard(result)
    } catch (requestError) {
      setScorecardError(requestError.message)
    } finally {
      setScorecardLoading(false)
    }
  }

  const handleRunOutcomes = async () => {
    if (outcomesLoading) return
    setOutcomesLoading(true)
    setOutcomesError(null)
    try {
      const result = await runCopilotOutcomes({})
      setOutcomes(result)
    } catch (requestError) {
      setOutcomesError(requestError.message)
    } finally {
      setOutcomesLoading(false)
    }
  }

  const handleRunShadowPortfolio = async () => {
    if (shadowLoading) return
    setShadowLoading(true)
    setShadowError(null)
    try {
      const result = await runCopilotShadowPortfolio({})
      setShadowPortfolio(result)
    } catch (requestError) {
      setShadowError(requestError.message)
    } finally {
      setShadowLoading(false)
    }
  }

  const handleRunPaperPortfolioNav = async () => {
    if (paperPortfolioLoading) return
    setPaperPortfolioLoading(true)
    setPaperPortfolioError(null)
    try {
      const result = await runCopilotPaperPortfolioNav({ apply_exit_policy: true })
      setPaperPortfolioNav(result)
    } catch (requestError) {
      setPaperPortfolioError(requestError.message)
    } finally {
      setPaperPortfolioLoading(false)
    }
  }

  const handleRunForwardPilot = async () => {
    if (forwardPilotLoading) return
    setForwardPilotLoading(true)
    setForwardPilotError(null)
    try {
      const result = await runCopilotForwardValidationPilot({})
      setForwardPilot(result)
    } catch (requestError) {
      setForwardPilotError(requestError.message)
    } finally {
      setForwardPilotLoading(false)
    }
  }

  const handleRunComparativeValidation = async () => {
    if (comparativeLoading) return
    setComparativeLoading(true)
    setComparativeError(null)
    try {
      const result = await runCopilotComparativeValidation({})
      setComparativeValidation(result)
    } catch (requestError) {
      setComparativeError(requestError.message)
    } finally {
      setComparativeLoading(false)
    }
  }

  const loadRecentDecisions = async (filters = recentFilters, { preserveSelection = false } = {}) => {
    setRecentLoading(true)
    setJournalError(null)
    try {
      const result = await listJournalDecisions({
        ticker: filters.ticker || null,
        recommendation_status: filters.recommendation_status || null,
        action_taken: filters.action_taken || null,
        date_from: filters.date_from || null,
        date_to: filters.date_to || null,
        limit: 10,
      })
      const entries = result.entries ?? []
      setRecentDecisions(entries)
      setShowRecent(true)
      if (!entries.length) {
        setSelectedDecisionId(null)
        setReviewDraft(buildReviewState(null))
        return
      }
      if (preserveSelection && selectedDecisionId) {
        const selected = entries.find((entry) => entry.decision_id === selectedDecisionId)
        if (selected) {
          setReviewDraft(buildReviewState(selected))
          return
        }
      }
      setSelectedDecisionId(entries[0].decision_id)
      setReviewDraft(buildReviewState(entries[0]))
    } catch (requestError) {
      setJournalError(requestError.message)
    } finally {
      setRecentLoading(false)
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed || loading) return
    setLoading(true)
    setError(null)
    setMessages((prev) => [...prev, { role: 'user', query: trimmed }])
    try {
      const response = await runCopilotChat({ user_query: trimmed, session_state: sessionState })
      setSessionState(response.session_state)
      setMessages((prev) => [...prev, { role: 'assistant', response }])
      setQuery('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const handleSaveDecision = async (message, index) => {
    setJournalSaving((prev) => new Set(prev).add(index))
    setJournalError(null)
    try {
      const response = message.response
      const saved = await saveJournalDecision({
        user_query: response.user_query,
        detected_intent: response.detected_intent,
        top_deterministic_result: extractTopResult(response),
        final_recommendation: buildRecommendationSnapshot(response),
        recommendation_status: response.recommendation_status ?? null,
        recommended_action_type: response.recommended_action_type ?? null,
        profile_constraints_applied: response.profile_constraints_applied ?? [],
        knowledge_sources_used: response.knowledge_sources_used ?? [],
        portfolio_context_applied: response.portfolio_context_applied ?? [],
        portfolio_decision_summary: response.answer.portfolio_decision_summary ?? null,
      })
      setSavedMessages((prev) => ({ ...prev, [index]: { decision_id: saved.decision_id, action_taken: saved.action_taken ?? null } }))
      if (showRecent) await loadRecentDecisions(recentFilters, { preserveSelection: true })
    } catch (requestError) {
      setJournalError(requestError.message)
    } finally {
      setJournalSaving((prev) => { const next = new Set(prev); next.delete(index); return next })
    }
  }

  const handleUpdateAction = async (decisionId, action, index) => {
    setJournalError(null)
    try {
      const updated = await updateJournalDecision(decisionId, { action_taken: action })
      setSavedMessages((prev) => ({ ...prev, [index]: { ...prev[index], action_taken: action } }))
      setRecentDecisions((prev) => prev.map((entry) => (entry.decision_id === decisionId ? updated : entry)))
      if (selectedDecisionId === decisionId) setReviewDraft(buildReviewState(updated))
    } catch (requestError) {
      setJournalError(requestError.message)
    }
  }

  const handleSaveReview = async () => {
    if (!selectedDecisionId || reviewSaving) return
    setReviewSaving(true)
    setJournalError(null)
    try {
      const updated = await updateJournalDecision(selectedDecisionId, {
        action_taken: reviewDraft.action_taken || undefined,
        review_date: reviewDraft.review_date || undefined,
        outcome_notes: reviewDraft.outcome_notes.trim() || undefined,
      })
      setRecentDecisions((prev) => prev.map((entry) => (entry.decision_id === selectedDecisionId ? updated : entry)))
      setReviewDraft(buildReviewState(updated))
      setSavedMessages((prev) => {
        const next = { ...prev }
        for (const [messageIndex, saved] of Object.entries(next)) {
          if (saved?.decision_id === selectedDecisionId) next[messageIndex] = { ...saved, action_taken: updated.action_taken ?? null }
        }
        return next
      })
    } catch (requestError) {
      setJournalError(requestError.message)
    } finally {
      setReviewSaving(false)
    }
  }

  const selectedDecision = recentDecisions.find((entry) => entry.decision_id === selectedDecisionId) ?? null

  return (
    <>
      <h2 className="section-title">Investment Copilot</h2>
      <div className="card">
        <div className="card-title">Copilot Chat</div>
        <form className="form" onSubmit={submit}>
          <div className="field">
            <label>Ask a question</label>
            <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask for a market snapshot, ranking, strategy evaluation, or explain the last result." disabled={loading} />
          </div>
          <button className="btn btn-primary" type="submit" disabled={loading || !query.trim()}>{loading ? <span className="spinner" /> : null}Send</button>
        </form>
        {error && <div className="alert alert-error" style={{ marginTop: 12 }}>{error}</div>}
      </div>

      {messages.length === 0 && !loading && !error && <div className="empty" style={{ paddingTop: 24 }}>Try: "Rank SPY, QQQ, TLT, GLD" or "Run a cross-preset strategy evaluation for SPY, QQQ, IWM, TLT, GLD".</div>}

      {messages.map((message, index) => (
        <div className="card" key={`${message.role}-${index}`}>
          <div className="card-title">{message.role === 'user' ? 'You' : 'Assistant'}</div>
          {message.role === 'user' ? <div>{message.query}</div> : (
            <>
              <div style={{ marginBottom: 12 }}><strong>{message.response.answer.headline}</strong></div>
              <div style={{ marginBottom: 12, color: 'var(--text)' }}>{message.response.answer.summary}</div>
              <BulletList items={message.response.answer.bullets} keyFn={(item) => item} />
              <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 12, marginBottom: 10 }}>
                Intent: <strong style={{ color: 'var(--text)' }}>{message.response.detected_intent}</strong> | Tools used: <strong style={{ color: 'var(--text)' }}>{message.response.tools_used.join(', ') || 'none'}</strong>
                {message.response.recommendation_status ? <> | Recommendation status: <strong style={{ color: 'var(--text)' }}>{message.response.recommendation_status}</strong></> : null}
                {message.response.recommended_action_type ? <> | Action: <strong style={{ color: 'var(--text)' }}>{message.response.recommended_action_type}</strong></> : null}
              </div>
              <Section title="Deterministic evidence">{message.response.answer.deterministic_evidence_summary}</Section>
              <Section title="Profile decision">{message.response.answer.profile_decision_summary}</Section>
              <Section title="Portfolio decision">{message.response.answer.portfolio_decision_summary}</Section>
              <Section title="Final recommendation">{message.response.answer.final_recommendation_summary}</Section>
              <Section title="Actionability">{message.response.answer.why_this_is_or_is_not_actionable}</Section>
              {message.response.warnings?.length > 0 && <div className="alert alert-info" style={{ marginTop: 0, marginBottom: 12 }}>{message.response.warnings.slice(0, 3).map((warning) => <div key={warning}>{warning}</div>)}</div>}
              <Section title="Profile constraints applied"><BulletList items={message.response.profile_constraints_applied} renderItem={(item) => <><strong>{item.category}</strong>: {item.detail}</>} keyFn={(item, itemIndex) => `${item.constraint}-${itemIndex}`} /></Section>
              <Section title="Portfolio context applied"><BulletList items={message.response.portfolio_context_applied} renderItem={(item) => <><strong>{item.status}</strong>: {item.detail}</>} keyFn={(item, itemIndex) => `${item.check}-${itemIndex}`} /></Section>
              {message.response.position_context && <Section title="Current portfolio impact"><div><strong>{message.response.position_context.ticker}</strong>{message.response.position_context.is_held ? ' is already held.' : ' is not currently held.'}</div></Section>}
              <Section title="Concentration notes"><BulletList items={message.response.concentration_notes} keyFn={(item) => item} /></Section>
              <Section title="Eligible alternatives"><BulletList items={message.response.eligible_alternatives} renderItem={(item) => <><strong>{item.entity}</strong> ({item.recommendation_status}) - {item.reason}</>} keyFn={(item) => `${item.entity}-${item.recommendation_status}`} /></Section>
              <Section title="Knowledge sources used"><BulletList items={message.response.knowledge_sources_used} renderItem={(item) => <><strong>{item.title}</strong> ({item.doc_type || 'note'}, {item.confidence_tier}) - {item.source}</>} keyFn={(item) => `${item.source}-${item.title}`} /></Section>
              <Section title="Confidence notes"><BulletList items={message.response.answer.confidence_notes} keyFn={(item) => item} /></Section>
              <Section title="Next actions"><BulletList items={message.response.next_actions} keyFn={(item) => item} /></Section>
              <div className="json-block">{JSON.stringify(message.response.supporting_data, null, 2)}</div>
              <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                {!savedMessages[index] ? (
                  <button className="btn" type="button" style={{ fontSize: 12 }} onClick={() => handleSaveDecision(message, index)} disabled={journalSaving.has(index)}>
                    {journalSaving.has(index) ? 'Saving...' : 'Save to Journal'}
                  </button>
                ) : (
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
                      Saved to journal. ID: <code style={{ fontSize: 11 }}>{savedMessages[index].decision_id.slice(0, 8)}...</code>
                      {savedMessages[index].action_taken ? <> | <span style={{ color: 'var(--success)' }}>Marked: {ACTION_LABELS[savedMessages[index].action_taken] ?? savedMessages[index].action_taken}</span></> : ' | Mark your action:'}
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {Object.entries(ACTION_LABELS).map(([key, label]) => <button key={key} className={`btn${savedMessages[index].action_taken === key ? ' btn-primary' : ''}`} type="button" style={{ fontSize: 11, padding: '3px 10px' }} onClick={() => handleUpdateAction(savedMessages[index].decision_id, key, index)}>{label}</button>)}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      ))}

      {journalError && <div className="alert alert-error">Journal error: {journalError}</div>}

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: showRecent ? 12 : 0 }}>
          <span>Decision Journal</span>
          <button className="btn" type="button" style={{ fontSize: 12 }} onClick={() => showRecent ? setShowRecent(false) : loadRecentDecisions()} disabled={recentLoading}>{recentLoading ? 'Loading...' : showRecent ? 'Hide' : 'Show recent'}</button>
        </div>
        {showRecent && (
          <>
            <div className="form" style={{ marginBottom: 12 }}>
              <div className="field"><label>Ticker</label><input value={recentFilters.ticker} onChange={(event) => setRecentFilters((prev) => ({ ...prev, ticker: event.target.value }))} placeholder="SPY" /></div>
              <div className="field"><label>Recommendation status</label><input value={recentFilters.recommendation_status} onChange={(event) => setRecentFilters((prev) => ({ ...prev, recommendation_status: event.target.value }))} placeholder="eligible_add_to_existing" /></div>
              <div className="field"><label>Action taken</label><select value={recentFilters.action_taken} onChange={(event) => setRecentFilters((prev) => ({ ...prev, action_taken: event.target.value }))}><option value="">All</option>{Object.entries(ACTION_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
              <div className="field"><label>Date from</label><input type="date" value={recentFilters.date_from} onChange={(event) => setRecentFilters((prev) => ({ ...prev, date_from: event.target.value }))} /></div>
              <div className="field"><label>Date to</label><input type="date" value={recentFilters.date_to} onChange={(event) => setRecentFilters((prev) => ({ ...prev, date_to: event.target.value }))} /></div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn" type="button" onClick={() => loadRecentDecisions()} disabled={recentLoading}>{recentLoading ? 'Loading...' : 'Apply filters'}</button>
                <button className="btn" type="button" onClick={() => { const empty = { ticker: '', recommendation_status: '', action_taken: '', date_from: '', date_to: '' }; setRecentFilters(empty); loadRecentDecisions(empty) }} disabled={recentLoading}>Reset</button>
              </div>
            </div>
            {recentDecisions.length === 0 ? <div className="empty">No decisions saved yet.</div> : (
              <>
                <div className="table-wrap">
                  <table className="table-compact">
                    <thead><tr><th>Date</th><th>Query</th><th>Top result</th><th>Status</th><th>Action taken</th><th>Notes</th></tr></thead>
                    <tbody>
                      {recentDecisions.map((entry) => (
                        <tr key={entry.decision_id} onClick={() => { setSelectedDecisionId(entry.decision_id); setReviewDraft(buildReviewState(entry)) }} style={{ cursor: 'pointer', background: entry.decision_id === selectedDecisionId ? 'rgba(255,255,255,0.03)' : 'transparent' }}>
                          <td style={{ fontFamily: 'monospace', fontSize: 12, whiteSpace: 'nowrap' }}>{entry.timestamp.slice(0, 10)}</td>
                          <td style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }}>{entry.user_query}</td>
                          <td><strong style={{ fontFamily: 'monospace', fontSize: 12 }}>{entry.top_deterministic_result ?? entry.final_recommendation?.recommended_entity ?? '-'}</strong></td>
                          <td style={{ fontSize: 11, color: 'var(--muted)' }}>{entry.recommendation_status ?? '-'}</td>
                          <td style={{ fontSize: 12, color: entry.action_taken ? 'var(--success)' : 'var(--muted)', whiteSpace: 'nowrap' }}>{ACTION_LABELS[entry.action_taken] ?? entry.action_taken ?? '-'}</td>
                          <td style={{ fontSize: 11, color: 'var(--muted)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.outcome_notes ?? 'No review notes yet'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {selectedDecision && (
                  <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>Review selected decision</div>
                    <div style={{ marginBottom: 10 }}>
                      <strong>{selectedDecision.final_recommendation?.recommended_entity ?? selectedDecision.top_deterministic_result ?? 'No surfaced result'}</strong>
                      <div style={{ color: 'var(--muted)', fontSize: 12 }}>{selectedDecision.user_query}</div>
                      {selectedDecision.final_recommendation?.summary && <div style={{ marginTop: 6, fontSize: 13 }}>{selectedDecision.final_recommendation.summary}</div>}
                      {!selectedDecision.outcome_notes && <div style={{ marginTop: 6, fontSize: 12, color: 'var(--muted)' }}>No outcome data recorded yet.</div>}
                    </div>
                    <div className="form">
                      <div className="field"><label>Action taken</label><select value={reviewDraft.action_taken} onChange={(event) => setReviewDraft((prev) => ({ ...prev, action_taken: event.target.value }))}><option value="">Unset</option>{Object.entries(ACTION_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
                      <div className="field"><label>Review date</label><input type="date" value={reviewDraft.review_date} onChange={(event) => setReviewDraft((prev) => ({ ...prev, review_date: event.target.value }))} /></div>
                      <div className="field"><label>Outcome notes</label><textarea value={reviewDraft.outcome_notes} onChange={(event) => setReviewDraft((prev) => ({ ...prev, outcome_notes: event.target.value }))} placeholder="Write what actually happened. Leave blank if the review is still pending." /></div>
                      <button className="btn btn-primary" type="button" onClick={handleSaveReview} disabled={reviewSaving}>{reviewSaving ? 'Saving...' : 'Save review'}</button>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <span>Outcome Review</span>
          <button className="btn btn-primary" type="button" style={{ fontSize: 12 }} onClick={handleRunOutcomes} disabled={outcomesLoading}>
            {outcomesLoading ? 'Running...' : 'Run outcome review'}
          </button>
        </div>
        {outcomesError && <div className="alert alert-error" style={{ marginBottom: 12 }}>Outcome error: {outcomesError}</div>}
        {!outcomes ? (
          <div className="empty">Run a local outcome review to see what happened after saved decisions.</div>
        ) : (
          <>
            <div className="alert alert-info" style={{ marginBottom: 12 }}>
              Reviewed {outcomes.summary.total_decisions_reviewed} decision(s) for {outcomes.date_range.label}.
            </div>
            <div className="form" style={{ marginBottom: 12 }}>
              <div className="field"><label>Reviewed later</label><div>{outcomes.summary.reviewed_decisions}</div></div>
              <div className="field"><label>Accepted decisions</label><div>{outcomes.summary.accepted_decisions}</div></div>
              <div className="field"><label>Later findings</label><div>{outcomes.summary.decisions_with_later_findings}</div></div>
              <div className="field"><label>Watchlist later actionable</label><div>{outcomes.summary.watchlist_or_paper_only_later_actionable}</div></div>
            </div>
            {outcomes.entries.length === 0 ? (
              <div className="empty">No saved decisions were available for outcome review in this range.</div>
            ) : (
              <div className="table-wrap">
                <table className="table-compact">
                  <thead><tr><th>Decision</th><th>Entity</th><th>Days</th><th>Relevance</th><th>Consistency</th><th>Watchlist transition</th></tr></thead>
                  <tbody>
                    {outcomes.entries.slice(0, 8).map((entry) => (
                      <tr key={entry.decision_id}>
                        <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{entry.decision_timestamp.slice(0, 10)}</td>
                        <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{entry.entity ?? '-'}</td>
                        <td style={{ fontSize: 12 }}>{entry.days_elapsed}</td>
                        <td style={{ fontSize: 12 }}>{entry.current_relevance_status}</td>
                        <td style={{ fontSize: 12 }}>{entry.later_recommendation_consistency}</td>
                        <td style={{ fontSize: 12 }}>{entry.watchlist_transition_status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Section title="Missing-data warnings">
              <BulletList
                items={[
                  ...outcomes.warnings,
                  ...outcomes.entries.flatMap((entry) => entry.missing_data_notes).slice(0, 6),
                ]}
                keyFn={(item, index) => `${item}-${index}`}
              />
            </Section>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <span>Forward Validation Pilot</span>
          <button className="btn btn-primary" type="button" style={{ fontSize: 12 }} onClick={handleRunForwardPilot} disabled={forwardPilotLoading}>
            {forwardPilotLoading ? 'Running...' : 'Run pilot review'}
          </button>
        </div>
        {forwardPilotError && <div className="alert alert-error" style={{ marginBottom: 12 }}>Pilot review error: {forwardPilotError}</div>}
        {!forwardPilot ? (
          <div className="empty">Run the local pilot review to summarize weekly-style forward validation over saved decisions, monitoring, and paper outputs.</div>
        ) : (
          <>
            <div className="alert alert-info" style={{ marginBottom: 12 }}>
              Reviewed the pilot window {forwardPilot.pilot_window.label} with {forwardPilot.review_protocol.review_cadence} cadence.
            </div>
            <div className="form" style={{ marginBottom: 12 }}>
              <div className="field"><label>Total decisions</label><div>{forwardPilot.review_protocol.total_decisions_in_period}</div></div>
              <div className="field"><label>Accepted</label><div>{forwardPilot.review_protocol.accepted_count}</div></div>
              <div className="field"><label>Paper only</label><div>{forwardPilot.review_protocol.paper_only_count}</div></div>
              <div className="field"><label>Findings</label><div>{forwardPilot.review_protocol.findings_generated}</div></div>
            </div>
            <Section title="Weekly review summary">
              <BulletList
                items={[
                  forwardPilot.cohort_comparison_summary.accepted_vs_paper_only.interpretation,
                  forwardPilot.cohort_comparison_summary.hold_only_vs_exit_policy.interpretation,
                  forwardPilot.benchmark_summary.interpretation,
                ]}
                keyFn={(item) => item}
              />
            </Section>
            <Section title="Operational counts">
              <div className="form">
                <div className="field"><label>Still actionable</label><div>{forwardPilot.operational_summary.still_actionable_count}</div></div>
                <div className="field"><label>Deteriorated</label><div>{forwardPilot.operational_summary.deteriorated_count}</div></div>
                <div className="field"><label>Reviewed later</label><div>{forwardPilot.operational_summary.reviewed_decisions}</div></div>
                <div className="field"><label>Snapshots</label><div>{forwardPilot.operational_summary.snapshots_in_period}</div></div>
              </div>
            </Section>
            <Section title="Accepted vs paper only">
              <div>{forwardPilot.cohort_comparison_summary.accepted_vs_paper_only.interpretation}</div>
            </Section>
            <Section title="Hold-only vs exit policy">
              <div>{forwardPilot.cohort_comparison_summary.hold_only_vs_exit_policy.interpretation}</div>
            </Section>
            <Section title="Benchmark summary">
              <div>{forwardPilot.benchmark_summary.interpretation}</div>
            </Section>
            <Section title="Next review actions">
              <BulletList items={forwardPilot.next_review_actions} keyFn={(item) => item} />
            </Section>
            <Section title="Warnings">
              <BulletList
                items={[...forwardPilot.warnings, ...forwardPilot.missing_data_notes].slice(0, 10)}
                keyFn={(item, index) => `${item}-${index}`}
              />
            </Section>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <span>Paper Portfolio NAV</span>
          <button className="btn btn-primary" type="button" style={{ fontSize: 12 }} onClick={handleRunPaperPortfolioNav} disabled={paperPortfolioLoading}>
            {paperPortfolioLoading ? 'Running...' : 'Run with exit policy'}
          </button>
        </div>
        {paperPortfolioError && <div className="alert alert-error" style={{ marginBottom: 12 }}>Paper portfolio error: {paperPortfolioError}</div>}
        {!paperPortfolioNav ? (
          <div className="empty">Run the local paper portfolio with explicit exit rules to build a cautious NAV path, cash ledger, and benchmark comparison from saved decisions.</div>
        ) : (
          <>
            <div className="alert alert-info" style={{ marginBottom: 12 }}>
              Built {paperPortfolioNav.cohort_definition.label.toLowerCase()} for {paperPortfolioNav.date_range.label}.
            </div>
            <div className="form" style={{ marginBottom: 12 }}>
              <div className="field"><label>Initial capital</label><div>{paperPortfolioNav.initial_capital}</div></div>
              <div className="field"><label>Ending value</label><div>{paperPortfolioNav.ending_value}</div></div>
              <div className="field"><label>Cash remaining</label><div>{paperPortfolioNav.cash_remaining}</div></div>
              <div className="field"><label>Total simple return</label><div>{paperPortfolioNav.nav_summary.total_portfolio_simple_return_pct ?? 'Unavailable'}</div></div>
            </div>
            <div className="form" style={{ marginBottom: 12 }}>
              <div className="field"><label>Active positions</label><div>{paperPortfolioNav.active_positions_count}</div></div>
              <div className="field"><label>Exited positions</label><div>{paperPortfolioNav.exited_positions_count}</div></div>
              <div className="field"><label>Unsupported exits</label><div>{paperPortfolioNav.unsupported_exit_count}</div></div>
              <div className="field"><label>Exit-policy delta</label><div>{paperPortfolioNav.comparison_summary.exit_policy_ending_value_difference ?? 'Unavailable'}</div></div>
            </div>
            <Section title="Exit reasons">
              <CountList items={paperPortfolioNav.exit_reason_distribution} />
            </Section>
            <Section title="Benchmark comparison">
              <div>{paperPortfolioNav.comparison_summary.interpretation}</div>
            </Section>
            <Section title="NAV points">
              {paperPortfolioNav.nav_points.length === 0 ? (
                <div className="empty">No supported NAV points were available for this cohort and range.</div>
              ) : (
                <div className="table-wrap">
                  <table className="table-compact">
                    <thead><tr><th>Date</th><th>Portfolio value</th><th>Cash</th><th>Invested</th><th>Active positions</th></tr></thead>
                    <tbody>
                      {paperPortfolioNav.nav_points.slice(-8).map((point) => (
                        <tr key={point.date}>
                          <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{point.date}</td>
                          <td style={{ fontSize: 12 }}>{point.portfolio_value}</td>
                          <td style={{ fontSize: 12 }}>{point.cash}</td>
                          <td style={{ fontSize: 12 }}>{point.invested_value}</td>
                          <td style={{ fontSize: 12 }}>{point.active_position_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
            <Section title="Position summaries">
              {paperPortfolioNav.position_summaries.length === 0 ? (
                <div className="empty">No paper positions were available for this cohort.</div>
              ) : (
                <div className="table-wrap">
                  <table className="table-compact">
                    <thead><tr><th>Entity</th><th>Status</th><th>Exit policy</th><th>Exit time</th><th>Allocated capital</th><th>Current value</th><th>Simple return %</th></tr></thead>
                    <tbody>
                      {paperPortfolioNav.position_summaries.slice(0, 8).map((position) => (
                        <tr key={position.decision_id}>
                          <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{position.entity ?? '-'}</td>
                          <td style={{ fontSize: 12 }}>{position.lifecycle_status}</td>
                          <td style={{ fontSize: 12 }}>{position.exit_policy_status}</td>
                          <td style={{ fontSize: 12 }}>{position.assumed_exit_timestamp?.slice(0, 10) ?? '-'}</td>
                          <td style={{ fontSize: 12 }}>{position.allocated_capital}</td>
                          <td style={{ fontSize: 12 }}>{position.current_value ?? '-'}</td>
                          <td style={{ fontSize: 12 }}>{position.simple_return_pct ?? '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
            <Section title="Warnings">
              <BulletList
                items={[...paperPortfolioNav.warnings, ...paperPortfolioNav.missing_data_notes].slice(0, 8)}
                keyFn={(item, index) => `${item}-${index}`}
              />
            </Section>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <span>Shadow Portfolio</span>
          <button className="btn btn-primary" type="button" style={{ fontSize: 12 }} onClick={handleRunShadowPortfolio} disabled={shadowLoading}>
            {shadowLoading ? 'Running...' : 'Run shadow portfolio'}
          </button>
        </div>
        {shadowError && <div className="alert alert-error" style={{ marginBottom: 12 }}>Shadow portfolio error: {shadowError}</div>}
        {!shadowPortfolio ? (
          <div className="empty">Run the local shadow portfolio to review supported paper positions and simple equal-weight marks.</div>
        ) : (
          <>
            <div className="alert alert-info" style={{ marginBottom: 12 }}>
              Reviewed {shadowPortfolio.paper_summary.total_positions} paper position(s) for {shadowPortfolio.cohort_definition.label.toLowerCase()}.
            </div>
            <div className="form" style={{ marginBottom: 12 }}>
              <div className="field"><label>Supported</label><div>{shadowPortfolio.supported_positions}</div></div>
              <div className="field"><label>Unsupported</label><div>{shadowPortfolio.unsupported_positions}</div></div>
              <div className="field"><label>Average simple return</label><div>{shadowPortfolio.paper_summary.average_simple_return_pct ?? 'Unavailable'}</div></div>
              <div className="field"><label>Median simple return</label><div>{shadowPortfolio.paper_summary.median_simple_return_pct ?? 'Unavailable'}</div></div>
            </div>
            <Section title="Benchmark comparison">
              <div>{shadowPortfolio.comparison_summary.interpretation}</div>
            </Section>
            <Section title="Current paper positions">
              {shadowPortfolio.paper_positions.length === 0 ? (
                <div className="empty">No shadow positions were available for this cohort.</div>
              ) : (
                <div className="table-wrap">
                  <table className="table-compact">
                    <thead><tr><th>Decision</th><th>Entity</th><th>Supported</th><th>Entry</th><th>Latest mark</th><th>Simple return %</th></tr></thead>
                    <tbody>
                      {shadowPortfolio.paper_positions.slice(0, 8).map((position) => (
                        <tr key={position.decision_id}>
                          <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{position.decision_timestamp.slice(0, 10)}</td>
                          <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{position.entity ?? '-'}</td>
                          <td style={{ fontSize: 12 }}>{position.supported ? 'yes' : 'no'}</td>
                          <td style={{ fontSize: 12 }}>{position.assumed_entry_price ?? '-'}</td>
                          <td style={{ fontSize: 12 }}>{position.latest_mark_price ?? '-'}</td>
                          <td style={{ fontSize: 12 }}>{position.simple_return_pct ?? '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
            <Section title="Warnings">
              <BulletList
                items={[...shadowPortfolio.warnings, ...shadowPortfolio.missing_data_notes].slice(0, 8)}
                keyFn={(item, index) => `${item}-${index}`}
              />
            </Section>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <span>Comparative Validation</span>
          <button className="btn btn-primary" type="button" style={{ fontSize: 12 }} onClick={handleRunComparativeValidation} disabled={comparativeLoading}>
            {comparativeLoading ? 'Running...' : 'Run comparison'}
          </button>
        </div>
        {comparativeError && <div className="alert alert-error" style={{ marginBottom: 12 }}>Comparative validation error: {comparativeError}</div>}
        {!comparativeValidation ? (
          <div className="empty">Run comparative validation to compare accepted, rejected, watchlist, and other local decision cohorts.</div>
        ) : (
          <>
            <div className="alert alert-info" style={{ marginBottom: 12 }}>
              Compared {comparativeValidation.comparison_groups.length} cohort pair(s) for {comparativeValidation.date_range.label}.
            </div>
            <div className="form" style={{ marginBottom: 12 }}>
              <div className="field"><label>Cohorts tracked</label><div>{comparativeValidation.cohort_summaries.length}</div></div>
              <div className="field"><label>Consistency comparisons</label><div>{comparativeValidation.consistency_summary.filter((item) => item.supported).length}</div></div>
              <div className="field"><label>Deterioration comparisons</label><div>{comparativeValidation.deterioration_summary.filter((item) => item.supported).length}</div></div>
              <div className="field"><label>Watchlist transition comparisons</label><div>{comparativeValidation.watchlist_transition_summary.filter((item) => item.supported).length}</div></div>
            </div>
            <Section title="Cohort totals">
              <CountList items={comparativeValidation.cohort_summaries.map((item) => ({ item: item.label, count: item.total_decisions }))} />
            </Section>
            <Section title="Consistency comparison">
              <BulletList
                items={comparativeValidation.consistency_summary.slice(0, 4)}
                renderItem={(item) => `${item.left_cohort} vs ${item.right_cohort}: ${item.interpretation}`}
                keyFn={(item) => item.comparison_key}
              />
            </Section>
            <Section title="Deterioration comparison">
              <BulletList
                items={comparativeValidation.deterioration_summary.slice(0, 4)}
                renderItem={(item) => `${item.left_cohort} vs ${item.right_cohort}: ${item.interpretation}`}
                keyFn={(item) => item.comparison_key}
              />
            </Section>
            <Section title="Notable patterns">
              <BulletList items={comparativeValidation.notable_patterns} keyFn={(item) => item} />
            </Section>
            <Section title="Missing-data warnings">
              <BulletList
                items={[...comparativeValidation.warnings, ...comparativeValidation.missing_data_notes].slice(0, 8)}
                keyFn={(item, index) => `${item}-${index}`}
              />
            </Section>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <span>Operational Scorecard</span>
          <button className="btn btn-primary" type="button" style={{ fontSize: 12 }} onClick={handleRunScorecard} disabled={scorecardLoading}>
            {scorecardLoading ? 'Running...' : 'Run scorecard'}
          </button>
        </div>
        {scorecardError && <div className="alert alert-error" style={{ marginBottom: 12 }}>Scorecard error: {scorecardError}</div>}
        {!scorecard ? (
          <div className="empty">Run the local scorecard to summarize journal activity and monitoring patterns.</div>
        ) : (
          <>
            <div className="alert alert-info" style={{ marginBottom: 12 }}>
              {scorecard.journal_summary.total_journal_decisions} journal decision(s) and {scorecard.findings_summary.total_findings} finding(s) reviewed for {scorecard.date_range.label}.
            </div>
            <div className="form" style={{ marginBottom: 12 }}>
              <div className="field"><label>Eligible ideas acted on</label><div>{scorecard.recommendation_summary.eligible_ideas_acted_on}</div></div>
              <div className="field"><label>Snapshots in range</label><div>{scorecard.monitoring_summary.snapshots_in_range}</div></div>
              <div className="field"><label>Best-asset changes</label><div>{scorecard.monitoring_summary.best_eligible_asset_changes}</div></div>
              <div className="field"><label>Watchlist later actionable</label><div>{scorecard.monitoring_summary.watchlist_or_paper_only_later_actionable_count ?? 'Unavailable'}</div></div>
            </div>
            <Section title="Decisions by status"><CountList items={scorecard.recommendation_summary.decisions_by_recommendation_status} /></Section>
            <Section title="Actions taken"><CountList items={scorecard.action_summary.decisions_by_action_taken} /></Section>
            <Section title="Top rejection reasons"><CountList items={scorecard.constraint_summary.top_blocked_or_rejected_reasons} /></Section>
            <Section title="Findings by type"><CountList items={scorecard.findings_summary.findings_by_finding_type} /></Section>
            <Section title="Findings by severity"><CountList items={scorecard.findings_summary.findings_by_severity} /></Section>
            <Section title="Notable patterns"><BulletList items={scorecard.notable_patterns} keyFn={(item) => item} /></Section>
            {scorecard.warnings?.length > 0 && <div className="alert alert-info">{scorecard.warnings.slice(0, 4).map((warning) => <div key={warning}>{warning}</div>)}</div>}
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <span>Monitoring Findings</span>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn" type="button" style={{ fontSize: 12 }} onClick={loadFindings} disabled={findingsLoading || monitoringLoading}>
              {findingsLoading ? 'Loading...' : 'Refresh history'}
            </button>
            <button className="btn btn-primary" type="button" style={{ fontSize: 12 }} onClick={handleRunMonitoring} disabled={monitoringLoading}>
              {monitoringLoading ? 'Running...' : 'Run monitoring'}
            </button>
          </div>
        </div>
        {monitoringSummary && <div className="alert alert-info" style={{ marginBottom: 12 }}>{monitoringSummary}</div>}
        {monitoringError && <div className="alert alert-error" style={{ marginBottom: 12 }}>Monitoring error: {monitoringError}</div>}
        {findings.length === 0 ? (
          <div className="empty">No monitoring findings saved yet.</div>
        ) : (
          <div className="table-wrap">
            <table className="table-compact">
              <thead><tr><th>Time</th><th>Severity</th><th>Entity</th><th>Headline</th><th>Suggested next action</th></tr></thead>
              <tbody>
                {findings.map((finding) => (
                  <tr key={finding.finding_id}>
                    <td style={{ fontFamily: 'monospace', fontSize: 12, whiteSpace: 'nowrap' }}>{finding.timestamp.slice(0, 16).replace('T', ' ')}</td>
                    <td style={{ fontSize: 11, textTransform: 'uppercase', color: finding.severity === 'critical' ? 'var(--error)' : finding.severity === 'warning' ? 'var(--accent)' : 'var(--success)' }}>{finding.severity}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{finding.entity ?? '-'}</td>
                    <td style={{ fontSize: 12 }}>{finding.headline}</td>
                    <td style={{ fontSize: 12, color: 'var(--muted)' }}>{finding.suggested_next_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
