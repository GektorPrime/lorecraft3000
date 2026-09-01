import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, createStyle, getStyle, updateStyle } from '../../api/client'
import type { StyleInput } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'

const EMPTY: StyleInput = { name: '', style_contract: '' }

const snapshot = (values: StyleInput) =>
  JSON.stringify({ name: values.name, style_contract: values.style_contract })

export function StyleFormPage() {
  const { id } = useParams()
  if (id === undefined) return <StyleForm key="new" styleId={null} />
  return (
    <RouteIdGuard>{(styleId) => <StyleForm key={styleId} styleId={styleId} />}</RouteIdGuard>
  )
}

function StyleForm({ styleId }: { styleId: number | null }) {
  const navigate = useNavigate()

  const [values, setValues] = useState<StyleInput>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loaded, setLoaded] = useState(styleId === null)
  const [notFound, setNotFound] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [baseline, setBaseline] = useState<string | null>(
    styleId === null ? snapshot(EMPTY) : null,
  )
  const allowNavigation = useUnsavedChanges(baseline !== null && snapshot(values) !== baseline)
  const mounted = useRef(true)
  const submitRequest = useRef(0)

  usePageTitle(styleId === null ? 'New Style' : loaded ? `Edit ${values.name}` : 'Edit Style')

  useEffect(() => {
    if (styleId === null) return
    let active = true
    getStyle(styleId)
      .then((style) => {
        if (!active) return
        const hydratedValues = { name: style.name, style_contract: style.style_contract }
        setBaseline(snapshot(hydratedValues))
        setValues(hydratedValues)
        setLoaded(true)
      })
      .catch((err) => {
        if (!active) return
        if (err instanceof ApiError && err.status === 404) setNotFound(true)
        else setError(err instanceof ApiError ? err.message : String(err))
      })
    return () => {
      active = false
    }
  }, [styleId, loadAttempt])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      submitRequest.current += 1
    }
  }, [])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const request = ++submitRequest.current
    setError(null)
    setSubmitting(true)
    try {
      const saved = styleId === null ? await createStyle(values) : await updateStyle(styleId, values)
      if (!mounted.current || request !== submitRequest.current) return
      allowNavigation()
      navigate('/styles')
      void saved
    } catch (err) {
      if (!mounted.current || request !== submitRequest.current) return
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      if (mounted.current && request === submitRequest.current) setSubmitting(false)
    }
  }

  if (notFound) return <NotFoundPage />
  if (!loaded) {
    return error ? (
      <div>
        <AsyncMessage kind="error">Could not load style: {error}</AsyncMessage>
        <button
          type="button"
          className="btn"
          onClick={() => {
            setError(null)
            setLoadAttempt((value) => value + 1)
          }}
        >
          Retry
        </button>
      </div>
    ) : <AsyncMessage kind="loading" aria-busy="true">Loading style…</AsyncMessage>
  }

  return (
    <section>
      <h1>{styleId === null ? 'New style' : 'Edit style'}</h1>
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {submitting && <AsyncMessage kind="loading">Saving style…</AsyncMessage>}
      <form onSubmit={handleSubmit} aria-busy={submitting}>
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
          <button
            type="button"
            className="btn"
            disabled={submitting}
            onClick={() => navigate('/styles')}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  )
}
