import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ApiError,
  createPanel,
  duplicatePanel,
  getPanel,
  listCharacters,
  listStyles,
  updatePanel,
} from '../../api/client'
import { useOptions } from '../../api/useOptions'
import type { CastMemberInput, Character, PanelInput, Style } from '../../api/types'
import { CastSelector } from '../../components/CastSelector'

const EMPTY = (defaults: { model: string; image_size: string }): PanelInput => ({
  beat_text: '',
  camera: '',
  framing: '',
  mood: '',
  aspect_ratio: '3:2',
  cast: [],
  style_id: 0,
  model: defaults.model,
  image_size: defaults.image_size,
})

export function PanelFormPage() {
  const { id } = useParams()
  const panelId = id ? Number(id) : null
  const navigate = useNavigate()
  const options = useOptions()

  const [values, setValues] = useState<PanelInput>(() =>
    EMPTY({ model: options.default_model, image_size: options.default_image_size }),
  )
  const [characters, setCharacters] = useState<Character[]>([])
  const [styles, setStyles] = useState<Style[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loaded, setLoaded] = useState(panelId === null)
  const [locked, setLocked] = useState(false)

  useEffect(() => {
    Promise.all([listCharacters(), listStyles()]).then(([chars, styleList]) => {
      setCharacters(chars)
      setStyles(styleList)
      setValues((v) => (v.style_id === 0 && styleList[0] ? { ...v, style_id: styleList[0].id } : v))
    })
  }, [])

  useEffect(() => {
    if (panelId === null) return
    getPanel(panelId)
      .then((panel) => {
        if (!panel.is_editable) {
          setLocked(true)
          setLoaded(true)
          return
        }
        setValues({
          beat_text: panel.beat_text,
          camera: panel.camera,
          framing: panel.framing,
          mood: panel.mood,
          aspect_ratio: panel.aspect_ratio,
          cast: panel.cast.map((m) => ({
            character_id: m.character_id,
            role: m.role,
            prominence: m.prominence,
          })),
          style_id: panel.style_id,
          model: panel.model,
          image_size: panel.image_size,
        })
        setLoaded(true)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [panelId])

  const handleDuplicate = async () => {
    if (panelId === null) return
    try {
      const copy = await duplicatePanel(panelId)
      navigate(`/panels/${copy.id}/edit`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const saved = panelId === null ? await createPanel(values) : await updatePanel(panelId, values)
      navigate(`/panels/${saved.id}/preview`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!loaded) return <p>Loading…</p>

  if (locked) {
    return (
      <section>
        <h1>Panel locked</h1>
        <p className="banner banner--info">{options.panel_immutability_explanation}</p>
        <button type="button" className="btn btn--primary" onClick={() => void handleDuplicate()}>
          Duplicate &amp; edit
        </button>
      </section>
    )
  }

  const setCast = (cast: CastMemberInput[]) => setValues((v) => ({ ...v, cast }))

  return (
    <section>
      <h1>{panelId === null ? 'Stage new panel' : 'Edit panel'}</h1>
      {error && <p className="banner banner--error">{error}</p>}
      <form onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="beat_text">Action</label>
          <textarea
            id="beat_text"
            required
            aria-describedby="beat_text-hint"
            value={values.beat_text}
            onChange={(e) => setValues((v) => ({ ...v, beat_text: e.target.value }))}
          />
          <span className="field__hint" id="beat_text-hint">
            What is happening in this panel — the beat/action, not the camera. Example: "Elias
            draws his sword as Mara backs toward the door."
          </span>
        </div>

        <fieldset style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '0.75rem 1rem' }}>
          <legend>Framing</legend>
          <div className="field">
            <label htmlFor="camera">Camera</label>
            <input
              id="camera"
              type="text"
              required
              aria-describedby="camera-hint"
              value={values.camera}
              onChange={(e) => setValues((v) => ({ ...v, camera: e.target.value }))}
            />
            <span className="field__hint" id="camera-hint">
              The viewer's position and angle relative to the subject — where the "camera" is
              standing and which way it looks, not how tightly cropped the shot is. Example: "low
              angle, looking up" or "eye level, three-quarter view from the left".
            </span>
          </div>
          <div className="field">
            <label htmlFor="framing">Shot framing</label>
            <input
              id="framing"
              type="text"
              required
              aria-describedby="framing-hint"
              value={values.framing}
              onChange={(e) => setValues((v) => ({ ...v, framing: e.target.value }))}
            />
            <span className="field__hint" id="framing-hint">
              How tightly the shot is cropped — what remains visible in frame, not the viewer's
              angle. Example: "medium close-up, head and shoulders only" or "wide shot, full room
              visible".
            </span>
          </div>
        </fieldset>

        <div className="field">
          <label htmlFor="mood">Mood</label>
          <input
            id="mood"
            type="text"
            aria-describedby="mood-hint"
            value={values.mood}
            onChange={(e) => setValues((v) => ({ ...v, mood: e.target.value }))}
          />
          <span className="field__hint" id="mood-hint">
            Optional tone/atmosphere. Example: "tense, candlelit".
          </span>
        </div>

        <div className="field">
          <label htmlFor="aspect_ratio">Aspect ratio</label>
          <select
            id="aspect_ratio"
            aria-describedby="aspect_ratio-hint"
            value={values.aspect_ratio}
            onChange={(e) => setValues((v) => ({ ...v, aspect_ratio: e.target.value }))}
          >
            {options.aspect_ratios.map((ratio) => (
              <option key={ratio} value={ratio}>
                {ratio}
              </option>
            ))}
          </select>
          <span className="field__hint" id="aspect_ratio-hint">
            The shape (width:height) of the generated image. Example: "16:9" for a wide,
            cinematic panel; "1:1" for a square panel; "3:4" for a tall portrait panel.
          </span>
        </div>

        <div className="field">
          <label htmlFor="style_id">Style</label>
          <select
            id="style_id"
            aria-describedby="style_id-hint"
            value={values.style_id}
            onChange={(e) => setValues((v) => ({ ...v, style_id: Number(e.target.value) }))}
          >
            {styles.map((style) => (
              <option key={style.id} value={style.id}>
                {style.name}
              </option>
            ))}
          </select>
          <span className="field__hint" id="style_id-hint">
            The visual art style applied to every character and the scene — its style contract is
            sent verbatim with the generation. Example: "Victorian Oil Painting" for rich
            chiaroscuro brushwork.
          </span>
        </div>

        <div className="field">
          <label htmlFor="model">Model</label>
          <select
            id="model"
            aria-describedby="model-hint"
            value={values.model}
            onChange={(e) => setValues((v) => ({ ...v, model: e.target.value }))}
          >
            {options.models.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
          <span className="field__hint" id="model-hint">
            Which image-generation model to use. Higher-capacity models support larger casts and
            cost more per image; see the budget in the header.
          </span>
        </div>

        <div className="field">
          <label htmlFor="image_size">Image size</label>
          <select
            id="image_size"
            aria-describedby="image_size-hint"
            value={values.image_size}
            onChange={(e) => setValues((v) => ({ ...v, image_size: e.target.value }))}
          >
            {options.image_sizes.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
          <span className="field__hint" id="image_size-hint">
            Output resolution. Larger sizes look sharper but cost more per generation. Example:
            "1K" for a quick draft, "2K" or "4K" for a final panel.
          </span>
        </div>

        <div className="field">
          <label id="cast-label">Cast</label>
          <CastSelector
            characters={characters}
            value={values.cast}
            onChange={setCast}
            labelledBy="cast-label"
          />
        </div>

        <div className="btn-row">
          <button type="submit" className="btn btn--primary" disabled={submitting}>
            Save and preview
          </button>
        </div>
      </form>
    </section>
  )
}
