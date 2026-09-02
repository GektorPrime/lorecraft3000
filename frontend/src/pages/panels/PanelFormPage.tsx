import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
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
import { AsyncMessage } from '../../components/AsyncMessage'
import { EmptyState } from '../../components/EmptyState'
import { Notice } from '../../components/Notice'
import { PageHeader } from '../../components/PageHeader'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'

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

const snapshot = (values: PanelInput) =>
  JSON.stringify({
    beat_text: values.beat_text,
    camera: values.camera,
    framing: values.framing,
    mood: values.mood,
    aspect_ratio: values.aspect_ratio,
    cast: values.cast.map(({ character_id, role, prominence }) => ({
      character_id,
      role,
      prominence,
    })),
    style_id: values.style_id,
    model: values.model,
    image_size: values.image_size,
  })

export function PanelFormPage() {
  const { id } = useParams()
  if (id === undefined) return <PanelForm key="new" panelId={null} />
  return (
    <RouteIdGuard>{(panelId) => <PanelForm key={panelId} panelId={panelId} />}</RouteIdGuard>
  )
}

function PanelForm({ panelId }: { panelId: number | null }) {
  const navigate = useNavigate()
  const options = useOptions()

  const [values, setValues] = useState<PanelInput>(() =>
    EMPTY({ model: options.default_model, image_size: options.default_image_size }),
  )
  const [characters, setCharacters] = useState<Character[]>([])
  const [styles, setStyles] = useState<Style[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  const [prerequisiteState, setPrerequisiteState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [prerequisiteError, setPrerequisiteError] = useState<string | null>(null)
  const [prerequisiteAttempt, setPrerequisiteAttempt] = useState(0)
  const [panelState, setPanelState] = useState<'loading' | 'ready' | 'error'>(
    panelId === null ? 'ready' : 'loading',
  )
  const [loadedPanelId, setLoadedPanelId] = useState<number | null>(panelId)
  const [panelError, setPanelError] = useState<string | null>(null)
  const [panelAttempt, setPanelAttempt] = useState(0)
  const [locked, setLocked] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [baseline, setBaseline] = useState<string | null>(null)
  const { allowNavigation, confirmationProps } = useUnsavedChanges(
    baseline !== null && snapshot(values) !== baseline,
  )
  const mounted = useRef(true)
  const mutationRequest = useRef(0)

  usePageTitle(
    panelId === null
      ? 'New Panel'
      : panelState === 'ready' && loadedPanelId === panelId
        ? `Edit Panel #${panelId}`
        : 'Edit Panel',
  )

  useEffect(() => {
    let active = true
    Promise.all([listCharacters(), listStyles()])
      .then(([chars, styleList]) => {
        if (!active) return
        setCharacters(chars)
        setStyles(styleList)
        setValues((v) =>
          v.style_id === 0 && styleList[0] ? { ...v, style_id: styleList[0].id } : v,
        )
        if (panelId === null) {
          const hydratedValues = EMPTY({
            model: options.default_model,
            image_size: options.default_image_size,
          })
          if (styleList[0]) hydratedValues.style_id = styleList[0].id
          setBaseline(snapshot(hydratedValues))
        }
        setPrerequisiteState('ready')
      })
      .catch((err) => {
        if (!active) return
        setPrerequisiteError(err instanceof ApiError ? err.message : String(err))
        setPrerequisiteState('error')
      })
    return () => {
      active = false
    }
  }, [options.default_image_size, options.default_model, panelId, prerequisiteAttempt])

  useEffect(() => {
    if (panelId === null) return
    let active = true
    getPanel(panelId)
      .then((panel) => {
        if (!active) return
        setLoadedPanelId(panelId)
        if (!panel.is_editable) {
          setLocked(true)
          setPanelState('ready')
          return
        }
        setLocked(false)
        const hydratedValues: PanelInput = {
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
        }
        setBaseline(snapshot(hydratedValues))
        setValues(hydratedValues)
        setPanelState('ready')
      })
      .catch((err) => {
        if (!active) return
        setLoadedPanelId(panelId)
        if (err instanceof ApiError && err.status === 404) setNotFound(true)
        else {
          setPanelError(err instanceof ApiError ? err.message : String(err))
          setPanelState('error')
        }
      })
    return () => {
      active = false
    }
  }, [panelAttempt, panelId])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      mutationRequest.current += 1
    }
  }, [])

  const handleDuplicate = async () => {
    if (panelId === null) return
    const request = ++mutationRequest.current
    setDuplicating(true)
    setError(null)
    try {
      const copy = await duplicatePanel(panelId)
      if (!mounted.current || request !== mutationRequest.current) return
      navigate(`/panels/${copy.id}/edit`)
    } catch (err) {
      if (!mounted.current || request !== mutationRequest.current) return
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      if (mounted.current && request === mutationRequest.current) setDuplicating(false)
    }
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const request = ++mutationRequest.current
    setSubmitting(true)
    setError(null)
    try {
      const saved = panelId === null ? await createPanel(values) : await updatePanel(panelId, values)
      if (!mounted.current || request !== mutationRequest.current) return
      allowNavigation()
      navigate(`/panels/${saved.id}/preview`)
    } catch (err) {
      if (!mounted.current || request !== mutationRequest.current) return
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      if (mounted.current && request === mutationRequest.current) setSubmitting(false)
    }
  }

  const heading = panelId === null ? 'Stage new panel' : 'Edit panel'
  const currentPanelState = panelId === null ? 'ready' : loadedPanelId === panelId ? panelState : 'loading'

  if (notFound) return <NotFoundPage />

  if (prerequisiteState !== 'ready' || currentPanelState !== 'ready') {
    return (
      <section className="form-page form-page--wide">
        <PageHeader title={heading} description="Scene direction, framing, output settings and cast." />
        {prerequisiteState === 'loading' && (
          <AsyncMessage kind="loading" aria-busy="true">Loading panel prerequisites...</AsyncMessage>
        )}
        {prerequisiteState === 'error' && (
          <div>
            <AsyncMessage kind="error">
              Could not load panel prerequisites: {prerequisiteError}
            </AsyncMessage>
            <button
              type="button"
              className="btn"
              aria-label="Retry panel prerequisites"
              onClick={() => {
                setPrerequisiteState('loading')
                setPrerequisiteError(null)
                setPrerequisiteAttempt((attempt) => attempt + 1)
              }}
            >
              Retry
            </button>
          </div>
        )}
        {currentPanelState === 'loading' && (
          <AsyncMessage kind="loading" aria-busy="true">Loading panel details...</AsyncMessage>
        )}
        {currentPanelState === 'error' && (
          <div>
            <AsyncMessage kind="error">Could not load panel details: {panelError}</AsyncMessage>
            <button
              type="button"
              className="btn"
              aria-label="Retry panel details"
              onClick={() => {
                setPanelState('loading')
                setPanelError(null)
                setPanelAttempt((attempt) => attempt + 1)
              }}
            >
              Retry
            </button>
          </div>
        )}
      </section>
    )
  }

  if (locked) {
    return (
      <section className="form-page">
        <PageHeader title="Panel locked" />
        <div className="content-stack">
          <Notice>{options.panel_immutability_explanation}</Notice>
          {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
          {duplicating && <AsyncMessage kind="loading">Duplicating panel…</AsyncMessage>}
          <div>
            <button type="button" className="btn btn--primary" disabled={duplicating} aria-busy={duplicating} onClick={() => void handleDuplicate()}>
              Duplicate &amp; edit
            </button>
          </div>
        </div>
      </section>
    )
  }

  if (styles.length === 0) {
    return (
      <section className="form-page">
        <PageHeader title={heading} />
        <EmptyState
          icon="styles"
          title="A style is required"
          description="Define a visual contract before staging a panel."
          action={<Link to="/styles/new" className="btn btn--primary">Create a style</Link>}
        />
      </section>
    )
  }

  if (characters.length === 0) {
    return (
      <section className="form-page">
        <PageHeader title={heading} />
        <EmptyState
          icon="characters"
          title="A character is required"
          description="Add a character before staging a panel."
          action={<Link to="/characters/new" className="btn btn--primary">Create a character</Link>}
        />
      </section>
    )
  }

  if (
    !characters.some((character) => character.has_canonical_ref_set) &&
    (panelId === null || values.cast.length === 0)
  ) {
    return (
      <section className="form-page">
        <PageHeader title={heading} />
        <EmptyState
          icon="gallery"
          title="A canonical reference set is required"
          description="A character needs a canonical reference set before you can stage a panel."
          action={<Link to="/characters" className="btn btn--primary">Manage characters</Link>}
        />
      </section>
    )
  }

  const setCast = (cast: CastMemberInput[]) => setValues((v) => ({ ...v, cast }))

  return (
    <section className="form-page form-page--wide">
      <PageHeader title={heading} description="Scene direction, framing, output settings and cast." />
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {submitting && <AsyncMessage kind="loading">Saving panel…</AsyncMessage>}
      <form className="form-card" onSubmit={handleSubmit} aria-busy={submitting}>
        <fieldset className="form-section">
          <legend>Scene</legend>
        <div className="field">
          <label htmlFor="beat_text">Action</label>
          <textarea
            id="beat_text"
            className="field__textarea--standard"
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
        </fieldset>

        <fieldset className="form-section">
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

        <fieldset className="form-section">
          <legend>Style and output</legend>
          <div className="form-grid">
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

          </div>
        </fieldset>

        <fieldset className="form-section">
          <legend>Cast</legend>
        <div className="field">
          <label id="cast-label">Cast</label>
          <CastSelector
            characters={characters}
            value={values.cast}
            onChange={setCast}
            labelledBy="cast-label"
          />
        </div>
        </fieldset>

        <div className="form-actions">
          <button type="submit" className="btn btn--primary" disabled={submitting}>
            Save and preview
          </button>
          <button
            type="button"
            className="btn"
            disabled={submitting}
            onClick={() =>
              navigate(panelId === null ? '/panels' : `/panels/${panelId}/preview`)
            }
          >
            Cancel
          </button>
        </div>
      </form>
      <ConfirmDialog {...confirmationProps} />
    </section>
  )
}
