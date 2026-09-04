import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ApiError,
  deletePanel,
  duplicatePanel,
  editCandidate,
  generatePanel,
  getPanel,
  listPanelGenerations,
  previewPanel,
  reviewCandidate,
  updatePanelModel,
} from '../../api/client'
import type { GenerationSummary, Panel, PanelPreview } from '../../api/types'
import { useBudget } from '../../api/useBudget'
import { useOptions } from '../../api/useOptions'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'
import { DateTime } from '../../components/DateTime'
import { CopyButton } from '../../components/CopyButton'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Icon } from '../../components/Icon'
import { ImageDialog } from '../../components/ImageDialog'
import { EmptyState } from '../../components/EmptyState'
import { Notice } from '../../components/Notice'
import { PageHeader } from '../../components/PageHeader'
import { SectionHeader } from '../../components/SectionHeader'
import { CandidateCarousel } from './CandidateCarousel'

const REVIEW_STATUS_LABEL: Record<string, string> = {
  pending: 'Waiting',
  accepted: 'Accepted',
  rejected: 'Rejected',
}

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
  const options = useOptions()

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
  const [changingModel, setChangingModel] = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [reviewingCandidateId, setReviewingCandidateId] = useState<number | null>(null)
  const [editingCandidateId, setEditingCandidateId] = useState<number | null>(null)
  const [editInstruction, setEditInstruction] = useState('')
  const [submittingEdit, setSubmittingEdit] = useState(false)
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
    if (generating || changingModel) return
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

  const handleModelChange = async (model: string) => {
    if (!panel || changingModel || hasPendingAttempt || model === panel.model) return
    setChangingModel(true)
    setActionMessage(null)
    // Prevent an older page load from restoring the model and preview that
    // were current before this mutation.
    requestVersion.current += 1
    try {
      const nextPanel = await updatePanelModel(panel.id, model)
      if (!mounted.current) return
      setPanel(nextPanel)
      setPreview(null)
      await reloadInFlight.current
      await reload()
    } catch (err) {
      if (!mounted.current) return
      setActionMessage(
        `Could not change model: ${err instanceof ApiError ? err.message : String(err)}`,
      )
      await reloadInFlight.current
      await reload()
    } finally {
      if (mounted.current) setChangingModel(false)
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

  const handleDelete = async () => {
    setConfirmingDelete(false)
    if (deleting) return
    setDeleting(true)
    setActionMessage(null)
    try {
      await deletePanel(panelId)
      if (!mounted.current) return
      navigate('/panels')
    } catch (err) {
      if (!mounted.current) return
      setActionMessage(`Could not delete panel: ${err instanceof ApiError ? err.message : String(err)}`)
      setDeleting(false)
    }
  }

  const handleEditSubmit = async (candidateId: number) => {
    if (submittingEdit || hasPendingAttempt) return
    const instruction = editInstruction.trim()
    if (!instruction) return
    setSubmittingEdit(true)
    setActionMessage(null)
    try {
      await editCandidate(candidateId, instruction)
      await refreshBudget()
      if (!mounted.current) return
      // The edited result appears as a new attempt in the history below.
      setEditingCandidateId(null)
      setEditInstruction('')
      await reload()
    } catch (err) {
      if (!mounted.current) return
      const message = err instanceof ApiError ? err.message : String(err)
      setActionMessage(`Could not edit image. ${friendlyGenerationError(message)}`)
      await reload()
    } finally {
      if (mounted.current) setSubmittingEdit(false)
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
    <section
      className="panel-preview"
      aria-busy={generating || changingModel || duplicating || deleting || undefined}
    >
      <PageHeader
        title="Preview panel"
        actions={(
          <Link to="/panels" className="btn btn--primary">
            Back to panels
          </Link>
        )}
      />
      {attempts && attempts.length > 0 && (
        <CandidateCarousel
          attempts={attempts}
          cast={panel.cast}
        />
      )}
      <p className="panel-preview__beat">{panel.beat_text}</p>
      {panelError && <AsyncMessage kind="error">Could not refresh panel: {panelError}</AsyncMessage>}
      {actionMessage && <AsyncMessage kind="error">{actionMessage}</AsyncMessage>}
      {completionMessage && <AsyncMessage kind={completionMessage.kind}>{completionMessage.text}</AsyncMessage>}
      {hasPendingAttempt && (
        <AsyncMessage kind="loading">
          A generation is in progress. This page refreshes automatically; do not start another
          paid request.
        </AsyncMessage>
      )}

      <div className="panel-preview__workspace">
        <div className="panel-preview__content">
      {!preview && previewError && (
        <div>
          <AsyncMessage kind="error">Could not load generation preview: {previewError}</AsyncMessage>
          <button type="button" className="btn" onClick={() => void reload()}>Retry preview</button>
        </div>
      )}
      {!preview && !previewError && <AsyncMessage kind="loading">Loading generation preview…</AsyncMessage>}
      {preview?.can_generate ? (
        <>
          <SectionHeader title="Reference-slot allocation" className="panel-preview__section-header" />
          <ul>
            {preview.attachments.map((a) => (
              <li key={a.image_number}>
                Image {a.image_number}: {a.character_name} (ref-set v{a.ref_set_version}, role {a.role})
              </li>
            ))}
          </ul>
          <Notice tone="privacy" className="privacy-note">
            <p>
              These reference images are uploaded to{' '}
              {panel.model.startsWith('gpt-') ? "OpenAI's API" : "Google's Gemini API"},
              together with the prompt below, to generate this panel. They leave
              your computer.
            </p>
          </Notice>

          {preview.warnings.length > 0 && (
            <Notice tone="warning">
              {preview.warnings.map((w) => (
                <p key={w}>{w}</p>
              ))}
            </Notice>
          )}

          <SectionHeader
            title="Exact prompt sent to Gemini"
            actions={<CopyButton value={preview.prompt} label="Copy prompt" />}
          />
          <pre className="prompt-preview">{preview.prompt}</pre>

          <p className="panel-preview__cost">
            Estimated cost: <strong>{formatCents(preview.estimated_cost_cents)}</strong> · Spent or
            reserved today: {formatCents(preview.spent_today_cents)} · Remaining after:{' '}
            {formatCents(preview.remaining_after_cents)}
          </p>
        </>
      ) : preview ? (
        <AsyncMessage kind="error">Generation blocked: {preview.blocked_reason}</AsyncMessage>
      ) : null}

        </div>
        <aside className="panel-preview__sidebar" aria-label="Panel actions">
      <div className="action-bar panel-preview__actions">
        <div className="field panel-preview__model">
          <label htmlFor="preview-model">Generation model</label>
          <select
            id="preview-model"
            value={panel.model}
            disabled={attempts === null || changingModel || generating || hasPendingAttempt}
            aria-describedby="preview-model-hint"
            onChange={(event) => void handleModelChange(event.target.value)}
          >
            {options.models.map((model) => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
          <span className="field__hint" id="preview-model-hint">
            {hasPendingAttempt
              ? 'Locked while a generation is in progress.'
              : 'Applies to future generations and refreshes the prompt and cost.'}
          </span>
        </div>
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
          <button
            type="button"
            className="btn btn--danger"
            disabled={deleting}
            onClick={() => setConfirmingDelete(true)}
          >
            <Icon name="trash" size={15} />
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
        {preview?.can_generate && (
          <div className="action-bar__group action-bar__group--end">
            <button
              type="button"
              className="btn btn--primary"
              disabled={generating || changingModel || hasPendingAttempt}
              onClick={() => void handleGenerate()}
            >
              {generating
                ? 'Starting generation…'
                : changingModel
                ? 'Updating model…'
                : hasPendingAttempt
                ? 'Generation in progress'
                : `Generate one candidate · ${formatCents(preview.estimated_cost_cents)}`}
            </button>
          </div>
        )}
      </div>
        </aside>
      </div>

      <SectionHeader title="Generation attempts" className="panel-preview__attempts-heading" />
      {attemptsError && (
        <div>
          <AsyncMessage kind="error">Could not load generation history: {attemptsError}</AsyncMessage>
          <button type="button" className="btn" onClick={() => void reload()}>Retry generation history</button>
        </div>
      )}
      {!attempts && !attemptsError && <AsyncMessage kind="loading">Loading generation history…</AsyncMessage>}
      {attempts?.length === 0 ? (
        <EmptyState
          icon="sparkles"
          title="No generation attempts yet."
          description="Generate a candidate when the panel preview is ready."
          compact
        />
      ) : attempts ? (
        <div className="attempt-list">
            {attempts.map((attempt) => (
              <article className="attempt-row" key={attempt.id}>
                <div className="attempt-row__summary">
                  <strong>Attempt #{attempt.id}</strong>
                  <span className="field__hint">
                    {attempt.model} · accounted cost {formatCents(attempt.cost_usd_cents)} ·{' '}
                    <DateTime value={attempt.created_at} />
                  </span>
                  <div className="attempt-row__badges">
                    <span className={`badge badge--attempt-${attempt.state}`}>
                      {attempt.state.charAt(0).toUpperCase() + attempt.state.slice(1)}
                    </span>
                    {attempt.candidates[0] && (
                      <span className={`badge badge--attempt-${attempt.candidates[0].review_status}`}>
                        {REVIEW_STATUS_LABEL[attempt.candidates[0].review_status]
                          ?? attempt.candidates[0].review_status}
                      </span>
                    )}
                  </div>
                </div>
                {(attempt.candidates.length > 0 || attempt.error_text) && (
                  <div className="attempt-row__detail">
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
                  </div>
                )}
                {preview?.can_generate &&
                    attempt.state === 'failed' &&
                    attempt.id === attempts[0].id && (
                  <div className="attempt-row__actions">
                    <button
                      type="button"
                      className="btn btn--primary"
                      disabled={generating || changingModel || hasPendingAttempt}
                      onClick={() => void handleGenerate()}
                      title="Generates from the panel's current settings"
                    >
                      Try again
                    </button>
                  </div>
                )}
                {attempt.state === 'succeeded' && attempt.candidates.length > 0 && (
                  <div className="attempt-row__actions attempt-row__candidate-actions">
                    <button
                      type="button"
                      className="btn btn--primary"
                      disabled={reviewingCandidateId !== null}
                      onClick={() => void handleReview(attempt.candidates[0]!.id, 'accepted')}
                    >
                      <Icon name="check" size={16} />
                      Accept
                    </button>
                    <button
                      type="button"
                      className="btn btn--danger"
                      disabled={reviewingCandidateId !== null}
                      onClick={() => void handleReview(attempt.candidates[0]!.id, 'rejected')}
                    >
                      Reject
                    </button>
                    {editingCandidateId !== attempt.candidates[0].id && (
                      <button
                        type="button"
                        className="btn"
                        disabled={hasPendingAttempt || submittingEdit}
                        onClick={() => {
                          setEditingCandidateId(attempt.candidates[0]!.id)
                          setEditInstruction('')
                          setActionMessage(null)
                        }}
                        title="Refine this image with an instruction"
                      >
                        Edit this image
                      </button>
                    )}
                    {reviewingCandidateId === attempt.candidates[0].id && (
                      <span className="field__hint">Reviewing image…</span>
                    )}
                  </div>
                )}
                {attempt.state === 'succeeded' &&
                  attempt.candidates.length > 0 &&
                  editingCandidateId === attempt.candidates[0].id && (
                  <div className="attempt-row__edit">
                      <form
                        className="attempt-edit-form"
                        onSubmit={(event) => {
                          event.preventDefault()
                          void handleEditSubmit(attempt.candidates[0]!.id)
                        }}
                      >
                        <label htmlFor={`edit-${attempt.id}`}>
                          Describe the change to make to this image
                        </label>
                        <textarea
                          id={`edit-${attempt.id}`}
                          value={editInstruction}
                          rows={2}
                          disabled={submittingEdit}
                          placeholder="e.g. make it night time; move the lantern to the left"
                          onChange={(event) => setEditInstruction(event.target.value)}
                        />
                        <div className="attempt-edit-form__actions">
                          <button
                            type="submit"
                            className="btn btn--primary"
                            disabled={
                              submittingEdit ||
                              hasPendingAttempt ||
                              editInstruction.trim().length === 0
                            }
                          >
                            {submittingEdit ? 'Editing…' : 'Submit edit'}
                          </button>
                          <button
                            type="button"
                            className="btn"
                            disabled={submittingEdit}
                            onClick={() => {
                              setEditingCandidateId(null)
                              setEditInstruction('')
                            }}
                          >
                            Cancel
                          </button>
                        </div>
                        <span className="field__hint">
                          Runs on the same model ({attempt.model}) and keeps each
                          character anchored to their canonical references. Creates a
                          new attempt and costs another generation.
                        </span>
                      </form>
                  </div>
                )}
              </article>
            ))}
          </div>
      ) : null}

      <ConfirmDialog
        open={confirmingDelete}
        title="Delete this panel?"
        description="This permanently deletes the panel and its entire generation history. This cannot be undone."
        confirmLabel="Delete panel"
        onConfirm={() => void handleDelete()}
        onCancel={() => setConfirmingDelete(false)}
      />
    </section>
  )
}
