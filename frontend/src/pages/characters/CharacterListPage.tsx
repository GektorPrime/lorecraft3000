import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, listCharacters } from '../../api/client'
import type { Character } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { AsyncMessage } from '../../components/AsyncMessage'

export function CharacterListPage() {
  const [characters, setCharacters] = useState<Character[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listCharacters()
      .then(setCharacters)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [])

  return (
    <section>
      <div className="btn-row list-page-header">
        <h1>Characters</h1>
        <Link to="/characters/new" className="btn btn--primary">
          New character
        </Link>
      </div>
      {error && <AsyncMessage kind="error">Could not load characters: {error}</AsyncMessage>}
      {!characters && !error && <AsyncMessage kind="loading">Loading characters…</AsyncMessage>}
      {characters && characters.length === 0 && <p>No characters yet.</p>}
      {characters && characters.length > 0 && (
        <div className="card-grid">
          {characters.map((character) => (
            <Link key={character.id} to={`/characters/${character.id}`} className="card card--link">
              <div className="btn-row" style={{ marginTop: 0, alignItems: 'center' }}>
                <Avatar
                  url={character.avatar_url}
                  initials={character.avatar_initials}
                  name={character.name}
                  size={48}
                />
                <div>
                  <strong>{character.name}</strong>
                  <p className="field__hint" style={{ margin: 0 }}>
                    {character.has_canonical_ref_set ? 'Canonical ref-set ready' : 'No canonical ref-set yet'}
                  </p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  )
}
