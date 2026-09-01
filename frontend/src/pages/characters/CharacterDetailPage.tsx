import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, createRefSetDraft, getCharacter, listRefSets } from '../../api/client'
import type { Character, RefSetSummary } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { AsyncMessage } from '../../components/AsyncMessage'
import { RefSetPanel } from '../../components/RefSetPanel'
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
  const [openId, setOpenId] = useState<number | null>(null)
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
      setOpenId(draft.id)
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
    <section aria-busy={creatingDraft || undefined}>
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
        <button type="button" className="btn btn--primary" disabled={creatingDraft} onClick={() => void handleNewDraft()}>
          {creatingDraft ? 'Creating draft…' : 'New draft'}
        </button>
      </div>

      {characterError && <AsyncMessage kind="error">Could not refresh character: {characterError}</AsyncMessage>}
      {actionMessage && <AsyncMessage kind={actionMessage.kind}>{actionMessage.text}</AsyncMessage>}

      {refSetsError && (
        <div>
          <AsyncMessage kind="error">Could not load reference sets: {refSetsError}</AsyncMessage>
          <button type="button" className="btn" onClick={() => void reload()}>Retry reference sets</button>
        </div>
      )}
      {!refSets && !refSetsError && <AsyncMessage kind="loading">Loading reference sets…</AsyncMessage>}
      {refSets?.length === 0 && <p className="field__hint">No reference sets yet.</p>}
      {refSets?.map((summary) => (
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
          {openId === summary.id && <RefSetPanel refSetId={summary.id} onChanged={handleRefSetChanged} />}
        </div>
      ))}
    </section>
  )
}
