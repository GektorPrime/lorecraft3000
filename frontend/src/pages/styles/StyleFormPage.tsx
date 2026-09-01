import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, createStyle, getStyle, updateStyle } from '../../api/client'
import type { StyleInput } from '../../api/types'

const EMPTY: StyleInput = { name: '', style_contract: '' }

export function StyleFormPage() {
  const { id } = useParams()
  const styleId = id ? Number(id) : null
  const navigate = useNavigate()

  const [values, setValues] = useState<StyleInput>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loaded, setLoaded] = useState(styleId === null)

  useEffect(() => {
    if (styleId === null) return
    getStyle(styleId)
      .then((style) => {
        setValues({ name: style.name, style_contract: style.style_contract })
        setLoaded(true)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [styleId])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const saved = styleId === null ? await createStyle(values) : await updateStyle(styleId, values)
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
        <div className="btn-row">
          <button type="submit" className="btn btn--primary" disabled={submitting}>
            Save
          </button>
        </div>
      </form>
    </section>
  )
}
