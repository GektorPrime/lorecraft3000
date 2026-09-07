import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ApiError,
  createScene,
  duplicateScene,
  getScene,
  listBaseStages,
  listCharacters,
  listStyles,
  updateScene,
} from '../../api/client'
import { useOptions } from '../../api/useOptions'
import type {
  BaseStage,
  CastMemberInput,
  Character,
  SceneBaseStage,
  SceneInput,
  Style,
} from '../../api/types'
import { BaseStageCastMapper } from '../../components/BaseStageCastMapper'
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

const EMPTY = (defaults: { model: string; image_size: string }): SceneInput => ({
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

const snapshot = (
  values: SceneInput,
  useBaseStage: boolean,
  selectedStageId: number | null,
  stagedCast: CastMemberInput[],
) =>
  JSON.stringify({
    beat_text: values.beat_text,
    camera: values.camera,
    framing: values.framing,
    mood: values.mood,
    aspect_ratio: values.aspect_ratio,
    cast: values.cast.map(({ character_id, role, prominence, base_stage_target_id }) => ({
      character_id,
      role,
      prominence,
      base_stage_target_id,
    })),
    style_id: values.style_id,
    model: values.model,
    image_size: values.image_size,
    useBaseStage,
    selectedStageId,
    stagedCast,
  })

export function SceneFormPage() {
  const { id } = useParams()
  if (id === undefined) return <SceneForm key="new" sceneId={null} />
  return (
    <RouteIdGuard>{(sceneId) => <SceneForm key={sceneId} sceneId={sceneId} />}</RouteIdGuard>
  )
}

function SceneForm({ sceneId }: { sceneId: number | null }) {
  const navigate = useNavigate()
  const options = useOptions()

  const [values, setValues] = useState<SceneInput>(() =>
    EMPTY({ model: options.default_model, image_size: options.default_image_size }),
  )
  const [characters, setCharacters] = useState<Character[]>([])
  const [styles, setStyles] = useState<Style[]>([])
  const [baseStages, setBaseStages] = useState<(BaseStage | SceneBaseStage)[]>([])
  const [useBaseStage, setUseBaseStage] = useState(false)
  const [selectedStageId, setSelectedStageId] = useState<number | null>(null)
  const [stagedCast, setStagedCast] = useState<CastMemberInput[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  const [prerequisiteState, setPrerequisiteState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [prerequisiteError, setPrerequisiteError] = useState<string | null>(null)
  const [stylesError, setStylesError] = useState<string | null>(null)
  const [baseStagesError, setBaseStagesError] = useState<string | null>(null)
  const [prerequisiteAttempt, setPrerequisiteAttempt] = useState(0)
  const [sceneState, setSceneState] = useState<'loading' | 'ready' | 'error'>(
    sceneId === null ? 'ready' : 'loading',
  )
  const [loadedSceneId, setLoadedSceneId] = useState<number | null>(sceneId)
  const [sceneError, setSceneError] = useState<string | null>(null)
  const [sceneAttempt, setSceneAttempt] = useState(0)
  const [locked, setLocked] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [baseline, setBaseline] = useState<string | null>(null)
  const { allowNavigation, confirmationProps } = useUnsavedChanges(
    baseline !== null && snapshot(values, useBaseStage, selectedStageId, stagedCast) !== baseline,
  )
  const mounted = useRef(true)
  const mutationRequest = useRef(0)

  usePageTitle(
    sceneId === null
      ? 'New Scene'
      : sceneState === 'ready' && loadedSceneId === sceneId
        ? `Edit Scene #${sceneId}`
        : 'Edit Scene',
  )

  useEffect(() => {
    let active = true
    Promise.allSettled([listCharacters(), listStyles(), listBaseStages()])
      .then(([characterResult, styleResult, stageResult]) => {
        if (!active) return
        if (characterResult.status === 'rejected') {
          setPrerequisiteError(characterResult.reason instanceof ApiError
            ? characterResult.reason.message
            : String(characterResult.reason))
          setPrerequisiteState('error')
          return
        }
        const styleList = styleResult.status === 'fulfilled' ? styleResult.value : []
        setCharacters(characterResult.value)
        setStyles(styleList)
        setStylesError(styleResult.status === 'rejected'
          ? styleResult.reason instanceof ApiError ? styleResult.reason.message : String(styleResult.reason)
          : null)
        setBaseStages((current) => {
          const activeStages = stageResult.status === 'fulfilled' ? stageResult.value : []
          const linkedStage = current.find((stage) => !('dimensions' in stage))
          return linkedStage && !activeStages.some((stage) => stage.id === linkedStage.id)
            ? [...activeStages, linkedStage]
            : activeStages
        })
        setBaseStagesError(stageResult.status === 'rejected'
          ? stageResult.reason instanceof ApiError ? stageResult.reason.message : String(stageResult.reason)
          : null)
        setValues((v) => v.style_id === 0 && styleList[0]
          ? { ...v, style_id: styleList[0].id }
          : v)
        if (sceneId === null) {
          const hydratedValues = EMPTY({
            model: options.default_model,
            image_size: options.default_image_size,
          })
          if (styleList[0]) hydratedValues.style_id = styleList[0].id
          setBaseline(snapshot(hydratedValues, false, null, []))
        }
        setPrerequisiteState('ready')
      })
    return () => {
      active = false
    }
  }, [options.default_image_size, options.default_model, sceneId, prerequisiteAttempt])

  useEffect(() => {
    if (sceneId === null) return
    let active = true
    getScene(sceneId)
      .then((scene) => {
        if (!active) return
        setLoadedSceneId(sceneId)
        if (!scene.is_editable) {
          setLocked(true)
          setSceneState('ready')
          return
        }
        setLocked(false)
        const hydratedValues: SceneInput = {
          beat_text: scene.base_stage ? '' : scene.beat_text,
          camera: scene.base_stage ? '' : scene.camera,
          framing: scene.base_stage ? '' : scene.framing,
          mood: scene.base_stage ? '' : scene.mood,
          aspect_ratio: scene.aspect_ratio,
          cast: scene.base_stage ? [] : scene.cast.map((m) => ({
            character_id: m.character_id,
            role: m.role,
            prominence: m.prominence,
            base_stage_target_id: m.base_stage_target_id,
          })),
          style_id: scene.style_id ?? 0,
          model: scene.model,
          image_size: scene.image_size,
        }
        const hydratedStagedCast = scene.base_stage
          ? [...scene.cast].sort((a, b) => {
              const positions = new Map(scene.base_stage!.targets.map((target) => [target.id, target.position]))
              return (positions.get(a.base_stage_target_id ?? -1) ?? 0) - (positions.get(b.base_stage_target_id ?? -1) ?? 0)
            }).map((member) => ({
              character_id: member.character_id,
              role: '',
              prominence: member.prominence,
              base_stage_target_id: member.base_stage_target_id,
            }))
          : []
        const staged = scene.base_stage !== null
        setUseBaseStage(staged)
        setSelectedStageId(scene.base_stage_id)
        setStagedCast(hydratedStagedCast)
        const linkedStage = scene.base_stage
        if (linkedStage) {
          setBaseStages((current) => current.some((stage) => stage.id === linkedStage.id)
            ? current
            : [...current, linkedStage])
        }
        setBaseline(snapshot(hydratedValues, staged, scene.base_stage_id, hydratedStagedCast))
        setValues(hydratedValues)
        setSceneState('ready')
      })
      .catch((err) => {
        if (!active) return
        setLoadedSceneId(sceneId)
        if (err instanceof ApiError && err.status === 404) setNotFound(true)
        else {
          setSceneError(err instanceof ApiError ? err.message : String(err))
          setSceneState('error')
        }
      })
    return () => {
      active = false
    }
  }, [sceneAttempt, sceneId])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      mutationRequest.current += 1
    }
  }, [])

  const handleDuplicate = async () => {
    if (sceneId === null) return
    const request = ++mutationRequest.current
    setDuplicating(true)
    setError(null)
    try {
      const copy = await duplicateScene(sceneId)
      if (!mounted.current || request !== mutationRequest.current) return
      navigate(`/scenes/${copy.id}/edit`)
    } catch (err) {
      if (!mounted.current || request !== mutationRequest.current) return
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      if (mounted.current && request === mutationRequest.current) setDuplicating(false)
    }
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const selectedStage = baseStages.find((stage) => stage.id === selectedStageId)
    if (useBaseStage && (!selectedStage || stagedCast.length !== selectedStage.targets.length)) {
      setError(selectedStage ? 'Assign a character to every Base Stage target.' : 'Select a Base Stage.')
      return
    }
    const request = ++mutationRequest.current
    setSubmitting(true)
    setError(null)
    try {
      const payload: SceneInput = useBaseStage && selectedStage
        ? {
            base_stage_id: selectedStage.id,
            beat_text: null,
            camera: null,
            framing: null,
            mood: null,
            aspect_ratio: selectedStage.aspect_ratio,
            cast: stagedCast.map((member) => ({ ...member, role: '' })),
            style_id: values.style_id || null,
            model: values.model,
            image_size: values.image_size,
          }
        : { ...values, base_stage_id: null }
      const saved = sceneId === null ? await createScene(payload) : await updateScene(sceneId, payload)
      if (!mounted.current || request !== mutationRequest.current) return
      allowNavigation()
      navigate(`/scenes/${saved.id}/preview`)
    } catch (err) {
      if (!mounted.current || request !== mutationRequest.current) return
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      if (mounted.current && request === mutationRequest.current) setSubmitting(false)
    }
  }

  const heading = sceneId === null ? 'Stage new scene' : 'Edit scene'
  const currentSceneState = sceneId === null ? 'ready' : loadedSceneId === sceneId ? sceneState : 'loading'

  if (notFound) return <NotFoundPage />

  if (prerequisiteState !== 'ready' || currentSceneState !== 'ready') {
    return (
      <section className="form-page form-page--wide">
        <PageHeader title={heading} description="Scene direction, framing, output settings and cast." />
        {prerequisiteState === 'loading' && (
          <AsyncMessage kind="loading" aria-busy="true">Loading scene prerequisites...</AsyncMessage>
        )}
        {prerequisiteState === 'error' && (
          <div>
            <AsyncMessage kind="error">
              Could not load scene prerequisites: {prerequisiteError}
            </AsyncMessage>
            <button
              type="button"
              className="btn"
              aria-label="Retry scene prerequisites"
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
        {currentSceneState === 'loading' && (
          <AsyncMessage kind="loading" aria-busy="true">Loading scene details...</AsyncMessage>
        )}
        {currentSceneState === 'error' && (
          <div>
            <AsyncMessage kind="error">Could not load scene details: {sceneError}</AsyncMessage>
            <button
              type="button"
              className="btn"
              aria-label="Retry scene details"
              onClick={() => {
                setSceneState('loading')
                setSceneError(null)
                setSceneAttempt((attempt) => attempt + 1)
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
        <PageHeader title="Scene locked" />
        <div className="content-stack">
          <Notice>{options.scene_immutability_explanation}</Notice>
          {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
          {duplicating && <AsyncMessage kind="loading">Duplicating scene…</AsyncMessage>}
          <div>
            <button type="button" className="btn btn--primary" disabled={duplicating} aria-busy={duplicating} onClick={() => void handleDuplicate()}>
              Duplicate &amp; edit
            </button>
          </div>
        </div>
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
          description="Add a character before staging a scene."
          action={<Link to="/characters/new" className="btn btn--primary">Create a character</Link>}
        />
      </section>
    )
  }

  if (
    !characters.some((character) => character.has_canonical_ref_set) &&
    (sceneId === null || values.cast.length === 0)
  ) {
    return (
      <section className="form-page">
        <PageHeader title={heading} />
        <EmptyState
          icon="gallery"
          title="A canonical reference set is required"
          description="A character needs a canonical reference set before you can stage a scene."
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
      {submitting && <AsyncMessage kind="loading">Saving scene…</AsyncMessage>}
      <form className="form-card" onSubmit={handleSubmit} aria-busy={submitting}>
        <div className="field scene-mode-toggle">
          <label>
            <input
              type="checkbox"
              checked={useBaseStage}
              onChange={(event) => {
                setUseBaseStage(event.target.checked)
                if (!event.target.checked) {
                  setValues((v) =>
                    (v.style_id === 0 || v.style_id === null) && styles[0]
                      ? { ...v, style_id: styles[0].id }
                      : v,
                  )
                }
                setError(null)
              }}
            />{' '}
            Use a base stage
          </label>
          <span className="field__hint">
            Start from a reusable source composition and map its ordered targets to characters.
          </span>
        </div>

        {!useBaseStage && stylesError && (
          <div>
            <AsyncMessage kind="error">Could not load styles: {stylesError}</AsyncMessage>
            <button
              type="button"
              className="btn"
              aria-label="Retry scene prerequisites"
              onClick={() => {
                setPrerequisiteState('loading')
                setPrerequisiteAttempt((attempt) => attempt + 1)
              }}
            >
              Retry
            </button>
          </div>
        )}
        {!useBaseStage && !stylesError && styles.length === 0 && (
          <EmptyState
            icon="styles"
            title="A style is required"
            description="Define a visual contract before staging a scene, or use a Base Stage."
            action={<Link to="/styles/new" className="btn btn--primary">Create a style</Link>}
            compact
          />
        )}

        {!useBaseStage && !stylesError && styles.length > 0 && <>
        <fieldset className="form-section">
          <legend>Scene</legend>
        <div className="field">
          <label htmlFor="beat_text">Action</label>
          <textarea
            id="beat_text"
            className="field__textarea--standard"
            required
            aria-describedby="beat_text-hint"
            value={values.beat_text ?? ''}
            onChange={(e) => setValues((v) => ({ ...v, beat_text: e.target.value }))}
          />
          <span className="field__hint" id="beat_text-hint">
            What is happening in this scene — the beat/action, not the camera. Example: "Elias
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
              value={values.camera ?? ''}
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
              value={values.framing ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, framing: e.target.value }))}
            />
            <span className="field__hint" id="framing-hint">
              How tightly the shot is cropped — what remains visible in frame, not the viewer's
              angle. Example: "medium close-up, head and shoulders only" or "wide shot, full room
              visible".
            </span>
          </div>
        </fieldset>
        </>}

        <fieldset className="form-section">
          <legend>Style and output</legend>
          <div className="form-grid">
        {!useBaseStage && !stylesError && styles.length > 0 && <>
        <div className="field">
          <label htmlFor="mood">Mood</label>
          <input
            id="mood"
            type="text"
            aria-describedby="mood-hint"
            value={values.mood ?? ''}
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
            cinematic scene; "1:1" for a square scene; "3:4" for a tall portrait scene.
          </span>
        </div>

        </>}

        {!stylesError && styles.length > 0 && <div className="field">
          <label htmlFor="style_id">Style</label>
          <select
            id="style_id"
            aria-describedby="style_id-hint"
            value={values.style_id ?? 0}
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
        </div>}

        {useBaseStage && (
          <div className="field">
            <label htmlFor="inherited_aspect_ratio">Inherited aspect ratio</label>
            <input
              id="inherited_aspect_ratio"
              type="text"
              readOnly
              value={baseStages.find((stage) => stage.id === selectedStageId)?.aspect_ratio ?? 'Select a Base Stage'}
              aria-describedby="inherited_aspect_ratio-hint"
            />
            <span className="field__hint" id="inherited_aspect_ratio-hint">
              The source image fixes the scene aspect ratio.
            </span>
          </div>
        )}

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
            "1K" for a quick draft, "2K" or "4K" for a final scene.
          </span>
        </div>

          </div>
        </fieldset>

        {useBaseStage && (
          <fieldset className="form-section">
            <legend>Base Stage composition</legend>
            {baseStagesError ? (
              <div>
                <AsyncMessage kind="error">Could not load Base Stages: {baseStagesError}</AsyncMessage>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setPrerequisiteState('loading')
                    setPrerequisiteAttempt((attempt) => attempt + 1)
                  }}
                >
                  Retry Base Stages
                </button>
              </div>
            ) : baseStages.every((stage) => stage.state !== 'ready' || stage.targets.length === 0) ? (
              <EmptyState
                icon="baseStages"
                title="No usable Base Stages"
                description="Upload a ready Base Stage with at least one target. Stages without targets cannot map characters."
                action={<Link to="/base-stages/upload" className="btn btn--primary">Upload base stage</Link>}
                compact
              />
            ) : (
              <BaseStageCastMapper
                stages={baseStages}
                characters={characters}
                selectedStageId={selectedStageId}
                value={stagedCast}
                onStageChange={(stageId) => {
                  if (stageId === selectedStageId) return
                  setSelectedStageId(stageId)
                  setStagedCast([])
                  const stage = baseStages.find((candidate) => candidate.id === stageId)
                  if (stage) {
                    setValues((current) => ({
                      ...current,
                      aspect_ratio: stage.aspect_ratio,
                      style_id: stage.style_id ?? current.style_id,
                    }))
                  }
                  setError(null)
                }}
                onChange={setStagedCast}
              />
            )}
          </fieldset>
        )}

        {!useBaseStage && !stylesError && styles.length > 0 && (
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
        )}

        <div className="form-actions">
          <button
            type="submit"
            className="btn btn--primary"
            disabled={submitting || (!useBaseStage && (stylesError !== null || styles.length === 0))}
          >
            Save and preview
          </button>
          <button
            type="button"
            className="btn"
            disabled={submitting}
            onClick={() =>
              navigate(sceneId === null ? '/scenes' : `/scenes/${sceneId}/preview`)
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
