/**
 * TypeScript mirrors of the backend's typed Pydantic DTOs
 * (LoreCraft3000/app/schemas.py). Keep these in sync by hand — there is no
 * codegen step, so any backend DTO change must be reflected here.
 *
 * Invariant carried over from the backend: no field here is a content hash
 * (sha256). Images are referenced only by opaque numeric id + a content URL.
 */

export interface ErrorOut {
  message: string
  type: string
}

export interface OptionsSummary {
  models: string[]
  image_sizes: string[]
  aspect_ratios: string[]
  ref_image_roles: string[]
  default_model: string
  default_image_size: string
  daily_spend_cap_cents: number
  spent_today_cents: number
  remaining_today_cents: number
  ref_image_weight_explanation: string
  ref_set_immutability_explanation: string
  panel_immutability_explanation: string
}

export interface Budget {
  daily_spend_cap_cents: number
  spent_today_cents: number
  remaining_today_cents: number
}

export interface Character {
  id: number
  name: string
  slug: string
  lore_md: string
  visual_contract: string
  negative_traits: string
  default_style_id: number | null
  created_at: string
  has_canonical_ref_set: boolean
  avatar_url: string | null
  avatar_initials: string
}

export interface CharacterInput {
  name: string
  slug?: string | null
  lore_md?: string
  visual_contract?: string
  negative_traits?: string
  default_style_id?: number | null
}

export interface Style {
  id: number
  name: string
  style_contract: string
  ref_image_ids: number[]
  created_at: string
}

export interface StyleInput {
  name: string
  style_contract?: string
  ref_image_ids?: number[]
}

export interface RefImage {
  id: number
  ref_set_id: number
  role: string
  weight: number
  quality_flags: string[]
  created_at: string
  content_url: string
}

export interface RefSet {
  id: number
  character_id: number
  version: number
  status: 'draft' | 'canonical' | 'retired'
  created_at: string
  images: RefImage[]
}

export interface RefSetSummary {
  id: number
  character_id: number
  version: number
  status: 'draft' | 'canonical' | 'retired'
  created_at: string
  image_count: number
}

export interface CastMemberInput {
  character_id: number
  role?: string
  prominence?: number
}

export interface CastMember {
  character_id: number
  role: string
  prominence: number
  name: string
  avatar_url: string | null
  avatar_initials: string
}

export interface PanelInput {
  beat_text: string
  camera: string
  framing: string
  mood?: string
  aspect_ratio: string
  cast: CastMemberInput[]
  style_id: number
  model: string
  image_size: string
}

export interface Panel {
  id: number
  beat_text: string
  camera: string
  framing: string
  mood: string
  aspect_ratio: string
  cast: CastMember[]
  style_id: number
  model: string
  image_size: string
  created_at: string
  is_editable: boolean
  generation_count: number
}

export interface GenerationAttachment {
  image_number: number
  character_id: number
  character_name: string
  ref_set_id: number
  ref_set_version: number
  role: string
}

export interface PanelPreview {
  scene_id: number
  model: string
  image_size: string
  prompt: string
  prompt_hash: string
  attachments: GenerationAttachment[]
  warnings: string[]
  estimated_cost_cents: number
  spent_today_cents: number
  remaining_after_cents: number
  can_generate: boolean
  blocked_reason: string | null
}

export interface Candidate {
  id: number
  generation_id: number
  idx: number
  review_status: 'pending' | 'accepted' | 'rejected'
  content_url: string
  created_at: string
}

export interface Generation {
  id: number
  scene_id: number
  model: string
  image_size: string
  aspect_ratio: string
  prompt: string
  prompt_hash: string
  attachments: GenerationAttachment[]
  warnings: string[]
  cost_usd_cents: number
  reserved_cost_usd_cents: number
  actual_cost_usd_cents: number | null
  state: 'pending' | 'succeeded' | 'failed'
  interaction_id: string | null
  error_text: string | null
  completed_at: string | null
  created_at: string
  candidates: Candidate[]
}

export interface GenerationSummary {
  id: number
  scene_id: number
  model: string
  cost_usd_cents: number
  reserved_cost_usd_cents: number
  actual_cost_usd_cents: number | null
  state: 'pending' | 'succeeded' | 'failed'
  error_text: string | null
  completed_at: string | null
  created_at: string
}
