import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, listStyles } from '../../api/client'
import type { Style } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'

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
      <div className="btn-row list-page-header">
        <h1>Styles</h1>
        <Link to="/styles/new" className="btn btn--primary">
          New style
        </Link>
      </div>
      {error && <AsyncMessage kind="error">Could not load styles: {error}</AsyncMessage>}
      {!styles && !error && <AsyncMessage kind="loading">Loading styles…</AsyncMessage>}
      {styles && (
        <div className="stack-list">
          {styles.map((style) => (
            <div key={style.id} className="h-tile">
              <div className="h-tile__main">
                <h3 style={{ margin: 0 }}>{style.name}</h3>
                <p className="field__hint text-clamp" style={{ marginTop: '0.25rem' }}>
                  {style.style_contract || 'No style contract yet.'}
                </p>
              </div>
              <div className="h-tile__actions">
                <Link to={`/styles/${style.id}/edit`} className="btn">
                  Edit
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
