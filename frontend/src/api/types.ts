/**
 * TypeScript mirrors of the backend's Pydantic DTOs — GENERATED, not typed by
 * hand. The source of truth is the backend's OpenAPI document, snapshotted at
 * frontend/openapi.json by app/scripts/generate_openapi.py and turned into
 * types by `npm run types` (openapi-typescript) into
 * frontend/src/api/generated/types.d.ts.
 *
 * Keep the wire contract stable: a backend DTO field change must be committed
 * together with a regenerated snapshot, or `npm run build` fails loudly.
 *
 * Invariant carried over from the backend: no field is a content hash (sha256).
 * Images are referenced only by opaque numeric id + a content URL.
 */

import type { components } from './generated/types'

export type OptionsSummary = components['schemas']['OptionsSummary']
export type Budget = components['schemas']['Budget']
export type Character = components['schemas']['Character']
export type CharacterInput = components['schemas']['CharacterInput']
export type BaseStage = components['schemas']['BaseStage']
export type BaseStageTarget = components['schemas']['BaseStageTarget']
export type Style = components['schemas']['Style']
export type StyleInput = components['schemas']['StyleInput']
export type RefImage = components['schemas']['RefImage']
export type RefSet = components['schemas']['RefSet']
export type RefSetSummary = components['schemas']['RefSetSummary']
export type CastMemberInput = components['schemas']['CastMemberInput']
export type CastMember = components['schemas']['CastMember']
export type PanelInput = components['schemas']['PanelInput']
export type Panel = components['schemas']['Panel']
export type PanelBaseStage = components['schemas']['PanelBaseStage']
export type PanelBaseStageTarget = components['schemas']['PanelBaseStageTarget']
export type GenerationAttachment = components['schemas']['GenerationAttachment']
export type PanelPreview = components['schemas']['PanelPreview']
export type Candidate = components['schemas']['Candidate']
export type Generation = components['schemas']['Generation']
export type GenerationSummary = components['schemas']['GenerationSummary']
export type GalleryItem = components['schemas']['GalleryItem']
