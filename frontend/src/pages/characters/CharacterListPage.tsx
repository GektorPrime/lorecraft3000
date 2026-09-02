import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ApiError,
  archiveCharacter,
  listArchivedCharacters,
  listCharacters,
  restoreCharacter,
} from '../../api/client'
import type { Character } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'

export function CharacterListPage() {
  const navigate = useNavigate()
  const [characters, setCharacters] = useState<Character[] | null>(null)
  const [archived, setArchived] = useState<Character[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const mounted = useRef(true)

  const reload = () =>
    Promise.all([listCharacters(), listArchivedCharacters()])
      .then(([active, archivedCharacters]) => {
        if (!mounted.current) return
        setCharacters(active)
        setArchived(archivedCharacters)
        setError(null)
      })
      .catch((err) => {
        if (mounted.current) setError(err instanceof ApiError ? err.message : String(err))
      })

  useEffect(() => {
    mounted.current = true
    void reload()
    return () => {
      mounted.current = false
    }
  }, [])

  const confirmArchive = async () => {
    const id = confirmId
    setConfirmId(null)
    if (id === null || busyId !== null) return
    setBusyId(id)
    setError(null)
    try {
      await archiveCharacter(id)
      await reload()
    } catch (err) {
      if (mounted.current) setError(`Could not archive character: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setBusyId(null)
    }
  }

  const handleRestore = async (id: number) => {
    if (busyId !== null) return
    setBusyId(id)
    setError(null)
    try {
      await restoreCharacter(id)
      await reload()
    } catch (err) {
      if (mounted.current) setError(`Could not restore character: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setBusyId(null)
    }
  }

  const openDetail = (id: number) => navigate(`/characters/${id}`)

  const pendingCharacter = confirmId !== null ? characters?.find((c) => c.id === confirmId) : undefined

  return (
    <section aria-busy={busyId !== null || undefined}>
      <PageHeader
        title="Characters"
        actions={(
          <Link to="/characters/new" className="btn btn--primary">
            <Icon name="plus" size={16} />
            New character
          </Link>
        )}
      />
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {!characters && !error && <AsyncMessage kind="loading">Loading characters…</AsyncMessage>}
      {characters && characters.length === 0 && (
        <EmptyState
          icon="characters"
          title="No characters yet"
          description="Create a character, then build a canonical reference set for consistent generations."
          action={(
            <Link to="/characters/new" className="btn btn--primary">
              <Icon name="plus" size={16} />
              New character
            </Link>
          )}
        />
      )}
      {characters && characters.length > 0 && (
        <div className="resource-grid">
          {characters.map((character) => (
            <article
              key={character.id}
              className="resource-card resource-card--clickable character-card"
              role="button"
              tabIndex={0}
              aria-label={`Open ${character.name}`}
              onClick={() => openDetail(character.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  openDetail(character.id)
                }
              }}
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
              <div className="resource-card__actions">
                <Link
                  to={`/characters/${character.id}/edit`}
                  className="btn"
                  onClick={(event) => event.stopPropagation()}
                >
                  <Icon name="edit" size={15} />
                  Edit
                </Link>
                <button
                  type="button"
                  className="btn btn--danger"
                  disabled={busyId !== null}
                  onClick={(event) => {
                    event.stopPropagation()
                    setConfirmId(character.id)
                  }}
                >
                  <Icon name="trash" size={15} />
                  Delete
                </button>
              </div>
            </article>
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
                <article
                  key={character.id}
                  className="resource-card resource-card--archived character-card"
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
                    </div>
                  </div>
                  <div className="resource-card__actions">
                    <button
                      type="button"
                      className="btn"
                      disabled={busyId !== null}
                      onClick={() => void handleRestore(character.id)}
                    >
                      {busyId === character.id ? 'Restoring…' : 'Restore'}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmId !== null}
        title="Archive this character?"
        description={
          pendingCharacter
            ? `"${pendingCharacter.name}" stays in existing panels but is hidden from lists and can't be cast in new panels. You can restore it later.`
            : 'The character stays in existing panels but is hidden from lists. You can restore it later.'
        }
        confirmLabel="Archive character"
        onConfirm={() => void confirmArchive()}
        onCancel={() => setConfirmId(null)}
      />
    </section>
  )
}
