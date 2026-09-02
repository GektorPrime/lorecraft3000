import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getGallery, listCharacters, listPanels, listStyles } from '../api/client'
import type { Character, GalleryItem, Panel, Style } from '../api/types'
import { useBudget } from '../api/useBudget'
import { AsyncMessage } from '../components/AsyncMessage'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { ImageDialog } from '../components/ImageDialog'
import { PageHeader } from '../components/PageHeader'

const RECENT_PANEL_COUNT = 3
const RECENT_OUTPUT_COUNT = 6

function message(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : String(error)
}

/**
 * Workflow dashboard. Its four collections load independently: a gallery
 * outage must not hide panel work, and a character failure must not suppress
 * the style count. Budget comes from the shell provider and is available
 * immediately from the options snapshot.
 *
 * The app brand is intentionally absent here. Sidebar owns the document's
 * single "LoreCraft3000" occurrence and its single <header> landmark.
 */
export function Home() {
  const { budget, refreshError } = useBudget()
  const [panels, setPanels] = useState<Panel[] | null>(null)
  const [panelError, setPanelError] = useState<string | null>(null)
  const [gallery, setGallery] = useState<GalleryItem[] | null>(null)
  const [galleryError, setGalleryError] = useState<string | null>(null)
  const [characters, setCharacters] = useState<Character[] | null>(null)
  const [characterError, setCharacterError] = useState<string | null>(null)
  const [styles, setStyles] = useState<Style[] | null>(null)
  const [styleError, setStyleError] = useState<string | null>(null)
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true

    void listPanels()
      .then((value) => {
        if (mounted.current) setPanels(value)
      })
      .catch((error) => {
        if (mounted.current) setPanelError(message(error))
      })

    void getGallery()
      .then((value) => {
        if (mounted.current) setGallery(value)
      })
      .catch((error) => {
        if (mounted.current) setGalleryError(message(error))
      })

    void listCharacters()
      .then((value) => {
        if (mounted.current) setCharacters(value)
      })
      .catch((error) => {
        if (mounted.current) setCharacterError(message(error))
      })

    void listStyles()
      .then((value) => {
        if (mounted.current) setStyles(value)
      })
      .catch((error) => {
        if (mounted.current) setStyleError(message(error))
      })

    return () => {
      mounted.current = false
    }
  }, [])

  const spentCents = budget.spent_today_cents
  const capCents = budget.daily_spend_cap_cents
  const remainingCents = budget.remaining_today_cents
  const ratio = capCents > 0 ? Math.min(1, Math.max(0, spentCents / capCents)) : 0
  const budgetLevel = ratio >= 0.9 ? 'danger' : ratio >= 0.75 ? 'warn' : null
  const recentPanels = panels?.slice(0, RECENT_PANEL_COUNT)
  const recentOutput = gallery?.slice(0, RECENT_OUTPUT_COUNT)

  return (
    <section className="dashboard" aria-label="Dashboard">
      <PageHeader
        title="Dashboard"
        description="Your comic workspace at a glance. Continue a panel or start the next shot."
        actions={(
          <Link to="/panels/new" className="btn btn--primary">
            <Icon name="sparkles" size={17} />
            Stage new panel
          </Link>
        )}
      />

      <div className="dashboard__overview">
        <section
          className={
            budgetLevel
              ? `dashboard-card dashboard-budget dashboard-budget--${budgetLevel}`
              : 'dashboard-card dashboard-budget'
          }
          aria-labelledby="dashboard-budget-title"
        >
          <div className="dashboard-card__heading">
            <span className="dashboard-card__icon">
              <Icon name="budget" size={18} />
            </span>
            <h2 id="dashboard-budget-title">Daily budget</h2>
          </div>
          <div className="dashboard-budget__figures">
            <strong>${(remainingCents / 100).toFixed(2)}</strong>
            <span>remaining today</span>
          </div>
          <div
            className="dashboard-budget__track"
            role="progressbar"
            aria-label="Dashboard daily spend"
            aria-valuemin={0}
            aria-valuemax={Math.max(1, capCents)}
            aria-valuenow={capCents > 0 ? Math.min(Math.max(0, spentCents), capCents) : 0}
            aria-valuetext={`$${(spentCents / 100).toFixed(2)} of $${(capCents / 100).toFixed(2)} spent`}
          >
            <span className="dashboard-budget__fill" style={{ width: `${ratio * 100}%` }} />
          </div>
          <p className="dashboard-budget__meta">
            ${(spentCents / 100).toFixed(2)} spent of ${(capCents / 100).toFixed(2)}
          </p>
          {refreshError && (
            <AsyncMessage kind="error" className="dashboard-card__message" title={refreshError}>
              Budget may be out of date
            </AsyncMessage>
          )}
        </section>

        <section className="dashboard-card dashboard-library" aria-labelledby="dashboard-library-title">
          <div className="dashboard-card__heading">
            <span className="dashboard-card__icon">
              <Icon name="characters" size={18} />
            </span>
            <h2 id="dashboard-library-title">Library</h2>
          </div>
          <div className="dashboard-library__stats">
            <Link
              to="/characters"
              className="dashboard-stat"
              aria-label={characters ? `${characters.length} Characters` : 'Loading Characters'}
            >
              <Icon name="characters" size={18} />
              <span>
                <strong>{characters ? characters.length : '...'}</strong>
                Characters
              </span>
            </Link>
            <Link
              to="/styles"
              className="dashboard-stat"
              aria-label={styles ? `${styles.length} Styles` : 'Loading Styles'}
            >
              <Icon name="styles" size={18} />
              <span>
                <strong>{styles ? styles.length : '...'}</strong>
                Styles
              </span>
            </Link>
          </div>
          {characterError && (
            <AsyncMessage kind="error" className="dashboard-card__message">
              Characters unavailable: {characterError}
            </AsyncMessage>
          )}
          {styleError && (
            <AsyncMessage kind="error" className="dashboard-card__message">
              Styles unavailable: {styleError}
            </AsyncMessage>
          )}
        </section>
      </div>

      <section className="dashboard-section" aria-labelledby="continue-working-title">
        <div className="dashboard-section__heading">
          <div>
            <h2 id="continue-working-title">Continue working</h2>
            <p>Pick up where you left off.</p>
          </div>
          <Link to="/panels" className="dashboard-section__link">
            View all panels <Icon name="chevronRight" size={16} />
          </Link>
        </div>

        {!panels && !panelError && <AsyncMessage kind="loading">Loading recent panels...</AsyncMessage>}
        {panelError && <AsyncMessage kind="error">Could not load panels: {panelError}</AsyncMessage>}
        {recentPanels && recentPanels.length === 0 && (
          <EmptyState
            icon="panels"
            title="No panels staged yet"
            description="Build your first shot from a character, style and scene direction."
            action={(
              <Link to="/panels/new" className="btn btn--primary">
                <Icon name="plus" size={16} />
                Stage first panel
              </Link>
            )}
          />
        )}
        {recentPanels && recentPanels.length > 0 && (
          <div className="dashboard-panels">
            {recentPanels.map((panel) => (
              <article key={panel.id} className="dashboard-panel">
                <div className="dashboard-panel__topline">
                  <span className={`badge ${panel.is_editable ? 'badge--draft' : 'badge--canonical'}`}>
                    {panel.is_editable ? 'Editable' : 'Locked'}
                  </span>
                  <span>Panel #{panel.id}</span>
                </div>
                <p className="dashboard-panel__beat">{panel.beat_text}</p>
                <p className="dashboard-panel__meta">
                  {panel.cast.length} cast / {panel.generation_count} attempt
                  {panel.generation_count === 1 ? '' : 's'}
                </p>
                <Link
                  to={panel.is_editable ? `/panels/${panel.id}/edit` : `/panels/${panel.id}/preview`}
                  className="dashboard-panel__action"
                >
                  {panel.is_editable ? 'Continue editing' : 'Open preview'}
                  <Icon name="chevronRight" size={15} />
                </Link>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="dashboard-section" aria-labelledby="recent-output-title">
        <div className="dashboard-section__heading">
          <div>
            <h2 id="recent-output-title">Recent output</h2>
            <p>Your latest accepted images.</p>
          </div>
          <Link to="/gallery" className="dashboard-section__link">
            Open gallery <Icon name="chevronRight" size={16} />
          </Link>
        </div>

        {!gallery && !galleryError && <AsyncMessage kind="loading">Loading recent output...</AsyncMessage>}
        {galleryError && <AsyncMessage kind="error">Could not load gallery: {galleryError}</AsyncMessage>}
        {recentOutput && recentOutput.length === 0 && (
          <EmptyState
            icon="gallery"
            title="No accepted images yet"
            description="Accepted generation candidates will collect here automatically."
            action={<Link to="/panels">Review panels</Link>}
            compact
          />
        )}
        {recentOutput && recentOutput.length > 0 && (
          <div className="dashboard-output">
            {recentOutput.map((item, index) => {
              const previewItem = recentOutput[previewIndex ?? index]
              return (
                <article key={item.candidate_id} className="dashboard-output__item">
                  <ImageDialog
                    src={item.content_url}
                    previewSrc={previewItem.content_url}
                    thumbnailAlt={`Accepted image from panel ${item.panel_id}`}
                    previewAlt={`Accepted image from panel ${previewItem.panel_id}, full-size preview`}
                    triggerLabel={`Preview accepted image from panel ${item.panel_id}`}
                    dialogLabel={`Accepted image from panel ${previewItem.panel_id}, larger preview`}
                    onPrevious={() =>
                      setPreviewIndex(
                        (current) => ((current ?? index) - 1 + recentOutput.length) % recentOutput.length,
                      )
                    }
                    onNext={() =>
                      setPreviewIndex((current) => ((current ?? index) + 1) % recentOutput.length)
                    }
                    onOpenChange={(open) => setPreviewIndex(open ? index : null)}
                  />
                  <Link to={`/panels/${item.panel_id}/preview`}>
                    Panel #{item.panel_id}
                  </Link>
                </article>
              )
            })}
          </div>
        )}
      </section>
    </section>
  )
}
