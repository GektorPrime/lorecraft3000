import { Link } from 'react-router-dom'

const TILES = [
  { to: '/characters', code: 'CH', label: 'Characters' },
  { to: '/styles', code: 'ST', label: 'Styles' },
  { to: '/gallery', code: 'GA', label: 'Gallery' },
  { to: '/panels', code: 'PN', label: 'Panels' },
  { to: '/panels/new', code: '+', label: 'Stage New Panel' },
] as const

/**
 * Homepage (issue #15): the app brand ("LoreCraft3000") is rendered exactly
 * once, by the shared <Header> in App.tsx — the page body below must NOT
 * repeat it (a prior version duplicated the brand as this page's <h1>,
 * which is the bug being fixed here). This page still has its own
 * accessible <h1> for page structure, just with page-specific wording
 * instead of the brand name. Square navigation tiles use a plain
 * text/CSS badge (no emoji) per project convention.
 */
export function Home() {
  return (
    <section aria-label="Home">
      <h1>Home</h1>
      <p>Persistent, referenced comic-panel characters.</p>
      <nav className="tile-grid" aria-label="Main sections">
        {TILES.map((tile) => (
          <Link key={tile.to} to={tile.to} className="tile">
            <span className="tile__icon" aria-hidden="true">
              {tile.code}
            </span>
            <span>{tile.label}</span>
          </Link>
        ))}
      </nav>
    </section>
  )
}
