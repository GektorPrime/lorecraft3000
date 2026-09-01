import type { Character, CastMemberInput } from '../api/types'
import { Avatar } from './Avatar'

interface CastSelectorProps {
  characters: Character[]
  value: CastMemberInput[]
  onChange: (next: CastMemberInput[]) => void
  /** id of an external <label>/heading that names this whole widget. */
  labelledBy?: string
}

/**
 * Visual, ordered cast picker: add/remove characters by clicking their
 * avatar/name card, reorder with up/down buttons, and edit each member's
 * staging role text + prominence — never a raw character-ID field
 * (issue #15).
 *
 * Two distinct, visible (not placeholder-only) explanations are provided so
 * every field is described, not just hinted at via input placeholder text:
 *   - "Cast order" (#cast-order-hint): what the up/down reorder controls
 *     actually affect.
 *   - "Staging" (#staging-hint): what the free-text role field means.
 * Both are wired up via aria-describedby on the relevant controls.
 */
export function CastSelector({ characters, value, onChange, labelledBy }: CastSelectorProps) {
  const selectedIds = new Set(value.map((m) => m.character_id))
  const available = characters.filter((c) => !selectedIds.has(c.id))
  const byId = new Map(characters.map((c) => [c.id, c]))

  const add = (characterId: number) => {
    onChange([...value, { character_id: characterId, role: '', prominence: value.length + 1 }])
  }
  const remove = (characterId: number) => {
    onChange(value.filter((m) => m.character_id !== characterId))
  }
  const move = (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= value.length) return
    const next = [...value]
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next)
  }
  const updateRole = (characterId: number, role: string) => {
    onChange(value.map((m) => (m.character_id === characterId ? { ...m, role } : m)))
  }
  const updateProminence = (characterId: number, prominence: number) => {
    onChange(value.map((m) => (m.character_id === characterId ? { ...m, prominence } : m)))
  }

  return (
    <div role="group" aria-labelledby={labelledBy}>
      <p className="field__hint" id="cast-order-hint">
        <strong>Cast order:</strong> the list order below sets who is introduced first in the
        reference declaration sent to the model and gets first pick of a canonical reference
        slot. Reorder with the ↑/↓ buttons. Example: put your two leads first if the panel has
        more characters than reference slots. Order does not change a character's position or
        size in the generated artwork.
      </p>
      <p className="field__hint" id="prominence-hint">
        <strong>Prominence:</strong> gives higher-prominence cast members priority for extra
        reference-image slots once every character already has one. Example: a prominence of 3 for
        the hero and 1 for a background character means the hero gets extra reference slots
        first. It does not change size, position, or importance in the generated art.
      </p>
      <p className="field__hint" id="staging-hint">
        <strong>Staging:</strong> a short free-text description of what this character is doing
        or where they stand in this specific panel. It is sent to the model as part of the scene
        description. Example: "kneeling by the fire" or "reaching for the door".
      </p>
      {value.length === 0 && <p className="field__hint">No cast selected yet — add one below.</p>}
      <ol className="cast-list" aria-describedby="cast-order-hint">
        {value.map((member, index) => {
          const character = byId.get(member.character_id)
          return (
            <li className="cast-list__item" key={member.character_id}>
              <Avatar
                url={character?.avatar_url ?? null}
                initials={character?.avatar_initials ?? '?'}
                name={character?.name ?? `#${member.character_id}`}
                size={32}
              />
              <strong>{character?.name ?? `Unknown #${member.character_id}`}</strong>
              <input
                type="text"
                aria-label={`Staging role for ${character?.name ?? member.character_id}`}
                aria-describedby="staging-hint"
                placeholder={'Staging role, e.g. "kneeling by the fire"'}
                value={member.role ?? ''}
                onChange={(e) => updateRole(member.character_id, e.target.value)}
              />
              <input
                type="number"
                min={1}
                aria-label={`Prominence for ${character?.name ?? member.character_id}`}
                aria-describedby="prominence-hint"
                value={member.prominence ?? 1}
                onChange={(e) => updateProminence(member.character_id, Number(e.target.value) || 1)}
                style={{ width: '4.5em' }}
              />
              <button
                type="button"
                className="btn"
                aria-describedby="cast-order-hint"
                onClick={() => move(index, -1)}
                disabled={index === 0}
              >
                ↑
              </button>
              <button
                type="button"
                className="btn"
                aria-describedby="cast-order-hint"
                onClick={() => move(index, 1)}
                disabled={index === value.length - 1}
              >
                ↓
              </button>
              <button type="button" className="btn btn--danger" onClick={() => remove(member.character_id)}>
                Remove
              </button>
            </li>
          )
        })}
      </ol>

      {available.length > 0 && (
        <div style={{ marginTop: '0.75rem' }}>
          <p className="field__hint">Add to cast:</p>
          <div className="btn-row" style={{ marginTop: 0 }}>
            {available.map((character) => (
              <button
                key={character.id}
                type="button"
                className="btn"
                disabled={!character.has_canonical_ref_set}
                onClick={() => add(character.id)}
              >
                <Avatar
                  url={character.avatar_url}
                  initials={character.avatar_initials}
                  name={character.name}
                  size={24}
                />
                {character.name}
                {!character.has_canonical_ref_set && ' - Needs a canonical reference set'}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
