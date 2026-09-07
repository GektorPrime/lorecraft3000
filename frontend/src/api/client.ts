/**
 * Thin typed fetch wrapper for the /api/v1 JSON API. Every function here
 * corresponds 1:1 to a backend route in app/routes/api_v1.py.
 *
 * Errors: the backend returns a consistent envelope on failure —
 * `{"detail": {"message": string, "type": string}}` — which this module
 * surfaces as an ApiError so callers can show `error.message` directly and
 * branch on `error.type` when useful (e.g. "SceneImmutableError").
 */

import type {
  BaseStage,
  BaseStageGeneratedInput,
  BaseStagePreview,
  Budget,
  Candidate,
  Character,
  CharacterInput,
  GalleryItem,
  Generation,
  GenerationSummary,
  OptionsSummary,
  Scene,
  SceneInput,
  ScenePreview,
  SceneSummary,
  RefImage,
  RefSet,
  RefSetSummary,
  Style,
  StyleInput,
} from './types'

const BASE = '/api/v1'

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export class ApiError extends Error {
  type: string
  status: number

  constructor(message: string, type: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.type = type
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { headers: initHeaders, signal: initSignal, ...rest } = init ?? {}
  const headers = { ...(initHeaders ?? {}) } as Record<string, string>
  if (!(rest.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  headers['X-Timezone'] = browserTimezone()
  // Laptop sleep can leave a fetch hanging forever (no resolve nor reject);
  // bound it so OptionsProvider and other pages can show the Retry UI and
  // recover without a server restart. Callers that need a custom abort
  // signal can pass one.
  let timeoutId: number | undefined
  let signal = initSignal
  if (!signal) {
    const controller = new AbortController()
    signal = controller.signal
    timeoutId = window.setTimeout(
      () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
      15_000,
    )
  }
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers,
      signal,
      ...rest,
    })
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId)
  }
  if (response.status === 204) {
    return undefined as T
  }
  const isJson = response.headers.get('content-type')?.includes('application/json')
  const body = isJson ? await response.json() : undefined
  if (!response.ok) {
    const detail = body?.detail
    throw new ApiError(
      detail?.message ?? response.statusText,
      detail?.type ?? 'UnknownError',
      response.status,
    )
  }
  if (!isJson) {
    throw new ApiError(
      'The API returned an unexpected non-JSON response. Check the forwarded port and tunnel access settings.',
      'InvalidResponseError',
      response.status,
    )
  }
  return body as T
}

function json(method: string, body: unknown): RequestInit {
  return { method, body: JSON.stringify(body) }
}

// ---------------------------------------------------------------------------
// options / budget
// ---------------------------------------------------------------------------

export const getOptionsSummary = () => request<OptionsSummary>('/options/summary')
export const getBudget = () => request<Budget>('/budget')

// ---------------------------------------------------------------------------
// base stages
// ---------------------------------------------------------------------------

export const listBaseStages = () => request<BaseStage[]>('/base-stages')
export const listArchivedBaseStages = () => request<BaseStage[]>('/base-stages/archived')
export const getBaseStage = (id: number) => request<BaseStage>(`/base-stages/${id}`)
export const uploadBaseStage = (file: File, description: string, targets: string[]) => {
  const form = new FormData()
  form.append('image', file)
  form.append('description', description)
  form.append('targets', JSON.stringify(targets))
  return request<BaseStage>('/base-stages/upload', { method: 'POST', body: form })
}
export const archiveBaseStage = (id: number) =>
  request<void>(`/base-stages/${id}`, { method: 'DELETE' })
export const restoreBaseStage = (id: number) =>
  request<BaseStage>(`/base-stages/${id}/restore`, { method: 'POST' })

// Generated Base Stages: a draft is composed first, generated, and only becomes
// selectable by scenes once one candidate is explicitly published.
export const createGeneratedBaseStage = (payload: BaseStageGeneratedInput) =>
  request<BaseStage>('/base-stages/generated', json('POST', payload))
export const updateBaseStage = (id: number, payload: BaseStageGeneratedInput) =>
  request<BaseStage>(`/base-stages/${id}`, json('PUT', payload))
export const duplicateBaseStage = (id: number) =>
  request<BaseStage>(`/base-stages/${id}/duplicate`, { method: 'POST' })
export const previewBaseStage = (id: number) =>
  request<BaseStagePreview>(`/base-stages/${id}/preview`)
export const listBaseStageGenerations = (id: number) =>
  request<GenerationSummary[]>(`/base-stages/${id}/generations`)
export const listBaseStageScenes = (id: number) =>
  request<SceneSummary[]>(`/base-stages/${id}/scenes`)
export const generateBaseStage = (id: number, expectedPromptHash: string) => {
  const controller = new AbortController()
  const t = window.setTimeout(
    () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
    180_000,
  )
  controller.signal.addEventListener('abort', () => window.clearTimeout(t), { once: true })
  return request<Generation>(`/base-stages/${id}/generate`, {
    method: 'POST',
    signal: controller.signal,
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify({ expected_prompt_hash: expectedPromptHash }),
  }).finally(() => window.clearTimeout(t))
}
export const publishBaseStage = (id: number, candidateId: number) =>
  request<BaseStage>(`/base-stages/${id}/publish`, json('POST', { candidate_id: candidateId }))

// ---------------------------------------------------------------------------
// characters
// ---------------------------------------------------------------------------

export const listCharacters = () => request<Character[]>('/characters')
export const listArchivedCharacters = () => request<Character[]>('/characters/archived')
export const getCharacter = (id: number) => request<Character>(`/characters/${id}`)
export const createCharacter = (payload: CharacterInput) =>
  request<Character>('/characters', json('POST', payload))
export const updateCharacter = (id: number, payload: CharacterInput) =>
  request<Character>(`/characters/${id}`, json('PUT', payload))
// Archive (soft-delete): the character stays linked to existing scenes but is
// hidden from lists/pickers. restoreCharacter reverses it.
export const archiveCharacter = (id: number) =>
  request<void>(`/characters/${id}`, { method: 'DELETE' })
export const restoreCharacter = (id: number) =>
  request<Character>(`/characters/${id}/restore`, { method: 'POST' })

// ---------------------------------------------------------------------------
// styles
// ---------------------------------------------------------------------------

export const listStyles = () => request<Style[]>('/styles')
export const listArchivedStyles = () => request<Style[]>('/styles/archived')
export const getStyle = (id: number) => request<Style>(`/styles/${id}`)
export const createStyle = (payload: StyleInput) => request<Style>('/styles', json('POST', payload))
export const updateStyle = (id: number, payload: StyleInput) =>
  request<Style>(`/styles/${id}`, json('PUT', payload))
// Archive (soft-delete): the style stays on existing scenes but is hidden from
// lists/pickers. restoreStyle reverses it. The seeded default style cannot be
// archived (the backend returns 409).
export const archiveStyle = (id: number) =>
  request<void>(`/styles/${id}`, { method: 'DELETE' })
export const restoreStyle = (id: number) =>
  request<Style>(`/styles/${id}/restore`, { method: 'POST' })

// ---------------------------------------------------------------------------
// reference sets / images
// ---------------------------------------------------------------------------

export const listRefSets = (characterId: number) =>
  request<RefSetSummary[]>(`/characters/${characterId}/ref-sets`)
export const createRefSetDraft = (characterId: number) =>
  request<RefSet>(`/characters/${characterId}/ref-sets`, { method: 'POST' })
export const getRefSet = (refSetId: number) => request<RefSet>(`/ref-sets/${refSetId}`)
export const copyRefSet = (refSetId: number) =>
  request<RefSet>(`/ref-sets/${refSetId}/copy`, { method: 'POST' })
export const promoteRefSet = (refSetId: number) =>
  request<RefSet>(`/ref-sets/${refSetId}/promote`, { method: 'POST' })

export const uploadRefImage = (refSetId: number, file: File, role: string) => {
  const form = new FormData()
  form.append('role', role)
  form.append('image', file)
  return request<RefImage>(`/ref-sets/${refSetId}/images`, { method: 'POST', body: form })
}
export const reRoleRefImage = (refSetId: number, imageId: number, role: string) =>
  request<RefImage>(`/ref-sets/${refSetId}/images/${imageId}`, json('PATCH', { role }))
export const removeRefImage = (refSetId: number, imageId: number) =>
  request<void>(`/ref-sets/${refSetId}/images/${imageId}`, { method: 'DELETE' })

// ---------------------------------------------------------------------------
// scenes
// ---------------------------------------------------------------------------

export const listScenes = () => request<Scene[]>('/scenes')
export const getScene = (id: number) => request<Scene>(`/scenes/${id}`)
export const createScene = (payload: SceneInput) => request<Scene>('/scenes', json('POST', payload))
export const updateScene = (id: number, payload: SceneInput) =>
  request<Scene>(`/scenes/${id}`, json('PUT', payload))
export const updateSceneModel = (id: number, model: string) =>
  request<Scene>(`/scenes/${id}/model`, json('PATCH', { model }))
export const duplicateScene = (id: number) =>
  request<Scene>(`/scenes/${id}/duplicate`, { method: 'POST' })
// Scenes are hard-deleted (not archived): this permanently removes the scene
// and its entire generation history.
export const deleteScene = (id: number) =>
  request<void>(`/scenes/${id}`, { method: 'DELETE' })
export const previewScene = (id: number) => request<ScenePreview>(`/scenes/${id}/preview`)
export const listSceneGenerations = (id: number) =>
  request<GenerationSummary[]>(`/scenes/${id}/generations`)
export const generateScene = (id: number, expectedPromptHash: string) => {
  const controller = new AbortController()
  const t = window.setTimeout(
    () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
    180_000,
  )
  controller.signal.addEventListener('abort', () => window.clearTimeout(t), { once: true })
  return request<Generation>(`/scenes/${id}/generate`, {
    method: 'POST',
    signal: controller.signal,
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify({ expected_prompt_hash: expectedPromptHash }),
  }).finally(() => window.clearTimeout(t))
}

// ---------------------------------------------------------------------------
// generations / candidates
// ---------------------------------------------------------------------------

export const reviewCandidate = (id: number, verdict: 'accepted' | 'rejected') =>
  request<Candidate>(`/candidates/${id}/review`, json('POST', { verdict }))

// Edit an existing candidate with a natural-language instruction. Produces a
// new candidate under a child generation on the same provider/model, keeping
// character identity anchored to the scene's canonical references.
export const editCandidate = (id: number, instruction: string) => {
  const controller = new AbortController()
  const t = window.setTimeout(
    () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
    180_000,
  )
  controller.signal.addEventListener('abort', () => window.clearTimeout(t), { once: true })
  return request<Generation>(`/candidates/${id}/edit`, {
    method: 'POST',
    signal: controller.signal,
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify({ instruction }),
  }).finally(() => window.clearTimeout(t))
}

// ---------------------------------------------------------------------------
// gallery
// ---------------------------------------------------------------------------

export const getGallery = () => request<GalleryItem[]>('/gallery')
