import { FormEvent, useEffect, useState } from 'react'

type HealthStatus = {
  status: string
  model: string
  debug: boolean
}

type SourceDocument = {
  content: string
  source: string
  relevance: number
}

type ChatResponse = {
  response: string
  sources: SourceDocument[]
  confidence: number
  conversation_id: string
}

const apiBaseUrl = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

export default function App() {
  const [message, setMessage] = useState('What can this assistant do?')
  const [isSending, setIsSending] = useState(false)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [chatResult, setChatResult] = useState<ChatResponse | null>(null)
  const [chatError, setChatError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true

    async function loadHealth() {
      try {
        const response = await fetch(`${apiBaseUrl}/health`)

        if (!response.ok) {
          throw new Error(`Health check failed with status ${response.status}`)
        }

        const payload = (await response.json()) as HealthStatus
        if (isMounted) {
          setHealth(payload)
          setHealthError(null)
        }
      } catch (error) {
        if (isMounted) {
          setHealthError(
            error instanceof Error ? error.message : 'Unable to reach backend health endpoint.',
          )
        }
      }
    }

    void loadHealth()

    return () => {
      isMounted = false
    }
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSending(true)
    setChatError(null)

    try {
      const response = await fetch(`${apiBaseUrl}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message,
          conversation_id: chatResult?.conversation_id,
        }),
      })

      if (!response.ok) {
        throw new Error(`Chat request failed with status ${response.status}`)
      }

      const payload = (await response.json()) as ChatResponse
      setChatResult(payload)
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'Chat request failed.')
    } finally {
      setIsSending(false)
    }
  }

  return (
    <main className="app-shell">
      <section className="hero-card">
        <p className="eyebrow">RAG Chatbot Assistant</p>
        <h1>Starter workspace for a FastAPI + React retrieval assistant.</h1>
        <p className="lede">
          The backend is currently a stub, but the health check and chat contract are wired so the
          project can boot cleanly while you build the retrieval pipeline.
        </p>
        <div className="status-row">
          <article className="status-card">
            <span>Backend status</span>
            <strong>{health?.status ?? 'Unavailable'}</strong>
            <small>{healthError ?? 'Health endpoint responded successfully.'}</small>
          </article>
          <article className="status-card">
            <span>Model</span>
            <strong>{health?.model ?? 'Not reported'}</strong>
            <small>{health ? `Debug mode: ${health.debug}` : 'Start the API to populate this.'}</small>
          </article>
        </div>
      </section>

      <section className="workspace-card">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Chat Probe</p>
            <h2>Send a request to the backend stub</h2>
          </div>
        </div>

        <form className="chat-form" onSubmit={handleSubmit}>
          <label htmlFor="message">Prompt</label>
          <textarea
            id="message"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={5}
            placeholder="Ask a question to test the API contract."
          />
          <button type="submit" disabled={isSending || !message.trim()}>
            {isSending ? 'Sending...' : 'Send message'}
          </button>
        </form>

        <div className="response-panel">
          <div className="response-header">
            <h3>Latest response</h3>
            {chatResult ? <span>Confidence {chatResult.confidence.toFixed(2)}</span> : null}
          </div>

          {chatError ? <p className="error-text">{chatError}</p> : null}

          {chatResult ? (
            <>
              <p className="response-copy">{chatResult.response}</p>
              <p className="conversation-tag">Conversation ID: {chatResult.conversation_id}</p>
              <div className="sources-list">
                {chatResult.sources.length > 0 ? (
                  chatResult.sources.map((source, index) => (
                    <article className="source-card" key={`${source.source}-${index}`}>
                      <strong>{source.source}</strong>
                      <span>Relevance {source.relevance.toFixed(2)}</span>
                      <p>{source.content}</p>
                    </article>
                  ))
                ) : (
                  <p className="muted-text">No source documents are returned yet.</p>
                )}
              </div>
            </>
          ) : (
            <p className="muted-text">Send a message to confirm the API response shape.</p>
          )}
        </div>
      </section>
    </main>
  )
}
