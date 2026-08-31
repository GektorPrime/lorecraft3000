import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, createCharacter, getCharacter, listStyles, updateCharacter } from '../../api/client'
import type { CharacterInput, Style } from '../../api/types'

const EMPTY: CharacterInput = {
  name: '',
  slug: '',
  lore_md: '',
  visual_contract: '',
  negative_traits: '',
  default_style_id: null,
}

/** Create/edit form. On a failed submit the user's values are preserved
 * (they live in React state, not reset from a server response) and only the
 * error banner changes — issue #15's "preserve values on errors" rule. */
export function CharacterFormPage() {
  const { id } = useParams()
  const characterId = id ? Number(id) : null
  const navigate = useNavigate()

  const [values, setValues] = useState<CharacterInput>(EMPTY)
  const [styles, setStyles] = useState<Style[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loaded, setLoaded] = useState(characterId === null)

  useEffect(() => {
    listStyles().then(setStyles).catch(() => setStyles([]))
  }, [])

  useEffect(() => {
    if (characterId === null) return
    getCharacter(characterId)
      .then((character) => {
        setValues({
          name: character.name,
          slug: character.slug,
          lore_md: character.lore_md,
          visual_contract: character.visual_contract,
          negative_traits: character.negative_traits,
          default_style_id: character.default_style_id,
        })
        setLoaded(true)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [characterId])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const saved =
        characterId === null
          ? await createCharacter(values)
          : await updateCharacter(characterId, values)
      navigate(`/characters/${saved.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!loaded) return <p>Loading…</p>

  const wordCount = values.visual_contract?.trim() ? values.visual_contract.trim().split(/\s+/).length : 0

  return (
    <section>
      <h1>{characterId === null ? 'New character' : 'Edit character'}</h1>
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
        </div>
      </form>
    </section>
  )
}
