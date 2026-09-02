import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, duplicatePanel, listPanels } from '../../api/client'
import type { Panel } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'

export function PanelListPage() {
  const navigate = useNavigate()
  const [panels, setPanels] = useState<Panel[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [duplicatingId, setDuplicatingId] = useState<number | null>(null)
  const mounted = useRef(true)

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

  // Duplicate a locked panel and go straight to editing the new, editable
  // copy — duplicating alone does not let the user edit anything, so this
  // must navigate, not just refresh the list (issue #15 follow-up).
  const handleDuplicateAndEdit = async (id: number) => {
    if (duplicatingId !== null) return
    setDuplicatingId(id)
    setError(null)
    try {
      const copy = await duplicatePanel(id)
      if (!mounted.current) return
      navigate(`/panels/${copy.id}/edit`)
    } catch (err) {
      if (!mounted.current) return
      setError(`Could not duplicate panel: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setDuplicatingId(null)
    }
  }

  return (
    <section aria-busy={duplicatingId !== null || undefined}>
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
            <article key={panel.id} className="resource-card">
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
                <Link to={`/panels/${panel.id}/preview`} className="btn">
                  <Icon name="gallery" size={15} />
                  Preview
                </Link>
                {panel.is_editable ? (
                  <Link to={`/panels/${panel.id}/edit`} className="btn">
                    <Icon name="edit" size={15} />
                    Edit
                  </Link>
                ) : (
                  <button
                    type="button"
                    className="btn"
                    disabled={duplicatingId !== null}
                    onClick={() => void handleDuplicateAndEdit(panel.id)}
                  >
                    <Icon name="copy" size={15} />
                    {duplicatingId === panel.id ? 'Duplicating…' : 'Duplicate & edit'}
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
