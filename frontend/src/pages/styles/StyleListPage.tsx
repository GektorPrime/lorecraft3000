import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, listStyles } from '../../api/client'
import type { Style } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'

export function StyleListPage() {
  const [styles, setStyles] = useState<Style[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listStyles()
      .then(setStyles)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [])

  return (
    <section>
      <PageHeader
        title="Styles"
        actions={(
          <Link to="/styles/new" className="btn btn--primary">
            <Icon name="plus" size={16} />
            New style
          </Link>
        )}
      />
      {error && <AsyncMessage kind="error">Could not load styles: {error}</AsyncMessage>}
      {!styles && !error && <AsyncMessage kind="loading">Loading styles…</AsyncMessage>}
      {styles && styles.length === 0 && (
        <EmptyState
          icon="styles"
          title="No styles yet"
          description="Define a visual contract before staging your first panel."
          action={(
            <Link to="/styles/new" className="btn btn--primary">
              <Icon name="plus" size={16} />
              New style
            </Link>
          )}
        />
      )}
      {styles && styles.length > 0 && (
        <div className="resource-list">
          {styles.map((style) => (
            <article key={style.id} className="resource-card">
              <div className="resource-card__body">
                <h2 className="resource-card__title">{style.name}</h2>
                <p className="resource-card__summary text-clamp" title={style.style_contract}>
                  {style.style_contract || 'No style contract yet.'}
                </p>
              </div>
              <div className="resource-card__actions">
                <Link to={`/styles/${style.id}/edit`} className="btn">
                  <Icon name="edit" size={15} />
                  Edit
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
