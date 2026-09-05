import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ApiError,
  duplicateBaseStage,
  generateBaseStage,
  getBaseStage,
  listBaseStageGenerations,
  listBaseStagePanels,
  previewBaseStage,
  publishBaseStage,
} from '../../api/client'
import type { BaseStage, BaseStagePreview, GenerationSummary, PanelSummary } from '../../api/types'
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
  const [usagePanels, setUsagePanels] = useState<PanelSummary[] | null>(null)
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
      const usageRequest = listBaseStagePanels(stageId).then(
        (panels) => {
          if (!mounted.current || version !== requestVersion.current) return
          setUsagePanels(panels)
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
      await publishBaseStage(stageId, candidateId)
      if (!mounted.current) return
      await reload()
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
    <section className="panel-preview" aria-busy={generating || duplicating || publishing || undefined}>
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

      <div className="panel-preview__workspace">
        <div className="panel-preview__content">
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
                <section className="panel-preview__base-stage">
                  <SectionHeader title="Current image" className="panel-preview__section-header" />
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
                <section className="panel-preview__base-stage">
                  <SectionHeader
                    title={usagePanels
                      ? `Used by ${usagePanels.length} panel${usagePanels.length === 1 ? '' : 's'}`
                      : 'Used by panels'}
                    className="panel-preview__section-header"
                  />
                  {usageError && (
                    <AsyncMessage kind="error" className="field__hint">
                      Could not load panels using this Base Stage: {usageError}
                    </AsyncMessage>
                  )}
                  {usagePanels && usagePanels.length === 0 && (
                    <p className="field__hint">No panels are currently anchored on this Base Stage.</p>
                  )}
                  {usagePanels && usagePanels.length > 0 && (
                    <ul className="base-stage-usage">
                      {usagePanels.map((panel) => (
                        <li key={panel.id}>
                          <Link to={`/panels/${panel.id}/preview`}>
                            Panel #{panel.id}
                          </Link>
                          <span className="field__hint">
                            {panel.beat_text} · {panel.generation_count} attempt
                            {panel.generation_count === 1 ? '' : 's'}
                            {panel.latest_attempt_preview_url && ' · has preview'}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}

              {stage.targets.length > 0 && (
                <section className="panel-preview__base-stage">
                  <SectionHeader title="Identity targets" className="panel-preview__section-header" />
                  <ol className="panel-preview__mapping">
                    {[...stage.targets].sort((a, b) => a.position - b.position).map((target) => (
                      <li key={target.id}>
                        <strong>{target.description}</strong>
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

              <p className="panel-preview__cost">
                Estimated cost: <strong>{formatCents(preview.estimated_cost_cents)}</strong>
              </p>
            </>
          )}

          {attemptsError && (
            <div>
              <AsyncMessage kind="error">Could not load generation history: {attemptsError}</AsyncMessage>
              <button type="button" className="btn" onClick={() => void reload()}>Retry generation history</button>
            </div>
          )}

          {attempts && attempts.length > 0 && (
            <>
              <SectionHeader title="Generation attempts" />
              <div className="attempt-list">
                {attempts.map((attempt) => (
                  <article className="attempt-row" key={attempt.id}>
                    <div className="attempt-row__summary">
                      <strong>Attempt #{attempt.id}</strong>
                      <span className="field__hint">
                        {attempt.model} · cost {formatCents(attempt.cost_usd_cents)} ·{' '}
                        <DateTime value={attempt.created_at} />
                      </span>
                      <div className="attempt-row__badges">
                        <span className={`badge badge--attempt-${attempt.state}`}>
                          {attempt.state.charAt(0).toUpperCase() + attempt.state.slice(1)}
                        </span>
                      </div>
                    </div>
                    {(attempt.candidates.length > 0 || attempt.error_text) && (
                      <div className="attempt-row__detail">
                        {attempt.candidates.length > 0 && (
                          <div className="attempt-row__preview">
                            <ImageDialog
                              src={attempt.candidates[0].content_url}
                              thumbnailAlt={`Preview from attempt ${attempt.id}`}
                              previewAlt={`Image from attempt ${attempt.id}, full size`}
                              triggerLabel={`Preview attempt ${attempt.id}`}
                              dialogLabel={`Attempt ${attempt.id} full preview`}
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
                ))}
              </div>
            </>
          )}
        </div>

        <aside className="panel-preview__sidebar" aria-label="Base stage actions">
          <div className="action-bar panel-preview__actions">
            {stage.is_editable && (
              <div className="action-bar__group action-bar__group--start">
                <button
                  type="button"
                  className="btn"
                  disabled={duplicating}
                  onClick={() => void handleDuplicate()}
                >
                  {duplicating ? 'Duplicating…' : 'Duplicate'}
                </button>
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
            <p className="field__hint" style={{ marginTop: '0.5rem' }}>
              This base stage is published and can be used by panels.
              Duplicate to create a new editable variant.
            </p>
          )}
        </aside>
      </div>
    </section>
  )
}
