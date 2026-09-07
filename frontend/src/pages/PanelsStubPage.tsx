import { Link } from 'react-router-dom'
import { usePageTitle } from '../routing/usePageTitle'

export function PanelsStubPage() {
  usePageTitle('Panels')

  return (
    <section aria-labelledby="panels-stub-title">
      <h1 id="panels-stub-title">Panels</h1>
      <p>
        Panels are not here yet. In a future release you will compose your scenes
        into multi-scene panels.
      </p>
      <p>
        For now, return to <Link to="/">Dashboard</Link>.
      </p>
    </section>
  )
}
