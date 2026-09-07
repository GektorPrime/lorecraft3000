import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, deleteScene, listScenes } from '../../api/client'
import type { Scene } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'

export function SceneListPage() {
  const navigate = useNavigate()
  const [scenes, setScenes] = useState<Scene[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const mounted = useRef(true)

  const busy = deletingId !== null

  const reload = () =>
    listScenes()
      .then((value) => {
        if (!mounted.current) return
        setScenes(value)
        setError(null)
      })
      .catch((err) => {
        if (mounted.current) setError(err instanceof ApiError ? err.message : String(err))
      })

  useEffect(() => {
    mounted.current = true
    reload()
    return () => {
      mounted.current = false
    }
  }, [])

  const confirmDelete = async () => {
    const id = confirmId
    setConfirmId(null)
    if (id === null || busy) return
    setDeletingId(id)
    setError(null)
    try {
      await deleteScene(id)
      await reload()
    } catch (err) {
      if (mounted.current) setError(`Could not delete scene: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setDeletingId(null)
    }
  }

  // The whole tile opens the scene preview. Action buttons stopPropagation so
  // they never trigger this navigation.
  const openPreview = (id: number) => navigate(`/scenes/${id}/preview`)

  return (
    <section aria-busy={busy || undefined}>
      <PageHeader
        title="Scenes"
        actions={(
          <Link to="/scenes/new" className="btn btn--primary">
            <Icon name="plus" size="sm" />
            New scene
          </Link>
        )}
      />
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {!scenes && !error && <AsyncMessage kind="loading">Loading scenes…</AsyncMessage>}
      {scenes && scenes.length === 0 && (
        <EmptyState
          icon="scenes"
          title="No scenes yet"
          description="Stage a shot from your character library and visual style."
          action={(
            <Link to="/scenes/new" className="btn btn--primary">
              <Icon name="plus" size="sm" />
              New scene
            </Link>
          )}
        />
      )}
      {scenes && scenes.length > 0 && (
        <div className="resource-list">
          {scenes.map((scene) => (
            <article
              key={scene.id}
              className="resource-card resource-card--clickable scene-list-card"
              role="button"
              tabIndex={0}
              aria-label={`Preview scene #${scene.id}`}
              onClick={() => openPreview(scene.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  openPreview(scene.id)
                }
              }}
            >
              {scene.latest_attempt_preview_url && (
                <img
                  className="scene-list-card__preview"
                  src={scene.latest_attempt_preview_url}
                  alt={`Latest generation attempt for scene #${scene.id}`}
                />
              )}
              <div className="resource-card__body">
                <h2 className="resource-card__title">Scene #{scene.id}</h2>
                <p className="resource-card__summary text-clamp" title={scene.beat_text}>
                  {scene.beat_text}
                </p>
                <p className="resource-card__meta">
                  <span className={`badge ${scene.is_editable ? 'badge--draft' : 'badge--canonical'}`}>
                    {scene.is_editable ? 'Editable' : 'Locked'}
                  </span>
                  {scene.base_stage_id !== null && (
                    <Link
                      className="badge badge--draft scene-list-card__stage-link"
                      to={`/base-stages/${scene.base_stage?.id ?? scene.base_stage_id}/preview`}
                      title={`Open Base Stage #${scene.base_stage?.id ?? scene.base_stage_id}`}
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => event.stopPropagation()}
                    >
                      Base Stage
                    </Link>
                  )}
                  <span>Cast: {scene.cast.map((m) => m.name).join(', ') || 'none'}</span>
                  <span>
                    {scene.generation_count} generation attempt
                    {scene.generation_count === 1 ? '' : 's'}
                  </span>
                </p>
              </div>
              <div className="resource-card__actions">
                <button
                  type="button"
                  className="btn btn--danger"
                  disabled={busy}
                  onClick={(event) => {
                    event.stopPropagation()
                    setConfirmId(scene.id)
                  }}
                >
                  <Icon name="trash" size="sm" />
                  {deletingId === scene.id ? 'Deleting…' : 'Delete'}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={confirmId !== null}
        title="Delete this scene?"
        description="This permanently deletes the scene and its entire generation history. This cannot be undone."
        confirmLabel="Delete scene"
        onConfirm={() => void confirmDelete()}
        onCancel={() => setConfirmId(null)}
      />
    </section>
  )
}
