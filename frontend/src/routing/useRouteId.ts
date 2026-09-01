import { useParams } from 'react-router-dom'
import { parseRouteId } from './parseRouteId'

export function useRouteId(paramName = 'id'): number | null {
  return parseRouteId(useParams()[paramName])
}
