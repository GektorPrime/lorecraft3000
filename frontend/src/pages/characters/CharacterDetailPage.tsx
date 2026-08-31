import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, createRefSetDraft, getCharacter, listRefSets } from '../../api/client'
import type { Character, RefSetSummary } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { RefSetPanel } from '../../components/RefSetPanel'

export function CharacterDetailPage() {
  const { id } = useParams()
  const characterId = Number(id)

  const [character, setCharacter] = useState<Character | null>(null)
  const [refSets, setRefSets] = useState<RefSetSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)

  const reload = useCallback(() => {
    Promise.all([getCharacter(characterId), listRefSets(characterId)])
      .then(([c, sets]) => {
        setCharacter(c)
        setRefSets(sets)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [characterId])

  useEffect(() => {
    reload()
  }, [reload])

  const handleNewDraft = async () => {
    try {
      const draft = await createRefSetDraft(characterId)
      reload()
      setOpenId(draft.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  if (error) return <p className="banner banner--error">{error}</p>
  if (!character || !refSets) return <p>Loading…</p>

  return (
    <section>
      <div className="btn-row" style={{ marginTop: 0, alignItems: 'center' }}>
        <Avatar url={character.avatar_url} initials={character.avatar_initials} name={character.name} size={72} />
        <div>
          <h1 style={{ margin: 0 }}>{character.name}</h1>
          <p className="field__hint" style={{ margin: 0 }}>
            {character.slug}
          </p>
        </div>
        <Link to={`/characters/${character.id}/edit`} className="btn">
          Edit
        </Link>
      </div>

      {character.visual_contract && (
        <div className="card" style={{ marginTop: '1rem' }}>
          <h3>Visual contract</h3>
          <p>{character.visual_contract}</p>
        </div>
      )}
      {character.negative_traits && (
        <div className="card" style={{ marginTop: '0.75rem' }}>
          <h3>Negative traits</h3>
          <p>{character.negative_traits}</p>
        </div>
      )}
      {character.lore_md && (
        <div className="card" style={{ marginTop: '0.75rem' }}>
          <h3>Lore (local only)</h3>
          <p>{character.lore_md}</p>
        </div>
      )}

      <div className="btn-row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>Reference-set versions</h2>
        <button type="button" className="btn btn--primary" onClick={() => void handleNewDraft()}>
          New draft
        </button>
      </div>

      {refSets.length === 0 && <p className="field__hint">No reference sets yet.</p>}
      {refSets.map((summary) => (
        <div key={summary.id}>
          <button
            type="button"
            className="btn"
            style={{ marginTop: '0.5rem' }}
            onClick={() => setOpenId(openId === summary.id ? null : summary.id)}
          >
            v{summary.version} · <span className={`badge badge--${summary.status}`}>{summary.status}</span> ·{' '}
            {summary.image_count} image{summary.image_count === 1 ? '' : 's'}
            {openId === summary.id ? ' (hide)' : ' (manage)'}
          </button>
          {openId === summary.id && <RefSetPanel refSetId={summary.id} onChanged={reload} />}
        </div>
      ))}
    </section>
  )
}
