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
  Budget,
  Candidate,
  Character,
  CharacterInput,
  GalleryItem,
  Generation,
  GenerationSummary,
  OptionsSummary,
  Panel,
  PanelInput,
  PanelPreview,
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
  const { headers: initHeaders, ...rest } = init ?? {}
  const headers = { ...(initHeaders ?? {}) } as Record<string, string>
  if (!(rest.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  headers['X-Timezone'] = browserTimezone()
  const response = await fetch(`${BASE}${path}`, {
    headers,
    ...rest,
  })
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
// characters
// ---------------------------------------------------------------------------

export const listCharacters = () => request<Character[]>('/characters')
export const listArchivedCharacters = () => request<Character[]>('/characters/archived')
export const getCharacter = (id: number) => request<Character>(`/characters/${id}`)
export const createCharacter = (payload: CharacterInput) =>
  request<Character>('/characters', json('POST', payload))
export const updateCharacter = (id: number, payload: CharacterInput) =>
  request<Character>(`/characters/${id}`, json('PUT', payload))
// Archive (soft-delete): the character stays linked to existing panels but is
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
// Archive (soft-delete): the style stays on existing panels but is hidden from
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
// panels
// ---------------------------------------------------------------------------

export const listPanels = () => request<Panel[]>('/panels')
export const getPanel = (id: number) => request<Panel>(`/panels/${id}`)
export const createPanel = (payload: PanelInput) => request<Panel>('/panels', json('POST', payload))
export const updatePanel = (id: number, payload: PanelInput) =>
  request<Panel>(`/panels/${id}`, json('PUT', payload))
export const updatePanelModel = (id: number, model: string) =>
  request<Panel>(`/panels/${id}/model`, json('PATCH', { model }))
export const duplicatePanel = (id: number) =>
  request<Panel>(`/panels/${id}/duplicate`, { method: 'POST' })
// Panels are hard-deleted (not archived): this permanently removes the panel
// and its entire generation history.
export const deletePanel = (id: number) =>
  request<void>(`/panels/${id}`, { method: 'DELETE' })
export const previewPanel = (id: number) => request<PanelPreview>(`/panels/${id}/preview`)
export const listPanelGenerations = (id: number) =>
  request<GenerationSummary[]>(`/panels/${id}/generations`)
export const generatePanel = (id: number, expectedPromptHash: string) =>
  request<Generation>(`/panels/${id}/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify({ expected_prompt_hash: expectedPromptHash }),
  })

// ---------------------------------------------------------------------------
// generations / candidates
// ---------------------------------------------------------------------------

export const reviewCandidate = (id: number, verdict: 'accepted' | 'rejected') =>
  request<Candidate>(`/candidates/${id}/review`, json('POST', { verdict }))

// Edit an existing candidate with a natural-language instruction. Produces a
// new candidate under a child generation on the same provider/model, keeping
// character identity anchored to the panel's canonical references.
export const editCandidate = (id: number, instruction: string) =>
  request<Generation>(`/candidates/${id}/edit`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify({ instruction }),
  })

// ---------------------------------------------------------------------------
// gallery
// ---------------------------------------------------------------------------

export const getGallery = () => request<GalleryItem[]>('/gallery')
