import { useState } from 'react'
import { runCopilotChat } from '../api.js'

export default function CopilotChat() {
  const [query, setQuery] = useState('Show me a market snapshot for SPY, QQQ, TLT, GLD')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [sessionState, setSessionState] = useState(null)
  const [messages, setMessages] = useState([])

  const submit = async (event) => {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed || loading) return

    setLoading(true)
    setError(null)
    setMessages((prev) => [...prev, { role: 'user', query: trimmed }])

    try {
      const response = await runCopilotChat({
        user_query: trimmed,
        session_state: sessionState,
      })
      setSessionState(response.session_state)
      setMessages((prev) => [...prev, { role: 'assistant', response }])
      setQuery('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <h2 className="section-title">Investment Copilot</h2>

      <div className="card">
        <div className="card-title">Copilot Chat</div>
        <form className="form" onSubmit={submit}>
          <div className="field">
            <label>Ask a question</label>
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ask for a market snapshot, ranking, strategy evaluation, or explain the last result."
              disabled={loading}
            />
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-primary" type="submit" disabled={loading || !query.trim()}>
              {loading ? <span className="spinner" /> : null}
              Send
            </button>
          </div>
        </form>
        {error && <div className="alert alert-error" style={{ marginTop: 12 }}>{error}</div>}
      </div>

      {messages.length === 0 && !loading && !error && (
        <div className="empty" style={{ paddingTop: 24 }}>
          Try: "Rank SPY, QQQ, TLT, GLD" or "Run a cross-preset strategy evaluation for SPY, QQQ, IWM, TLT, GLD".
        </div>
      )}

      {messages.map((message, index) => (
        <div className="card" key={`${message.role}-${index}`}>
          <div className="card-title">{message.role === 'user' ? 'You' : 'Assistant'}</div>
          {message.role === 'user' ? (
            <div>{message.query}</div>
          ) : (
            <>
              <div style={{ marginBottom: 12 }}>
                <strong>{message.response.answer.headline}</strong>
              </div>
              <div style={{ marginBottom: 12, color: 'var(--text)' }}>
                {message.response.answer.summary}
              </div>
              {message.response.answer.bullets?.length > 0 && (
                <ul style={{ paddingLeft: 18, marginBottom: 12 }}>
                  {message.response.answer.bullets.map((bullet) => (
                    <li key={bullet}>{bullet}</li>
                  ))}
                </ul>
              )}
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
                Intent: <strong style={{ color: 'var(--text)' }}>{message.response.detected_intent}</strong>
                {' '}| Tools used: <strong style={{ color: 'var(--text)' }}>{message.response.tools_used.join(', ') || 'none'}</strong>
                {message.response.recommendation_status ? (
                  <>
                    {' '}| Recommendation status:{' '}
                    <strong style={{ color: 'var(--text)' }}>{message.response.recommendation_status}</strong>
                  </>
                ) : null}
              </div>
              {message.response.answer.deterministic_evidence_summary && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 4 }}>
                    Deterministic evidence
                  </div>
                  <div>{message.response.answer.deterministic_evidence_summary}</div>
                </div>
              )}
              {message.response.answer.profile_decision_summary && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 4 }}>
                    Profile decision
                  </div>
                  <div>{message.response.answer.profile_decision_summary}</div>
                </div>
              )}
              {message.response.answer.final_recommendation_summary && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 4 }}>
                    Final recommendation
                  </div>
                  <div>{message.response.answer.final_recommendation_summary}</div>
                </div>
              )}
              {message.response.answer.why_this_is_or_is_not_actionable && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 4 }}>
                    Actionability
                  </div>
                  <div>{message.response.answer.why_this_is_or_is_not_actionable}</div>
                </div>
              )}
              {message.response.warnings?.length > 0 && (
                <div className="alert alert-info" style={{ marginTop: 0, marginBottom: 12 }}>
                  {message.response.warnings.slice(0, 3).map((warning) => (
                    <div key={warning}>{warning}</div>
                  ))}
                </div>
              )}
              {message.response.profile_constraints_applied?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                    Profile constraints applied
                  </div>
                  <ul style={{ paddingLeft: 18, marginBottom: 0 }}>
                    {message.response.profile_constraints_applied.map((item, itemIndex) => (
                      <li key={`${item.constraint}-${itemIndex}`}>
                        <strong>{item.category}</strong>: {item.detail}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {message.response.eligible_alternatives?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                    Eligible alternatives
                  </div>
                  <ul style={{ paddingLeft: 18, marginBottom: 0 }}>
                    {message.response.eligible_alternatives.map((alternative) => (
                      <li key={`${alternative.entity}-${alternative.recommendation_status}`}>
                        <strong>{alternative.entity}</strong> ({alternative.recommendation_status}) - {alternative.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {message.response.knowledge_sources_used?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                    Knowledge sources used
                  </div>
                  <ul style={{ paddingLeft: 18, marginBottom: 0 }}>
                    {message.response.knowledge_sources_used.map((source) => (
                      <li key={`${source.source}-${source.title}`}>
                        <strong>{source.title}</strong> ({source.doc_type || 'note'}, {source.confidence_tier}) - {source.source}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {message.response.answer.confidence_notes?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                    Confidence notes
                  </div>
                  <ul style={{ paddingLeft: 18 }}>
                    {message.response.answer.confidence_notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </div>
              )}
              {message.response.next_actions?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                    Next actions
                  </div>
                  <ul style={{ paddingLeft: 18 }}>
                    {message.response.next_actions.map((action) => (
                      <li key={action}>{action}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="json-block">{JSON.stringify(message.response.supporting_data, null, 2)}</div>
            </>
          )}
        </div>
      ))}
    </>
  )
}
