import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, deletePanel, listPanels } from '../../api/client'
import type { Panel } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'

export function PanelListPage() {
  const navigate = useNavigate()
  const [panels, setPanels] = useState<Panel[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const mounted = useRef(true)

  const busy = deletingId !== null

  const reload = () =>
    listPanels()
      .then((value) => {
        if (!mounted.current) return
        setPanels(value)
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
      await deletePanel(id)
      await reload()
    } catch (err) {
      if (mounted.current) setError(`Could not delete panel: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setDeletingId(null)
    }
  }

  // The whole tile opens the panel preview. Action buttons stopPropagation so
  // they never trigger this navigation.
  const openPreview = (id: number) => navigate(`/panels/${id}/preview`)

  return (
    <section aria-busy={busy || undefined}>
      <PageHeader
        title="Panels"
        actions={(
          <Link to="/panels/new" className="btn btn--primary">
            <Icon name="plus" size={16} />
            Stage new panel
          </Link>
        )}
      />
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {!panels && !error && <AsyncMessage kind="loading">Loading panels…</AsyncMessage>}
      {panels && panels.length === 0 && (
        <EmptyState
          icon="panels"
          title="No panels yet"
          description="Stage a shot from your character library and visual style."
          action={(
            <Link to="/panels/new" className="btn btn--primary">
              <Icon name="plus" size={16} />
              Stage new panel
            </Link>
          )}
        />
      )}
      {panels && panels.length > 0 && (
        <div className="resource-list">
          {panels.map((panel) => (
            <article
              key={panel.id}
              className="resource-card resource-card--clickable"
              role="button"
              tabIndex={0}
              aria-label={`Preview panel #${panel.id}`}
              onClick={() => openPreview(panel.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  openPreview(panel.id)
                }
              }}
            >
              <div className="resource-card__body">
                <div className="resource-card__header">
                  <h2 className="resource-card__title">Panel #{panel.id}</h2>
                  <span className={`badge ${panel.is_editable ? 'badge--draft' : 'badge--canonical'}`}>
                    {panel.is_editable ? 'Editable' : 'Locked'}
                  </span>
                </div>
                <p className="resource-card__summary text-clamp" title={panel.beat_text}>
                  {panel.beat_text}
                </p>
                <p className="resource-card__meta">
                  <span>Cast: {panel.cast.map((m) => m.name).join(', ') || 'none'}</span>
                  <span>
                    {panel.generation_count} generation attempt
                    {panel.generation_count === 1 ? '' : 's'}
                  </span>
                </p>
              </div>
              <div className="resource-card__actions">
                {panel.is_editable && (
                  <Link
                    to={`/panels/${panel.id}/edit`}
                    className="btn"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <Icon name="edit" size={15} />
                    Edit
                  </Link>
                )}
                <button
                  type="button"
                  className="btn btn--danger"
                  disabled={busy}
                  onClick={(event) => {
                    event.stopPropagation()
                    setConfirmId(panel.id)
                  }}
                >
                  <Icon name="trash" size={15} />
                  {deletingId === panel.id ? 'Deleting…' : 'Delete'}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={confirmId !== null}
        title="Delete this panel?"
        description="This permanently deletes the panel and its entire generation history. This cannot be undone."
        confirmLabel="Delete panel"
        onConfirm={() => void confirmDelete()}
        onCancel={() => setConfirmId(null)}
      />
    </section>
  )
}
