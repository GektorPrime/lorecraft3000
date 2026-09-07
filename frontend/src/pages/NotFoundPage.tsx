import { Link } from 'react-router-dom'
import { usePageTitle } from '../routing/usePageTitle'

export function NotFoundPage() {
  usePageTitle('Page Not Found')

  return (
    <section aria-labelledby="not-found-title">
      <h1 id="not-found-title">Page not found</h1>
      <p>The page you requested does not exist or its address is invalid.</p>
      <p>
        Return <Link to="/">Home</Link>, or browse the{' '}
        <Link to="/characters">character collection</Link>,{' '}
        <Link to="/styles">style collection</Link>, or <Link to="/scenes">scene collection</Link>.
      </p>
    </section>
  )
}
