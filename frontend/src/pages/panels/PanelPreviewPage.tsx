import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ApiError,
  duplicatePanel,
  generatePanel,
  getPanel,
  listPanelGenerations,
  previewPanel,
  reviewCandidate,
} from '../../api/client'
import type { GenerationSummary, Panel, PanelPreview } from '../../api/types'
import { useBudget } from '../../api/useBudget'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'
import { DateTime } from '../../components/DateTime'
import { CopyButton } from '../../components/CopyButton'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ImageDialog } from '../../components/ImageDialog'
import { CandidateCarousel } from './CandidateCarousel'

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
  if (normalized.includes('assembled prompt changed after preview')) {
    return 'The generation inputs changed. Review the updated prompt before trying again.'
  }
  return 'Generation failed before an image was produced. Open the technical details for the provider response.'
}

export function PanelPreviewPage() {
  return (
    <RouteIdGuard>{(panelId) => <PanelPreview key={panelId} panelId={panelId} />}</RouteIdGuard>
  )
}

function PanelPreview({ panelId }: { panelId: number }) {
  const navigate = useNavigate()
  const { refreshBudget } = useBudget()

  const [panel, setPanel] = useState<Panel | null>(null)
  const [preview, setPreview] = useState<PanelPreview | null>(null)
  const [attempts, setAttempts] = useState<GenerationSummary[] | null>(null)
  const [panelError, setPanelError] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [attemptsError, setAttemptsError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [completionMessage, setCompletionMessage] = useState<{
    kind: 'success' | 'error'
    text: string
  } | null>(null)
  const [generating, setGenerating] = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  const [reviewingCandidateId, setReviewingCandidateId] = useState<number | null>(null)
  const [notFound, setNotFound] = useState(false)
  const requestVersion = useRef(0)
  const hasLoadedPanel = useRef(false)
  const attemptsRef = useRef<GenerationSummary[] | null>(null)
  const reloadInFlight = useRef<Promise<void> | null>(null)
  const mounted = useRef(true)

  usePageTitle(panel ? `Panel #${panel.id} Preview` : 'Loading Panel Preview')

  const reload = useCallback(async () => {
    if (reloadInFlight.current) return reloadInFlight.current

    let release!: () => void
    const inFlight = new Promise<void>((resolve) => {
      release = resolve
    })
    reloadInFlight.current = inFlight

    try {
      const version = ++requestVersion.current
      const panelRequest = getPanel(panelId).then(
        (nextPanel) => {
          if (!mounted.current || version !== requestVersion.current) return
          setPanel(nextPanel)
          hasLoadedPanel.current = true
          setPanelError(null)
        },
        (err: unknown) => {
          if (!mounted.current || version !== requestVersion.current) return
          if (err instanceof ApiError && err.status === 404 && !hasLoadedPanel.current) {
            setNotFound(true)
          }
          setPanelError(err instanceof ApiError ? err.message : String(err))
        },
      )
      const previewRequest = previewPanel(panelId).then(
        (nextPreview) => {
          if (!mounted.current || version !== requestVersion.current) return
          setPreview(nextPreview)
          setPreviewError(null)
        },
        (err: unknown) => {
          if (!mounted.current || version !== requestVersion.current) return
          setPreviewError(err instanceof ApiError ? err.message : String(err))
        },
      )
      const attemptsRequest = listPanelGenerations(panelId).then(
        (history) => {
          if (!mounted.current || version !== requestVersion.current) return
          const completed = attemptsRef.current?.find((previous) =>
            previous.state === 'pending' && history.some(
              (next) => next.id === previous.id && next.state !== 'pending',
            ),
          )
          const nextCompleted = completed && history.find((next) => next.id === completed.id)
          if (nextCompleted) {
            setCompletionMessage({
              kind: nextCompleted.state === 'failed' ? 'error' : 'success',
              text: `Generation attempt #${nextCompleted.id} ${nextCompleted.state}.`,
            })
          }
          attemptsRef.current = history
          setAttempts(history)
          setAttemptsError(null)
        },
        (err: unknown) => {
          if (!mounted.current || version !== requestVersion.current) return
          setAttemptsError(err instanceof ApiError ? err.message : String(err))
        },
      )

      await Promise.all([panelRequest, previewRequest, attemptsRequest])
      if (mounted.current && version === requestVersion.current) await refreshBudget()
    } finally {
      if (reloadInFlight.current === inFlight) reloadInFlight.current = null
      release()
    }
  }, [panelId, refreshBudget])

  useEffect(() => {
    mounted.current = true
    // reload updates state only after its resource promises settle.
    // oxlint-disable-next-line react/set-state-in-effect
    void reload()
    return () => {
      mounted.current = false
    }
  }, [reload])

  const hasPendingAttempt = attempts?.some((attempt) => attempt.state === 'pending') ?? false

  useEffect(() => {
    if (!hasPendingAttempt) return
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      await reload()
      if (!cancelled) timer = window.setTimeout(() => void poll(), 2000)
    }
    timer = window.setTimeout(() => void poll(), 2000)
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [hasPendingAttempt, reload])

  useEffect(() => {
    if (!generating) return
    let cancelled = false
    let timer: number | undefined
    const pollBudget = async () => {
      await refreshBudget()
      if (!cancelled) timer = window.setTimeout(() => void pollBudget(), 2000)
    }
    timer = window.setTimeout(() => void pollBudget(), 2000)
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [generating, refreshBudget])

  const handleGenerate = async () => {
    if (generating) return
    setGenerating(true)
    setActionMessage(null)
    try {
      if (!preview) return
      await generatePanel(panelId, preview.prompt_hash)
      await refreshBudget()
      if (!mounted.current) return
      // Stay on this page so the new attempt and its candidates appear in place;
      // the details page has been removed.
      await reload()
    } catch (err) {
      if (!mounted.current) return
      const message = err instanceof ApiError ? err.message : String(err)
      setActionMessage(`Could not start generation. ${friendlyGenerationError(message)}`)
      await reload()
    } finally {
      if (mounted.current) setGenerating(false)
    }
  }

  // Pending or successful generations lock a panel. Failed attempts remain
  // editable because their exact request is preserved on the attempt itself.
  // A locked panel can be duplicated into a fresh editable copy.
  const handleDuplicateAndEdit = async () => {
    if (duplicating) return
    setDuplicating(true)
    setActionMessage(null)
    try {
      const copy = await duplicatePanel(panelId)
      if (!mounted.current) return
      navigate(`/panels/${copy.id}/edit`)
    } catch (err) {
      if (!mounted.current) return
      setActionMessage(`Could not duplicate panel: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setDuplicating(false)
    }
  }

  const handleReview = async (candidateId: number, verdict: 'accepted' | 'rejected') => {
    if (reviewingCandidateId !== null) return
    setReviewingCandidateId(candidateId)
    setActionMessage(null)
    try {
      await reviewCandidate(candidateId, verdict)
      if (!mounted.current) return
      // The outcome is visible in place — the carousel badge flips to
      // Accepted/Rejected after refresh — so no top-of-page banner is needed.
      await reload()
    } catch (err) {
      if (!mounted.current) return
      setActionMessage(
        `Could not ${verdict === 'accepted' ? 'accept' : 'reject'} image: ${err instanceof ApiError ? err.message : String(err)}`,
      )
    } finally {
      if (mounted.current) setReviewingCandidateId(null)
    }
  }

  if (notFound) return <NotFoundPage />
  if (!panel) {
    return panelError ? (
      <div>
        <AsyncMessage kind="error">Could not load panel: {panelError}</AsyncMessage>
        <button
          type="button"
          className="btn"
          onClick={() => {
            setPanelError(null)
            void reload()
          }}
        >
          Retry
        </button>
      </div>
    ) : <AsyncMessage kind="loading">Loading panel…</AsyncMessage>
  }

  return (
    <section aria-busy={generating || duplicating || undefined}>
      <h1>Preview panel</h1>
      {attempts && attempts.length > 0 && (
        <CandidateCarousel
          attempts={attempts}
          reviewingCandidateId={reviewingCandidateId}
          onReview={handleReview}
        />
      )}
      <p>{panel.beat_text}</p>
      {panelError && <AsyncMessage kind="error">Could not refresh panel: {panelError}</AsyncMessage>}
      {actionMessage && <AsyncMessage kind="error">{actionMessage}</AsyncMessage>}
      {completionMessage && <AsyncMessage kind={completionMessage.kind}>{completionMessage.text}</AsyncMessage>}
      {hasPendingAttempt && (
        <AsyncMessage kind="loading">
          A generation is in progress. This page refreshes automatically; do not start another
          paid request.
        </AsyncMessage>
      )}

      {!preview && previewError && (
        <div>
          <AsyncMessage kind="error">Could not load generation preview: {previewError}</AsyncMessage>
          <button type="button" className="btn" onClick={() => void reload()}>Retry preview</button>
        </div>
      )}
      {!preview && !previewError && <AsyncMessage kind="loading">Loading generation preview…</AsyncMessage>}
      {preview?.can_generate ? (
        <>
          <h2>Reference-slot allocation</h2>
          <ul>
            {preview.attachments.map((a) => (
              <li key={a.image_number}>
                Image {a.image_number}: {a.character_name} (ref-set v{a.ref_set_version}, role {a.role})
              </li>
            ))}
          </ul>
          <p className="privacy-note">
            These reference images are uploaded to Google's Gemini API, together
            with the prompt below, to generate this panel. They leave your
            computer.
          </p>

          {preview.warnings.length > 0 && (
            <div className="banner banner--info">
              {preview.warnings.map((w) => (
                <p key={w} style={{ margin: 0 }}>
                  {w}
                </p>
              ))}
            </div>
          )}

          <div className="section-heading">
            <h2 style={{ margin: 0 }}>Exact prompt sent to Gemini</h2>
            <CopyButton value={preview.prompt} label="Copy prompt" />
          </div>
          <pre className="prompt-preview">{preview.prompt}</pre>

          <p>
            Estimated cost: <strong>{formatCents(preview.estimated_cost_cents)}</strong> · Spent or
            reserved today: {formatCents(preview.spent_today_cents)} · Remaining after:{' '}
            {formatCents(preview.remaining_after_cents)}
          </p>
        </>
      ) : preview ? (
        <AsyncMessage kind="error">Generation blocked: {preview.blocked_reason}</AsyncMessage>
      ) : null}

      <div className="action-bar">
        <div className="action-bar__group action-bar__group--start">
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
              {duplicating ? 'Duplicating…' : 'Duplicate & edit'}
            </button>
          )}
          <Link to="/panels" className="btn">
            Back to panels
          </Link>
        </div>
        {preview?.can_generate && (
          <div className="action-bar__group action-bar__group--end">
            <button
              type="button"
              className="btn btn--primary"
              disabled={generating || hasPendingAttempt}
              onClick={() => void handleGenerate()}
            >
              {generating
                ? 'Starting generation…'
                : hasPendingAttempt
                ? 'Generation in progress'
                : `Generate one candidate · ${formatCents(preview.estimated_cost_cents)}`}
            </button>
          </div>
        )}
      </div>

      <h2 style={{ marginTop: '1.5rem' }}>Generation attempts</h2>
      {attemptsError && (
        <div>
          <AsyncMessage kind="error">Could not load generation history: {attemptsError}</AsyncMessage>
          <button type="button" className="btn" onClick={() => void reload()}>Retry generation history</button>
        </div>
      )}
      {!attempts && !attemptsError && <AsyncMessage kind="loading">Loading generation history…</AsyncMessage>}
      {attempts?.length === 0 ? (
        <p className="field__hint">No generation attempts yet.</p>
      ) : attempts ? (
        <div className="attempt-list">
            {attempts.map((attempt) => (
              <article className="attempt-row" key={attempt.id}>
                <div className="attempt-row__summary">
                  <span className={`badge badge--attempt-${attempt.state}`}>{attempt.state}</span>
                  <strong>Attempt #{attempt.id}</strong>
                  <span className="field__hint">
                    {attempt.model} · accounted cost {formatCents(attempt.cost_usd_cents)} ·{' '}
                    <DateTime value={attempt.created_at} />
                  </span>
                </div>
                {attempt.candidates.length > 0 && (
                  <div className="attempt-row__preview">
                    <ImageDialog
                      src={attempt.candidates[0].content_url}
                      thumbnailAlt={`Preview from attempt ${attempt.id}`}
                      previewAlt={`Generated image from attempt ${attempt.id}, full-size preview`}
                      triggerLabel={`Preview image from attempt ${attempt.id}`}
                      dialogLabel={`Generated image from attempt ${attempt.id}, larger preview`}
                    />
                  </div>
                )}
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
                  {preview?.can_generate &&
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
                </div>
              </article>
            ))}
          </div>
      ) : null}
    </section>
  )
}
