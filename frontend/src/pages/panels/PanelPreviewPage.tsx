import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ApiError,
  duplicatePanel,
  generatePanel,
  getPanel,
  listPanelGenerations,
  previewPanel,
} from '../../api/client'
import type { GenerationSummary, Panel, PanelPreview } from '../../api/types'

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`
}

function friendlyGenerationError(error: string): string {
  const normalized = error.toLowerCase()
  if (normalized.includes('high demand') && normalized.includes('try again later')) {
    return 'Gemini Pro is temporarily busy. No image was generated. Try again in a few minutes.'
  }
  if (normalized.includes('media resolution is not supported')) {
    return 'Gemini rejected an unsupported reference setting. The application has been corrected; try again.'
  }
  return 'Generation failed before an image was produced. Open the technical details for the provider response.'
}

export function PanelPreviewPage() {
  const { id } = useParams()
  const panelId = Number(id)
  const navigate = useNavigate()

  const [panel, setPanel] = useState<Panel | null>(null)
  const [preview, setPreview] = useState<PanelPreview | null>(null)
  const [attempts, setAttempts] = useState<GenerationSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [duplicating, setDuplicating] = useState(false)

  const reload = async () => {
    try {
      const [nextPanel, nextPreview, history] = await Promise.all([
        getPanel(panelId),
        previewPanel(panelId),
        listPanelGenerations(panelId),
      ])
      setPanel(nextPanel)
      setPreview(nextPreview)
      setAttempts(history)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  useEffect(() => {
    void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panelId])

  const hasPendingAttempt = attempts?.some((attempt) => attempt.state === 'pending') ?? false

  useEffect(() => {
    if (!hasPendingAttempt) return
    const timer = window.setInterval(() => void reload(), 2000)
    return () => window.clearInterval(timer)
    // reload intentionally follows the current panel id without becoming a
    // public callback dependency; the interval is rebuilt when pending ends.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasPendingAttempt, panelId])

  const handleGenerate = async () => {
    setGenerating(true)
    setError(null)
    try {
      const generation = await generatePanel(panelId)
      navigate(`/generations/${generation.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
      await reload()
    } finally {
      setGenerating(false)
    }
  }

  // Pending or successful generations lock a panel. Failed attempts remain
  // editable because their exact request is preserved on the attempt itself.
  // A locked panel can be duplicated into a fresh editable copy.
  const handleDuplicateAndEdit = async () => {
    setDuplicating(true)
    setError(null)
    try {
      const copy = await duplicatePanel(panelId)
      navigate(`/panels/${copy.id}/edit`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setDuplicating(false)
    }
  }

  if (!panel || !preview || !attempts) {
    return error ? <p className="banner banner--error">{error}</p> : <p>Loading…</p>
  }

  return (
    <section>
      <h1>Preview panel</h1>
      <p>{panel.beat_text}</p>
      {error && <p className="banner banner--error">{friendlyGenerationError(error)}</p>}

      {preview.can_generate ? (
        <>
          <h2>Reference-slot allocation</h2>
          <ul>
            {preview.attachments.map((a) => (
              <li key={a.image_number}>
                Image {a.image_number}: {a.character_name} (ref-set v{a.ref_set_version}, role {a.role})
              </li>
            ))}
          </ul>

          {preview.warnings.length > 0 && (
            <div className="banner banner--info">
              {preview.warnings.map((w) => (
                <p key={w} style={{ margin: 0 }}>
                  {w}
                </p>
              ))}
            </div>
          )}

          <p>
            Estimated cost: <strong>{formatCents(preview.estimated_cost_cents)}</strong> · Spent or
            reserved today: {formatCents(preview.spent_today_cents)} · Remaining after:{' '}
            {formatCents(preview.remaining_after_cents)}
          </p>

          {hasPendingAttempt && (
            <p className="banner banner--info">
              A generation is in progress. This page refreshes automatically; do not start another
              paid request.
            </p>
          )}

          <button
            type="button"
            className="btn btn--primary"
            disabled={generating || hasPendingAttempt}
            onClick={() => void handleGenerate()}
          >
            {hasPendingAttempt
              ? 'Generation in progress'
              : `Generate one candidate · ${formatCents(preview.estimated_cost_cents)}`}
          </button>
        </>
      ) : (
        <p className="banner banner--error">Generation blocked: {preview.blocked_reason}</p>
      )}

      <div className="btn-row">
        {panel.is_editable ? (
          <Link to={`/panels/${panel.id}/edit`} className="btn">
            Edit panel
          </Link>
        ) : (
          <button
            type="button"
            className="btn"
            disabled={duplicating}
            onClick={() => void handleDuplicateAndEdit()}
          >
            Duplicate &amp; edit
          </button>
        )}
        <Link to="/panels" className="btn">
          Back to panels
        </Link>
      </div>

      <h2>Generation attempts</h2>
      {attempts.length === 0 ? (
        <p className="field__hint">No generation attempts yet.</p>
      ) : (
        <div className="attempt-list">
          {attempts.map((attempt) => (
            <article className="attempt-row" key={attempt.id}>
              <div className="attempt-row__summary">
                <span className={`badge badge--attempt-${attempt.state}`}>{attempt.state}</span>
                <strong>Attempt #{attempt.id}</strong>
                <span className="field__hint">
                  {attempt.model} · accounted cost {formatCents(attempt.cost_usd_cents)} ·{' '}
                  {attempt.created_at}
                </span>
              </div>
              {attempt.error_text && (
                <div className="attempt-error">
                  <p>{friendlyGenerationError(attempt.error_text)}</p>
                  <details>
                    <summary>Technical details</summary>
                    <pre>{attempt.error_text}</pre>
                  </details>
                </div>
              )}
              <div className="btn-row attempt-row__actions">
                {preview.can_generate &&
                  attempt.state === 'failed' &&
                  attempt.id === attempts[0].id && (
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={generating || hasPendingAttempt}
                    onClick={() => void handleGenerate()}
                    title="Generates from the panel's current settings"
                  >
                    Try again
                  </button>
                  )}
                <Link to={`/generations/${attempt.id}`} className="btn">
                  View details
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
