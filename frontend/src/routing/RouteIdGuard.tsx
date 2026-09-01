import type { ReactNode } from 'react'
import { NotFoundPage } from '../pages/NotFoundPage'
import { useRouteId } from './useRouteId'

export function RouteIdGuard({
  children,
  paramName = 'id',
}: {
  children: (id: number) => ReactNode
  paramName?: string
}) {
  const id = useRouteId(paramName)
  return id === null ? <NotFoundPage /> : children(id)
}
