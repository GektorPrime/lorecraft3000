import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { createGeneratedBaseStage, listStyles } from '../../api/client'
import type { BaseStageGeneratedInput, Style } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'

const ASPECT_RATIOS = ['16:9', '3:2', '1:1', '2:3', '9:16'] as const
const IMAGE_SIZES = ['1K', '2K'] as const

export function BaseStageNewPage() {
  const navigate = useNavigate()
  const [styles, setStyles] = useState<Style[] | null>(null)
  const [description, setDescription] = useState('')
  const [beatText, setBeatText] = useState('')
  const [camera, setCamera] = useState('')
  const [framing, setFraming] = useState('')
  const [mood, setMood] = useState('')
  const [aspectRatio, setAspectRatio] = useState('16:9')
  const [styleId, setStyleId] = useState<number | null>(null)
  const [model, setModel] = useState('')
  const [imageSize, setImageSize] = useState('1K')
  const [targets, setTargets] = useState<string[]>([])
  const [validationError, setValidationError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const { allowNavigation, confirmationProps } = useUnsavedChanges(
    description !== '' || beatText !== '' || targets.length > 0,
  )

  useEffect(() => {
    listStyles().then((s) => {
      setStyles(s)
      if (s.length > 0) setStyleId(s[0].id)
    }).catch(() => {})
  }, [])

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
      const stage = await createGeneratedBaseStage(payload)
      allowNavigation()
      navigate(`/base-stages/${stage.id}/preview`)
    } catch (err) {
      setApiError(err instanceof Error ? err.message : String(err))
      setSubmitting(false)
    }
  }

  return (
    <section className="form-page form-page--wide">
      <PageHeader
        title="Create generated base stage"
        description="Compose a scene first, then generate the anonymous composition image."
      />
      {validationError && <AsyncMessage kind="error">{validationError}</AsyncMessage>}
      {apiError && <AsyncMessage kind="error">Could not create base stage: {apiError}</AsyncMessage>}
      {submitting && <AsyncMessage kind="loading">Creating base stage…</AsyncMessage>}
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
                {ASPECT_RATIOS.map((ar) => <option key={ar} value={ar}>{ar}</option>)}
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
                {IMAGE_SIZES.map((sz) => <option key={sz} value={sz}>{sz}</option>)}
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
              <option value="" disabled>Select model…</option>
              <option value="gpt-image-2">gpt-image-2</option>
              <option value="gemini-3.1-flash-image">gemini-3.1-flash-image</option>
            </select>
          </div>
        </fieldset>
        <fieldset className="form-section">
          <legend>Identity targets</legend>
          <p className="field__hint base-stage-upload__target-hint">
            Describe each visible person in order. These targets will be mapped to
            characters when panels reference this base stage.
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
                <Icon name="trash" size={15} /> Remove
              </button>
            </div>
          ))}
          <button type="button" className="btn" disabled={submitting} onClick={() => setTargets((current) => [...current, ''])}>
            <Icon name="plus" size={15} /> Add target
          </button>
        </fieldset>
        <div className="form-actions">
          <button type="submit" className="btn btn--primary" disabled={submitting}>
            Create base stage
          </button>
          <button type="button" className="btn" disabled={submitting} onClick={() => navigate('/base-stages')}>
            Cancel
          </button>
        </div>
      </form>
      <ConfirmDialog {...confirmationProps} />
    </section>
  )
}
