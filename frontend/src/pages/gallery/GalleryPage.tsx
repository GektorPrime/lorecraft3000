import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getGallery } from '../../api/client'
import type { GalleryItem } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { DateTime } from '../../components/DateTime'
import { ImageDialog } from '../../components/ImageDialog'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'

/**
 * Gallery of every accepted generated image across all panels, newest first.
 * Each card links back to its panel's preview page so the user can review
 * the attempt that produced the accepted image.
 */
export function GalleryPage() {
  const [items, setItems] = useState<GalleryItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const mounted = useRef(true)

  const reload = () =>
    getGallery()
      .then((value) => {
        if (!mounted.current) return
        setItems(value)
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

  return (
    <section aria-busy={items === null && error === null || undefined}>
      <PageHeader title="Gallery" description="All accepted generated images, newest first." />
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {!items && !error && <AsyncMessage kind="loading">Loading gallery…</AsyncMessage>}
      {items && items.length === 0 && (
        <EmptyState
          icon="gallery"
          title="No accepted images yet."
          description="Accept a generated candidate from a panel preview and it will appear here."
          action={<Link to="/panels">Review panels</Link>}
        />
      )}
      {items && items.length > 0 && (
        <div className="gallery-grid">
          {items.map((item, index) => {
            const previewItem = items[previewIndex ?? index]
            return (
              <article className="gallery-card" key={item.candidate_id}>
                <ImageDialog
                  src={item.content_url}
                  previewSrc={previewItem.content_url}
                  thumbnailAlt={`Accepted image from panel ${item.panel_id}`}
                  previewAlt={`Accepted image from panel ${previewItem.panel_id}, full-size preview`}
                  triggerLabel={`Preview accepted image from panel ${item.panel_id}`}
                  dialogLabel={`Accepted image from panel ${previewItem.panel_id}, larger preview`}
                  onPrevious={() => setPreviewIndex((current) => ((current ?? index) - 1 + items.length) % items.length)}
                  onNext={() => setPreviewIndex((current) => ((current ?? index) + 1) % items.length)}
                  onOpenChange={(open) => setPreviewIndex(open ? index : null)}
                />
                <div className="gallery-card__body">
                  <p className="gallery-card__summary text-clamp" title={item.beat_text}>{item.beat_text}</p>
                  <p className="gallery-card__meta">
                    Panel #{item.panel_id} · {item.aspect_ratio} ·{' '}
                    <DateTime value={item.created_at} />
                  </p>
                </div>
                <div className="gallery-card__actions">
                  <Link to={`/panels/${item.panel_id}/preview`} className="btn">
                    <Icon name="chevronRight" size={15} />
                    Open panel
                  </Link>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
