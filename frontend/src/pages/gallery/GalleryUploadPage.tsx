import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadGalleryPicture } from '../../api/client'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { PageHeader } from '../../components/PageHeader'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])

export function GalleryUploadPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [dimensions, setDimensions] = useState<{ width: number; height: number } | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const { allowNavigation, confirmationProps } = useUnsavedChanges(file !== null || title !== '')

  useEffect(() => {
    if (!previewUrl) return
    return () => URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null
    if (selected && !IMAGE_TYPES.has(selected.type)) {
      setFile(selected)
      setPreviewUrl(null)
      setDimensions(null)
      setValidationError('The selected file must be PNG, JPEG, or WebP.')
      return
    }
    if (selected && selected.size > MAX_FILE_SIZE) {
      setFile(selected)
      setPreviewUrl(null)
      setDimensions(null)
      setValidationError('The selected image is larger than the 10MB upload limit.')
      return
    }
    setFile(selected)
    setPreviewUrl(selected ? URL.createObjectURL(selected) : null)
    setDimensions(null)
    setValidationError(null)
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setApiError(null)
    const trimmedTitle = title.trim()
    if (!file) return setValidationError('Choose a PNG, JPEG, or WebP image.')
    if (!IMAGE_TYPES.has(file.type)) return setValidationError('The selected file must be PNG, JPEG, or WebP.')
    if (file.size > MAX_FILE_SIZE) return setValidationError('The selected image is larger than the 10MB upload limit.')
    if (!trimmedTitle) return setValidationError('Enter a title for this picture.')
    setValidationError(null)
    setSubmitting(true)
    try {
      await uploadGalleryPicture(file, trimmedTitle)
      allowNavigation()
      navigate('/gallery')
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error))
      setSubmitting(false)
    }
  }

  return (
    <section className="form-page form-page--wide">
      <PageHeader title="Upload picture" description="Add an image to the Gallery and make it immediately available for panels." />
      {validationError && <AsyncMessage kind="error">{validationError}</AsyncMessage>}
      {apiError && <AsyncMessage kind="error">Could not upload picture: {apiError}</AsyncMessage>}
      {submitting && <AsyncMessage kind="loading">Uploading picture…</AsyncMessage>}
      <form className="form-card" noValidate aria-busy={submitting} onSubmit={(event) => void handleSubmit(event)}>
        <fieldset className="form-section">
          <legend>Picture details</legend>
          <div className="field">
            <label htmlFor="gallery-picture-title">Title</label>
            <input id="gallery-picture-title" type="text" required maxLength={120} value={title} onChange={(event) => setTitle(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="gallery-picture-image">Image</label>
            <input id="gallery-picture-image" type="file" required accept="image/png,image/jpeg,image/webp" onChange={handleFile} />
            <span className="field__hint">PNG, JPEG, or WebP. Maximum file size: 10MB.</span>
          </div>
          {previewUrl && (
            <figure className="base-stage-upload__preview">
              <img src={previewUrl} alt="Selected gallery picture preview" onLoad={(event) => setDimensions({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} />
              <figcaption>{file?.name}{dimensions ? ` · ${dimensions.width} × ${dimensions.height}` : ''}</figcaption>
            </figure>
          )}
        </fieldset>
        <div className="form-actions">
          <button type="submit" className="btn btn--primary" disabled={submitting}>Upload picture</button>
          <button type="button" className="btn" disabled={submitting} onClick={() => navigate('/gallery')}>Cancel</button>
        </div>
      </form>
      <ConfirmDialog {...confirmationProps} />
    </section>
  )
}
