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
 * Gallery of every accepted generated image across all scenes, newest first.
 * Each card links back to its scene's preview page so the user can review
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
      <PageHeader title="Gallery" description="All accepted generated images." />
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {!items && !error && <AsyncMessage kind="loading">Loading gallery…</AsyncMessage>}
      {items && items.length === 0 && (
        <EmptyState
          icon="gallery"
          title="No accepted images yet."
          description="Accept a generated candidate from a scene preview and it will appear here."
          action={<Link to="/scenes">Review scenes</Link>}
        />
      )}
      {items && items.length > 0 && (
        <div className="resource-grid">
          {items.map((item, index) => {
            const previewItem = items[previewIndex ?? index]
            return (
              <article className="card card--flush gallery-card" key={item.candidate_id}>
                <ImageDialog
                  src={item.content_url}
                  previewSrc={previewItem.content_url}
                  thumbnailAlt={`Accepted image from scene ${item.scene_id}`}
                  previewAlt={`Accepted image from scene ${previewItem.scene_id}, full-size preview`}
                  triggerLabel={`Preview accepted image from scene ${item.scene_id}`}
                  dialogLabel={`Accepted image from scene ${previewItem.scene_id}, larger preview`}
                  onPrevious={() => setPreviewIndex((current) => ((current ?? index) - 1 + items.length) % items.length)}
                  onNext={() => setPreviewIndex((current) => ((current ?? index) + 1) % items.length)}
                  onOpenChange={(open) => setPreviewIndex(open ? index : null)}
                />
                <div className="gallery-card__body">
                  <p className="gallery-card__summary text-clamp" title={item.beat_text}>{item.beat_text}</p>
                  <p className="gallery-card__meta">
                    Scene #{item.scene_id} · {item.aspect_ratio} ·{' '}
                    <DateTime value={item.created_at} />
                  </p>
                </div>
                <div className="gallery-card__actions">
                  <Link to={`/panels/new?candidate=${item.candidate_id}`} className="btn btn--primary">
                    <Icon name="plus" size="sm" />
                    Add to panel
                  </Link>
                  <Link to={`/scenes/${item.scene_id}/preview`} className="btn">
                    <Icon name="chevronRight" size="sm" />
                    Open scene
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
