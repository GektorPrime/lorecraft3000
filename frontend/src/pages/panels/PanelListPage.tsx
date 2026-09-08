import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, deletePanel, listPanels } from '../../api/client'
import type { Panel } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { DateTime } from '../../components/DateTime'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { ImageWithFallback } from '../../components/ImageWithFallback'
import { PageHeader } from '../../components/PageHeader'

const errorMessage = (error: unknown) => error instanceof ApiError ? error.message : String(error)

export function PanelListPage() {
  const [panels, setPanels] = useState<Panel[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const mounted = useRef(true)

  const reload = (clearError = true) => {
    if (clearError) setError(null)
    return listPanels().then((value) => {
      if (mounted.current) setPanels(value)
    }).catch((reason) => {
      if (mounted.current) setError(errorMessage(reason))
    })
  }

  useEffect(() => {
    mounted.current = true
    void listPanels().then((value) => {
      if (mounted.current) setPanels(value)
    }).catch((reason) => {
      if (mounted.current) setError(errorMessage(reason))
    })
    return () => { mounted.current = false }
  }, [])

  const handleDelete = async () => {
    const id = confirmId
    setConfirmId(null)
    if (id === null) return
    setBusyId(id)
    try {
      await deletePanel(id)
      if (mounted.current) setPanels((current) => current?.filter((panel) => panel.id !== id) ?? null)
    } catch (reason) {
      if (mounted.current) setError(`Could not delete panel: ${errorMessage(reason)}`)
    } finally {
      if (mounted.current) setBusyId(null)
    }
  }

  return (
    <section aria-busy={panels === null && !error || busyId !== null || undefined}>
      <PageHeader
        title="Panels"
        description="Arrange accepted images into finished, export-ready panels."
        actions={<Link className="btn btn--primary" to="/panels/new"><Icon name="plus" size="sm" />New panel</Link>}
      />
      {error && <div className="content-stack"><AsyncMessage kind="error">{error}</AsyncMessage><div><button className="btn" type="button" onClick={() => void reload()}>Retry</button></div></div>}
      {!panels && !error && <AsyncMessage kind="loading">Loading panels…</AsyncMessage>}
      {panels?.length === 0 && (
        <EmptyState
          icon="panels"
          title="No panels yet"
          description="Choose accepted images from the Gallery, then arrange them into a panel."
          action={<div className="btn-row"><Link className="btn" to="/gallery">Open Gallery</Link><Link className="btn btn--primary" to="/panels/new">New panel</Link></div>}
        />
      )}
      {panels && panels.length > 0 && <div className="panel-grid">
        {panels.map((panel) => {
          const filled = panel.slots.filter((slot) => slot.candidate_id !== null).length
          return <article className="card card--flush panel-card" key={panel.id}>
            <div className={`panel-card__media panel-card__media--${panel.format}`}>
              {panel.latest_render
                ? <ImageWithFallback src={panel.latest_render.content_url} alt={`Latest render of ${panel.title}`} />
                : <span className="panel-placeholder" role="img" aria-label={`${panel.title} has not been rendered`}><Icon name="panels" size="xl" /></span>}
            </div>
            <div className="panel-card__body">
              <h2>{panel.title}</h2>
              <p className="resource-card__meta"><span>{panel.format}</span><span>{filled}/{panel.slots.length} slots</span><span>Updated <DateTime value={panel.updated_at} /></span></p>
            </div>
            <div className="panel-card__actions">
              <Link className="btn" to={`/panels/${panel.id}/edit`}>Edit</Link>
              {panel.latest_render && <a className="btn" href={panel.latest_render.download_url}>Download</a>}
              <button className="btn btn--danger" type="button" disabled={busyId === panel.id} onClick={() => setConfirmId(panel.id)}><Icon name="trash" size="sm" />Delete</button>
            </div>
          </article>
        })}
      </div>}
      <ConfirmDialog
        open={confirmId !== null}
        title="Delete this panel?"
        description="The panel and its render history will be permanently deleted. Accepted source images remain in the Gallery."
        confirmLabel="Delete panel"
        onConfirm={() => void handleDelete()}
        onCancel={() => setConfirmId(null)}
      />
    </section>
  )
}
