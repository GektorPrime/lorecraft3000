import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, createGeneratedBaseStage, getBaseStage, listStyles, updateBaseStage } from '../../api/client'
import type { BaseStageGeneratedInput, Style } from '../../api/types'
import { useOptions } from '../../api/useOptions'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'

export function BaseStageNewPage() {
  const { id } = useParams()
  if (id === undefined) return <BaseStageForm key="new" stageId={null} />
  return (
    <RouteIdGuard>{(stageId) => <BaseStageForm key={stageId} stageId={stageId} />}</RouteIdGuard>
  )
}

function BaseStageForm({ stageId }: { stageId: number | null }) {
  const navigate = useNavigate()
  const options = useOptions()
  const [styles, setStyles] = useState<Style[] | null>(null)
  const [description, setDescription] = useState('')
  const [beatText, setBeatText] = useState('')
  const [camera, setCamera] = useState('')
  const [framing, setFraming] = useState('')
  const [mood, setMood] = useState('')
  const [aspectRatio, setAspectRatio] = useState(() =>
    options.aspect_ratios.includes('16:9') ? '16:9' : options.aspect_ratios[0] ?? '',
  )
  const [styleId, setStyleId] = useState<number | null>(null)
  const [model, setModel] = useState(options.default_model)
  const [imageSize, setImageSize] = useState(options.default_image_size)
  const [targets, setTargets] = useState<string[]>([])
  const [validationError, setValidationError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loaded, setLoaded] = useState(stageId === null)
  const [locked, setLocked] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [baseline, setBaseline] = useState<string | null>(null)
  const currentSnapshot = JSON.stringify({
    description, beatText, camera, framing, mood, aspectRatio, styleId, model, imageSize, targets,
  })
  const { allowNavigation, confirmationProps } = useUnsavedChanges(
    stageId === null
      ? description !== '' || beatText !== '' || targets.length > 0
      : baseline !== null && currentSnapshot !== baseline,
  )

  usePageTitle(stageId === null ? 'New Generated Base Stage' : `Edit Base Stage #${stageId}`)

  useEffect(() => {
    listStyles().then((s) => {
      setStyles(s)
      if (stageId === null && s.length > 0) setStyleId(s[0].id)
    }).catch(() => {})
  }, [stageId])

  useEffect(() => {
    if (stageId === null) return
    let active = true
    getBaseStage(stageId)
      .then((stage) => {
        if (!active) return
        if (!stage.is_editable) {
          setLocked(true)
          setLoaded(true)
          return
        }
        const hydrated = {
          description: stage.description,
          beatText: stage.beat_text ?? '',
          camera: stage.camera ?? '',
          framing: stage.framing ?? '',
          mood: stage.mood ?? '',
          aspectRatio: stage.aspect_ratio,
          styleId: stage.style_id,
          model: stage.model ?? options.default_model,
          imageSize: stage.image_size ?? options.default_image_size,
          targets: [...stage.targets]
            .sort((a, b) => a.position - b.position)
            .map((target) => target.description),
        }
        setDescription(hydrated.description)
        setBeatText(hydrated.beatText)
        setCamera(hydrated.camera)
        setFraming(hydrated.framing)
        setMood(hydrated.mood)
        setAspectRatio(hydrated.aspectRatio)
        setStyleId(hydrated.styleId)
        setModel(hydrated.model)
        setImageSize(hydrated.imageSize)
        setTargets(hydrated.targets)
        setBaseline(JSON.stringify(hydrated))
        setLoadError(null)
        setLoaded(true)
      })
      .catch((err) => {
        if (!active) return
        if (err instanceof ApiError && err.status === 404) setNotFound(true)
        else setLoadError(err instanceof Error ? err.message : String(err))
      })
    return () => { active = false }
  }, [loadAttempt, options.default_image_size, options.default_model, stageId])

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setApiError(null)
    const trimmedDescription = description.trim()
    const trimmedBeatText = beatText.trim()
    const trimmedTargets = targets.map((t) => t.trim()).filter(Boolean)
    if (!trimmedDescription) return setValidationError('Enter a description for this base stage.')
    if (!trimmedBeatText) return setValidationError('Enter a beat text describing the action.')
    if (!styleId) return setValidationError('Select a style.')
    if (!model) return setValidationError('Select a model.')
    if (trimmedTargets.length === 0) return setValidationError('Add at least one identity target.')
    setValidationError(null)
    setSubmitting(true)
    try {
      const payload: BaseStageGeneratedInput = {
        description: trimmedDescription,
        beat_text: trimmedBeatText,
        camera: camera.trim(),
        framing: framing.trim(),
        mood: mood.trim(),
        aspect_ratio: aspectRatio,
        style_id: styleId,
        model,
        image_size: imageSize,
        targets: trimmedTargets,
      }
      const stage = stageId === null
        ? await createGeneratedBaseStage(payload)
        : await updateBaseStage(stageId, payload)
      allowNavigation()
      navigate(`/base-stages/${stage.id}/preview`)
    } catch (err) {
      setApiError(err instanceof Error ? err.message : String(err))
      setSubmitting(false)
    }
  }

  if (notFound) return <NotFoundPage />
  if (!loaded) {
    return loadError ? (
      <div>
        <AsyncMessage kind="error">Could not load base stage: {loadError}</AsyncMessage>
        <button type="button" className="btn" onClick={() => { setLoadError(null); setLoadAttempt((value) => value + 1) }}>
          Retry
        </button>
      </div>
    ) : <AsyncMessage kind="loading" aria-busy="true">Loading base stage…</AsyncMessage>
  }
  if (locked) {
    return (
      <section className="form-page">
        <PageHeader title="Base stage locked" />
        <AsyncMessage kind="error">This base stage can no longer be edited. Duplicate it to change the composition.</AsyncMessage>
        <Link to={`/base-stages/${stageId}/preview`} className="btn btn--primary">Back to preview</Link>
      </section>
    )
  }

  return (
    <section className="form-page form-page--wide">
      <PageHeader
        title={stageId === null ? 'Create generated base stage' : `Edit base stage #${stageId}`}
        description={stageId === null
          ? 'Compose a scene first, then generate the anonymous composition image.'
          : 'Update the anonymous composition before starting generation.'}
      />
      {validationError && <AsyncMessage kind="error">{validationError}</AsyncMessage>}
      {apiError && <AsyncMessage kind="error">Could not {stageId === null ? 'create' : 'update'} base stage: {apiError}</AsyncMessage>}
      {submitting && <AsyncMessage kind="loading">{stageId === null ? 'Creating' : 'Updating'} base stage…</AsyncMessage>}
      <form className="form-card" noValidate aria-busy={submitting} onSubmit={(event) => void handleSubmit(event)}>
        <fieldset className="form-section">
          <legend>Composition</legend>
          <div className="field">
            <label htmlFor="base-stage-new-description">Description</label>
            <textarea
              id="base-stage-new-description"
              className="field__textarea--standard"
              rows={4}
              required
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
            <span className="field__hint">Describe the overall scene and composition.</span>
          </div>
          <div className="field">
            <label htmlFor="base-stage-new-beat">Beat text</label>
            <textarea
              id="base-stage-new-beat"
              className="field__textarea--standard"
              rows={2}
              required
              value={beatText}
              onChange={(event) => setBeatText(event.target.value)}
            />
            <span className="field__hint">What is happening in this scene.</span>
          </div>
          <div className="form-row form-row--triple">
            <div className="field">
              <label htmlFor="base-stage-new-camera">Camera position</label>
              <input
                id="base-stage-new-camera"
                type="text"
                value={camera}
                onChange={(event) => setCamera(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="base-stage-new-framing">Framing</label>
              <input
                id="base-stage-new-framing"
                type="text"
                value={framing}
                onChange={(event) => setFraming(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="base-stage-new-mood">Mood</label>
              <input
                id="base-stage-new-mood"
                type="text"
                value={mood}
                onChange={(event) => setMood(event.target.value)}
              />
            </div>
          </div>
          <div className="form-row form-row--triple">
            <div className="field">
              <label htmlFor="base-stage-new-aspect">Aspect ratio</label>
              <select
                id="base-stage-new-aspect"
                value={aspectRatio}
                onChange={(event) => setAspectRatio(event.target.value)}
              >
                {options.aspect_ratios.map((ar) => <option key={ar} value={ar}>{ar}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="base-stage-new-style">Style</label>
              <select
                id="base-stage-new-style"
                value={styleId ?? ''}
                onChange={(event) => setStyleId(Number(event.target.value))}
              >
                <option value="" disabled>Select style…</option>
                {styles?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="base-stage-new-size">Image size</label>
              <select
                id="base-stage-new-size"
                value={imageSize}
                onChange={(event) => setImageSize(event.target.value)}
              >
                {options.image_sizes.map((sz) => <option key={sz} value={sz}>{sz}</option>)}
              </select>
            </div>
          </div>
        </fieldset>
        <fieldset className="form-section">
          <legend>Generation settings</legend>
          <div className="field">
            <label htmlFor="base-stage-new-model">Model</label>
            <select
              id="base-stage-new-model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              {options.models.map((availableModel) => (
                <option key={availableModel} value={availableModel}>{availableModel}</option>
              ))}
            </select>
          </div>
        </fieldset>
        <fieldset className="form-section">
          <legend>Identity targets</legend>
          <p className="field__hint base-stage-upload__target-hint">
            Describe each visible person in order. These targets will be mapped to
            characters when scenes reference this base stage.
          </p>
          {targets.map((target, index) => (
            <div className="base-stage-upload__target" key={index}>
              <div className="field">
                <label htmlFor={`base-stage-new-target-${index}`}>Target {index + 1}</label>
                <input
                  id={`base-stage-new-target-${index}`}
                  type="text"
                  value={target}
                  onChange={(event) => setTargets((current) => current.map((value, i) => i === index ? event.target.value : value))}
                />
              </div>
              <button
                type="button"
                className="btn"
                disabled={submitting}
                aria-label={`Remove target ${index + 1}`}
                onClick={() => setTargets((current) => current.filter((_, i) => i !== index))}
              >
                <Icon name="trash" size="sm" /> Remove
              </button>
            </div>
          ))}
          <button type="button" className="btn" disabled={submitting} onClick={() => setTargets((current) => [...current, ''])}>
            <Icon name="plus" size="sm" /> Add target
          </button>
        </fieldset>
        <div className="form-actions">
          <button type="submit" className="btn btn--primary" disabled={submitting}>
            {stageId === null ? 'Create base stage' : 'Save changes'}
          </button>
          <button type="button" className="btn" disabled={submitting} onClick={() => navigate(stageId === null ? '/base-stages' : `/base-stages/${stageId}/preview`)}>
            Cancel
          </button>
        </div>
      </form>
      <ConfirmDialog {...confirmationProps} />
    </section>
  )
}
