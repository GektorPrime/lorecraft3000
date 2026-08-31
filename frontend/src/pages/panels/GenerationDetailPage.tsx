import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getGeneration, reviewCandidate } from '../../api/client'
import type { Candidate, Generation } from '../../api/types'

export function GenerationDetailPage() {
  const { id } = useParams()
  const generationId = Number(id)

  const [generation, setGeneration] = useState<Generation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewCandidate, setPreviewCandidate] = useState<Candidate | null>(null)

  const reload = () =>
    getGeneration(generationId)
      .then(setGeneration)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generationId])

  useEffect(() => {
    if (!previewCandidate) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreviewCandidate(null)
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [previewCandidate])

  const handleReview = async (candidateId: number, verdict: 'accepted' | 'rejected') => {
    try {
      await reviewCandidate(candidateId, verdict)
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  if (error) return <p className="banner banner--error">{error}</p>
  if (!generation) return <p>Loading…</p>

  return (
    <section>
      <h1>Generation #{generation.id}</h1>
      <p>
        State: <strong>{generation.state}</strong> · Model: {generation.model} ({generation.image_size})
        · Cost: ${(generation.cost_usd_cents / 100).toFixed(2)}
      </p>
      {generation.error_text && <p className="banner banner--error">{generation.error_text}</p>}

      <h2>Prompt</h2>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{generation.prompt}</pre>

      <h2>Candidates</h2>
      {generation.candidates.length === 0 && <p>No candidates yet.</p>}
      <div className="card-grid">
        {generation.candidates.map((candidate) => (
          <div key={candidate.id} className="card">
            <button
              type="button"
              className="candidate-preview-trigger"
              aria-label={`Preview candidate ${candidate.idx}`}
              onClick={() => setPreviewCandidate(candidate)}
            >
              <img src={candidate.content_url} alt={`Candidate ${candidate.idx}`} />
            </button>
            <p>
              Review status: <strong>{candidate.review_status}</strong>
            </p>
            <div className="btn-row" style={{ marginTop: 0 }}>
              <button
                type="button"
                className="btn"
                onClick={() => void handleReview(candidate.id, 'accepted')}
              >
                Accept
              </button>
              <button
                type="button"
                className="btn btn--danger"
                onClick={() => void handleReview(candidate.id, 'rejected')}
              >
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>

      <Link to={`/panels/${generation.scene_id}/preview`} className="btn" style={{ marginTop: '1rem' }}>
        Back to panel
      </Link>

      {previewCandidate && (
        <div
          className="candidate-preview-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={`Candidate ${previewCandidate.idx}, larger preview`}
          onClick={() => setPreviewCandidate(null)}
        >
          <div className="candidate-preview" onClick={(event) => event.stopPropagation()}>
            <button
              type="button"
              className="candidate-preview__close"
              aria-label="Close preview"
              onClick={() => setPreviewCandidate(null)}
              autoFocus
            >
              &times;
            </button>
            <img
              className="candidate-preview__image"
              src={previewCandidate.content_url}
              alt={`Candidate ${previewCandidate.idx}, full-size preview`}
            />
          </div>
        </div>
      )}
    </section>
  )
}
