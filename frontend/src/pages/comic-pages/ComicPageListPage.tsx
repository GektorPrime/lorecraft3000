import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, deleteComicPage, listComicPages } from '../../api/client'
import type { ComicPage } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { DateTime } from '../../components/DateTime'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { ImageWithFallback } from '../../components/ImageWithFallback'
import { PageHeader } from '../../components/PageHeader'
import { getComicPageTemplate } from '../../comic-pages/templates'

const errorMessage = (error: unknown) => error instanceof ApiError ? error.message : String(error)

export function ComicPageListPage() {
  const [pages, setPages] = useState<ComicPage[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const mounted = useRef(true)

  const reload = (clearError = true) => {
    if (clearError) setError(null)
    return listComicPages().then((value) => {
      if (mounted.current) setPages(value)
    }).catch((reason) => {
      if (mounted.current) setError(errorMessage(reason))
    })
  }

  useEffect(() => {
    mounted.current = true
    void listComicPages().then((value) => {
      if (mounted.current) setPages(value)
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
      await deleteComicPage(id)
      if (mounted.current) setPages((current) => current?.filter((page) => page.id !== id) ?? null)
    } catch (reason) {
      if (mounted.current) setError(`Could not delete comic page: ${errorMessage(reason)}`)
    } finally {
      if (mounted.current) setBusyId(null)
    }
  }

  return (
    <section aria-busy={pages === null && !error || busyId !== null || undefined}>
      <PageHeader
        title="Comic pages"
        description="Arrange accepted scenes into finished, export-ready pages."
        actions={<Link className="btn btn--primary" to="/panels/new"><Icon name="plus" size="sm" />New comic page</Link>}
      />
      {error && <div className="content-stack"><AsyncMessage kind="error">{error}</AsyncMessage><div><button className="btn" type="button" onClick={() => void reload()}>Retry</button></div></div>}
      {!pages && !error && <AsyncMessage kind="loading">Loading comic pages…</AsyncMessage>}
      {pages?.length === 0 && (
        <EmptyState
          icon="panels"
          title="No comic pages yet"
          description="Choose accepted images from the Gallery, then arrange them in a page template."
          action={<div className="btn-row"><Link className="btn" to="/gallery">Open Gallery</Link><Link className="btn btn--primary" to="/panels/new">New comic page</Link></div>}
        />
      )}
      {pages && pages.length > 0 && <div className="comic-page-grid">
        {pages.map((page) => {
          const slots = getComicPageTemplate(page.template_key).slotCount
          return <article className="card card--flush comic-page-card" key={page.id}>
            <div className={`comic-page-card__media comic-page-card__media--${page.format}`}>
              {page.latest_render
                ? <ImageWithFallback src={page.latest_render.content_url} alt={`Latest render of ${page.title}`} />
                : <span className="comic-page-placeholder" role="img" aria-label={`${page.title} has not been rendered`}><Icon name="panels" size="xl" /></span>}
            </div>
            <div className="comic-page-card__body">
              <h2>{page.title}</h2>
              <p className="resource-card__meta"><span>{page.format}</span><span>{page.panels.length}/{slots} panels</span><span>Updated <DateTime value={page.updated_at} /></span></p>
            </div>
            <div className="comic-page-card__actions">
              <Link className="btn" to={`/panels/${page.id}/edit`}>Edit</Link>
              {page.latest_render && <a className="btn" href={page.latest_render.download_url}>Download</a>}
              <button className="btn btn--danger" type="button" disabled={busyId === page.id} onClick={() => setConfirmId(page.id)}><Icon name="trash" size="sm" />Delete</button>
            </div>
          </article>
        })}
      </div>}
      <ConfirmDialog
        open={confirmId !== null}
        title="Delete this comic page?"
        description="The page and its render history will be permanently deleted. Accepted source images remain in the Gallery."
        confirmLabel="Delete comic page"
        onConfirm={() => void handleDelete()}
        onCancel={() => setConfirmId(null)}
      />
    </section>
  )
}
