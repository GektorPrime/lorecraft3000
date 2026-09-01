import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getGeneration, reviewCandidate } from '../../api/client'
import type { Generation } from '../../api/types'
import { ImageDialog } from '../../components/ImageDialog'
import { AsyncMessage } from '../../components/AsyncMessage'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'

export function GenerationDetailPage() {
  return (
    <RouteIdGuard>
      {(generationId) => <GenerationDetail key={generationId} generationId={generationId} />}
    </RouteIdGuard>
  )
}

function GenerationDetail({ generationId }: { generationId: number }) {
  const [generation, setGeneration] = useState<Generation | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<{
    kind: 'success' | 'error'
    text: string
  } | null>(null)
  const [reviewingCandidateId, setReviewingCandidateId] = useState<number | null>(null)
  const [notFound, setNotFound] = useState(false)
  const requestVersion = useRef(0)
  const hasLoaded = useRef(false)
  const mounted = useRef(true)

  usePageTitle(generation ? `Generation #${generation.id}` : 'Loading Generation')

  const reload = useCallback(async () => {
    const version = ++requestVersion.current
    try {
      const nextGeneration = await getGeneration(generationId)
      if (!mounted.current || version !== requestVersion.current) return null
      setGeneration(nextGeneration)
      hasLoaded.current = true
      setLoadError(null)
      return null
    } catch (err) {
      if (!mounted.current || version !== requestVersion.current) return null
      if (err instanceof ApiError && err.status === 404 && !hasLoaded.current) setNotFound(true)
      const message = err instanceof ApiError ? err.message : String(err)
      setLoadError(message)
      return message
    }
  }, [generationId])

  useEffect(() => {
    mounted.current = true
    // oxlint-disable-next-line react/set-state-in-effect
    void reload()
    return () => {
      mounted.current = false
      requestVersion.current += 1
    }
  }, [reload])

  const handleReview = async (candidateId: number, verdict: 'accepted' | 'rejected') => {
    if (reviewingCandidateId !== null) return
    setReviewingCandidateId(candidateId)
    setActionMessage(null)
    try {
      await reviewCandidate(candidateId, verdict)
      if (!mounted.current) return
      const refreshError = await reload()
      if (!mounted.current) return
      if (refreshError) setLoadError(null)
      const pastTense = verdict === 'accepted' ? 'accepted' : 'rejected'
      setActionMessage(
        refreshError
          ? { kind: 'error', text: `Candidate ${pastTense}, but generation details could not be refreshed: ${refreshError}` }
          : { kind: 'success', text: `Candidate ${pastTense}.` },
      )
    } catch (err) {
      if (!mounted.current) return
      setActionMessage({
        kind: 'error',
        text: `Could not ${verdict === 'accepted' ? 'accept' : 'reject'} candidate: ${err instanceof ApiError ? err.message : String(err)}`,
      })
    } finally {
      if (mounted.current) setReviewingCandidateId(null)
    }
  }

  if (notFound) return <NotFoundPage />
  if (loadError && !generation) {
    return (
      <div>
        <AsyncMessage kind="error">Could not load generation: {loadError}</AsyncMessage>
        <button type="button" className="btn" onClick={() => void reload()}>Retry</button>
      </div>
    )
  }
  if (!generation) return <AsyncMessage kind="loading">Loading generation…</AsyncMessage>

  return (
    <section aria-busy={reviewingCandidateId !== null || undefined}>
      <h1>Generation #{generation.id}</h1>
      <p>
        State: <strong>{generation.state}</strong> · Model: {generation.model} ({generation.image_size})
        · Cost: ${(generation.cost_usd_cents / 100).toFixed(2)}
      </p>
      {generation.error_text && <AsyncMessage kind="error">{generation.error_text}</AsyncMessage>}
      {loadError && <AsyncMessage kind="error">Could not refresh generation: {loadError}</AsyncMessage>}
      {actionMessage && <AsyncMessage kind={actionMessage.kind}>{actionMessage.text}</AsyncMessage>}

      <h2>Prompt</h2>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{generation.prompt}</pre>

      <h2>Candidates</h2>
      {generation.candidates.length === 0 && <p>No candidates yet.</p>}
      <div className="card-grid">
        {generation.candidates.map((candidate) => (
          <div key={candidate.id} className="card">
            <ImageDialog
              src={candidate.content_url}
              thumbnailAlt={`Candidate ${candidate.idx}`}
              previewAlt={`Candidate ${candidate.idx}, full-size preview`}
              triggerLabel={`Preview candidate ${candidate.idx}`}
              dialogLabel={`Candidate ${candidate.idx}, larger preview`}
            />
            <p>
              Review status: <strong>{candidate.review_status}</strong>
            </p>
            <div className="btn-row" style={{ marginTop: 0 }}>
              <button
                type="button"
                className="btn"
                disabled={reviewingCandidateId !== null}
                onClick={() => void handleReview(candidate.id, 'accepted')}
              >
                Accept
              </button>
              <button
                type="button"
                className="btn btn--danger"
                disabled={reviewingCandidateId !== null}
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
    </section>
  )
}
