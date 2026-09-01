import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, createCharacter, getCharacter, listStyles, updateCharacter } from '../../api/client'
import type { CharacterInput, Style } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'

const EMPTY: CharacterInput = {
  name: '',
  slug: '',
  lore_md: '',
  visual_contract: '',
  negative_traits: '',
  default_style_id: null,
}

const snapshot = (values: CharacterInput) =>
  JSON.stringify({
    name: values.name,
    slug: values.slug ?? '',
    lore_md: values.lore_md,
    visual_contract: values.visual_contract,
    negative_traits: values.negative_traits,
    default_style_id: values.default_style_id ?? null,
  })

/** Create/edit form. On a failed submit the user's values are preserved
 * (they live in React state, not reset from a server response) and only the
 * error banner changes — issue #15's "preserve values on errors" rule. */
export function CharacterFormPage() {
  const { id } = useParams()
  if (id === undefined) return <CharacterForm key="new" characterId={null} />
  return (
    <RouteIdGuard>
      {(characterId) => <CharacterForm key={characterId} characterId={characterId} />}
    </RouteIdGuard>
  )
}

function CharacterForm({ characterId }: { characterId: number | null }) {
  const navigate = useNavigate()

  const [values, setValues] = useState<CharacterInput>(EMPTY)
  const [styles, setStyles] = useState<Style[]>([])
  const [stylesError, setStylesError] = useState<string | null>(null)
  const [stylesLoading, setStylesLoading] = useState(true)
  const [stylesAttempt, setStylesAttempt] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loaded, setLoaded] = useState(characterId === null)
  const [notFound, setNotFound] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [baseline, setBaseline] = useState<string | null>(
    characterId === null ? snapshot(EMPTY) : null,
  )
  const allowNavigation = useUnsavedChanges(baseline !== null && snapshot(values) !== baseline)
  const mounted = useRef(true)
  const submitRequest = useRef(0)

  usePageTitle(
    characterId === null ? 'New Character' : loaded ? `Edit ${values.name}` : 'Edit Character',
  )

  useEffect(() => {
    let active = true
    listStyles()
      .then((styleList) => {
        if (!active) return
        setStyles(styleList)
        setStylesLoading(false)
      })
      .catch((err) => {
        if (!active) return
        setStylesError(err instanceof ApiError ? err.message : String(err))
        setStylesLoading(false)
      })
    return () => {
      active = false
    }
  }, [stylesAttempt])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      submitRequest.current += 1
    }
  }, [])

  useEffect(() => {
    if (characterId === null) return
    let active = true
    getCharacter(characterId)
      .then((character) => {
        if (!active) return
        const hydratedValues: CharacterInput = {
          name: character.name,
          slug: character.slug,
          lore_md: character.lore_md,
          visual_contract: character.visual_contract,
          negative_traits: character.negative_traits,
          default_style_id: character.default_style_id,
        }
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
  }, [characterId, loadAttempt])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const request = ++submitRequest.current
    setSubmitting(true)
    setError(null)
    try {
      const saved =
        characterId === null
          ? await createCharacter(values)
          : await updateCharacter(characterId, values)
      if (!mounted.current || request !== submitRequest.current) return
      allowNavigation()
      navigate(`/characters/${saved.id}`)
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
        <AsyncMessage kind="error">Could not load character: {error}</AsyncMessage>
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
    ) : <AsyncMessage kind="loading" aria-busy="true">Loading character…</AsyncMessage>
  }

  const wordCount = values.visual_contract?.trim() ? values.visual_contract.trim().split(/\s+/).length : 0

  return (
    <section>
      <h1>{characterId === null ? 'New character' : 'Edit character'}</h1>
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {stylesLoading && (
        <AsyncMessage kind="loading" aria-busy="true">Loading styles…</AsyncMessage>
      )}
      {stylesError && (
        <div>
          <AsyncMessage kind="error">Could not load styles: {stylesError}</AsyncMessage>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setStylesLoading(true)
              setStylesError(null)
              setStylesAttempt((value) => value + 1)
            }}
          >
            Retry styles
          </button>
        </div>
      )}
      {submitting && <AsyncMessage kind="loading">Saving character…</AsyncMessage>}
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
          <label htmlFor="slug">Slug</label>
          <input
            id="slug"
            type="text"
            value={values.slug ?? ''}
            onChange={(e) => setValues((v) => ({ ...v, slug: e.target.value }))}
          />
          <span className="field__hint">Leave blank to derive from the name. Must be unique.</span>
        </div>
        <div className="field">
          <label htmlFor="visual_contract">Visual contract</label>
          <textarea
            id="visual_contract"
            value={values.visual_contract}
            onChange={(e) => setValues((v) => ({ ...v, visual_contract: e.target.value }))}
          />
          <span className="field__hint">
            Sent to the image model with every generation — discriminative traits only, capped at 60
            words ({wordCount}/60). Example: "Tall, gaunt build; pale grey eyes; a thin scar over the
            left brow."
          </span>
        </div>
        <div className="field">
          <label htmlFor="negative_traits">Negative traits</label>
          <textarea
            id="negative_traits"
            value={values.negative_traits}
            onChange={(e) => setValues((v) => ({ ...v, negative_traits: e.target.value }))}
          />
          <span className="field__hint">
            Sent to the model as traits to avoid. Example: "no facial hair, no glasses."
          </span>
        </div>
        <div className="field">
          <label htmlFor="lore_md">Lore</label>
          <textarea
            id="lore_md"
            value={values.lore_md}
            onChange={(e) => setValues((v) => ({ ...v, lore_md: e.target.value }))}
          />
          <span className="field__hint">
            Local-only backstory notes. Never sent to the image model — keep as much detail as you
            like.
          </span>
        </div>
        <div className="field">
          <label htmlFor="default_style_id">Default style</label>
          <select
            id="default_style_id"
            value={values.default_style_id ?? ''}
            onChange={(e) =>
              setValues((v) => ({
                ...v,
                default_style_id: e.target.value ? Number(e.target.value) : null,
              }))
            }
          >
            <option value="">None</option>
            {styles.map((style) => (
              <option key={style.id} value={style.id}>
                {style.name}
              </option>
            ))}
          </select>
        </div>
        <div className="btn-row">
          <button type="submit" className="btn btn--primary" disabled={submitting}>
            Save
          </button>
          <button
            type="button"
            className="btn"
            disabled={submitting}
            onClick={() => navigate(characterId === null ? '/characters' : `/characters/${characterId}`)}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  )
}
