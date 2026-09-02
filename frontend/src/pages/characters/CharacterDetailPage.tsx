import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, createRefSetDraft, getCharacter, listRefSets } from '../../api/client'
import type { Character, RefSetSummary } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { AsyncMessage } from '../../components/AsyncMessage'
import { RefSetPanel } from '../../components/RefSetPanel'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'
import { SectionHeader } from '../../components/SectionHeader'
import { NotFoundPage } from '../NotFoundPage'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'

export function CharacterDetailPage() {
  return (
    <RouteIdGuard>
      {(characterId) => <CharacterDetail key={characterId} characterId={characterId} />}
    </RouteIdGuard>
  )
}

function CharacterDetail({ characterId }: { characterId: number }) {
  const [character, setCharacter] = useState<Character | null>(null)
  const [refSets, setRefSets] = useState<RefSetSummary[] | null>(null)
  const [characterError, setCharacterError] = useState<string | null>(null)
  const [refSetsError, setRefSetsError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<{
    kind: 'success' | 'error'
    text: string
  } | null>(null)
  const [creatingDraft, setCreatingDraft] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [openIds, setOpenIds] = useState<Set<number>>(new Set())
  const seededCanonical = useRef(false)
  const requestVersion = useRef(0)
  const hasLoadedCharacter = useRef(false)
  const mounted = useRef(true)

  usePageTitle(character?.name ?? 'Loading Character')

  const reload = useCallback(async () => {
    const version = ++requestVersion.current
    const characterRequest = getCharacter(characterId).then(
      (nextCharacter) => {
        if (!mounted.current || version !== requestVersion.current) return null
        setCharacter(nextCharacter)
        hasLoadedCharacter.current = true
        setCharacterError(null)
        return null
      },
      (err: unknown) => {
        if (!mounted.current || version !== requestVersion.current) return null
        if (err instanceof ApiError && err.status === 404 && !hasLoadedCharacter.current) {
          setNotFound(true)
        }
        const message = err instanceof ApiError ? err.message : String(err)
        setCharacterError(message)
        return message
      },
    )
    const refSetsRequest = listRefSets(characterId).then(
      (sets) => {
        if (!mounted.current || version !== requestVersion.current) return null
        setRefSets(sets)
        // Canonical reference set is expanded by default and stays open; drafts
        // toggle independently. Seed once so later refreshes don't fight the user.
        if (!seededCanonical.current) {
          seededCanonical.current = true
          const canonical = sets.find((set) => set.status === 'canonical')
          if (canonical) setOpenIds((prev) => new Set(prev).add(canonical.id))
        }
        setRefSetsError(null)
        return null
      },
      (err: unknown) => {
        if (!mounted.current || version !== requestVersion.current) return null
        const message = err instanceof ApiError ? err.message : String(err)
        setRefSetsError(message)
        return message
      },
    )

    const [nextCharacterError, nextRefSetsError] = await Promise.all([
      characterRequest,
      refSetsRequest,
    ])
    return { characterError: nextCharacterError, refSetsError: nextRefSetsError }
  }, [characterId])

  useEffect(() => {
    mounted.current = true
    // oxlint-disable-next-line react/set-state-in-effect
    void reload()
    return () => {
      mounted.current = false
      requestVersion.current += 1
    }
  }, [reload])

  const handleNewDraft = async () => {
    if (creatingDraft) return
    setCreatingDraft(true)
    setActionMessage(null)
    try {
      const draft = await createRefSetDraft(characterId)
      if (!mounted.current) return
      setOpenIds((prev) => new Set(prev).add(draft.id))
      const refreshResult = await reload()
      if (!mounted.current) return
      const refreshError = refreshResult.refSetsError
      setActionMessage(
        refreshError
          ? { kind: 'error', text: `Draft created, but reference sets could not be refreshed: ${refreshError}` }
          : { kind: 'success', text: 'New reference-set draft created.' },
      )
    } catch (err) {
      if (!mounted.current) return
      setActionMessage({
        kind: 'error',
        text: `Could not create reference-set draft: ${err instanceof ApiError ? err.message : String(err)}`,
      })
    } finally {
      if (mounted.current) setCreatingDraft(false)
    }
  }

  const handleRefSetChanged = async () => {
    const refreshResult = await reload()
    return refreshResult.refSetsError
  }

  if (notFound) return <NotFoundPage />
  if (characterError && !character) {
    return (
      <div>
        <AsyncMessage kind="error">Could not load character: {characterError}</AsyncMessage>
        <button type="button" className="btn" onClick={() => void reload()}>Retry</button>
      </div>
    )
  }
  if (!character) return <AsyncMessage kind="loading">Loading character…</AsyncMessage>

  return (
    <section className="character-detail" aria-busy={creatingDraft || undefined}>
      <PageHeader
        media={(
          <Avatar
            url={character.avatar_url}
            initials={character.avatar_initials}
            name={character.name}
            size={72}
          />
        )}
        title={character.name}
        description={character.slug}
        actions={(
          <Link to={`/characters/${character.id}/edit`} className="btn btn--primary">
            <Icon name="edit" size={16} />
            Edit
          </Link>
        )}
      />

      {(character.visual_contract || character.negative_traits || character.lore_md) && (
        <div className="character-detail__cards">
          {character.visual_contract && (
            <section className="card character-detail__card">
              <h2>Visual contract</h2>
              <p>{character.visual_contract}</p>
            </section>
          )}
          {character.negative_traits && (
            <section className="card character-detail__card">
              <h2>Negative traits</h2>
              <p>{character.negative_traits}</p>
            </section>
          )}
          {character.lore_md && (
            <section className="card character-detail__card">
              <h2>Lore (local only)</h2>
              <p>{character.lore_md}</p>
            </section>
          )}
        </div>
      )}

      <SectionHeader
        title="Reference-set versions"
        description="Canonical identity and immutable version history."
        actions={(
          <button
            type="button"
            className="btn btn--primary"
            disabled={creatingDraft}
            onClick={() => void handleNewDraft()}
          >
            <Icon name="plus" size={16} />
            {creatingDraft ? 'Creating draft…' : 'New draft'}
          </button>
        )}
      />

      {characterError && <AsyncMessage kind="error">Could not refresh character: {characterError}</AsyncMessage>}
      {actionMessage && <AsyncMessage kind={actionMessage.kind}>{actionMessage.text}</AsyncMessage>}

      {refSetsError && (
        <div>
          <AsyncMessage kind="error">Could not load reference sets: {refSetsError}</AsyncMessage>
          <button type="button" className="btn" onClick={() => void reload()}>Retry reference sets</button>
        </div>
      )}
      {!refSets && !refSetsError && <AsyncMessage kind="loading">Loading reference sets…</AsyncMessage>}
      {refSets?.length === 0 && (
        <EmptyState
          icon="gallery"
          title="No reference sets yet."
          description="Create a draft and upload identity references for this character."
          compact
        />
      )}
      {refSets && refSets.length > 0 && (
        <div className="ref-set-list">
          {refSets.map((summary) => {
            const isOpen = openIds.has(summary.id)
            return (
              <div className="ref-set-item" key={summary.id}>
            <div className="refset-row">
              <div className="refset-row__meta">
                <span>v{summary.version}</span>
                <span className={`badge badge--${summary.status}`}>
                  {summary.status.charAt(0).toUpperCase() + summary.status.slice(1)}
                </span>
                <span className="field__hint">
                  {summary.image_count} image{summary.image_count === 1 ? '' : 's'}
                </span>
              </div>
              <button
                type="button"
                className="btn"
                aria-expanded={isOpen}
                onClick={() =>
                  setOpenIds((prev) => {
                    const next = new Set(prev)
                    if (next.has(summary.id)) next.delete(summary.id)
                    else next.add(summary.id)
                    return next
                  })
                }
              >
                {isOpen ? 'Hide' : 'Manage'}
              </button>
            </div>
            {isOpen && <RefSetPanel refSetId={summary.id} onChanged={handleRefSetChanged} />}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
