import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, createStyle, getStyle, updateStyle } from '../../api/client'
import type { StyleInput } from '../../api/types'
import { parseRefImageIds } from './refImageIds'

const EMPTY: StyleInput = { name: '', style_contract: '', ref_image_ids: [] }

export function StyleFormPage() {
  const { id } = useParams()
  const styleId = id ? Number(id) : null
  const navigate = useNavigate()

  const [values, setValues] = useState<StyleInput>(EMPTY)
  // Reference-image IDs are edited as raw comma-separated text so a user can
  // type "1, 2, 3" freely; it is parsed/validated on submit (see
  // parseRefImageIds above) rather than on every keystroke.
  const [refImageIdsText, setRefImageIdsText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loaded, setLoaded] = useState(styleId === null)

  useEffect(() => {
    if (styleId === null) return
    getStyle(styleId)
      .then((style) => {
        setValues({ name: style.name, style_contract: style.style_contract, ref_image_ids: style.ref_image_ids })
        // Preserve the existing IDs in the editable text control so editing
        // a style never silently drops its reference-image associations.
        setRefImageIdsText(style.ref_image_ids.join(', '))
        setLoaded(true)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [styleId])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    let refImageIds: number[]
    try {
      refImageIds = parseRefImageIds(refImageIdsText)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      return
    }
    setSubmitting(true)
    try {
      const payload: StyleInput = { ...values, ref_image_ids: refImageIds }
      const saved = styleId === null ? await createStyle(payload) : await updateStyle(styleId, payload)
      navigate('/styles')
      void saved
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!loaded) return <p>Loading…</p>

  return (
    <section>
      <h1>{styleId === null ? 'New style' : 'Edit style'}</h1>
      {error && <p className="banner banner--error">{error}</p>}
      <form onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="name">Name</label>
          <input
            id="name"
            type="text"
            required
            value={values.name}
            onChange={(e) => setValues((v) => ({ ...v, name: e.target.value }))}
          />
        </div>
        <div className="field">
          <label htmlFor="style_contract">Style contract</label>
          <textarea
            id="style_contract"
            aria-describedby="style_contract-hint"
            value={values.style_contract}
            onChange={(e) => setValues((v) => ({ ...v, style_contract: e.target.value }))}
          />
          <span className="field__hint" id="style_contract-hint">
            Sent verbatim with every generation using this style. Example: "Victorian-era oil
            painting. Rich chiaroscuro lighting; visible brushwork."
          </span>
        </div>
        <div className="field">
          <label htmlFor="ref_image_ids">Reference image IDs</label>
          <input
            id="ref_image_ids"
            type="text"
            aria-describedby="ref_image_ids-hint"
            placeholder="e.g. 12, 15"
            value={refImageIdsText}
            onChange={(e) => setRefImageIdsText(e.target.value)}
          />
          <span className="field__hint" id="ref_image_ids-hint">
            Optional. A comma-separated list of reference image IDs (from a character's
            reference set) that best represent this style, e.g. "12, 15". Leave blank if this
            style has no example images. IDs are the same opaque IDs shown throughout the app —
            never a content hash.
          </span>
        </div>
        <div className="btn-row">
          <button type="submit" className="btn btn--primary" disabled={submitting}>
            Save
          </button>
        </div>
      </form>
    </section>
  )
}
