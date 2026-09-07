import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ApiError,
  duplicateBaseStage,
  generateBaseStage,
  getBaseStage,
  listBaseStageGenerations,
  listBaseStageScenes,
  previewBaseStage,
  publishBaseStage,
} from '../../api/client'
import type { BaseStage, BaseStagePreview, GenerationSummary, SceneSummary } from '../../api/types'
import { useBudget } from '../../api/useBudget'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'
import { DateTime } from '../../components/DateTime'
import { CopyButton } from '../../components/CopyButton'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ImageDialog } from '../../components/ImageDialog'
import { Notice } from '../../components/Notice'
import { PageHeader } from '../../components/PageHeader'
import { SectionHeader } from '../../components/SectionHeader'

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`
}

function friendlyGenerationError(error: string): string {
  const normalized = error.toLowerCase()
  if (normalized.includes('high demand') && normalized.includes('try again later')) {
    return 'Gemini Pro is temporarily busy. No image was generated. Try again in a few minutes.'
  }
  if (normalized.includes('assembled prompt changed after preview')) {
    return 'The generation inputs changed. Review the updated prompt before trying again.'
  }
  return 'Generation failed before an image was produced. Open the technical details for the provider response.'
}

export function BaseStagePreviewPage() {
  return (
    <RouteIdGuard>{(stageId) => <BaseStagePreview key={stageId} stageId={stageId} />}</RouteIdGuard>
  )
}

function BaseStagePreview({ stageId }: { stageId: number }) {
  const navigate = useNavigate()
  const { refreshBudget } = useBudget()

  const [stage, setStage] = useState<BaseStage | null>(null)
  const [preview, setPreview] = useState<BaseStagePreview | null>(null)
  const [attempts, setAttempts] = useState<GenerationSummary[] | null>(null)
  const [usageScenes, setUsageScenes] = useState<SceneSummary[] | null>(null)
  const [usageError, setUsageError] = useState<string | null>(null)
  const [stageError, setStageError] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [attemptsError, setAttemptsError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [completionMessage, setCompletionMessage] = useState<{
    kind: 'success' | 'error'
    text: string
  } | null>(null)
  const [generating, setGenerating] = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [previewSlot, setPreviewSlot] = useState<number | null>(null)
  const requestVersion = useRef(0)
  const hasLoadedStage = useRef(false)
  const attemptsRef = useRef<GenerationSummary[] | null>(null)
  const reloadInFlight = useRef<Promise<void> | null>(null)
  const mounted = useRef(true)

  usePageTitle(stage ? `Base stage #${stage.id} preview` : 'Loading Base Stage Preview')

  const reload = useCallback(async () => {
    if (reloadInFlight.current) return reloadInFlight.current

    let release!: () => void
    const inFlight = new Promise<void>((resolve) => { release = resolve })
    reloadInFlight.current = inFlight

    try {
      const version = ++requestVersion.current
      const stageRequest = getBaseStage(stageId).then(
        (next) => {
          if (!mounted.current || version !== requestVersion.current) return
          setStage(next)
          hasLoadedStage.current = true
          setStageError(null)
        },
        (err: unknown) => {
          if (!mounted.current || version !== requestVersion.current) return
          if (err instanceof ApiError && err.status === 404 && !hasLoadedStage.current) setNotFound(true)
          setStageError(err instanceof ApiError ? err.message : String(err))
        },
      )
      const previewRequest = previewBaseStage(stageId).then(
        (next) => {
          if (!mounted.current || version !== requestVersion.current) return
          setPreview(next)
          setPreviewError(null)
        },
        (err: unknown) => {
          if (!mounted.current || version !== requestVersion.current) return
          setPreviewError(err instanceof ApiError ? err.message : String(err))
        },
      )
      const attemptsRequest = listBaseStageGenerations(stageId).then(
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
      const usageRequest = listBaseStageScenes(stageId).then(
        (scenes) => {
          if (!mounted.current || version !== requestVersion.current) return
          setUsageScenes(scenes)
          setUsageError(null)
        },
        (err: unknown) => {
          if (!mounted.current || version !== requestVersion.current) return
          setUsageError(err instanceof ApiError ? err.message : String(err))
        },
      )
      await Promise.all([stageRequest, previewRequest, attemptsRequest, usageRequest])
      if (mounted.current && version === requestVersion.current) await refreshBudget()
    } finally {
      if (reloadInFlight.current === inFlight) reloadInFlight.current = null
      release()
    }
  }, [stageId, refreshBudget])

  useEffect(() => {
    mounted.current = true
    void reload()
    return () => { mounted.current = false }
  }, [reload])

  const hasPendingAttempt = attempts?.some((a) => a.state === 'pending') ?? false

  useEffect(() => {
    if (!hasPendingAttempt) return
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      await reload()
      if (!cancelled) timer = window.setTimeout(() => void poll(), 2000)
    }
    timer = window.setTimeout(() => void poll(), 2000)
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer) }
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
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer) }
  }, [generating, refreshBudget])

  const handleGenerate = async () => {
    if (generating) return
    setGenerating(true)
    setActionMessage(null)
    try {
      if (!preview) return
      await generateBaseStage(stageId, preview.prompt_hash)
      await refreshBudget()
      if (!mounted.current) return
      await reload()
    } catch (err) {
      if (!mounted.current) return
      setActionMessage(`Could not start generation. ${friendlyGenerationError(err instanceof ApiError ? err.message : String(err))}`)
      await reload()
    } finally {
      if (mounted.current) setGenerating(false)
    }
  }

  const handlePublish = async (candidateId: number) => {
    if (publishing) return
    setPublishing(true)
    setActionMessage(null)
    try {
      const publishedStage = await publishBaseStage(stageId, candidateId)
      if (!mounted.current) return
      await reload()
      if (mounted.current) setStage(publishedStage)
    } catch (err) {
      if (!mounted.current) return
      setActionMessage(`Could not publish: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setPublishing(false)
    }
  }

  const handleDuplicate = async () => {
    if (duplicating) return
    setDuplicating(true)
    setActionMessage(null)
    try {
      const copy = await duplicateBaseStage(stageId)
      if (!mounted.current) return
      navigate(`/base-stages/${copy.id}/preview`)
    } catch (err) {
      if (!mounted.current) return
      setActionMessage(`Could not duplicate: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setDuplicating(false)
    }
  }

  if (notFound) return <NotFoundPage />
  if (!stage) {
    return stageError ? (
      <div>
        <AsyncMessage kind="error">Could not load base stage: {stageError}</AsyncMessage>
        <button type="button" className="btn" onClick={() => { setStageError(null); void reload() }}>Retry</button>
      </div>
    ) : <AsyncMessage kind="loading">Loading base stage…</AsyncMessage>
  }

  return (
    <section className="scene-preview" aria-busy={generating || duplicating || publishing || undefined}>
      <PageHeader
        title={stage.state === 'ready' ? `Base stage #${stage.id} — Ready` : `Base stage #${stage.id} — Draft`}
        actions={<Link to="/base-stages" className="btn btn--primary">Back to base stages</Link>}
      />
      {stageError && <AsyncMessage kind="error">Could not refresh base stage: {stageError}</AsyncMessage>}
      {actionMessage && <AsyncMessage kind="error">{actionMessage}</AsyncMessage>}
      {completionMessage && <AsyncMessage kind={completionMessage.kind}>{completionMessage.text}</AsyncMessage>}
      {hasPendingAttempt && (
        <AsyncMessage kind="loading">
          A generation is in progress. This page refreshes automatically; do not start another paid request.
        </AsyncMessage>
      )}

      <div className="scene-preview__workspace">
        <div className="scene-preview__content">
          {!preview && previewError && (
            <div>
              <AsyncMessage kind="error">Could not load generation preview: {previewError}</AsyncMessage>
              <button type="button" className="btn" onClick={() => void reload()}>Retry preview</button>
            </div>
          )}
          {!preview && !previewError && <AsyncMessage kind="loading">Loading generation preview…</AsyncMessage>}
          {preview && (
            <>
              {stage.content_url && (
                <section className="scene-preview__base-stage">
                  <SectionHeader title="Current image" className="scene-preview__section-header" />
                  <ImageDialog
                    src={stage.content_url}
                    thumbnailAlt={`Base stage #${stage.id}`}
                    previewAlt={`Base stage #${stage.id}, full-size`}
                    triggerLabel="Preview base stage image"
                    dialogLabel={`Base stage #${stage.id} full preview`}
                  />
                </section>
              )}

              {stage.state === 'ready' && (
                <section className="scene-preview__base-stage">
                  <SectionHeader
                    title={usageScenes
                      ? `Used by ${usageScenes.length} scene${usageScenes.length === 1 ? '' : 's'}`
                      : 'Used by scenes'}
                    className="scene-preview__section-header"
                  />
                  {usageError && (
                    <AsyncMessage kind="error" className="field__hint">
                      Could not load scenes using this Base Stage: {usageError}
                    </AsyncMessage>
                  )}
                  {usageScenes && usageScenes.length === 0 && (
                    <p className="field__hint">No scenes are currently anchored on this Base Stage.</p>
                  )}
                  {usageScenes && usageScenes.length > 0 && (
                    <ul className="base-stage-usage">
                      {usageScenes.map((scene) => (
                        <li key={scene.id}>
                          <Link to={`/scenes/${scene.id}/preview`}>
                            Scene #{scene.id}
                          </Link>
                          <span className="field__hint">
                            {scene.beat_text} · {scene.generation_count} attempt
                            {scene.generation_count === 1 ? '' : 's'}
                            {scene.latest_attempt_preview_url && ' · has preview'}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}

              {stage.targets.length > 0 && (
                <section className="scene-preview__base-stage">
                  <SectionHeader
                    title="Identity targets"
                    description="Ordered figure placeholders that can be mapped to characters when staging a scene."
                    className="scene-preview__section-header"
                  />
                  <ol className="base-stage-target-list" aria-label="Identity targets">
                    {[...stage.targets].sort((a, b) => a.position - b.position).map((target, index) => (
                      <li key={target.id}>
                        <span className="base-stage-target-list__number" aria-hidden="true">{index + 1}</span>
                        <div>
                          <span className="base-stage-target-list__label">Target {index + 1}</span>
                          <p>{target.description}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              <Notice tone="privacy" className="privacy-note">
                <p>
                  The composition prompt (without character references) is sent to{' '}
                  {preview.model.startsWith('gpt-') ? "OpenAI's API" : "Google's Gemini API"}{' '}
                  to generate this base stage. No character identities are included at this stage.
                </p>
              </Notice>

              {preview.warnings?.length > 0 && (
                <Notice tone="warning">
                  {preview.warnings.map((w) => <p key={w}>{w}</p>)}
                </Notice>
              )}

              <SectionHeader
                title="Exact generation prompt"
                actions={<CopyButton value={preview.prompt} label="Copy prompt" />}
              />
              <pre className="prompt-preview">{preview.prompt}</pre>

              <p className="scene-preview__cost">
                Estimated cost: <strong>{formatCents(preview.estimated_cost_cents)}</strong>
              </p>
</>
          )}

        </div>

        <aside className="scene-preview__sidebar" aria-label="Base stage actions">
          <div className="card action-bar scene-preview__actions">
            {(stage.is_editable || stage.origin === 'generated') && (
              <div className="action-bar__group action-bar__group--start">
                {stage.is_editable ? (
                  <Link to={`/base-stages/${stage.id}/edit`} className="btn">Edit composition</Link>
                ) : (
                  <button
                    type="button"
                    className="btn"
                    disabled={duplicating}
                    onClick={() => void handleDuplicate()}
                  >
                    {duplicating ? 'Duplicating…' : 'Duplicate'}
                  </button>
                )}
              </div>
            )}
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
                    : `Generate candidate · ${formatCents(preview.estimated_cost_cents)}`}
                </button>
              </div>
            )}
          </div>
          {stage.state === 'ready' && (
            <p className="field__hint scene-preview__aside-hint">
              This base stage is published and can be used by scenes.
              Duplicate to create a new editable variant.
            </p>
          )}
        </aside>
      </div>

      {attemptsError && (
        <div>
          <AsyncMessage kind="error">Could not load generation history: {attemptsError}</AsyncMessage>
          <button type="button" className="btn" onClick={() => void reload()}>Retry generation history</button>
        </div>
      )}

      {attempts && attempts.length > 0 && (
        <>
          <SectionHeader title="Generation attempts" className="scene-preview__attempts-heading" />
          {(() => {
            const slots = attempts
              .filter((attempt) => attempt.state === 'succeeded' && attempt.candidates.length > 0)
              .map((attempt) => ({ attempt, candidate: attempt.candidates[0] }))
            const previewSlotIndex = previewSlot !== null ? previewSlot % slots.length : null
            const previewItem = previewSlotIndex !== null ? slots[previewSlotIndex] : null
            return (
              <div className="attempt-list">
                {attempts.map((attempt) => {
                  const slotIndex = slots.findIndex((slot) => slot.attempt.id === attempt.id)
                  return (
                    <article className="card attempt-row" key={attempt.id}>
                      <div className="attempt-row__summary">
                        <strong>Attempt #{attempt.id}</strong>
                        <span className="field__hint">
                          <span>{attempt.model}</span>
                          <span>accounted cost {formatCents(attempt.cost_usd_cents)}</span>
                          <span>
                            <DateTime value={attempt.created_at} />
                          </span>
                        </span>
                        <div className="attempt-row__badges">
                          <span className={`badge badge--attempt-${attempt.state}`}>
                            {attempt.state.charAt(0).toUpperCase() + attempt.state.slice(1)}
                          </span>
                          {attempt.candidates.length > 0 && (
                            <span
                              className={`badge badge--attempt-${stage.selected_candidate_id === attempt.candidates[0].id ? 'accepted' : 'pending'}`}
                            >
                              {stage.selected_candidate_id === attempt.candidates[0].id
                                ? 'Selected'
                                : 'Waiting'}
                            </span>
                          )}
                        </div>
                      </div>
                      {(attempt.candidates.length > 0 || attempt.error_text) && (
                        <div className="attempt-row__detail">
                          {attempt.candidates.length > 0 && slotIndex >= 0 && (
                            <div className="attempt-row__preview">
                              <ImageDialog
                                src={attempt.candidates[0].content_url}
                                previewSrc={previewItem?.candidate.content_url ?? attempt.candidates[0].content_url}
                                thumbnailAlt={`Preview from attempt ${attempt.id}`}
                                previewAlt={`Image from attempt ${previewItem?.attempt.id ?? attempt.id}, full size`}
                                triggerLabel={`Preview attempt ${attempt.id}`}
                                dialogLabel={`Attempt ${previewItem?.attempt.id ?? attempt.id} full preview`}
                                onPrevious={() => setPreviewSlot((current) => ((current ?? slotIndex) - 1 + slots.length) % slots.length)}
                                onNext={() => setPreviewSlot((current) => ((current ?? slotIndex) + 1) % slots.length)}
                                onOpenChange={(open) => setPreviewSlot(open ? slotIndex : null)}
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
                      {attempt.state === 'succeeded' && attempt.candidates.length > 0 && !stage.selected_candidate_id && (
                        <div className="attempt-row__actions">
                          <button
                            type="button"
                            className="btn btn--primary"
                            disabled={publishing || hasPendingAttempt}
                            onClick={() => void handlePublish(attempt.candidates[0].id)}
                          >
                            {publishing ? 'Publishing…' : 'Publish as base stage image'}
                          </button>
                        </div>
                      )}
                      {attempt.state === 'failed' && (
                        <div className="attempt-row__actions">
                          <button
                            type="button"
                            className="btn btn--primary"
                            disabled={generating || hasPendingAttempt}
                            onClick={() => void handleGenerate()}
                          >
                            Try again
                          </button>
                        </div>
                      )}
                    </article>
                  )
                })}
              </div>
            )
          })()}
        </>
      )}
    </section>
  )
}
