import type {
  BaseStage,
  CastMemberInput,
  Character,
  PanelBaseStage,
} from '../api/types'
import { ProminenceInput } from './ProminenceInput'

type StageChoice = BaseStage | PanelBaseStage

interface BaseStageCastMapperProps {
  stages: StageChoice[]
  characters: Character[]
  selectedStageId: number | null
  value: CastMemberInput[]
  onStageChange: (stageId: number) => void
  onChange: (next: CastMemberInput[]) => void
}

function dimensions(stage: StageChoice) {
  return 'dimensions' in stage && stage.dimensions
    ? `${stage.dimensions.width} x ${stage.dimensions.height}`
    : 'Dimensions unavailable'
}

export function BaseStageCastMapper({
  stages,
  characters,
  selectedStageId,
  value,
  onStageChange,
  onChange,
}: BaseStageCastMapperProps) {
  const selected = stages.find((stage) => stage.id === selectedStageId) ?? null
  const orderedTargets = selected ? [...selected.targets].sort((a, b) => a.position - b.position) : []
  const byTarget = new Map(value.map((member) => [member.base_stage_target_id, member]))
  const selectedCharacterIds = new Set(value.map((member) => member.character_id))

  const updateTarget = (targetId: number, characterId: number) => {
    const existing = byTarget.get(targetId)
    const next = orderedTargets.flatMap((target) => {
      const member = target.id === targetId
        ? characterId === 0
          ? null
          : {
              character_id: characterId,
              base_stage_target_id: target.id,
              role: '',
              prominence: existing?.prominence ?? 1,
            }
        : byTarget.get(target.id)
      return member ? [member] : []
    })
    onChange(next)
  }

  const updateProminence = (targetId: number, prominence: number) => {
    onChange(value.map((member) =>
      member.base_stage_target_id === targetId ? { ...member, prominence } : member,
    ))
  }

  return (
    <div className="base-stage-mapper">
      <div className="field">
        <span className="field__label" id="base-stage-picker-label">Base Stage</span>
        <span className="field__hint" id="base-stage-picker-hint">
          Choose the source composition. Stages without character targets cannot map your cast.
        </span>
        <div
          className="base-stage-picker"
          role="radiogroup"
          aria-labelledby="base-stage-picker-label"
          aria-describedby="base-stage-picker-hint"
        >
          {stages.map((stage) => {
            const usable = stage.state === 'ready' && stage.targets.length > 0
            return (
              <label
                key={stage.id}
                className={`base-stage-picker__option${selectedStageId === stage.id ? ' base-stage-picker__option--selected' : ''}${!usable ? ' base-stage-picker__option--disabled' : ''}`}
              >
                <input
                  type="radio"
                  name="base-stage"
                  value={stage.id}
                  checked={selectedStageId === stage.id}
                  disabled={!usable}
                  onChange={() => onStageChange(stage.id)}
                />
                {stage.content_url ? (
                  <img src={stage.content_url} alt="" />
                ) : (
                  <span className="base-stage-picker__placeholder">Preview unavailable</span>
                )}
                <span className="base-stage-picker__copy">
                  <strong>Base stage #{stage.id}</strong>
                  <span>{stage.description}</span>
                  <span className="field__hint">
                    {stage.aspect_ratio} · {dimensions(stage)} · {stage.targets.length} target{stage.targets.length === 1 ? '' : 's'}
                  </span>
                  {stage.targets.length === 0 && (
                    <span className="field__hint">Cannot be selected: no targets to map characters.</span>
                  )}
                  {stage.state !== 'ready' && (
                    <span className="field__hint">Cannot be selected: stage is {stage.state}.</span>
                  )}
                </span>
              </label>
            )
          })}
        </div>
      </div>

      {selected && (
        <section className="base-stage-selection" aria-labelledby="selected-base-stage-heading">
          <div className="base-stage-selection__summary">
            {selected.content_url && (
              <img src={selected.content_url} alt={`Selected base stage: ${selected.description}`} />
            )}
            <div>
              <h3 id="selected-base-stage-heading">Selected base stage #{selected.id}</h3>
              <p>{selected.description}</p>
              <p className="field__hint">
                {selected.aspect_ratio} · {dimensions(selected)} · {orderedTargets.length} target{orderedTargets.length === 1 ? '' : 's'}
              </p>
            </div>
          </div>

          <p className="field__hint" id="base-stage-mapping-hint">
            Assign one character with a canonical reference set to every target. Cast and reference priority follow this target order.
          </p>
          <ol className="base-stage-targets" aria-describedby="base-stage-mapping-hint">
            {orderedTargets.map((target, index) => {
              const member = byTarget.get(target.id)
              return (
                <li key={target.id} className="base-stage-targets__row">
                  <div className="base-stage-targets__description">
                    <span className="badge badge--draft">Target {index + 1}</span>
                    <strong>{target.description}</strong>
                  </div>
                  <div className="field">
                    <label htmlFor={`base-stage-target-${target.id}`}>Character</label>
                    <select
                      id={`base-stage-target-${target.id}`}
                      required
                      value={member?.character_id ?? ''}
                      onChange={(event) => updateTarget(target.id, Number(event.target.value))}
                    >
                      <option value="">Select a character</option>
                      {characters.map((character) => (
                        <option
                          key={character.id}
                          value={character.id}
                          disabled={
                            !character.has_canonical_ref_set ||
                            (selectedCharacterIds.has(character.id) && member?.character_id !== character.id)
                          }
                        >
                          {character.name}{!character.has_canonical_ref_set ? ' - Needs a canonical reference set' : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor={`base-stage-prominence-${target.id}`}>Prominence</label>
                    <ProminenceInput
                      id={`base-stage-prominence-${target.id}`}
                      disabled={!member}
                      value={member?.prominence ?? 1}
                      onChange={(prominence) => updateProminence(target.id, prominence)}
                    />
                  </div>
                </li>
              )
            })}
          </ol>
        </section>
      )}
    </div>
  )
}
