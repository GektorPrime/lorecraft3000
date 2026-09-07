import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, listArchivedCharacters, listCharacters } from '../../api/client'
import type { Character } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { AsyncMessage } from '../../components/AsyncMessage'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'

export function CharacterListPage() {
  const [characters, setCharacters] = useState<Character[] | null>(null)
  const [archived, setArchived] = useState<Character[]>([])
  const [error, setError] = useState<string | null>(null)
  const [showArchived, setShowArchived] = useState(false)

  useEffect(() => {
    Promise.all([listCharacters(), listArchivedCharacters()])
      .then(([active, archivedCharacters]) => {
        setCharacters(active)
        setArchived(archivedCharacters)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [])

  return (
    <section>
      <PageHeader
        title="Characters"
        actions={(
          <Link to="/characters/new" className="btn btn--primary">
            <Icon name="plus" size="sm" />
            New character
          </Link>
        )}
      />
      {error && <AsyncMessage kind="error">Could not load characters: {error}</AsyncMessage>}
      {!characters && !error && <AsyncMessage kind="loading">Loading characters…</AsyncMessage>}
      {characters && characters.length === 0 && (
        <EmptyState
          icon="characters"
          title="No characters yet"
          description="Create a character, then build a canonical reference set for consistent generations."
          action={(
            <Link to="/characters/new" className="btn btn--primary">
              <Icon name="plus" size="sm" />
              New character
            </Link>
          )}
        />
      )}
      {characters && characters.length > 0 && (
        <div className="resource-grid">
          {characters.map((character) => (
            <Link
              key={character.id}
              to={`/characters/${character.id}`}
              className="resource-card resource-card--link character-card"
            >
              <div className="resource-card__identity">
                <Avatar
                  url={character.avatar_url}
                  initials={character.avatar_initials}
                  name={character.name}
                  size={48}
                />
                <div className="resource-card__body">
                  <h2 className="resource-card__title">{character.name}</h2>
                  <span
                    className={`badge ${character.has_canonical_ref_set ? 'badge--canonical' : 'badge--draft'}`}
                  >
                    {character.has_canonical_ref_set ? 'Canonical ready' : 'Needs canonical set'}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {archived.length > 0 && (
        <div className="archived-section">
          <button
            type="button"
            className="btn archived-section__toggle"
            aria-expanded={showArchived}
            onClick={() => setShowArchived((value) => !value)}
          >
            {showArchived ? 'Hide' : 'Show'} archived characters ({archived.length})
          </button>
          {showArchived && (
            <div className="resource-grid">
              {archived.map((character) => (
                <Link
                  key={character.id}
                  to={`/characters/${character.id}`}
                  className="resource-card resource-card--link resource-card--archived character-card"
                >
                  <div className="resource-card__identity">
                    <Avatar
                      url={character.avatar_url}
                      initials={character.avatar_initials}
                      name={character.name}
                      size={48}
                    />
                    <div className="resource-card__body">
                      <h2 className="resource-card__title">{character.name}</h2>
                      <span className="badge badge--draft">Archived</span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
