import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadBaseStage } from '../../api/client'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])

export function BaseStageUploadPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [description, setDescription] = useState('')
  const [targets, setTargets] = useState<string[]>([])
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [dimensions, setDimensions] = useState<{ width: number; height: number } | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const { allowNavigation, confirmationProps } = useUnsavedChanges(
    file !== null || description !== '' || targets.length > 0,
  )

  useEffect(() => {
    if (!previewUrl) return
    return () => URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0] ?? null
    setFile(selectedFile)
    setPreviewUrl(selectedFile ? URL.createObjectURL(selectedFile) : null)
    setDimensions(null)
    setValidationError(null)
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setApiError(null)
    const trimmedDescription = description.trim()
    const trimmedTargets = targets.map((target) => target.trim())
    if (!file) return setValidationError('Choose a PNG, JPEG, or WebP image.')
    if (!IMAGE_TYPES.has(file.type)) return setValidationError('The selected file must be PNG, JPEG, or WebP.')
    if (file.size > MAX_FILE_SIZE) return setValidationError('The selected image is larger than the 10MB upload limit.')
    if (!trimmedDescription) return setValidationError('Enter a description for this base stage.')
    if (trimmedTargets.some((target) => !target)) return setValidationError('Remove empty targets or describe each target.')
    setValidationError(null)
    setSubmitting(true)
    try {
      await uploadBaseStage(file, trimmedDescription, trimmedTargets)
      allowNavigation()
      navigate('/base-stages')
    } catch (err) {
      setApiError(err instanceof Error ? err.message : String(err))
      setSubmitting(false)
    }
  }

  return (
    <section className="form-page form-page--wide">
      <PageHeader title="Upload base stage" description="Add a reusable scene image to the base stage library." />
      {validationError && <AsyncMessage kind="error">{validationError}</AsyncMessage>}
      {apiError && <AsyncMessage kind="error">Could not upload base stage: {apiError}</AsyncMessage>}
      {submitting && <AsyncMessage kind="loading">Uploading base stage…</AsyncMessage>}
      <form className="form-card" noValidate aria-busy={submitting} onSubmit={(event) => void handleSubmit(event)}>
        <fieldset className="form-section">
          <legend>Stage image</legend>
          <div className="field">
            <label htmlFor="base-stage-image">Image</label>
            <input id="base-stage-image" type="file" required accept="image/png,image/jpeg,image/webp" onChange={handleFile} />
            <span className="field__hint">PNG, JPEG, or WebP. Maximum file size: 10MB.</span>
          </div>
          {previewUrl && (
            <figure className="base-stage-upload__preview">
              <img src={previewUrl} alt="Selected base stage preview" onLoad={(event) => setDimensions({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} />
              <figcaption>{file?.name}{dimensions ? ` · ${dimensions.width} × ${dimensions.height}` : ''}</figcaption>
            </figure>
          )}
          <div className="field">
            <label htmlFor="base-stage-description">Description</label>
            <textarea id="base-stage-description" className="field__textarea--standard" rows={6} required value={description} onChange={(event) => setDescription(event.target.value)} />
          </div>
        </fieldset>
        <fieldset className="form-section">
          <legend>Identity targets</legend>
          <p className="field__hint base-stage-upload__target-hint">Optional reusable descriptions of visible people, kept in order for future character mapping.</p>
          {targets.map((target, index) => (
            <div className="base-stage-upload__target" key={index}>
              <div className="field">
                <label htmlFor={`base-stage-target-${index}`}>Target {index + 1}</label>
                <input id={`base-stage-target-${index}`} type="text" value={target} onChange={(event) => setTargets((current) => current.map((value, targetIndex) => targetIndex === index ? event.target.value : value))} />
              </div>
              <button type="button" className="btn" disabled={submitting} aria-label={`Remove target ${index + 1}`} onClick={() => setTargets((current) => current.filter((_, targetIndex) => targetIndex !== index))}>
                <Icon name="trash" size="sm" /> Remove
              </button>
            </div>
          ))}
          <button type="button" className="btn" disabled={submitting} onClick={() => setTargets((current) => [...current, ''])}>
            <Icon name="plus" size="sm" /> Add target
          </button>
        </fieldset>
        <div className="form-actions">
          <button type="submit" className="btn btn--primary" disabled={submitting}>Upload base stage</button>
          <button type="button" className="btn" disabled={submitting} onClick={() => navigate('/base-stages')}>Cancel</button>
        </div>
      </form>
      <ConfirmDialog {...confirmationProps} />
    </section>
  )
}
